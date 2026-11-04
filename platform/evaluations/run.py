"""Small opt-in scientific evaluation runner. No scientific self-grading."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from lanm_platform.config import DEFAULT_MODEL, data_directory
from lanm_platform.core import Store
from lanm_platform.runtime import Runtime

CASES_PATH = Path(__file__).with_name("cases.json")


def load_suite(path=CASES_PATH):
    suite = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = [case["id"] for case in suite["cases"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Evaluation case IDs must be unique")
    for case in suite["cases"]:
        if not case["reference_criteria"]:
            raise ValueError("Each case needs human reference criteria")
        for key in case["source_keys"]:
            if key not in suite["sources"]:
                raise ValueError("Unknown source: " + key)
    return suite


def case_sources(suite, case):
    return [deepcopy(suite["sources"][key]) for key in case["source_keys"]] + [
        {"url": "", "kind": "synthetic_fixture", "locator": "Whole fixture", **deepcopy(item)}
        for item in case["fixtures"]
    ]


def review_template(case):
    return {
        "status": "unreviewed", "reviewer": None, "reviewed_at": None,
        "rubric_status": "Author judgment; not expert validated. Other defensible answers may satisfy the criteria.",
        "criteria": [{"criterion": text, "rating": "unreviewed", "rationale": ""}
                     for text in case["reference_criteria"]],
        "notes": "",
    }


def make_prompt(case, sources):
    catalog = [{"id": source["id"], "title": source["title"], "url": source.get("url", "")}
               for source in sources]
    return (
        "This is an isolated development exercise. Synthetic records are fictional and must not be "
        "represented as laboratory or published measurements. Use the archived case sources below "
        "and the current project state; no live literature search is required. Read the relevant "
        "archived text and cite its source ID or URL when answering. Do not create or accept experiments.\n\n"
        "CASE SOURCE CATALOG:\n" + json.dumps(catalog, ensure_ascii=False) + "\n\n" + case["question"]
    )


def structural_checks(case, answer, events, sources):
    """Only observable syntax/activity. These checks do not judge scientific truth."""
    activities = [event.get("text", "") for event in events if event.get("type") == "activity"]
    tools = sorted({match.group(1) for text in activities
                    if (match := re.match(r"Using ([A-Za-z0-9_]+)", text))})
    markers = [{"id": source["id"], "title": source["title"],
                "id_present": source["id"] in answer,
                "url_present": bool(source.get("url") and source["url"].rstrip("/") in answer)}
               for source in sources]
    return {
        "scope": "Syntax and attempted tool activity only. No scientific correctness or entailment score.",
        "answer_present": bool(answer.strip()),
        "fixture_citation_marker_present": any(m["id_present"] or m["url_present"] for m in markers),
        "fixture_citation_markers": markers,
        "observed_tool_names": tools,
        "expected_tool_activity": {name: name in tools for name in case["expected_tools"]},
        "source_use_verification": "unverified: Runtime activity gives tool names, not call arguments, success or returned excerpts",
    }


def run_case(suite, case, model, timeout=300, runtime_factory=Runtime):
    result = {"id": case["id"], "title": case["title"], "question": case["question"],
              "model": model, "mode": "research", "scientific_review": review_template(case)}
    started = time.monotonic()
    # There is deliberately no --data or --project option. No existing Store is opened.
    with tempfile.TemporaryDirectory(prefix="lanm-evaluation-") as temporary:
        store = Store(temporary)
        project = store.create_project("Evaluation: " + case["id"], **case["project"],
                                       description="Fictional isolated evaluation. No real laboratory evidence.")
        pid = project["id"]
        if case.get("assumptions"):
            store.update_assumptions(pid, case["assumptions"], "Synthetic evaluation scenario")
        sources = []
        for fixture in case_sources(suite, case):
            text = ("Evidence kind: " + fixture["kind"] + "\nLocator: " + fixture["locator"] +
                    "\n\n" + fixture["text"])
            saved = store.add_source(pid, fixture["title"], text, fixture["url"])
            sources.append({**fixture, "id": saved["id"], "archived_text": text, "sha256": saved["sha256"]})
        prompt = make_prompt(case, sources)
        result.update(prompt=prompt, evidence=sources, initial_project=store.get_project(pid))
        runtime = runtime_factory(store, Path(temporary))
        job = None
        timed_out = False
        try:
            job = runtime.submit(pid, prompt, mode="research", model=model)
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
        if job:
            with job.condition:
                events = deepcopy(job.events)
                answer = job.text
            terminal = next((e for e in reversed(events) if e.get("type") in {"done", "error"}), {})
            status = ("timeout" if timed_out else "error" if terminal.get("type") == "error"
                      else "completed" if job.done else "incomplete")
            result.update(status=result.get("status", status), answer=answer, events=events,
                          terminal=terminal, job_id=job.id, thread_id=job.thread_id,
                          structural_checks=structural_checks(case, answer, events, sources))
        result.update(final_project=store.get_project(pid), saved_runs=store.list_runs(pid),
                      elapsed_seconds=round(time.monotonic() - started, 3))
    result["temporary_project_removed"] = True
    return result


def output_path(value=None):
    path = Path(value).expanduser().resolve() if value else data_directory() / "evaluations" / "latest.json"
    path = path.resolve()
    if path.is_relative_to(ROOT):
        raise ValueError("Evaluation outputs belong outside the source checkout; choose --output elsewhere")
    if path.suffix.casefold() != ".json":
        raise ValueError("Evaluation output must have a .json extension")
    return path


def save_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--list", action="store_true", help="List cases; default, no model requests")
    action.add_argument("--prepare", action="store_true", help="Save review packet without opening a Store or model")
    action.add_argument("--run", action="store_true", help="Explicitly invoke the signed-in model, using temporary projects")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--case", action="append", default=[], help="Case ID; repeat for a subset")
    selection.add_argument("--all", action="store_true", help="Select all cases")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=float, default=300, help="Seconds per case, including model startup")
    parser.add_argument("--output", type=Path, help="JSON outside checkout; default: data/evaluations/latest.json")
    args = parser.parse_args(argv)
    suite = load_suite()
    unknown = set(args.case) - {case["id"] for case in suite["cases"]}
    if unknown:
        parser.error("Unknown cases: " + ", ".join(sorted(unknown)))
    selected = [case for case in suite["cases"] if not args.case or case["id"] in args.case]
    if not (args.prepare or args.run):
        for case in selected:
            print(case["id"] + ": " + case["title"])
        print("No model requests made. Use --prepare or explicit --run with --case ID / --all.")
        return 0
    if args.run and not (args.case or args.all):
        parser.error("--run requires --case ID or --all")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    try:
        destination = output_path(args.output)
    except ValueError as exc:
        parser.error(str(exc))
    report = {
        "suite_id": suite["suite_id"], "suite_version": suite["version"],
        "cases_sha256": hashlib.sha256(CASES_PATH.read_bytes()).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(), "model": args.model,
        "status": "running" if args.run else "prepared_without_model_requests",
        "scope": suite["status"],
        "isolation": "A new temporary Store/project per live case. Existing project databases are never opened.",
        "scientific_accuracy": "not assessed; requires human review of outputs and sources",
        "results": [],
    }
    save_report(destination, report)
    for case in selected:
        if args.run:
            print("Running " + case["id"] + " in a temporary project...", flush=True)
            try:
                result = run_case(suite, case, args.model, args.timeout)
            except Exception as exc:
                # Retain prior cases if setup, teardown or file access fails.
                result = {"id": case["id"], "status": "error", "error": str(exc),
                          "scientific_review": review_template(case)}
            print(case["id"] + ": " + result["status"] + "; scientific review unreviewed", flush=True)
        else:
            result = {"id": case["id"], "title": case["title"], "question": case["question"],
                      "evidence": case_sources(suite, case), "setup": case.get("assumptions", {}),
                      "expected_tools": case["expected_tools"], "status": "not_run",
                      "scientific_review": review_template(case)}
        report["results"].append(result)
        save_report(destination, report)
    if args.run:
        report["status"] = "run_finished"
        save_report(destination, report)
    print("Report: " + str(destination))
    return 1 if any(r["status"] in {"error", "timeout", "incomplete"} for r in report["results"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
