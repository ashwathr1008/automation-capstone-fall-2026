"""CPU-only artifact-chain and platform-trace guards; no model/server calls."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import check_platform_integration as integration


class IntegrationGuardTests(unittest.TestCase):
    def setUp(self):
        (integration.ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=integration.ROOT / "tmp")
        self.root = Path(self.temporary.name)
        self.patch = patch.object(integration, "ROOT", self.root)
        self.patch.start()
        self.run = self.root / "runs/qwen-4b-lanm"
        self.base = self.root / "models/Qwen3.5-4B"
        (self.run / "adapter").mkdir(parents=True)
        self.base.mkdir(parents=True)
        def save(path, value):
            path.write_text(json.dumps(value), encoding="utf-8")
        self.save = save
        save(self.base / "download-manifest.json", {"complete": True, "repo_id": "Qwen/Qwen3.5-4B", "revision": "fixture-revision"})
        save(self.base / "config.json", {"test_fixture": True})
        save(self.run / "adapter/adapter_config.json", {"test_fixture": True})
        (self.run / "adapter/adapter_model.safetensors").write_bytes(b"fixture bytes; never loaded")
        self.adapter = self.run / "qwen-4b-lanm-lora-f16.gguf"
        self.adapter.write_bytes(b"fixture export bytes; never loaded")
        self.manifest = {"status": "completed", "args": {"size": "4B", "epochs": 1}, "global_step": 1,
            "completed_epochs": 1, "nonzero_lora_b_elements": 1,
            "base_repo": "Qwen/Qwen3.5-4B", "base_revision": "fixture-revision",
            "base_download_manifest_sha256": integration.sha(self.base / "download-manifest.json"),
            "identity": {"base_config_sha256": integration.sha(self.base / "config.json")},
            "adapter_sha256": integration.sha(self.run / "adapter/adapter_model.safetensors"),
            "adapter_config_sha256": integration.sha(self.run / "adapter/adapter_config.json")}
        self.export = {"synthetic": False, "base_config_sha256": integration.sha(self.base / "config.json"),
            "llama_cpp_commit": integration.LLAMA_COMMIT, "runtime": "llama.cpp b12323",
            "adapter_sha256": self.manifest["adapter_sha256"], "gguf_sha256": integration.sha(self.adapter),
            "gguf_bytes": self.adapter.stat().st_size}
        self.write_manifests()

    def tearDown(self):
        self.patch.stop()
        self.temporary.cleanup()

    def write_manifests(self):
        self.save(self.run / "run-manifest.json", self.manifest)
        self.save(self.run / "export-manifest.json", self.export)

    def test_matching_artifact_chain_and_optional_run_path(self):
        self.assertEqual(integration.validate_artifacts("4B", self.run), (self.manifest, self.export))
        self.assertEqual(integration.validate_artifacts("4B"), (self.manifest, self.export))

    def test_synthetic_incomplete_wrong_size_and_mixed_origin_rejected(self):
        cases = [("export", "synthetic", True), ("manifest", "status", "training"),
            ("manifest", "args", {"size": "9B", "epochs": 1}), ("export", "adapter_sha256", "different"),
            ("export", "base_config_sha256", "different"), ("manifest", "adapter_config_sha256", "different"),
            ("export", "llama_cpp_commit", "different"), ("manifest", "nonzero_lora_b_elements", 0)]
        for which, key, value in cases:
            with self.subTest(which=which, key=key):
                target = self.export if which == "export" else self.manifest
                old = deepcopy(target[key])
                target[key] = value
                self.write_manifests()
                with self.assertRaises(ValueError):
                    integration.validate_artifacts("4B")
                target[key] = old
        self.write_manifests()
        self.adapter.write_bytes(b"modified export")
        with self.assertRaises(ValueError):
            integration.validate_artifacts("4B")

    def test_loaded_adapter_must_match_path_scale_and_exclusivity(self):
        good = [{"path": str(self.adapter), "scale": 1.0}]
        integration.validate_loaded_adapter(good, self.adapter)
        for loaded in ([], good + good, [{"path": str(self.adapter), "scale": 0}],
                       [{"path": str(self.adapter), "scale": True}], [{"path": "different.gguf", "scale": 1}]):
            with self.assertRaises(ValueError):
                integration.validate_loaded_adapter(loaded, self.adapter)

    def test_actual_result_required_and_cancelled_calls_do_not_pass(self):
        initial = {"id": "fresh-project", "name": "Fresh smoke", "target": "Dy", "competitor": "Y", "revision": 0,
            "assumptions": {}, "configuration": {}, "experiment_count": 0, "accepted_experiment_count": 0}
        trace = [{"type": "tool_call", "name": "project_state", "success": True,
                  "arguments": {"project_id": initial["id"]}, "result": deepcopy(initial)}]
        def check(entries=trace, events=None, final=None):
            return integration.smoke_checks(initial, final or initial, entries, events or [{"type": "done"}], True, False, "Fresh smoke: Dy / Y")
        self.assertTrue(all(check().values()))
        self.assertFalse(check([])["real_lanm_tool_call"])
        corrupted = deepcopy(trace)
        corrupted[0]["result"]["id"] = "other-project"
        self.assertFalse(check(corrupted)["real_lanm_tool_call"])
        self.assertFalse(check(events=[{"type": "done", "status": "cancelled"}])["completed"])
        self.assertFalse(check(final={**initial, "accepted_experiment_count": 1})["project_unchanged"])

    def test_model_requests_require_explicit_run(self):
        with patch.object(integration, "validate_artifacts", side_effect=AssertionError("No runtime work before explicit run")) as validate:
            with self.assertRaises(SystemExit):
                integration.main(["--size", "4B"])
            validate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
