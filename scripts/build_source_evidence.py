"""Bundle only source files referenced by the current application's library.

Original source paths and bytes are preserved so existing provenance hashes and
evidence links keep working. Old application code, databases, slides, and other
unreferenced archive contents are never copied. The input archive is unchanged.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "platform" / "src" / "lanm_platform" / "data"
MANIFEST = "_source_evidence_manifest.json"
ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".ipynb", ".jpg", ".png", ".jpeg", ".json", ".txt", ".csv", ".md", ".html", ".htm"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_records(library: Path, database: Path | None = None) -> list[dict]:
    with gzip.open(library, "rt", encoding="utf-8") as stream:
        records = list(json.load(stream).get("sources", []))
    if database is not None:
        # URI read-only mode prevents accidental database creation or updates.
        with closing(sqlite3.connect(database.resolve(strict=True).as_uri() + "?mode=ro", uri=True)) as db:
            records.extend(json.loads(row[0]) for row in db.execute("SELECT payload FROM library_records WHERE kind='sources'"))
            records.extend(json.loads(row[0]) for row in db.execute("SELECT payload FROM sources"))
    return records


def collect_references(records: list[dict]) -> dict[str, dict]:
    references: dict[str, dict] = {}
    for record in records:
        if "text" in record:
            continue  # Current project sources with inline text need no ZIP.
        for field, hash_field in (("path", "sha256"), ("text_path", "text_sha256")):
            if not record.get(field):
                continue
            name = str(record[field]).replace("\\", "/")
            path = PurePosixPath(name)
            lowered = name.lower()
            if path.is_absolute() or ".." in path.parts or ":" in name or "\x00" in name:
                raise ValueError("Unsafe source-evidence path: " + name)
            if path.suffix.lower() not in ALLOWED_EXTENSIONS or any(
                word in lowered for word in ("presentation", "slide", "powerpoint", "speaker_notes", ".venv/", "__pycache__/")
            ):
                raise ValueError("Reference is not a permitted source-evidence asset: " + name)
            expected = record.get(hash_field)
            if not isinstance(expected, str) or len(expected) != 64 or any(character not in "0123456789abcdefABCDEF" for character in expected):
                raise ValueError("Missing or invalid recorded source hash: " + name)
            expected = expected.lower()
            item = references.setdefault(name, {"sha256": expected, "source_ids": set(), "roles": set()})
            if item["sha256"] != expected:
                raise ValueError("Conflicting recorded hashes for source: " + name)
            item["source_ids"].add(str(record.get("id", "")))
            item["roles"].add("original" if field == "path" else "extracted_text")
    if not references:
        raise ValueError("No external source-evidence references were found")
    return references


def verify_bundle(path: Path) -> dict:
    with zipfile.ZipFile(path) as package:
        names = package.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Evidence bundle has duplicate member paths")
        manifest = json.loads(package.read(MANIFEST))
        records = manifest["files"]
        if set(names) != {row["path"] for row in records} | {MANIFEST}:
            raise ValueError("Evidence bundle differs from its manifest")
        for row in records:
            data = package.read(row["path"])
            if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("Source-evidence integrity check failed: " + row["path"])
    return {"source_files": len(records), "uncompressed_bytes": sum(row["bytes"] for row in records)}


def build_evidence(source: Path, output: Path, library: Path, database: Path | None = None, force: bool = False) -> dict:
    source = source.resolve(strict=True)
    output = output.resolve()
    if source == output or (output.exists() and os.path.samefile(source, output)):
        raise ValueError("Source archive and output must be different files")
    if output.exists() and not force:
        raise FileExistsError("Output already exists; pass --force to replace the evidence bundle")
    references = collect_references(source_records(library, database))
    source_hash = sha256_file(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="build-evidence-", dir=output.parent) as temporary:
        prepared = Path(temporary) / "source-evidence.zip"
        entries = []
        with zipfile.ZipFile(source) as incoming, zipfile.ZipFile(prepared, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as outgoing:
            for name, reference in sorted(references.items()):
                matches = [info for info in incoming.infolist() if info.filename == name]
                if len(matches) != 1 or matches[0].is_dir():
                    raise ValueError("Required source member is missing or ambiguous: " + name)
                data = incoming.read(matches[0])
                if hashlib.sha256(data).hexdigest() != reference["sha256"]:
                    raise ValueError("Source differs from the application's recorded hash: " + name)
                if data.startswith(b"SQLite format 3\x00") or (
                    data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
                    and PurePosixPath(name).suffix.lower() != ".xlsx"
                ):
                    raise ValueError("Database or nested archive content is not source evidence: " + name)
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                outgoing.writestr(info, data, compresslevel=9)
                entries.append({
                    "path": name, "bytes": len(data), "sha256": reference["sha256"],
                    "source_ids": sorted(reference["source_ids"]), "roles": sorted(reference["roles"]),
                })
            manifest = {
                "format": "lanm-source-evidence-v1",
                "description": "Only source assets referenced by the current library and project source metadata. Original paths and bytes are preserved for evidence verification.",
                "source_archive_sha256": source_hash,
                "library_sha256": sha256_file(library),
                "files": entries,
            }
            info = zipfile.ZipInfo(MANIFEST, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            outgoing.writestr(info, json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", compresslevel=9)
        if sha256_file(source) != source_hash:
            raise RuntimeError("Input archive changed during evidence export")
        result = verify_bundle(prepared)
        result.update({"output": str(output), "bytes": prepared.stat().st_size, "sha256": sha256_file(prepared), "original_archive_unchanged": True})
        if output.exists() and not force:
            raise FileExistsError("Output was created during export; refusing to overwrite it")
        os.replace(prepared, output)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "archive" / "weeks1-3.zip")
    parser.add_argument("--output", type=Path, default=DATA / "source-evidence.zip")
    parser.add_argument("--library", type=Path, default=DATA / "candidates.json.gz")
    default_database = ROOT / "research-data" / "research.sqlite3"
    parser.add_argument("--database", type=Path, default=default_database if default_database.is_file() else None)
    parser.add_argument("--force", action="store_true", help="Replace the generated evidence bundle")
    args = parser.parse_args()
    print(json.dumps(build_evidence(args.source, args.output, args.library, args.database, args.force), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
