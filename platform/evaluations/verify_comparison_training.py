"""Verify finished learned adapters, evaluated exports, and runtime evidence."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

WORKSPACE = Path(__file__).resolve().parents[2]


def _path(value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else WORKSPACE / path).resolve()


def file_identity(path, cache=None):
    path = _path(path)
    if cache is not None and path in cache:
        return cache[path]
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    result = {"path": str(path), "sha256": digest, "bytes": path.stat().st_size}
    if cache is not None:
        cache[path] = result
    return result


def _json(path, cache):
    identity = file_identity(path, cache)
    return json.loads(Path(identity["path"]).read_text(encoding="utf-8")), identity


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_training(declaration, profile, cache=None):
    identifier = declaration["profile_id"]
    cache = {} if cache is None else cache
    required = ("training_artifact_path", "training_artifact_sha256", "evaluated_adapter_path", "adapter_gguf_sha256",
                "provenance_path", "export_provenance_path", "training_data_sha256")
    _require(all(declaration.get(key) for key in required), f"{identifier}: missing trained artifact/provenance fields")
    for key in ("training_artifact_sha256", "adapter_gguf_sha256", "training_data_sha256"):
        _require(bool(re.fullmatch(r"[0-9a-f]{64}", declaration[key])), f"{identifier}: invalid {key}")
        _require(profile.get("metadata", {}).get(key) == declaration[key], f"{identifier}: runtime profile {key} differs")
    raw = file_identity(declaration["training_artifact_path"], cache)
    evaluated = file_identity(declaration["evaluated_adapter_path"], cache)
    _require(raw["sha256"] == declaration["training_artifact_sha256"], f"{identifier}: raw adapter hash mismatch")
    _require(evaluated["sha256"] == declaration["adapter_gguf_sha256"], f"{identifier}: evaluated adapter hash mismatch")
    run, run_file = _json(declaration["provenance_path"], cache)
    exported, export_file = _json(declaration["export_provenance_path"], cache)
    _require(run.get("status") == "completed" and run.get("global_step", 0) > 0
             and run.get("nonzero_lora_b_elements", 0) > 0, f"{identifier}: no completed nonzero learned update")
    _require(run.get("completed_epochs", 0) + 1e-6 >= run.get("args", {}).get("epochs", float("inf")),
             f"{identifier}: requested training epochs did not complete")
    _require(run.get("adapter_sha256") == raw["sha256"], f"{identifier}: run manifest adapter hash mismatch")
    _require(run.get("data", {}).get("train_sha256") == declaration["training_data_sha256"],
             f"{identifier}: training-data identity mismatch")
    _require(exported.get("synthetic") is False and exported.get("finite_tensors") is True
             and exported.get("nonzero_lora_b_elements", 0) > 0, f"{identifier}: export is synthetic or has no finite learned updates")
    _require(exported.get("adapter_sha256") == raw["sha256"] and exported.get("gguf_sha256") == evaluated["sha256"],
             f"{identifier}: raw-to-evaluated export lineage mismatch")
    _require(exported.get("base_config_sha256") == run.get("identity", {}).get("base_config_sha256")
             and bool(exported.get("base_config_sha256")), f"{identifier}: training/export base configuration differs")
    _require(run.get("base_revision") and profile.get("metadata", {}).get("training_base_revision") == run["base_revision"],
             f"{identifier}: runtime training base revision differs")
    _require(run.get("identity", {}).get("train_sha256") == declaration["training_data_sha256"],
             f"{identifier}: run identity training-data hash differs")
    _require(exported.get("gguf_bytes") == evaluated["bytes"], f"{identifier}: export size mismatch")
    smoke_path = declaration.get("integration_smoke_path") or Path(run_file["path"]).parent / "integration-smoke.json"
    smoke, smoke_file = _json(smoke_path, cache)
    required_checks = {"completed", "real_lanm_tool_call", "only_read_only_tools_succeeded", "project_unchanged", "answer_present"}
    checks = smoke.get("checks", {})
    _require(smoke.get("passed") is True and required_checks.issubset(checks)
             and all(value is True for value in checks.values()), f"{identifier}: integration smoke did not pass")
    _require(smoke.get("adapter_sha256") == raw["sha256"] and smoke.get("adapter_gguf_sha256") == evaluated["sha256"],
             f"{identifier}: integration smoke used another adapter")
    loaded = smoke.get("loaded_adapters")
    _require(isinstance(loaded, list) and len(loaded) == 1 and isinstance(loaded[0], dict)
             and loaded[0].get("path") and _path(loaded[0]["path"]) == Path(evaluated["path"])
             and not isinstance(loaded[0].get("scale"), bool) and loaded[0].get("scale") == 1,
             f"{identifier}: smoke did not load the sole evaluated adapter at scale 1")
    return {"profile_id": identifier, "verified": True, "raw_adapter": raw, "evaluated_adapter": evaluated,
            "run_manifest": run_file, "export_manifest": export_file, "integration_smoke": smoke_file,
            "training": {key: run.get(key) for key in ("base_repo", "base_revision", "base_download_manifest_sha256",
                "identity", "args", "data", "global_step", "completed_epochs", "nonzero_lora_b_elements", "train_metrics",
                "validation_before", "validation_after", "elapsed_seconds", "peak_cuda_allocated_bytes", "peak_cuda_reserved_bytes")},
            "export": {key: exported.get(key) for key in ("runtime", "llama_cpp_commit", "converter_sha256", "base_config_sha256", "tensor_count")},
            "smoke_checks": checks,
            "interpretation": "Artifact hashes establish the trained adapter and its served export. The separate smoke verifies one read-only LanM call; benchmark results measure broader task performance."}
