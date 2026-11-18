"""Check plotted denominators and missing-data behavior without rendering."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("comparison_plots", Path(__file__).resolve().parents[1] / "evaluations" / "plot_comparison.py")
plots = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plots)


def fixture():
    records = []
    for repetition, passed, status, failures, seconds in [(1, True, "completed", 0, 10),
                                                         (2, True, "completed", 2, 30),
                                                         (3, False, "timeout", 0, 100)]:
        records.append({"profile_id": "qwen-local", "id": "tool_economics", "repetition": repetition,
                        "category": "objective_tool_contract", "objective_task_passed": passed,
                        "status": status, "tool_failures": failures, "elapsed_seconds": seconds})
    return {"case_results": records, "model_summary": {"qwen-local": {}}, "profiles": {},
            "tool_summary": [{"profile_id": "qwen-local", "tool": "calculate_economics", "calls": 10,
                              "failed": 2, "unknown": 1, "attempts_with_failure": 1, "distinct_cases_with_failure": 1}],
            "source_reports": [{"status": "run_finished", "path": "synthetic.json"}]}


class PlotDataTests(unittest.TestCase):
    def test_success_recovery_failure_and_missing_models_keep_actual_denominators(self):
        data = plots.plotted_data(fixture())
        qwen = data["outcomes"][0]
        self.assertEqual((qwen["clean_success"], qwen["recovered_success"], qwen["failed"]), (1, 1, 1))
        self.assertEqual(qwen["success_rate"], 2 / 3)
        self.assertEqual(data["outcomes"][1]["attempted"], 0)
        self.assertIsNone(data["outcomes"][1]["success_rate"])
        self.assertEqual(data["task_matrix"][0]["models"][0]["passed"], 2)
        self.assertEqual(data["task_matrix"][0]["models"][1]["attempted"], 0)
        self.assertEqual(data["task_matrix"][0]["models"][1]["missing_from_planned_repeats"], 3)

    def test_latency_uses_completed_cases_only_and_retains_excluded_counts(self):
        data = plots.plotted_data(fixture())
        qwen = data["latency"][0]
        self.assertEqual(qwen["median_seconds"], 20)
        self.assertEqual(qwen["completed_case_seconds"], [10, 30])
        self.assertEqual(qwen["completed"], 2)
        self.assertEqual(qwen["attempted"], 3)
        self.assertEqual(qwen["excluded_noncompleted"], 1)
        self.assertIsNone(data["latency"][1]["median_seconds"])

    def test_tool_failures_keep_call_and_affected_attempt_denominators(self):
        data = plots.plotted_data(fixture())
        tool = data["tool_failure_rows"][0]
        self.assertEqual((tool["failed"], tool["calls"], tool["attempts_with_failure"], tool["distinct_cases_with_failure"]), (2, 10, 1, 1))
        self.assertEqual(data["tool_calls_unknown"], 1)
        self.assertEqual(data["all_tool_calls"], 10)

    def test_overfull_repeats_and_mixed_scientific_scope_are_not_silently_plotted(self):
        data = fixture()
        data["case_results"].append(deepcopy(data["case_results"][0]))
        with self.assertRaisesRegex(ValueError, "exceeding"):
            plots.plotted_data(data)
        data = fixture()
        data["case_results"].append({"profile_id": "qwen-local", "id": "scientific-case", "category": "scientific_review",
                                     "objective_task_passed": None})
        with self.assertRaisesRegex(ValueError, "same evaluation scope"):
            plots.plotted_data(data)

    def test_unfinished_reports_require_explicit_provisional_export(self):
        data = fixture()
        data["source_reports"][0]["status"] = "running"
        with self.assertRaisesRegex(ValueError, "unfinished"):
            plots.export_figures(data, "unused")

    def test_declared_configuration_order_labels_and_unobserved_tasks_are_preserved(self):
        source = fixture()
        source["planned_case_ids"] = ["tool_economics", "wf_evidence_extract"]
        source["configuration_order"] = ["qwen-local", "qwen-4b-trained-thinking"]
        source["configurations"] = {"qwen-local": {"display_name": "Qwen 4B · base · off", "group": "Qwen 4B", "training": "base", "thinking": "off"},
                                    "qwen-4b-trained-thinking": {"display_name": "Qwen 4B · trained · on (planned)", "group": "Qwen 4B", "training": "planned", "thinking": "on"}}
        data = plots.plotted_data(source)
        self.assertEqual(data["model_order"], source["configuration_order"])
        self.assertEqual(data["configurations"][1]["short_label"], "Trained*\nThink on")
        self.assertEqual(data["outcomes"][1]["attempted"], 0)
        self.assertIsNone(data["outcomes"][1]["success_rate"])
        self.assertEqual(data["task_matrix"][1]["models"][0]["attempted"], 0)
        with self.assertRaisesRegex(ValueError, "coverage is incomplete"):
            plots.export_figures(source, "unused")

    def test_corrected_results_are_explicitly_labeled_and_keep_the_new_case_identity(self):
        source = fixture()
        for row in source["case_results"]:
            row["id"] = "wf_build_method_clarified"
        source["analysis_corrections"] = [{"id": "authored_method_contract_clarification_v1"}]
        data = plots.plotted_data(source)
        self.assertEqual(data["case_ids"], ["wf_build_method_clarified"])
        self.assertEqual(data["task_matrix"][0]["label"], "Build a method with explicit validation")
        self.assertTrue(plots._subtitle(data).startswith("Clarified-task automated checks"))


if __name__ == "__main__":
    unittest.main()
