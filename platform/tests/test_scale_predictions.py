"""Scale predictions remain explicit scenarios, isolated from accepted results."""
from copy import deepcopy
import http.client
from http.server import ThreadingHTTPServer
import json
import tempfile
import threading
import unittest

from lanm_platform.core import Store
from lanm_platform.mcp import definitions, dispatch
from lanm_platform.server import Application, handler_for


def predicted_values(**changes):
    return {
        "collected_target_kg_per_l_cycle": 0.0005,
        "cycle_time_hours": 8,
        "usable_lifetime_cycles": 80,
        "target_production_kg_per_day": 0.3,
        "equipment_cost_usd": 30000,
        "labor_hours_per_day": 2,
        "labor_rate_usd_per_hour": 40,
        **changes,
    }


class ScalePredictionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.pid = self.store.create_project("Prediction fixture", "Nd", "La")["id"]

    def tearDown(self):
        self.temp.cleanup()

    def arguments(self, **changes):
        return {
            "project_id": self.pid,
            "label": "Fictional 200 L prediction",
            "intended_bed_volume_l": 200,
            "scale_description": "200 L total packed material; unspecified column arrangement",
            "basis": "Synthetic test forecast, not an experimental result",
            "values": predicted_values(),
            "candidate_id": "o-36",
            "source_url": "https://example.org/prediction-fixture",
            **changes,
        }

    def add(self, **changes):
        return self.store.add_scale_prediction(**self.arguments(**changes))

    def test_prediction_and_calculation_do_not_change_revisions_or_experiment_pools(self):
        before = self.store.get_project(self.pid)
        prediction = self.add()
        self.assertEqual(prediction["evidence_kind"], "user_supplied_prediction")
        self.assertEqual(prediction["status"], "prediction_not_measurement")
        result = self.store.calculate_scale_prediction(self.pid, prediction["id"])
        after = self.store.get_project(self.pid)
        for field in ("revision", "assumptions", "revisions", "experiment_count", "accepted_experiment_count"):
            self.assertEqual(before[field], after[field], field)
        self.assertEqual(self.store.list_candidates(self.pid, pool="updated")["total"], 0)
        self.assertEqual(self.store.list_candidates(self.pid, pool="untested")["total"], 616)
        self.assertEqual(result["kind"], "scale_prediction_calculation")
        self.assertEqual(result["candidate_id"], "o-36")
        self.assertEqual(result["prediction"]["id"], prediction["id"])
        self.assertEqual(result["prediction"]["basis"], prediction["basis"])
        self.assertEqual(result["evidence_kind"], "user_supplied_prediction")
        self.assertAlmostEqual(result["summary"]["required_bed_volume_l"], 200)
        self.assertEqual(self.store.list_runs(self.pid)[0]["id"], result["id"])

    def test_snapshot_survives_later_project_revisions_and_restart(self):
        prediction = self.add()
        saved_copy = deepcopy(prediction)
        original = self.store.calculate_scale_prediction(self.pid, prediction["id"])
        prediction["label"] = "Caller-mutated label"
        prediction["inputs"]["usable_lifetime_cycles"] = 1
        self.store.update_assumptions(self.pid, {
            "prepared_material_cost_usd_per_l": 999,
            "operating_days_per_year": 200,
            "regeneration_cost_usd_per_l_cycle": 10,
        }, "Change a later project scenario")
        restarted = Store(self.temp.name)
        self.assertEqual(restarted.get_scale_prediction(self.pid, saved_copy["id"]), saved_copy)
        replay = restarted.calculate_scale_prediction(self.pid, saved_copy["id"])
        self.assertEqual(replay["assumptions"], original["assumptions"])
        self.assertEqual(replay["summary"], original["summary"])
        self.assertEqual(replay["assumptions"]["prepared_material_cost_usd_per_l"], 100)
        self.assertEqual(replay["assumptions"]["operating_days_per_year"], 330)

    def test_predictions_are_project_scoped(self):
        prediction = self.add()
        other = self.store.create_project("Another project", "Nd", "Dy")["id"]
        self.assertEqual(self.store.list_scale_predictions(other), [])
        for operation in (self.store.get_scale_prediction, self.store.calculate_scale_prediction):
            with self.assertRaises((ValueError, KeyError)):
                operation(other, prediction["id"])
        self.assertEqual(self.store.list_runs(other), [])

    def test_explicit_forecast_excludes_candidate_overrides_and_accepted_measurements(self):
        conditions = {"target": "Nd", "support": "agarose", "feed": "defined nitrate mixture"}
        self.store.update_project(self.pid, {"configuration": conditions}, "Define fixture conditions")
        self.store.update_assumptions(self.pid, {
            "product_purity_fraction": .99, "target_recovery_fraction": .95,
            "feed_target_kg_per_l": .1, "feed_volume_l_per_l_cycle": 1,
        }, "Shared values do not establish a larger process")
        self.store.update_assumptions(self.pid, {
            "prepared_material_cost_usd_per_l": 999, "collected_target_kg_per_l_cycle": .02,
        }, "Candidate-specific scenario", "o-36")
        experiment = self.store.add_experiment(self.pid, "o-36", "Fictional small-column result", conditions,
            {"collected_target_kg_per_l_cycle": .03, "purity_fraction": .98,
             "recovery_fraction": .9, "cycle_time_hours": 2, "cycles_observed": 4},
            "Only a test fixture")
        self.store.accept_experiment(experiment["id"], "Accept fixture in temporary store")
        before = self.store.get_project(self.pid)
        prediction = self.add()
        result = self.store.calculate_scale_prediction(self.pid, prediction["id"])
        self.assertEqual(result["assumptions"]["collected_target_kg_per_l_cycle"], .0005)
        self.assertEqual(result["assumptions"]["cycle_time_hours"], 8)
        self.assertEqual(result["assumptions"]["prepared_material_cost_usd_per_l"], 100)
        for key in ("product_purity_fraction", "target_recovery_fraction", "feed_target_kg_per_l", "feed_volume_l_per_l_cycle"):
            self.assertNotIn(key, result["assumptions"])
        self.assertTrue(all(check["status"] == "unknown" for check in result["specification_checks"]))
        self.assertFalse(any(row["evidence_kind"] == "accepted_experimental_measurement" for row in result["input_details"]))
        supplied_details = {row["parameter"]: row for row in result["input_details"]}
        for key in predicted_values():
            self.assertEqual(supplied_details[key]["evidence_kind"], "user_supplied_prediction")
        after = self.store.get_project(self.pid)
        self.assertEqual(before["revision"], after["revision"])
        self.assertEqual(before["accepted_experiment_count"], after["accepted_experiment_count"])

    def test_optional_performance_only_enters_when_explicitly_supplied(self):
        prediction = self.add(values=predicted_values(product_purity_fraction=.94, target_recovery_fraction=.85))
        result = self.store.calculate_scale_prediction(self.pid, prediction["id"])
        self.assertEqual(result["assumptions"]["product_purity_fraction"], .94)
        self.assertEqual(result["assumptions"]["target_recovery_fraction"], .85)
        self.assertTrue(all(check["status"] == "meets" for check in result["specification_checks"]))
        self.assertAlmostEqual(result["summary"]["required_bed_volume_l"], 200)

    def test_equipment_and_labor_are_forecast_inputs_in_the_calculation(self):
        base = self.add()
        costlier = self.add(values=predicted_values(equipment_cost_usd=60000, labor_hours_per_day=4))
        low = self.store.calculate_scale_prediction(self.pid, base["id"])
        high = self.store.calculate_scale_prediction(self.pid, costlier["id"])
        low_parts = {row["name"]: row["annual_cost_usd"] for row in low["cost_breakdown"]}
        high_parts = {row["name"]: row["annual_cost_usd"] for row in high["cost_breakdown"]}
        for key in ("Annualized equipment", "Maintenance", "Labor"):
            self.assertAlmostEqual(high_parts[key], 2 * low_parts[key])
        self.assertEqual(low_parts["Material replacement"], high_parts["Material replacement"])
        self.assertGreater(high["summary"]["cost_usd_per_kg"], low["summary"]["cost_usd_per_kg"])

    def test_volume_check_reports_inconsistent_output_without_rewriting_predictions(self):
        consistent = self.add()
        consistent_result = self.store.calculate_scale_prediction(self.pid, consistent["id"])
        self.assertEqual(consistent_result["scale_check"]["status"], "consistent")
        # 0.5 g/L/cycle at three cycles/day needs 300 L to collect 450 g/day.
        mismatch = self.add(values=predicted_values(target_production_kg_per_day=.45))
        result = self.store.calculate_scale_prediction(self.pid, mismatch["id"])
        check = result["scale_check"]
        self.assertEqual(check["status"], "mismatch")
        self.assertEqual(check["intended_bed_volume_l"], 200)
        self.assertAlmostEqual(check["calculated_required_bed_volume_l"], 300)
        self.assertAlmostEqual(check["implied_output_kg_per_day_at_intended_volume"], .3)
        self.assertTrue(any("5%" in warning for warning in result["uncertainties"]))
        self.assertEqual(self.store.get_scale_prediction(self.pid, mismatch["id"]), mismatch)

    def test_explicit_impossible_feed_balance_is_rejected_before_saving(self):
        with self.assertRaisesRegex(ValueError, "mass balance"):
            self.add(values=predicted_values(feed_target_kg_per_l=.0001,
                                            feed_volume_l_per_l_cycle=1,
                                            target_recovery_fraction=.8))
        self.assertEqual(self.store.list_scale_predictions(self.pid), [])

    def test_missing_required_values_and_invalid_numeric_values_leave_no_prediction(self):
        for key in predicted_values():
            values = predicted_values()
            del values[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.add(values=values)
        for values in (predicted_values(cycle_time_hours=0), predicted_values(usable_lifetime_cycles=-1),
                       predicted_values(equipment_cost_usd=float("nan")), predicted_values(labor_hours_per_day=True),
                       predicted_values(target_production_kg_per_day=float("inf")), {"unexpected": 1}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.add(values=values)
        self.assertEqual(self.store.list_scale_predictions(self.pid), [])

    def test_bad_scale_metadata_identifiers_and_urls_are_rejected(self):
        invalid = [
            {"intended_bed_volume_l": 0}, {"intended_bed_volume_l": float("nan")},
            {"intended_bed_volume_l": True}, {"label": ""}, {"basis": ""},
            {"scale_description": ""}, {"candidate_id": "not-a-candidate"},
            {"source_url": "javascript:alert(1)"}, {"source_url": "https://"},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.add(**changes)
        self.assertEqual(self.store.list_scale_predictions(self.pid), [])

    def test_both_mcp_modes_use_the_same_durable_forecast_tools(self):
        for build in (False, True):
            tools = {tool["name"]: tool for tool in definitions(build)}
            for name in ("add_scale_prediction", "calculate_scale_prediction"):
                self.assertFalse(tools[name]["annotations"]["readOnlyHint"])
            for name in ("list_scale_predictions", "get_scale_prediction"):
                self.assertTrue(tools[name]["annotations"]["readOnlyHint"])
            prediction = dispatch(self.store, None, "add_scale_prediction", self.arguments(candidate_id=None), build)
            listing = dispatch(self.store, None, "list_scale_predictions", {"project_id": self.pid}, build)
            self.assertIn(prediction["id"], [row["id"] for row in listing])
            arguments = {"project_id": self.pid, "prediction_id": prediction["id"]}
            self.assertEqual(dispatch(self.store, None, "get_scale_prediction", arguments, build), prediction)
            result = dispatch(self.store, None, "calculate_scale_prediction", arguments, build)
            self.assertEqual(result["kind"], "scale_prediction_calculation")
            self.assertAlmostEqual(result["summary"]["required_bed_volume_l"], 200)

    def test_http_create_read_calculate_and_reject_cross_project_access(self):
        app = Application(self.temp.name)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(app))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)

        def request(method, path, body=None, expected=200):
            connection.request(method, path, body=json.dumps(body) if body is not None else None,
                               headers={"Content-Type": "application/json"} if body is not None else {})
            response = connection.getresponse()
            payload = json.loads(response.read())
            self.assertEqual(response.status, expected, payload)
            return payload

        try:
            prefix = f"/api/projects/{self.pid}/scale-predictions"
            body = self.arguments()
            body.pop("project_id")
            prediction = request("POST", prefix, body, expected=201)
            result = request("GET", prefix + "/" + prediction["id"])
            self.assertEqual(result, prediction)
            calculation = request("POST", prefix + "/" + prediction["id"] + "/calculate", {})
            self.assertEqual(calculation["kind"], "scale_prediction_calculation")
            self.assertAlmostEqual(calculation["summary"]["required_bed_volume_l"], 200)
            other = self.store.create_project("Other HTTP project", "Nd", "La")["id"]
            request("GET", f"/api/projects/{other}/scale-predictions/" + prediction["id"], expected=400)
            invalid = {**body, "values": {"usable_lifetime_cycles": 80}}
            request("POST", prefix, invalid, expected=400)
            self.assertEqual(self.store.get_project(self.pid)["accepted_experiment_count"], 0)
            self.assertEqual(len(self.store.list_scale_predictions(self.pid)), 1)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            app.close()


if __name__ == "__main__":
    unittest.main()
