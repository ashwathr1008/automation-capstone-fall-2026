"""Keep clarified-task replacement complete, auditable, and free of double counts."""
from copy import deepcopy
import importlib.util
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "evaluations"
def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

combine = load("clarified_combiner", "combine_clarified_comparison.py")
summary = load("clarified_summary", "summarize_comparison.py")


def fixture(profile="model-a", clarified=False):
    cases = [combine.CLARIFIED_CASE] if clarified else ["retained", combine.ORIGINAL_CASE]
    result = {"status": "run_finished", "repeat": 3, "timeout_seconds": 300,
              "profiles": [{"id": profile, "model": "weights-a", "enable_thinking": False}],
              "local_tool_allowlist": ["retained_tool"], "build_tool_allowlist": ["retained_tool", "new_tool"], "results": [],
              "harness_sha256": "new-harness" if clarified else "old-harness",
              "objective_cases_sha256": "new-cases" if clarified else "old-cases",
              "workflow_implementation_sha256": "same-workflow", "scientific_runner_sha256": "same-runner",
              "implementation_sha256": {"runtime.py": "same-runtime", "core.py": "same-core"}}
    if clarified:
        result["base_harness_sha256"] = "old-harness"
        result["clarification"] = {"original_case_id": combine.ORIGINAL_CASE, "case_id": combine.CLARIFIED_CASE,
                                   "prompt": "Clarified task", "prompt_sha256": hashlib.sha256(b"Clarified task").hexdigest()}
    for case in cases:
        for repeat in (1, 2, 3):
            old = case == combine.ORIGINAL_CASE
            row = {"profile_id": profile, "model": "weights-a", "category": "objective_tool_contract", "id": case,
                   "repetition": repeat, "status": "completed", "elapsed_seconds": 999 if old else 10,
                   "objective_checks": {"checks": [{"id": "saved", "passed": not old}]},
                   "metrics": {"token_usage": {"total_tokens": 999 if old else 10}},
                   "trace": [{"type": "tool_call", "name": "old_tool" if old else "new_tool", "success": not old}]}
            if clarified:
                row.update(prompt_sha256=result["clarification"]["prompt_sha256"], prompt="Clarified task",
                           original_case_id=combine.ORIGINAL_CASE, checker_case_id=combine.ORIGINAL_CASE)
            result["results"].append(row)
    return result


def run(original=None, revised=None):
    return combine.combine_reports([("original.json", original or fixture(), "a" * 64)],
                                   [("clarified.json", revised or fixture(clarified=True), "c" * 64)], expected_workflows=2)


class ClarifiedComparisonTests(unittest.TestCase):
    def test_replaces_all_repetitions_preserves_raw_sources_and_exact_provenance(self):
        original, revised = fixture(), fixture(clarified=True)
        before = deepcopy((original, revised))
        result, manifest = run(original, revised)
        self.assertEqual(len(result["results"]), 6)
        self.assertEqual(len(manifest["replacements"]), 3)
        self.assertNotIn(combine.ORIGINAL_CASE, [r["id"] for r in result["results"]])
        for row in result["results"]:
            origin = row["evidence_origin"]
            source = original if origin["role"] == "original" else revised
            raw = source["results"][origin["source_result_index"]]
            self.assertEqual(origin["source_row_sha256"], combine.row_hash(raw))
            self.assertEqual({k: v for k, v in row.items() if k != "evidence_origin"}, raw)
        self.assertEqual((original, revised), before)

    def test_removed_task_calls_tokens_and_timings_do_not_leak_into_summary(self):
        derived, _ = run()
        data = summary.summarize_reports([("derived.json", derived)])
        model = data["model_summary"]["model-a"]
        self.assertEqual(model["objective_tasks_passed"], 6)
        self.assertEqual(model["tool_calls"], 6)
        self.assertEqual(model["tool_calls_failed"], 0)
        self.assertEqual(model["token_usage"]["total_tokens"]["observed_sum"], 60)
        self.assertEqual(model["all_attempt_case_seconds"]["max"], 10)
        self.assertEqual(data["tool_summary"][0]["tool"], "new_tool")
        self.assertTrue(all(row.get("evidence_origin") for row in data["case_results"]))
        self.assertEqual(data["analysis_corrections"][0]["id"], combine.CORRECTION_ID)

    def test_failed_replacement_is_kept_instead_of_falling_back_to_original(self):
        original, revised = fixture(), fixture(clarified=True)
        for row in original["results"]:
            row["objective_checks"]["checks"][0]["passed"] = True
        for status in ("timeout", "incomplete"):
            revised["results"][0]["status"] = status
            derived, _ = run(original, revised)
            data = summary.summarize_reports([("derived", derived)])
            self.assertEqual(data["model_summary"]["model-a"]["objective_tasks_passed"], 5)
            self.assertEqual(data["model_summary"]["model-a"]["objective_tasks_attempted"], 6)

    def test_missing_duplicate_or_mismatched_runs_are_rejected(self):
        for change, message in [("missing", "repetitions"), ("duplicate", "Duplicate"), ("profile", "same nonempty"),
                                ("thinking", "profile differs"), ("allowlist", "allowlist differs"), ("running", "finished")]:
            with self.subTest(change=change):
                revised = fixture(clarified=True)
                if change == "missing": revised["results"].pop()
                elif change == "duplicate": revised["results"].append(deepcopy(revised["results"][0]))
                elif change == "profile": revised = fixture("model-b", clarified=True)
                elif change == "thinking": revised["profiles"][0]["enable_thinking"] = True
                elif change == "allowlist": revised["build_tool_allowlist"].append("extra")
                elif change == "running": revised["status"] = "running"
                with self.assertRaisesRegex(ValueError, message): run(revised=revised)

    def test_prompt_provenance_and_original_case_identity_cannot_be_substituted(self):
        revised = fixture(clarified=True)
        revised["results"][0]["prompt_sha256"] = "different"
        with self.assertRaisesRegex(ValueError, "prompt hash"):
            run(revised=revised)
        revised = fixture(clarified=True)
        revised["results"][0]["id"] = combine.ORIGINAL_CASE
        with self.assertRaisesRegex(ValueError, "unexpected clarified case"):
            run(revised=revised)

    def test_mismatched_prespecified_plan_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "plan does not match"):
            combine.combine_reports([("old", fixture(), "a" * 64)],
                                    [("new", fixture(clarified=True), "b" * 64)],
                                    expected_workflows=2, correction_plan={"contents": {"repetitions": 1}})

    def test_deadline_declarations_and_actual_prompt_text_are_verified(self):
        for field, value in (("timeout_seconds", 600), ("repeat", 4)):
            revised = fixture(clarified=True)
            revised[field] = value
            with self.assertRaisesRegex(ValueError, "repeat/deadline"):
                run(revised=revised)
        revised = fixture(clarified=True)
        revised["clarification"]["prompt"] += " Changed instruction"
        with self.assertRaisesRegex(ValueError, "prompt text hash"):
            run(revised=revised)
        revised = fixture(clarified=True)
        revised["results"][0]["prompt"] += " Changed instruction"
        with self.assertRaisesRegex(ValueError, "row prompt text"):
            run(revised=revised)

    def test_runtime_checker_and_base_harness_drift_are_rejected(self):
        for field in ("workflow_implementation_sha256", "scientific_runner_sha256", "implementation_sha256", "base_harness_sha256"):
            with self.subTest(field=field):
                revised = fixture(clarified=True)
                revised[field] = {"runtime.py": "changed"} if field == "implementation_sha256" else "changed"
                with self.assertRaisesRegex(ValueError, field):
                    run(revised=revised)
        old_a, old_b = fixture(), fixture("model-b")
        old_b["harness_sha256"] = "changed-original-harness"
        with self.assertRaisesRegex(ValueError, "differing original harness_sha256"):
            combine.combine_reports([("a", old_a, "a" * 64), ("b", old_b, "b" * 64)],
                                    [("ca", fixture(clarified=True), "c" * 64), ("cb", fixture("model-b", clarified=True), "d" * 64)],
                                    expected_workflows=2)


if __name__ == "__main__":
    unittest.main()
