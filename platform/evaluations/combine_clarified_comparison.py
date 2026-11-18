"""Derive a separate comparison replacing only the ambiguous authored-method task."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
ORIGINAL_CASE = "wf_build_method"
CLARIFIED_CASE = "wf_build_method_clarified"
CORRECTION_ID = "authored_method_contract_clarification_v1"
NOT_ATTEMPTED = {"not_run", "prepared", "pending", "skipped", "unavailable"}


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def row_hash(row):
    return hashlib.sha256(json_bytes(row)).hexdigest()


def _verify_frozen_controls(original_sources, clarified_sources):
    role_values = {}
    fields = ("harness_sha256", "objective_cases_sha256", "workflow_implementation_sha256",
              "scientific_runner_sha256", "implementation_sha256")
    for role, sources in (("original", original_sources), ("clarified", clarified_sources)):
        for field in fields:
            values = [source["frozen_hashes"].get(field) for source in sources]
            if any(not value for value in values) or len({json_bytes(value) for value in values}) != 1:
                raise ValueError(f"Missing or differing {role} {field}")
            role_values[(role, field)] = values[0]
    for field in ("workflow_implementation_sha256", "scientific_runner_sha256", "implementation_sha256"):
        if role_values[("original", field)] != role_values[("clarified", field)]:
            raise ValueError(f"Original and clarified {field} differ")
    for source in clarified_sources:
        if source["frozen_hashes"].get("base_harness_sha256") != role_values[("original", "harness_sha256")]:
            raise ValueError("Clarified base_harness_sha256 differs from original harness")


def _collect(reports, role, repeats, timeout_seconds):
    rows, profiles, sources = {}, {}, []
    for source, report, digest in reports:
        if report.get("status") != "run_finished":
            raise ValueError(f"{source}: only finished reports may be combined")
        if report.get("repeat") != repeats or report.get("timeout_seconds") != timeout_seconds:
            raise ValueError(f"{source}: declared repeat/deadline differs from the planned {repeats} x {timeout_seconds}s")
        if report.get("analysis_correction"):
            raise ValueError(f"{source}: input must be raw, not already corrected")
        clarification = report.get("clarification", {})
        if role == "clarified" and (clarification.get("original_case_id") != ORIGINAL_CASE
                                    or clarification.get("case_id") != CLARIFIED_CASE
                                    or not clarification.get("prompt_sha256")):
            raise ValueError(f"{source}: missing or mismatched clarified-prompt provenance")
        if role == "clarified" and (not isinstance(clarification.get("prompt"), str)
                or hashlib.sha256(clarification["prompt"].encode("utf-8")).hexdigest() != clarification["prompt_sha256"]):
            raise ValueError(f"{source}: clarified prompt text hash mismatch")
        declared = {profile["id"]: profile for profile in report.get("profiles", [])}
        sources.append({"role": role, "path": str(source), "sha256": digest,
                        "raw_result_count": len(report.get("results", [])), "suite_id": report.get("suite_id"),
                        "created_at": report.get("created_at"), "clarification": report.get("clarification"),
                        "repeat": report.get("repeat"), "timeout_seconds": report.get("timeout_seconds"),
                        "frozen_hashes": {key: value for key, value in report.items() if key.endswith("_sha256")},
                        "local_tool_allowlist": report.get("local_tool_allowlist", []),
                        "build_tool_allowlist": report.get("build_tool_allowlist", [])})
        for index, row in enumerate(report.get("results", [])):
            if row.get("category") != "objective_tool_contract" or row.get("status") in NOT_ATTEMPTED:
                raise ValueError(f"{source}: every row must be an attempted objective workflow")
            if row.get("status") not in {"completed", "error", "timeout", "cancelled", "incomplete"}:
                raise ValueError(f"{source}: unrecognized terminal attempt status")
            profile, case, repetition = row.get("profile_id"), row.get("id"), row.get("repetition", 1)
            if not profile or not case or not isinstance(repetition, int) or isinstance(repetition, bool):
                raise ValueError(f"{source}: invalid profile/case/repetition")
            if role == "clarified" and case != CLARIFIED_CASE:
                raise ValueError(f"{source}: unexpected clarified case {case!r}")
            if role == "clarified" and row.get("prompt_sha256") != clarification["prompt_sha256"]:
                raise ValueError(f"{source}: row prompt hash differs from clarified prompt")
            if role == "clarified" and (row.get("prompt") != clarification["prompt"]
                    or row.get("original_case_id") != ORIGINAL_CASE or row.get("checker_case_id") != ORIGINAL_CASE):
                raise ValueError(f"{source}: row prompt text or checker identity differs")
            key = (profile, case, repetition)
            if key in rows:
                raise ValueError(f"Duplicate {role} attempt: {key}")
            if profile not in declared:
                raise ValueError(f"{source}: missing recorded profile {profile}")
            if profile in profiles and profiles[profile] != declared[profile]:
                raise ValueError(f"{profile}: recorded profile differs within {role} inputs")
            if row.get("model") and declared[profile].get("model") and row["model"] != declared[profile]["model"]:
                raise ValueError(f"{profile}: row model differs from profile")
            profiles[profile] = deepcopy(declared[profile])
            origin = {"role": role, "source_report": str(source), "source_sha256": digest,
                      "source_result_index": index, "source_row_sha256": row_hash(row),
                      "profile_id": profile, "case_id": case, "repetition": repetition}
            rows[key] = (row, origin)
    return rows, profiles, sources


def combine_reports(original_reports, clarified_reports, *, repeats=3, expected_workflows=16, timeout_seconds=300, correction_plan=None):
    """Inputs contain triples (source name, parsed report, raw-file SHA256)."""
    if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1:
        raise ValueError("repeats must be positive")
    if correction_plan:
        plan = correction_plan.get("contents", {})
        if (plan.get("correction_id") != CORRECTION_ID or plan.get("original_case_id") != ORIGINAL_CASE
                or plan.get("clarified_case_id") != CLARIFIED_CASE or plan.get("repetitions") != repeats):
            raise ValueError("Correction plan does not match the replacement rule")
    originals, profiles, original_sources = _collect(original_reports, "original", repeats, timeout_seconds)
    clarified, replacements, clarified_sources = _collect(clarified_reports, "clarified", repeats, timeout_seconds)
    if not originals or set(profiles) != set(replacements):
        raise ValueError("Inputs must contain the same nonempty configuration set")
    if correction_plan and not set(profiles).issubset(set(correction_plan["contents"].get("configuration_ids", []))):
        raise ValueError("Input configuration is outside the prespecified correction plan")
    for profile in profiles:
        if profiles[profile] != replacements[profile]:
            raise ValueError(f"{profile}: clarified run profile differs from original")
    case_sets = {tuple(sorted({case for model, case, _ in originals if model == profile})) for profile in profiles}
    if len(case_sets) != 1:
        raise ValueError("Original configurations have different workflow coverage")
    cases = next(iter(case_sets))
    if len(cases) != expected_workflows or ORIGINAL_CASE not in cases or CLARIFIED_CASE in cases:
        raise ValueError(f"Original inputs need {expected_workflows} workflows including only the original authored-method case")
    expected_originals = {(profile, case, repetition) for profile in profiles for case in cases for repetition in range(1, repeats + 1)}
    expected_clarified = {(profile, CLARIFIED_CASE, repetition) for profile in profiles for repetition in range(1, repeats + 1)}
    if set(originals) != expected_originals or set(clarified) != expected_clarified:
        raise ValueError("Missing or out-of-plan repetitions: exact planned repeats required for every task/configuration")
    all_sources = original_sources + clarified_sources
    _verify_frozen_controls(original_sources, clarified_sources)
    if len({source["clarification"]["prompt_sha256"] for source in clarified_sources}) != 1:
        raise ValueError("Clarified reports use different prompt versions")
    for field in ("local_tool_allowlist", "build_tool_allowlist"):
        if len({tuple(sorted(source[field])) for source in all_sources}) > 1:
            raise ValueError(f"Recorded {field} differs across original and clarified reports")
    output, swaps = [], []
    for key in sorted(originals):
        row, origin = originals[key]
        if key[1] == ORIGINAL_CASE:
            replacement, replacement_origin = clarified[(key[0], CLARIFIED_CASE, key[2])]
            swaps.append({"excluded_original": origin, "included_clarified": replacement_origin,
                          "original_status": row.get("status"), "original_objective_checks": row.get("objective_checks"),
                          "clarified_status": replacement.get("status"), "clarified_objective_checks": replacement.get("objective_checks")})
            row, origin = replacement, replacement_origin
        output.append({**deepcopy(row), "evidence_origin": deepcopy(origin)})
    correction = {"id": CORRECTION_ID, "original_case_id": ORIGINAL_CASE, "replacement_case_id": CLARIFIED_CASE,
                  "rule": "Retain all 15 other original workflows. Replace all 3 authored-method repetitions per configuration with all 3 clarified attempts. No best-of selection or fallback.",
                  "reason": "Original output-boundary wording and execution-failure versus error-object rejection format were ambiguous.",
                  "clarified_contract": "annual_output_kg>0; annual_cost_usd>=0; zero cost valid; calculate(inputs) raises ValueError for invalid inputs.",
                  "original_reports_unchanged": True, "original_results_archived": True,
                  "configuration_ids": sorted(profiles), "planned_repeats": repeats,
                  "retained_original_row_count": len(originals) - len(swaps), "excluded_original_row_count": len(swaps),
                  "included_clarified_row_count": len(clarified), "output_row_count": len(output)}
    if correction_plan:
        correction["prespecified_analysis_plan"] = deepcopy(correction_plan)
    manifest = {"schema_version": "1.0", "created_at": datetime.now(timezone.utc).isoformat(),
                "analysis_correction": correction, "source_reports": all_sources, "replacements": swaps,
                "row_provenance": "Every derived result has raw file hash, raw row index, and canonical JSON row hash in evidence_origin.",
                "limitations": ["Clarified tasks run later; combined elapsed-time summaries are descriptive.",
                                "One task's wording changes explicitly. Original strict-check scores remain separately archived."]}
    report = {"suite_id": "lanm_provider_comparison_clarified", "version": "1.0.0", "created_at": manifest["created_at"],
              "status": "run_finished", "repeat": repeats, "planned_attempts": len(output),
              "selected_case_ids": [CLARIFIED_CASE if case == ORIGINAL_CASE else case for case in cases],
              "profiles": [profiles[key] for key in sorted(profiles)], "results": output,
              "local_tool_allowlist": all_sources[0]["local_tool_allowlist"], "build_tool_allowlist": all_sources[0]["build_tool_allowlist"],
              "analysis_correction": deepcopy(correction)}
    return report, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, nargs="+", required=True)
    parser.add_argument("--clarified", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--correction-plan", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.expanduser().resolve()
    manifest_path = output.with_name(output.stem + "-replacement-manifest.json")
    if not output.is_relative_to(WORKSPACE) or output.is_relative_to(WORKSPACE / "platform") or output.suffix != ".json":
        parser.error("Output must be JSON within this workspace and outside platform/")
    if output.exists() or manifest_path.exists():
        parser.error("Use new versioned outputs; existing evidence must not be overwritten")
    def read(paths):
        result = []
        for path in paths:
            raw = path.read_bytes()
            result.append((str(path.resolve()), json.loads(raw), hashlib.sha256(raw).hexdigest()))
        return result
    plan_bytes = args.correction_plan.read_bytes()
    plan = {"path": str(args.correction_plan.resolve()), "sha256": hashlib.sha256(plan_bytes).hexdigest(),
            "contents": json.loads(plan_bytes)}
    try:
        report, manifest = combine_reports(read(args.original), read(args.clarified), correction_plan=plan)
    except ValueError as exc:
        parser.error(str(exc))
    manifest["analysis_script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    manifest_bytes = json_bytes(manifest)
    report["analysis_correction"]["replacement_manifest"] = {"path": str(manifest_path), "sha256": hashlib.sha256(manifest_bytes).hexdigest()}
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(manifest_bytes)
    output.write_bytes(json_bytes(report))
    print(f"Derived {len(report['results'])} attempts across {len(report['profiles'])} configurations: {output}")
    print(f"Auditable replacement manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
