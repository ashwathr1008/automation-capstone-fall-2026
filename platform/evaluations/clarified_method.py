"""Separate method-case clarification; original evaluations and training stay frozen."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import tempfile

_SPEC = importlib.util.spec_from_file_location("lanm_clarified_base", Path(__file__).with_name("compare.py"))
comparison = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(comparison)
VERSION = "1.0.0"
ORIGINAL_CASE_ID, CASE_ID = "wf_build_method", "wf_build_method_clarified"
REPETITIONS, TIMEOUT_SECONDS = 3, 300.0
ORIGINAL_CASE = deepcopy(next(c for c in comparison.workflows.CASES if c["id"] == ORIGINAL_CASE_ID))
AMBIGUOUS_TEXT = "Reject output <= 0 and negative annual cost."
CLARIFIED_TEXT = ("Inside calculate(inputs), reject annual_output_kg <= 0 or annual_cost_usd < 0 by raising ValueError. "
    "Do not rely solely on input-schema validation or return an error object for these invalid numeric inputs. "
    "Zero annual_cost_usd is valid and returns usd_per_kg=0 when annual_output_kg > 0.")
if len(ORIGINAL_CASE["turns"]) != 1 or ORIGINAL_CASE["question"].count(AMBIGUOUS_TEXT) != 1:
    raise ValueError("Original case differs from the reviewed clarification target")
CASE = deepcopy(ORIGINAL_CASE)
CASE.update(id=CASE_ID, title=ORIGINAL_CASE["title"] + " (clarified input validation)", category="objective_tool_contract")
CASE["question"] = ORIGINAL_CASE["question"].replace(AMBIGUOUS_TEXT, CLARIFIED_TEXT)
CASE["turns"] = [turn.replace(AMBIGUOUS_TEXT, CLARIFIED_TEXT) for turn in ORIGINAL_CASE["turns"]]
PROMPT = comparison.workflows.PREFIX + CASE["turns"][0]


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def execution_case():
    case = deepcopy(CASE)
    case["id"] = ORIGINAL_CASE_ID
    return case


def prompt_identity():
    return {"case_id": CASE_ID, "original_case_id": ORIGINAL_CASE_ID,
        "original_question": ORIGINAL_CASE["question"], "original_question_sha256": digest(ORIGINAL_CASE["question"]),
        "original_prompt_sha256": digest(comparison.workflows.PREFIX + ORIGINAL_CASE["turns"][0]),
        "revised_question": CASE["question"], "revised_question_sha256": digest(CASE["question"]),
        "prompt": PROMPT, "prompt_sha256": digest(PROMPT), "removed_text": AMBIGUOUS_TEXT, "replacement_text": CLARIFIED_TEXT,
        "scope": "Clarifies validation inside calculate(inputs), invalid input variable, ValueError and valid zero cost; all other requirements, references, setup and checks are unchanged."}


def run_case(profile, runtime_factory):
    result = comparison.run_workflow_case(execution_case(), profile, TIMEOUT_SECONDS, runtime_factory)
    if result.get("prompts") != [PROMPT]:
        raise ValueError("Executed prompt differs from clarified prompt identity")
    result.update(id=CASE_ID, title=CASE["title"], question=CASE["question"], original_case_id=ORIGINAL_CASE_ID,
        prompt_sha256=digest(PROMPT), revised_question_sha256=digest(CASE["question"]), checker_case_id=ORIGINAL_CASE_ID)
    return result


def report_template(profiles, running):
    source = comparison.ROOT / "src" / "lanm_platform"
    names = ["runtime.py", "compatible_runtime.py", "claude_runtime.py", "providers.py", "grounding.py", "guidance.py",
             "mcp.py", "methods.py", "method_worker.py", "core.py", "economics.py", "data/candidates.json.gz", "data/lanm_handbook.md"]
    return {"suite_id": "lanm_clarified_method_comparison", "version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(), "status": "running" if running else "prepared_without_model_requests",
        "clarification": prompt_identity(), "harness_sha256": digest(Path(__file__).read_bytes()),
        "base_harness_sha256": digest(Path(comparison.__file__).read_bytes()),
        "workflow_implementation_sha256": digest(Path(comparison.workflows.__file__).read_bytes()),
        "scientific_runner_sha256": digest(Path(comparison.science.__file__).read_bytes()),
        "objective_cases_sha256": digest(json.dumps([CASE], sort_keys=True)),
        "implementation_sha256": {name: digest((source / name).read_bytes()) for name in names if (source / name).is_file()},
        "profiles": [comparison.public_profile(p) for p in profiles], "repeat": REPETITIONS, "timeout_seconds": TIMEOUT_SECONDS,
        "local_tool_allowlist": deepcopy(comparison.LOCAL_TOOLS), "build_tool_allowlist": deepcopy(comparison.BUILD_TOOLS),
        "selected_case_ids": [CASE_ID], "planned_attempts": REPETITIONS * len(profiles),
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "comparison_scope": "Separate clarification rerun; do not silently pool with or replace original wf_build_method results. Frozen checker reused; scientific accuracy unreviewed.",
        "timing_scope": "Same 300-second case deadline, fresh project/runtime and alternating profile order. Hardware, queueing, caches and warmness are not controlled.",
        "training_policy": {"split": "evaluation_holdout", "training_eligible": False,
                            "reason": "Original and clarified cases, rubrics and outputs are excluded from the frozen training corpus."}, "results": []}


IDENTITY_KEYS = ("suite_id", "version", "clarification", "harness_sha256", "base_harness_sha256",
    "workflow_implementation_sha256", "scientific_runner_sha256", "objective_cases_sha256", "implementation_sha256",
    "profiles", "repeat", "timeout_seconds", "local_tool_allowlist", "build_tool_allowlist", "selected_case_ids")


def validate_resume(previous, planned):
    changed = [key for key in IDENTITY_KEYS if previous.get(key) != planned.get(key)]
    if changed:
        raise ValueError("Cannot resume a different clarified configuration: " + ", ".join(changed))
    expected = {(p["id"], CASE_ID, rep) for p in planned["profiles"] for rep in range(1, REPETITIONS + 1)}
    try:
        keys = [(r["profile_id"], r["id"], r["repetition"]) for r in previous["results"]]
    except (KeyError, TypeError) as error:
        raise ValueError("Existing report has malformed attempts") from error
    if len(set(keys)) != len(keys) or not set(keys) <= expected:
        raise ValueError("Existing report has duplicate, original-case or out-of-plan attempts")
    if any(r.get("prompt_sha256") != digest(PROMPT) for r in previous["results"]):
        raise ValueError("Existing attempt has a different prompt identity")
    return set(keys)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--list", action="store_true")
    action.add_argument("--prepare", action="store_true")
    action.add_argument("--run", action="store_true", help="Explicitly make live model requests")
    parser.add_argument("--profile", action="append", default=[])
    parser.add_argument("--profiles-file", type=Path)
    parser.add_argument("--case", choices=[CASE_ID], default=CASE_ID)
    parser.add_argument("--repeat", type=int, choices=[REPETITIONS], default=REPETITIONS)
    parser.add_argument("--timeout", type=float, choices=[TIMEOUT_SECONDS], default=TIMEOUT_SECONDS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    configured = comparison.load_profiles(args.profiles_file) if args.profiles_file else comparison.load_profiles()
    by_id = {p["id"]: p for p in configured}
    if set(args.profile) - set(by_id):
        parser.error("Unknown profiles: " + ", ".join(sorted(set(args.profile) - set(by_id))))
    profiles = [by_id[key] for key in dict.fromkeys(args.profile)]
    if not (args.prepare or args.run):
        print(CASE_ID + ": " + CASE["title"] + "\nPrompt SHA-256: " + digest(PROMPT) + ". No model requests made.")
        return 0
    if args.resume and not args.run:
        parser.error("--resume requires --run")
    if args.run and not profiles:
        parser.error("--run requires at least one --profile")
    if not args.output:
        parser.error("--prepare/--run require --output outside platform/")
    try:
        destination = comparison.output_path(args.output)
    except ValueError as error:
        parser.error(str(error))
    if destination.exists() and not args.resume:
        parser.error("Output exists; choose a new filename or use --resume")
    report, completed = report_template(profiles, args.run), set()
    if args.resume:
        if not destination.is_file():
            parser.error("There is no clarified report to resume")
        previous = json.loads(destination.read_text(encoding="utf-8"))
        try:
            completed = validate_resume(previous, report)
        except ValueError as error:
            parser.error(str(error))
        report = previous
        report["status"] = "running"
        report.setdefault("resumed_at", []).append(datetime.now(timezone.utc).isoformat())
    comparison.science.save_report(destination, report)
    if args.prepare:
        with tempfile.TemporaryDirectory(prefix="lanm-clarified-prepare-") as directory:
            store = comparison.Store(directory)
            pid, context, prompts = comparison.workflows.setup(store, execution_case())
            assert prompts == [PROMPT]
            report["results"].append({"id": CASE_ID, "original_case_id": ORIGINAL_CASE_ID, "title": CASE["title"],
                "category": CASE["category"], "status": "not_run", "question_template": CASE["question"],
                "prompt": prompts[0], "prompt_sha256": digest(prompts[0]), "fixture_context": context,
                "initial_state": comparison.workflows.snapshot(store, pid),
                "scientific_review": comparison.science.review_template(CASE), "temporary_project_removed": True})
    else:
        for repetition in range(REPETITIONS):
            for order, profile in enumerate(comparison.ordered_profiles(profiles, repetition)):
                if (profile["id"], CASE_ID, repetition + 1) in completed:
                    continue
                print(f"Repeat {repetition + 1}: {profile['id']} / {CASE_ID}", flush=True)
                try:
                    factory = comparison.runtime_factory_for(profile, tool_allowlist=deepcopy(comparison.BUILD_TOOLS))
                    result = run_case(profile, factory)
                except Exception as error:
                    result = {"id": CASE_ID, "original_case_id": ORIGINAL_CASE_ID, "status": "error", "error": str(error),
                        "model": profile["model"], "mode": "build", "trace": [], "metrics": {},
                        "objective_checks": {"scope": "Run failed before objective checks completed.", "checks": []},
                        "prompt": PROMPT, "prompt_sha256": digest(PROMPT), "scientific_review": comparison.science.review_template(CASE)}
                result.update(profile_id=profile["id"], backend=profile["backend"], category=CASE["category"],
                    repetition=repetition + 1, provider_order=order + 1, tool_outcomes=comparison.trace_facts(result.get("trace", [])))
                report["results"].append(result)
                report["summary"] = comparison.summarize(report["results"])
                comparison.science.save_report(destination, report)
                print("  " + result["status"] + "; scientific review unreviewed", flush=True)
        report["status"] = "run_finished"
    comparison.science.save_report(destination, report)
    print("Report: " + str(destination))
    return int(any(r["status"] in {"error", "timeout", "incomplete", "cancelled"} for r in report["results"]))


if __name__ == "__main__":
    raise SystemExit(main())
