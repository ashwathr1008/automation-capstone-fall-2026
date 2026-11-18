"""Prepare or explicitly run the sequential post-training Qwen evaluation queue."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from check_platform_integration import ROOT, WORKSPACE, sha, validate_artifacts, validate_loaded_adapter

DEFAULT_OUTPUT = WORKSPACE / "benchmark-results/local-comparison"
_SPEC = importlib.util.spec_from_file_location("post_training_clarified", WORKSPACE / "platform/evaluations/clarified_method.py")
clarified = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(clarified)
comparison = clarified.comparison
ORIGINAL_CASE_IDS = [case["id"] for case in comparison.OBJECTIVE_CASES + comparison.workflows.CASES]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_plan(profiles_file, output, python=sys.executable, powershell=None):
    """Pure planning: no subprocesses, HTTP requests, model loads or registration."""
    profiles_file, output = Path(profiles_file).resolve(), Path(output).resolve()
    if not profiles_file.is_relative_to(WORKSPACE) or not output.is_relative_to(WORKSPACE):
        raise ValueError("Queue paths must stay in the workspace")
    if output.is_relative_to(WORKSPACE / "platform") or output.is_relative_to(ROOT):
        raise ValueError("Benchmark reports must stay outside platform/ and local-training/")
    powershell = powershell or shutil.which("pwsh") or "powershell.exe"
    profiles = comparison.load_profiles(profiles_file)
    by_id = {profile["id"]: profile for profile in profiles}
    stages = []
    for trained in (False, True):
        for size, digit in (("4B", "4"), ("9B", "9")):
            tag = size.lower()
            helper_suffix = "" if size == "4B" else "-9b"
            if trained:
                start = [powershell, "-NoProfile", "-File", str(ROOT / "start-trained-qwen.ps1"), "-Size", size]
                stop = [powershell, "-NoProfile", "-File", str(ROOT / "stop-trained-qwen.ps1"), "-Size", size]
                port = 18082 if size == "4B" else 18083
            else:
                start = [powershell, "-NoProfile", "-File", str(WORKSPACE / "local-inference" / f"start-qwen{helper_suffix}.ps1")]
                stop = [powershell, "-NoProfile", "-File", str(WORKSPACE / "local-inference" / f"stop-qwen{helper_suffix}.ps1")]
                port = 18080 if size == "4B" else 18081
            stage = {"id": ("trained-" if trained else "base-") + tag, "size": size, "trained": trained,
                "start": start, "stop": stop, "port": port, "model_alias": f"qwen3.5-{tag}" + ("-lanm" if trained else ""),
                "smoke": [python, str(ROOT / "check_platform_integration.py"), "--size", size, "--run", "--profiles-file", str(profiles_file)] if trained else None,
                "benchmarks": []}
            for thinking in (False, True):
                suffix = "-thinking" if thinking else ""
                profile_id = (f"qwen-{tag}-trained{suffix}" if trained else f"qwen-{tag}-thinking" if thinking
                              else "qwen-local" if size == "4B" else "qwen-9b-local")
                stem = f"qwen{digit}" + ("-trained" if trained else "") + suffix
                for amended in (False, True):
                    runner = WORKSPACE / "platform/evaluations" / ("clarified_method.py" if amended else "compare.py")
                    report = output / (("clarified-" if amended else "") + stem + ".json")
                    command = [python, str(runner), "--run", "--profiles-file", str(profiles_file), "--profile", profile_id,
                               "--repeat", "3", "--timeout", "300", "--output", str(report)]
                    if not amended:
                        command.append("--workflows")
                    stage["benchmarks"].append({"profile_id": profile_id, "thinking": thinking, "clarified": amended,
                        "output": str(report), "log": str(report.with_suffix(".log")), "command": command,
                        "case_ids": [clarified.CASE_ID] if amended else ORIGINAL_CASE_IDS,
                        "expected_attempts": 3 if amended else 3 * len(ORIGINAL_CASE_IDS),
                        "profile": comparison.public_profile(by_id[profile_id]) if profile_id in by_id else None})
            stages.append(stage)
    required = sorted({benchmark["profile_id"] for stage in stages for benchmark in stage["benchmarks"]})
    files = [Path(__file__), ROOT / "check_platform_integration.py", Path(comparison.__file__), Path(clarified.__file__),
             Path(comparison.workflows.__file__)]
    source_hashes = {str(path.relative_to(WORKSPACE)): sha(path) for path in files}
    source_hashes.update({"platform/src/lanm_platform/" + name: value
        for name, value in clarified.report_template([], False)["implementation_sha256"].items()})
    return {"status": "prepared_no_model_requests", "created_at": datetime.now(timezone.utc).isoformat(),
        "profiles_file": str(profiles_file), "profiles_sha256": sha(profiles_file), "output_directory": str(output),
        "required_profile_ids": required, "missing_profiles": [name for name in required if name not in by_id],
        "benchmark_attempts": sum(item["expected_attempts"] for stage in stages for item in stage["benchmarks"]),
        "integration_smokes": 2, "repetitions": 3, "case_timeout_seconds": 300,
        "source_sha256": source_hashes, "stages": stages,
        "policy": "Execution requires --run and both completed real adapters. One server at a time; exact identity-checked stop helpers only. Failures are retained, not retried selectively. No profile registration or training-data changes."}


def report_identity(plan, stage, benchmark):
    return {"profile": benchmark["profile"], "case_ids": benchmark["case_ids"], "repeat": 3, "timeout": 300,
        "source_sha256": plan["source_sha256"], "artifact_identity": stage["artifact_identity"]}


def validate_report(report, benchmark, require_complete=False):
    expected_suite = "lanm_clarified_method_comparison" if benchmark["clarified"] else "lanm_provider_comparison"
    runner = Path(clarified.__file__) if benchmark["clarified"] else Path(comparison.__file__)
    if (report.get("suite_id") != expected_suite or report.get("profiles") != [benchmark["profile"]]
            or report.get("repeat") != 3 or report.get("timeout_seconds") != 300
            or report.get("selected_case_ids") != benchmark["case_ids"] or report.get("harness_sha256") != sha(runner)
            or report.get("workflow_implementation_sha256") != sha(Path(comparison.workflows.__file__))
            or report.get("local_tool_allowlist") != comparison.LOCAL_TOOLS or report.get("build_tool_allowlist") != comparison.BUILD_TOOLS):
        raise ValueError("Existing report configuration differs: " + benchmark["output"])
    expected = {(benchmark["profile_id"], case, repetition) for case in benchmark["case_ids"] for repetition in (1, 2, 3)}
    keys = [(row["profile_id"], row["id"], row["repetition"]) for row in report.get("results", [])]
    if len(keys) != len(set(keys)) or not set(keys) <= expected:
        raise ValueError("Duplicate or out-of-plan attempts: " + benchmark["output"])
    if any(row.get("status") not in {"completed", "error", "timeout", "cancelled", "incomplete"} for row in report.get("results", [])):
        raise ValueError("Report contains a nonterminal attempt")
    if report.get("implementation_sha256") != clarified.report_template([], False)["implementation_sha256"]:
        raise ValueError("Runtime implementation differs from frozen queue source")
    complete = report.get("status") == "run_finished" and set(keys) == expected
    if require_complete and not complete:
        raise ValueError("Benchmark did not produce every planned attempt: " + benchmark["output"])
    if benchmark["clarified"] and report.get("clarification", {}).get("prompt_sha256") != clarified.digest(clarified.PROMPT):
        raise ValueError("Clarified prompt identity differs")
    return complete


def validate_execution(plan, resume):
    """CPU/file checks only; fail before starting/stopping a server or calling HTTP."""
    if plan["missing_profiles"]:
        raise ValueError("Register required profiles first: " + ", ".join(plan["missing_profiles"]))
    trained = {size: validate_artifacts(size) for size in ("4B", "9B")}
    profiles = {item["profile_id"]: item["profile"] for stage in plan["stages"] for item in stage["benchmarks"]}
    inference = WORKSPACE / "local-inference"
    runtime_sha = sha(inference / "llama-b12323/llama-server.exe")
    for stage in plan["stages"]:
        size = stage["size"]
        base_name = "provenance.json" if size == "4B" else "provenance-9b.json"
        provenance = json.loads((inference / base_name).read_text(encoding="utf-8"))
        model = inference / f"Qwen3.5-{size}-Q4_K_M.gguf"
        expected = next(asset["sha256"] for asset in provenance["assets"] if asset["file"] == model.name)
        if sha(model) != expected:
            raise ValueError("Frozen base model checksum differs")
        identity = {"base_gguf_sha256": expected, "llama_server_sha256": runtime_sha}
        if stage["trained"]:
            manifest, exported = trained[size]
            identity.update(adapter_sha256=manifest["adapter_sha256"], adapter_config_sha256=manifest["adapter_config_sha256"],
                            adapter_gguf_sha256=exported["gguf_sha256"], training_identity=manifest["identity"])
        stage["artifact_identity"] = identity
        for item in stage["benchmarks"]:
            profile = item["profile"]
            if (profile.get("backend") != "compatible" or profile.get("model") != stage["model_alias"]
                    or profile.get("base_url", "").rstrip("/") != f"http://127.0.0.1:{stage['port']}/v1"
                    or profile.get("enable_thinking") is not item["thinking"]):
                raise ValueError("Profile identity or thinking setting differs: " + item["profile_id"])
            if stage["trained"]:
                base_id = f"qwen-{size.lower()}-thinking" if item["thinking"] else "qwen-local" if size == "4B" else "qwen-9b-local"
                peer = profiles[base_id]
                if any(profile.get(key) != peer.get(key) for key in ("request_timeout", "max_tool_rounds", "max_output_tokens", "domain_grounding", "effort")):
                    raise ValueError("Trained/base inference controls differ: " + item["profile_id"])
                if any(profile.get("metadata", {}).get(key) != peer.get("metadata", {}).get(key)
                       for key in ("temperature", "seed", "context_length", "quantization", "server_version", "hardware")):
                    raise ValueError("Trained/base runtime metadata differs: " + item["profile_id"])
            path = Path(item["output"])
            sidecar = path.with_suffix(".identity.json")
            identity = report_identity(plan, stage, item)
            if path.exists() and not resume:
                raise ValueError("Report exists; --resume is required: " + str(path))
            if sidecar.exists() and json.loads(sidecar.read_text(encoding="utf-8")) != identity:
                raise ValueError("Existing report has another adapter/source identity: " + str(path))
            if path.exists():
                if not sidecar.exists():
                    raise ValueError("Existing report lacks this queue's artifact identity sidecar: " + str(path))
                validate_report(json.loads(path.read_text(encoding="utf-8")), item)


def invoke(command, log=None, append=False):
    options = {"cwd": str(WORKSPACE)}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    if log:
        path = Path(log)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a" if append else "w", encoding="utf-8") as stream:
            return subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, **options).returncode
    return subprocess.run(command, **options).returncode


def request_json(url):
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.load(response)


def wait_ready(stage, timeout=180):
    deadline = time.monotonic() + timeout
    endpoint = f"http://127.0.0.1:{stage['port']}"
    while True:
        try:
            health = request_json(endpoint + "/health")
            if health.get("status") != "ok":
                raise urllib.error.URLError("Model is still loading")
            models = request_json(endpoint + "/v1/models")
            if not any(item.get("id") == stage["model_alias"] for item in models.get("data", [])):
                raise ValueError("Server exposes a different model alias")
            loaded = request_json(endpoint + "/lora-adapters")
            if stage["trained"]:
                tag = stage["size"].lower()
                validate_loaded_adapter(loaded, ROOT / f"runs/qwen-{tag}-lanm/qwen-{tag}-lanm-lora-f16.gguf")
            elif loaded != []:
                raise ValueError("Base benchmark server has an active adapter")
            return {"model_alias": stage["model_alias"], "loaded_adapters": loaded}
        except (urllib.error.URLError, TimeoutError, OSError):
            if time.monotonic() >= deadline:
                raise TimeoutError("Expected server did not become ready: " + stage["id"])
            time.sleep(1)


def execute(plan, resume=False):
    validate_execution(plan, resume)
    lock = ROOT / "post-training-queue.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps({"pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat()}))
    state_path = ROOT / "post-training-queue-state.json"
    state = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat(), "completed_reports": []}
    try:
        save(ROOT / "post-training-executed-plan.json", plan)
        for stage in plan["stages"]:
            state["stage"] = stage["id"]
            pending = []
            for item in stage["benchmarks"]:
                path = Path(item["output"])
                if path.exists() and validate_report(json.loads(path.read_text(encoding="utf-8")), item):
                    state["completed_reports"].append({"path": str(path), "sha256": sha(path), "retained_existing": True})
                else:
                    pending.append(item)
            if not pending:
                continue
            attempted_start = False
            try:
                state["phase"] = "starting_server"
                save(state_path, state)
                attempted_start = True
                if invoke(stage["start"]) != 0:
                    raise RuntimeError("Start helper failed: " + stage["id"])
                state["server_identity"] = wait_ready(stage)
                if stage["smoke"]:
                    state["phase"] = "platform_integration_smoke"
                    save(state_path, state)
                    if invoke(stage["smoke"]) != 0:
                        raise RuntimeError("Actual platform integration smoke failed: " + stage["id"])
                for item in pending:
                    path = Path(item["output"])
                    save(path.with_suffix(".identity.json"), report_identity(plan, stage, item))
                    state.update(phase="benchmark", current_report=str(path), profile_id=item["profile_id"])
                    save(state_path, state)
                    wait_ready(stage)
                    command = item["command"] + (["--resume"] if path.exists() else [])
                    print("Running " + item["profile_id"] + ": " + path.name, flush=True)
                    code = invoke(command, item["log"], append=path.exists())
                    # Read only after process exit: concurrent reads can block atomic replacement on Windows.
                    report = json.loads(path.read_text(encoding="utf-8"))
                    validate_report(report, item, require_complete=True)
                    if code not in (0, 1):
                        raise RuntimeError("Unexpected benchmark process failure: " + str(code))
                    state["completed_reports"].append({"path": str(path), "sha256": sha(path), "exit_code": code})
                    save(state_path, state)
            finally:
                if attempted_start:
                    state["phase"] = "stopping_server"
                    save(state_path, state)
                    if invoke(stage["stop"]) != 0:
                        raise RuntimeError("Identity-checked stop helper failed; queue will not start another server")
        state.update(status="completed", phase="finished", finished_at=datetime.now(timezone.utc).isoformat())
        save(state_path, state)
        return 0
    except Exception as error:
        state.update(status="failed", error=str(error))
        save(state_path, state)
        raise
    finally:
        lock.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--prepare", action="store_true", help="Write a reviewable plan without model/server calls (default)")
    action.add_argument("--run", action="store_true", help="Explicitly execute the post-training server/smoke/benchmark queue")
    parser.add_argument("--profiles-file", type=Path, default=DEFAULT_OUTPUT / "profiles.json")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--plan", type=Path, default=ROOT / "post-training-queue-plan.json")
    parser.add_argument("--resume", action="store_true", help="Keep completed attempts and continue only missing work")
    args = parser.parse_args(argv)
    if args.resume and not args.run:
        parser.error("--resume requires explicit --run")
    plan_path = args.plan.resolve()
    if not plan_path.is_relative_to(ROOT) or plan_path.is_relative_to(ROOT / "data"):
        parser.error("Plan must stay under local-training and outside frozen data/")
    plan = build_plan(args.profiles_file, args.output_dir)
    if args.run:
        return execute(plan, args.resume)
    save(plan_path, plan)
    print(json.dumps({"status": plan["status"], "plan": str(plan_path), "benchmark_attempts": plan["benchmark_attempts"],
                      "missing_profiles": plan["missing_profiles"], "server_or_model_calls": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
