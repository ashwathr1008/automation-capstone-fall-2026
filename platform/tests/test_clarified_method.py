"""Clarified-case prompt, isolation and report identity; reference actors only."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("clarified_method_tests", Path(__file__).resolve().parents[1] / "evaluations" / "clarified_method.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
PROFILE = {"id": "reference", "backend": "compatible", "model": "reference-actor-only", "name": "Reference", "enable_thinking": False}
CODE = ('def calculate(inputs):\n'
        '    if inputs["annual_output_kg"] <= 0 or inputs["annual_cost_usd"] < 0:\n'
        '        raise ValueError("Invalid inputs")\n'
        '    return {"usd_per_kg": inputs["annual_cost_usd"] / inputs["annual_output_kg"]}\n')
MANIFEST = {"name": "Annual cost", "description": "Independent arithmetic", "boundary": "Supplied annual cost per collected target mass",
    "assumptions": ["No physical performance prediction"], "references": ["Arithmetic"],
    "inputs": {"annual_cost_usd": {"unit": "USD/year"}, "annual_output_kg": {"unit": "kg/year"}},
    "reference_cases": [
        {"inputs": {"annual_cost_usd": 1200, "annual_output_kg": 12}, "expected": {"usd_per_kg": 100}, "basis": "1200/12=100"},
        {"inputs": {"annual_cost_usd": 3000, "annual_output_kg": 20}, "expected": {"usd_per_kg": 150}, "basis": "3000/20=150"}]}


class ReferenceActor:
    instances = []
    def __init__(self, store, directory):
        self.store, self.directory, self.closed = store, directory, False
        self.instances.append(self)
    def submit(self, project_id, message, mode, model):
        assert message == runner.PROMPT and mode == "build"
        self.project_id = project_id
        registry = runner.comparison.workflows.Registry(self.directory)
        registry.create_draft("evaluation-total-cost", deepcopy(MANIFEST), CODE)
        assert registry.check("evaluation-total-cost")["passed"]
        method = registry.register("evaluation-total-cost")
        self.store.save_custom_run(project_id, registry.run(method["id"], {"annual_cost_usd": 2400, "annual_output_kg": 8}))
        return SimpleNamespace(id="reference-job", thread_id="reference-thread", done=True, text="Reference actor; not a model response.",
            condition=threading.Condition(), events=[{"type": "done"}], trace=[], metrics={})
    def close(self):
        self.closed = True


class ClarifiedMethodTests(unittest.TestCase):
    def test_prompt_changes_only_the_declared_ambiguity(self):
        original = next(c for c in runner.comparison.workflows.CASES if c["id"] == runner.ORIGINAL_CASE_ID)
        self.assertEqual(original, runner.ORIGINAL_CASE)
        self.assertEqual(runner.CASE["question"].replace(runner.CLARIFIED_TEXT, runner.AMBIGUOUS_TEXT), original["question"])
        for phrase in ("Inside calculate(inputs)", "annual_output_kg <= 0", "annual_cost_usd < 0", "raising ValueError",
                       "input-schema validation", "return an error object", "Zero annual_cost_usd is valid", "usd_per_kg=0"):
            self.assertIn(phrase, runner.PROMPT)
        self.assertNotIn(runner.AMBIGUOUS_TEXT, runner.PROMPT)
        self.assertEqual(runner.CASE["reference_criteria"], original["reference_criteria"])
        self.assertEqual(runner.CASE["mode"], original["mode"])
        changed = runner.execution_case()
        changed["turns"][0] = "mutation"
        self.assertNotEqual(changed["turns"], runner.CASE["turns"])
        self.assertEqual(original, runner.ORIGINAL_CASE)

    def test_three_references_use_original_checks_and_isolated_state(self):
        protected = [Path(runner.comparison.__file__), Path(runner.comparison.workflows.__file__)] + [
            runner.comparison.WORKSPACE / "local-training/data" / name for name in ("train.jsonl", "validation.jsonl")]
        hashes = {path: runner.digest(path.read_bytes()) for path in protected if path.is_file()}
        ReferenceActor.instances = []
        for _ in range(3):
            result = runner.run_case(PROFILE, ReferenceActor)
            self.assertEqual(result["id"], runner.CASE_ID)
            self.assertEqual(result["checker_case_id"], runner.ORIGINAL_CASE_ID)
            self.assertEqual(result["prompt_sha256"], runner.digest(result["prompt"]))
            self.assertEqual(result["status"], "completed")
            self.assertTrue(all(c["passed"] for c in result["objective_checks"]["checks"]), result["objective_checks"])
            self.assertTrue(result["temporary_project_removed"])
        self.assertEqual(len({actor.project_id for actor in ReferenceActor.instances}), 3)
        self.assertTrue(all(actor.closed and not actor.directory.exists() for actor in ReferenceActor.instances))
        self.assertEqual(hashes, {path: runner.digest(path.read_bytes()) for path in hashes})

    def test_report_identity_and_resume_reject_original_or_mixed_results(self):
        plan = runner.report_template([PROFILE], True)
        self.assertEqual(plan["profiles"], [runner.comparison.public_profile(PROFILE)])
        self.assertEqual(plan["build_tool_allowlist"], runner.comparison.BUILD_TOOLS)
        self.assertEqual(plan["local_tool_allowlist"], runner.comparison.LOCAL_TOOLS)
        self.assertEqual((plan["repeat"], plan["timeout_seconds"], plan["planned_attempts"]), (3, 300, 3))
        good = deepcopy(plan)
        good["results"] = [{"id": runner.CASE_ID, "profile_id": PROFILE["id"], "repetition": 1, "prompt_sha256": runner.digest(runner.PROMPT)}]
        self.assertEqual(runner.validate_resume(good, plan), {(PROFILE["id"], runner.CASE_ID, 1)})
        for key, value in (("id", runner.ORIGINAL_CASE_ID), ("prompt_sha256", "different"), ("repetition", 4)):
            invalid = deepcopy(good)
            invalid["results"][0][key] = value
            with self.assertRaises(ValueError):
                runner.validate_resume(invalid, plan)
        invalid = deepcopy(good)
        invalid["results"].append(deepcopy(invalid["results"][0]))
        with self.assertRaises(ValueError):
            runner.validate_resume(invalid, plan)

        invalid = deepcopy(good)
        invalid["clarification"]["prompt"] = "different"
        with self.assertRaises(ValueError):
            runner.validate_resume(invalid, plan)

    def test_cli_preserves_schema_allowlist_and_three_attempts(self):
        with tempfile.TemporaryDirectory(prefix="clarified-runner-test-", dir=runner.comparison.WORKSPACE) as directory:
            output = Path(directory) / "clarified.json"
            with patch.object(runner.comparison, "load_profiles", return_value=[PROFILE]), \
                 patch.object(runner.comparison, "runtime_factory_for", return_value=ReferenceActor) as factory:
                arguments = ["--run", "--profile", PROFILE["id"], "--output", str(output)]
                self.assertEqual(runner.main(arguments), 0)
                self.assertEqual(factory.call_count, 3)
                self.assertTrue(all(call.kwargs["tool_allowlist"] == runner.comparison.BUILD_TOOLS for call in factory.call_args_list))
                factory.reset_mock()
                self.assertEqual(runner.main(arguments + ["--resume"]), 0)
                factory.assert_not_called()
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "run_finished")
            self.assertEqual([r["repetition"] for r in report["results"]], [1, 2, 3])
            self.assertEqual(report["summary"][PROFILE["id"]]["objective_cases_completed_with_all_checks"], 3)
            for row in report["results"]:
                self.assertEqual(row["category"], "objective_tool_contract")
                self.assertEqual(row["id"], runner.CASE_ID)
                for key in ("model", "profile_id", "repetition", "trace", "metrics", "objective_checks"):
                    self.assertIn(key, row)

    def test_prepare_never_constructs_runtime(self):
        with tempfile.TemporaryDirectory(prefix="clarified-prepare-test-", dir=runner.comparison.WORKSPACE) as directory:
            output = Path(directory) / "prepared.json"
            with patch.object(runner.comparison, "load_profiles", return_value=[PROFILE]), \
                 patch.object(runner.comparison, "runtime_factory_for", side_effect=AssertionError("No model runtime permitted")) as factory:
                self.assertEqual(runner.main(["--prepare", "--profile", PROFILE["id"], "--output", str(output)]), 0)
                factory.assert_not_called()
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "prepared_without_model_requests")
            self.assertEqual(report["results"][0]["prompt"], runner.PROMPT)
            self.assertEqual(report["results"][0]["id"], runner.CASE_ID)


if __name__ == "__main__":
    unittest.main()
