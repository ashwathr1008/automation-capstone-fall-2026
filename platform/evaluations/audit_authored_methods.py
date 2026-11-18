"""Posthoc sensitivity to explicit error-object rejection in authored methods.

Canonical scores, prompts, raw reports, and the frozen grader stay unchanged.
Uses the platform's existing restricted numerical runner, never model requests.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE / "platform" / "src"))
from lanm_platform.methods import execute_source

RULE_ID = "explicit_error_object_rejection_v1"
CHECK_ID = "saved_method_passes_independent_behavior_probes"
PROBES = [({"annual_cost_usd": 1000, "annual_output_kg": 4}, 250),
          ({"annual_cost_usd": 0, "annual_output_kg": 3}, 0),
          ({"annual_cost_usd": -1, "annual_output_kg": 2}, None),
          ({"annual_cost_usd": 100, "annual_output_kg": 0}, None),
          ({"annual_cost_usd": 100, "annual_output_kg": -1}, None)]


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def probe_method(method, executor=execute_source):
    probes = []
    for inputs, expected in PROBES:
        try:
            value = executor(method["source"], inputs)
            number = value.get("usd_per_kg") if isinstance(value, dict) else None
            passed = (finite(number) and abs(number - expected) < 1e-8) if expected is not None else (
                isinstance(value, dict) and bool(value.get("error")) and not finite(number))
            probes.append({"inputs": inputs, "expected_value": expected, "output": value,
                           "raised_error": None, "passes_explicit_error_object_policy": bool(passed)})
        except ValueError as exc:
            probes.append({"inputs": inputs, "expected_value": expected, "output": None,
                           "raised_error": str(exc).splitlines()[-1][:300] if str(exc) else "ValueError",
                           "passes_explicit_error_object_policy": expected is None})
        except Exception as exc:
            probes.append({"inputs": inputs, "expected_value": expected, "output": None,
                           "raised_error": f"{type(exc).__name__}: {exc}"[:300],
                           "passes_explicit_error_object_policy": False})
    return {"method_id": method["id"], "source_sha256": hashlib.sha256(method["source"].encode()).hexdigest(),
            "probes": probes, "passes_explicit_error_object_policy": all(p["passes_explicit_error_object_policy"] for p in probes)}


def strict_passed(row):
    checks = row.get("objective_checks", {}).get("checks", [])
    return row.get("status") == "completed" and bool(checks) and all(c.get("passed") is True for c in checks)


def audit_reports(reports, executor=execute_source):
    results, profiles, seen = [], defaultdict(lambda: {"attempted": 0, "strict_automated_passed": 0, "alternative_policy_passed": 0}), set()
    for filename, report in reports:
        if report.get("status") != "run_finished":
            raise ValueError(f"{filename}: only finished reports are eligible")
        for index, row in enumerate(report.get("results", [])):
            if row.get("category") != "objective_tool_contract" or row.get("status") in {"not_run", "prepared", "pending", "skipped", "unavailable"}:
                continue
            identity = (row["profile_id"], row["id"], row.get("repetition", 1))
            if identity in seen:
                raise ValueError(f"Duplicate attempt: {identity}")
            seen.add(identity)
            original, alternate = strict_passed(row), strict_passed(row)
            if row["id"] == "wf_build_method":
                checks = row.get("objective_checks", {}).get("checks", [])
                state = row.get("final_state", {})
                used_ids = {run.get("method_id") for run in state.get("runs", []) if run.get("kind") == "custom_calculation"}
                methods = [method for method in state.get("methods", []) if method.get("status") == "registered"
                           and method.get("id", "").startswith("evaluation-total-cost@") and method["id"] in used_ids]
                probes = [probe_method(method, executor) for method in methods]
                alternate = (row.get("status") == "completed" and any(c.get("id") == CHECK_ID for c in checks)
                             and all(c.get("passed") is True for c in checks if c.get("id") != CHECK_ID)
                             and bool(probes) and all(m["passes_explicit_error_object_policy"] for m in probes))
                results.append({"profile_id": row["profile_id"], "repetition": row.get("repetition", 1),
                                "source_report": str(filename), "source_result_index": index, "original_status": row.get("status"),
                                "canonical_checks": checks, "method_probes": probes, "canonical_task_passed": original,
                                "alternative_explicit_error_object_task_passed": alternate})
            profile = profiles[row["profile_id"]]
            profile["attempted"] += 1
            profile["strict_automated_passed"] += original
            profile["alternative_policy_passed"] += alternate
    changes = [{"profile_id": row["profile_id"], "repetition": row["repetition"], "canonical": row["canonical_task_passed"],
                "alternative": row["alternative_explicit_error_object_task_passed"]} for row in results
               if row["canonical_task_passed"] != row["alternative_explicit_error_object_task_passed"]]
    return {"schema_version": "1.0", "rule_id": RULE_ID, "status": "posthoc_grading_sensitivity_not_canonical",
            "policy": "For invalid inputs accept execution failure surfaced by execute_source as ValueError OR an object with nonempty error and no finite usd_per_kg. Valid held-out 1000/4=250 and 0/3=0 remain required. All other original task checks and completed status remain required.",
            "reason": "The task does not specify execution-failure versus error-object format. execute_source wraps any worker failure as ValueError; the frozen checker does not enforce the underlying exception type.",
            "original_reports_unchanged": True, "frozen_grader_unchanged": True, "changed_attempts": changes,
            "profile_sensitivity": dict(profiles), "audited_method_attempts": len(results), "results": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if not output.is_relative_to(WORKSPACE) or output.is_relative_to(WORKSPACE / "platform") or output.suffix != ".json":
        parser.error("Output must be JSON inside this workspace and outside platform/")
    if output.exists():
        parser.error("Use a new versioned output to preserve prior audit evidence")
    reports, sources = [], []
    for path in args.reports:
        raw = path.read_bytes()
        reports.append((path.name, json.loads(raw)))
        sources.append({"filename": path.name, "sha256": hashlib.sha256(raw).hexdigest()})
    try:
        result = audit_reports(reports)
    except ValueError as exc:
        parser.error(str(exc))
    result["source_reports"] = sources
    result["analysis_script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Audited {result['audited_method_attempts']} authored-method attempts; {len(result['changed_attempts'])} differ under the alternative policy: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
