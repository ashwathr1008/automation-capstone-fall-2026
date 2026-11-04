import io
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

from lanm_platform import pubmed


SEARCH = b'''<eSearchResult><Count>7</Count><IdList><Id>123</Id><Id>456</Id></IdList>
<QueryTranslation>lanmodulin[All Fields]</QueryTranslation></eSearchResult>'''
ARTICLES = b'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE PubmedArticleSet SYSTEM "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed.dtd">
<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>456</PMID><Article>
<ArticleTitle>Empty abstract</ArticleTitle><Journal><Title>Second Journal</Title>
<JournalIssue><PubDate><MedlineDate>2024 Nov-Dec</MedlineDate></PubDate></JournalIssue></Journal>
<PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
</Article></MedlineCitation></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>123</PMID><Article>
<ArticleTitle>Binding of <i>lanmodulin</i> to Nd<sup>3+</sup></ArticleTitle>
<Journal><Title>Test Journal</Title><JournalIssue><PubDate><Year>2025</Year><Month>04</Month></PubDate></JournalIssue></Journal>
<AuthorList><Author><LastName>Researcher</LastName><ForeName>Ada</ForeName></Author>
<Author><CollectiveName>LanM Consortium</CollectiveName></Author></AuthorList>
<Abstract><AbstractText Label="RESULTS" NlmCategory="RESULTS">Protein <i>A</i> binds Nd &amp; La.</AbstractText>
<AbstractText Label="LIMITATION">No <b>column</b> result.</AbstractText>
<CopyrightInformation>Test copyright notice</CopyrightInformation></Abstract>
<PublicationTypeList><PublicationType>Retracted Publication</PublicationType></PublicationTypeList>
</Article><CommentsCorrectionsList><CommentsCorrections RefType="RetractionIn"><PMID>789</PMID>
<RefSource>Notice journal</RefSource><Note>Retraction notice</Note></CommentsCorrections>
<CommentsCorrections RefType="ErratumIn"><PMID>790</PMID></CommentsCorrections></CommentsCorrectionsList>
</MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1234/test</ArticleId>
<ArticleId IdType="pmc">PMC123</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'''


class FakeTime:
    def __init__(self):
        self.now = 100.0
        self.waits = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


class PubMedTests(unittest.TestCase):
    def make_client(self, responses, **kwargs):
        responses = iter(responses)
        self.calls = []
        self.time = FakeTime()

        def opener(request, timeout):
            self.calls.append((request, timeout, self.time.now))
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return io.BytesIO(response)

        return pubmed.PubMedClient(opener=opener, limiter=pubmed._RateLimiter(self.time.clock, self.time.sleep),
                                   sleep=self.time.sleep, email="", api_key="", **kwargs)

    def test_search_retains_metadata_and_order_without_claiming_full_text(self):
        client = self.make_client([SEARCH, ARTICLES])
        result = client.search(" lanmodulin ", limit=2)
        self.assertEqual(result["total"], 7)
        self.assertEqual(result["translated_query"], "lanmodulin[All Fields]")
        self.assertEqual([row["pmid"] for row in result["articles"]], ["123", "456"])
        first, second = result["articles"]
        self.assertEqual(first["title"], "Binding of lanmodulin to Nd3+")
        self.assertEqual(first["authors"], ["Ada Researcher", "LanM Consortium"])
        self.assertEqual(first["abstract_sections"][0]["text"], "Protein A binds Nd & La.")
        self.assertIn("LIMITATION: No column result.", first["abstract"])
        self.assertEqual(first["year"], "2025")
        self.assertEqual(first["doi"], "10.1234/test")
        self.assertEqual(first["pmcid"], "PMC123")
        self.assertTrue(first["is_retracted"])
        self.assertEqual([notice["type"] for notice in first["notices"]], ["RetractionIn", "ErratumIn"])
        self.assertEqual(first["copyright_information"], "Test copyright notice")
        self.assertEqual(first["evidence_kind"], "literature_abstract")
        self.assertIn("no full text", first["content_scope"])
        self.assertTrue(first["retrieved_at"].endswith("Z"))
        self.assertFalse(second["has_abstract"])
        self.assertEqual(second["abstract"], "")
        self.assertEqual(second["year"], "2024")
        self.assertEqual(result["missing_pmids"], [])
        self.assertIn("not an exhaustive", result["provenance"]["coverage"])
        self.assertEqual(result["provenance"]["disclaimer_url"], pubmed.DISCLAIMER_URL)
        self.assertGreaterEqual(self.calls[1][2] - self.calls[0][2], 1.0)

    def test_empty_search_does_not_fetch_and_retains_ncbi_warning(self):
        client = self.make_client([b'<eSearchResult><Count>0</Count><IdList/><WarningList><OutputMessage>No items found.</OutputMessage></WarningList></eSearchResult>'])
        result = client.search("nonexistent")
        self.assertEqual(result["articles"], [])
        self.assertEqual(result["warnings"], ["No items found."])
        self.assertEqual(len(self.calls), 1)

    def test_missing_ids_are_reported_and_extra_records_not_returned(self):
        client = self.make_client([SEARCH.replace(b"456", b"999"), ARTICLES])
        result = client.search("lanmodulin")
        self.assertEqual(result["missing_pmids"], ["999"])
        self.assertEqual([row["pmid"] for row in result["articles"]], ["123"])

    def test_invalid_inputs_do_not_reach_network(self):
        client = self.make_client([])
        for query in ("", "  ", "x" * 2001, "x\x00y", None):
            with self.subTest(query=str(query)[:20]), self.assertRaises(ValueError):
                client.search(query)
        for limit in (0, 21, True, 2.5, "5"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                client.search("lanmodulin", limit)
        for ids in ([], ["1"] * 21, "123", [123], ["-1"], ["0"], ["123&db=pmc"]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                client.fetch(ids)
        with self.assertRaises(ValueError):
            client.search("lanmodulin", sort="arbitrary")
        self.assertEqual(self.calls, [])

    def test_parameters_are_encoded_and_secrets_stay_out_of_urls(self):
        client = self.make_client([SEARCH, ARTICLES])
        client.email, client.api_key = "contact@example.org", "test-secret"
        result = client.search("lanmodulin & Nd", sort="date")
        request, timeout, _ = self.calls[0]
        parameters = parse_qs(request.data.decode())
        self.assertEqual(parameters["term"], ["lanmodulin & Nd"])
        self.assertEqual(parameters["sort"], ["pub date"])
        self.assertEqual(parameters["api_key"], ["test-secret"])
        self.assertEqual(parameters["email"], ["contact@example.org"])
        self.assertEqual(timeout, 15)
        self.assertNotIn("test-secret", request.full_url)
        self.assertNotIn("contact@example.org", str(result))
        self.assertNotIn("test-secret", str(result))

    def test_retry_is_bounded_and_honors_retry_after(self):
        failure = lambda: HTTPError("https://example.invalid?api_key=secret", 429, "rate", {"Retry-After": "2"}, io.BytesIO(b""))
        client = self.make_client([failure(), ARTICLES])
        self.assertEqual(len(client.fetch(["123"])), 1)
        self.assertGreaterEqual(self.calls[1][2] - self.calls[0][2], 2)
        client = self.make_client([failure(), failure(), failure()])
        with self.assertRaisesRegex(pubmed.PubMedError, "HTTP 429") as caught:
            client.fetch(["123"])
        self.assertEqual(len(self.calls), 3)
        self.assertNotIn("secret", str(caught.exception))
        client = self.make_client([HTTPError("hidden", 503, "busy", {"Retry-After": "120"}, io.BytesIO(b""))])
        with self.assertRaisesRegex(pubmed.PubMedError, "longer retry delay"):
            client.fetch(["123"])
        self.assertEqual(len(self.calls), 1)

    def test_network_and_nonretryable_errors_do_not_expose_transport_urls(self):
        for failure in (URLError("url contains secret"), HTTPError("url contains secret", 400, "bad", {}, io.BytesIO(b""))):
            client = self.make_client([failure])
            with self.subTest(failure=type(failure)), self.assertRaises(pubmed.PubMedError) as caught:
                client.fetch(["123"])
            self.assertNotIn("secret", str(caught.exception))
            self.assertEqual(len(self.calls), 1)

    def test_xml_entities_oversized_and_malformed_responses_fail(self):
        examples = [b'<PubmedArticleSet', b'<ERROR>Unavailable</ERROR>', b'<html>error</html>',
                    b'<!DOCTYPE x [<!ENTITY e "expanded">]><PubmedArticleSet>&e;</PubmedArticleSet>',
                    b'x' * (pubmed.MAX_RESPONSE_BYTES + 1)]
        for raw in examples:
            client = self.make_client([raw])
            with self.subTest(raw=raw[:30]), self.assertRaises(pubmed.PubMedError):
                client.fetch(["123"])

    def test_book_and_doi_fallback(self):
        raw = b'''<PubmedArticleSet><PubmedBookArticle><BookDocument><PMID>1</PMID>
        <Book><BookTitle>Reference Book</BookTitle><PubDate><Year>2020</Year></PubDate></Book>
        <ArticleTitle>Chapter</ArticleTitle><Abstract><AbstractText>Chapter abstract</AbstractText></Abstract>
        <ELocationID EIdType="doi">10.1/chapter</ELocationID></BookDocument></PubmedBookArticle></PubmedArticleSet>'''
        result = self.make_client([raw]).fetch(["1", "1"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["journal"], "Reference Book")
        self.assertEqual(result[0]["doi"], "10.1/chapter")

    def test_shared_database_reserves_across_independent_clients(self):
        timer = FakeTime()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "research.sqlite3"
            limiter_a = pubmed._SqliteRateLimiter(path, timer.clock, timer.sleep)
            limiter_b = pubmed._SqliteRateLimiter(path, timer.clock, timer.sleep)
            times = []

            def opener(request, timeout):
                # A separate connection can write while transport runs: no lock
                # or transaction is retained across network operations.
                with closing(sqlite3.connect(path, timeout=0.1)) as db:
                    db.execute("CREATE TABLE IF NOT EXISTS unrelated (id INTEGER)")
                    db.execute("INSERT INTO unrelated VALUES (1)")
                    db.commit()
                times.append(timer.now)
                return io.BytesIO(ARTICLES)

            clients = [pubmed.PubMedClient(opener=opener, limiter=limiter, email="", api_key="")
                       for limiter in (limiter_a, limiter_b)]
            for client in (clients[0], clients[1], clients[0], clients[1]):
                client.fetch(["123"])
            self.assertTrue(all(second - first >= 0.399 for first, second in zip(times, times[1:])))
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM network_rate_limits").fetchone()[0], 1)

    def test_environment_is_optional_and_no_placeholder_contact_is_sent(self):
        with patch.dict("os.environ", {}, clear=True):
            client = pubmed.PubMedClient()
            self.assertEqual(client.email, "")
            self.assertEqual(client.api_key, "")
        with patch.dict("os.environ", {"NCBI_EMAIL": "configured@example.org", "NCBI_API_KEY": "configured-key"}, clear=True):
            client = pubmed.PubMedClient()
            self.assertEqual(client.email, "configured@example.org")
            self.assertEqual(client.api_key, "configured-key")


if __name__ == "__main__":
    unittest.main()
