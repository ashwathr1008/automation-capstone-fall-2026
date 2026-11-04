"""Conversational handoff tools and local CSV downloads with isolated test data."""
import csv
import http.client
import io
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from lanm_platform.core import Store
from lanm_platform.mcp import definitions, dispatch
from lanm_platform.methods import Registry
from lanm_platform.server import Application, handler_for


# Software fixtures within the requested MVP stock-volume range.
STOCK_VOLUMES = {"stock_volume_min_ul": 40.0, "stock_volume_max_ul": 90.0, "seed": 718}


class ConversationalHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.registry = Registry(self.temp.name)
        self.pid = self.store.create_project("Handoff fixture", "Nd", "La")["id"]

    def tearDown(self):
        self.temp.cleanup()

    def call(self, name, **arguments):
        return dispatch(self.store, self.registry, name, {"project_id": self.pid, **arguments})

    def test_scenario_selection_survives_restart_and_exports_exact_ids(self):
        before = self.store.get_project(self.pid)
        initial = self.call("prioritize_candidates", pool="untested", limit=8)
        first = initial["rows"][0]["candidate_id"]
        scenario = self.call(
            "prioritize_candidates", pool="untested", limit=8,
            assumption_overrides={"usable_lifetime_cycles": 80},
            exclude_candidate_ids=[first],
            scenario_reason="Hypothetical comparison; defer the first candidate for this batch.",
        )
        self.assertNotIn(first, [row["candidate_id"] for row in scenario["rows"]])
        self.assertEqual(scenario["assumptions"]["usable_lifetime_cycles"], 80)
        chosen = [scenario["rows"][2]["candidate_id"], scenario["rows"][0]["candidate_id"]]
        selection = self.call("save_testing_selection", ranking_run_id=scenario["id"], candidate_ids=chosen,
                              reason="User chose this order after reviewing the hypothetical shortlist.")
        self.store = Store(self.temp.name)
        self.assertEqual(self.call("get_testing_selection", selection_id=selection["id"])["candidate_ids"], chosen)
        self.assertIn(selection["id"], [item["id"] for item in self.call("list_testing_selections")])
        batch = self.call("create_testing_batch", count=2, selection_id=selection["id"], **STOCK_VOLUMES)
        self.assertEqual([row["candidate_id"] for row in batch["rows"]], chosen)
        self.assertEqual([row["well"] for row in batch["rows"]], ["A1", "B1"])
        self.assertEqual([row["rank"] for row in batch["rows"]], [1, 2])
        self.assertEqual([row["recommendation_rank"] for row in batch["rows"]], [3, 1])
        self.assertEqual(batch["volume_location"], "starting_well")
        self.assertTrue(batch["is_hypothetical"])
        self.assertEqual(batch["scenario"], scenario["scenario"])
        self.assertEqual(self.call("get_run", run_id=scenario["id"])["id"], scenario["id"])
        self.assertEqual(self.call("get_testing_batch", batch_id=batch["id"])["rows"], batch["rows"])
        self.assertIn(batch["id"], [item["id"] for item in self.call("list_testing_batches")])
        for row in batch["rows"]:
            self.assertEqual(row["volume_basis"], "simulated")
            self.assertEqual(row["volume_unit"], "uL")
            self.assertGreaterEqual(row["stock_volume"], 40)
            self.assertLessEqual(row["stock_volume"], 90)
            self.assertEqual(row["water_addition_mode"], "constant_per_starting_well")
        records = list(csv.DictReader(io.StringIO(self.store.testing_batch_csv(self.pid, batch["id"]))))
        self.assertEqual([row["candidate_id"] for row in records], chosen)
        self.assertEqual([row["recommendation_rank"] for row in records], ["3", "1"])
        after = self.store.get_project(self.pid)
        for key in ("revision", "assumptions", "configuration", "accepted_experiment_count"):
            self.assertEqual(after[key], before[key], key)

    def test_tools_expose_bounded_count_and_separate_persisted_selection(self):
        tools = {item["name"]: item for item in definitions()}
        expected = {"save_testing_selection", "list_testing_selections", "get_testing_selection",
                    "create_testing_batch", "list_testing_batches", "get_testing_batch", "get_run"}
        self.assertTrue(expected <= tools.keys())
        count = tools["create_testing_batch"]["inputSchema"]["properties"]["count"]
        self.assertEqual((count["type"], count["minimum"], count["maximum"]), ("integer", 1, 8))
        properties = tools["create_testing_batch"]["inputSchema"]["properties"]
        self.assertNotIn("concentration_unit", properties)
        self.assertNotIn("concentration_min", properties)
        for field in ("stock_volume_min_ul", "stock_volume_max_ul"):
            self.assertEqual((properties[field]["minimum"], properties[field]["maximum"]), (35, 250))
        self.assertIn("count", tools["create_testing_batch"]["inputSchema"]["required"])
        self.assertTrue(tools["get_testing_batch"]["annotations"]["readOnlyHint"])
        self.assertFalse(tools["create_testing_batch"]["annotations"]["readOnlyHint"])

    def test_prompt_with_only_count_uses_whole_number_demo_defaults(self):
        batch = self.call("create_testing_batch", count=3)
        self.assertEqual(len(batch["rows"]), 3)
        for row in batch["rows"]:
            value = row["stock_volume"]
            self.assertEqual(value, int(value))
            self.assertGreaterEqual(value, 35)
            self.assertLessEqual(value, 250)
            self.assertEqual(row["volume_unit"], "uL")
            self.assertEqual(row["volume_basis"], "simulated")
            self.assertEqual(row["water_addition_mode"], "constant_per_starting_well")
        self.assertIsNone(batch["water_addition"]["volume_ul"])


class HandoffHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(self.temp.name)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.pid = self.app.store.list_projects()[0]["id"]
        self.base = f"/api/projects/{self.pid}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.app.close()
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        connection.request(method, path, body=json.dumps(body) if body is not None else None,
                           headers={"Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse()
        result = (response.status, dict(response.getheaders()), response.read())
        connection.close()
        return result

    def json_request(self, method, path, body=None):
        status, _, raw = self.request(method, path, body)
        return status, json.loads(raw)

    def test_download_is_exact_stable_csv_even_after_project_changes(self):
        before = self.app.store.get_project(self.pid)
        status, batch = self.json_request("POST", self.base + "/testing-batches", {"count": 8, **STOCK_VOLUMES})
        self.assertEqual(status, 201, batch)
        download = batch["download_url"]
        self.assertEqual(download, f"{self.base}/testing-batches/{batch['id']}/csv")
        status, headers, original = self.request("GET", download)
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/csv"))
        self.assertTrue(headers["Content-Disposition"].startswith("attachment;"))
        rows = list(csv.DictReader(io.StringIO(original.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 8)
        self.assertEqual([row["well"] for row in rows], [letter + "1" for letter in "ABCDEFGH"])
        self.assertEqual([row["candidate_id"] for row in rows], [row["candidate_id"] for row in batch["rows"]])
        self.assertEqual(len({row["candidate_id"] for row in rows}), 8)
        for row, saved in zip(rows, batch["rows"]):
            self.assertEqual(float(row["stock_volume"]), saved["stock_volume"])
            self.assertEqual(row["schema_version"], "lanm_testing_batch_2")
            self.assertEqual(row["volume_unit"], "uL")
            self.assertEqual(row["volume_basis"], "simulated")
            self.assertEqual(row["volume_location"], "starting_well")
            self.assertEqual(row["water_addition_mode"], "constant_per_starting_well")
        self.assertEqual(self.request("GET", download)[2], original)
        status, listed = self.json_request("GET", self.base + "/testing-batches")
        self.assertEqual(status, 200)
        self.assertIn(batch["id"], [item["id"] for item in listed["batches"]])
        status, detail = self.json_request("GET", f"{self.base}/testing-batches/{batch['id']}")
        self.assertEqual((status, detail["rows"]), (200, batch["rows"]))
        after = self.app.store.get_project(self.pid)
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(after["accepted_experiment_count"], before["accepted_experiment_count"])
        self.app.store.update_assumptions(self.pid, {"usable_lifetime_cycles": 77}, "Later project update")
        self.assertEqual(self.request("GET", download)[2], original)

    def test_http_selection_and_hypothetical_rank_feed_the_batch(self):
        status, ranked = self.json_request("POST", self.base + "/rank", {"limit": 8, "pool": "untested"})
        self.assertEqual(status, 200)
        excluded = ranked["rows"][0]["candidate_id"]
        status, scenario = self.json_request("POST", self.base + "/rank", {
            "limit": 8, "pool": "untested", "exclude_candidate_ids": [excluded],
            "scenario_reason": "User deferred this candidate in the conversation.",
        })
        self.assertEqual(status, 200, scenario)
        self.assertNotIn(excluded, [row["candidate_id"] for row in scenario["rows"]])
        chosen = [scenario["rows"][1]["candidate_id"], scenario["rows"][0]["candidate_id"]]
        status, selection = self.json_request("POST", self.base + "/testing-selections", {
            "ranking_run_id": scenario["id"], "candidate_ids": chosen,
            "reason": "Explicit order chosen during discussion.",
        })
        self.assertEqual(status, 201, selection)
        status, listed = self.json_request("GET", self.base + "/testing-selections")
        self.assertEqual(status, 200)
        self.assertIn(selection["id"], [item["id"] for item in listed["selections"]])
        status, detail = self.json_request("GET", f"{self.base}/testing-selections/{selection['id']}")
        self.assertEqual((status, detail["id"]), (200, selection["id"]))
        status, batch = self.json_request("POST", self.base + "/testing-batches", {
            "count": 2, "selection_id": selection["id"], **STOCK_VOLUMES,
        })
        self.assertEqual(status, 201, batch)
        self.assertEqual([row["candidate_id"] for row in batch["rows"]], chosen)
        self.assertTrue(batch["is_hypothetical"])

    def test_invalid_counts_and_cross_project_download_cannot_create_or_leak_batch(self):
        for count in (0, 9, -1, True, 1.5, "2"):
            with self.subTest(count=count):
                status, result = self.json_request("POST", self.base + "/testing-batches", {"count": count, **STOCK_VOLUMES})
                self.assertEqual(status, 400, result)
        self.assertEqual(self.app.store.list_testing_batches(self.pid), [])
        status, batch = self.json_request("POST", self.base + "/testing-batches", {"count": 1, **STOCK_VOLUMES})
        self.assertEqual(status, 201, batch)
        other = self.app.store.create_project("Separate project", "Nd", "La")["id"]
        for suffix in ("", "/csv"):
            status, _, raw = self.request("GET", f"/api/projects/{other}/testing-batches/{batch['id']}" + suffix)
            self.assertEqual(status, 400)
            self.assertIn("error", json.loads(raw))
        status, _, _ = self.request("GET", batch["download_url"], headers={"Origin": "https://unrelated.example"})
        self.assertEqual(status, 403)

    def test_stale_selection_needs_explicit_override_for_a_new_batch(self):
        ranked = self.app.store.rank(self.pid, limit=2)
        selected = self.app.store.save_testing_selection(
            self.pid, ranked["id"], [row["candidate_id"] for row in ranked["rows"]], "Saved choice before revision")
        self.app.store.update_assumptions(self.pid, {"usable_lifetime_cycles": 75}, "Later committed assumption")
        args = {"selection_id": selected["id"], "count": 2, **STOCK_VOLUMES}
        status, result = self.json_request("POST", self.base + "/testing-batches", args)
        self.assertEqual(status, 400, result)
        self.assertEqual(self.app.store.list_testing_batches(self.pid), [])
        status, batch = self.json_request("POST", self.base + "/testing-batches", {**args, "allow_stale": True})
        self.assertEqual(status, 201, batch)
        self.assertEqual([row["candidate_id"] for row in batch["rows"]], selected["candidate_ids"])

    def test_partial_or_out_of_range_stock_volume_configuration_is_rejected(self):
        for values in ({"stock_volume_min_ul": 35}, {"stock_volume_max_ul": 250},
                       {"stock_volume_min_ul": 34, "stock_volume_max_ul": 250},
                       {"stock_volume_min_ul": 35, "stock_volume_max_ul": 251}):
            with self.subTest(values=values):
                status, result = self.json_request("POST", self.base + "/testing-batches", {"count": 1, **values})
                self.assertEqual(status, 400, result)
        self.assertEqual(self.app.store.list_testing_batches(self.pid), [])

    def test_old_concentration_parameters_are_rejected_instead_of_relabelled(self):
        for values in ({"concentration_min": 2}, {"concentration_unit": "uL"},
                       {"concentration_min": 1, "concentration_max": 10, "concentration_unit": "uM"}):
            with self.subTest(values=values):
                status, result = self.json_request("POST", self.base + "/testing-batches", {"count": 1, **values})
                self.assertEqual(status, 400, result)
        self.assertEqual(self.app.store.list_testing_batches(self.pid), [])


if __name__ == "__main__":
    unittest.main()
