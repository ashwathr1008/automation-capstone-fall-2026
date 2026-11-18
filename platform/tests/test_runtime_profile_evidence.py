"""Omitted metadata needs an executed identity chain, not current config alone."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluations"))
from compare import public_profile
from verify_runtime_profile_evidence import verify_profile_evidence


def write(path, value):
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class RuntimeProfileEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.full = {"id": "trained", "model": "weights", "backend": "compatible", "base_url": "http://127.0.0.1:18082/v1",
                     "metadata": {"seed": 42, "training_artifact_sha256": "a" * 64,
                                  "adapter_gguf_sha256": "b" * 64, "training_data_sha256": "c" * 64}}
        self.projected = public_profile(self.full)
        self.declarations = {"trained": {"training": "trained", **self.full["metadata"]}}
        self.profile_path, self.plan_path, self.state_path = [self.root / name for name in ("profiles.json", "plan.json", "state.json")]
        profiles_hash = write(self.profile_path, {"profiles": [self.full]})
        frozen_hash = write(self.root / "frozen.json", {"version": "frozen"})
        self.plan = {"profiles_sha256": profiles_hash, "missing_profiles": [], "source_sha256": {"frozen.json": frozen_hash}, "stages": []}
        stage = {"trained": True, "artifact_identity": {"adapter_sha256": "a" * 64, "adapter_gguf_sha256": "b" * 64,
                                                        "training_identity": {"train_sha256": "c" * 64}}, "benchmarks": []}
        self.reports, completed = [], []
        for name in ("original", "clarified"):
            path = self.root / (name + ".json")
            report = {"profiles": [self.projected], "selected_case_ids": [name]}
            digest = write(path, report)
            self.reports.append((str(path), report, digest))
            completed.append({"path": str(path), "sha256": digest})
            item = {"output": str(path), "profile": self.projected, "case_ids": [name]}
            stage["benchmarks"].append(item)
            write(path.with_suffix(".identity.json"), {"profile": self.projected, "case_ids": [name], "repeat": 3, "timeout": 300,
                  "source_sha256": self.plan["source_sha256"], "artifact_identity": stage["artifact_identity"]})
        self.plan["stages"].append(stage)
        write(self.plan_path, self.plan)
        self.state = {"status": "completed", "phase": "finished", "completed_reports": completed}
        write(self.state_path, self.state)

    def verify(self, **kwargs):
        return verify_profile_evidence({"trained": self.projected}, self.reports, self.declarations,
            profiles_path=self.profile_path, plan_path=self.plan_path, state_path=self.state_path, workspace=self.root, **kwargs)

    def test_complete_chain_supplies_metadata_without_changing_reports(self):
        before = deepcopy(self.reports)
        profiles, evidence = self.verify()
        self.assertNotIn("training_artifact_sha256", self.projected["metadata"])
        self.assertEqual(profiles["trained"]["metadata"]["training_artifact_sha256"], "a" * 64)
        self.assertEqual(len(evidence["trained_report_bindings"]), 2)
        self.assertEqual(self.reports, before)

    def test_current_profile_change_without_matching_recorded_checksum_is_rejected(self):
        self.full["metadata"]["training_artifact_sha256"] = "f" * 64
        write(self.profile_path, {"profiles": [self.full]})
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.verify()

    def test_visible_profile_change_and_report_hash_change_are_rejected(self):
        self.projected["model"] = "different"
        with self.assertRaisesRegex(ValueError, "projection"):
            self.verify()
        self.projected["model"] = "weights"
        self.state["completed_reports"][0]["sha256"] = "f" * 64
        write(self.state_path, self.state)
        with self.assertRaisesRegex(ValueError, "completed queue"):
            self.verify()

    def test_sidecar_adapter_and_frozen_source_changes_are_rejected(self):
        path = self.root / "original.identity.json"
        original = json.loads(path.read_bytes())
        changed = deepcopy(original)
        changed["artifact_identity"]["adapter_gguf_sha256"] = "f" * 64
        write(path, changed)
        with self.assertRaisesRegex(ValueError, "per-report"):
            self.verify()
        write(path, original)
        write(self.root / "frozen.json", {"version": "changed"})
        with self.assertRaisesRegex(ValueError, "frozen source"):
            self.verify()

    def test_missing_sidecar_and_missing_artifact_hash_are_rejected(self):
        path = self.root / "original.identity.json"
        original = json.loads(path.read_bytes())
        path.unlink()
        with self.assertRaisesRegex(ValueError, "Missing recorded"):
            self.verify()
        del self.plan["stages"][0]["artifact_identity"]["adapter_sha256"]
        write(self.plan_path, self.plan)
        del original["artifact_identity"]["adapter_sha256"]
        write(path, original)
        with self.assertRaisesRegex(ValueError, "adapter/data"):
            self.verify()

    def test_archived_frozen_source_requires_explicit_manifest_checksum_and_exact_bytes(self):
        archive = self.root / "archive"
        archive.mkdir()
        frozen = (self.root / "frozen.json").read_bytes()
        (archive / "frozen.json").write_bytes(frozen)
        manifest = archive / "manifest.json"
        digest = write(manifest, {"files": [{"path": "frozen.json", "sha256": hashlib.sha256(frozen).hexdigest(), "bytes": len(frozen)}]})
        write(self.root / "frozen.json", {"portable": "new source"})
        with self.assertRaisesRegex(ValueError, "frozen source"):
            self.verify()
        _, evidence = self.verify(archived_manifest=manifest, archived_manifest_sha256=digest)
        self.assertEqual(evidence["source_resolutions"][0]["location"], "verified_archive")
        with self.assertRaisesRegex(ValueError, "manifest checksum"):
            self.verify(archived_manifest=manifest, archived_manifest_sha256="f" * 64)
        write(archive / "frozen.json", {"changed": True})
        with self.assertRaisesRegex(ValueError, "Archived source bytes"):
            self.verify(archived_manifest=manifest, archived_manifest_sha256=digest)


if __name__ == "__main__":
    unittest.main()
