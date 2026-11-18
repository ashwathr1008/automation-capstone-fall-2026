"""Verify an exported trained adapter through the real LanM runtime in a fresh project."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
sys.path.insert(0, str(WORKSPACE / "platform/src"))
from lanm_platform.core import Store
from lanm_platform.providers import runtime_factory_for

LLAMA_COMMIT = "93cf736a8d1d46aa922e27eb64aa712bcd5ebc30"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_artifacts(size, run_dir=None):
    """Validate one completed real adapter without loading weights or using a GPU."""
    if size not in {"4B", "9B"}:
        raise ValueError("Unsupported model size")
    run = Path(run_dir).resolve() if run_dir else ROOT / "runs" / f"qwen-{size.lower()}-lanm"
    if not run.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("Adapter run must stay within local-training")
    manifest, exported = read_json(run / "run-manifest.json"), read_json(run / "export-manifest.json")
    if manifest.get("status") != "completed" or exported.get("synthetic") is not False:
        raise ValueError("A completed real trained adapter is required")
    if manifest.get("args", {}).get("size") != size:
        raise ValueError("Training size differs from requested adapter size")
    if (manifest.get("global_step", 0) <= 0 or manifest.get("nonzero_lora_b_elements", 0) <= 0
            or manifest.get("completed_epochs", 0) + 1e-6 < manifest.get("args", {}).get("epochs", 1)):
        raise ValueError("Manifest does not establish a completed nonzero adapter training run")
    base = ROOT / "models" / f"Qwen3.5-{size}"
    provenance = read_json(base / "download-manifest.json")
    if (provenance.get("complete") is not True or manifest.get("base_repo") != f"Qwen/Qwen3.5-{size}"
            or manifest.get("base_repo") != provenance.get("repo_id") or manifest.get("base_revision") != provenance.get("revision")
            or manifest.get("base_download_manifest_sha256") != sha(base / "download-manifest.json")):
        raise ValueError("Training base identity or provenance differs from local verified base")
    config_sha = sha(base / "config.json")
    if config_sha != manifest.get("identity", {}).get("base_config_sha256") or config_sha != exported.get("base_config_sha256"):
        raise ValueError("Training/export base configuration identity mismatch")
    if exported.get("llama_cpp_commit") != LLAMA_COMMIT or exported.get("runtime") != "llama.cpp b12323":
        raise ValueError("Export does not match the frozen inference runtime")
    learned_sha = sha(run / "adapter/adapter_model.safetensors")
    if learned_sha != manifest.get("adapter_sha256") or learned_sha != exported.get("adapter_sha256"):
        raise ValueError("Learned adapter and GGUF export do not have the same training origin")
    if sha(run / "adapter/adapter_config.json") != manifest.get("adapter_config_sha256"):
        raise ValueError("Learned adapter configuration checksum mismatch")
    adapter = run / f"qwen-{size.lower()}-lanm-lora-f16.gguf"
    if sha(adapter) != exported.get("gguf_sha256") or adapter.stat().st_size != exported.get("gguf_bytes"):
        raise ValueError("Exported adapter checksum or size mismatch")
    return manifest, exported


def validate_loaded_adapter(loaded, adapter):
    if (not isinstance(loaded, list) or len(loaded) != 1 or not isinstance(loaded[0], dict)
            or not isinstance(loaded[0].get("path"), str)
            or Path(loaded[0]["path"]).resolve() != Path(adapter).resolve()
            or isinstance(loaded[0].get("scale"), bool) or loaded[0].get("scale") != 1):
        raise ValueError("Expected trained adapter must be the sole active adapter at scale 1")


def smoke_checks(initial, final, trace, events, done, timed_out, answer):
    terminal = next((event for event in reversed(events) if event.get("type") in {"done", "error"}), {})
    identity = ("id", "name", "target", "competitor", "revision", "assumptions", "configuration", "experiment_count", "accepted_experiment_count")
    successful = [entry for entry in trace if entry.get("type") == "tool_call" and entry.get("success") is True]
    actual_reads = [entry for entry in successful if entry.get("name") == "project_state"
        and entry.get("arguments", {}).get("project_id") == initial["id"]
        and isinstance(entry.get("result"), dict)
        and all(entry["result"].get(key) == initial[key] for key in identity)]
    return {"completed": bool(done and not timed_out and terminal.get("type") == "done"
                             and terminal.get("status") not in {"cancelled", "interrupted", "error"}),
        "real_lanm_tool_call": bool(actual_reads),
        "only_read_only_tools_succeeded": all(entry.get("name") == "project_state" for entry in successful),
        "project_unchanged": all(initial[key] == final[key] for key in identity),
        "answer_present": bool(isinstance(answer, str) and answer.strip())}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", choices=["4B", "9B"], required=True)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--profiles-file", type=Path, default=ROOT / "profiles.example.json")
    args = parser.parse_args(argv)
    tag = args.size.lower()
    run = ROOT / "runs" / f"qwen-{tag}-lanm"
    manifest, exported = validate_artifacts(args.size, run)
    adapter = run / f"qwen-{tag}-lanm-lora-f16.gguf"

    base_profiles = read_json(args.profiles_file)["profiles"]
    base_id = "qwen-local" if args.size == "4B" else "qwen-9b-local"
    profile = deepcopy(next(p for p in base_profiles if p["id"] == base_id))
    port = 18082 if args.size == "4B" else 18083
    profile.update(id=f"qwen-{tag}-trained", name=f"Qwen3.5 {args.size} · LanM trained",
                   model=f"qwen3.5-{tag}-lanm", base_url=f"http://127.0.0.1:{port}/v1")
    profile.setdefault("metadata", {}).update(training_artifact_sha256=manifest["adapter_sha256"],
                               adapter_gguf_sha256=exported["gguf_sha256"], training="LanM LoRA")
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=10) as response:
        models = json.load(response)
    if not any(item.get("id") == profile["model"] for item in models.get("data", [])):
        raise ValueError("Server does not expose the expected trained model alias")
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/lora-adapters", timeout=10) as response:
        loaded = json.load(response)
    validate_loaded_adapter(loaded, adapter)

    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "profile": profile,
              "adapter_sha256": manifest["adapter_sha256"], "adapter_gguf_sha256": exported["gguf_sha256"],
              "loaded_adapters": loaded, "server_models": models, "benchmark_result": False,
              "purpose": "Independent read-only platform integration smoke; excluded from benchmark scores"}
    smoke_profile = deepcopy(profile)
    smoke_profile.update(request_timeout=30, max_tool_rounds=3, max_output_tokens=1024)
    result["smoke_limits"] = {key: smoke_profile[key] for key in ["request_timeout", "max_tool_rounds", "max_output_tokens"]}
    started = time.monotonic()
    temp_root = WORKSPACE / ".test-data"
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="trained-adapter-smoke-", dir=temp_root) as temporary:
        store = Store(temporary)
        project = store.create_project(f"Adapter connectivity {args.size}", "Dy", "Y")
        initial = store.get_project(project["id"])
        runtime = runtime_factory_for(smoke_profile, tool_allowlist=["project_state"])(store, Path(temporary))
        job = None
        timed_out = False
        try:
            job = runtime.submit(project["id"],
                "Call project_state for the active project, then report its project name, target metal and competitor metal. Do not modify the project.",
                mode="research", model=profile["model"])
            deadline = time.monotonic() + 120
            while not job.done and time.monotonic() < deadline:
                with job.condition:
                    job.condition.wait(timeout=0.25)
            if not job.done:
                timed_out = True
                runtime.cancel(job.id)
        finally:
            runtime.close()
        if job is None:
            raise RuntimeError("No platform conversation was created")
        with job.condition:
            result.update(answer=job.text, events=deepcopy(job.events), trace=deepcopy(job.trace),
                          metrics=deepcopy(job.metrics))
        final = store.get_project(project["id"])
        checks = smoke_checks(initial, final, result["trace"], result["events"], job.done, timed_out, result["answer"])
        result.update(checks=checks, passed=all(checks.values()), elapsed_seconds=time.monotonic()-started)
    result["temporary_project_removed"] = True
    output = run / "integration-smoke.json"
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    print(json.dumps({"size": args.size, "passed": result["passed"], "checks": checks, "report": str(output)}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
