"""Check the narrowly defined rejection-format sensitivity, without models."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("method_audit", Path(__file__).resolve().parents[1] / "evaluations" / "audit_authored_methods.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def explicit_error(_source, inputs):
    if inputs["annual_cost_usd"] < 0 or inputs["annual_output_kg"] <= 0:
        return {"error": "Invalid input", "usd_per_kg": None}
    return {"usd_per_kg": inputs["annual_cost_usd"] / inputs["annual_output_kg"]}


def fixture():
    return {"status": "run_finished", "results": [{"profile_id": "synthetic", "id": "wf_build_method", "repetition": 1,
        "category": "objective_tool_contract", "status": "completed",
        "objective_checks": {"checks": [{"id": "registered", "passed": True}, {"id": audit.CHECK_ID, "passed": False}]},
        "final_state": {"runs": [{"kind": "custom_calculation", "method_id": "evaluation-total-cost@v1"}],
                        "methods": [{"id": "evaluation-total-cost@v1", "status": "registered", "source": "synthetic"}]}}]}


class RejectionPolicyTests(unittest.TestCase):
    def test_explicit_error_object_changes_only_the_behavior_check(self):
        source = fixture()
        before = deepcopy(source)
        result = audit.audit_reports([("synthetic.json", source)], explicit_error)
        self.assertEqual(result["profile_sensitivity"]["synthetic"],
                         {"attempted": 1, "strict_automated_passed": 0, "alternative_policy_passed": 1})
        self.assertEqual(len(result["changed_attempts"]), 1)
        self.assertEqual(source, before)
        source["results"][0]["objective_checks"]["checks"][0]["passed"] = False
        self.assertFalse(audit.audit_reports([("a", source)], explicit_error)["results"][0]["alternative_explicit_error_object_task_passed"])

    def test_zero_cost_remains_required_and_numeric_error_output_is_not_rejection(self):
        method = {"id": "test", "source": "synthetic"}
        def reject_zero(source, inputs):
            return {"error": "No zero cost"} if inputs["annual_cost_usd"] == 0 else explicit_error(source, inputs)
        self.assertFalse(audit.probe_method(method, reject_zero)["passes_explicit_error_object_policy"])
        def numeric_error(source, inputs):
            value = explicit_error(source, inputs)
            if value.get("error"):
                value["usd_per_kg"] = 0
            return value
        self.assertFalse(audit.probe_method(method, numeric_error)["passes_explicit_error_object_policy"])

    def test_uncompleted_tasks_and_unused_versions_cannot_distort_results(self):
        source = fixture()
        source["results"][0]["final_state"]["methods"].append(
            {"id": "evaluation-total-cost@unused", "status": "registered", "source": "unused"})
        def executor(code, inputs):
            self.assertNotEqual(code, "unused")
            return explicit_error(code, inputs)
        result = audit.audit_reports([("a", source)], executor)
        self.assertEqual(len(result["results"][0]["method_probes"]), 1)
        source["results"][0]["status"] = "error"
        self.assertFalse(audit.audit_reports([("a", source)], executor)["results"][0]["alternative_explicit_error_object_task_passed"])

    def test_duplicates_running_reports_and_unexpected_execution_errors_are_not_passes(self):
        source = fixture()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            audit.audit_reports([("a", source), ("b", source)], explicit_error)
        source["status"] = "running"
        with self.assertRaisesRegex(ValueError, "finished"):
            audit.audit_reports([("a", source)], explicit_error)
        def crashed(_source, _inputs):
            raise RuntimeError("Unavailable")
        self.assertFalse(audit.probe_method({"id": "test", "source": "synthetic"}, crashed)["passes_explicit_error_object_policy"])


if __name__ == "__main__":
    unittest.main()
