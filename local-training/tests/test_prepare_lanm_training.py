"""Corpus integrity checks; no models, GPU, benchmark files or network calls."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


TRAINING_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prepare_lanm_training", TRAINING_ROOT / "prepare_lanm_training.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class TrainingCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="corpus-test-", dir=TRAINING_ROOT)
        cls.output = Path(cls.temporary.name) / "data"
        real_open = io.open
        def guarded_open(file, *args, **kwargs):
            if isinstance(file, (str, Path)):
                normalized = str(file).replace("\\", "/").lower()
                forbidden = ("/benchmark-results/", "/platform/evaluations/", "/research-data/")
                if any(part in normalized for part in forbidden):
                    raise AssertionError("Forbidden training input accessed: " + normalized)
            return real_open(file, *args, **kwargs)
        with patch("socket.create_connection", side_effect=AssertionError("Network disabled")), \
             patch("socket.socket.connect", side_effect=AssertionError("Network disabled")), \
             patch("io.open", side_effect=guarded_open):
            cls.manifest = builder.build(cls.output)
        cls.rows_by_split = {split: [json.loads(line) for line in (cls.output / (split + ".jsonl")).read_text(encoding="utf-8").splitlines()]
                            for split in ("train", "validation")}
        cls.rows = cls.rows_by_split["train"] + cls.rows_by_split["validation"]

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_all_contracts_and_only_local_executions(self):
        self.assertEqual(len(builder.SPECS), 41)
        self.assertEqual(set(self.manifest["all_tool_contracts"]), set(builder.SPECS))
        self.assertEqual(set(self.manifest["verified_local_tool_call_counts"]), set(builder.SPECS) - builder.EXTERNAL_TOOLS)
        self.assertEqual(sum(self.manifest["verified_local_tool_call_counts"].values()), 240)
        self.assertEqual(self.manifest["network_requests"], 0)
        self.assertEqual(self.manifest["model_requests"], 0)
        self.assertTrue(256 <= len(self.rows_by_split["train"]) <= 512)
        self.assertEqual(Counter(r["kind"] for r in self.rows)["tool_contract"], 41)
        for row in self.rows:
            if row["kind"] == "tool_dialogue":
                self.assertNotIn(row["provenance"]["tool_name"], builder.EXTERNAL_TOOLS)
                result = json.loads(next(m["content"] for m in row["messages"] if m["role"] == "tool"))
                self.assertEqual(builder.digest(result), row["provenance"]["displayed_result_sha256"])

    def test_group_split_and_actual_paper_holdout(self):
        train_groups = {r["group"] for r in self.rows_by_split["train"]}
        val_groups = {r["group"] for r in self.rows_by_split["validation"]}
        self.assertFalse(train_groups & val_groups)
        self.assertIn(builder.HELD_OUT_PAPER, val_groups)
        paper_rows = [r for r in self.rows_by_split["validation"] if r["group"] == builder.HELD_OUT_PAPER]
        self.assertEqual(len(paper_rows), 21)
        for row in self.rows_by_split["train"]:
            content = builder.encoded(row["messages"])
            self.assertNotIn("smerigan_shi_2025_arxiv_v1", content)
            self.assertNotIn("2504.10495", content)
        for row in self.rows_by_split["validation"]:
            if row["kind"] == "tool_dialogue":
                self.assertIn(row["provenance"]["tool_name"], builder.PURE_VALIDATION_TOOLS)
                self.assertEqual(row["provenance"]["source_ids"], [])

    def test_grounded_passages_match_archive_hashes_and_locators(self):
        with zipfile.ZipFile(builder.DATA / "source-evidence.zip") as archive:
            excerpts = [r for r in self.rows if r["id"].startswith("excerpt-")]
            self.assertEqual(len(excerpts), 42)
            for row in excerpts:
                provenance = row["provenance"]
                locator = provenance["locator"]
                raw = archive.read(locator["archive_member"])
                self.assertEqual(builder.digest(raw), provenance["text_sha256"])
                text = raw.decode("utf-8-sig")
                excerpt = text[locator["character_start"]:locator["character_end"]]
                self.assertEqual(builder.digest(excerpt.encode()), provenance["excerpt_sha256"])
                self.assertIn(excerpt, row["messages"][-1]["content"])
                self.assertIn(provenance["source_ids"][0], row["messages"][-1]["content"])

    def test_exact_tool_schemas_and_candidate_scope(self):
        builder.validate_records(self.rows)
        for row in self.rows:
            for tool in row["tools"]:
                function = tool["function"]
                self.assertEqual(function["parameters"], builder.SPECS[function["name"]]["inputSchema"])
                self.assertEqual(function["description"], builder.SPECS[function["name"]]["description"])
            if row["id"].endswith("-update_assumptions") and row["kind"] == "tool_dialogue":
                call = next(m["tool_calls"][0] for m in row["messages"] if m.get("tool_calls"))
                args = call["function"]["arguments"]
                result = json.loads(next(m["content"] for m in row["messages"] if m["role"] == "tool"))
                if args.get("candidate_id"):
                    self.assertNotEqual(result["assumptions"]["usable_lifetime_cycles"], args["values"]["usable_lifetime_cycles"])

    def test_input_allowlist_file_hashes_and_no_output_escape(self):
        for path, info in self.manifest["input_files"].items():
            self.assertNotIn("benchmark", path)
            self.assertNotIn("evaluations", path)
            self.assertEqual(builder.digest((builder.ROOT / path).read_bytes()), info["sha256"])
        for name, info in self.manifest["files"].items():
            self.assertEqual(builder.digest((self.output / name).read_bytes()), info["sha256"])
        with self.assertRaises(ValueError):
            builder.build(builder.ROOT / "not-a-training-output")

    def test_projection_does_not_modify_retained_fields(self):
        original = {"id": "saved-run", "summary": {"cost_usd_per_kg": 42.25}, "input_details": {"large": "catalog"},
                    "created_at": "date", "rows": [{"candidate_id": "example", "source_id": "source"}]}
        frozen = deepcopy(original)
        projected = builder.training_result("get_run", original)
        self.assertEqual(projected["summary"], original["summary"])
        self.assertEqual(projected["rows"], original["rows"])
        self.assertEqual(original, frozen)
        self.assertNotIn("input_details", projected)
        self.assertNotIn("created_at", projected)

    def test_rebuild_is_byte_reproducible(self):
        second = Path(self.temporary.name) / "repeated"
        with patch("socket.create_connection", side_effect=AssertionError("Network disabled")), \
             patch("socket.socket.connect", side_effect=AssertionError("Network disabled")):
            builder.build(second)
        for split in ("train", "validation"):
            self.assertEqual((self.output / (split + ".jsonl")).read_bytes(), (second / (split + ".jsonl")).read_bytes())


if __name__ == "__main__":
    unittest.main()
