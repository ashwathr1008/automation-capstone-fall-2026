"""Paired changes retain missing observations and timing scope."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("comparison_pairs", Path(__file__).resolve().parents[1] / "evaluations/comparison_pairs.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def row(profile, case, passed, status="completed", elapsed=10, repetition=1):
    return {"profile_id": profile, "id": case, "repetition": repetition, "objective_task_passed": passed,
            "status": status, "elapsed_seconds": elapsed, "tool_calls": 3, "tool_failures": 1,
            "evidence_origin": {"source_row_sha256": profile + case}}


class PairedComparisonTests(unittest.TestCase):
    specs = [("test", "training", "4B", "off", "base", "trained")]

    def test_missing_pairs_not_failures_and_timeouts_remain_task_failures(self):
        rows = [row("base", "improve", False), row("trained", "improve", True),
                row("base", "regress", True), row("trained", "regress", False, "timeout", 300), row("base", "missing", True)]
        result = module.paired_comparisons({"case_results": rows}, self.specs)
        contrast = result["contrasts"][0]
        self.assertEqual(contrast["matched_attempt_pairs"], 2)
        self.assertEqual(contrast["missing_pairs"], 1)
        self.assertEqual(contrast["transition_counts"], {"improved": 1, "missing": 1, "regressed": 1})
        self.assertEqual(contrast["net_pass_change"], 0)
        regress = next(r for r in result["attempt_pairs"] if r["case_id"] == "regress")
        self.assertIsNone(regress["elapsed_seconds_change"])
        self.assertEqual(regress["after_evidence"]["source_row_sha256"], "trainedregress")

    def test_task_aggregation_does_not_multiply_distinct_workflows(self):
        rows = [row(p, "one_workflow", p == "trained", repetition=r) for p in ("base", "trained") for r in (1, 2, 3)]
        result = module.paired_comparisons({"case_results": rows}, self.specs)
        self.assertEqual(len(result["per_task"]), 1)
        self.assertEqual(result["contrasts"][0]["net_pass_change"], 3)
        self.assertEqual(result["contrasts"][0]["pass_rate_difference_percentage_points"], 100)

    def test_duplicate_attempt_refused(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            module.paired_comparisons({"case_results": [row("base", "one", True)] * 2}, self.specs)


if __name__ == "__main__":
    unittest.main()
