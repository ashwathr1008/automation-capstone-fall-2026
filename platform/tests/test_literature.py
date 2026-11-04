"""Literature retrieval preserves traceability without becoming measurements."""
from copy import deepcopy
import hashlib
import http.client
from http.server import ThreadingHTTPServer
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from lanm_platform.core import Store
from lanm_platform.evidence import preview
from lanm_platform.mcp import definitions, dispatch
from lanm_platform.pubmed import CONTENT_SCOPE, DISCLAIMER_URL, PubMedError
from lanm_platform.server import Application, handler_for


def article_fixture(**changes):
    record = {
        "pmid": "900000001", "title": "Synthetic LanM literature fixture",
        "journal": "Fixture Journal", "year": "2025", "publication_date": "2025 01",
        "authors": ["Ada Researcher", "LanM Test Consortium"], "doi": "10.99999/lanm-test",
        "pmcid": "PMC900000001", "abstract": "Fixture only: equilibrium binding is not column capacity.",
        "abstract_sections": [{"label": "", "category": "", "text": "Fixture only: equilibrium binding is not column capacity."}],
        "has_abstract": True, "copyright_information": "Fixture copyright statement",
        "publication_types": ["Retracted Publication"], "is_retracted": True,
        "notices": [{"type": "RetractionIn", "pmid": "900000002", "note": "Fixture retraction", "source": "Fixture Journal"}],
        "url": "https://pubmed.ncbi.nlm.nih.gov/900000001/", "retrieved_at": "2026-11-03T12:00:00Z",
        "evidence_kind": "literature_abstract", "content_scope": CONTENT_SCOPE,
    }
    return {**record, **changes}


def search_fixture(article=None, query="lanmodulin", retrieved_at="2026-11-03T12:00:00Z"):
    article = article_fixture() if article is None else article
    return {
        "query": query, "translated_query": query + "[All Fields]", "total": 5,
        "pmids": [article["pmid"]], "articles": [article], "missing_pmids": [], "warnings": [],
        "provenance": {"provider": "NCBI PubMed E-utilities", "retrieved_at": retrieved_at,
                       "sort": "relevance", "limit": 5, "search_url": "https://pubmed.ncbi.nlm.nih.gov/?term=lanmodulin",
                       "content_scope": CONTENT_SCOPE, "disclaimer_url": DISCLAIMER_URL,
                       "coverage": "PubMed is not an exhaustive index of REE process engineering."},
    }


class LiteratureIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.pid = self.store.create_project("Literature tests", "Nd", "La")["id"]
        self.patcher = patch("lanm_platform.pubmed.PubMedClient")
        self.client_type = self.patcher.start()
        self.client = self.client_type.return_value
        self.client.search.return_value = search_fixture()
        self.client.fetch.return_value = [article_fixture()]

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def own_sources(self, project_id=None):
        return [source for source in self.store.list_sources(project_id or self.pid)
                if source.get("project_id") == (project_id or self.pid)]

    def test_search_archives_identifiers_abstract_notices_and_query_provenance(self):
        result = self.store.search_pubmed(self.pid, "lanmodulin", limit=5)
        self.client_type.assert_called_once_with(rate_limit_path=self.store.db_path)
        self.client.search.assert_called_once_with("lanmodulin", limit=5, sort="relevance")
        returned = result["articles"][0]
        source = self.own_sources()[0]
        self.assertEqual(returned["source_id"], source["id"])
        self.assertEqual(returned["source_sha256"], hashlib.sha256(source["text"].encode()).hexdigest())
        self.assertEqual(source["evidence_kind"], "retrieved_literature_abstract")
        self.assertEqual(source["url"], article_fixture()["url"])
        self.assertEqual(source["provenance"]["doi"], "10.99999/lanm-test")
        self.assertEqual(source["provenance"]["authors"], ["Ada Researcher", "LanM Test Consortium"])
        self.assertTrue(source["provenance"]["is_retracted"])
        self.assertIn("RetractionIn", source["text"])
        self.assertIn("The full article has not been retrieved", source["text"])
        self.assertIn("equilibrium binding is not column capacity", source["text"])
        self.assertNotIn("abstract", source["provenance"])
        history = self.store.list_literature_searches(self.pid)
        self.assertEqual(history[0]["id"], result["search_id"])
        self.assertEqual(history[0]["translated_query"], "lanmodulin[All Fields]")
        self.assertEqual(history[0]["total"], 5)
        self.assertEqual(history[0]["records"][0]["source_id"], source["id"])
        saved_record = history[0]["records"][0]
        self.assertEqual(saved_record["journal"], "Fixture Journal")
        self.assertEqual(saved_record["year"], "2025")
        self.assertTrue(saved_record["has_abstract"])
        self.assertTrue(saved_record["is_retracted"])
        self.assertEqual(saved_record["notices"], article_fixture()["notices"])
        self.assertIn("no full text", history[0]["provenance"]["content_scope"])
        self.assertEqual(history[0]["provenance"]["retrieved_at"], "2026-11-03T12:00:00Z")
        excerpt = self.store.read_source(self.pid, source["id"], query="equilibrium")
        self.assertTrue(excerpt["hash_verified"])
        self.assertIn("equilibrium", excerpt["excerpt"])
        citation_only = article_fixture(abstract="", abstract_sections=[], has_abstract=False)
        self.client.search.return_value = search_fixture(citation_only)
        self.store.search_pubmed(self.pid, "lanmodulin")
        self.assertFalse(self.store.list_literature_searches(self.pid)[0]["records"][0]["has_abstract"])

    def test_doi_and_pubmed_citations_resolve_to_saved_abstract_preview(self):
        article = self.store.fetch_pubmed(self.pid, ["900000001"])["articles"][0]
        for url in (article["url"], "https://doi.org/10.99999/lanm-test"):
            with self.subTest(url=url):
                result = preview(self.store, self.pid, url=url)
                self.assertEqual(result["source_id"], article["source_id"])
                self.assertTrue(result["available"])
                self.assertEqual(result["preview_kind"], "text")
                self.assertTrue(result["hash_verified"])

    def test_repeat_retrieval_retains_one_immutable_source_and_separate_search_history(self):
        first = self.store.search_pubmed(self.pid, "lanmodulin")
        self.client.search.return_value = search_fixture(article_fixture(retrieved_at="2026-11-04T12:00:00Z"),
                                                         retrieved_at="2026-11-04T12:00:00Z")
        second = self.store.search_pubmed(self.pid, "lanmodulin")
        self.assertEqual(first["articles"][0]["source_id"], second["articles"][0]["source_id"])
        self.assertNotEqual(first["search_id"], second["search_id"])
        self.assertEqual(len(self.own_sources()), 1)
        self.assertEqual(self.own_sources()[0]["provenance"]["retrieved_at"], "2026-11-03T12:00:00Z")
        history = self.store.list_literature_searches(self.pid)
        self.assertEqual([row["provenance"]["retrieved_at"] for row in history],
                         ["2026-11-04T12:00:00Z", "2026-11-03T12:00:00Z"])
        reopened = Store(self.temp.name)
        self.assertEqual(reopened.list_literature_searches(self.pid), history)

    def test_updated_abstract_is_archived_as_separate_evidence(self):
        first = self.store.fetch_pubmed(self.pid, ["900000001"])["articles"][0]
        self.client.fetch.return_value = [article_fixture(abstract="Fixture corrected abstract; uncertainty remains.")]
        second = self.store.fetch_pubmed(self.pid, ["900000001"])["articles"][0]
        self.assertNotEqual(first["source_id"], second["source_id"])
        self.assertNotEqual(first["source_sha256"], second["source_sha256"])
        self.assertEqual(len(self.own_sources()), 2)

    def test_long_and_empty_titles_have_bounded_labels_without_losing_originals(self):
        long_title = "Synthetic fixture title " * 40
        self.client.fetch.return_value = [article_fixture(title=long_title),
                                         article_fixture(pmid="900000002", title="", url="https://pubmed.ncbi.nlm.nih.gov/900000002/")]
        result = self.store.fetch_pubmed(self.pid, ["900000001", "900000002"])
        sources = {source["id"]: source for source in self.own_sources()}
        first, second = [sources[article["source_id"]] for article in result["articles"]]
        self.assertLessEqual(len(first["title"]), 500)
        self.assertIn(long_title, first["text"])
        self.assertEqual(first["provenance"]["title"], long_title)
        self.assertEqual(result["articles"][0]["title"], long_title)
        self.assertEqual(second["title"], "PubMed record 900000002")
        self.assertEqual(second["provenance"]["title"], "")
        self.assertEqual(result["missing_pmids"], [])

    def test_sources_and_search_history_are_project_scoped(self):
        result = self.store.search_pubmed(self.pid, "lanmodulin")
        other = self.store.create_project("Other literature project", "Dy", "Nd")["id"]
        self.assertEqual(self.store.list_literature_searches(other), [])
        self.assertEqual(self.own_sources(other), [])
        self.assertFalse(preview(self.store, other, url=article_fixture()["url"])["available"])
        second = self.store.search_pubmed(other, "lanmodulin")
        self.assertNotEqual(result["articles"][0]["source_id"], second["articles"][0]["source_id"])
        self.assertEqual(len(self.store.list_literature_searches(self.pid)), 1)
        self.assertEqual(self.store.list_literature_searches(other)[0]["project_id"], other)

    def test_retrieval_never_changes_assumptions_experiments_or_existing_run_validity(self):
        self.store.update_assumptions(self.pid, {"usable_lifetime_cycles": 70}, "Explicit test scenario")
        run = self.store.calculate(self.pid)
        before = deepcopy(self.store.get_project(self.pid))
        self.store.search_pubmed(self.pid, "lanmodulin")
        self.store.fetch_pubmed(self.pid, ["900000001"])
        self.assertEqual(self.store.get_project(self.pid), before)
        self.assertFalse(self.store.get_run(self.pid, run["id"])["stale"])
        self.assertEqual(self.store.get_candidate("o-36", self.pid)["experiments"], [])

    def test_network_failure_keeps_scientific_state_sources_and_history_intact(self):
        self.store.search_pubmed(self.pid, "lanmodulin")
        before = (self.store.get_project(self.pid), self.own_sources(), self.store.list_literature_searches(self.pid))
        self.client.search.side_effect = PubMedError("Could not reach PubMed")
        self.client.fetch.side_effect = PubMedError("Could not reach PubMed")
        for operation in (lambda: self.store.search_pubmed(self.pid, "Nd LanM"),
                          lambda: self.store.fetch_pubmed(self.pid, ["900000001"])):
            with self.assertRaisesRegex(PubMedError, "Could not reach"):
                operation()
            self.assertEqual((self.store.get_project(self.pid), self.own_sources(), self.store.list_literature_searches(self.pid)), before)

    def test_nonexistent_project_is_rejected_before_network_call(self):
        for operation in (lambda: self.store.search_pubmed("missing", "lanmodulin"),
                          lambda: self.store.fetch_pubmed("missing", ["900000001"]),
                          lambda: self.store.list_literature_searches("missing")):
            with self.assertRaisesRegex(ValueError, "Project not found"):
                operation()
        self.client_type.assert_not_called()

    def test_mcp_modes_expose_archive_mutations_and_dispatch_guidance_and_search(self):
        for build in (False, True):
            tools = {tool["name"]: tool for tool in definitions(build)}
            for name in ("search_pubmed", "fetch_pubmed"):
                self.assertFalse(tools[name]["annotations"]["readOnlyHint"])
                self.assertTrue(tools[name]["annotations"]["openWorldHint"])
            self.assertTrue(tools["list_literature_searches"]["annotations"]["readOnlyHint"])
            result = dispatch(self.store, None, "search_pubmed", {"project_id": self.pid, "query": "lanmodulin"}, build)
            history = dispatch(self.store, None, "list_literature_searches", {"project_id": self.pid}, build)
            self.assertEqual(history[0]["id"], result["search_id"])
            fetched = dispatch(self.store, None, "fetch_pubmed", {"project_id": self.pid, "pmids": ["900000001", "900000009"]}, build)
            self.assertEqual(fetched["articles"][0]["source_id"], result["articles"][0]["source_id"])
            self.assertEqual(fetched["missing_pmids"], ["900000009"])
            sections = dispatch(self.store, None, "list_guidance", {}, build)
            section = dispatch(self.store, None, "read_guidance", {"section_id": sections[0]["id"]}, build)
            self.assertTrue(section["text"])
            self.assertTrue(section["sources"])
            self.assertIn("review_status", section)

    def test_http_retrieval_history_and_preview_use_same_project_sources(self):
        app = Application(self.temp.name)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(app))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)

        def request(method, path, body=None):
            connection.request(method, path, body=json.dumps(body) if body is not None else None,
                               headers={"Content-Type": "application/json"} if body is not None else {})
            response = connection.getresponse()
            payload = json.loads(response.read())
            self.assertEqual(response.status, 200, payload)
            return payload

        try:
            prefix = f"/api/projects/{self.pid}"
            result = request("POST", prefix + "/pubmed/search", {"query": "lanmodulin", "limit": 5})
            source_id = result["articles"][0]["source_id"]
            history = request("GET", prefix + "/literature-searches")
            self.assertEqual(history[0]["records"][0]["source_id"], source_id)
            fetched = request("POST", prefix + "/pubmed/fetch", {"pmids": ["900000001", "900000009"]})
            self.assertEqual(fetched["missing_pmids"], ["900000009"])
            previewed = request("GET", prefix + "/evidence-preview?" + urlencode({"url": "https://doi.org/10.99999/lanm-test"}))
            self.assertEqual(previewed["source_id"], source_id)
            self.assertEqual(previewed["preview_kind"], "text")
            sections = request("GET", "/api/guidance")["sections"]
            section = request("GET", "/api/guidance/" + sections[0]["id"])
            self.assertEqual(section["id"], sections[0]["id"])
            self.assertTrue(section["sources"])
            self.assertEqual(self.store.get_project(self.pid)["accepted_experiment_count"], 0)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.close()


if __name__ == "__main__":
    unittest.main()
