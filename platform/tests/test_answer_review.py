"""Protect blinded review sampling, evidence fidelity, and unreviewed ratings."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("answer_review", Path(__file__).resolve().parents[1] / "evaluations" / "prepare_answer_review.py")
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


def report(profile="hidden-a", cases=("one", "two")):
    return {"status": "run_finished", "results": [
        {"profile_id": profile, "model": "hidden-checkpoint", "category": "objective_tool_contract", "id": case,
         "repetition": repeat, "status": "completed", "elapsed_seconds": 11,
         "objective_checks": {"checks": [{"id": "secret_grade", "passed": True}]},
         "prompt": "Use the supplied cost", "answer": "Cost is $40/kg.",
         "initial_state": {"cost": 80, "output": 2}, "trace": [
             {"type": "tool_call", "name": "mcp__lanm__calculate_economics", "success": True,
              "arguments": {"cost": 80}, "result": {"content": [{"type": "text", "text": '{"usd_per_kg":40}'}]}}]}
        for repeat in (1, 2, 3) for case in cases]}


class AnswerReviewTests(unittest.TestCase):
    def test_blinding_omits_identity_grades_and_timings_but_preserves_evidence(self):
        original = report()
        before = deepcopy(original)
        packet, key = review.prepare_packet([("hidden-source.json", original)])
        text = json.dumps(packet)
        for secret in ("hidden-a", "hidden-checkpoint", "hidden-source", "secret_grade", "elapsed_seconds", "objective_checks"):
            self.assertNotIn(secret, text)
        item = packet["items"][0]
        self.assertEqual(item["conversation"][0]["answer"], "Cost is $40/kg.")
        self.assertEqual(item["conversation"][0]["tool_evidence"][0]["result"], {"usd_per_kg": 40})
        self.assertEqual(item["reference_material"]["initial_state"], {"cost": 80, "output": 2})
        self.assertTrue(all(rating["rating"] is None for rating in item["review"]["ratings"].values()))
        self.assertEqual(key["profile_item_counts"], {"hidden-a": 2})
        self.assertEqual(original, before)

    def test_fixed_repetition_is_balanced_and_order_independent(self):
        reports = [("a", report()), ("b", report("hidden-b"))]
        first, key = review.prepare_packet(reports, repetition=2)
        second, _ = review.prepare_packet(list(reversed(reports)), repetition=2)
        self.assertEqual(first["items"], second["items"])
        self.assertEqual(first["item_count"], 4)
        self.assertTrue(all(row["repetition"] == 2 for row in key["key"].values()))
        with self.assertRaisesRegex(ValueError, "unmatched"):
            review.prepare_packet([("a", report()), ("b", report("hidden-b", ("one",)))])

    def test_unfinished_duplicate_and_missing_attempts_are_not_silently_reviewed(self):
        pending = report()
        pending["status"] = "running"
        with self.assertRaisesRegex(ValueError, "finished reports"):
            review.prepare_packet([("a", pending)])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            review.prepare_packet([("a", report()), ("b", report())])
        missing = report()
        for row in missing["results"]:
            row["status"] = "not_run"
        with self.assertRaisesRegex(ValueError, "No attempted"):
            review.prepare_packet([("a", missing)])

    def test_multiturn_answers_and_self_identification_are_not_rewritten(self):
        source = report(cases=("one",))
        source["results"][0]["turns"] = [
            {"prompt": "Draft only", "answer": "I am model X. Draft saved.", "trace": []},
            {"prompt": "Accept it", "answer": "Accepted.", "trace": []}]
        packet, _ = review.prepare_packet([("a", source)])
        turns = packet["items"][0]["conversation"]
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]["answer"], "I am model X. Draft saved.")
        self.assertTrue(any("self-identification" in line for line in packet["instructions"]))


if __name__ == "__main__":
    unittest.main()
