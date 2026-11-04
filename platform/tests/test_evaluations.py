"""Evaluation plumbing tests, not scientific-response validation."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from lanm_platform.core import Store

SPEC = importlib.util.spec_from_file_location("evaluation_runner", Path(__file__).resolve().parents[1] / "evaluations" / "run.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class FakeRuntime:
    instances = []

    def __init__(self, store, directory):
        self.store, self.directory, self.closed = store, directory, False
        self.instances.append(self)

    def submit(self, project_id, message, mode, model):
        source = next(s for s in self.store.list_sources(project_id) if s.get("project_id") == project_id)
        self.store.add_message(project_id, "user", message)
        return SimpleNamespace(id="fake-job", thread_id="fake-thread", done=True,
                               text="An answer with a citation " + source["id"],
                               condition=threading.Condition(),
                               events=[{"type": "activity", "text": "Using read_source"}, {"type": "done"}])

    def close(self):
        self.closed = True


class EvaluationTests(unittest.TestCase):
    def test_case_coverage_and_references_are_complete(self):
        suite = runner.load_suite()
        self.assertEqual(len(suite["cases"]), 9)
        for case in suite["cases"]:
            self.assertTrue(runner.case_sources(suite, case))
            self.assertGreaterEqual(len(case["reference_criteria"]), 3)
            for fixture in runner.case_sources(suite, case):
                if fixture["kind"] == "primary_paper_paraphrase":
                    self.assertTrue(fixture["url"].startswith("https://pubmed.ncbi.nlm.nih.gov/"))
                    self.assertTrue(fixture["locator"])
                else:
                    self.assertIn("SYNTHETIC EVALUATION FIXTURE", fixture["text"])

    def test_run_uses_temporary_store_never_configured_existing_data(self):
        suite = runner.load_suite()
        with tempfile.TemporaryDirectory() as directory:
            existing = Store(Path(directory) / "existing")
            project = existing.create_project("Untouched real project", "Nd", "La")
            before = existing.db_path.read_bytes()
            with patch.dict(os.environ, {"LANM_DATA_DIR": str(existing.data_dir)}):
                result = runner.run_case(suite, suite["cases"][0], "fake-model", runtime_factory=FakeRuntime)
            self.assertEqual(existing.db_path.read_bytes(), before)
            self.assertEqual(existing.get_project(project["id"])["experiment_count"], 0)
            fake = FakeRuntime.instances[-1]
            self.assertNotEqual(fake.directory, existing.data_dir)
            self.assertFalse(fake.directory.exists())
            self.assertTrue(fake.closed)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["scientific_review"]["status"], "unreviewed")
        for criterion in suite["cases"][0]["reference_criteria"]:
            self.assertNotIn(criterion, result["prompt"])
        self.assertEqual(result["final_project"]["accepted_experiment_count"], 0)

    def test_marker_or_tool_name_is_never_scientific_success(self):
        case = runner.load_suite()["cases"][0]
        sources = [{"id": "source_fixture", "url": "https://example.test/paper", "title": "Fixture"}]
        checks = runner.structural_checks(case, "Unsupported claim [source_fixture]", [], sources)
        self.assertTrue(checks["fixture_citation_marker_present"])
        self.assertFalse(checks["expected_tool_activity"]["read_source"])
        self.assertTrue(checks["source_use_verification"].startswith("unverified"))
        self.assertNotIn("score", checks)
        self.assertEqual(runner.review_template(case)["status"], "unreviewed")

    def test_default_and_prepare_make_no_runtime_or_store(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            output = Path(directory) / "prepared.json"
            with patch.object(runner, "Runtime", side_effect=AssertionError("No runtime")), \
                 patch.object(runner, "Store", side_effect=AssertionError("No Store")):
                self.assertEqual(runner.main([]), 0)
                self.assertEqual(runner.main(["--prepare", "--case", "mass_basis", "--output", str(output)]), 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["results"][0]["status"], "not_run")
            self.assertEqual(report["results"][0]["scientific_review"]["status"], "unreviewed")

    def test_live_requires_selection_and_output_stays_outside_checkout(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            runner.main(["--run"])
        with self.assertRaisesRegex(ValueError, "outside"):
            runner.output_path(runner.ROOT / "evaluations" / "result.json")
        with self.assertRaisesRegex(ValueError, ".json"):
            runner.output_path(runner.ROOT.parent / "research.sqlite3")

    def test_setup_failure_is_saved_without_erasing_prior_results(self):
        completed = {"id": "source_entailment", "status": "completed", "scientific_review": {"status": "unreviewed"}}
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            output = Path(directory) / "failure.json"
            with patch.object(runner, "run_case", side_effect=[completed, OSError("Cannot open temporary project")]):
                code = runner.main(["--run", "--case", "source_entailment", "--case", "double_recovery", "--output", str(output)])
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertEqual(report["results"][0], completed)
        self.assertEqual(report["results"][1]["status"], "error")
        self.assertEqual(report["results"][1]["scientific_review"]["status"], "unreviewed")


if __name__ == "__main__":
    unittest.main()
