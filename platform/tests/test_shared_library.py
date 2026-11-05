import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from lanm_platform.core import Store


class SharedLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.pid = self.store.create_project("Origin project", "Nd", "La")["id"]
        self.other = self.store.create_project("Receiving project", "Nd", "La")["id"]

    def source(self, **kwargs):
        return self.store.add_source(self.pid, "Reviewed evidence", "A source statement with limitations.",
                                     "https://example.org/evidence", **kwargs)

    def preview(self, record, kind="source", **kwargs):
        return self.store.preview_shared_evidence(self.pid, kind, record["id"], **kwargs)

    def promote(self, record, kind="source", **kwargs):
        candidate_id = kwargs.get("candidate_id")
        proposal = self.preview(record, kind, candidate_id=candidate_id)
        return self.store.promote_shared_evidence(self.pid, kind, record["id"], proposal["snapshot_sha256"],
                                                 "Reviewed for reuse in shared research", **kwargs)

    def shared(self, project_id=None):
        return [row for row in self.store.list_sources(project_id or self.pid)
                if row.get("origin") == "reviewed_shared_evidence"]

    def experiment(self):
        return self.store.add_experiment(self.pid, "o-36", "Processed result",
                                         {"target": "Nd", "support": "agarose", "feed": "defined Nd/La feed", "pH": 5},
                                         {"collected_target_kg_per_l_cycle": .001, "recovery_fraction": .9,
                                          "purity_fraction": .98, "cycles_observed": 3, "cycle_time_hours": 8},
                                         "Synthetic test fixture, not a laboratory observation")

    def test_preview_is_read_only_and_promotion_shares_exact_source_with_provenance(self):
        source = self.source(evidence_kind="retrieved_literature_abstract",
                             provenance={"provider": "NCBI PubMed", "pmid": "123", "content_scope": "Abstract only"})
        before = (self.store.get_project(self.pid), self.store.get_project(self.other))
        proposal = self.preview(source, candidate_id="o-36")
        self.assertEqual(self.shared(), [])
        self.assertEqual(proposal["text"], source["text"])
        self.assertEqual(proposal["provenance"]["record_snapshot"], source)
        shared = self.promote(source, candidate_id="o-36")
        self.assertIn(shared, self.store.list_sources(self.other))
        self.assertEqual(shared["evidence_kind"], "retrieved_literature_abstract")
        self.assertEqual(shared["provenance"]["record_snapshot"]["provenance"]["pmid"], "123")
        self.assertEqual(shared["sha256"], source["sha256"])
        self.assertEqual((self.store.get_project(self.pid), self.store.get_project(self.other)), before)
        excerpt = self.store.read_source(self.other, shared["id"], limit=10)
        self.assertTrue(excerpt["hash_verified"])
        self.assertEqual(excerpt["excerpt"], source["text"][:10])
        self.assertNotIn("record_snapshot", excerpt["provenance"])
        self.assertEqual(excerpt["candidate_id"], "o-36")
        self.assertEqual(self.store.library_evidence("o-36")["shared_evidence"][0]["id"], shared["id"])
        self.assertEqual(self.store.library_evidence("o-37")["shared_evidence"], [])

    def test_sharing_requires_origin_project_and_does_not_expose_private_sources(self):
        source = self.source()
        self.assertNotIn(source, self.store.list_sources(self.other))
        with self.assertRaisesRegex(ValueError, "Source not found"):
            self.store.read_source(self.other, source["id"])
        with self.assertRaisesRegex(ValueError, "Source not found in this project"):
            self.store.preview_shared_evidence(self.other, "source", source["id"])
        proposal = self.preview(source)
        with self.assertRaisesRegex(ValueError, "Source not found in this project"):
            self.store.promote_shared_evidence(self.other, "source", source["id"], proposal["snapshot_sha256"], "Share")
        self.assertEqual(self.shared(), [])

    def test_only_accepted_experiments_share_and_receiving_project_state_stays_unchanged(self):
        experiment = self.experiment()
        with self.assertRaisesRegex(ValueError, "explicitly accepted"):
            self.preview(experiment, "experiment")
        accepted = self.store.accept_experiment(experiment["id"], "Reviewed processed measurements")
        run = self.store.calculate(self.other)
        before = (self.store.get_project(self.pid), self.store.get_project(self.other),
                  self.store.get_candidate("o-36", self.pid), self.store.get_candidate("o-36", self.other))
        shared = self.promote(accepted, "experiment")
        self.assertEqual(shared["evidence_kind"], "accepted_experiment_snapshot")
        self.assertEqual(shared["candidate_id"], "o-36")
        self.assertEqual(shared["provenance"]["record_snapshot"], accepted)
        self.assertIn('"pH": 5', self.store.read_source(self.other, shared["id"])["excerpt"])
        self.assertEqual((self.store.get_project(self.pid), self.store.get_project(self.other),
                          self.store.get_candidate("o-36", self.pid), self.store.get_candidate("o-36", self.other)), before)
        self.assertFalse(self.store.get_run(self.other, run["id"])["stale"])
        self.assertEqual(self.store.rank(self.other, "updated")["pool_count"], 0)
        with self.assertRaisesRegex(ValueError, "Experiment not found in this project"):
            self.store.preview_shared_evidence(self.other, "experiment", accepted["id"])

    def test_snapshot_guard_rejects_changed_metadata_and_source_integrity_failures(self):
        source = self.source()
        proposal = self.preview(source)
        changed = {**source, "title": "Changed since review"}
        with self.store._connect() as db:
            db.execute("UPDATE sources SET payload=? WHERE id=?", (json.dumps(changed), source["id"]))
        with self.assertRaisesRegex(ValueError, "changed since preview"):
            self.store.promote_shared_evidence(self.pid, "source", source["id"], proposal["snapshot_sha256"], "Share")
        with self.store._connect() as db:
            db.execute("UPDATE sources SET payload=? WHERE id=?", (json.dumps({**source, "text": "Altered without hash"}), source["id"]))
        with self.assertRaisesRegex(ValueError, "SHA-256 integrity"):
            self.preview(source)
        self.assertEqual(self.shared(), [])

    def test_candidate_associations_and_review_inputs_are_validated(self):
        source = self.source()
        with self.assertRaisesRegex(ValueError, "Candidate not found"):
            self.preview(source, candidate_id="missing-candidate")
        experiment = self.experiment()
        self.store.accept_experiment(experiment["id"], "Reviewed")
        with self.assertRaisesRegex(ValueError, "must match"):
            self.preview(experiment, "experiment", candidate_id="o-37")
        proposal = self.preview(source)
        with self.assertRaisesRegex(ValueError, "review reason"):
            self.store.promote_shared_evidence(self.pid, "source", source["id"], proposal["snapshot_sha256"], " ")
        with self.assertRaisesRegex(ValueError, "snapshot SHA-256"):
            self.store.promote_shared_evidence(self.pid, "source", source["id"], "invalid", "Share")
        with self.assertRaisesRegex(ValueError, "Record type"):
            self.preview(source, "assumption")

    def test_retries_are_idempotent_including_concurrent_promotions(self):
        source = self.source()
        proposal = self.preview(source)
        def share(_):
            return self.store.promote_shared_evidence(self.pid, "source", source["id"], proposal["snapshot_sha256"],
                                                      "Explicit shared review")
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(share, range(4)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(len(self.shared()), 1)
        self.assertEqual(share(None), results[0])
        with self.store._connect() as db:
            events = [json.loads(row[0]) for row in db.execute("SELECT payload FROM events")]
        self.assertEqual(sum(event["kind"] == "evidence_shared" for event in events), 1)

    def test_revisions_append_without_overwriting_and_require_a_shared_target(self):
        source = self.source()
        initial = self.promote(source)
        revised_source = self.store.add_source(self.pid, "Revised evidence", "A corrected claim; prior evidence stays available.")
        for invalid_target in (source["id"], "spyci_paper", "missing-source"):
            with self.subTest(target=invalid_target), self.assertRaisesRegex(ValueError, "existing reviewed shared source"):
                self.promote(revised_source, supersedes_source_id=invalid_target)
        revision = self.promote(revised_source, supersedes_source_id=initial["id"])
        self.assertNotEqual(revision["id"], initial["id"])
        self.assertEqual(revision["supersedes_source_id"], initial["id"])
        self.assertEqual(self.promote(revised_source, supersedes_source_id=initial["id"]), revision)
        self.assertIn({**initial, "superseded_by_source_ids": [revision["id"]]}, self.shared(self.other))
        self.assertIn(revision, self.shared(self.other))
        self.assertEqual(self.shared(self.other)[0]["id"], revision["id"])
        previous = self.store.read_source(self.other, initial["id"])
        self.assertEqual(previous["excerpt"], source["text"])
        self.assertEqual(previous["superseded_by_source_ids"], [revision["id"]])
        self.assertNotIn("superseded_by_source_ids", self.store.read_source(self.other, revision["id"]))
        retained = {row["id"]: row for row in self.store.library_evidence()["shared_evidence"]}
        self.assertEqual(retained[initial["id"]]["superseded_by_source_ids"], [revision["id"]])
        self.assertNotIn("superseded_by_source_ids", retained[revision["id"]])
        with self.store._connect() as db:
            saved = json.loads(db.execute("SELECT payload FROM library_records WHERE id=?", ("sources:" + initial["id"],)).fetchone()[0])
        self.assertEqual(saved, initial)

    def test_revision_successor_links_include_all_branches_in_sorted_order(self):
        source = self.source()
        initial = self.promote(source, candidate_id="o-36")
        revisions = []
        for number in range(2):
            revision_source = self.store.add_source(self.pid, "Revision " + str(number), "Revised evidence " + str(number))
            revisions.append(self.promote(revision_source, candidate_id="o-36", supersedes_source_id=initial["id"]))
        expected = sorted(revision["id"] for revision in revisions)
        sources = {row["id"]: row for row in self.store.list_sources(self.other)}
        self.assertEqual(sources[initial["id"]]["superseded_by_source_ids"], expected)
        self.assertEqual(self.store.read_source(self.other, initial["id"])["superseded_by_source_ids"], expected)
        evidence = {row["id"]: row for row in self.store.library_evidence("o-36")["shared_evidence"]}
        self.assertEqual(evidence[initial["id"]]["superseded_by_source_ids"], expected)
        self.assertEqual(self.shared(self.other)[-1]["id"], initial["id"])

    def test_shared_copy_survives_origin_removal_restart_and_checks_its_own_hash(self):
        source = self.source()
        shared = self.promote(source)
        with self.store._connect() as db:
            db.execute("DELETE FROM sources WHERE id=?", (source["id"],))
        reopened = Store(self.temp.name)
        self.assertEqual(reopened.read_source(self.other, shared["id"])["excerpt"], source["text"])
        self.assertEqual(shared["sha256"], hashlib.sha256(shared["text"].encode()).hexdigest())
        with self.store._connect() as db:
            db.execute("UPDATE library_records SET payload=? WHERE id=?",
                       (json.dumps({**shared, "text": "Tampered shared copy"}), "sources:" + shared["id"]))
        result = reopened.read_source(self.other, shared["id"])
        self.assertFalse(result["hash_verified"])
        self.assertEqual(result["excerpt"], "")
        self.assertNotIn("record_snapshot", result["provenance"])


if __name__ == "__main__":
    unittest.main()
