"""Offline protocol and state-boundary tests; these do not score a model."""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from lanm_platform.compatible_runtime import CompatibleRuntime, _endpoint
from lanm_platform.core import Store


def tool(name, args, identity="call_1"):
    return {"id": identity, "type": "function", "function": {
        "name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}


def completion(content=None, calls=None, reason=None, **extra):
    message = {"role": "assistant", "content": content, **extra}
    if calls is not None:
        message["tool_calls"] = calls
    return {"model": "fixture-server-model", "choices": [{"message": message,
            "finish_reason": reason or ("tool_calls" if calls else "stop")}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}


class FixtureRuntime(CompatibleRuntime):
    def __init__(self, store, directory, responses, **kwargs):
        super().__init__(store, directory, base_url="http://127.0.0.1:1/v1", model="fixture-model", **kwargs)
        self.responses = list(responses)
        self.requests = []

    def _request(self, payload, timeout):
        self.requests.append(copy.deepcopy(payload))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response(payload) if callable(response) else copy.deepcopy(response)


class CompatibleRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.pid = self.store.create_project("Compatible runtime fixture", "Nd", "La")["id"]
        self.runtimes = []

    def tearDown(self):
        for runtime in self.runtimes:
            runtime.close()
            for job in runtime.jobs.values():
                self.wait(job)
        self.temp.cleanup()

    def runtime(self, responses, **kwargs):
        runtime = FixtureRuntime(self.store, self.temp.name, responses, **kwargs)
        self.runtimes.append(runtime)
        return runtime

    def wait(self, job):
        deadline = time.monotonic() + 5
        with job.condition:
            while not job.done and time.monotonic() < deadline:
                job.condition.wait(.05)
        self.assertTrue(job.done, "Fixture turn did not complete")
        return job

    def calls(self, job):
        return [entry for entry in job.trace if entry["type"] == "tool_call"]

    def test_multi_round_dispatch_persistence_timing_and_usage(self):
        runtime = self.runtime([
            completion(calls=[tool("update_assumptions", {"project_id": self.pid,
                "values": {"usable_lifetime_cycles": 45}, "reason": "Explicit fixture scenario change"})]),
            completion(calls=[tool("project_state", {"project_id": self.pid}, "call_2")]),
            completion("The saved lifetime assumption is 45 cycles.")])
        job = self.wait(runtime.submit(self.pid, "Save lifetime as 45 cycles, then verify it."))
        self.assertEqual(job.metrics["status"], "completed")
        self.assertEqual(self.store.get_project(self.pid)["assumptions"]["usable_lifetime_cycles"], 45)
        self.assertEqual([entry["success"] for entry in self.calls(job)], [True, True])
        result = json.loads(runtime.requests[1]["messages"][-1]["content"])
        self.assertEqual(result["assumptions"]["usable_lifetime_cycles"], 45)
        self.assertEqual(job.metrics["token_usage"]["total_tokens"], 36)
        self.assertIsNone(job.metrics["first_token_seconds"])
        self.assertGreaterEqual(job.metrics["total_seconds"], job.metrics["model_seconds"])
        self.assertIsNotNone(job.metrics["first_response_seconds"])
        self.assertEqual(job.metrics["reported_model"], "fixture-server-model")
        self.assertEqual([message["role"] for message in self.store.messages(self.pid)], ["user", "assistant"])
        self.assertEqual(self.store.messages(self.pid)[-1]["content"], job.text)
        self.assertFalse((Path(self.temp.name) / "runtime_threads.json").exists())

    def test_explicit_thinking_budget_and_private_reasoning(self):
        runtime = self.runtime([completion("A visible answer.", reasoning_content="Private working text.")],
                               enable_thinking=True, max_output_tokens=4096)
        job = self.wait(runtime.submit(self.pid, "Explain the current scenario."))
        request = runtime.requests[0]
        self.assertEqual(request["chat_template_kwargs"], {"enable_thinking":True})
        self.assertEqual(request["reasoning_format"], "deepseek")
        self.assertEqual(request["max_tokens"], 4096)
        self.assertEqual(job.metrics["reasoning_characters"], len("Private working text."))
        self.assertNotIn("Private working text.", json.dumps(job.trace))
        self.assertEqual(job.text, "A visible answer.")

    def test_grounding_is_opt_in_and_records_exact_supplied_evidence(self):
        source = self.store.add_source(self.pid, "Grounding zephyrium fixture", "Zephyrium has no measured process yield in this fixture.", "")
        question = "Explain zephyrium from " + source["id"]
        plain = self.runtime([completion("Plain fixture answer.")])
        self.wait(plain.submit(self.pid, question))
        self.assertNotIn("retrieved_reference_material", plain.requests[0]["messages"][0]["content"])
        grounded = self.runtime([completion("Grounded fixture answer.")], domain_grounding=True)
        job = self.wait(grounded.submit(self.pid, question))
        packet = next(entry["packet"] for entry in job.trace if entry["type"] == "grounding")
        excerpt = next(entry for entry in packet["sources"] if entry["id"] == source["id"])
        self.assertIn(excerpt["excerpt"], grounded.requests[0]["messages"][0]["content"])
        self.assertIn("untrusted evidence", grounded.requests[0]["messages"][0]["content"])
        self.assertTrue(job.metrics["domain_grounding"])
        self.assertTrue(excerpt["hash_verified"])

    def test_invalid_arguments_unknown_tools_and_mode_denials_are_returned_to_model(self):
        bad_calls = [tool("project_state", "{bad-json", "bad_json"),
                     tool("project_state", {"project_id": self.pid, "extra": 1}, "extra"),
                     tool("create_testing_batch", {"project_id": self.pid, "count": True}, "bool"),
                     tool("shell", {"command": "whoami"}, "shell"),
                     tool("save_method_draft", {}, "build"),
                     tool("project_state", '{}', "missing"),
                     tool("project_state", '{"project_id":"first","project_id":"second"}', "duplicate")]
        runtime = self.runtime([completion(calls=bad_calls), completion("The proposed calls were rejected.")])
        job = self.wait(runtime.submit(self.pid, "Fixture schema validation"))
        self.assertEqual(job.metrics["status"], "completed")
        self.assertTrue(all(not entry["success"] and entry["error"] for entry in self.calls(job)))
        replies = runtime.requests[1]["messages"][-len(bad_calls):]
        self.assertTrue(all(json.loads(reply["content"])["isError"] for reply in replies))
        self.assertEqual(self.store.list_testing_batches(self.pid), [])

    def test_cross_project_updates_and_unscoped_experiment_acceptance_are_blocked(self):
        other = self.store.create_project("Other fixture", "Nd", "La")["id"]
        experiment = self.store.add_experiment(other, "o-36", "Fixture draft", {
            "target": "Nd", "support": "agarose", "feed": "fixture"}, {"cycles_observed": 1})
        runtime = self.runtime([completion(calls=[
            tool("update_assumptions", {"project_id": other, "values": {"usable_lifetime_cycles": 55}, "reason": "Wrong project"}),
            tool("accept_experiment", {"experiment_id": experiment["id"], "reason": "Wrong project"}, "accept")]),
            completion("Cross-project operations were blocked.")])
        revision = self.store.get_project(other)["revision"]
        job = self.wait(runtime.submit(self.pid, "Validate project isolation"))
        self.assertTrue(all("active project" in entry["error"] for entry in self.calls(job)))
        self.assertEqual(self.store.get_project(other)["revision"], revision)
        self.assertEqual(self.store.get_project(other)["accepted_experiment_count"], 0)

    def test_network_allowlist_is_applied_to_schema_and_dispatch(self):
        runtime = self.runtime([completion(calls=[tool("search_pubmed", {"project_id": self.pid, "query": "fixture"})]),
                                completion("No network tool is enabled.")], tool_allowlist=["project_state"])
        job = self.wait(runtime.submit(self.pid, "Fixture restricted tools"))
        advertised = [item["function"]["name"] for item in runtime.requests[0]["tools"]]
        self.assertEqual(advertised, ["project_state"])
        self.assertFalse(self.calls(job)[0]["success"])

    def test_saved_context_and_bounded_history_are_replayed_without_other_project_data(self):
        ranking = self.store.rank(self.pid, limit=1)
        selection = self.store.save_testing_selection(self.pid, ranking["id"], [ranking["rows"][0]["candidate_id"]], "Chosen fixture")
        batch = self.store.create_testing_batch(self.pid, count=1, selection_id=selection["id"])
        for index in range(12):
            self.store.add_message(self.pid, "assistant" if index % 2 else "user", str(index) + "x" * 7000)
        other = self.store.create_project("Private other fixture", "Nd", "La")["id"]
        self.store.add_message(other, "user", "DO_NOT_REPLAY_OTHER_PROJECT")
        runtime = self.runtime([completion("Fixture reply")])
        self.wait(runtime.submit(self.pid, "Recover my saved testing selection"))
        messages = runtime.requests[0]["messages"]
        self.assertEqual(len(messages), 10)
        self.assertTrue(all(len(message["content"]) <= 6000 for message in messages[1:-1]))
        prompt = messages[0]["content"]
        self.assertIn(selection["id"], prompt)
        self.assertIn(batch["id"], prompt)
        self.assertNotIn("DO_NOT_REPLAY_OTHER_PROJECT", json.dumps(messages))

    def test_cancellation_of_inflight_response_prevents_tool_mutation_and_busy_turns(self):
        entered, release = threading.Event(), threading.Event()
        def delayed(payload):
            entered.set()
            release.wait(3)
            return completion(calls=[tool("update_assumptions", {"project_id": self.pid,
                "values": {"usable_lifetime_cycles": 99}, "reason": "Must never dispatch"})])
        runtime = self.runtime([delayed])
        revision = self.store.get_project(self.pid)["revision"]
        job = runtime.submit(self.pid, "Delayed fixture")
        self.assertTrue(entered.wait(2))
        try:
            with self.assertRaisesRegex(ValueError, "active conversation"):
                runtime.submit(self.pid, "Concurrent fixture")
            self.assertTrue(runtime.cancel(job.id)["cancel_requested"])
        finally:
            release.set()
        self.wait(job)
        self.assertEqual(job.metrics["status"], "cancelled")
        self.assertEqual(self.calls(job), [])
        self.assertEqual(self.store.get_project(self.pid)["revision"], revision)

    def test_cancellation_between_tools_stops_remaining_dispatch(self):
        runtime = self.runtime([completion(calls=[tool("project_state", {"project_id": self.pid}),
            tool("update_assumptions", {"project_id": self.pid, "values": {"usable_lifetime_cycles": 99}, "reason": "Must never dispatch"}, "second")])])
        original = runtime._call_tool
        def cancel_after_first(job, *args):
            result = original(job, *args)
            runtime.cancel(job.id)
            return result
        runtime._call_tool = cancel_after_first
        revision = self.store.get_project(self.pid)["revision"]
        job = self.wait(runtime.submit(self.pid, "Cancel between fixture calls"))
        self.assertEqual(job.metrics["status"], "cancelled")
        self.assertEqual(len(self.calls(job)), 1)
        self.assertEqual(self.store.get_project(self.pid)["revision"], revision)

    def test_round_limit_and_duplicate_ids_prevent_repeat_mutation(self):
        first = completion(calls=[tool("project_state", {"project_id": self.pid})])
        for second, limit, expected in [
            (completion(calls=[tool("project_state", {"project_id": self.pid}, "second")]), 1, "tool-round limit"),
            (first, 3, "reused a tool-call ID")]:
            with self.subTest(expected=expected):
                runtime = self.runtime([first, second], max_tool_rounds=limit)
                job = self.wait(runtime.submit(self.pid, "Bound fixture"))
                self.assertEqual(job.metrics["status"], "error")
                self.assertIn(expected, job.terminal["text"])
                self.assertEqual(len(self.calls(job)), 1)

    def test_malformed_or_truncated_batch_cannot_partially_mutate(self):
        valid = tool("update_assumptions", {"project_id": self.pid, "values": {"usable_lifetime_cycles": 99}, "reason": "Invalid response"})
        for reply in [completion(calls=[valid, {"type": "function"}]), completion(calls=[valid], reason="length")]:
            runtime = self.runtime([reply])
            revision = self.store.get_project(self.pid)["revision"]
            job = self.wait(runtime.submit(self.pid, "Malformed fixture"))
            self.assertEqual(job.metrics["status"], "error")
            self.assertEqual(self.calls(job), [])
            self.assertEqual(self.store.get_project(self.pid)["revision"], revision)

    def test_reasoning_is_replayed_only_transiently_and_never_exported(self):
        reasoning = "private reasoning fixture"
        runtime = self.runtime([completion(calls=[tool("project_state", {"project_id": self.pid})], reasoning_content=reasoning), completion("Final answer")])
        job = self.wait(runtime.submit(self.pid, "Reasoning replay fixture"))
        self.assertEqual(runtime.requests[1]["messages"][-2]["reasoning_content"], reasoning)
        self.assertNotIn(reasoning, json.dumps(job.trace))
        self.assertNotIn(reasoning, json.dumps(self.store.messages(self.pid)))

    def test_missing_usage_is_unknown_and_errors_redact_key(self):
        response = completion("No token usage available")
        response.pop("usage")
        runtime = self.runtime([response, RuntimeError("Failure with fixture-secret-value")], api_key_env="LANM_TEST_ONLY_KEY")
        with patch.dict(os.environ, {"LANM_TEST_ONLY_KEY": "fixture-secret-value"}):
            job = self.wait(runtime.submit(self.pid, "Unknown usage"))
            self.assertFalse(job.metrics["token_usage_complete"])
            self.assertTrue(all(value is None for value in job.metrics["token_usage"].values()))
            failed = self.wait(runtime.submit(self.pid, "Redacted error"))
        self.assertNotIn("fixture-secret-value", json.dumps(failed.trace) + failed.terminal["text"])
        self.assertEqual(failed.metrics["status"], "error")
        self.assertFalse(failed.metrics["token_usage_complete"])
        self.assertTrue(all(value is None for value in failed.metrics["token_usage"].values()))

    def test_url_validation_and_mode_tools(self):
        for value in ["http://example.com/v1", "https://user:secret@example.com/v1", "https://example.com/v1?key=x", "file:///test", "https://example.com/#fragment"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                _endpoint(value)
        self.assertEqual(_endpoint("http://[::1]:1234/v1/"), "http://[::1]:1234/v1/chat/completions")
        self.assertEqual(_endpoint("https://example.com/v1/chat/completions"), "https://example.com/v1/chat/completions")
        runtime = self.runtime([])
        self.assertNotIn("save_method_draft", runtime._tools("research"))
        self.assertIn("save_method_draft", runtime._tools("build"))
        self.assertNotIn("create_project", runtime._tools("build"))

    def test_real_http_transport_json_auth_and_redirect_rejection(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append((self.path, self.headers.get("Authorization"), payload))
                if len(received) == 1:
                    body = json.dumps(completion("HTTP fixture answer")).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(307)
                    self.send_header("Location", "/must-not-follow")
                    self.end_headers()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            runtime = CompatibleRuntime(self.store, self.temp.name,
                base_url=f"http://127.0.0.1:{server.server_port}/v1", model="fixture", api_key_env="LANM_TEST_ONLY_KEY")
            self.runtimes.append(runtime)
            with patch.dict(os.environ, {"LANM_TEST_ONLY_KEY": "fixture-http-key"}):
                success = self.wait(runtime.submit(self.pid, "HTTP fixture"))
                failed = self.wait(runtime.submit(self.pid, "Redirect fixture"))
            self.assertEqual(success.text, "HTTP fixture answer")
            self.assertEqual(received[0][0], "/v1/chat/completions")
            self.assertEqual(received[0][1], "Bearer fixture-http-key")
            self.assertFalse(received[0][2]["stream"])
            self.assertEqual(len(received), 2)
            self.assertIn("redirects are disabled", failed.terminal["text"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == "__main__":
    unittest.main()
