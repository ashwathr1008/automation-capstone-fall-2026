"""Prepare anonymous answer/evidence packets with empty human review fields.

Use only finished reports. The separate key retains model and source identity;
the reviewer packet hides identities, timings, and automatic check outcomes.
It never assigns scientific or answer-quality scores.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random

WORKSPACE = Path(__file__).resolve().parents[2]
RUBRIC = [
    {"id": "instruction_fidelity", "question": "Does the answer fulfill the requested scope and accurately describe what was done?",
     "major_error": "Claims an action was done when evidence shows otherwise, or changes the requested scope."},
    {"id": "quantitative_correctness", "question": "Are reported values, units, arithmetic, and causal explanations consistent with the supplied inputs and tool results?",
     "major_error": "Wrong value, unit, direction, or explanation that changes the interpretation."},
    {"id": "evidence_fidelity", "question": "Are claims supported by the archived evidence, with conflicting sources and citations represented faithfully?",
     "major_error": "Invented evidence, unsupported citation, or conflation of incompatible source conditions."},
    {"id": "uncertainty_and_boundaries", "question": "Does the answer distinguish observations from assumptions, predictions, and unvalidated methods?",
     "major_error": "Presents a scenario or model output as established physical performance or scientific validation."},
    {"id": "usability", "question": "Can a researcher follow the answer and identify the saved artifact or the required next decision?",
     "major_error": "Missing or misleading action, artifact identifier, or link prevents the requested use."},
]


def _canonical_result(result):
    # Normalize a JSON object carried inside MCP's textual content wrapper.
    # Keep mixed/binary/non-JSON payloads intact; never rewrite the evidence.
    if isinstance(result, dict) and isinstance(result.get("content"), list):
        content = result["content"]
        if len(content) == 1 and isinstance(content[0], dict) and content[0].get("type") == "text":
            try:
                return json.loads(content[0]["text"])
            except (KeyError, ValueError, TypeError):
                pass
    return result


def _tool_evidence(trace):
    return [{"tool": str(entry.get("name", "")).rsplit("__", 1)[-1],
             "arguments": entry.get("arguments"), "result": _canonical_result(entry.get("result")),
             "error": entry.get("error")}
            for entry in trace if entry.get("type") == "tool_call"]


def _public_item(row, review_id):
    turns = row.get("turns") or [row]
    conversation = [{"turn": index + 1, "prompt": turn.get("prompt") or row.get("prompt") or row.get("question"),
                     "answer": turn.get("answer", ""), "tool_evidence": _tool_evidence(turn.get("trace", []))}
                    for index, turn in enumerate(turns)]
    initial = row.get("initial_state", row.get("initial_project"))
    final = row.get("final_state", row.get("final_project"))
    return {"review_id": review_id, "task": row["id"], "conversation": conversation,
            "reference_material": {"fixture_context": row.get("fixture_context"), "initial_state": initial,
                                   "final_state": final},
            "review": {"reviewer_id": None, "completed_at": None, "potential_deblinding": None,
                       "ratings": {criterion["id"]: {"rating": None, "evidence": None, "notes": None} for criterion in RUBRIC},
                       "unverifiable_claims": [], "major_errors": [], "overall_notes": None}}


def prepare_packet(reports, *, repetition=1, seed=20261118, allow_unmatched=False):
    if isinstance(repetition, bool) or not isinstance(repetition, int) or repetition < 1:
        raise ValueError("repetition must be a positive integer")
    rows, seen, source_info, profile_cases = [], set(), [], {}
    for source, report in reports:
        if report.get("status") != "run_finished":
            raise ValueError(f"{source}: only finished reports may be read into a review packet")
        source_info.append({"path": str(source), "result_count": len(report.get("results", []))})
        for row in report.get("results", []):
            if row.get("repetition", 1) != repetition or row.get("category") != "objective_tool_contract":
                continue
            if row.get("status") in {"not_run", "prepared", "pending", "skipped", "unavailable"}:
                continue
            identity = (row.get("profile_id"), row.get("id"), repetition)
            if not identity[0] or not identity[1] or identity in seen:
                raise ValueError(f"Missing identity or duplicate review attempt: {identity}")
            seen.add(identity)
            profile_cases.setdefault(identity[0], set()).add(identity[1])
            rows.append((str(source), row))
    if not rows:
        raise ValueError("No attempted objective tasks exist for the selected repetition")
    coverage = {tuple(sorted(cases)) for cases in profile_cases.values()}
    if len(coverage) > 1 and not allow_unmatched:
        raise ValueError("Profiles have unmatched task coverage; select matched reports or explicitly allow unmatched review")
    items, key = [], {}
    for source, row in sorted(rows, key=lambda value: (value[1]["profile_id"], value[1]["id"])):
        identity = json.dumps([seed, row["profile_id"], row["id"], repetition])
        review_id = "review-" + hashlib.sha256(identity.encode()).hexdigest()[:12]
        items.append(_public_item(row, review_id))
        key[review_id] = {"profile_id": row["profile_id"], "model": row.get("model"), "task": row["id"],
                          "repetition": repetition, "source_report": source, "status": row.get("status"),
                          "objective_checks": row.get("objective_checks")}
    random.Random(seed).shuffle(items)
    packet = {"schema_version": "1.0", "created_at": datetime.now(timezone.utc).isoformat(),
              "review_status": "unreviewed", "item_count": len(items), "configuration_count": len(profile_cases),
              "rubric": RUBRIC,
              "rating_scale": {"0": "Major error; cite the exact conflicting answer and evidence.",
                               "1": "Partly adequate; a minor error or omission needs correction.",
                               "2": "Meets the criterion within the supplied evidence and task scope.",
                               "N/A": "Criterion is not applicable to this task.",
                               "unverifiable": "Necessary reference evidence is missing; do not guess.",
                               "null": "Not reviewed yet; never treat as zero."},
              "instructions": [
                  "Review the exact answer against the user request and supplied archived evidence. Record evidence for every rating.",
                  "Keep this packet separate from review-key.json; do not consult model identity, timings, or automatic grades while rating.",
                  "Use two independent reviewers for major errors, then reconcile disagreements with quoted evidence.",
                  "A successful tool execution is not proof that the answer is true. Distinguish requested state from reported claims.",
                  "These tasks use synthetic fixtures. Judge consistency with the provided scenario, not real-world LanM validity.",
                  "Do not infer a scientific accuracy score or combine ordinal ratings into an unvalidated composite.",
                  "Source text is preserved. Style, self-identification, or platform artifacts may reveal identity; note potential deblinding.",
                  "Empty answers and incomplete attempts remain reviewable; an omitted attempt is never invented as a failure.",
              ], "items": items}
    private = {"schema_version": "1.0", "seed": seed, "selected_repetition": repetition,
               "sampling_rule": "Same prespecified repetition for every available task/configuration; no outcome-based selection.",
               "allow_unmatched": allow_unmatched, "source_reports": source_info,
               "profile_item_counts": dict(sorted(Counter(row["profile_id"] for _, row in rows).items())), "key": key}
    return packet, private


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--repetition", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20261118)
    parser.add_argument("--allow-unmatched", action="store_true")
    args = parser.parse_args(argv)
    destination = args.output_dir.expanduser().resolve()
    if not destination.is_relative_to(WORKSPACE) or destination.is_relative_to(WORKSPACE / "platform"):
        parser.error("Review output must be inside this workspace and outside platform/")
    paths = [destination / name for name in ("review-packet.json", "review-key.json")]
    if any(path.exists() for path in paths):
        parser.error("Use a new output directory to preserve any existing human ratings")
    reports, hashes = [], {}
    for path in args.reports:
        path = path.expanduser().resolve()
        raw = path.read_bytes()
        reports.append((str(path), json.loads(raw)))
        hashes[str(path)] = hashlib.sha256(raw).hexdigest()
    try:
        packet, key = prepare_packet(reports, repetition=args.repetition, seed=args.seed, allow_unmatched=args.allow_unmatched)
    except ValueError as exc:
        parser.error(str(exc))
    for source in key["source_reports"]:
        source["sha256"] = hashes[source["path"]]
    destination.mkdir(parents=True, exist_ok=True)
    for path, data in zip(paths, (packet, key)):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Prepared {packet['item_count']} unreviewed items from {packet['configuration_count']} configurations in {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
