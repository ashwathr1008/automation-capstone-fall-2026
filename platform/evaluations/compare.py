"""Opt-in provider comparison on isolated, archived development fixtures."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))
from lanm_platform.core import Store
from lanm_platform.mcp import definitions
from lanm_platform.providers import load_profiles, runtime_factory_for

_SPEC = importlib.util.spec_from_file_location("lanm_scientific_evaluation", Path(__file__).with_name("run.py"))
science = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(science)

_WORKFLOW_SPEC = importlib.util.spec_from_file_location("lanm_workflow_evaluation", Path(__file__).with_name("workflow_cases.py"))
workflows = importlib.util.module_from_spec(_WORKFLOW_SPEC)
_WORKFLOW_SPEC.loader.exec_module(workflows)

VERSION = "2.0.0"
# Keep local state-changing tools: respecting a hypothetical request should be
# observable instead of forced by removing the ability to change assumptions.
LOCAL_TOOLS = sorted(item["name"] for item in definitions(False)
                     if item["name"] not in {"search_pubmed", "fetch_pubmed", "promote_shared_evidence", "list_projects", "create_project"})
BUILD_TOOLS = sorted(set(LOCAL_TOOLS) | {item["name"] for item in definitions(True)
                                       if item["name"] not in {tool["name"] for tool in definitions(False)}})
OBJECTIVE_CASES = [
    {"id": "tool_economics", "title": "Saved economic calculation with collected mass basis",
     "question": "Calculate and save the current economic scenario using calculate_economics. Report the required aggregate bed volume and productivity with units. The collected mass is already after recovery losses. Do not change any inputs or create experiments.",
     "reference_criteria": ["The response correctly describes the saved result, including units and conditional scenario status.",
                            "Does not apply recovery a second time or claim industrial validation."]},
    {"id": "tool_hypothetical", "title": "Hypothetical ranking without committed changes",
     "question": "For a hypothetical comparison only, rank the top three untested candidates assuming usable_lifetime_cycles = 50 and support = 'hypothetical support'. Save the ranking snapshot with these overrides and explain its limits. Do not commit project inputs, change configuration, or create experiments.",
     "reference_criteria": ["Clearly distinguishes the hypothetical ranking from committed inputs and measurements.",
                            "Explains that lifetime changes do not improve untested screening scores."]},
    {"id": "tool_exact_selection", "title": "Exact ordered selection and export provenance",
     "question": "Save a testing selection from ranking {ranking_run_id} using exactly these candidate IDs in this order: {candidate_ids}. Then create one software-demo CSV batch of exactly two candidates from that saved selection, with stock-volume bounds 40 and 60 uL and seed 7. Return its download link. Do not rerank or substitute candidates, change inputs, create experiments, or run automation.",
     "reference_criteria": ["Links to the saved batch and accurately describes the selected candidates and simulated volume units.",
                            "Does not claim that the software export executes laboratory automation."]},
    {"id": "tool_missing_bound", "title": "Missing export prerequisite stays unresolved",
     "question": "Export exactly two candidates from saved selection {selection_id}, with a custom minimum stock volume of 50 uL. I have not decided the upper bound: ask me for that value before creating any batch. Do not choose it for me, rerank, change inputs, or create experiments.",
     "reference_criteria": ["Asks for the missing upper stock-volume bound in uL.",
                            "Does not invent a bound or claim an export exists."]},
]


def output_path(value):
    path = Path(value).expanduser().resolve()
    if not path.is_relative_to(WORKSPACE) or path.is_relative_to(ROOT):
        raise ValueError("Comparison output must be inside the workspace and outside platform/ (for example ../benchmark-results/run.json)")
    if path.suffix.lower() != ".json":
        raise ValueError("Comparison output must have a .json extension")
    return path


def public_profile(profile):
    """Configuration identity only; credentials never belong in a report."""
    keys = {"id", "name", "backend", "model", "base_url", "api_key_env", "request_timeout", "max_tool_rounds", "enable_thinking", "max_output_tokens", "domain_grounding", "effort"}
    result = {key: deepcopy(value) for key, value in profile.items() if key in keys}
    metadata_keys = {"checkpoint", "revision", "quantization", "context_length", "thinking", "temperature", "seed", "server_version", "hardware"}
    result["metadata"] = {key: deepcopy(value) for key, value in profile.get("metadata", {}).items() if key in metadata_keys}
    return result


def all_cases(suite):
    return [{**case, "category": "scientific_review"} for case in suite["cases"]] + [
        {**case, "category": "objective_tool_contract"} for case in OBJECTIVE_CASES + workflows.CASES]


def semantic_state(project):
    return {key: deepcopy(project[key]) for key in
            ("revision", "assumptions", "configuration", "experiment_count", "accepted_experiment_count")}


def setup_objective(store, case):
    project = store.create_project("Comparison: " + case["id"], "Nd", "La",
                                   description="Isolated software evaluation; no laboratory measurements.")
    pid = project["id"]
    context = {}
    if case["id"] == "tool_economics":
        store.update_assumptions(pid, {"collected_target_kg_per_l_cycle": 0.0005,
                                     "target_recovery_fraction": 0.8,
                                     "cycle_time_hours": 8, "target_production_kg_per_day": 0.1},
                                 "Synthetic software-evaluation scenario")
    if case["id"] in {"tool_exact_selection", "tool_missing_bound"}:
        run = store.rank(pid, "untested", 3)
        if len(run["rows"]) < 3:
            raise ValueError("Comparison fixture needs at least three eligible library candidates")
        context = {"ranking_run_id": run["id"],
                   "candidate_ids": [run["rows"][2]["candidate_id"], run["rows"][0]["candidate_id"]]}
        if case["id"] == "tool_missing_bound":
            selection = store.save_testing_selection(pid, run["id"], context["candidate_ids"],
                                                     "Fixed evaluation fixture selection")
            context["selection_id"] = selection["id"]
    prompt = ("This is an isolated software-development evaluation. Use the local platform tools and project "
              "state only; no live web or literature search. Do not treat fixture scenarios as measured evidence.\n\n"
              + case["question"].format(**context))
    return pid, context, prompt


def check_objective(case_id, initial, final, runs, selections, batches, context):
    """Check persisted software facts. Never grade answer prose or scientific truth."""
    checks = [{"id": "committed_inputs_and_experiments_unchanged",
               "passed": semantic_state(initial) == semantic_state(final),
               "basis": "Exact comparison of revision, assumptions, configuration and experiment counts; saved tool outputs and chat are allowed."}]
    if case_id == "tool_economics":
        correct = [run for run in runs if run.get("kind") == "calculate"
                   and math.isclose(run.get("summary", {}).get("required_bed_volume_l", -1), 200 / 3, rel_tol=1e-9)
                   and math.isclose(run.get("summary", {}).get("productivity_kg_per_l_day", -1), 0.0015, rel_tol=1e-9)]
        checks.append({"id": "saved_calculation_matches_independent_arithmetic", "passed": bool(correct),
                       "basis": "0.0005 kg/L/cycle * (24/8) cycles/day = 0.0015 kg/L/day; 0.1 / 0.0015 = 66.6666667 L. Checks tool output, not answer wording."})
    elif case_id == "tool_hypothetical":
        matching = [run for run in runs if run.get("kind") == "rank" and run.get("is_hypothetical")
                    and run.get("scenario", {}).get("assumption_overrides") == {"usable_lifetime_cycles": 50}
                    and run.get("scenario", {}).get("configuration_overrides") == {"support": "hypothetical support"}
                    and run.get("scenario", {}).get("exclude_candidate_ids") == []
                    and run.get("pool") == "untested" and len(run.get("rows", [])) == 3]
        checks.append({"id": "requested_hypothetical_snapshot_saved", "passed": bool(matching),
                       "basis": "Saved untested ranking has both exact requested overrides and three displayed rows."})
    elif case_id == "tool_exact_selection":
        exact = [s for s in selections if s["candidate_ids"] == context["candidate_ids"]
                 and s["ranking_run_id"] == context["ranking_run_id"]]
        checks.append({"id": "exact_order_and_ranking_preserved", "passed": len(selections) == len(exact) == 1,
                       "basis": "Exactly one selection uses the supplied candidate order and ranking ID."})
        good = [b for b in batches if b["candidate_ids"] == context["candidate_ids"] and b["count"] == 2
                and b.get("selection_id") in {s["id"] for s in exact}
                and b.get("generation", {}).get("minimum") == 40
                and b.get("generation", {}).get("maximum") == 60
                and b.get("generation", {}).get("seed") == 7
                and all(40 <= row["stock_volume"] <= 60 for row in b["rows"])]
        checks.append({"id": "one_batch_from_exact_selection", "passed": len(batches) == len(good) == 1,
                       "basis": "Exactly one batch references the saved selection and preserves requested count, order, bounds and seed."})
        checks.append({"id": "no_unrequested_reranking", "passed": len(runs) == 1,
                       "basis": "Only the fixture ranking exists."})
    elif case_id == "tool_missing_bound":
        checks.append({"id": "no_batch_before_missing_bound", "passed": not batches,
                       "basis": "No export was persisted. Whether the answer actually asks a useful clarification requires human review."})
        checks.append({"id": "original_selection_and_ranking_preserved", "passed": len(selections) == len(runs) == 1,
                       "basis": "No extra ranking or selection was saved."})
    return {"scope": "Persisted software facts only; no scientific or answer-quality score.", "checks": checks}


def run_objective_case(case, profile, timeout, runtime_factory):
    started = time.monotonic()
    result = {"id": case["id"], "title": case["title"], "question": case["question"],
              "model": profile["model"], "mode": "research", "scientific_review": science.review_template(case)}
    with tempfile.TemporaryDirectory(prefix="lanm-comparison-") as temporary:
        store = Store(temporary)
        pid, context, prompt = setup_objective(store, case)
        initial = store.get_project(pid)
        result.update(prompt=prompt, fixture_context=context, initial_project=initial)
        runtime = runtime_factory(store, Path(temporary))
        job, timed_out = None, False
        inference_started = time.monotonic()
        try:
            job = runtime.submit(pid, prompt, mode="research", model=profile["model"])
            deadline = time.monotonic() + timeout
            while not job.done:
                with job.condition:
                    job.condition.wait(timeout=min(0.5, max(0.001, deadline - time.monotonic())))
                if time.monotonic() >= deadline and not job.done:
                    timed_out = True
                    runtime.cancel(job.id)
                    break
        except Exception as exc:
            result.update(status="error", error=str(exc))
        finally:
            runtime.close()
            if job and not job.done:
                end = time.monotonic() + 5
                with job.condition:
                    while not job.done and time.monotonic() < end:
                        job.condition.wait(timeout=0.2)
        result["submit_to_close_seconds"] = round(time.monotonic() - inference_started, 6)
        if job:
            with job.condition:
                events, answer = deepcopy(job.events), job.text
                trace, metrics = deepcopy(getattr(job, "trace", [])), deepcopy(getattr(job, "metrics", {}))
            terminal = next((e for e in reversed(events) if e.get("type") in {"done", "error"}), {})
            status = ("timeout" if timed_out else "cancelled" if terminal.get("status") in {"cancelled", "interrupted"}
                      else "error" if terminal.get("type") == "error"
                      else "completed" if job.done else "incomplete")
            result.update(status=result.get("status", status), answer=answer, events=events, trace=trace,
                          metrics=metrics, terminal=terminal, job_id=job.id, thread_id=job.thread_id)
        final, runs = store.get_project(pid), store.list_runs(pid)
        selections, batches = store.list_testing_selections(pid), store.list_testing_batches(pid)
        result.update(final_project=final, saved_runs=runs, testing_selections=selections, testing_batches=batches,
                      objective_checks=check_objective(case["id"], initial, final, runs, selections, batches, context),
                      elapsed_seconds=round(time.monotonic() - started, 6))
    result["temporary_project_removed"] = True
    return result


def trace_facts(trace):
    """Only count explicit tool outcomes, preserving unknowns as unknown."""
    calls = [item for item in trace if item.get("type") == "tool_call"]
    succeeded = sum(item.get("success") is True for item in calls)
    failed = sum(item.get("success") is False for item in calls)
    return {"record_count": len(calls), "explicit_success_records": succeeded,
            "explicit_failure_records": failed, "outcome_unknown_records": len(calls) - succeeded - failed,
            "qualification": "Recorded tool outcomes only; counts are not scientific accuracy or source entailment."}


def aggregate_turn_metrics(turns):
    metrics = [turn.get("metrics", {}) for turn in turns]
    result = {"turn_count": len(turns), "first_token_seconds": metrics[0].get("first_token_seconds") if metrics else None,
              "reported_models": sorted({m["reported_model"] for m in metrics if m.get("reported_model")})}
    for key in ("total_seconds", "model_seconds", "tool_seconds", "request_count", "tool_call_count"):
        values = [m.get(key) for m in metrics]
        result[key] = sum(values) if values and all(isinstance(v, (int, float)) for v in values) else None
    # Codex reports cumulative thread usage; summing turns would count earlier tokens twice.
    cumulative = bool(metrics) and all(str(m.get("token_usage_scope", "")).startswith("thread_cumulative") for m in metrics)
    usages = [metrics[-1].get("token_usage")] if cumulative else [m.get("token_usage") for m in metrics]
    complete = bool(usages) and all(isinstance(u, dict) and all(isinstance(u.get(k), (int, float))
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens")) for u in usages)
    complete = complete and all(m.get("token_usage_complete", True) is not False for m in metrics)
    result["token_usage_complete"] = complete
    result["token_usage"] = ({k: sum(u[k] for u in usages) for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
                              if complete else None)
    result["token_usage_scope"] = "final_thread_cumulative" if cumulative else "sum_of_turn_usage_when_complete"
    return result


def run_workflow_case(case, profile, timeout, runtime_factory):
    """Run every scripted turn in one isolated project and preserve intermediate violations."""
    started = time.monotonic()
    mode = case.get("mode", "research")
    result = {"id": case["id"], "title": case["title"], "question": case["question"],
              "model": profile["model"], "mode": mode, "turns": [], "trace": [], "events": [],
              "scientific_review": science.review_template(case)}
    with tempfile.TemporaryDirectory(prefix="lanm-workflow-comparison-") as temporary:
        store = Store(temporary)
        pid, context, prompts = workflows.setup(store, case)
        initial = workflows.snapshot(store, pid)
        result.update(prompt=prompts[0], prompts=prompts, fixture_context=context, initial_state=initial)
        runtime = runtime_factory(store, Path(temporary))
        deadline = time.monotonic() + timeout
        intermediate_checks = []
        try:
            for index, prompt in enumerate(prompts):
                turn = {"turn_index": index + 1, "prompt": prompt}
                job, timed_out = None, False
                turn_started = time.monotonic()
                try:
                    if time.monotonic() >= deadline:
                        turn.update(status="timeout", error="Case deadline reached before next turn")
                        result["turns"].append(turn)
                        break
                    job = runtime.submit(pid, prompt, mode=mode, model=profile["model"])
                    while not job.done:
                        with job.condition:
                            job.condition.wait(timeout=min(0.5, max(0.001, deadline - time.monotonic())))
                        if time.monotonic() >= deadline and not job.done:
                            timed_out = True
                            runtime.cancel(job.id)
                            break
                    if timed_out:
                        runtime.close()
                    with job.condition:
                        events, answer = deepcopy(job.events), job.text
                        trace = deepcopy(getattr(job, "trace", []))
                        metrics = deepcopy(getattr(job, "metrics", {}))
                    terminal = next((e for e in reversed(events) if e.get("type") in {"done", "error"}), {})
                    status = ("timeout" if timed_out else "cancelled" if terminal.get("status") in {"cancelled", "interrupted"}
                              else "error" if terminal.get("type") == "error"
                              else "completed" if job.done else "incomplete")
                    turn.update(status=status, answer=answer, events=events, trace=trace, metrics=metrics,
                                terminal=terminal, job_id=job.id, thread_id=job.thread_id)
                except Exception as exc:
                    turn.update(status="error", error=str(exc))
                turn["elapsed_seconds"] = round(time.monotonic() - turn_started, 6)
                current = workflows.snapshot(store, pid)
                turn["state"] = current
                if hasattr(workflows, "check_turn"):
                    checks = workflows.check_turn(case["id"], index, initial, current, context)
                    turn["objective_checks"] = checks
                    intermediate_checks.extend({**check, "id": f"turn_{index + 1}:" + check["id"]}
                                               for check in checks.get("checks", []))
                result["turns"].append(turn)
                result["trace"].extend({**entry, "turn_index": index + 1} for entry in turn.get("trace", []))
                result["events"].extend({**entry, "turn_index": index + 1} for entry in turn.get("events", []))
                if turn["status"] != "completed":
                    break
        finally:
            runtime.close()
        final = workflows.snapshot(store, pid)
        facts = workflows.check(case["id"], initial, final, context, trace=result["trace"])
        facts["checks"] = intermediate_checks + facts["checks"]
        result.update(final_state=final, objective_checks=facts, metrics=aggregate_turn_metrics(result["turns"]),
                      answer="\n\n".join(turn.get("answer", "") for turn in result["turns"]),
                      elapsed_seconds=round(time.monotonic() - started, 6))
        statuses = [turn["status"] for turn in result["turns"]]
        result["status"] = (next((status for status in statuses if status != "completed"), "incomplete")
                            if len(statuses) != len(prompts) or any(status != "completed" for status in statuses)
                            else "completed")
    result["temporary_project_removed"] = True
    return result


def percentile(values, proportion):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * proportion
    lower, upper = math.floor(position), math.ceil(position)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 6)


def summarize(results):
    summary = {}
    for profile_id in dict.fromkeys(r["profile_id"] for r in results):
        rows = [r for r in results if r["profile_id"] == profile_id]
        completed = [r for r in rows if r["status"] == "completed"]
        times = [r["elapsed_seconds"] for r in completed if isinstance(r.get("elapsed_seconds"), (int, float))]
        objective = [r for r in rows if r.get("category") == "objective_tool_contract"]
        checks = [check for r in rows for check in r.get("objective_checks", {}).get("checks", [])]
        summary[profile_id] = {
            "attempted": len(rows), "completed": len(completed),
            "status_counts": {status: sum(r["status"] == status for r in rows) for status in sorted({r["status"] for r in rows})},
            "completed_case_wall_seconds": {"n": len(times), "median": statistics.median(times) if times else None,
                                            "p95": percentile(times, 0.95), "min": min(times) if times else None,
                                            "max": max(times) if times else None},
            "objective_checks_passed": sum(c["passed"] is True for c in checks), "objective_checks_total": len(checks),
            "objective_cases_attempted": len(objective),
            "objective_cases_completed_with_all_checks": sum(r["status"] == "completed"
                and bool(r.get("objective_checks", {}).get("checks"))
                and all(c["passed"] is True for c in r["objective_checks"]["checks"]) for r in objective),
            "scientific_accuracy": "unreviewed", "cost_usd": None,
            "qualification": "Latency includes per-case setup, runtime startup and teardown; successful runs only, failures listed separately. Mixed-case aggregates are descriptive, not a model ranking. Cost is unknown, not zero.",
        }
    return summary


def ordered_profiles(profiles, repetition):
    return profiles if repetition % 2 == 0 else list(reversed(profiles))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--list", action="store_true")
    action.add_argument("--prepare", action="store_true", help="Save fixtures and review criteria without model requests")
    action.add_argument("--run", action="store_true", help="Make live requests through configured profiles")
    parser.add_argument("--profile", action="append", default=[], help="Configured profile ID; repeat for comparisons")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--case", action="append", default=[])
    selection.add_argument("--all", action="store_true")
    selection.add_argument("--workflows", action="store_true", help="Select all 16 objective platform workflows")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--profiles-file", type=Path, help="Explicit benchmark profiles without changing application settings")
    parser.add_argument("--resume", action="store_true", help="Continue missing attempts in an identical report; do not retry failures")
    args = parser.parse_args(argv)
    suite = science.load_suite()
    cases = all_cases(suite)
    if args.workflows:
        cases = [case for case in cases if case["category"] == "objective_tool_contract"]
    unknown = set(args.case) - {case["id"] for case in cases}
    if unknown:
        parser.error("Unknown cases: " + ", ".join(sorted(unknown)))
    if args.repeat < 1 or args.repeat > 100:
        parser.error("--repeat must be between 1 and 100")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    cases = [case for case in cases if not args.case or case["id"] in args.case]
    configured = load_profiles(args.profiles_file) if args.profiles_file else load_profiles()
    by_id = {profile["id"]: profile for profile in configured}
    unknown_profiles = set(args.profile) - set(by_id)
    if unknown_profiles:
        parser.error("Unknown profiles: " + ", ".join(sorted(unknown_profiles)))
    profiles = [by_id[key] for key in dict.fromkeys(args.profile)]
    if not (args.prepare or args.run):
        for case in cases:
            print(case["id"] + ": " + case["title"])
        print("Profiles: " + ", ".join(by_id) + ". No model requests made.")
        return 0
    if args.run and not (args.case or args.all or args.workflows):
        parser.error("--run requires --case ID, --all, or --workflows")
    if args.resume and not args.run:
        parser.error("--resume requires --run")
    if args.run and not profiles:
        parser.error("--run requires at least one configured --profile ID")
    if not args.output:
        parser.error("--prepare and --run require --output (for example ../benchmark-results/run.json)")
    try:
        destination = output_path(args.output)
    except ValueError as exc:
        parser.error(str(exc))
    if destination.exists() and not args.resume:
        parser.error("Output already exists; choose a new filename or use --resume")
    spec_bytes = json.dumps(OBJECTIVE_CASES + workflows.CASES, sort_keys=True).encode("utf-8")
    report = {
        "suite_id": "lanm_provider_comparison", "version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "running" if args.run else "prepared_without_model_requests",
        "scientific_cases_sha256": hashlib.sha256(science.CASES_PATH.read_bytes()).hexdigest(),
        "objective_cases_sha256": hashlib.sha256(spec_bytes).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scientific_runner_sha256": hashlib.sha256(Path(science.__file__).read_bytes()).hexdigest(),
        "workflow_implementation_sha256": hashlib.sha256(Path(workflows.__file__).read_bytes()).hexdigest(),
        "implementation_sha256": {name: hashlib.sha256((ROOT / "src" / "lanm_platform" / name).read_bytes()).hexdigest()
                                  for name in ["runtime.py", "compatible_runtime.py", "claude_runtime.py", "providers.py", "grounding.py", "guidance.py", "mcp.py", "methods.py", "method_worker.py", "core.py", "economics.py", "data/candidates.json.gz", "data/lanm_handbook.md"]
                                  if (ROOT / "src" / "lanm_platform" / name).is_file()},
        "profiles": [public_profile(profile) for profile in profiles], "repeat": args.repeat,
        "timeout_seconds": args.timeout, "local_tool_allowlist": LOCAL_TOOLS, "build_tool_allowlist": BUILD_TOOLS,
        "selected_case_ids": [case["id"] for case in cases],
        "planned_attempts": len(cases) * len(profiles) * args.repeat,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "comparison_scope": "Development fixture comparison, not an independent or expert-validated benchmark. Same case templates and setup; fresh project/source IDs differ per run. Compatible runtime uses bounded native platform tools; Codex agent capabilities may differ. Inspect runtime metrics and traces before attributing differences to model weights.",
        "timing_scope": "One new runtime per case; provider order is reversed on alternate repeats. Server-side model warmness, queueing, caching and remote hardware are not controlled. First-token latency is unknown unless explicitly measured by the runtime.",
        "training_policy": {"split": "evaluation_holdout", "training_eligible": False,
                            "review_required": True, "reason": "These cases and derived answers are excluded from training; reviewed outputs require a separate training collection."},
        "results": [],
    }
    if args.resume:
        if not destination.is_file():
            parser.error("There is no report to resume")
        previous = json.loads(destination.read_text(encoding="utf-8"))
        identity = ("version", "scientific_cases_sha256", "objective_cases_sha256", "harness_sha256", "scientific_runner_sha256",
                    "workflow_implementation_sha256", "implementation_sha256", "profiles", "repeat",
                    "timeout_seconds", "selected_case_ids", "local_tool_allowlist", "build_tool_allowlist")
        changed = [key for key in identity if previous.get(key) != report.get(key)]
        if changed:
            parser.error("Cannot resume a different benchmark configuration: " + ", ".join(changed))
        report = previous
        report["status"] = "running"
        report.setdefault("resumed_at", []).append(datetime.now(timezone.utc).isoformat())
    expected_keys = {(p["id"], c["id"], rep + 1) for p in profiles for c in cases for rep in range(args.repeat)}
    try:
        result_keys = [(r["profile_id"], r["id"], r["repetition"]) for r in report["results"]]
    except (KeyError, TypeError):
        parser.error("Existing report has malformed attempts")
    completed_keys = set(result_keys)
    if len(completed_keys) != len(result_keys) or not completed_keys <= expected_keys:
        parser.error("Existing report has duplicate or out-of-plan attempts")
    science.save_report(destination, report)
    if args.prepare:
        for case in cases:
            report["results"].append({"id": case["id"], "category": case["category"], "title": case["title"],
                                      "question_template": case["question"], "status": "not_run",
                                      "evidence": science.case_sources(suite, case) if case["category"] == "scientific_review" else [],
                                      "scientific_review": science.review_template(case)})
    else:
        for repetition in range(args.repeat):
            for case in cases:
                for order, profile in enumerate(ordered_profiles(profiles, repetition)):
                    if (profile["id"], case["id"], repetition + 1) in completed_keys:
                        continue
                    print(f"Repeat {repetition + 1}: {profile['id']} / {case['id']}", flush=True)
                    try:
                        factory = runtime_factory_for(profile, tool_allowlist=BUILD_TOOLS if case.get("mode") == "build" else LOCAL_TOOLS)
                        result = (science.run_case(suite, case, profile["model"], args.timeout, runtime_factory=factory)
                                  if case["category"] == "scientific_review"
                                  else run_workflow_case(case, profile, args.timeout, factory)
                                  if case["id"] in {item["id"] for item in workflows.CASES}
                                  else run_objective_case(case, profile, args.timeout, factory))
                    except Exception as exc:
                        result = {"id": case["id"], "status": "error", "error": str(exc),
                                  "scientific_review": science.review_template(case)}
                    result.update(profile_id=profile["id"], backend=profile["backend"], category=case["category"],
                                  repetition=repetition + 1, provider_order=order + 1,
                                  tool_outcomes=trace_facts(result.get("trace", [])))
                    report["results"].append(result)
                    report["summary"] = summarize(report["results"])
                    science.save_report(destination, report)
                    print(f"  {result['status']}; scientific review unreviewed", flush=True)
        report["status"] = "run_finished"
    science.save_report(destination, report)
    print("Report: " + str(destination))
    return 1 if any(result["status"] in {"error", "timeout", "incomplete", "cancelled"} for result in report["results"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
