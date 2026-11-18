"""Summarize observed benchmark outcomes without grading scientific answer quality.

Reads one or more comparison JSON reports; writes JSON and CSV tables. The input
reports remain the evidence for every failure. Unknown tool outcomes, missing
usage, and incomplete cases are retained rather than converted to successes.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

VERSION = "1.0.0"
WORKSPACE = Path(__file__).resolve().parents[2]
NOT_ATTEMPTED = {"not_run", "prepared", "pending", "skipped", "unavailable"}
TOKEN_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens", "cached_input_tokens", "reasoning_output_tokens")


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def distribution(values):
    values = sorted(value for value in values if finite_number(value))
    if not values:
        return {"n": 0, "median": None, "p95": None, "min": None, "max": None}
    position = (len(values) - 1) * 0.95
    low, high = math.floor(position), math.ceil(position)
    return {"n": len(values), "median": statistics.median(values),
            "p95": values[low] + (values[high] - values[low]) * (position - low),
            "min": values[0], "max": values[-1]}


def _checks(row):
    value = row.get("objective_checks", {})
    return value.get("checks", []) if isinstance(value, dict) else []


def task_passed(row):
    checks = _checks(row)
    return row.get("status") == "completed" and bool(checks) and all(c.get("passed") is True for c in checks)


def is_objective(row):
    return row.get("category") == "objective_tool_contract" or bool(_checks(row))


def _trace(row):
    # New runners flatten all turn traces with turn_index. Do not count both
    # the flattened copy and the originals retained in turns[].
    if isinstance(row.get("trace"), list):
        return row["trace"]
    return [{**entry, "turn_index": i} for i, turn in enumerate(row.get("turns", []))
            for entry in turn.get("trace", [])]


def tool_calls(row):
    trace = _trace(row)
    calls = [entry for entry in trace if entry.get("type") == "tool_call"]
    completed_ids = {(entry.get("turn_index"), entry.get("id")) for entry in calls if entry.get("id") is not None}
    # An interrupted started call is observable but its outcome is unknown.
    starts = [entry for entry in trace if entry.get("type") == "tool_started"
              and (entry.get("id") is None or (entry.get("turn_index"), entry.get("id")) not in completed_ids)]
    return calls + [{**entry, "success": None, "unfinished_started_call": True} for entry in starts]


def tool_name(entry):
    name = str(entry.get("name") or "<unnamed>")
    return name.rsplit("__", 1)[-1] if name.startswith("mcp__") else name


def error_text(entry):
    value = entry.get("error")
    result = entry.get("result")
    if not value and isinstance(result, dict) and result.get("isError"):
        value = result.get("error") or " ".join(part.get("text", "") for part in result.get("content", [])
                                                 if isinstance(part, dict) and part.get("type") == "text")
    if isinstance(value, str):
        return value[:4000]
    return json.dumps(value, ensure_ascii=False, sort_keys=True)[:4000] if value else "No error detail recorded"


def classify_error(message):
    """Descriptive text rules, not a diagnosis of model versus software blame."""
    value = message.casefold()
    rules = [
        ("timeout", ("timed out", "timeout", "time limit", "deadline")),
        ("cancelled", ("cancelled", "canceled")),
        ("authentication_or_access", ("unauthorized", "authentication", "api key", "permission denied", "forbidden", "not logged in")),
        ("rate_limit_or_quota", ("rate limit", "quota", "usage limit", "too many requests", "429")),
        ("invalid_json", ("not valid json", "invalid json", "jsondecode", "bounded json string")),
        ("wrong_project", ("active project id", "active project", "different project")),
        ("record_not_found", ("not found", "unknown candidate", "unknown source", "unknown method", "unknown run")),
        ("tool_unavailable", ("not available in the active mode", "unknown tool", "not in the allowlist", "tool is not available")),
        ("invalid_arguments", ("unsupported assumption", "unexpected argument", "unexpected keyword", "required", "must be", "cannot exceed", "invalid input", "schema", "is not allowed", "unrecognized")),
        ("state_or_validation_rejection", ("stale", "changed since", "review", "accept", "register", "check failed", "exceeds declared", "mass balance", "refus")),
        ("transport_or_runtime", ("connection", "http", "socket", "process", "broken pipe", "runtime", "server", "network")),
    ]
    return next((name for name, fragments in rules if any(fragment in value for fragment in fragments)), "other_or_unspecified")


def error_signature(message):
    # Group the same rejection across fresh projects without hiding the exact
    # error retained in each failure record.
    return re.sub(r"\b(?:project|run|selection|batch|source|experiment|revision)_[0-9a-f]+\b", "<record-id>", message).strip()


def _identity(row):
    identity = {key: row.get(key) for key in ("profile_id", "model", "id", "repetition", "source_report", "source_result_index")}
    if row.get("evidence_origin"):
        identity["evidence_origin"] = row["evidence_origin"]
    return identity


def _reported_models(row):
    metrics = row.get("metrics", {})
    reported = metrics.get("reported_models", [])
    names = {str(value) for value in reported if value} if isinstance(reported, list) else set()
    if metrics.get("reported_model"):
        names.add(str(metrics["reported_model"]))
    return names


def _execution_error(row):
    terminal = row.get("terminal", {})
    error = row.get("error") or (terminal.get("error") or terminal.get("message") or terminal.get("text")
                                 if isinstance(terminal, dict) else None)
    if error:
        return error
    failed_turns = [{"turn_index": turn.get("turn_index", index + 1), "status": turn.get("status"),
                     "error": _execution_error({key: value for key, value in turn.items() if key != "turns"})}
                    for index, turn in enumerate(row.get("turns", [])) if turn.get("status") != "completed"]
    return failed_turns or None


def _token_summary(rows):
    result = {}
    for key in TOKEN_KEYS:
        values = []
        for row in rows:
            usage = row.get("metrics", {}).get("token_usage")
            value = usage.get(key) if isinstance(usage, dict) else None
            if finite_number(value):
                values.append(value)
        result[key] = {"observed_sum": sum(values) if values else None,
                       "observed_cases": len(values), "attempted_cases": len(rows),
                       "complete_coverage": bool(rows) and len(values) == len(rows)}
    return result


def _summarize_group(rows):
    objective = [row for row in rows if is_objective(row)]
    passed = [row for row in objective if task_passed(row)]
    checks = [check for row in objective for check in _checks(row)]
    calls = [entry for row in rows for entry in tool_calls(row)]
    successes = sum(entry.get("success") is True for entry in calls)
    failures = sum(entry.get("success") is False for entry in calls)
    known = successes + failures
    failed_rows = [row for row in rows if any(entry.get("success") is False for entry in tool_calls(row))]
    return {
        "attempted": len(rows), "completed": sum(row.get("status") == "completed" for row in rows),
        "status_counts": dict(sorted(Counter(row.get("status", "unknown") for row in rows).items())),
        "objective_tasks_attempted": len(objective), "objective_tasks_passed": len(passed),
        "objective_task_success_rate": len(passed) / len(objective) if objective else None,
        "objective_tasks_without_checks": sum(not _checks(row) for row in objective),
        "objective_checks_passed": sum(check.get("passed") is True for check in checks),
        "objective_checks_failed": sum(check.get("passed") is False for check in checks),
        "objective_checks_unknown": sum(check.get("passed") is not True and check.get("passed") is not False for check in checks),
        "objective_checks_total": len(checks),
        "tool_calls": len(calls), "tool_calls_succeeded": successes, "tool_calls_failed": failures,
        "tool_calls_outcome_unknown": len(calls) - known,
        "tool_success_rate_known_outcomes": successes / known if known else None,
        "cases_with_tool_failures": len(failed_rows),
        "tasks_passed_despite_tool_failures": sum(task_passed(row) for row in failed_rows),
        "tasks_failed_without_tool_failures": sum(not task_passed(row)
            and not any(entry.get("success") is False for entry in tool_calls(row)) for row in objective),
        "native_tool_records": sum(entry.get("type") == "native_tool" for row in rows for entry in _trace(row)),
        "all_attempt_case_seconds": distribution([row.get("elapsed_seconds") for row in rows]),
        "completed_case_seconds": distribution([row.get("elapsed_seconds") for row in rows if row.get("status") == "completed"]),
        "all_attempt_runtime_seconds": distribution([row.get("metrics", {}).get("total_seconds") for row in rows]),
        "successful_task_case_seconds": distribution([row.get("elapsed_seconds") for row in passed]),
        "token_usage": _token_summary(rows),
        "requested_models": sorted({str(row.get("metrics", {}).get("requested_model") or row.get("model")) for row in rows
                                     if row.get("metrics", {}).get("requested_model") or row.get("model")}),
        "reported_models": sorted({model for row in rows for model in _reported_models(row)}),
        "cases_with_model_rerouting": sum(any(entry.get("type") == "model_rerouted" for entry in _trace(row)) for row in rows),
        "scientific_review_status_counts": dict(sorted(Counter(row.get("scientific_review", {}).get("status", "unreviewed") for row in rows).items())),
    }


def summarize_reports(reports, *, allow_duplicates=False):
    """reports is an iterable of (source name, parsed report); no source is changed."""
    rows, sources, profiles, warnings, seen = [], [], {}, [], {}
    comparison_values = defaultdict(set)
    not_attempted = []
    planned_case_ids, planned_repeats, analysis_corrections = [], set(), []
    allowed_research, allowed_build = set(), set()
    for source, report in reports:
        if not isinstance(report, dict) or not isinstance(report.get("results"), list):
            raise ValueError(f"{source}: expected a comparison report with a results list")
        sources.append({"path": str(source), "suite_id": report.get("suite_id"), "version": report.get("version"),
                        "created_at": report.get("created_at"), "status": report.get("status"),
                        "result_count": len(report["results"])})
        if report.get("analysis_correction"):
            analysis_corrections.append(report["analysis_correction"])
        if isinstance(report.get("repeat"), int) and not isinstance(report["repeat"], bool):
            planned_repeats.add(report["repeat"])
        allowed_research.update(report.get("local_tool_allowlist", []))
        allowed_build.update(report.get("build_tool_allowlist", []))
        for case_id in report.get("selected_case_ids", []):
            if case_id not in planned_case_ids:
                planned_case_ids.append(case_id)
        for key in ("suite_id", "objective_cases_sha256", "scientific_cases_sha256", "harness_sha256", "scientific_runner_sha256",
                    "workflow_implementation_sha256", "implementation_sha256"):
            if report.get(key) is not None:
                comparison_values[key].add(json.dumps(report[key], sort_keys=True))
        for profile in report.get("profiles", []):
            identifier = profile.get("id")
            if identifier in profiles and profiles[identifier] != profile:
                warnings.append(f"Profile {identifier!r} has different declared configurations across input reports.")
            profiles.setdefault(identifier, profile)
        for index, original in enumerate(report["results"]):
            if not isinstance(original, dict):
                raise ValueError(f"{source}: result {index} is not an object")
            row = {**original, "source_report": str(source), "source_result_index": index}
            if not row.get("profile_id") or not row.get("id"):
                raise ValueError(f"{source}: result {index} is missing profile_id or id")
            if row.get("status") in NOT_ATTEMPTED:
                not_attempted.append(_identity(row) | {"status": row.get("status"), "error": row.get("error")})
                continue
            key = (row["profile_id"], row["id"], row.get("repetition", 1))
            if key in seen:
                message = f"Duplicate profile/case/repetition {key!r} in {source} and {seen[key]}"
                if not allow_duplicates:
                    raise ValueError(message + "; pass --allow-duplicates only to intentionally count both attempts")
                warnings.append(message + "; both attempts counted by explicit request.")
            seen[key] = str(source)
            rows.append(row)
    for key, values in comparison_values.items():
        if len(values) > 1:
            warnings.append(f"Input reports differ in {key}; pooled totals are descriptive and may not represent matched conditions.")

    by_profile, by_case, by_tool = defaultdict(list), defaultdict(list), defaultdict(list)
    tool_failures, task_failures, error_groups, case_results = [], [], defaultdict(list), []
    for row in rows:
        profile_id, case_id = row["profile_id"], row["id"]
        by_profile[profile_id].append(row)
        by_case[(profile_id, case_id)].append(row)
        calls = tool_calls(row)
        for ordinal, entry in enumerate(calls):
            name = tool_name(entry)
            by_tool[(profile_id, name)].append((row, entry))
            if entry.get("success") is False:
                error = error_text(entry)
                later_success = any(tool_name(later) == name and later.get("success") is True for later in calls[ordinal + 1:])
                failure = {**_identity(row), "tool": name, "call_id": entry.get("id"),
                           "turn_index": entry.get("turn_index"), "tool_record_index": ordinal,
                           "error_category": classify_error(error), "error": error,
                           "argument_keys": sorted(entry["arguments"]) if isinstance(entry.get("arguments"), dict) else [],
                           "later_success_same_tool": later_success, "objective_task_passed": task_passed(row)}
                tool_failures.append(failure)
                error_groups[(profile_id, name, failure["error_category"], error_signature(error))].append(failure)
        failed_checks = [{"id": check.get("id"), "passed": check.get("passed"), "basis": check.get("basis")}
                         for check in _checks(row) if check.get("passed") is not True]
        passed = task_passed(row) if is_objective(row) else None
        case_results.append({**_identity(row), "category": row.get("category"), "status": row.get("status"),
                             "objective_task_passed": passed, "elapsed_seconds": row.get("elapsed_seconds"),
                             "runtime_seconds": row.get("metrics", {}).get("total_seconds"),
                             "tool_calls": len(calls), "tool_failures": sum(entry.get("success") is False for entry in calls),
                             "failed_check_ids": [check["id"] for check in failed_checks]})
        if row.get("status") != "completed" or passed is False:
            task_failures.append({**_identity(row), "status": row.get("status"),
                                  "failure_kind": "execution_not_completed" if row.get("status") != "completed" else "objective_checks_not_met",
                                  "execution_error": _execution_error(row), "failed_checks": failed_checks,
                                  "objective_checks_missing": is_objective(row) and not _checks(row),
                                  "tool_failures": sum(entry.get("success") is False for entry in calls)})

    tool_summary = []
    for (profile_id, name), entries in sorted(by_tool.items()):
        succeeded = sum(entry.get("success") is True for _, entry in entries)
        failed = sum(entry.get("success") is False for _, entry in entries)
        known = succeeded + failed
        tool_summary.append({"profile_id": profile_id, "tool": name, "calls": len(entries),
                             "succeeded": succeeded, "failed": failed, "unknown": len(entries) - known,
                             "failure_rate_known_outcomes": failed / known if known else None,
                             "distinct_cases_with_failure": len({row["id"] for row, entry in entries if entry.get("success") is False}),
                             "attempts_with_failure": len({(row["source_report"], row["source_result_index"]) for row, entry in entries if entry.get("success") is False})})

    model_summary = {}
    for profile_id in sorted(set(profiles) | set(by_profile)):
        absent = [row for row in not_attempted if row["profile_id"] == profile_id]
        model_summary[profile_id] = {**_summarize_group(by_profile[profile_id]),
                                     "not_attempted_count": len(absent),
                                     "not_attempted_status_counts": dict(sorted(Counter(row["status"] for row in absent).items())),
                                     "case_attempt_counts": dict(sorted(Counter(row["id"] for row in by_profile[profile_id]).items()))}
    coverage = {json.dumps(row["case_attempt_counts"], sort_keys=True) for row in model_summary.values()}
    if len(coverage) > 1:
        warnings.append("Models do not have identical case/repetition coverage; use paired case rows and identify unfinished or unavailable model runs.")

    observed_tools = {name for _, name in by_tool}
    allowed_tools = allowed_research | allowed_build
    coverage_summary = {
        "distinct_workflow_types_observed": len({row["id"] for row in rows if is_objective(row)}),
        "planned_workflow_type_count": len(planned_case_ids) if planned_case_ids else None,
        "planned_repeats_per_task": sorted(planned_repeats),
        "objective_attempts_observed": sum(is_objective(row) for row in rows),
        "observed_tool_type_count": len(observed_tools), "observed_tool_types": sorted(observed_tools),
        "observed_lanm_tool_type_count": len(observed_tools & allowed_tools) if allowed_tools else None,
        "observed_lanm_tool_types": sorted(observed_tools & allowed_tools) if allowed_tools else None,
        "other_observed_tool_names": sorted(observed_tools - allowed_tools) if allowed_tools else None,
        "research_allowed_tool_count": len(allowed_research) if allowed_research else None,
        "build_allowed_tool_count": len(allowed_build) if allowed_build else None,
        "research_allowed_tools": sorted(allowed_research), "build_allowed_tools": sorted(allowed_build),
        "observed_tools_by_profile": {profile: sorted(name for model, name in by_tool if model == profile)
                                      for profile in sorted(by_profile)},
        "interpretation": "Tool coverage counts distinct names attempted, including rejected calls; it does not prove all features or argument combinations were tested.",
    }
    return {"summary_version": VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
            "source_reports": sources, "profiles": profiles, "warnings": list(dict.fromkeys(warnings)),
            "not_attempted": not_attempted, "planned_case_ids": planned_case_ids, "coverage": coverage_summary,
            "analysis_corrections": analysis_corrections,
            "model_summary": model_summary,
            "case_summary": [{"profile_id": profile_id, "case_id": case_id, **_summarize_group(group)}
                             for (profile_id, case_id), group in sorted(by_case.items())],
            "tool_summary": tool_summary, "case_results": case_results,
            "tool_failures": tool_failures, "task_failures": task_failures,
            "recurring_tool_errors": [{"profile_id": profile_id, "tool": tool, "error_category": category,
                                       "error_signature": signature, "count": len(group),
                                       "distinct_cases": len({failure["id"] for failure in group}),
                                       "attempts": len({(f["source_report"], f["source_result_index"]) for f in group}),
                                       "tasks_passed_after_errors": len({(f["source_report"], f["source_result_index"]) for f in group if f["objective_task_passed"]})}
                                      for (profile_id, tool, category, signature), group in sorted(error_groups.items(), key=lambda item: (-len(item[1]), item[0]))],
            "interpretation": [
                "Task success requires completion and every recorded objective check to pass; errors and timeouts remain in attempted-task denominators.",
                "Objective checks measure specified state or artifact contracts, not scientific correctness, citation entailment, or usefulness of the prose.",
                "Tool outcomes use only explicit success flags; unknown and interrupted outcomes remain separate. A rejected call can be followed by successful task completion.",
                "Error categories are deterministic text labels for observed messages, not proof that a model or tool implementation caused the problem.",
                "Token totals sum only observed case-level usage and state coverage. Provider token accounting and underlying agent runtimes can differ.",
                "Reported-model aliases, native tools, configured grounding, code hashes, and profile differences must be checked before claiming matched model-only comparisons.",
                "No price, confidence interval, statistical significance, or scientific score is inferred. Small repeated development suites support descriptive findings only.",
            ]}


def apply_configuration_manifest(summary, manifest):
    """Attach declared display/provenance metadata without changing raw identity.

    Planned configurations remain unobserved. An observed trained configuration
    needs an artifact hash so a prompt variant cannot silently become 'trained'.
    """
    declarations = manifest.get("configurations") if isinstance(manifest, dict) else None
    if not isinstance(declarations, list) or not declarations:
        raise ValueError("Configuration manifest needs a nonempty configurations list")
    configurations = {}
    allowed_fields = ("profile_id", "display_name", "group", "training", "thinking", "model", "checkpoint",
                      "training_artifact_sha256", "training_artifact_path", "evaluated_adapter_path", "adapter_gguf_sha256",
                      "training_data_sha256", "provenance_path", "export_provenance_path", "integration_smoke_path", "notes")
    for declaration in declarations:
        if not isinstance(declaration, dict):
            raise ValueError("Each configuration must be an object")
        identifier = declaration.get("profile_id")
        if not isinstance(identifier, str) or not identifier or identifier in configurations:
            raise ValueError("Configuration profile_id values must be nonempty and unique")
        training, thinking = declaration.get("training", "unknown"), declaration.get("thinking", "unknown")
        if training not in {"base", "trained", "planned", "not_applicable", "unknown"}:
            raise ValueError(f"{identifier}: invalid training label")
        if thinking not in {"off", "on", "provider default", "unknown"}:
            raise ValueError(f"{identifier}: invalid thinking label")
        profile = summary.get("profiles", {}).get(identifier, {})
        if declaration.get("model") and profile.get("model") and declaration["model"] != profile["model"]:
            raise ValueError(f"{identifier}: manifest model differs from the recorded profile")
        if isinstance(profile.get("enable_thinking"), bool) and thinking in {"on", "off"}:
            if profile["enable_thinking"] != (thinking == "on"):
                raise ValueError(f"{identifier}: manifest thinking differs from the recorded profile")
        attempted = summary.get("model_summary", {}).get(identifier, {}).get("attempted", 0)
        if attempted and training == "planned":
            raise ValueError(f"{identifier}: observed attempts cannot retain a planned training label")
        if attempted and training == "trained":
            artifact_hash = declaration.get("training_artifact_sha256", "")
            if not isinstance(artifact_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", artifact_hash):
                raise ValueError(f"{identifier}: observed trained runs need a training_artifact_sha256")
        configurations[identifier] = {key: declaration[key] for key in allowed_fields if key in declaration}
        configurations[identifier].update(training=training, thinking=thinking)
    # Validate everything before changing the summary.
    summary["configurations"] = configurations
    summary["configuration_order"] = list(configurations)
    if isinstance(manifest.get("coverage_context"), dict):
        summary["coverage"]["declared_context"] = manifest["coverage_context"]
    for identifier in configurations:
        summary["model_summary"].setdefault(identifier, {**_summarize_group([]), "not_attempted_count": 0,
            "not_attempted_status_counts": {}, "case_attempt_counts": {}})
    missing = [identifier for identifier in configurations if not summary["model_summary"][identifier]["attempted"]]
    if missing:
        summary["warnings"].append("Declared configurations have no observed attempts: " + ", ".join(missing))
    return summary


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                             for key, value in row.items() if key in fields})


def write_outputs(summary, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    model_rows = []
    for profile_id, row in summary["model_summary"].items():
        model_rows.append({"profile_id": profile_id, **summary.get("configurations", {}).get(profile_id, {}), **row,
                           "median_case_seconds": row["all_attempt_case_seconds"]["median"],
                           "median_runtime_seconds": row["all_attempt_runtime_seconds"]["median"],
                           "p95_case_seconds": row["all_attempt_case_seconds"]["p95"]})
    tables = {
        "models": (model_rows, ["profile_id", "display_name", "group", "training", "thinking", "attempted", "completed", "objective_tasks_attempted", "objective_tasks_passed",
                                  "objective_task_success_rate", "tool_calls", "tool_calls_succeeded", "tool_calls_failed",
                                  "tool_calls_outcome_unknown", "tasks_passed_despite_tool_failures", "tasks_failed_without_tool_failures",
                                  "median_case_seconds", "p95_case_seconds", "median_runtime_seconds", "status_counts"]),
        "cases": (summary["case_results"], ["profile_id", "model", "id", "repetition", "status", "objective_task_passed", "elapsed_seconds",
                                             "runtime_seconds", "tool_calls", "tool_failures", "failed_check_ids", "source_report", "source_result_index", "evidence_origin"]),
        "tools": (summary["tool_summary"], ["profile_id", "tool", "calls", "succeeded", "failed", "unknown", "failure_rate_known_outcomes",
                                             "distinct_cases_with_failure", "attempts_with_failure"]),
        "tool-failures": (summary["tool_failures"], ["profile_id", "id", "repetition", "tool", "turn_index", "call_id", "error_category", "error",
                                                      "argument_keys", "later_success_same_tool", "objective_task_passed", "source_report", "source_result_index", "evidence_origin"]),
        "task-failures": (summary["task_failures"], ["profile_id", "id", "repetition", "status", "failure_kind", "execution_error", "failed_checks",
                                                      "objective_checks_missing", "tool_failures", "source_report", "source_result_index", "evidence_origin"]),
    }
    for suffix, (rows, fields) in tables.items():
        write_csv(destination.with_name(destination.stem + "-" + suffix + ".csv"), rows, fields)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-duplicates", action="store_true")
    parser.add_argument("--configurations", type=Path, help="Declared configuration order, labels, and training provenance")
    args = parser.parse_args(argv)
    destination = args.output.expanduser().resolve()
    if not destination.is_relative_to(WORKSPACE) or destination.is_relative_to(WORKSPACE / "platform") or destination.suffix.lower() != ".json":
        parser.error("Output must be a .json file inside this workspace and outside platform/")
    inputs = [path.expanduser().resolve() for path in args.reports]
    if destination in inputs:
        parser.error("The summary must not overwrite an input report")
    reports = []
    for path in inputs:
        reports.append((str(path), json.loads(path.read_text(encoding="utf-8"))))
    try:
        summary = summarize_reports(reports, allow_duplicates=args.allow_duplicates)
        if args.configurations:
            config_path = args.configurations.expanduser().resolve()
            raw_config = config_path.read_bytes()
            apply_configuration_manifest(summary, json.loads(raw_config))
            summary["configuration_manifest"] = {"path": str(config_path), "sha256": hashlib.sha256(raw_config).hexdigest()}
    except ValueError as exc:
        parser.error(str(exc))
    for item, path in zip(summary["source_reports"], inputs):
        item["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_outputs(summary, destination)
    print(f"Summary and five CSV tables: {destination}")
    for profile_id, row in summary["model_summary"].items():
        print(f"{profile_id}: {row['objective_tasks_passed']}/{row['objective_tasks_attempted']} objective tasks; "
              f"{row['tool_calls_failed']} failed / {row['tool_calls']} observed tool calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
