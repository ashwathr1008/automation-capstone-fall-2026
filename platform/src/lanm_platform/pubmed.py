"""Small, bounded NCBI E-utilities adapter for citations and abstracts.

Independently implemented after reviewing Biomni's PubMed MCP example; no
Biomni code or dependencies are included. See NOTICE.md for the reference.
PubMed is a biomedical index, not an exhaustive REE engineering bibliography.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import os
import re
import sqlite3
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
DISCLAIMER_URL = "https://www.ncbi.nlm.nih.gov/About/disclaimer.html"
MAX_RESULTS = 20
MAX_RESPONSE_BYTES = 2_000_000
MAX_RETRY_WAIT = 30
CONTENT_SCOPE = "PubMed citation and abstract; no full text retrieved"
_PMID = re.compile(r"[1-9][0-9]{0,11}\Z")


class PubMedError(ValueError):
    """A bounded public-service request failed; safe to display without secrets."""


class _RateLimiter:
    def __init__(self, clock=time.monotonic, sleep=time.sleep):
        self.clock, self.sleep = clock, sleep
        self.next_request = 0.0
        self.lock = threading.Lock()

    def wait(self):
        # One request per second per process leaves room for the app's two
        # Research/Build MCP processes within NCBI's 3 requests/second/IP limit.
        # Larger deployments need a shared limiter across workers and hosts.
        with self.lock:
            delay = self.next_request - self.clock()
            if delay > 0:
                self.sleep(delay)
            self.next_request = self.clock() + 1.05


_RATE = _RateLimiter()


class _SqliteRateLimiter:
    """Coordinate all app workers through the existing research database."""

    def __init__(self, path, clock=time.time, sleep=time.sleep):
        self.path, self.clock, self.sleep = path, clock, sleep
        with closing(sqlite3.connect(path, timeout=10)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS network_rate_limits (service TEXT PRIMARY KEY, next_request REAL NOT NULL)")
            db.commit()

    def wait(self):
        with closing(sqlite3.connect(self.path, timeout=10, isolation_level=None)) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT next_request FROM network_rate_limits WHERE service='pubmed_eutilities'").fetchone()
            reserved = max(self.clock(), row[0] if row else 0)
            db.execute("INSERT OR REPLACE INTO network_rate_limits VALUES('pubmed_eutilities', ?)", (reserved + 0.4,))
            db.commit()
        # No database transaction spans either a sleep or a network request.
        delay = reserved - self.clock()
        if delay > 0:
            self.sleep(delay)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(element):
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def _ids(pmids):
    if not isinstance(pmids, (list, tuple)) or not 1 <= len(pmids) <= MAX_RESULTS:
        raise ValueError(f"Supply a list of 1 to {MAX_RESULTS} PMID strings")
    if any(not isinstance(pmid, str) or not _PMID.fullmatch(pmid) for pmid in pmids):
        raise ValueError("PMIDs must be positive decimal identifier strings")
    return list(dict.fromkeys(pmids))


def _parse_xml(raw):
    if len(raw) > MAX_RESPONSE_BYTES:
        raise PubMedError("PubMed response exceeded the 2 MB limit; request fewer records")
    try:
        # E-utilities supplies UTF-8. Reject entity declarations before parsing;
        # ElementTree does not fetch the normal external PubMed DTD.
        source = raw.decode("utf-8-sig")
        if "<!ENTITY" in source.upper():
            raise PubMedError("PubMed response contained unsupported XML entities")
        root = ET.fromstring(source)
    except (UnicodeDecodeError, ET.ParseError):
        raise PubMedError("PubMed returned an unreadable XML response") from None
    if root.tag == "ERROR" or root.find(".//ERROR") is not None:
        raise PubMedError("NCBI reported an error; check the query or identifiers and retry")
    return root


def _retry_after(value):
    if not value:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            seconds = (parsed - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    if not 0 <= seconds <= MAX_RETRY_WAIT:
        # Do not retry sooner than a long server-requested wait. Let the caller
        # decide when to try again instead of blocking the conversation.
        if seconds > MAX_RETRY_WAIT:
            raise PubMedError("NCBI requested a longer retry delay; try again later")
        return 0
    return seconds


def _article(node, retrieved_at):
    citation = node.find("MedlineCitation")
    book = citation is None
    if book:
        citation = node.find("BookDocument")
    if citation is None:
        return None
    pmid = _text(citation.find("PMID"))
    if not _PMID.fullmatch(pmid):
        raise PubMedError("PubMed returned an invalid record identifier")
    article = citation if book else citation.find("Article")
    if article is None:
        raise PubMedError("PubMed returned an incomplete citation")
    date = article.find("Book/PubDate" if book else "Journal/JournalIssue/PubDate")
    publication_date = " ".join(_text(part) for part in date) if date is not None else ""
    year_match = re.search(r"\b[12][0-9]{3}\b", publication_date)
    if year_match is None:
        year_match = re.search(r"\b[12][0-9]{3}\b", _text(article.find("ArticleDate/Year")))
    authors = []
    for author in article.findall("AuthorList/Author"):
        name = _text(author.find("CollectiveName"))
        if not name:
            given = _text(author.find("ForeName")) or _text(author.find("Initials"))
            name = " ".join(part for part in (given, _text(author.find("LastName")), _text(author.find("Suffix"))) if part)
        if name:
            authors.append(name)
    sections = [{"label": item.get("Label", ""), "category": item.get("NlmCategory", ""), "text": _text(item)}
                for item in article.findall("Abstract/AbstractText")]
    identifiers = {item.get("IdType", "").lower(): _text(item)
                   for item in node.findall("./PubmedBookData/ArticleIdList/ArticleId" if book else "./PubmedData/ArticleIdList/ArticleId")}
    doi = identifiers.get("doi", "") or next((_text(item) for item in article.findall("ELocationID") if item.get("EIdType") == "doi"), "")
    notices = [{"type": item.get("RefType", ""), "pmid": _text(item.find("PMID")),
                "note": _text(item.find("Note")), "source": _text(item.find("RefSource"))}
               for item in citation.findall("CommentsCorrectionsList/CommentsCorrections")]
    publication_types = [_text(item) for item in article.findall("PublicationTypeList/PublicationType")]
    return {
        "pmid": pmid, "title": _text(article.find("ArticleTitle")),
        "journal": _text(article.find("Book/BookTitle" if book else "Journal/Title")),
        "year": year_match.group() if year_match else "", "publication_date": publication_date,
        "authors": authors, "doi": doi, "pmcid": identifiers.get("pmc", ""),
        "abstract": "\n\n".join((part["label"] + ": " if part["label"] else "") + part["text"] for part in sections),
        "abstract_sections": sections, "has_abstract": any(part["text"] for part in sections),
        "copyright_information": _text(article.find("Abstract/CopyrightInformation")),
        "publication_types": publication_types, "notices": notices,
        "is_retracted": "Retracted Publication" in publication_types or any(item["type"] == "RetractionIn" for item in notices),
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "retrieved_at": retrieved_at,
        "evidence_kind": "literature_abstract", "content_scope": CONTENT_SCOPE,
    }


class PubMedClient:
    def __init__(self, *, opener=None, limiter=None, sleep=time.sleep, timeout=15,
                 email=None, api_key=None, rate_limit_path=None):
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 30:
            raise ValueError("PubMed timeout must be between 0 and 30 seconds")
        self.opener = opener or urlopen
        self.limiter = limiter or (_SqliteRateLimiter(rate_limit_path) if rate_limit_path is not None else _RATE)
        self.sleep, self.timeout = sleep, timeout
        # Only explicitly configured contact information is sent. Never infer a
        # user's email from Git identity, browser state, or other local files.
        self.email = os.environ.get("NCBI_EMAIL", "") if email is None else email
        self.api_key = os.environ.get("NCBI_API_KEY", "") if api_key is None else api_key

    def _request(self, endpoint, parameters):
        parameters = {"db": "pubmed", "retmode": "xml", "tool": "LanMResearch", **parameters}
        if self.email:
            parameters["email"] = self.email
        if self.api_key:
            parameters["api_key"] = self.api_key
        # POST keeps credentials and queries out of URLs and ordinary URL logs.
        request = Request(BASE_URL + endpoint, data=urlencode(parameters).encode("utf-8"),
                          headers={"User-Agent": "LanMResearch/0.1", "Accept": "application/xml"})
        for attempt in range(3):
            self.limiter.wait()
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                return _parse_xml(raw)
            except HTTPError as error:
                status = error.code
                retry_value = error.headers.get("Retry-After") if error.headers else None
                error.close()
                if status not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise PubMedError(f"PubMed request failed (HTTP {status}); try again later") from None
                delay = _retry_after(retry_value)
                self.sleep(delay if delay is not None else 0.5 * 2 ** attempt)
            except (URLError, OSError, TimeoutError):
                raise PubMedError("Could not reach PubMed within the request timeout; try again later") from None

    def search(self, query, limit=5, sort="relevance"):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000 or any(ord(char) < 32 for char in query):
            raise ValueError("Supply a PubMed query of 1 to 2000 characters without control characters")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
            raise ValueError(f"PubMed result limit must be an integer from 1 to {MAX_RESULTS}")
        if not isinstance(sort, str) or sort not in {"relevance", "date"}:
            raise ValueError("PubMed sort must be relevance or date")
        query = query.strip()
        root = self._request("esearch.fcgi", {"term": query, "retmax": limit, "sort": "pub date" if sort == "date" else "relevance"})
        if root.tag != "eSearchResult":
            raise PubMedError("PubMed returned an unexpected search response")
        total = _text(root.find("Count"))
        if not total.isdecimal():
            raise PubMedError("PubMed response did not include a valid result count")
        raw_ids = [_text(item) for item in root.findall("IdList/Id")]
        if len(raw_ids) > limit:
            raise PubMedError("PubMed returned more identifiers than requested")
        pmids = _ids(raw_ids) if raw_ids else []
        articles = self.fetch(pmids) if pmids else []
        found = {article["pmid"] for article in articles}
        warnings = [_text(item) for path in ("WarningList/*", "ErrorList/*") for item in root.findall(path)]
        return {
            "query": query, "translated_query": _text(root.find("QueryTranslation")), "total": int(total),
            "pmids": pmids, "articles": articles, "missing_pmids": [pmid for pmid in pmids if pmid not in found],
            "warnings": warnings,
            "provenance": {"provider": "NCBI PubMed E-utilities", "retrieved_at": _now(), "sort": sort,
                           "limit": limit, "search_url": "https://pubmed.ncbi.nlm.nih.gov/?" + urlencode({"term": query}),
                           "content_scope": CONTENT_SCOPE, "disclaimer_url": DISCLAIMER_URL,
                           "coverage": "PubMed is not an exhaustive index of REE separation or process engineering literature."},
        }

    def fetch(self, pmids):
        pmids = _ids(pmids)
        root = self._request("efetch.fcgi", {"id": ",".join(pmids)})
        if root.tag != "PubmedArticleSet":
            raise PubMedError("PubMed returned an unexpected article response")
        retrieved_at = _now()
        records = {}
        for node in root:
            article = _article(node, retrieved_at)
            if article is not None and article["pmid"] in pmids:
                records[article["pmid"]] = article
        return [records[pmid] for pmid in pmids if pmid in records]


def search(query, limit=5, sort="relevance"):
    """Search PubMed and fetch up to 20 citation/abstract records, without saving."""
    return PubMedClient().search(query, limit, sort)


def fetch(pmids):
    """Fetch 1–20 explicit PMIDs in request order; unavailable IDs are omitted."""
    return PubMedClient().fetch(pmids)
