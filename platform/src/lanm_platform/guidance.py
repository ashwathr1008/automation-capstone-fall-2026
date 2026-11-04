"""Bounded local LanM guidance, with deterministic selection and no network calls.

The catalog/read pattern is inspired by Biomni's know_how loader (Apache-2.0,
commit 400c1f366b96a35ca253e13c9b06c5076af41d65). This implementation and the
LanM handbook are original; no Biomni source or biomedical guides are copied.
"""

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
import re


_HEADING = re.compile(r"^## ([a-z][a-z0-9-]*) \| ([^\n]+)$", re.MULTILINE)
_LINK = re.compile(r"\[[^\]]+\]\((https://[^\s)]+)\)")
_STOP = frozenset("a an and are as at be by can do for from how i in is it lanm lanmodulin lanmodulins of on or that the their them these this to use using we what which with".split())


@dataclass(frozen=True)
class _Section:
    id: str
    title: str
    summary: str
    keywords: tuple[str, ...]
    text: str
    sources: tuple[str, ...]


def _field(text: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}: ([^\n]+)$", text, re.MULTILINE)
    if not match:
        raise ValueError(f"Handbook is missing {name}")
    return match.group(1).strip()


@lru_cache(maxsize=1)
def _load() -> tuple[str, str, tuple[_Section, ...]]:
    raw = files("lanm_platform").joinpath("data/lanm_handbook.md").read_bytes()
    if len(raw) > 12000:
        raise ValueError("Handbook exceeds the 12 KB limit")
    document = raw.decode("utf-8").replace("\r\n", "\n")
    headings = list(_HEADING.finditer(document))
    if not 1 <= len(headings) <= 12:
        raise ValueError("Handbook requires between 1 and 12 sections")
    header = document[:headings[0].start()]
    version, review = _field(header, "Version"), _field(header, "Review status")
    sections = []
    seen = set()
    for index, heading in enumerate(headings):
        identifier, title = heading.groups()
        if identifier in seen:
            raise ValueError("Duplicate handbook section")
        seen.add(identifier)
        end = headings[index + 1].start() if index + 1 < len(headings) else len(document)
        content = document[heading.end():end].strip()
        metadata, separator, body = content.partition("\n\n")
        summary = _field(metadata, "Summary")
        keywords = tuple(word.strip() for word in _field(metadata, "Keywords").split(","))
        if not separator or not body.strip() or len(summary) > 240 or len(title) > 120:
            raise ValueError("Invalid or oversized handbook section metadata")
        sources = tuple(dict.fromkeys(_LINK.findall(body)))
        sections.append(_Section(identifier, title, summary, keywords, body.strip(), sources))
    return version, review, tuple(sections)


def _summary(section: _Section) -> dict:
    return {"id": section.id, "title": section.title, "summary": section.summary,
            "keywords": list(section.keywords), "sources": list(section.sources)}


def catalog() -> list[dict]:
    """Return fresh, compact section metadata in stable handbook order."""
    return [_summary(section) for section in _load()[2]]


def read(section_id: str) -> dict:
    """Read one known ID. An ID is never used to construct a filesystem path."""
    if not isinstance(section_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,79}", section_id):
        raise ValueError("Unknown guidance section")
    version, review, sections = _load()
    for section in sections:
        if section.id == section_id:
            return {"id": section.id, "title": section.title, "text": section.text,
                    "sources": list(section.sources), "version": version,
                    "review_status": review}
    raise ValueError("Unknown guidance section")


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - _STOP


def select(query: str, limit: int = 3) -> list[dict]:
    """Select relevant summaries by lexical overlap, without claiming relevance calibration.

    No overlap returns an empty list. Ties retain handbook order. Query processing
    is bounded to 4,000 characters and results never contain full section text.
    """
    if not isinstance(query, str):
        raise ValueError("Guidance query must be text")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("Guidance limit must be a nonnegative integer")
    wanted = _tokens(query[:4000])
    ranked = []
    for index, section in enumerate(_load()[2]):
        score = (4 * len(wanted & _tokens(" ".join(section.keywords)))
                 + 2 * len(wanted & _tokens(section.title))
                 + len(wanted & _tokens(section.summary)))
        if score:
            ranked.append((-score, index, section))
    ranked.sort(key=lambda item: item[:2])
    return [_summary(section) for _, _, section in ranked[:limit]]
