"""Comparison orchestration and persisted-fact checks, with no model requests."""
import contextlib
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from lanm_platform.core import Store

SPEC = importlib.util.spec_from_file_location("comparison", Path(__file__).resolve().parents[1] / "evaluations" / "compare.py")
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)
PROFILE = {"id": "fake", "backend": "compatible", "model": "fake-model"}


class FixtureRuntime:
    instances = []

    def __init__(self, store, directory):
        self.store, self.directory, self.closed = store, directory, False
        self.instances.append(self)

    def submit(self, project_id, message, mode, model):
        case_id = self.store.get_project(project_id)["name"].split(": ", 1)[1]
        if case_id == "tool_economics":
            result = self.store.calculate(project_id)
            name = "calculate_economics"
        elif case_id == "tool_hypothetical":
            result = self.store.rank(project_id, "untested", 3,
                                     assumption_overrides={"usable_lifetime_cycles": 50},
                                     configuration_overrides={"support": "hypothetical support"},
                                     scenario_reason="Fixture request")
            name = "prioritize_candidates"
        elif case_id == "tool_exact_selection":
            run = self.store.list_runs(project_id)[0]
            ids = [run["rows"][2]["candidate_id"], run["rows"][0]["candidate_id"]]
            selection = self.store.save_testing_selection(project_id, run["id"], ids, "Fixture request")
            result = self.store.create_testing_batch(project_id, 2, 40, 60, selection_id=selection["id"], seed=7)
            name = "create_testing_batch"
        else:
            result, name = None, None
        trace = [{"type": "tool_call", "name": name, "arguments": {"project_id": project_id},
                  "result": result, "success": True}] if name else []
        return SimpleNamespace(id="fake-job", thread_id=None, done=True, text="Fixture answer only.",
                               events=[{"type": "done"}], condition=threading.Condition(), trace=trace,
                               metrics={"total_seconds": 0.01, "first_token_seconds": None})

    def close(self):
        self.closed = True


class ComparisonTests(unittest.TestCase):
    def test_objective_cases_check_saved_facts_in_fresh_stores(self):
        directories = []
        for case in comparison.OBJECTIVE_CASES:
            result = comparison.run_objective_case(case, PROFILE, 10, FixtureRuntime)
            self.assertEqual(result["status"], "completed")
            self.assertTrue(all(check["passed"] for check in result["objective_checks"]["checks"]), case["id"])
            self.assertEqual(result["scientific_review"]["status"], "unreviewed")
            self.assertEqual(result["metrics"]["first_token_seconds"], None)
            self.assertTrue(result["temporary_project_removed"])
            instance = FixtureRuntime.instances[-1]
            self.assertTrue(instance.closed)
            self.assertFalse(instance.directory.exists())
            directories.append(instance.directory)
            for criterion in case["reference_criteria"]:
                self.assertNotIn(criterion, result["prompt"])
        self.assertEqual(len(set(directories)), len(directories))

    def test_hypothetical_commit_and_invented_export_fail_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            case = next(c for c in comparison.OBJECTIVE_CASES if c["id"] == "tool_hypothetical")
            pid, context, _ = comparison.setup_objective(store, case)
            initial = store.get_project(pid)
            store.update_assumptions(pid, {"usable_lifetime_cycles": 50}, "Wrongly committed hypothetical")
            facts = comparison.check_objective(case["id"], initial, store.get_project(pid), [], [], [], context)
            self.assertFalse(facts["checks"][0]["passed"])
            self.assertFalse(facts["checks"][1]["passed"])
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            case = next(c for c in comparison.OBJECTIVE_CASES if c["id"] == "tool_missing_bound")
            pid, context, _ = comparison.setup_objective(store, case)
            initial = store.get_project(pid)
            store.create_testing_batch(pid, 2, 50, 250, selection_id=context["selection_id"])
            facts = comparison.check_objective(case["id"], initial, store.get_project(pid), store.list_runs(pid),
                                                store.list_testing_selections(pid), store.list_testing_batches(pid), context)
            self.assertFalse(facts["checks"][1]["passed"])

    def test_activity_does_not_imply_success_or_scientific_accuracy(self):
        facts = comparison.trace_facts([{"type": "activity", "text": "Using read_source"},
                                        {"type": "tool_call", "name": "read_source"},
                                        {"type": "tool_call", "success": False},
                                        {"type": "tool_call", "success": True}])
        self.assertEqual(facts["record_count"], 3)
        self.assertEqual(facts["explicit_success_records"], 1)
        self.assertEqual(facts["explicit_failure_records"], 1)
        self.assertEqual(facts["outcome_unknown_records"], 1)
        self.assertNotIn("score", facts)

    def test_default_and_prepare_do_not_open_store_or_runtime(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            destination = Path(directory) / "prepared.json"
            with patch.object(comparison, "WORKSPACE", Path(directory)), \
                 patch.object(comparison, "load_profiles", return_value=[PROFILE]), \
                 patch.object(comparison, "runtime_factory_for", side_effect=AssertionError("No requests")), \
                 patch.object(comparison, "Store", side_effect=AssertionError("No Store")):
                self.assertEqual(comparison.main([]), 0)
                self.assertEqual(comparison.main(["--prepare", "--all", "--output", str(destination)]), 0)
            report = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(len(report["results"]), 13)
            self.assertTrue(all(r["status"] == "not_run" for r in report["results"]))
            self.assertFalse(report["training_policy"]["training_eligible"])

    def test_live_order_alternates_and_failure_preserves_prior_results(self):
        profiles = [{**PROFILE, "id": "one"}, {**PROFILE, "id": "two"}]
        completed = {"id": "tool_economics", "status": "completed", "elapsed_seconds": 1.5,
                     "scientific_review": {"status": "unreviewed"}}
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            destination = Path(directory) / "run.json"
            with patch.object(comparison, "WORKSPACE", Path(directory)), \
                 patch.object(comparison, "load_profiles", return_value=profiles), \
                 patch.object(comparison, "runtime_factory_for", return_value=FixtureRuntime), \
                 patch.object(comparison, "run_objective_case", side_effect=[deepcopy(completed), RuntimeError("failed"), deepcopy(completed), deepcopy(completed)]):
                code = comparison.main(["--run", "--profile", "one", "--profile", "two", "--case", "tool_economics",
                                        "--repeat", "2", "--output", str(destination)])
            report = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertEqual([r["profile_id"] for r in report["results"]], ["one", "two", "two", "one"])
        self.assertEqual(report["results"][1]["status"], "error")
        self.assertEqual(report["summary"]["two"]["completed"], 1)
        self.assertEqual(report["summary"]["two"]["scientific_accuracy"], "unreviewed")
        self.assertIsNone(report["summary"]["two"]["cost_usd"])

    def test_output_scope_and_explicit_live_selection(self):
        with self.assertRaisesRegex(ValueError, "outside platform"):
            comparison.output_path(comparison.ROOT / "evaluations" / "report.json")
        with self.assertRaisesRegex(ValueError, "inside the workspace"):
            comparison.output_path(comparison.WORKSPACE.parent / "report.json")
        with patch.object(comparison, "load_profiles", return_value=[PROFILE]), contextlib.redirect_stderr(io.StringIO()):
            for args in (["--run"], ["--run", "--case", "tool_economics"],
                         ["--run", "--profile", "fake", "--case", "tool_economics"], ["--repeat", "0"]):
                with self.assertRaises(SystemExit):
                    comparison.main(args)

    def test_report_profile_never_contains_secret_values(self):
        profile = {**PROFILE, "api_key": "secret", "authorization": "secret", "api_key_env": "EXAMPLE_KEY",
                   "metadata": {"quantization": "Q4_K_M", "api_key": "secret"}}
        exported = comparison.public_profile(profile)
        self.assertNotIn("secret", json.dumps(exported))
        self.assertEqual(exported["api_key_env"], "EXAMPLE_KEY")
        self.assertEqual(exported["metadata"], {"quantization": "Q4_K_M"})

    def test_failed_cases_stay_in_objective_denominator(self):
        result = {"profile_id": "fake", "category": "objective_tool_contract", "status": "error",
                  "objective_checks": {"checks": [{"passed": False}, {"passed": True}]}}
        summary = comparison.summarize([result])["fake"]
        self.assertEqual(summary["objective_checks_total"], 2)
        self.assertEqual(summary["objective_checks_passed"], 1)
        self.assertEqual(summary["objective_cases_attempted"], 1)
        self.assertEqual(summary["objective_cases_completed_with_all_checks"], 0)


if __name__ == "__main__":
    unittest.main()
