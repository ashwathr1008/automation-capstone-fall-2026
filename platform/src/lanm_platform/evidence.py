"""Resolve citations to saved evidence and read verified local preview files.

No external URLs are fetched. Original files stay inside a local evidence ZIP;
project and reviewed shared text snapshots are retained in the database.
HTML and SVG are never served as active content from the application origin.
"""
from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit
import zipfile

from .config import source_archive

MAX_FILE_BYTES = 50_000_000
_TRACKING = {"fbclid", "gclid", "mc_cid", "mc_eid"}
_TYPES = {
    ".pdf": ("pdf", "application/pdf"),
    ".png": ("image", "image/png"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".txt": ("text", "text/plain; charset=utf-8"),
    ".csv": ("text", "text/plain; charset=utf-8"),
    ".md": ("text", "text/plain; charset=utf-8"),
    ".json": ("unsupported", "application/json"),
    ".ipynb": ("unsupported", "application/json"),
    ".xlsx": ("unsupported", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
}


def _url_parts(url):
    if not isinstance(url, str) or not url or len(url) > 8192:
        raise ValueError("Supply an HTTP(S) source URL")
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Supply an HTTP(S) source URL without embedded credentials")
    # Reading .port also rejects malformed port strings.
    port = parsed.port
    host = parsed.hostname.lower()
    if port and port not in {80, 443}:
        host += ":" + str(port)
    path = unquote(parsed.path).rstrip("/") or "/"
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in _TRACKING]
    return parsed, host, path, urlencode(sorted(query))


def _url_keys(url):
    if not url:
        return set()
    try:
        parsed, host, path, query = _url_parts(url)
    except ValueError:
        return set()
    keys = {"url:" + host + path + ("?" + query if query else "")}
    if host in {"doi.org", "dx.doi.org"} and re.fullmatch(r"/10\.\d{4,9}/\S+", path, re.I):
        keys.add("doi:" + path[1:].casefold())
    if host in {"www.nature.com", "nature.com"}:
        match = re.fullmatch(r"/articles/([^/]+?)(?:\.pdf)?", path)
        if match:
            keys.add("nature:" + match.group(1))
    if host in {"pmc.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov"}:
        match = re.fullmatch(r"/(?:pmc/)?articles/(PMC\d+)(?:/pdf/[^/]+\.pdf)?", path, re.I)
        if match:
            keys.add("pmc:" + match.group(1).upper())
    return keys


def _current_matches(sources):
    """Prefer a matching successor without replacing unrelated source records."""
    ids = {source.get("id") for source in sources}
    current = [source for source in sources
               if source.get("origin") != "reviewed_shared_evidence"
               or not ids.intersection(source.get("superseded_by_source_ids", []))]
    # A newly shared excerpt must not displace an existing primary document.
    # Preserve the order among project/imported records and among shared records.
    return sorted(current or sources, key=lambda source: source.get("origin") == "reviewed_shared_evidence")


def _source_doi(source):
    provenance = source.get("provenance", {})
    original = provenance.get("record_snapshot", {})
    return str(source.get("doi") or provenance.get("doi")
               or original.get("doi") or original.get("provenance", {}).get("doi", "")).casefold()


def _source(store, project_id, source_id=None, url=None):
    sources = store.list_sources(project_id)
    if source_id:
        found = next((row for row in sources if row.get("id") == source_id), None)
        if found is None:
            raise ValueError("Source not found in this project or the shared library")
        return found
    _url_parts(url)
    requested = _url_keys(url)
    # An exact artifact URL always wins over the shared parent-paper DOI.
    exact = _current_matches([row for row in sources if any(key.startswith("url:") for key in requested & _url_keys(row.get("url")))])
    if exact:
        return exact[0]
    aliases = _current_matches([row for row in sources if requested & _url_keys(row.get("url"))])
    if aliases:
        return aliases[0]
    dois = {key[4:] for key in requested if key.startswith("doi:")}
    matches = _current_matches([row for row in sources if _source_doi(row) in dois])
    primary = [(row, _url_keys(row.get("url"))) for row in matches]
    # Dataset and supplement records can carry the same DOI. Prefer an actual
    # primary article URL, and preserve ambiguity when no primary is identified.
    for prefix in ("nature:", "pmc:"):
        article = [row for row, keys in primary if any(key.startswith(prefix) for key in keys)]
        original = [row for row in article if row.get("origin") != "reviewed_shared_evidence"]
        if original:
            article = original
        if len(article) == 1:
            return article[0]
    return matches[0] if len(matches) == 1 else None


def _archive(store):
    return source_archive(store.data_dir)


def _member(source):
    member = str(source.get("path", "")).replace("\\", "/")
    path = PurePosixPath(member)
    if not member or path.is_absolute() or ".." in path.parts or ":" in member or "\x00" in member:
        raise ValueError("No safe relative original-file path is recorded for this source")
    return member, path


def _file_details(source):
    if "text" in source:
        filename = re.sub(r"[^A-Za-z0-9._-]", "_", str(source["id"]))[:170] + ".txt"
        return "text", "text/plain; charset=utf-8", filename
    _, path = _member(source)
    if path.suffix.lower() not in _TYPES:
        raise ValueError("This original file type is not offered for inline preview or download; use its archived text or linked original")
    kind, mime = _TYPES[path.suffix.lower()]
    filename = re.sub(r"[^A-Za-z0-9._ -]", "_", path.name)[:180]
    return kind, mime, filename


def _read_original(store, source):
    kind, mime, filename = _file_details(source)
    if "text" in source:
        if not isinstance(source["text"], str):
            raise ValueError("Archived source text must be UTF-8 text")
        raw = source["text"].encode("utf-8")
    else:
        member, _ = _member(source)
        archive = _archive(store)
        if not archive.is_file():
            raise ValueError("The original source archive is unavailable")
        try:
            with zipfile.ZipFile(archive) as package:
                matches = [item for item in package.infolist() if item.filename == member]
                if len(matches) != 1 or matches[0].is_dir():
                    raise ValueError("The expected original file is missing or ambiguous in the archive")
                if matches[0].file_size > MAX_FILE_BYTES:
                    raise ValueError("The original file exceeds the 50 MB preview limit")
                raw = package.read(matches[0])
        except (OSError, zipfile.BadZipFile, RuntimeError) as error:
            raise ValueError("The original source could not be read: " + str(error)) from error
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("The original file exceeds the 50 MB preview limit")
    expected = source.get("sha256")
    if not expected or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Original source failed its recorded SHA-256 integrity check")
    if kind == "pdf" and b"%PDF-" not in raw[:1024]:
        raise ValueError("The archived file is not recognizable as a PDF")
    if mime == "image/png" and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("The archived file is not recognizable as a PNG")
    if mime == "image/jpeg" and not raw.startswith(b"\xff\xd8\xff"):
        raise ValueError("The archived file is not recognizable as a JPEG")
    if kind == "text":
        try:
            raw.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("The original text is not supported UTF-8") from error
    return raw, mime, filename


def read_original(store, project_id, source_id):
    """Return verified bytes, MIME type and a header-safe filename.

    The HTTP layer must use attachment disposition for types other than PDF,
    PNG, JPEG and plain text. Spreadsheets/notebooks are explicit downloads.
    """
    return _read_original(store, _source(store, project_id, source_id=source_id))


def preview(store, project_id, url=None, source_id=None):
    source = _source(store, project_id, source_id=source_id, url=url)
    result = {"source": None, "source_id": None, "title": "External source", "url": url or "",
              "available": False, "preview_kind": "unavailable", "file_name": None,
              "mime_type": None, "original_available": False, "text_available": False, "hash_verified": False}
    if source is None:
        return {**result, "reason": "This citation has no unambiguous saved source in this project. You can open its original website explicitly or archive its text for preview."}
    metadata = {key: value for key, value in source.items() if key != "text"}
    # Shared snapshots retain their original record for traceability. Do not
    # duplicate its potentially large text in a metadata-only preview response.
    provenance = metadata.get("provenance")
    if isinstance(provenance, dict) and isinstance(provenance.get("record_snapshot"), dict):
        metadata["provenance"] = {**provenance, "record_snapshot": {
            key: value for key, value in provenance["record_snapshot"].items() if key != "text"}}
    result.update(source=metadata,
                  source_id=source["id"], title=source.get("title", source["id"]), url=source.get("url") or url or "")
    original_error = None
    try:
        kind, _, _ = _file_details(source)
        raw, mime, filename = _read_original(store, source)
        result.update(original_available=True, file_name=filename, mime_type=mime, hash_verified=True)
        if kind in {"pdf", "image"}:
            result.update(available=True, preview_kind=kind)
    except ValueError as error:
        original_error = str(error)
    text = store.read_source(project_id, source["id"], limit=1)
    result["text_available"] = text["status"] == "available"
    if not result["available"] and result["text_available"]:
        result.update(available=True, preview_kind="text", hash_verified=text["hash_verified"])
    if not result["available"]:
        result["reason"] = original_error or "This file can be downloaded explicitly, but no in-app rendering or archived text is available."
    elif original_error:
        result["original_reason"] = original_error
    return result
