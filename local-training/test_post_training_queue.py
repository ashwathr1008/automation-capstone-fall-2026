"""Queue preparation and simulated orchestration; never calls a model or GPU."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import post_training_queue as queue


class PostTrainingQueueTests(unittest.TestCase):
    def setUp(self):
        (queue.ROOT / "tmp").mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="postqueue-test-", dir=queue.WORKSPACE)
        self.local = tempfile.TemporaryDirectory(prefix="postqueue-plan-test-", dir=queue.ROOT / "tmp")
        self.folder, self.local_folder = Path(self.temporary.name), Path(self.local.name)
        profiles = []
        for trained in (False, True):
            for size, port in (("4b", 18082 if trained else 18080), ("9b", 18083 if trained else 18081)):
                for thinking in (False, True):
                    identifier = (f"qwen-{size}-trained" + ("-thinking" if thinking else "") if trained
                        else f"qwen-{size}-thinking" if thinking else "qwen-local" if size == "4b" else "qwen-9b-local")
                    profiles.append({"id": identifier, "name": identifier, "backend": "compatible",
                        "model": f"qwen3.5-{size}" + ("-lanm" if trained else ""), "base_url": f"http://127.0.0.1:{port}/v1",
                        "enable_thinking": thinking, "request_timeout": 180, "max_tool_rounds": 12, "max_output_tokens": 4096})
        self.profiles = self.folder / "profiles.json"
        self.profiles.write_text(json.dumps({"profiles": profiles}), encoding="utf-8")
        self.plan = queue.build_plan(self.profiles, self.folder / "reports")

    def tearDown(self):
        self.local.cleanup()
        self.temporary.cleanup()

    def report(self, item):
        report = queue.clarified.report_template([item["profile"]], True)
        report.update(status="run_finished", selected_case_ids=item["case_ids"], results=[
            {"id": case, "profile_id": item["profile_id"], "repetition": rep, "status": "error", "trace": [],
             "metrics": {}, "objective_checks": {"checks": []}} for case in item["case_ids"] for rep in (1, 2, 3)])
        if not item["clarified"]:
            report["suite_id"] = "lanm_provider_comparison"
            report["harness_sha256"] = queue.sha(Path(queue.comparison.__file__))
        return report

    def test_plan_has_exact_sequence_profiles_and_408_attempts(self):
        self.assertEqual(self.plan["benchmark_attempts"], 408)
        self.assertEqual(self.plan["integration_smokes"], 2)
        self.assertEqual(self.plan["missing_profiles"], [])
        self.assertEqual([stage["id"] for stage in self.plan["stages"]], ["base-4b", "base-9b", "trained-4b", "trained-9b"])
        self.assertEqual([len(stage["benchmarks"]) for stage in self.plan["stages"]], [4, 4, 4, 4])
        names = {Path(item["output"]).name for stage in self.plan["stages"] for item in stage["benchmarks"]}
        self.assertEqual(names, {f"clarified-qwen{size}{trained}{thinking}.json" for size in (4, 9)
            for trained in ("", "-trained") for thinking in ("", "-thinking")} |
            {f"qwen{size}{trained}{thinking}.json" for size in (4, 9) for trained in ("", "-trained") for thinking in ("", "-thinking")})

    def test_prepare_never_calls_subprocess_network_or_execution(self):
        with patch.object(queue, "execute", side_effect=AssertionError("Explicit run required")), \
             patch.object(queue.subprocess, "run", side_effect=AssertionError("No process in prepare")), \
             patch.object(queue.urllib.request, "urlopen", side_effect=AssertionError("No HTTP in prepare")):
            result = queue.main(["--prepare", "--profiles-file", str(self.profiles), "--output-dir", str(self.folder / "reports"),
                                 "--plan", str(self.local_folder / "plan.json")])
        self.assertEqual(result, 0)
        self.assertTrue((self.local_folder / "plan.json").is_file())

    def test_complete_failed_attempts_are_retained_but_missing_attempts_rejected(self):
        for item in (self.plan["stages"][0]["benchmarks"][0], self.plan["stages"][2]["benchmarks"][0]):
            report = self.report(item)
            self.assertTrue(queue.validate_report(report, item, require_complete=True))
            report["results"].pop()
            with self.assertRaises(ValueError):
                queue.validate_report(report, item, require_complete=True)

    def test_incomplete_training_stops_before_server_or_model_calls(self):
        with patch.object(queue, "validate_artifacts", side_effect=ValueError("Training incomplete")), \
             patch.object(queue, "invoke", side_effect=AssertionError("No process before artifacts")) as invoke:
            with self.assertRaisesRegex(ValueError, "Training incomplete"):
                queue.execute(self.plan)
            invoke.assert_not_called()

    def test_simulated_queue_accepts_exit_one_and_never_overlaps_servers(self):
        active, calls = [], []
        def validate(plan, resume):
            for stage in plan["stages"]:
                stage["artifact_identity"] = {"fixture": stage["id"]}
        def invoke(command, log=None, append=False):
            for stage in self.plan["stages"]:
                if command == stage["start"]:
                    self.assertFalse(active)
                    active.append(stage["id"])
                    calls.append("start:" + stage["id"])
                    return 0
                if command == stage["stop"]:
                    self.assertEqual(active.pop(), stage["id"])
                    calls.append("stop:" + stage["id"])
                    return 0
                if command == stage["smoke"]:
                    self.assertEqual(active, [stage["id"]])
                    calls.append("smoke:" + stage["id"])
                    return 0
                for item in stage["benchmarks"]:
                    if command == item["command"]:
                        self.assertEqual(active, [stage["id"]])
                        queue.save(Path(item["output"]), self.report(item))
                        calls.append("benchmark:" + item["profile_id"])
                        return 1  # Complete benchmark with failed attempts is valid evidence.
            self.fail("Unexpected subprocess: " + repr(command))
        runtime = self.local_folder / "runtime"
        runtime.mkdir()
        with patch.object(queue, "ROOT", runtime), patch.object(queue, "validate_execution", side_effect=validate), \
             patch.object(queue, "invoke", side_effect=invoke), patch.object(queue, "wait_ready", return_value={"fixture": True}):
            self.assertEqual(queue.execute(self.plan), 0)
            before = list(calls)
            self.assertEqual(queue.execute(self.plan, resume=True), 0)
            self.assertEqual(calls, before)
        self.assertFalse(active)
        self.assertEqual(sum(call.startswith("benchmark:") for call in calls), 16)
        self.assertEqual(sum(call.startswith("start:") for call in calls), 4)
        self.assertEqual(sum(call.startswith("stop:") for call in calls), 4)
        self.assertEqual(sum(call.startswith("smoke:") for call in calls), 2)


if __name__ == "__main__":
    unittest.main()
