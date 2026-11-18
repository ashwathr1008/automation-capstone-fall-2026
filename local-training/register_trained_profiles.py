"""Register verified learned LanM adapters without changing existing model profiles."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from check_platform_integration import validate_artifacts, sha
from prepare_workspace import DEFAULT_BENCHMARK

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
BENCHMARK = DEFAULT_BENCHMARK


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".registration-tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Write the validated profiles; otherwise show the plan")
    parser.add_argument("--benchmark-dir", type=Path, default=BENCHMARK)
    parser.add_argument("--app-profiles", type=Path, default=WORKSPACE / "research-data/model_profiles.json")
    args = parser.parse_args()
    benchmark_path = args.benchmark_dir.resolve() / "profiles.json"
    app_path = args.app_profiles.resolve()
    analysis_path = args.benchmark_dir.resolve() / "analysis-configurations.json"
    if not args.benchmark_dir.resolve().is_relative_to(WORKSPACE / "benchmark-results"):
        raise ValueError("Benchmark configuration must stay under benchmark-results/")
    if not app_path.parent.is_dir():
        raise ValueError("Restore the research workspace before registering its app profiles")
    benchmark, app, analysis = (read(path if path.exists() else template) for path, template in (
        (benchmark_path, ROOT / "profiles.example.json"), (app_path, WORKSPACE / "platform/model_profiles.example.json"),
        (analysis_path, ROOT / "analysis-configurations.example.json")))
    additions, identities = [], {}
    for size, base_id, port in [("4B", "qwen-local", 18082), ("9B", "qwen-9b-local", 18083)]:
        tag = size.lower()
        run = ROOT / "runs" / f"qwen-{tag}-lanm"
        manifest, exported = validate_artifacts(size)
        settings = manifest["args"]
        base = next(p for p in benchmark["profiles"] if p["id"] == base_id)
        if manifest["identity"]["train_sha256"] != sha(ROOT / "data/train.jsonl"):
            raise ValueError("Training corpus identity changed")
        if manifest["identity"]["validation_sha256"] != sha(ROOT / "data/validation.jsonl"):
            raise ValueError("Validation corpus identity changed")
        identities[size] = {"adapter_sha256": manifest["adapter_sha256"],
                            "adapter_gguf_sha256": exported["gguf_sha256"],
                            "run_manifest_sha256": sha(run / "run-manifest.json"),
                            "export_manifest_sha256": sha(run / "export-manifest.json")}
        for thinking in (False, True):
            profile = deepcopy(base)
            profile_id = f"qwen-{tag}-trained" + ("-thinking" if thinking else "")
            profile.update(id=profile_id, name=f"Local Qwen3.5 {size} · LanM trained" + (" · thinking" if thinking else ""),
                           model=f"qwen3.5-{tag}-lanm", base_url=f"http://127.0.0.1:{port}/v1", enable_thinking=thinking)
            profile.pop("domain_grounding", None)
            profile.setdefault("metadata", {}).update(thinking=thinking, training="LanM LoRA",
                                       training_method=f"{settings['precision']}, rank {settings['rank']}, {settings['epochs']:g} epochs",
                                       training_artifact_sha256=manifest["adapter_sha256"], adapter_gguf_sha256=exported["gguf_sha256"],
                                       training_data_sha256=manifest["identity"]["train_sha256"],
                                       training_base_revision=manifest["base_revision"],
                                       training_provenance_path=str(run / "run-manifest.json"))
            additions.append(profile)
            entry = next(c for c in analysis["configurations"] if c["profile_id"] == profile_id)
            entry.update(display_name=f"Qwen {size} · trained · thinking {'on' if thinking else 'off'}", training="trained",
                         model=profile["model"], checkpoint=f"Qwen3.5-{size} Q4_K_M + LanM LoRA",
                         training_artifact_path=str(run / "adapter/adapter_model.safetensors"),
                         training_artifact_sha256=manifest["adapter_sha256"],
                         evaluated_adapter_path=str(run / f"qwen-{tag}-lanm-lora-f16.gguf"),
                         adapter_gguf_sha256=exported["gguf_sha256"],
                         training_data_sha256=manifest["identity"]["train_sha256"],
                         provenance_path=str(run / "run-manifest.json"),
                         export_provenance_path=str(run / "export-manifest.json"))
            entry.pop("notes", None)
    hosted = [deepcopy(p) for p in benchmark["profiles"] if p["id"] in {"claude-sonnet", "claude-opus"}]
    for document, new_profiles in [(benchmark, additions), (app, additions + hosted)]:
        by_id = {p["id"]: p for p in document["profiles"]}
        for profile in new_profiles:
            if profile["id"] in by_id and by_id[profile["id"]] != profile:
                raise ValueError("Refusing to replace a different existing profile: " + profile["id"])
            if profile["id"] not in by_id:
                document["profiles"].append(profile)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "written": args.run,
              "trained_profiles": [p["id"] for p in additions], "identities": identities,
              "serving_validation": "Separate integration-smoke.json is required before benchmark execution",
              "app_restart_required": "An already-running platform loads profiles at startup; restart it to see additions."}
    if args.run:
        for path, document in [(benchmark_path, benchmark), (app_path, app), (analysis_path, analysis)]:
            backup = path.with_suffix(path.suffix + ".before-trained-profiles")
            if path.exists() and not backup.exists():
                backup.write_bytes(path.read_bytes())
            save(path, document)
        save(ROOT / "profiles-registration.json", report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
