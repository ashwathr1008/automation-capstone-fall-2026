"""Bind omitted training metadata to pre-execution identities and completed reports."""
from __future__ import annotations

import json
from pathlib import Path

from verify_comparison_training import file_identity


def verify_profile_evidence(report_profiles, reports, declarations, *, profiles_path, plan_path, state_path, workspace,
                            archived_manifest=None, archived_manifest_sha256=None):
    # Use the exact report projection used by the frozen runner, not a looser subset test.
    from compare import load_profiles, public_profile

    cache = {}
    files = {name: file_identity(path, cache) for name, path in
             (("runtime_profiles", profiles_path), ("executed_plan", plan_path), ("completed_queue_state", state_path))}
    plan = json.loads(Path(files["executed_plan"]["path"]).read_bytes())
    state = json.loads(Path(files["completed_queue_state"]["path"]).read_bytes())
    if plan.get("profiles_sha256") != files["runtime_profiles"]["sha256"]:
        raise ValueError("Runtime profiles differ from the recorded executed-plan checksum")
    if state.get("status") != "completed" or state.get("phase") != "finished" or plan.get("missing_profiles"):
        raise ValueError("A completed queue with all registered profiles is required")
    archived = {}
    if bool(archived_manifest) != bool(archived_manifest_sha256):
        raise ValueError("Archived-source resolution requires both manifest path and its expected checksum")
    if archived_manifest:
        identity = file_identity(archived_manifest, cache)
        if identity["sha256"] != archived_manifest_sha256:
            raise ValueError("Archived-source manifest checksum differs")
        files["archived_source_manifest"] = identity
        entries = json.loads(Path(identity["path"]).read_bytes()).get("files", [])
        archived = {row["path"].replace("\\", "/"): row for row in entries}
        if len(archived) != len(entries):
            raise ValueError("Duplicate source path in archive manifest")
    resolutions = []
    for name, digest in plan.get("source_sha256", {}).items():
        path = Path(workspace) / name.replace("\\", "/")
        current = file_identity(path, cache) if path.is_file() else None
        location = "current_workspace"
        if current is None or current["sha256"] != digest:
            record = archived.get(name.replace("\\", "/"))
            if not record or record.get("sha256") != digest:
                raise ValueError("Executed-plan frozen source differs: " + name)
            archive_root = Path(files["archived_source_manifest"]["path"]).parent
            path = (archive_root / record.get("archive_path", Path(record["path"]).name)).resolve()
            if not path.is_relative_to(archive_root):
                raise ValueError("Archived source resolves outside its manifest directory")
            current = file_identity(path, cache)
            if current["sha256"] != digest or current["bytes"] != record.get("bytes"):
                raise ValueError("Archived source bytes differ: " + name)
            location = "verified_archive"
        resolutions.append({"original_source": name, "expected_sha256": digest, "location": location, "resolved_source": current})
    if not plan.get("source_sha256"):
        raise ValueError("Executed plan lacks frozen source identities")
    profiles = {item["id"]: item for item in load_profiles(profiles_path)}
    if set(profiles) != set(report_profiles):
        raise ValueError("Full runtime profile population differs from the reports")
    for identifier, reported in report_profiles.items():
        if public_profile(profiles[identifier]) != reported:
            raise ValueError("Runtime profile projection differs from frozen report: " + identifier)
    completed = {Path(item["path"]).resolve(): item["sha256"] for item in state.get("completed_reports", [])}
    if len(completed) != len(state.get("completed_reports", [])):
        raise ValueError("Duplicate report in completed queue state")
    planned = {}
    for stage in plan.get("stages", []):
        for item in stage.get("benchmarks", []):
            path = Path(item["output"]).resolve()
            if path in planned:
                raise ValueError("Duplicate report in executed plan")
            planned[path] = stage, item
    bindings = []
    for source, report, digest in reports:
        identifier = report["profiles"][0]["id"]
        declaration = declarations[identifier]
        if declaration.get("training") != "trained":
            continue
        path = Path(source).resolve()
        if path not in planned or completed.get(path) != digest:
            raise ValueError("Trained report is not bound to the completed queue: " + path.name)
        stage, item = planned[path]
        artifact = stage.get("artifact_identity", {})
        if not stage.get("trained") or item.get("profile") != report["profiles"][0]:
            raise ValueError("Executed stage/profile differs from trained report: " + path.name)
        identity_path = path.with_suffix(".identity.json")
        if not identity_path.is_file():
            raise ValueError("Missing recorded per-report artifact identity: " + path.name)
        identity = json.loads(identity_path.read_bytes())
        expected = {"profile": item["profile"], "case_ids": item["case_ids"], "repeat": 3, "timeout": 300,
                    "source_sha256": plan["source_sha256"], "artifact_identity": artifact}
        if identity != expected or report.get("selected_case_ids") != item["case_ids"]:
            raise ValueError("Recorded per-report artifact identity differs: " + path.name)
        if (artifact.get("adapter_sha256") != declaration["training_artifact_sha256"]
                or artifact.get("adapter_gguf_sha256") != declaration["adapter_gguf_sha256"]
                or artifact.get("training_identity", {}).get("train_sha256") != declaration["training_data_sha256"]):
            raise ValueError("Recorded adapter/data identity differs: " + path.name)
        bindings.append({"profile_id": identifier, "report": {"path": str(path), "sha256": digest},
                         "recorded_identity": file_identity(identity_path, cache), "artifact_identity": artifact})
    trained = {key for key, value in declarations.items() if value.get("training") == "trained"}
    if len(bindings) != 2 * len(trained) or any(sum(row["profile_id"] == key for row in bindings) != 2 for key in trained):
        raise ValueError("Each trained profile needs its original and clarified recorded identity")
    return profiles, {"verified": True, "files": files, "source_resolutions": resolutions, "trained_report_bindings": bindings,
        "disclosure": "The frozen report serializer omitted training-specific metadata. Full-profile metadata is verified separately against the executed plan's profile checksum, exact report-visible profile projection, per-report artifact identities and completed queue report hashes. Raw reports remain unchanged."}
