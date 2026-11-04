"""Testing handoffs preserve a decision snapshot without changing research evidence."""
import csv
import io
import json
import math
import tempfile
import unittest

from lanm_platform.core import Store


class TestingHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.project = self.store.create_project("Handoff test", "Nd", "La")
        self.pid = self.project["id"]

    def tearDown(self):
        self.temp.cleanup()

    def rank(self, **kwargs):
        return self.store.rank(self.pid, **kwargs)

    def batch(self, **kwargs):
        return self.store.create_testing_batch(self.pid, **{"count": 3, **kwargs})

    def assert_research_state_unchanged(self, before):
        after = self.store.get_project(self.pid)
        for key in ("revision", "assumptions", "revisions", "configuration", "experiment_count", "accepted_experiment_count"):
            self.assertEqual(after[key], before[key], key)

    def test_default_eight_candidate_csv_survives_restart_and_project_change(self):
        before = self.store.get_project(self.pid)
        batch = self.batch(count=8, seed=27)
        self.assertEqual([row["well"] for row in batch["rows"]], [row + "1" for row in "ABCDEFGH"])
        self.assertEqual([row["rank"] for row in batch["rows"]], list(range(1, 9)))
        self.assertEqual(len(set(row["candidate_id"] for row in batch["rows"])), 8)
        self.assertTrue(batch["generation"]["uses_demo_defaults"])
        self.assertEqual(batch["generation"]["distribution"], "discrete_uniform")
        self.assertEqual(batch["generation"]["quantity"], "stock_volume")
        self.assertEqual((batch["generation"]["minimum"], batch["generation"]["maximum"]), (35, 250))
        self.assertEqual(batch["water_addition"], {
            "mode": "constant_per_starting_well", "volume_ul": None,
            "configured_by": "receiving_automation",
        })
        for row in batch["rows"]:
            self.assertIsInstance(row["stock_volume"], int)
            self.assertTrue(35 <= row["stock_volume"] <= 250)
            self.assertEqual(row["volume_unit"], "uL")
            self.assertEqual(row["volume_basis"], "simulated")
            self.assertEqual(row["volume_location"], "starting_well")
            self.assertEqual(row["water_addition_mode"], "constant_per_starting_well")
            self.assertNotIn("starting_concentration", row)
        text = self.store.testing_batch_csv(self.pid, batch["id"])
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(parsed), 8)
        self.assertEqual([row["candidate_id"] for row in parsed], batch["candidate_ids"])
        self.assertEqual({row["schema_version"] for row in parsed}, {"lanm_testing_batch_2"})
        self.assertEqual([float(row["stock_volume"]) for row in parsed], [row["stock_volume"] for row in batch["rows"]])
        self.assertEqual({row["volume_unit"] for row in parsed}, {"uL"})
        self.assertEqual({row["water_addition_mode"] for row in parsed}, {"constant_per_starting_well"})
        self.assert_research_state_unchanged(before)
        restarted = Store(self.temp.name)
        self.assertEqual(restarted.get_testing_batch(self.pid, batch["id"]), batch)
        self.assertEqual(restarted.testing_batch_csv(self.pid, batch["id"]), text)
        restarted.update_assumptions(self.pid, {"usable_lifetime_cycles": 30}, "Later committed scenario")
        self.assertTrue(restarted.get_testing_batch(self.pid, batch["id"])["stale"])
        self.assertEqual(restarted.testing_batch_csv(self.pid, batch["id"]), text)

    def test_explicit_default_profile_has_whole_numbers_and_seed_reproduces_values(self):
        default = self.batch(seed=18)
        explicit = self.batch(stock_volume_min_ul=35, stock_volume_max_ul=250, seed=18)
        self.assertEqual([row["stock_volume"] for row in default["rows"]], [row["stock_volume"] for row in explicit["rows"]])
        self.assertTrue(all(isinstance(row["stock_volume"], int) for row in explicit["rows"]))
        self.assertEqual(explicit["generation"]["unit"], "uL")
        self.assertFalse(explicit["generation"]["uses_demo_defaults"])

    def test_saved_legacy_concentrations_keep_original_units_and_csv_bytes(self):
        # An already-saved v1 record must never be interpreted as a volume plan.
        legacy = {
            "id": "batch_legacy", "project_id": self.pid, "revision": self.project["revision"],
            "schema_version": "lanm_testing_batch_1", "count": 1,
            "rows": [{"rank": 1, "candidate_id": "o-36", "candidate_name": "Legacy sample",
                      "plate_id": "legacy_plate", "well": "A1", "starting_concentration": 7,
                      "concentration_unit": "uM", "concentration_basis": "simulated",
                      "concentration_location": "starting_well", "recommendation_rank": 3}],
        }
        with self.store._connect() as db:
            db.execute("INSERT INTO testing_batches(id,project_id,payload) VALUES(?,?,?)",
                       (legacy["id"], self.pid, json.dumps(legacy)))
        expected = (
            "schema_version,batch_id,rank,candidate_id,candidate_name,plate_id,well,"
            "starting_concentration,concentration_unit,concentration_basis,concentration_location,"
            "recommendation_rank\r\n"
            "lanm_testing_batch_1,batch_legacy,1,o-36,Legacy sample,legacy_plate,A1,7,uM,simulated,starting_well,3\r\n"
        )
        self.assertEqual(self.store.testing_batch_csv(self.pid, legacy["id"]), expected)
        restarted = Store(self.temp.name)
        self.assertEqual(restarted.get_testing_batch(self.pid, legacy["id"])["rows"], legacy["rows"])
        restarted.update_assumptions(self.pid, {"usable_lifetime_cycles": 30}, "Later committed scenario")
        self.assertEqual(restarted.testing_batch_csv(self.pid, legacy["id"]), expected)

    def test_custom_stock_volume_bounds_and_fixed_endpoints(self):
        batch = self.batch(count=8, stock_volume_min_ul=35.125, stock_volume_max_ul=35.875, seed=3)
        for row in batch["rows"]:
            self.assertTrue(35.125 <= row["stock_volume"] <= 35.875)
            self.assertEqual(row["volume_unit"], "uL")
        self.assertEqual(batch["generation"]["distribution"], "uniform")
        for value in (35, 250, 35.1234567):
            with self.subTest(value=value):
                fixed = self.batch(stock_volume_min_ul=value, stock_volume_max_ul=value)
                self.assertEqual({row["stock_volume"] for row in fixed["rows"]}, {value})

    def test_invalid_counts_and_stock_volume_profiles_make_no_batches(self):
        for count in (0, 9, -1, True, 3.0, "3", None):
            with self.subTest(count=count), self.assertRaises(ValueError):
                self.batch(count=count)
        invalid = [
            {"stock_volume_min_ul": 35}, {"stock_volume_max_ul": 250},
            {"stock_volume_min_ul": 0, "stock_volume_max_ul": 250},
            {"stock_volume_min_ul": 34.999, "stock_volume_max_ul": 250},
            {"stock_volume_min_ul": 35, "stock_volume_max_ul": 250.001},
            {"stock_volume_min_ul": True, "stock_volume_max_ul": 250},
            {"stock_volume_min_ul": 35, "stock_volume_max_ul": False},
            {"stock_volume_min_ul": 250, "stock_volume_max_ul": 35},
            {"stock_volume_min_ul": 35, "stock_volume_max_ul": math.inf},
            {"stock_volume_min_ul": math.nan, "stock_volume_max_ul": 250},
            {"stock_volume_min_ul": "35", "stock_volume_max_ul": 250},
            {"seed": True}, {"seed": -1}, {"seed": 1.5}, {"seed": 2**53}, {"allow_stale": "yes"},
        ]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.batch(**kwargs)
        self.assertEqual(self.store.list_testing_batches(self.pid), [])

    def test_selection_reorders_and_includes_eligible_candidates_beyond_display_limit(self):
        run = self.rank(limit=2)
        ids = [run["ranked_candidate_ids"][7], run["ranked_candidate_ids"][0], run["ranked_candidate_ids"][4]]
        before = self.store.get_project(self.pid)
        selection = self.store.save_testing_selection(self.pid, run["id"], ids, "Discussed availability and selected these candidates")
        self.assertEqual(selection["candidate_ids"], ids)
        self.assertEqual([row["rank"] for row in selection["rows"]], [8, 1, 5])
        batch = self.batch(count=2, selection_id=selection["id"])
        self.assertEqual(batch["candidate_ids"], ids[:2])
        self.assertEqual([row["rank"] for row in batch["rows"]], [1, 2])
        self.assertEqual([row["recommendation_rank"] for row in batch["rows"]], [8, 1])
        self.assertEqual(batch["selection_reason"], selection["reason"])
        self.assertEqual(batch["selection_snapshot"]["candidate_ids"], ids)
        self.assert_research_state_unchanged(before)
        restarted = Store(self.temp.name)
        self.assertEqual(restarted.get_testing_selection(self.pid, selection["id"]), selection)
        self.assertEqual(restarted.list_testing_selections(self.pid)[0]["id"], selection["id"])

    def test_invalid_duplicate_or_ineligible_selection_is_rejected(self):
        run = self.rank(limit=8)
        candidate_id = run["rows"][0]["candidate_id"]
        for ids in ([], [candidate_id] * 2, [candidate_id] * 9, [None], "o-36", ["not-a-candidate"]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.store.save_testing_selection(self.pid, run["id"], ids, "Selection test")
        filtered = self.rank(exclude_candidate_ids=[candidate_id], scenario_reason="Candidate unavailable")
        with self.assertRaisesRegex(ValueError, "not eligible"):
            self.store.save_testing_selection(self.pid, filtered["id"], [candidate_id], "Cannot override eligibility silently")
        with self.assertRaises(ValueError):
            self.store.save_testing_selection(self.pid, run["id"], [candidate_id], "")
        self.assertEqual(self.store.list_testing_selections(self.pid), [])

    def test_shortage_and_conflicting_sources_fail_without_silent_truncation(self):
        run = self.rank(limit=1)
        selection = self.store.save_testing_selection(self.pid, run["id"], [run["rows"][0]["candidate_id"]], "Only one selected")
        with self.assertRaisesRegex(ValueError, "only 1"):
            self.batch(count=2, selection_id=selection["id"])
        with self.assertRaisesRegex(ValueError, "only 0"):
            self.batch(pool="updated")
        with self.assertRaisesRegex(ValueError, "not both"):
            self.batch(selection_id=selection["id"], ranking_run_id=run["id"])
        self.assertEqual(self.store.list_testing_batches(self.pid), [])

    def test_records_and_source_rank_are_project_scoped(self):
        run = self.rank()
        selection = self.store.save_testing_selection(self.pid, run["id"], [run["rows"][0]["candidate_id"]], "Scope fixture")
        batch = self.batch(count=1, selection_id=selection["id"])
        other = self.store.create_project("Other project", "Nd", "La")["id"]
        operations = [
            lambda: self.store.get_testing_selection(other, selection["id"]),
            lambda: self.store.get_testing_batch(other, batch["id"]),
            lambda: self.store.testing_batch_csv(other, batch["id"]),
            lambda: self.store.save_testing_selection(other, run["id"], batch["candidate_ids"], "Wrong project"),
            lambda: self.store.create_testing_batch(other, 1, selection_id=selection["id"]),
            lambda: self.store.create_testing_batch(other, 1, ranking_run_id=run["id"]),
        ]
        for operation in operations:
            with self.assertRaises(ValueError):
                operation()
        self.assertEqual(self.store.list_testing_batches(other), [])
        self.assertEqual(self.store.list_testing_selections(other), [])

    def test_new_exports_reject_stale_sources_unless_explicit_historical_snapshot(self):
        run = self.rank()
        ids = [row["candidate_id"] for row in run["rows"][:2]]
        selection = self.store.save_testing_selection(self.pid, run["id"], ids, "Original selection")
        self.store.update_assumptions(self.pid, {"usable_lifetime_cycles": 25}, "Change committed input")
        with self.assertRaisesRegex(ValueError, "Project changed"):
            self.batch(count=2, ranking_run_id=run["id"])
        with self.assertRaisesRegex(ValueError, "Project changed"):
            self.batch(count=2, selection_id=selection["id"])
        with self.assertRaisesRegex(ValueError, "Project changed"):
            self.store.save_testing_selection(self.pid, run["id"], ids, "Old selection")
        batch = self.batch(count=2, selection_id=selection["id"], allow_stale=True)
        self.assertTrue(batch["historical_snapshot_requested"])
        self.assertTrue(batch["project_changed_at_creation"])
        self.assertEqual(batch["revision"], run["revision"])
        self.assertEqual(batch["candidate_ids"], ids)

    def test_nonranking_source_is_rejected(self):
        calculation = self.store.calculate(self.pid)
        with self.assertRaisesRegex(ValueError, "candidate ranking"):
            self.batch(ranking_run_id=calculation["id"])

    def test_hypothetical_exclusion_changes_suggestions_without_committing(self):
        baseline = self.rank(limit=8)
        before = self.store.get_project(self.pid)
        first = baseline["rows"][0]["candidate_id"]
        scenario = self.rank(limit=8, exclude_candidate_ids=[first], scenario_reason="Keep unavailable sample out of this proposal")
        self.assertEqual(scenario["rows"][0]["candidate_id"], baseline["rows"][1]["candidate_id"])
        self.assertNotIn(first, scenario["ranked_candidate_ids"])
        self.assertTrue(scenario["is_hypothetical"])
        batch = self.batch(ranking_run_id=scenario["id"])
        self.assertEqual(batch["scenario"]["exclude_candidate_ids"], [first])
        self.assertTrue(batch["is_hypothetical"])
        self.assertEqual(batch["ranking_snapshot"]["scenario"], scenario["scenario"])
        self.assert_research_state_unchanged(before)
        self.assertEqual(self.rank(limit=8)["rows"], baseline["rows"])

    def test_hypothetical_assumptions_and_conditions_affect_updated_results_only(self):
        conditions = {"target": "Nd", "support": "agarose", "feed": "defined solution"}
        self.store.update_project(self.pid, {"configuration": conditions}, "Fixture operating context")
        self.store.update_assumptions(self.pid, {"cost_ceiling_usd_per_kg": 1e9}, "Fixture cost allowance")
        exp = self.store.add_experiment(self.pid, "o-36", "Fixture", conditions,
                                       {"collected_target_kg_per_l_cycle": .001, "recovery_fraction": .9,
                                        "purity_fraction": .98, "cycles_observed": 3, "cycle_time_hours": 8})
        self.store.accept_experiment(exp["id"], "Fixture acceptance")
        before = self.store.get_project(self.pid)
        baseline = self.rank(pool="updated")
        scenario = self.rank(pool="updated", assumption_overrides={"usable_lifetime_cycles": 200}, scenario_reason="Explore longer service life")
        self.assertLess(scenario["rows"][0]["cost_usd_per_kg"], baseline["rows"][0]["cost_usd_per_kg"])
        self.assertEqual(scenario["rows"][0]["assumed_usable_lifetime_cycles"], 200)
        mismatch = self.rank(pool="updated", configuration_overrides={"support": "different support"}, scenario_reason="Explore alternate support")
        self.assertEqual(mismatch["eligible_count"], 0)
        self.assertEqual(self.rank(pool="untested")["rows"], self.rank(pool="untested", assumption_overrides={"usable_lifetime_cycles": 200}, scenario_reason="No change expected to screening")["rows"])
        self.assert_research_state_unchanged(before)

    def test_invalid_or_unexplained_scenario_does_not_mutate_inputs(self):
        before = self.store.get_project(self.pid)
        cases = [
            {"assumption_overrides": {"usable_lifetime_cycles": 20}},
            {"assumption_overrides": {"usable_lifetime_cycles": -1}, "scenario_reason": "Invalid lifetime"},
            {"configuration_overrides": {"support": ""}, "scenario_reason": "Empty context"},
            {"configuration_overrides": {"target": "Dy"}, "scenario_reason": "Different metal"},
            {"configuration_overrides": {"temperature_c": math.nan}, "scenario_reason": "Invalid"},
            {"exclude_candidate_ids": ["unknown"], "scenario_reason": "Invalid"},
            {"exclude_candidate_ids": ["o-36", "o-36"], "scenario_reason": "Duplicate"},
            {"exclude_candidate_ids": "o-36", "scenario_reason": "Invalid type"},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.rank(**kwargs)
        self.assert_research_state_unchanged(before)

    def test_csv_quotes_names_and_neutralizes_spreadsheet_formulas(self):
        run = self.rank(limit=2)
        first, second = [row["candidate_id"] for row in run["rows"]]
        candidates = {candidate_id: self.store.get_candidate(candidate_id) for candidate_id in (first, second)}
        with self.store._connect() as db:
            for candidate_id, name in ((first, 'A "quoted", name\nsecond line'), (second, '=HYPERLINK("https://example.invalid")')):
                candidate = candidates[candidate_id]
                candidate["name"] = name
                db.execute("UPDATE candidates SET payload=? WHERE id=?", (json.dumps(candidate), candidate_id))
        batch = self.batch(count=2, ranking_run_id=run["id"])
        parsed = list(csv.DictReader(io.StringIO(self.store.testing_batch_csv(self.pid, batch["id"]))))
        self.assertEqual(parsed[0]["candidate_name"], 'A "quoted", name\nsecond line')
        self.assertTrue(parsed[1]["candidate_name"].startswith("'="))
        self.assertEqual([row["candidate_id"] for row in parsed], [first, second])


if __name__ == "__main__":
    unittest.main()
