"""Failure accounting tests with synthetic traces and no model requests."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("comparison_summary", Path(__file__).resolve().parents[1] / "evaluations" / "summarize_comparison.py")
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)


def row(case_id="sample", repetition=1, **changes):
    result = {"profile_id": "model-a", "model": "model-a-v1", "id": case_id, "repetition": repetition,
              "category": "objective_tool_contract", "status": "completed", "elapsed_seconds": 10,
              "objective_checks": {"checks": [{"id": "saved_fact", "passed": True}]},
              "metrics": {"total_seconds": 8, "token_usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}},
              "scientific_review": {"status": "unreviewed"}, "trace": []}
    result.update(changes)
    return result


def report(*rows):
    return {"suite_id": "synthetic", "objective_cases_sha256": "fixed-cases",
            "profiles": [{"id": "model-a", "model": "model-a-v1"}], "results": list(rows)}


class SummaryTests(unittest.TestCase):
    def test_failed_tool_can_recover_and_task_fail_can_have_no_tool_errors(self):
        recovered = row(trace=[
            {"type": "tool_call", "id": "bad", "name": "prioritize_candidates", "success": False,
             "arguments": {"assumption_overrides": {"support": "example"}}, "error": "Unsupported assumption(s): support"},
            {"type": "tool_call", "id": "good", "name": "prioritize_candidates", "success": True},
        ])
        omitted = row("omitted", objective_checks={"checks": [{"id": "requested_override", "passed": False}]},
                      trace=[{"type": "tool_call", "name": "prioritize_candidates", "success": True}])
        result = summary.summarize_reports([("synthetic.json", report(recovered, omitted))])
        model = result["model_summary"]["model-a"]
        self.assertEqual(model["objective_tasks_passed"], 1)
        self.assertEqual(model["objective_tasks_attempted"], 2)
        self.assertEqual(model["tasks_passed_despite_tool_failures"], 1)
        self.assertEqual(model["tasks_failed_without_tool_failures"], 1)
        self.assertEqual(model["tool_calls_failed"], 1)
        self.assertEqual(result["tool_failures"][0]["error_category"], "invalid_arguments")
        self.assertTrue(result["tool_failures"][0]["later_success_same_tool"])
        self.assertEqual(result["task_failures"][0]["failed_checks"][0]["id"], "requested_override")
        self.assertEqual(result["tool_summary"][0]["calls"], 3)

    def test_timeouts_and_errors_remain_in_task_denominator(self):
        result = summary.summarize_reports([("a", report(row(), row("timeout", status="timeout", objective_checks={}),
                                                         row("error", status="error", objective_checks={}, metrics={})))])
        model = result["model_summary"]["model-a"]
        self.assertEqual(model["objective_tasks_attempted"], 3)
        self.assertEqual(model["objective_tasks_passed"], 1)
        self.assertEqual(model["objective_task_success_rate"], 1 / 3)
        self.assertEqual(model["objective_tasks_without_checks"], 2)
        self.assertEqual(model["token_usage"]["total_tokens"]["observed_cases"], 2)
        self.assertFalse(model["token_usage"]["total_tokens"]["complete_coverage"])
        self.assertEqual(model["all_attempt_case_seconds"]["n"], 3)
        self.assertEqual(model["completed_case_seconds"]["n"], 1)

    def test_unfinished_calls_and_unknown_outcomes_are_not_successes(self):
        trace = [{"type": "tool_started", "id": "a", "name": "read_source"},
                 {"type": "tool_call", "id": "a", "name": "read_source", "success": True},
                 {"type": "tool_started", "id": "b", "name": "calculate_economics"},
                 {"type": "tool_call", "id": "c", "name": "list_methods", "success": None}]
        result = summary.summarize_reports([("a", report(row(trace=trace)))])
        model = result["model_summary"]["model-a"]
        self.assertEqual(model["tool_calls"], 3)
        self.assertEqual(model["tool_calls_succeeded"], 1)
        self.assertEqual(model["tool_calls_outcome_unknown"], 2)
        self.assertEqual(model["tool_success_rate_known_outcomes"], 1)

    def test_flattened_turns_not_double_counted_and_fallback_works(self):
        call = {"type": "tool_call", "id": "a", "name": "mcp__lanm__read_source", "success": True}
        result = row(trace=[{**call, "turn_index": 0}], turns=[{"trace": [call]}])
        self.assertEqual(len(summary.tool_calls(result)), 1)
        del result["trace"]
        self.assertEqual(summary.tool_calls(result)[0]["turn_index"], 0)
        self.assertEqual(summary.tool_name(call), "read_source")

    def test_duplicate_attempts_refused_unless_explicit(self):
        data = report(row())
        with self.assertRaisesRegex(ValueError, "Duplicate profile/case/repetition"):
            summary.summarize_reports([("a", data), ("b", deepcopy(data))])
        combined = summary.summarize_reports([("a", data), ("b", deepcopy(data))], allow_duplicates=True)
        self.assertEqual(combined["model_summary"]["model-a"]["attempted"], 2)
        self.assertTrue(any("both attempts counted" in text for text in combined["warnings"]))

    def test_missing_usage_unavailable_models_and_science_stay_explicit(self):
        data = report(row(category="scientific_review", objective_checks={}, metrics={}))
        data["profiles"].append({"id": "model-b", "model": "unavailable"})
        data["results"].append(row(profile_id="model-b", status="unavailable", error="Authentication required"))
        result = summary.summarize_reports([("a", data)])
        a, b = result["model_summary"]["model-a"], result["model_summary"]["model-b"]
        self.assertEqual(a["objective_tasks_attempted"], 0)
        self.assertIsNone(a["objective_task_success_rate"])
        self.assertIsNone(a["token_usage"]["total_tokens"]["observed_sum"])
        self.assertEqual(a["scientific_review_status_counts"], {"unreviewed": 1})
        self.assertEqual(b["attempted"], 0)
        self.assertEqual(b["not_attempted_count"], 1)
        self.assertTrue(any("coverage" in text for text in result["warnings"]))

    def test_mixed_conditions_warn_and_recurring_errors_group_fresh_ids(self):
        first = report(row(trace=[{"type": "tool_call", "name": "get_run", "success": False,
                                   "error": "run_ab1234 not found"}]))
        second = report(row(repetition=2, trace=[{"type": "tool_call", "name": "get_run", "success": False,
                                                "error": "run_cd5678 not found"}]))
        second["objective_cases_sha256"] = "different-cases"
        result = summary.summarize_reports([("a", first), ("b", second)])
        self.assertTrue(any("objective_cases_sha256" in text for text in result["warnings"]))
        group = result["recurring_tool_errors"][0]
        self.assertEqual(group["count"], 2)
        self.assertEqual(group["attempts"], 2)
        self.assertEqual(group["error_category"], "record_not_found")
        self.assertEqual(group["error_signature"], "<record-id> not found")

    def test_json_and_csv_outputs_handle_unicode_and_do_not_mutate_input(self):
        original = report(row(trace=[{"type": "tool_call", "name": "read_source", "success": False,
                                      "error": "A comma, a quote \" and units µL"}]))
        before = deepcopy(original)
        result = summary.summarize_reports([("input.json", original)])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.json"
            summary.write_outputs(result, path)
            self.assertEqual(len(list(Path(directory).glob("*.csv"))), 5)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["tool_failures"][0]["error"],
                             original["results"][0]["trace"][0]["error"])
        self.assertEqual(original, before)

    def test_multiturn_reported_models_and_terminal_error_text_are_preserved(self):
        failed = row(status="error", metrics={"reported_models": ["checkpoint-a", "checkpoint-b"]},
                     turns=[{"turn_index": 1, "status": "completed"},
                            {"turn_index": 2, "status": "error", "terminal": {"type": "error", "text": "Endpoint refused this model"}}])
        result = summary.summarize_reports([("a", report(failed))])
        self.assertEqual(result["model_summary"]["model-a"]["reported_models"], ["checkpoint-a", "checkpoint-b"])
        error = result["task_failures"][0]["execution_error"]
        self.assertEqual(error, [{"turn_index": 2, "status": "error", "error": "Endpoint refused this model"}])

    def test_configuration_manifest_keeps_planned_missing_and_original_identity(self):
        data = report(row())
        result = summary.summarize_reports([("a", data)])
        before = deepcopy(result["profiles"])
        summary.apply_configuration_manifest(result, {"configurations": [
            {"profile_id": "model-a", "display_name": "Base A", "model": "model-a-v1", "training": "base", "thinking": "off"},
            {"profile_id": "model-b", "display_name": "Trained B (planned)", "training": "planned", "thinking": "on"}]})
        self.assertEqual(result["configuration_order"], ["model-a", "model-b"])
        self.assertEqual(result["model_summary"]["model-b"]["attempted"], 0)
        self.assertIsNone(result["model_summary"]["model-b"]["objective_task_success_rate"])
        self.assertEqual(result["profiles"], before)
        self.assertEqual(len(result["case_results"]), 1)

    def test_configuration_manifest_rejects_mislabeling_and_unproven_training(self):
        data = report(row())
        data["profiles"][0]["enable_thinking"] = False
        result = summary.summarize_reports([("a", data)])
        for change, message in [({"model": "different"}, "model differs"), ({"thinking": "on"}, "thinking differs"),
                                ({"training": "planned"}, "planned training"), ({"training": "trained"}, "artifact_sha256")]:
            with self.subTest(change=change):
                with self.assertRaisesRegex(ValueError, message):
                    summary.apply_configuration_manifest(result, {"configurations": [{"profile_id": "model-a", **change}]})
        self.assertNotIn("configurations", result)
        summary.apply_configuration_manifest(result, {"configurations": [{"profile_id": "model-a", "training": "trained",
                                                                        "training_artifact_sha256": "a" * 64}]})
        self.assertEqual(result["configurations"]["model-a"]["training"], "trained")

    def test_tool_coverage_uses_recorded_allowlist_and_separates_unrecognized_calls(self):
        data = report(row(trace=[{"type": "tool_call", "name": "read_source", "success": True},
                                 {"type": "tool_call", "name": "read_source", "success": True},
                                 {"type": "tool_call", "name": "unknown_tool", "success": False}]))
        data.update(repeat=3, selected_case_ids=["sample", "unrun"], local_tool_allowlist=["read_source", "save_source"],
                    build_tool_allowlist=["read_source", "save_source", "check_method"])
        result = summary.summarize_reports([("a", data)])
        coverage = result["coverage"]
        self.assertEqual(coverage["distinct_workflow_types_observed"], 1)
        self.assertEqual(coverage["planned_workflow_type_count"], 2)
        self.assertEqual(coverage["planned_repeats_per_task"], [3])
        self.assertEqual(coverage["observed_tool_type_count"], 2)
        self.assertEqual(coverage["observed_lanm_tool_type_count"], 1)
        self.assertEqual(coverage["other_observed_tool_names"], ["unknown_tool"])
        self.assertEqual(coverage["research_allowed_tool_count"], 2)
        self.assertEqual(coverage["build_allowed_tool_count"], 3)


if __name__ == "__main__":
    unittest.main()
