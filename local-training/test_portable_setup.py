"""Fresh-clone setup checks: no models, credentials, network or GPU required."""
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

import prepare_workspace as setup
import provision_training as provision
import register_trained_profiles as registration


class PortableSetupTests(unittest.TestCase):
    def test_registration_uses_templates_and_preserves_custom_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); training = root / "local-training"; training.mkdir()
            app = root / "research-data/model_profiles.json"; app.parent.mkdir()
            custom = {"id": "my-model", "backend": "codex", "model": "my-model"}
            app.write_text(json.dumps({"profiles": [custom]}), encoding="utf-8")
            base_profiles = {"profiles": [{"id": identifier, "model": identifier, "metadata": {}} for identifier in ("qwen-local", "qwen-9b-local")]}
            (training / "profiles.example.json").write_text(json.dumps(base_profiles), encoding="utf-8")
            configs = {"configurations": [{"profile_id": f"qwen-{size}-trained" + suffix} for size in ("4b", "9b") for suffix in ("", "-thinking")]}
            (training / "analysis-configurations.example.json").write_text(json.dumps(configs), encoding="utf-8")
            manifest = {"args": {"precision": "qlora4", "rank": 16, "epochs": 1}, "adapter_sha256": "a" * 64,
                        "identity": {"train_sha256": "d" * 64, "validation_sha256": "d" * 64}, "base_revision": "pinned"}
            benchmark = root / "benchmark-results/local"
            command = ["register", "--run", "--benchmark-dir", str(benchmark), "--app-profiles", str(app)]
            with patch.object(registration, "ROOT", training), patch.object(registration, "WORKSPACE", root), \
                 patch.object(registration, "validate_artifacts", return_value=(manifest, {"gguf_sha256": "b" * 64})), \
                 patch.object(registration, "sha", return_value="d" * 64), patch.object(sys, "argv", command):
                self.assertEqual(registration.main(), 0)
            result = json.loads(app.read_text())
            self.assertEqual(result["profiles"][0], custom)
            self.assertEqual(len(result["profiles"]), 5)
            self.assertTrue((benchmark / "profiles.json").exists())
            self.assertEqual(json.loads(app.with_suffix('.json.before-trained-profiles').read_text()), {"profiles": [custom]})

    def test_profiles_initialize_without_private_files_and_preserve_existing_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            training, platform = root / "local-training", root / "platform"
            training.mkdir(); platform.mkdir(); (root / "research-data").mkdir()
            for path in (training / "profiles.example.json", training / "analysis-configurations.example.json", platform / "model_profiles.example.json"):
                path.write_text('{"template":true}', encoding="utf-8")
            output = root / "benchmark-results/local"
            with patch.object(setup, "ROOT", training), patch.object(setup, "WORKSPACE", root):
                first = setup.initialize(output)
                app = root / "research-data/model_profiles.json"
                app.write_text('{"user":"preserved"}', encoding="utf-8")
                second = setup.initialize(output)
            self.assertEqual(len(first), 3)
            self.assertTrue(all(row["status"] == "preserved_existing" for row in second))
            self.assertEqual(json.loads(app.read_text()), {"user": "preserved"})

    def test_setup_does_not_create_a_fake_research_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); training = root / "local-training"; training.mkdir()
            for name in ("profiles.example.json", "analysis-configurations.example.json"):
                (training / name).write_text('{}', encoding="utf-8")
            with patch.object(setup, "ROOT", training), patch.object(setup, "WORKSPACE", root):
                self.assertEqual(len(setup.initialize(root / "benchmark-results/local")), 2)
            self.assertFalse((root / "research-data").exists())

    def test_provisioning_queries_the_pinned_revision_and_refuses_stale_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "base-lineage.json").write_text(json.dumps({"models": [{"size": "4B", "official_repo": "Qwen/Qwen3.5-4B", "official_revision": "pinned"}]}))
            with patch.object(provision, "ROOT", root), patch.object(provision, "fetch_json", return_value={"sha": "pinned", "siblings": []}) as fetch:
                provision.model("4B")
                self.assertIn('/revision/pinned?', fetch.call_args.args[0])
                path = root / "models/Qwen3.5-4B/download-manifest.json"
                manifest = json.loads(path.read_text()); manifest["revision"] = "another"; path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, "differs from the pinned"):
                    provision.model("4B")
                self.assertEqual(fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
