"""Workflow orchestration tests; no endpoints, accounts, or model requests."""
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


SPEC = importlib.util.spec_from_file_location("workflow_comparison_runner", Path(__file__).resolve().parents[1] / "evaluations" / "compare.py")
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)
PROFILE = {"id": "synthetic-model", "backend": "compatible", "model": "synthetic-v1"}
CASE = {"id": "synthetic_workflow", "title": "Synthetic two-turn workflow", "question": "Turn one, then turn two",
        "mode": "build", "reference_criteria": ["Unsubmitted review criterion"], "category": "objective_tool_contract"}


def fake_setup(store, case):
    pid = store.create_project("Synthetic workflow runner test", "Nd", "La")["id"]
    return pid, {"expected_first": 60, "expected_final": 120}, ["First user request", "Second user request"]


def fake_snapshot(store, pid):
    return deepcopy(store.get_project(pid))


def fake_check_turn(case_id, index, initial, current, context):
    return {"checks": [{"id": "first_value", "passed": current["assumptions"]["usable_lifetime_cycles"] == context["expected_first"]}]
            if index == 0 else []}


def fake_check(case_id, initial, final, context, trace=None):
    return {"checks": [{"id": "final_value", "passed": final["assumptions"]["usable_lifetime_cycles"] == context["expected_final"]}]}


def job(index, *, status="completed", done=True):
    return SimpleNamespace(id=f"job-{index}", thread_id="same-native-thread", done=done,
                           text=f"Synthetic answer {index}", events=[{"type": "error" if status == "error" else "done", "status": status}],
                           condition=threading.Condition(), trace=[{"type": "tool_call", "id": f"call-{index}",
                               "name": "update_assumptions", "success": True}],
                           metrics={"total_seconds": 1.0, "tool_call_count": 1, "reported_model": "synthetic-v1",
                                    "token_usage": {"prompt_tokens": index * 100, "completion_tokens": index * 10, "total_tokens": index * 110},
                                    "token_usage_scope": "thread_cumulative; isolated comparison"})


class ScriptedRuntime:
    def __init__(self, store, directory, *, values=(60, 120), statuses=("completed", "completed"), unfinished=False):
        self.store, self.directory = store, directory
        self.values, self.statuses, self.unfinished = values, statuses, unfinished
        self.submissions, self.jobs, self.closed, self.cancelled = [], {}, 0, []

    def submit(self, pid, prompt, mode, model):
        index = len(self.submissions)
        self.submissions.append((pid, prompt, mode, model))
        self.store.update_assumptions(pid, {"usable_lifetime_cycles": self.values[index]}, "Synthetic runner fixture")
        result = job(index + 1, status=self.statuses[index], done=not self.unfinished)
        if self.unfinished:
            result.events = []
        self.jobs[result.id] = result
        return result

    def cancel(self, identifier):
        self.cancelled.append(identifier)
        result = self.jobs[identifier]
        result.done = True
        result.events.append({"type": "done", "status": "cancelled"})

    def close(self):
        self.closed += 1


class WorkflowRunnerTests(unittest.TestCase):
    def run_synthetic(self, **runtime_settings):
        instances = []

        def factory(store, directory):
            runtime = ScriptedRuntime(store, directory, **runtime_settings)
            instances.append(runtime)
            return runtime

        with patch.object(comparison.workflows, "setup", side_effect=fake_setup), \
             patch.object(comparison.workflows, "snapshot", side_effect=fake_snapshot), \
             patch.object(comparison.workflows, "check_turn", side_effect=fake_check_turn), \
             patch.object(comparison.workflows, "check", side_effect=fake_check):
            result = comparison.run_workflow_case(CASE, PROFILE, 0.002 if runtime_settings.get("unfinished") else 10, factory)
        return result, instances

    def test_one_runtime_and_project_preserve_multiturn_context(self):
        result, instances = self.run_synthetic()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(instances), 1)
        runtime = instances[0]
        self.assertEqual(runtime.closed, 1)
        self.assertEqual(len(runtime.submissions), 2)
        self.assertEqual(len({item[0] for item in runtime.submissions}), 1)
        self.assertEqual([item[1] for item in runtime.submissions], ["First user request", "Second user request"])
        self.assertTrue(all(item[2] == "build" and item[3] == PROFILE["model"] for item in runtime.submissions))
        self.assertEqual([entry["turn_index"] for entry in result["trace"]], [1, 2])
        self.assertEqual([turn["thread_id"] for turn in result["turns"]], ["same-native-thread"] * 2)
        self.assertEqual(result["metrics"]["token_usage"]["total_tokens"], 220)
        self.assertTrue(all(check["passed"] for check in result["objective_checks"]["checks"]))
        self.assertFalse(runtime.directory.exists())
        self.assertTrue(result["temporary_project_removed"])

    def test_later_correct_state_does_not_erase_earlier_violation(self):
        result, _ = self.run_synthetic(values=(80, 120))
        checks = {check["id"]: check["passed"] for check in result["objective_checks"]["checks"]}
        self.assertFalse(checks["turn_1:first_value"])
        self.assertTrue(checks["final_value"])
        self.assertEqual(result["turns"][0]["state"]["assumptions"]["usable_lifetime_cycles"], 80)
        result.update(profile_id=PROFILE["id"], category="objective_tool_contract")
        self.assertEqual(comparison.summarize([result])[PROFILE["id"]]["objective_cases_completed_with_all_checks"], 0)

    def test_error_turn_stops_scripted_followups(self):
        result, instances = self.run_synthetic(statuses=("error", "completed"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(instances[0].submissions), 1)
        self.assertEqual(len(result["turns"]), 1)
        self.assertEqual(instances[0].closed, 1)

    def test_cancelled_terminal_stops_scripted_followups(self):
        result, instances = self.run_synthetic(statuses=("cancelled", "completed"))
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(len(instances[0].submissions), 1)

    def test_timeout_is_retained_in_attempted_task_denominator(self):
        result, instances = self.run_synthetic(unfinished=True)
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(instances[0].cancelled, ["job-1"])
        self.assertEqual(len(instances[0].submissions), 1)
        result.update(profile_id=PROFILE["id"], category="objective_tool_contract")
        totals = comparison.summarize([result])[PROFILE["id"]]
        self.assertEqual(totals["objective_cases_attempted"], 1)
        self.assertEqual(totals["objective_cases_completed_with_all_checks"], 0)
        self.assertEqual(totals["status_counts"], {"timeout": 1})

    def test_cumulative_usage_uses_last_thread_total_not_sum_of_turns(self):
        turns = [{"metrics": job(1).metrics}, {"metrics": job(2).metrics}]
        totals = comparison.aggregate_turn_metrics(turns)
        self.assertEqual(totals["token_usage"], {"prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 220})
        self.assertEqual(totals["token_usage_scope"], "final_thread_cumulative")
        self.assertEqual(totals["total_seconds"], 2)
        self.assertEqual(totals["reported_models"], ["synthetic-v1"])

    def test_per_turn_usage_sums_only_when_all_turn_usage_known(self):
        turns = [{"metrics": job(1).metrics}, {"metrics": job(2).metrics}]
        for turn in turns:
            turn["metrics"].pop("token_usage_scope")
        self.assertEqual(comparison.aggregate_turn_metrics(turns)["token_usage"]["total_tokens"], 330)
        turns[1]["metrics"]["token_usage"] = None
        totals = comparison.aggregate_turn_metrics(turns)
        self.assertIsNone(totals["token_usage"])
        self.assertFalse(totals["token_usage_complete"])


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.destination = Path(self.directory.name) / "report.json"
        self.base_args = ["--run", "--profile", PROFILE["id"], "--case", "tool_economics", "--repeat", "2", "--output", str(self.destination)]
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(comparison, "WORKSPACE", Path(self.directory.name)))
        self.stack.enter_context(patch.object(comparison, "load_profiles", return_value=[PROFILE]))
        self.stack.enter_context(patch.object(comparison, "runtime_factory_for", return_value=object()))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def write_initial(self):
        with patch.object(comparison, "run_objective_case", side_effect=[
            {"id": "tool_economics", "status": "error", "error": "Synthetic failure"},
            {"id": "tool_economics", "status": "completed", "elapsed_seconds": 1}]) as run:
            self.assertEqual(comparison.main(self.base_args), 1)
            self.assertEqual(run.call_count, 2)
        return json.loads(self.destination.read_text(encoding="utf-8"))

    def test_identical_resume_does_not_retry_completed_or_failed_attempts(self):
        before = self.write_initial()
        with patch.object(comparison, "run_objective_case", side_effect=AssertionError("No retry")):
            self.assertEqual(comparison.main(self.base_args + ["--resume"]), 1)
        after = json.loads(self.destination.read_text(encoding="utf-8"))
        self.assertEqual(after["results"], before["results"])
        self.assertEqual(len(after["resumed_at"]), 1)

    def test_resume_runs_only_missing_attempt(self):
        previous = self.write_initial()
        previous["results"] = previous["results"][:1]
        self.destination.write_text(json.dumps(previous), encoding="utf-8")
        with patch.object(comparison, "run_objective_case", return_value={"id": "tool_economics", "status": "completed", "elapsed_seconds": 1}) as run:
            self.assertEqual(comparison.main(self.base_args + ["--resume"]), 1)
            self.assertEqual(run.call_count, 1)
        after = json.loads(self.destination.read_text(encoding="utf-8"))
        self.assertEqual([item["repetition"] for item in after["results"]], [1, 2])
        self.assertEqual(after["results"][0]["error"], "Synthetic failure")

    def test_changed_timeout_or_profile_configuration_cannot_resume(self):
        self.write_initial()
        before = self.destination.read_bytes()
        for extra, profiles in [(["--timeout", "999"], [PROFILE]),
                                ([], [{**PROFILE, "max_tool_rounds": 4}]),
                                ([], [{**PROFILE, "model": "different-checkpoint"}])]:
            with self.subTest(extra=extra, profiles=profiles), \
                 patch.object(comparison, "load_profiles", return_value=profiles), \
                 patch.object(comparison, "run_objective_case", side_effect=AssertionError("No request")), \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                comparison.main(self.base_args + ["--resume"] + extra)
        self.assertEqual(self.destination.read_bytes(), before)

    def test_duplicate_existing_attempts_are_refused_before_resuming(self):
        previous = self.write_initial()
        previous["results"].append(deepcopy(previous["results"][0]))
        self.destination.write_text(json.dumps(previous), encoding="utf-8")
        before = self.destination.read_bytes()
        with patch.object(comparison, "run_objective_case", side_effect=AssertionError("No request")), \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            comparison.main(self.base_args + ["--resume"])
        self.assertEqual(self.destination.read_bytes(), before)

    def test_out_of_plan_attempt_or_modified_case_hash_cannot_resume(self):
        original = self.write_initial()
        altered_result = deepcopy(original)
        altered_result["results"][0]["repetition"] = 99
        altered_hash = deepcopy(original)
        altered_hash["workflow_implementation_sha256"] = "different-implementation"
        for previous in (altered_result, altered_hash):
            with self.subTest(previous=previous["workflow_implementation_sha256"]):
                self.destination.write_text(json.dumps(previous), encoding="utf-8")
                before = self.destination.read_bytes()
                with patch.object(comparison, "run_objective_case", side_effect=AssertionError("No request")), \
                     contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    comparison.main(self.base_args + ["--resume"])
                self.assertEqual(self.destination.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
