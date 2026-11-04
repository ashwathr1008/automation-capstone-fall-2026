"""Check handoff recovery context without starting Codex or requesting a model."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lanm_platform.core import Store
from lanm_platform.runtime import Job, Runtime


class FinishedTurnRpc:
    """Capture actual Runtime requests and finish at the first turn/start."""
    def __init__(self, work, fail_resume=False):
        self.work = Path(work)
        self.fail_resume = fail_resume
        self.jobs = {}
        self.calls = []

    def start(self):
        pass

    def request(self, method, params, timeout=None):
        self.calls.append((method, params))
        if method == "thread/resume":
            if self.fail_resume:
                raise RuntimeError("Fixture native thread expired")
            return {"thread": {"id": params["threadId"]}}
        if method == "thread/start":
            return {"thread": {"id": "fresh-fixture-thread"}}
        if method == "turn/start":
            self.jobs[params["threadId"]].finish("done", status="completed")
            return {"turn": {"id": "finished-fixture-turn"}}
        raise AssertionError("Unexpected runtime request: " + method)

    def close(self):
        pass


class HandoffRuntimeContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.pid = self.store.create_project("Handoff context fixture", "Nd", "La")["id"]
        ranking = self.store.rank(self.pid, limit=2)
        self.chosen = [row["candidate_id"] for row in reversed(ranking["rows"])]
        self.selection = self.store.save_testing_selection(self.pid, ranking["id"], self.chosen,
                                                           "User chose this order in the conversation.")
        self.batch = self.store.create_testing_batch(self.pid, count=1, selection_id=self.selection["id"])
        other = self.store.create_project("Other project", "Nd", "La")["id"]
        self.other_batch = self.store.create_testing_batch(other, count=1)
        self.store.add_message(self.pid, "user", "Keep this chosen shortlist for later.")
        self.store.add_message(self.pid, "assistant", "The ordered shortlist has been saved.")
        self.message = "Export those candidates."
        self.store.add_message(self.pid, "user", self.message)

    def tearDown(self):
        self.temp.cleanup()

    def run_context(self, *, existing_thread=False, fail_resume=False):
        runtime = Runtime(self.store, self.temp.name)
        if existing_thread:
            runtime.threads[self.pid + ":research"] = "saved-fixture-thread"
        fake = FinishedTurnRpc(self.temp.name, fail_resume=fail_resume)
        job = Job(self.pid, self.message, "research", "fixture-model-never-requested")
        with patch("lanm_platform.runtime.Rpc", return_value=fake):
            runtime._run(job, self.store.get_project(self.pid))
        self.assertTrue(job.done)
        self.assertEqual(job.terminal["type"], "done", job.terminal)
        calls = [params for method, params in fake.calls if method == "turn/start"]
        self.assertEqual(len(calls), 1)
        prompt = calls[0]["input"][0]["text"]
        state_text = prompt.split("CURRENT VERIFIED APPLICATION STATE:\n", 1)[1].split("\n\nUSER MESSAGE:\n", 1)[0]
        context = json.loads(state_text)
        self.assertEqual(context["active_project_id"], self.pid)
        selection = context["recent_testing_selections"][0]
        self.assertEqual(selection["id"], self.selection["id"])
        self.assertEqual(selection["candidate_ids"], self.chosen)
        self.assertEqual(selection["ranking_run_id"], self.selection["ranking_run_id"])
        batch = context["recent_testing_batches"][0]
        self.assertEqual(batch["id"], self.batch["id"])
        self.assertEqual(batch["selection_id"], self.selection["id"])
        self.assertEqual(batch["count"], 1)
        self.assertEqual(batch["schema_version"], "lanm_testing_batch_2")
        self.assertEqual(batch["generation"]["quantity"], "stock_volume")
        self.assertEqual(batch["generation"]["unit"], "uL")
        self.assertEqual(batch["download_url"], self.batch["download_url"])
        self.assertNotIn(self.other_batch["id"], prompt)
        self.assertTrue(prompt.endswith(self.message))
        return context, fake.calls

    def test_new_thread_receives_saved_selection_batch_and_recent_conversation(self):
        context, calls = self.run_context()
        self.assertIn("thread/start", [method for method, _ in calls])
        self.assertNotIn("thread/resume", [method for method, _ in calls])
        self.assertEqual(context["recent_conversation"][0]["content"], "Keep this chosen shortlist for later.")
        self.assertEqual(len(context["recent_conversation"]), 2)

    def test_resumed_thread_receives_current_saved_ids_and_staleness(self):
        self.store.update_assumptions(self.pid, {"usable_lifetime_cycles": 70}, "Later committed change")
        context, calls = self.run_context(existing_thread=True)
        self.assertIn("thread/resume", [method for method, _ in calls])
        self.assertNotIn("thread/start", [method for method, _ in calls])
        self.assertNotIn("recent_conversation", context)
        self.assertTrue(context["recent_testing_selections"][0]["stale"])
        self.assertTrue(context["recent_testing_batches"][0]["stale"])
        self.assertEqual(context["project"]["assumptions"]["usable_lifetime_cycles"], 70)

    def test_expired_thread_fallback_retains_saved_selection_and_batch_context(self):
        context, calls = self.run_context(existing_thread=True, fail_resume=True)
        methods = [method for method, _ in calls]
        self.assertEqual(methods, ["thread/resume", "thread/start", "turn/start"])
        self.assertIn("recent_conversation", context)
        saved_threads = json.loads((Path(self.temp.name) / "runtime_threads.json").read_text(encoding="utf-8"))
        self.assertEqual(saved_threads[self.pid + ":research"], "fresh-fixture-thread")


if __name__ == "__main__":
    unittest.main()
