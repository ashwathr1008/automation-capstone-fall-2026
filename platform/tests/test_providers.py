"""Profile configuration, routing and observability without model requests."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lanm_platform.providers import ProfileRuntime, load_profiles
from lanm_platform.runtime import Job, Rpc


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.resets = []
    def submit(self, project_id, message, mode, model):
        self.calls.append(model)
        return Job(project_id, message, mode, model)
    def cancel(self, ident):
        return {"cancelled": ident}
    def status(self):
        return {"connected": False}
    def reset_thread(self, project_id, mode):
        self.resets.append((project_id, mode))
    def close(self):
        pass


class ProviderTests(unittest.TestCase):
    def test_config_rejects_duplicate_ids_and_inline_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            profile = {"id":"local", "backend":"compatible", "model":"fixture", "base_url":"http://127.0.0.1:18080/v1"}
            for payload in [[profile, profile], [{**profile, "api_key":"do-not-store"}]]:
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_profiles(path)
            path.write_text(json.dumps([profile]), encoding="utf-8")
            self.assertEqual(load_profiles(path), [profile])
            path.write_text(json.dumps([{"id":"codex", "backend":"codex", "model":"fixture", "domain_grounding":True}]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "require a compatible backend"):
                load_profiles(path)

    def test_router_enforces_busy_across_backends_and_selects_exact_model(self):
        profiles = [{"id":"teacher", "backend":"codex", "model":"teacher-model"},
                    {"id":"student", "backend":"compatible", "model":"student-model", "base_url":"http://localhost:18080/v1"}]
        backends = []
        def factory(profile):
            backend = FakeBackend()
            backends.append(backend)
            return lambda store, directory: backend
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"LANM_DEFAULT_PROFILE":"teacher"}), \
                patch("lanm_platform.providers.runtime_factory_for", side_effect=factory):
            router = ProfileRuntime(None, directory, profiles)
            first = router.submit("p1", "hello")
            with self.assertRaisesRegex(ValueError, "active conversation"):
                router.submit("p1", "hello", model="student")
            first.done = True
            second = router.submit("p1", "hello", model="student")
            self.assertEqual(second.model, "student-model")
            self.assertEqual(router.cancel(second.id), {"cancelled":second.id})
            self.assertEqual(len(backends), 2)
            with self.assertRaisesRegex(ValueError, "configured model"):
                router.submit("p2", "hello", model="unconfigured")

    def test_codex_trace_records_tool_outcomes_and_excludes_reasoning(self):
        with tempfile.TemporaryDirectory() as directory:
            rpc = Rpc(directory, "research")
            job = Job("p", "question", "research", "fixture")
            rpc.jobs["thread"] = job
            rpc._event("item/completed", {"threadId":"thread", "item":{
                "type":"reasoning", "content":"private reasoning"}})
            rpc._event("item/completed", {"threadId":"thread", "item":{
                "type":"mcpToolCall", "id":"call", "tool":"read_source", "arguments":{"source_id":"s"},
                "result":{"isError":True,"content":[{"type":"text","text":"not found"}]}}})
            self.assertEqual(len(job.trace), 1)
            self.assertFalse(job.trace[0]["success"])
            self.assertEqual(job.metrics["tool_call_count"], 1)
            self.assertNotIn("private reasoning", json.dumps(job.trace))

    def test_compatible_turn_invalidates_both_codex_modes_across_restart(self):
        profiles = [{"id":"teacher", "backend":"codex", "model":"teacher-model"},
                    {"id":"student", "backend":"compatible", "model":"student-model", "base_url":"http://localhost:18080/v1"}]
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"LANM_DEFAULT_PROFILE":"teacher"}), \
                patch("lanm_platform.providers.runtime_factory_for", side_effect=lambda p: lambda s,d: FakeBackend()):
            first = ProfileRuntime(None, directory, profiles)
            first.submit("p", "hello", mode="build", model="student").done = True
            restarted = ProfileRuntime(None, directory, profiles)
            restarted.submit("p", "continue", mode="research", model="teacher").done = True
            restarted.submit("p", "continue", mode="build", model="teacher").done = True
            self.assertEqual(restarted.backends["codex"].resets, [("p", "research"), ("p", "build")])


if __name__ == "__main__":
    unittest.main()
