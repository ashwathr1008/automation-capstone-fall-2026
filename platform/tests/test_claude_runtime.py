"""Claude CLI boundary/trace checks with recorded synthetic protocol events."""
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from lanm_platform.claude_runtime import ClaudeRuntime
from lanm_platform.core import Store
from lanm_platform.providers import load_profiles, runtime_factory_for
from lanm_platform.runtime import Job


class Sink(io.StringIO):
    def close(self):
        self.saved = self.getvalue()


class Process:
    def __init__(self, events):
        self.stdin = Sink()
        self.stdout = io.StringIO("\n".join(json.dumps(e) for e in events) + "\n")
        self.stderr = io.StringIO("")
    def poll(self):
        return 0


def answer(text="Fixture answer.", model="claude-fixture-version"):
    return [{"type": "system", "subtype": "init", "session_id": "synthetic-session",
             "tools": ["mcp__lanm__project_state"], "model": model},
            {"type": "assistant", "message": {"model": model, "content": [
                {"type": "thinking", "thinking": "Private reasoning fixture"},
                {"type": "text", "text": text}]}},
            {"type": "result", "subtype": "success", "is_error": False,
             "result": text, "num_turns": 1, "duration_api_ms": 125,
             "usage": {"input_tokens": 100, "output_tokens": 10}, "total_cost_usd": 0.01}]


class ClaudeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.store = Store(self.directory)
        self.pid = self.store.create_project("Claude adapter fixture", "Nd", "La")["id"]
        self.runtime = ClaudeRuntime(self.store, self.directory, model="sonnet",
                                     tool_allowlist={"project_state", "save_method_draft"})

    def tearDown(self):
        self.runtime.close()
        for job in self.runtime.jobs.values():
            self.wait(job)
        self.temp.cleanup()

    def wait(self, job):
        deadline = time.monotonic() + 5
        with job.condition:
            while not job.done and time.monotonic() < deadline:
                job.condition.wait(.05)
        self.assertTrue(job.done)
        return job

    def job(self):
        job = Job(self.pid, "Fixture request", "research", "sonnet")
        job.metrics.update(reported_model=None, first_response_seconds=None, cost_usd=None)
        return job

    def test_allowlist_mode_and_native_capabilities_are_explicit(self):
        job = self.job()
        job.message_item = self.store.add_message(self.pid, "user", job.message)
        messages = self.runtime._context(job, self.store.get_project(self.pid))
        command, prompt = self.runtime._command(job, self.directory, messages)
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertEqual(command[command.index("--setting-sources") + 1], "")
        self.assertIn("--strict-mcp-config", command)
        self.assertIn("--no-session-persistence", command)
        self.assertNotIn("--dangerously-skip-permissions", command)
        self.assertNotIn("save_method_draft", command[command.index("--allowedTools") + 1])
        config = json.loads((self.directory / "mcp.json").read_text())
        self.assertEqual(set(config["mcpServers"]), {"lanm"})
        self.assertIn("project_state", config["mcpServers"]["lanm"]["args"])
        job.mode = "build"
        command, _ = self.runtime._command(job, self.directory, messages)
        self.assertIn("save_method_draft", command[command.index("--allowedTools") + 1])
        self.assertIn("--allow-build", json.loads((self.directory / "mcp.json").read_text())["mcpServers"]["lanm"]["args"])
        self.assertIn(job.message, prompt)

    def test_actual_tool_results_distinguish_success_failure_and_unknown(self):
        job, calls = self.job(), {}
        for ident in ("success", "failure", "implicit_success", "unknown"):
            self.runtime._event(job, {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": ident, "name": "mcp__lanm__project_state",
                 "input": {"project_id": self.pid}}]}}, calls)
        self.runtime._event(job, {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "success", "is_error": False,
             "content": [{"type": "text", "text": '{"revision":1}'}]},
            {"type": "tool_result", "tool_use_id": "failure", "is_error": True, "content": "not found"},
            {"type": "tool_result", "tool_use_id": "implicit_success", "content": "result without optional is_error"}]}}, calls)
        self.assertEqual([c["success"] for c in calls.values()], [True, False, True, None])
        self.assertEqual(calls["success"]["result"], {"revision": 1})
        self.assertEqual(calls["failure"]["error"], "not found")
        self.assertEqual(job.metrics["tool_call_count"], 4)

    def test_observed_preflight_usage_includes_cache_in_processed_totals(self):
        for model, output, cached, created, total in (
                ("claude-sonnet-5-5", 833, 10955, 15664, 27456),
                ("claude-opus-5-5", 941, 10962, 15636, 27543)):
            job = self.job()
            self.runtime._event(job, {"type": "result", "subtype": "success", "is_error": False,
                "terminal_reason": "completed", "usage": {"input_tokens": 4, "output_tokens": output,
                    "cache_read_input_tokens": cached, "cache_creation_input_tokens": created}}, {})
            with self.subTest(model=model):
                self.assertEqual(job.metrics["token_usage"]["total_tokens"], total)
                self.assertEqual(job.metrics["token_usage"]["prompt_tokens"], total-output)
                self.assertEqual(job.metrics["token_usage"]["uncached_input_tokens"], 4)

    def test_native_tool_exposure_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "unexpected native tools"):
            self.runtime._event(self.job(), {"type": "system", "subtype": "init", "tools": ["Bash"]}, {})

    def test_failure_result_is_not_a_completed_task(self):
        for event in ({"type": "result", "subtype": "error_max_turns", "is_error": True,
                       "errors": ["turn budget exhausted"]},
                      {"type": "result", "subtype": "success", "is_error": False,
                       "terminal_reason": "aborted_tools"}):
            with self.subTest(event=event), self.assertRaisesRegex(RuntimeError, "Claude turn failed"):
                self.runtime._event(self.job(), event, {})

    def test_stream_saves_answer_usage_identity_and_hides_reasoning(self):
        process = Process(answer())
        with patch.object(self.runtime, "_launch", return_value=process):
            job = self.wait(self.runtime.submit(self.pid, "Read the scenario"))
        self.assertEqual(job.metrics["status"], "completed")
        self.assertEqual(job.text, "Fixture answer.")
        self.assertEqual(job.metrics["reported_model"], "claude-fixture-version")
        self.assertEqual(job.metrics["token_usage"]["total_tokens"], 110)
        self.assertEqual(job.metrics["cost_usd"], .01)
        self.assertIsNone(job.metrics["first_token_seconds"])
        self.assertNotIn("Private reasoning", json.dumps(job.trace))
        self.assertEqual(self.store.messages(self.pid)[-1]["content"], job.text)
        self.assertFalse((self.directory / "runtime_threads.json").exists())

    def test_continuation_uses_saved_history_and_current_state(self):
        first, second = Process(answer("I need the upper bound.")), Process(answer("Recorded."))
        with patch.object(self.runtime, "_launch", side_effect=[first, second]):
            self.wait(self.runtime.submit(self.pid, "Use a minimum volume of 50."))
            self.wait(self.runtime.submit(self.pid, "The upper bound is 80."))
        self.assertIn("I need the upper bound.", second.stdin.saved)
        self.assertIn("Use a minimum volume of 50.", second.stdin.saved)
        self.assertTrue(second.stdin.saved.endswith("CURRENT USER REQUEST:\nThe upper bound is 80."))

    def test_missing_result_and_credentials_do_not_become_success(self):
        with patch.object(self.runtime, "_launch", return_value=Process([])):
            job = self.wait(self.runtime.submit(self.pid, "Fixture"))
        self.assertEqual(job.metrics["status"], "error")
        self.assertIsNone(job.metrics["token_usage"])
        self.assertIsNone(job.metrics["cost_usd"])

    def test_profiles_route_claude_without_api_credentials(self):
        profile = {"id": "claude-fixture", "backend": "claude", "model": "sonnet", "effort": "medium"}
        path = self.directory / "profiles.json"
        path.write_text(json.dumps([profile]))
        self.assertEqual(load_profiles(path), [profile])
        runtime = runtime_factory_for(profile, ["project_state"])(self.store, self.directory)
        self.assertIsInstance(runtime, ClaudeRuntime)
        self.assertEqual(set(runtime._tools("build")), {"project_state"})
        runtime.close()


if __name__ == "__main__":
    unittest.main()
