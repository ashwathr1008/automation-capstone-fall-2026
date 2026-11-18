"""Reject stale, untrained, or different served artifacts in final analysis."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("verify_comparison_training", Path(__file__).resolve().parents[1] / "evaluations/verify_comparison_training.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(root):
    raw, evaluated = root / "weights.safetensors", root / "weights.gguf"
    raw.write_bytes(b"learned raw fixture")
    evaluated.write_bytes(b"served export fixture")
    a, b, data = hashlib.sha256(raw.read_bytes()).hexdigest(), hashlib.sha256(evaluated.read_bytes()).hexdigest(), "d" * 64
    run = {"status": "completed", "global_step": 7, "completed_epochs": 1, "args": {"epochs": 1},
           "nonzero_lora_b_elements": 16, "adapter_sha256": a, "base_revision": "official-revision",
           "identity": {"base_config_sha256": "c" * 64, "train_sha256": data}, "data": {"train_sha256": data}}
    exported = {"synthetic": False, "finite_tensors": True, "nonzero_lora_b_elements": 16,
                "adapter_sha256": a, "gguf_sha256": b, "gguf_bytes": evaluated.stat().st_size, "base_config_sha256": "c" * 64}
    smoke = {"passed": True, "adapter_sha256": a, "adapter_gguf_sha256": b,
             "loaded_adapters": [{"path": str(evaluated), "scale": 1}],
             "checks": dict.fromkeys(["completed", "real_lanm_tool_call", "only_read_only_tools_succeeded", "project_unchanged", "answer_present"], True)}
    for name, value in (("run-manifest", run), ("export-manifest", exported), ("integration-smoke", smoke)):
        (root / (name + ".json")).write_text(json.dumps(value), encoding="utf-8")
    declaration = {"profile_id": "qwen-4b-trained", "training_artifact_path": str(raw), "training_artifact_sha256": a,
                   "evaluated_adapter_path": str(evaluated), "adapter_gguf_sha256": b, "training_data_sha256": data,
                   "provenance_path": str(root / "run-manifest.json"), "export_provenance_path": str(root / "export-manifest.json")}
    profile = {"metadata": {key: declaration[key] for key in ("training_artifact_sha256", "adapter_gguf_sha256", "training_data_sha256")}}
    profile["metadata"]["training_base_revision"] = "official-revision"
    return declaration, profile


class TrainingIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.declaration, self.profile = fixture(self.root)

    def modify(self, name, operation):
        path = self.root / (name + ".json")
        value = json.loads(path.read_text(encoding="utf-8"))
        operation(value)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_completed_training_raw_export_and_smoke_identity_verified(self):
        result = module.verify_training(self.declaration, self.profile)
        self.assertTrue(result["verified"])
        self.assertEqual(result["training"]["global_step"], 7)
        self.assertNotEqual(result["raw_adapter"]["sha256"], result["evaluated_adapter"]["sha256"])

    def test_changed_evaluated_weights_refused_even_when_raw_adapter_matches(self):
        Path(self.declaration["evaluated_adapter_path"]).write_bytes(b"other served adapter")
        with self.assertRaisesRegex(ValueError, "evaluated adapter hash"):
            module.verify_training(self.declaration, self.profile)

    def test_zero_updates_or_incomplete_training_refused(self):
        for updates in ({"global_step": 0}, {"nonzero_lora_b_elements": 0}, {"completed_epochs": 0.5}):
            self.declaration, self.profile = fixture(self.root)
            self.modify("run-manifest", lambda v: v.update(updates))
            with self.assertRaises(ValueError):
                module.verify_training(self.declaration, self.profile)

    def test_smoke_must_use_same_adapter_and_only_one_active_at_scale_one(self):
        for change in ({"adapter_sha256": "a" * 64}, {"loaded_adapters": []},
                       {"loaded_adapters": [{"path": self.declaration["evaluated_adapter_path"], "scale": True}]}):
            self.declaration, self.profile = fixture(self.root)
            self.modify("integration-smoke", lambda v: v.update(change))
            with self.assertRaisesRegex(ValueError, "smoke"):
                module.verify_training(self.declaration, self.profile)

    def test_runtime_profile_cannot_claim_different_training_data_or_base(self):
        for key in ("training_data_sha256", "training_base_revision"):
            profile = deepcopy(self.profile)
            profile["metadata"][key] = "different"
            with self.assertRaisesRegex(ValueError, "runtime"):
                module.verify_training(self.declaration, profile)


if __name__ == "__main__":
    unittest.main()
