"""One-way, content-checked import of the reviewed Week 3 evidence seed.

The compact asset preserves exact source candidate records, including raw assay
replicates and cautions. No synthetic experiment becomes accepted project data.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ASSET = Path(__file__).parent / "data" / "candidates.json.gz"


def build_asset(source: str | Path, destination: str | Path = ASSET) -> dict:
    source = Path(source)
    raw = source.read_bytes()
    original = json.loads(raw)
    candidates = original.get("candidates", [])
    if len(candidates) != 616 or len({row["id"] for row in candidates}) != 616:
        raise ValueError("Expected all 616 distinct reviewed candidate records")
    package = {"schema_version": "lanm_library_1", "origin": "Reviewed Week 3 seed",
               "origin_sha256": hashlib.sha256(raw).hexdigest(),
               "origin_schema_version": original.get("schema_version"),
               "candidates": candidates, "sources": original.get("sources", []),
               "contexts": original.get("contexts", []), "assertions": original.get("assertions", []),
               "formulas": original.get("formulas", []), "dataset_notes": original.get("dataset_notes", []),
               "interpretation": "Published screening library; no accepted in-house experiment or validated process economics is implied."}
    encoded = json.dumps(package, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(gzip.compress(encoded, mtime=0))
    return {"path": str(destination), "candidate_count": len(candidates),
            "source_sha256": package["origin_sha256"], "asset_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "compressed_bytes": destination.stat().st_size}


def load_asset(path: str | Path = ASSET) -> dict:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError("The packaged candidate library is missing: " + str(path))
    data = json.loads(gzip.decompress(path.read_bytes()))
    candidates = data.get("candidates", [])
    if data.get("schema_version") != "lanm_library_1" or len({row["id"] for row in candidates}) != len(candidates):
        raise ValueError("Invalid packaged candidate library")
    return data


def _file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_legacy_context(store, project_id: str, legacy_root: str | Path) -> dict:
    """Archive a small historical handoff, without activating legacy assumptions.

    legacy_root is the old workspace or its Week_3 folder. Closed SQLite
    snapshots are opened immutable/read-only; full originals remain authoritative.
    Repeating this operation against identical inputs reuses the source record.
    """
    store.get_project(project_id)
    root = Path(legacy_root).expanduser().resolve()
    week = root / "Week_3" if (root / "Week_3").is_dir() else root
    if not week.is_dir():
        raise ValueError("Legacy Week_3 directory does not exist")
    source_ids = {row["id"] for row in load_asset().get("sources", [])}
    snapshots, sources, presenter = [], {}, None
    for relative in ("data/tea_research.sqlite3", "outputs/live_demo/chat.sqlite3", "outputs/presenter_app/chat.sqlite3"):
        path = (week / relative).resolve()
        if not path.is_relative_to(week):
            raise ValueError("Legacy database path escapes the specified directory")
        if not path.is_file():
            continue
        before = _file_digest(path)
        db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        db.row_factory = sqlite3.Row
        try:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required = {"candidates", "sources", "contexts", "assertions", "formulas", "events", "selected_values"}
            if not required <= tables:
                raise ValueError("Legacy database lacks expected scientific tables: " + relative)
            counts = {name: db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
                      for name in ("candidates", "sources", "contexts", "assertions", "formulas")}
            event_counts = dict(db.execute("SELECT kind,COUNT(*) FROM events GROUP BY kind"))
            all_assertions = [json.loads(row[0]) for row in db.execute("SELECT payload FROM assertions")]
            measured = sum(row.get("tier") == "measured" or row.get("evidence_kind") == "in_house_measurement" for row in all_assertions)
            synthetic_reports = [row for row in all_assertions if row.get("evidence_kind") == "hypothetical_user_report"]
            snapshots.append({"relative_path": "Week_3/" + relative, "original_absolute_path": str(path),
                              "sha256": before, "byte_count": path.stat().st_size, "record_counts": counts,
                              "event_counts": event_counts, "measured_assertion_count": measured,
                              "hypothetical_user_reports": [{key: row.get(key) for key in ("id", "context_id", "parameter", "value", "unit", "tier", "evidence_kind")}
                                                            for row in synthetic_reports]})
            for record in db.execute("SELECT payload FROM sources"):
                row = json.loads(record[0])
                if row["id"] in source_ids or row.get("visibility") == "private" or row.get("origin") == "user_upload":
                    continue
                if not str(row.get("url", "")).startswith(("https://", "http://")):
                    continue
                metadata = {key: row[key] for key in ("id", "title", "url", "doi", "path", "sha256", "text_path", "text_sha256", "retrieved_on") if key in row}
                signature = json.dumps(metadata, sort_keys=True, ensure_ascii=False)
                item = sources.setdefault(signature, {"original_metadata": metadata, "seen_in": []})
                item["seen_in"].append("Week_3/" + relative)
            if relative == "outputs/presenter_app/chat.sqlite3":
                found = db.execute("SELECT payload FROM contexts WHERE id=?", ("provisional_o36_economics",)).fetchone()
                if found:
                    context = json.loads(found[0])
                    selected = {row[0] for row in db.execute("SELECT assertion_id FROM selected_values WHERE context_id=?", (context["id"],))}
                    rows = [json.loads(row[0]) for row in db.execute("SELECT payload FROM assertions WHERE context_id=? ORDER BY seq", (context["id"],))]
                    formulas = [json.loads(row[0]) for row in db.execute("SELECT payload FROM formulas WHERE context_id=? ORDER BY seq", (context["id"],))]
                    presenter = {
                        "context": context,
                        "active_input_assertions": [row for row in rows if row["id"] in selected and row.get("tier") != "calculated"],
                        "prior_input_assertions": [row for row in rows if row["id"] not in selected and row.get("tier") != "calculated"],
                        "historical_calculated_outputs": [row for row in rows if row["id"] in selected and row.get("tier") == "calculated"],
                        "formula_references": formulas,
                        "interpretation": "Historical provisional Pr/La agarose scenario for o-36. User-selected lifetime is an assumption, not observed reuse. Historical estimated capacity transfer and price claims are retained verbatim, not independently endorsed or imported as current parameters.",
                    }
        finally:
            db.close()
        if _file_digest(path) != before:
            raise ValueError("Legacy database changed during inspection; retry against a closed snapshot")
    if not snapshots:
        raise ValueError("No expected Week_3 main/live/presenter databases were found")
    package = {"schema": "lanm_legacy_context_1", "status": "historical_reference_only",
               "notice": "This is a compact handoff from archived Week 3 databases. It does not change this project's current assumptions, mark candidates tested, or create/accept experiments. Full original databases retain complete conversations, provenance and outputs. Historical scientific assertions remain subject to their original limitations.",
               "snapshots": snapshots, "presenter_provisional_scenario": presenter,
               "additional_public_source_metadata": list(sources.values())}
    text = json.dumps(package, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(text.encode("utf-8")) > 25000:
        raise ValueError("Historical handoff exceeds 25 KB; review selection rather than silently truncate evidence")
    result = store.add_source(project_id, "Week 3 historical context — provisional scenarios and source metadata", text)
    return {"source_id": result["id"], "project_id": project_id, "sha256": result["sha256"],
            "text_bytes": len(text.encode("utf-8")), "database_count": len(snapshots),
            "additional_source_count": len(sources), "presenter_context_preserved": presenter is not None,
            "current_assumptions_changed": False, "experiments_created": 0,
            "interpretation": "Historical reference source only; no evidence was promoted to a measurement or active scenario."}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "import-legacy":
        from .core import Store
        parser = argparse.ArgumentParser(description="Archive a compact historical Week 3 handoff without activating it")
        parser.add_argument("--data-dir", required=True)
        parser.add_argument("--project-id", required=True)
        parser.add_argument("--legacy-root", required=True)
        args = parser.parse_args(sys.argv[2:])
        print(json.dumps(import_legacy_context(Store(args.data_dir), args.project_id, args.legacy_root), indent=2))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("source")
        parser.add_argument("--destination", default=str(ASSET))
        args = parser.parse_args()
        print(json.dumps(build_asset(args.source, args.destination), indent=2))
