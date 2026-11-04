import json
import unittest

from lanm_platform import guidance


class GuidanceTests(unittest.TestCase):
    def test_catalog_is_stable_small_and_does_not_include_full_text(self):
        records = guidance.catalog()
        self.assertEqual([row["id"] for row in records], [
            "candidate-evidence", "binding-vs-process", "matched-conditions",
            "experiments-and-reuse", "separation-economics", "evidence-and-citations",
            "method-validation",
        ])
        self.assertLess(len(json.dumps(records)), 6500)
        for row in records:
            self.assertEqual(set(row), {"id", "title", "summary", "keywords", "sources"})
            self.assertLessEqual(len(row["summary"]), 240)
            self.assertTrue(row["sources"])
        records[0]["sources"].clear()
        records[0]["keywords"].append("poisoned")
        self.assertTrue(guidance.catalog()[0]["sources"])
        self.assertNotIn("poisoned", guidance.catalog()[0]["keywords"])

    def test_read_is_restricted_to_known_ids(self):
        for identifier in ("../core.py", "..\\core.py", "C:\\secret.txt", "data/lanm_handbook.md",
                           "https://example.org", "", "unknown-section", None, 1, "x" * 100):
            with self.subTest(identifier=identifier), self.assertRaisesRegex(ValueError, "Unknown guidance"):
                guidance.read(identifier)

    def test_reads_include_citations_revision_and_honest_review_status(self):
        for summary in guidance.catalog():
            result = guidance.read(summary["id"])
            self.assertEqual(result["version"], "2026-11-03.1")
            self.assertIn("not independently scientifically validated", result["review_status"])
            self.assertNotIn("Keywords:", result["text"])
            self.assertEqual(result["sources"], summary["sources"])
            for url in result["sources"]:
                self.assertIn(url, result["text"])
        result["sources"].clear()
        self.assertTrue(guidance.read(result["id"])["sources"])

    def test_selection_routes_real_questions_without_full_text_or_guessing(self):
        questions = {
            "Which untested candidates should we shortlist?": "candidate-evidence",
            "What does affinity or a logD selectivity factor mean?": "binding-vs-process",
            "How should we compare feed, pH, support and temperature conditions?": "matched-conditions",
            "What next experiment measures reuse with independent replicates?": "experiments-and-reuse",
            "Build a technoeconomic cost model per kilogram": "separation-economics",
            "Find literature evidence in PubMed abstracts and cite sources": "evidence-and-citations",
            "Validate numerical method code with independent reference checks": "method-validation",
        }
        for query, expected in questions.items():
            with self.subTest(query=query):
                selected = guidance.select(query, limit=1)
                self.assertEqual(selected[0]["id"], expected)
                self.assertNotIn("text", selected[0])
                self.assertEqual(selected, guidance.select(query, limit=1))
        self.assertEqual(guidance.select("lanmodulin"), [])
        self.assertEqual(guidance.select("unrelated astronomy"), [])
        self.assertEqual(guidance.select("cost", limit=0), [])
        self.assertEqual(guidance.select(" " * 4000 + "cost"), [])
        self.assertLessEqual(len(guidance.select("cost method screening", limit=100000)), 7)

    def test_invalid_selection_arguments_are_rejected(self):
        for limit in (-1, 1.5, True, "3"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                guidance.select("cost", limit=limit)
        with self.assertRaises(ValueError):
            guidance.select(None)


if __name__ == "__main__":
    unittest.main()
