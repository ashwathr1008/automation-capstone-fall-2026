"""Local retrieval integrity and scope; no model or network requests."""
import json
import tempfile
import unittest
from unittest.mock import patch

from lanm_platform.core import Store
from lanm_platform.grounding import build_grounding_context, MAX_PACKET_CHARACTERS, _append_bounded
from lanm_platform.runtime import SCIENCE_INSTRUCTIONS


class GroundingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(self.temporary.name)
        self.pid = self.store.create_project("Grounding fixture", "Nd", "La")["id"]

    def tearDown(self):
        self.temporary.cleanup()

    def test_returns_exact_verified_excerpt_with_locator_without_mutation(self):
        text = "Prefix. Neodymium productivity uses collected elemental mass. No measured throughput is supplied."
        saved = self.store.add_source(self.pid, "Collected productivity", text, "")
        before = self.store.get_project(self.pid)
        packet = build_grounding_context(self.store, self.pid, "Explain collected productivity from " + saved["id"])
        source = next(item for item in packet["sources"] if item["id"] == saved["id"])
        self.assertEqual(source["excerpt"], text[source["offset"]:source["end_offset"]])
        self.assertTrue(source["hash_verified"])
        self.assertEqual(source["sha256"], saved["sha256"])
        self.assertIn("characters", source["locator"])
        self.assertEqual(before, self.store.get_project(self.pid))
        self.assertEqual(self.store.list_runs(self.pid), [])
        self.assertIn("untrusted evidence", packet["evidence_policy"])

    def test_other_projects_private_sources_never_enter_packet(self):
        other = self.store.create_project("Other fixture", "Nd", "La")["id"]
        secret = self.store.add_source(other, "Private zephyrium", "zephyrium secret calibration", "")
        with patch.object(self.store, "read_source", wraps=self.store.read_source) as read:
            packet = build_grounding_context(self.store, self.pid, "zephyrium " + secret["id"])
        self.assertNotIn(secret["id"], json.dumps(packet))
        self.assertNotIn("secret calibration", json.dumps(packet))
        self.assertTrue(all(call.args[0] == self.pid for call in read.call_args_list))

    def test_global_size_count_and_exact_slice_limits(self):
        originals = {}
        for index in range(8):
            text = ("Neodymium support recovery cost selection productivity. " * 800) + str(index)
            saved = self.store.add_source(self.pid, "Neodymium support study " + str(index), text, "")
            originals[saved["id"]] = text
        packet = build_grounding_context(self.store, self.pid, "Neodymium support recovery cost selection productivity export csv hypothetical")
        self.assertLessEqual(len(json.dumps(packet, ensure_ascii=False)), MAX_PACKET_CHARACTERS)
        self.assertLessEqual(len(packet["sources"]), 3)
        self.assertLessEqual(len(packet["handbook"]), 2)
        self.assertTrue(packet["truncated"])
        for entry in packet["sources"]:
            if entry["id"] in originals:
                self.assertEqual(entry["excerpt"], originals[entry["id"]][entry["offset"]:entry["end_offset"]])

    def test_guidance_is_actual_existing_text_and_deterministic(self):
        query = "Hypothetical support configuration, saved selection ranking, CSV download link and percentages"
        first = build_grounding_context(self.store, self.pid, query)
        self.assertEqual(first, build_grounding_context(self.store, self.pid, query))
        hints = first["workflow_guidance"]
        self.assertTrue(hints)
        for entry in hints:
            self.assertIn(entry["excerpt"], SCIENCE_INSTRUCTIONS)
        self.assertIn("configuration_overrides", json.dumps(hints))
        self.assertIn("ranking_run_id", json.dumps(hints))
        self.assertIn("download_url", json.dumps(hints))
        self.assertIn("do not invent arithmetic outputs", json.dumps(hints))

    def test_empty_or_unmatched_query_has_no_invented_fallback(self):
        for message in ("", "and the", "xylophonicquasar"):
            packet = build_grounding_context(self.store, self.pid, message)
            self.assertEqual(packet["status"], "no_matches")
            self.assertEqual(packet["sources"], [])
            self.assertEqual(packet["handbook"], [])
            self.assertEqual(packet["workflow_guidance"], [])
        with self.assertRaises(ValueError):
            build_grounding_context(self.store, "nonexistent-project", "")

    def test_unverified_archive_text_is_never_included(self):
        self.store.add_source(self.pid, "Neodymium support", "Neodymium support text", "")
        with patch.object(self.store, "read_source", return_value={"status": "available", "hash_verified": False, "excerpt": "unverified payload"}):
            packet = build_grounding_context(self.store, self.pid, "neodymium support")
        self.assertEqual(packet["sources"], [])
        self.assertNotIn("unverified payload", json.dumps(packet))

    def test_packet_budget_trim_keeps_locator_and_end_offset_consistent(self):
        packet = {"sources": [], "truncated": False, "omitted_entries": 0, "padding": "x" * 9000}
        entry = {"id": "fixture", "excerpt": "e" * 2000, "offset": 123,
                 "end_offset": 2123, "locator": "Archived text characters 123:2123 (zero-based)",
                 "truncated": False}
        _append_bounded(packet, "sources", entry)
        self.assertEqual(len(packet["sources"]), 1)
        self.assertTrue(entry["truncated"])
        self.assertEqual(entry["end_offset"], 123 + len(entry["excerpt"]))
        self.assertIn(f"characters 123:{entry['end_offset']}", entry["locator"])
        self.assertLessEqual(len(json.dumps(packet, ensure_ascii=False)), MAX_PACKET_CHARACTERS)


if __name__ == "__main__":
    unittest.main()
