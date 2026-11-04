import json
import hashlib
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from lanm_platform.core import Store
from lanm_platform.migration import load_asset, import_legacy_context


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.project = self.store.create_project("Test scenario", "Nd", "La")
        self.pid = self.project["id"]

    def tearDown(self):
        self.temp.cleanup()

    def conditions(self, **changes):
        return {"target": "Nd", "support": "agarose", "feed": "defined Nd/La nitrate solution", **changes}

    def configure(self):
        self.store.update_project(self.pid, {"configuration": self.conditions()}, "Specify operating context")
        self.store.update_assumptions(self.pid, {"cost_ceiling_usd_per_kg": 1e9}, "Evaluate the scientific gate independently of cost in this test")

    def metrics(self, **changes):
        return {"collected_target_kg_per_l_cycle": .001, "recovery_fraction": .9, "purity_fraction": .98,
                "cycles_observed": 3, "cycle_time_hours": 8, **changes}

    def draft(self, candidate="o-36", conditions=None, metrics=None):
        return self.store.add_experiment(self.pid, candidate, "Processed column result", conditions or self.conditions(),
                                         self.metrics() if metrics is None else metrics, "Test fixture, not a real measurement")

    def test_all_616_preserved_exactly_and_not_tested(self):
        library = load_asset()
        self.assertEqual(self.store.candidate_count(), 616)
        listing = self.store.list_candidates(self.pid, pool="untested")
        self.assertEqual(listing["total"], 616)
        self.assertEqual(len(listing["candidates"]), 100)
        original = next(c for c in library["candidates"] if c["id"] == "o-36")
        candidate = self.store.get_candidate("o-36")
        self.assertEqual(candidate["sequence"], original["sequence"])
        self.assertEqual(candidate["screening"], original["screening"])

    def test_immutable_revisions_persist_across_restart(self):
        old = self.store.get_project(self.pid)
        self.store.update_assumptions(self.pid, {"usable_lifetime_cycles": 20}, "A conservative scenario")
        self.store.update_assumptions(self.pid, {"usable_lifetime_cycles": 40}, "Revised hypothetical life", "o-36")
        self.store.add_message(self.pid, "user", "Retain these assumptions")
        saved = self.store.calculate(self.pid, "o-36")
        restart = Store(self.temp.name)
        self.assertEqual(restart.get_project(self.pid)["assumptions"]["usable_lifetime_cycles"], 20)
        self.assertEqual(restart.get_candidate("o-36", self.pid)["assumptions"]["usable_lifetime_cycles"], 40)
        self.assertEqual(restart.get_project(self.pid)["revisions"][0], old["revisions"][0])
        self.assertEqual(restart.messages(self.pid)[0]["content"], "Retain these assumptions")
        self.assertEqual(restart.list_runs(self.pid)[0]["id"], saved["id"])

    def test_draft_never_enters_updated_pool(self):
        self.draft()
        self.assertEqual(self.store.list_candidates(self.pid, pool="updated")["total"], 0)
        self.assertEqual(self.store.rank(self.pid, "updated")["pool_count"], 0)

    def test_acceptance_checks_target_and_stated_context(self):
        wrong = self.draft(conditions=self.conditions(target="Pr"))
        with self.assertRaisesRegex(ValueError, "target"):
            self.store.accept_experiment(wrong["id"], "Reviewed")
        missing = self.draft(conditions={"target": "Nd"})
        with self.assertRaisesRegex(ValueError, "support"):
            self.store.accept_experiment(missing["id"], "Reviewed")

    def test_explicit_accept_changes_pool_and_scientific_inputs(self):
        self.configure()
        draft = self.draft()
        self.store.accept_experiment(draft["id"], "Accepted processed measurements for this test")
        rank = self.store.rank(self.pid, "updated")
        self.assertEqual(rank["pool_count"], 1)
        self.assertEqual(rank["eligible_count"], 1)
        self.assertEqual(rank["rows"][0]["candidate_id"], "o-36")
        result = self.store.calculate(self.pid, "o-36")
        self.assertEqual(result["assumptions"]["collected_target_kg_per_l_cycle"], .001)
        self.assertEqual(result["assumptions"]["usable_lifetime_cycles"], 100)
        self.assertEqual(self.store.list_candidates(self.pid, pool="untested")["total"], 615)
        measured = [d for d in result["input_details"] if d["evidence_kind"] == "accepted_experimental_measurement"]
        self.assertEqual(len(measured), 4)

    def test_unknown_or_mismatched_context_is_not_scale_ready(self):
        draft = self.draft()
        self.store.accept_experiment(draft["id"], "Reviewed")
        rank = self.store.rank(self.pid, "updated")
        self.assertEqual(rank["eligible_count"], 0)
        self.assertIn("Project support is unspecified", rank["exclusions"][0]["reasons"])
        self.store.update_project(self.pid, {"configuration": self.conditions(support="CPG")}, "Changed format")
        result = self.store.calculate(self.pid, "o-36")
        self.assertEqual(result["assumptions"]["collected_target_kg_per_l_cycle"], .0005)
        self.assertEqual(self.store.rank(self.pid, "updated")["eligible_count"], 0)

    def test_incomplete_measured_update_remains_insufficient(self):
        self.configure()
        draft = self.draft(metrics={"purity_fraction": .999})
        self.store.accept_experiment(draft["id"], "Purity reviewed; no recovery supplied")
        result = self.store.rank(self.pid, "updated")
        self.assertEqual(result["pool_count"], 1)
        self.assertEqual(result["eligible_count"], 0)
        self.assertIn("Missing matched accepted measurements", " ".join(result["exclusions"][0]["reasons"]))

    def test_different_ph_experiments_cannot_supply_a_fictional_complete_set(self):
        self.configure()
        first = self.draft(conditions=self.conditions(pH=5), metrics={"purity_fraction": .99, "recovery_fraction": .9})
        second = self.draft(conditions=self.conditions(pH=6), metrics={"collected_target_kg_per_l_cycle": .002, "cycle_time_hours": 2, "cycles_observed": 10})
        self.store.accept_experiment(first["id"], "First accepted context")
        self.store.accept_experiment(second["id"], "Different conditions")
        rank = self.store.rank(self.pid, "updated")
        self.assertEqual(rank["eligible_count"], 0)
        calculation = self.store.calculate(self.pid, "o-36")
        self.assertNotIn("product_purity_fraction", calculation["assumptions"])
        self.assertEqual(calculation["assumptions"]["collected_target_kg_per_l_cycle"], .002)

    def test_entire_library_ranked_before_output_limit(self):
        result = self.store.rank(self.pid, "untested", limit=3)
        self.assertEqual(result["total_evaluated"], 616)
        self.assertEqual(result["pool_count"], 616)
        self.assertEqual(len(result["rows"]), 3)
        candidates = load_asset()["candidates"]
        expected = sorted(candidates, key=lambda c: (-(c["screening"]["mean"]["Nd"] - c["screening"]["mean"]["La"]), c["id"]))[:3]
        self.assertEqual([r["candidate_id"] for r in result["rows"]], [r["id"] for r in expected])
        self.assertTrue(all("cost_usd_per_kg" not in row for row in result["rows"]))

    def test_accepted_evidence_is_project_relative(self):
        draft = self.draft()
        self.store.accept_experiment(draft["id"], "Accepted here")
        other = self.store.create_project("Other", "Nd", "Dy")
        self.assertEqual(self.store.list_candidates(other["id"], pool="updated")["total"], 0)

    def test_source_dedup_and_unknown_metric_rejection(self):
        one = self.store.add_source(self.pid, "Notes", "A source text", "https://example.org/paper")
        two = self.store.add_source(self.pid, "Same", "A source text")
        self.assertEqual(one["id"], two["id"])
        self.assertEqual(self.store.list_sources(self.pid)[0]["text"], "A source text")
        with self.assertRaisesRegex(ValueError, "Unsupported metric"):
            self.draft(metrics={"normalized_score_as_recovery": .9})

    def test_custom_run_saved_with_method_version(self):
        run = self.store.save_custom_run(self.pid, {"method_id": "example", "method_version": "1.2", "inputs": {"x": 2}, "outputs": {"y": 4}})
        self.assertEqual(Store(self.temp.name).list_runs(self.pid)[0]["inputs"], {"x": 2})
        self.assertEqual(run["method_version"], "1.2")

    def test_saved_run_is_not_silently_refreshed_after_change(self):
        original = self.store.calculate(self.pid)
        self.assertFalse(self.store.get_run(self.pid, original["id"])["stale"])
        self.store.update_assumptions(self.pid, {"usable_lifetime_cycles": 200}, "Change hypothetical life")
        prior = self.store.get_run(self.pid, original["id"])
        self.assertTrue(prior["stale"])
        self.assertEqual(prior["assumptions"]["usable_lifetime_cycles"], 100)
        fresh = self.store.calculate(self.pid)
        self.assertFalse(self.store.get_run(self.pid, fresh["id"])["stale"])
        self.assertLess(fresh["summary"]["cost_usd_per_kg"], original["summary"]["cost_usd_per_kg"])

    def test_persisted_sensitivity_does_not_change_assumptions_or_project_revision(self):
        before = self.store.get_project(self.pid)
        result = self.store.sensitivity(self.pid, keys=["usable_lifetime_cycles"], factors=[.5, 1, 2])
        rows = result["sensitivity"][0]["rows"]
        self.assertGreater(rows[0]["cost_usd_per_kg"], rows[1]["cost_usd_per_kg"])
        self.assertGreater(rows[1]["cost_usd_per_kg"], rows[2]["cost_usd_per_kg"])
        after = self.store.get_project(self.pid)
        self.assertEqual(before["revision"], after["revision"])
        self.assertEqual(before["assumptions"], after["assumptions"])
        replay = Store(self.temp.name).get_run(self.pid, result["id"])
        self.assertEqual(replay["sensitivity"], result["sensitivity"])

    def test_sensitivity_reports_invalid_fraction_trial(self):
        result = self.store.sensitivity(self.pid, keys=["minimum_purity_fraction"], factors=[1, 2])
        rows = result["sensitivity"][0]["rows"]
        self.assertEqual(rows[0]["status"], "calculated")
        self.assertEqual(rows[1]["status"], "inapplicable")
        with self.assertRaises(ValueError):
            self.store.sensitivity(self.pid, factors=[-1])

    def test_legacy_handoff_preserves_hypotheses_without_activating_them(self):
        legacy = Path(self.temp.name) / "legacy" / "Week_3"
        path = legacy / "outputs" / "presenter_app" / "chat.sqlite3"
        path.parent.mkdir(parents=True)
        context = {"id": "provisional_o36_economics", "candidate_id": "o-36",
                   "configuration": {"target": "Pr", "support": "agarose", "scope": "partial_material_cost_contribution_only"}}
        life = {"id": "old-life", "context_id": context["id"], "parameter": "usable_lifetime_cycles",
                "value": 200, "unit": "cycle", "tier": "person", "evidence_kind": "user_constraint",
                "provenance": {"quote": "Use 200 cycles as a scenario constraint", "verification": "not a measurement"}}
        scope = {"id": "old-scope", "context_id": context["id"], "parameter": "scope", "value": "Partial material cost only",
                 "unit": "narrative", "tier": "person", "evidence_kind": "user_constraint"}
        with sqlite3.connect(path) as db:
            db.executescript("""
                CREATE TABLE candidates(id TEXT,payload TEXT);
                CREATE TABLE sources(id TEXT,payload TEXT);
                CREATE TABLE contexts(id TEXT,payload TEXT);
                CREATE TABLE assertions(seq INTEGER PRIMARY KEY,id TEXT,context_id TEXT,payload TEXT);
                CREATE TABLE formulas(seq INTEGER PRIMARY KEY,id TEXT,context_id TEXT,payload TEXT);
                CREATE TABLE selected_values(context_id TEXT,assertion_id TEXT);
                CREATE TABLE events(kind TEXT,payload TEXT);
            """)
            db.execute("INSERT INTO contexts VALUES(?,?)", (context["id"], json.dumps(context)))
            for item in (life, scope):
                db.execute("INSERT INTO assertions(id,context_id,payload) VALUES(?,?,?)", (item["id"], context["id"], json.dumps(item)))
                db.execute("INSERT INTO selected_values VALUES(?,?)", (context["id"], item["id"]))
            source = {"id": "legacy-paper", "title": "Historical source fixture", "url": "https://example.org/science", "sha256": "abc123"}
            db.execute("INSERT INTO sources VALUES(?,?)", (source["id"], json.dumps(source)))
        db.close()
        original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        before = self.store.get_project(self.pid)
        result = import_legacy_context(self.store, self.pid, legacy)
        repeat = import_legacy_context(self.store, self.pid, legacy)
        after = self.store.get_project(self.pid)
        self.assertEqual(result["source_id"], repeat["source_id"])
        self.assertEqual(result["database_count"], 1)
        self.assertEqual(result["additional_source_count"], 1)
        self.assertEqual(before["assumptions"], after["assumptions"])
        self.assertEqual(before["revision"], after["revision"])
        self.assertEqual(after["experiment_count"], 0)
        self.assertEqual(after["accepted_experiment_count"], 0)
        self.assertEqual(original_hash, hashlib.sha256(path.read_bytes()).hexdigest())
        archive = json.loads(self.store.list_sources(self.pid)[0]["text"])
        retained = archive["presenter_provisional_scenario"]["active_input_assertions"]
        self.assertEqual(next(r for r in retained if r["id"] == "old-life"), life)
        self.assertEqual(archive["status"], "historical_reference_only")
        self.assertLess(result["text_bytes"], 25000)

    def test_archived_source_read_is_bounded_verified_and_does_not_extract(self):
        text = "Introduction. " * 180 + "NEODYMIUM breakthrough observation. " + "Following context. " * 200
        raw = text.encode("utf-8")
        metadata = {"id": "archive-test", "title": "Archived paper fixture", "url": "https://example.org/paper",
                    "text_path": "Week_3/sources/paper.txt", "text_sha256": hashlib.sha256(raw).hexdigest()}
        with self.store._connect() as db:
            db.execute("INSERT INTO library_records VALUES(?,?,?)", ("sources:archive-test", "sources", json.dumps(metadata)))
        directory = Path(self.temp.name) / "legacy"
        directory.mkdir()
        archive = directory / "weeks1-3.zip"
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr(metadata["text_path"], raw)
        result = self.store.read_source(self.pid, "archive-test", query="neodymium", limit=1200)
        self.assertEqual(result["status"], "available")
        self.assertTrue(result["hash_verified"])
        self.assertTrue(result["query_found"])
        self.assertIn("NEODYMIUM", result["excerpt"])
        self.assertLessEqual(len(result["excerpt"]), 1200)
        continuation = self.store.read_source(self.pid, "archive-test", offset=result["next_offset"], limit=100)
        self.assertEqual(continuation["excerpt"], text[result["next_offset"]:result["next_offset"] + 100])
        self.assertEqual([p.name for p in directory.iterdir()], ["weeks1-3.zip"])
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr(metadata["text_path"], "Changed evidence")
        failed = self.store.read_source(self.pid, "archive-test")
        self.assertEqual(failed["status"], "unavailable")
        self.assertFalse(failed["hash_verified"])
        self.assertEqual(failed["excerpt"], "")
        self.assertIn("SHA-256", failed["reason"])

    def test_uploaded_source_read_checks_scope_and_missing_archives_are_explicit(self):
        own = self.store.add_source(self.pid, "Project notes", "Measured sample record")
        result = self.store.read_source(self.pid, own["id"], query="sample", limit=20)
        self.assertEqual(result["status"], "available")
        self.assertTrue(result["hash_verified"])
        other = self.store.create_project("Other source scope", "Nd", "Dy")
        with self.assertRaises(ValueError):
            self.store.read_source(other["id"], own["id"])
        with patch("lanm_platform.config.SOURCE_EVIDENCE", Path(self.temp.name) / "missing-evidence.zip"):
            missing = self.store.read_source(self.pid, "spyci_dataset")
        self.assertEqual(missing["status"], "unavailable")
        self.assertIn("archive is unavailable", missing["reason"])
        self.assertTrue(missing["url"].startswith("https://"))


if __name__ == "__main__":
    unittest.main()
