"""A final export must be complete, auditable, and refuse stale evidence."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

EVALUATIONS = Path(__file__).resolve().parents[1] / "evaluations"
sys.path.insert(0, str(EVALUATIONS))
import build_final_comparison as builder
from test_clarified_comparison import fixture as report_fixture
from test_comparison_training import fixture as training_fixture


def fixture(root):
    data = root / "local-training/data"
    data.mkdir(parents=True)
    (data / "train.jsonl").write_bytes(b"synthetic train fixture\n")
    (data / "validation.jsonl").write_bytes(b"synthetic validation fixture\n")
    train_sha = hashlib.sha256((data / "train.jsonl").read_bytes()).hexdigest()
    val_sha = hashlib.sha256((data / "validation.jsonl").read_bytes()).hexdigest()
    training, lineage = {}, []
    for size in ("4B", "9B"):
        run_dir = root / "local-training/runs" / size
        run_dir.mkdir(parents=True)
        declaration, profile = training_fixture(run_dir)
        declaration["training_data_sha256"] = train_sha
        profile["metadata"]["training_data_sha256"] = train_sha
        path = run_dir / "run-manifest.json"
        run = json.loads(path.read_bytes())
        run.update(base_repo="Qwen/Qwen3.5-" + size)
        run["identity"].update(train_sha256=train_sha, validation_sha256=val_sha)
        run["data"]["train_sha256"] = train_sha
        path.write_text(json.dumps(run), encoding="utf-8")
        training[size] = declaration, profile
        lineage.append({"size": size, "official_repo": run["base_repo"], "official_revision": run["base_revision"],
                        "conversion_revision": "conversion-" + size})
    (root / "local-training/base-lineage.json").write_text(json.dumps({"models": lineage}), encoding="utf-8")
    originals, clarified, declarations = [], [], []
    for identifier in sorted(builder.EXPECTED_IDS):
        size = "9B" if "9b" in identifier else "4B"
        is_local = identifier.startswith("qwen")
        trained = identifier in builder.TRAINED_IDS
        thinking = "thinking" in identifier
        profile = {"id": identifier, "model": identifier + "-weights", "enable_thinking": thinking,
                   "metadata": {"revision": "conversion-" + size} if is_local else {}}
        declaration = {"profile_id": identifier, "display_name": identifier, "group": size if is_local else "Frontier",
                       "model": profile["model"], "training": "trained" if trained else "base" if is_local else "not_applicable",
                       "thinking": "on" if thinking else "off"}
        if trained:
            declaration.update({k: v for k, v in training[size][0].items() if k != "profile_id"})
            profile["metadata"].update(training[size][1]["metadata"])
        declarations.append(declaration)
        old, revised = report_fixture(identifier), report_fixture(identifier, clarified=True)
        for report in (old, revised):
            report["profiles"] = [profile]
            for row in report["results"]:
                row["model"] = profile["model"]
        retained = [r for r in old["results"] if r["id"] == "retained"]
        old["results"] = [r for r in old["results"] if r["id"] != "retained"]
        old["results"] += [{**deepcopy(row), "id": "task_" + str(i)} for i in range(15) for row in retained]
        old["selected_case_ids"] = sorted({row["id"] for row in old["results"]})
        for report, prefix, target in ((old, "original", originals), (revised, "clarified", clarified)):
            raw = json.dumps(report).encode()
            target.append((str(root / (prefix + "-" + identifier + ".json")), report, hashlib.sha256(raw).hexdigest()))
    plan = {"contents": {"correction_id": "authored_method_contract_clarification_v1", "original_case_id": "wf_build_method",
                         "clarified_case_id": "wf_build_method_clarified", "repetitions": 3, "headline_workflow_count": 16,
                         "configuration_ids": sorted(builder.EXPECTED_IDS)}}
    return originals, clarified, {"configurations": declarations}, plan


class FinalBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.inputs = fixture(self.root)
        self.workspace = patch.object(builder, "WORKSPACE", self.root)
        self.workspace.start()
        self.addCleanup(self.workspace.stop)

    def test_complete_export_preserves_original_counts_and_hashes_every_packaged_file(self):
        result = builder.build_bundle(*self.inputs, self.root / "final-v1")
        output = Path(result["bundle"])
        self.assertEqual(result["counts"]["raw_attempts_total"], 612)
        self.assertEqual(result["counts"]["headline_attempts"], 576)
        original = json.loads((output / "original-strict-summary.json").read_bytes())
        corrected = json.loads((output / "corrected-summary.json").read_bytes())
        self.assertTrue(all(r["objective_tasks_passed"] == 45 for r in original["model_summary"].values()))
        self.assertTrue(all(r["objective_tasks_passed"] == 48 for r in corrected["model_summary"].values()))
        manifest = json.loads((output / "bundle-manifest.json").read_bytes())
        for record in manifest["files"]:
            self.assertEqual(hashlib.sha256((output / record["relative_path"]).read_bytes()).hexdigest(), record["sha256"])
        with zipfile.ZipFile(result["archive"]["path"]) as archive:
            self.assertIsNone(archive.testzip())
            self.assertFalse(any("corrected-attempts" in name for name in archive.namelist()))
        self.assertEqual(len(list(output.glob("*-figures/*.png"))), 8)
        with self.assertRaisesRegex(ValueError, "versioned"):
            builder.build_bundle(*self.inputs, output)

    def test_missing_configuration_cannot_create_final_artifacts(self):
        originals, clarified, configurations, plan = self.inputs
        output = self.root / "incomplete"
        with self.assertRaisesRegex(ValueError, "twelve"):
            builder.build_bundle(originals[:-1], clarified[:-1], configurations, plan, output)
        self.assertFalse(output.exists())

    def test_paired_runtime_drift_is_rejected(self):
        profiles = {report["profiles"][0]["id"]: deepcopy(report["profiles"][0]) for _, report, _ in self.inputs[0]}
        profiles["qwen-4b-trained"]["max_tool_rounds"] = 99
        with self.assertRaisesRegex(ValueError, "max_tool_rounds"):
            builder.verify_pair_controls(profiles)


if __name__ == "__main__":
    unittest.main()
