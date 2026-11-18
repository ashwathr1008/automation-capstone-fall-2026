"""Reference actors and adversarial mutations for expanded workflow graders; no model requests."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest

from lanm_platform.core import Store
from lanm_platform.methods import Registry

SPEC = importlib.util.spec_from_file_location("workflow_cases", Path(__file__).resolve().parents[1] / "evaluations" / "workflow_cases.py")
workflows = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflows)

TOTAL_CODE = ('def calculate(inputs):\n'
              '    if inputs["annual_cost_usd"] < 0 or inputs["annual_output_kg"] <= 0:\n'
              '        raise ValueError("Nonnegative cost and positive output required")\n'
              '    return {"usd_per_kg": inputs["annual_cost_usd"] / inputs["annual_output_kg"]}\n')
TOTAL_MANIFEST = {"name": "Annual unit cost", "description": "Synthetic software reference", "boundary": "Supplied annual cost per collected kg",
                  "assumptions": ["No physical performance prediction"], "references": ["Independent arithmetic"],
                  "inputs": {"annual_cost_usd": {"unit": "USD/year"}, "annual_output_kg": {"unit": "kg/year"}},
                  "reference_cases": [
                      {"inputs": {"annual_cost_usd": 1200, "annual_output_kg": 12}, "expected": {"usd_per_kg": 100}, "basis": "1200/12=100"},
                      {"inputs": {"annual_cost_usd": 3000, "annual_output_kg": 20}, "expected": {"usd_per_kg": 150}, "basis": "3000/20=150"}]}


def perform(store, pid, context, case_id, turn):
    if case_id == "wf_evidence_extract":
        source = store.read_source(pid, context["source_id"])
        assert source["hash_verified"]
        store.add_source(pid, "Extracted cost fields", json.dumps({"unit_price_usd_per_l": 72,
                         "price_basis": "supplier estimate", "service_life_established": False}), workflows.SOURCE_URL)
    elif case_id == "wf_source_conflict":
        store.add_source(pid, "Revised synthetic estimate", workflows.CONFLICT_TEXT, workflows.SOURCE_URL)
    elif case_id == "wf_assumption_revision":
        store.update_assumptions(pid, {"usable_lifetime_cycles": 60 if turn == 0 else 120},
                                 "Conservative software scenario" if turn == 0 else "Longer-life software scenario")
        store.calculate(pid)
    elif case_id == "wf_candidate_override":
        store.update_assumptions(pid, {"usable_lifetime_cycles": 80}, "Candidate-specific hypothetical case", "o-36")
        store.calculate(pid, "o-36")
        store.calculate(pid, "o-37")
    elif case_id == "wf_sensitivity":
        store.sensitivity(pid, keys=["usable_lifetime_cycles", "prepared_material_cost_usd_per_l"], factors=[.5, 1, 2])
    elif case_id in {"wf_draft_only", "wf_accept_after_review"}:
        if turn == 0:
            store.add_experiment(pid, "o-36", workflows.EXPERIMENT_LABEL, workflows.CONDITIONS, workflows.METRICS,
                                 "Synthetic software fixture; not laboratory data")
        else:
            exp = store._experiments(pid)[0]
            store.accept_experiment(exp["id"], "Reviewed synthetic fixture for software evaluation")
            store.calculate(pid, "o-36")
    elif case_id == "wf_mismatched_conditions":
        store.rank(pid, "updated")
        store.calculate(pid, "o-36")
    elif case_id == "wf_scale_prediction":
        prediction = store.add_scale_prediction(pid, "Synthetic 200 L scenario", 200,
            "Synthetic support A with synthetic feed A; no physical transport prediction",
            "User-supplied software scenario, not a measurement", workflows.prediction_values())
        store.calculate_scale_prediction(pid, prediction["id"])
    elif case_id == "wf_registered_method":
        registry = Registry(store.data_dir)
        store.save_custom_run(pid, registry.run(context["method_id"], {"cost": 90, "output": .003, "cycles": 75}))
    elif case_id == "wf_build_method":
        registry = Registry(store.data_dir)
        registry.create_draft("evaluation-total-cost", TOTAL_MANIFEST, TOTAL_CODE)
        registry.check("evaluation-total-cost")
        method = registry.register("evaluation-total-cost")
        store.save_custom_run(pid, registry.run(method["id"], {"annual_cost_usd": 2400, "annual_output_kg": 8}))
    elif case_id == "wf_clarify_export" and turn == 1:
        store.create_testing_batch(pid, 2, 50, 80, selection_id=context["selection_id"], seed=11)


class ExpandedWorkflowTests(unittest.TestCase):
    def test_comparison_runner_keeps_one_runtime_and_all_intermediate_checks(self):
        spec = importlib.util.spec_from_file_location("workflow_runner_smoke", Path(__file__).resolve().parents[1] / "evaluations" / "compare.py")
        comparison = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(comparison)
        instances = []

        class ActorRuntime:
            def __init__(self, store, directory):
                self.store, self.directory, self.index, self.closed = store, directory, 0, False
                self.modes = []
                instances.append(self)

            def submit(self, project_id, message, mode, model):
                case_id = self.store.get_project(project_id)["name"].split(": ", 1)[1]
                context = {}
                sources = self.store.list_sources(project_id)
                if case_id == "wf_evidence_extract":
                    context["source_id"] = next(s["id"] for s in sources if s["title"] == "Original synthetic cost note")
                if case_id == "wf_registered_method":
                    context["method_id"] = next(m["id"] for m in Registry(self.directory).list() if m.get("status") == "registered")
                if case_id == "wf_clarify_export":
                    context["selection_id"] = self.store.list_testing_selections(project_id)[0]["id"]
                perform(self.store, project_id, context, case_id, self.index)
                self.modes.append(mode)
                self.index += 1
                return SimpleNamespace(id=f"reference-{self.index}", thread_id="one-thread", done=True,
                    text="Reference actor only; not a model answer.", events=[{"type": "done"}],
                    condition=threading.Condition(), trace=[], metrics={})

            def close(self):
                self.closed = True

        profile = {"id": "reference", "model": "not-a-model", "backend": "compatible"}
        for case in workflows.CASES:
            with self.subTest(case=case["id"]):
                result = comparison.run_workflow_case(case, profile, 30, ActorRuntime)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(len(result["turns"]), len(case["turns"]))
                self.assertTrue(all(c["passed"] for c in result["objective_checks"]["checks"]), result["objective_checks"])
                self.assertEqual(instances[-1].modes, [case["mode"]] * len(case["turns"]))
                self.assertTrue(instances[-1].closed)
                self.assertFalse(instances[-1].directory.exists())

        class PrematureActor(ActorRuntime):
            def submit(self, project_id, message, mode, model):
                job = super().submit(project_id, message, mode, model)
                if self.index == 1:
                    self.store.accept_experiment(self.store._experiments(project_id)[0]["id"], "Premature acceptance")
                return job

        case = next(c for c in workflows.CASES if c["id"] == "wf_accept_after_review")
        result = comparison.run_workflow_case(case, profile, 30, PrematureActor)
        self.assertEqual(result["status"], "completed")
        failed = [c["id"] for c in result["objective_checks"]["checks"] if not c["passed"]]
        self.assertEqual(failed, ["turn_1:first_turn_draft_not_accepted"])

    def test_reference_actors_satisfy_every_frozen_workflow_and_milestone(self):
        self.assertEqual(len(workflows.CASES), 12)
        self.assertEqual(len({case["id"] for case in workflows.CASES}), 12)
        for case in workflows.CASES:
            with self.subTest(case=case["id"]), tempfile.TemporaryDirectory() as directory:
                store = Store(directory)
                pid, context, turns = workflows.setup(store, case)
                initial = workflows.snapshot(store, pid)
                for index, prompt in enumerate(turns):
                    for criterion in case["reference_criteria"]:
                        self.assertNotIn(criterion, prompt)
                    perform(store, pid, context, case["id"], index)
                    checks = workflows.check_turn(case["id"], index, initial, workflows.snapshot(store, pid), context)
                    self.assertTrue(all(c["passed"] for c in checks["checks"]), checks)
                checked = workflows.check(case["id"], initial, workflows.snapshot(store, pid), context)
                self.assertTrue(all(c["passed"] for c in checked["checks"]), checked)

    def test_noop_does_not_pass_positive_workflows(self):
        for case in workflows.CASES:
            with self.subTest(case=case["id"]), tempfile.TemporaryDirectory() as directory:
                store = Store(directory)
                pid, context, _ = workflows.setup(store, case)
                state = workflows.snapshot(store, pid)
                checked = workflows.check(case["id"], state, state, context)
                self.assertTrue(any(not c["passed"] for c in checked["checks"]))

    def test_first_turn_boundary_failures_are_retained_even_if_final_state_could_pass(self):
        for identifier in ("wf_accept_after_review", "wf_clarify_export"):
            case = next(c for c in workflows.CASES if c["id"] == identifier)
            with self.subTest(case=identifier), tempfile.TemporaryDirectory() as directory:
                store = Store(directory)
                pid, context, _ = workflows.setup(store, case)
                initial = workflows.snapshot(store, pid)
                perform(store, pid, context, identifier, 0)
                perform(store, pid, context, identifier, 1)  # Deliberately premature acceptance/export.
                checked = workflows.check_turn(identifier, 0, initial, workflows.snapshot(store, pid), context)
                self.assertTrue(any(not c["passed"] for c in checked["checks"]))

    def test_incorrect_extraction_and_shared_override_fail(self):
        for identifier in ("wf_evidence_extract", "wf_candidate_override"):
            case = next(c for c in workflows.CASES if c["id"] == identifier)
            with self.subTest(case=identifier), tempfile.TemporaryDirectory() as directory:
                store = Store(directory)
                pid, context, _ = workflows.setup(store, case)
                initial = workflows.snapshot(store, pid)
                if identifier == "wf_evidence_extract":
                    store.add_source(pid, "Extracted cost fields", json.dumps({"unit_price_usd_per_l": 19,
                                     "price_basis": "supplier estimate", "service_life_established": True}), workflows.SOURCE_URL)
                else:
                    store.update_assumptions(pid, {"usable_lifetime_cycles": 80}, "Incorrect shared mutation")
                    store.calculate(pid, "o-36")
                    store.calculate(pid, "o-37")
                checked = workflows.check(identifier, initial, workflows.snapshot(store, pid), context)
                self.assertTrue(any(not c["passed"] for c in checked["checks"]))

    def test_build_probe_rejects_hardcoded_outputs_and_missing_domain_validation(self):
        self.assertTrue(workflows._method_behavior({"source": TOTAL_CODE}))
        self.assertFalse(workflows._method_behavior({"source": 'def calculate(inputs):\n    return {"usd_per_kg": 300}\n'}))
        unguarded = ('def calculate(inputs):\n'
                     '    return {"usd_per_kg": inputs["annual_cost_usd"] / inputs["annual_output_kg"]}\n')
        self.assertFalse(workflows._method_behavior({"source": unguarded}))

    def test_build_grader_requires_the_requested_independent_reference_examples(self):
        case = next(c for c in workflows.CASES if c["id"] == "wf_build_method")
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            pid, context, _ = workflows.setup(store, case)
            initial = workflows.snapshot(store, pid)
            perform(store, pid, context, case["id"], 0)
            final = workflows.snapshot(store, pid)
            for method in final["methods"]:
                if method.get("status") == "registered":
                    method["reference_cases"] = [method["reference_cases"][0]] * 2
            checked = workflows.check(case["id"], initial, final, context)
            self.assertFalse(next(c["passed"] for c in checked["checks"] if c["id"] == "checked_method_registered_and_used"))


if __name__ == "__main__":
    unittest.main()
