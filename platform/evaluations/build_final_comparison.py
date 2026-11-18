"""Build a versioned complete twelve-configuration evidence and figure bundle."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from combine_clarified_comparison import combine_reports, json_bytes
from comparison_pairs import paired_comparisons, PAIR_SPECS
from audit_authored_methods import audit_reports
from plot_comparison import export_figures
from summarize_comparison import apply_configuration_manifest, summarize_reports, write_csv, write_outputs
from verify_comparison_training import verify_training, file_identity

WORKSPACE = Path(__file__).resolve().parents[2]
EXPECTED_IDS = {item for spec in PAIR_SPECS for item in spec[-2:]} | {"claude-sonnet", "claude-opus", "codex-default", "codex-astra"}
TRAINED_IDS = {"qwen-4b-trained", "qwen-4b-trained-thinking", "qwen-9b-trained", "qwen-9b-trained-thinking"}


def read_reports(paths):
    results = []
    for path in paths:
        path = Path(path).resolve()
        raw = path.read_bytes()
        results.append((str(path), json.loads(raw), hashlib.sha256(raw).hexdigest()))
    return results


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def validate_population(configurations, plan, profiles):
    declarations = configurations.get("configurations", [])
    ids = [row.get("profile_id") for row in declarations]
    if len(ids) != 12 or set(ids) != EXPECTED_IDS or set(profiles) != EXPECTED_IDS:
        raise ValueError("Final bundle requires exactly all twelve planned configurations, without missing or extra results")
    if set(plan["contents"].get("configuration_ids", [])) != EXPECTED_IDS:
        raise ValueError("Correction plan must cover exactly the same twelve configurations")
    if plan["contents"].get("headline_workflow_count") != 16 or plan["contents"].get("repetitions") != 3:
        raise ValueError("Final suite must contain sixteen workflows with three repetitions")
    if {row["profile_id"] for row in declarations if row.get("training") == "trained"} != TRAINED_IDS:
        raise ValueError("All four trained configurations must be actual trained artifacts")
    if any(row.get("training") in {"planned", "unknown"} for row in declarations):
        raise ValueError("Final bundle cannot contain planned or unknown training identities")
    return {row["profile_id"]: row for row in declarations}


def verify_pair_controls(profiles):
    controls = []
    for identifier, kind, size, condition, before, after in PAIR_SPECS:
        a, b = profiles[before], profiles[after]
        keys = ("backend", "request_timeout", "max_tool_rounds", "max_output_tokens")
        meta_keys = ("quantization", "context_length", "temperature", "seed", "server_version", "hardware", "revision")
        for key in keys:
            if a.get(key) != b.get(key):
                raise ValueError(f"{identifier}: paired runtime control {key} differs")
        for key in meta_keys:
            if a.get("metadata", {}).get(key) != b.get("metadata", {}).get(key):
                raise ValueError(f"{identifier}: paired runtime metadata {key} differs")
        if kind == "training" and a.get("enable_thinking") != b.get("enable_thinking"):
            raise ValueError(f"{identifier}: training contrast changes thinking")
        if kind == "thinking" and (a.get("enable_thinking") is not False or b.get("enable_thinking") is not True):
            raise ValueError(f"{identifier}: thinking contrast must change off to on")
        controls.append({"contrast_id": identifier, "runtime_controls": {key: a.get(key) for key in keys},
                         "metadata_controls": {key: a.get("metadata", {}).get(key) for key in meta_keys}})
    return controls


def headline_rows(original, corrected):
    result = []
    for identifier in corrected["configuration_order"]:
        old, new = original["model_summary"][identifier], corrected["model_summary"][identifier]
        result.append({"profile_id": identifier, "label": corrected["configurations"][identifier]["display_name"],
                       "original_strict_passed": old["objective_tasks_passed"], "corrected_passed": new["objective_tasks_passed"],
                       "attempted": new["attempted"], "completed_status": new["completed"],
                       "clean_success": new["objective_tasks_passed"] - new["tasks_passed_despite_tool_failures"],
                       "recovered_success": new["tasks_passed_despite_tool_failures"],
                       "failed_tasks": new["objective_tasks_attempted"] - new["objective_tasks_passed"],
                       "failed_without_tool_error": new["tasks_failed_without_tool_failures"],
                       "tool_calls": new["tool_calls"], "failed_tool_calls": new["tool_calls_failed"],
                       "unknown_tool_outcomes": new["tool_calls_outcome_unknown"],
                       "completed_latency_seconds": new["completed_case_seconds"],
                       "requested_models": new["requested_models"], "reported_models": new["reported_models"],
                       "rerouted_cases": new["cases_with_model_rerouting"], "native_tool_records": new["native_tool_records"]})
    return result


def failure_patterns(summary):
    tasks = []
    for row in summary["case_summary"]:
        if row["objective_tasks_passed"] == row["objective_tasks_attempted"]:
            continue
        matching = [item for item in summary["task_failures"] if item["profile_id"] == row["profile_id"] and item["id"] == row["case_id"]]
        checks = Counter(check["id"] for item in matching for check in item["failed_checks"])
        tasks.append({"profile_id": row["profile_id"], "case_id": row["case_id"],
                      "failed_attempts": len(matching), "attempted": row["objective_tasks_attempted"],
                      "failed_without_tool_error": row["tasks_failed_without_tool_failures"],
                      "failed_check_frequencies": dict(checks), "status_counts": row["status_counts"]})
    return {"task_patterns": sorted(tasks, key=lambda row: (-row["failed_attempts"], row["profile_id"], row["case_id"])),
            "tool_patterns": [row for row in summary["tool_summary"] if row["failed"] or row["unknown"]],
            "error_message_patterns": summary["recurring_tool_errors"],
            "attribution": "Observed tool responses and unmet state checks. Repeated invalid arguments suggest a calling problem; these automated labels do not prove a root cause or a broken tool implementation."}


def build_bundle(original_reports, clarified_reports, configurations, plan, output_dir):
    output = Path(output_dir).resolve()
    archive = output.with_suffix(".zip")
    derived_path = output.with_name(output.name + "-corrected-attempts.json")
    if not output.is_relative_to(WORKSPACE) or output.is_relative_to(WORKSPACE / "platform"):
        raise ValueError("Bundle output must stay within this workspace and outside platform/")
    if any(path.exists() for path in (output, archive, derived_path)):
        raise ValueError("Use a new versioned output; existing evidence must not be overwritten")
    derived, replacement = combine_reports(original_reports, clarified_reports, correction_plan=plan)
    profiles = {row["id"]: row for row in derived["profiles"]}
    declarations = validate_population(configurations, plan, profiles)
    controls = verify_pair_controls(profiles)
    cache = {}
    training = {key: verify_training(declarations[key], profiles[key], cache) for key in sorted(TRAINED_IDS)}
    for size in ("4b", "9b"):
        off, on = training[f"qwen-{size}-trained"], training[f"qwen-{size}-trained-thinking"]
        for field in ("raw_adapter", "evaluated_adapter", "run_manifest", "export_manifest"):
            if off[field]["sha256"] != on[field]["sha256"]:
                raise ValueError(f"{size}: thinking conditions must use the same learned adapter and export")
    dataset = file_identity(WORKSPACE / "local-training/data/train.jsonl", cache)
    validation = file_identity(WORKSPACE / "local-training/data/validation.jsonl", cache)
    for result in training.values():
        identity = result["training"]["identity"]
        if identity.get("train_sha256") != dataset["sha256"] or identity.get("validation_sha256") != validation["sha256"]:
            raise ValueError("Training or validation corpus differs from the finished training identity")
    lineage_path = WORKSPACE / "local-training/base-lineage.json"
    lineage = json.loads(lineage_path.read_bytes())
    for size, base_id in (("4B", "qwen-local"), ("9B", "qwen-9b-local")):
        item = next((row for row in lineage.get("models", []) if row.get("size") == size), {})
        trained = training[f"qwen-{size.lower()}-trained"]["training"]
        if (item.get("official_repo") != trained.get("base_repo") or item.get("official_revision") != trained.get("base_revision")
                or item.get("conversion_revision") != profiles[base_id].get("metadata", {}).get("revision")):
            raise ValueError(f"{size}: recorded official/conversion base lineage differs")
    original = summarize_reports([(source, report) for source, report, _ in original_reports])
    for record, (_, _, digest) in zip(original["source_reports"], original_reports):
        record["sha256"] = digest
    original = apply_configuration_manifest(original, configurations)
    replacement_path = output / "replacement-manifest.json"
    replacement["analysis_script_sha256"] = file_identity(Path(__file__).with_name("combine_clarified_comparison.py"))["sha256"]
    replacement_bytes = json_bytes(replacement)
    derived["analysis_correction"]["replacement_manifest"] = {"path": str(replacement_path), "sha256": hashlib.sha256(replacement_bytes).hexdigest()}
    derived_bytes = json_bytes(derived)
    corrected = apply_configuration_manifest(summarize_reports([(str(derived_path), derived)]), configurations)
    corrected["source_reports"][0]["sha256"] = hashlib.sha256(derived_bytes).hexdigest()
    corrected["raw_source_reports"] = replacement["source_reports"]
    for label, data in (("original", original), ("corrected", corrected)):
        if len(data["case_results"]) != 576 or any(row["attempted"] != 48 for row in data["model_summary"].values()):
            raise ValueError(f"{label}: incomplete final denominators")
        if data["warnings"]:
            raise ValueError(f"{label}: unresolved summary warnings: {data['warnings']}")
    pairs = {"original_strict": paired_comparisons(original), "corrected": paired_comparisons(corrected)}
    methodology = methodology_data(original, corrected, replacement)
    sensitivity = audit_reports([(source, report) for source, report, _ in original_reports])
    sensitivity["source_reports"] = replacement["source_reports"][:len(original_reports)]
    # All input validation occurs before creating outputs. Incomplete exports never receive a completion manifest.
    output.mkdir(parents=True)
    derived_path.write_bytes(derived_bytes)
    replacement_path.write_bytes(replacement_bytes)
    _write(output / "configurations.json", configurations)
    _write(output / "clarified-analysis-plan.json", plan)
    _write(output / "methodology-and-coverage.json", methodology)
    _write(output / "source-and-model-identities.json", {"raw_reports": replacement["source_reports"], "profiles": profiles,
        "training_verification": training, "paired_runtime_controls": controls,
        "training_corpus": dataset, "validation_corpus": validation, "base_lineage": lineage,
        "base_lineage_file": file_identity(lineage_path, cache), "derived_attempts": file_identity(derived_path, cache)})
    for name, data in (("original-strict", original), ("corrected", corrected)):
        summary_path = output / (name + "-summary.json")
        write_outputs(data, summary_path)
        export_figures(data, output / (name + "-figures"), summary_path=summary_path)
    _write(output / "paired-comparisons.json", pairs)
    _write(output / "authored-method-error-object-sensitivity.json", sensitivity)
    _write(output / "failure-patterns.json", failure_patterns(corrected))
    for name, data in pairs.items():
        for key in ("contrasts", "per_task", "attempt_pairs"):
            rows = data[key]
            write_csv(output / f"{name}-paired-{key.replace('_', '-')}.csv", rows, list(rows[0]) if rows else [])
    facts = {"score_label": "Clarified-task automated workflow checks", "counts": methodology["counts"],
             "configurations": headline_rows(original, corrected), "training_and_thinking_contrasts": pairs["corrected"]["contrasts"],
             "recurring_tool_errors": corrected["recurring_tool_errors"], "limitations": methodology["limitations"]}
    _write(output / "slide-facts.json", facts)
    copy_provenance(output, training)
    files = [{"relative_path": str(path.relative_to(output)).replace("\\", "/"),
              "sha256": file_identity(path, cache)["sha256"], "bytes": path.stat().st_size}
             for path in sorted(output.rglob("*")) if path.is_file()]
    _write(output / "bundle-manifest.json", {"status": "complete", "created_at": datetime.now(timezone.utc).isoformat(),
        "files": files, "raw_reports_and_model_weights_included": False, "derived_raw_report_external": str(derived_path),
        "counts": methodology["counts"]})
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as handle:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                handle.write(path, path.relative_to(output))
    with zipfile.ZipFile(archive) as handle:
        if handle.testzip() is not None:
            raise ValueError("Final archive integrity check failed")
    return {"bundle": str(output), "archive": file_identity(archive), "derived_report": str(derived_path), "counts": methodology["counts"]}


def methodology_data(original, corrected, replacement):
    counts = {"configurations": 12, "distinct_workflow_templates": 16, "repetitions_per_workflow": 3,
              "original_attempts": len(original["case_results"]), "clarified_extra_attempts": len(replacement["replacements"]),
              "raw_attempts_total": len(original["case_results"]) + len(replacement["replacements"]),
              "headline_attempts": len(corrected["case_results"]), "headline_attempts_per_configuration": 48,
              "retained_original_attempts": replacement["analysis_correction"]["retained_original_row_count"]}
    return {"schema_version": "1.0", "counts": counts, "deadline_seconds_per_workflow": 300,
            "original_coverage": original["coverage"], "corrected_coverage": corrected["coverage"],
            "scope": {"platform_tool_inventory_count_at_suite_design": 41, "research_allowed_tools": 33,
                      "build_allowed_tools": 36, "literature": "Archived literature fixture; live PubMed retrieval excluded",
                      "robot_execution": "Excluded", "project_state": "Fresh isolated project per workflow attempt; shared across its conversation turns"},
            "success_definition": "Completed execution and every recorded final/intermediate objective check passed. Errors and timeouts remain in task denominators.",
            "failure_interpretation": [
                "A rejected tool call may be corrected and the task completed; recovered successes are separate from clean successes.",
                "A tool can return success while the requested project state or generated method is wrong. Task checks catch some silent failures.",
                "check_method can successfully return a failed reference evaluation; tool-call success alone is not authored-method correctness.",
                "Error-message categories describe observations. They do not automatically attribute blame to model, transport, application, or grader.",
                "Saved-state contract success is separate from correctness and evidential support of the final prose.",
            ],
            "limitations": [
                "There are 16 distinct workflow templates, each repeated 3 times per configuration. These are not 48 or 144 independent tasks, and pooled models do not create new tasks.",
                "This is a development fixture suite, not an independent scientific benchmark or a blind expert accuracy assessment.",
                "Original ambiguous authored-method outputs remain archived. Corrected headlines consistently replace that task for all twelve configurations under a prespecified plan.",
                "Clarified attempts ran later. Model serving hardware, provider latency, caches, queues and warmness are not fully controlled; latency medians are descriptive with observed counts.",
                "Compatible-provider and Codex agent runtimes differ. Compare complete model/runtime configurations; observed differences are not isolated causal effects of model weights.",
                "Training comparisons use the same task/repetition labels and checked local runtime controls, but are not randomized independent replication or proof of broad generalization.",
                "Official training checkpoint and GGUF conversion revision identifiers belong to different repositories. Recorded lineage supports the same family/release; lossy quantization prevents bytewise reconstruction claims.",
                "Token accounting differs by provider and is reported with coverage. No pricing, confidence interval, significance test, or invented scientific-accuracy score is supplied.",
            ]}


def copy_provenance(output, training):
    seen = set()
    for identifier, record in training.items():
        for field in ("run_manifest", "export_manifest", "integration_smoke"):
            evidence = record[field]
            if evidence["sha256"] in seen:
                continue
            seen.add(evidence["sha256"])
            target = output / "training-provenance" / (identifier + "-" + field.replace("_", "-") + ".json")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(evidence["path"], target)
    scripts = ("build_final_comparison.py", "combine_clarified_comparison.py", "summarize_comparison.py", "plot_comparison.py",
               "comparison_pairs.py", "verify_comparison_training.py", "audit_authored_methods.py", "prepare_answer_review.py")
    (output / "analysis-scripts").mkdir()
    for name in scripts:
        shutil.copyfile(Path(__file__).with_name(name), output / "analysis-scripts" / name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, nargs="+", required=True)
    parser.add_argument("--clarified", type=Path, nargs="+", required=True)
    parser.add_argument("--configurations", type=Path, required=True)
    parser.add_argument("--correction-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    raw_plan = args.correction_plan.read_bytes()
    plan = {"path": str(args.correction_plan.resolve()), "sha256": hashlib.sha256(raw_plan).hexdigest(), "contents": json.loads(raw_plan)}
    try:
        result = build_bundle(read_reports(args.original), read_reports(args.clarified),
                              json.loads(args.configurations.read_bytes()), plan, args.output_dir)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
