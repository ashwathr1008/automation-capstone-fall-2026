import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from lanm_platform.core import Store
from lanm_platform.evidence import preview, read_original


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "research-data")
        self.project = self.store.create_project("Evidence test", "Nd", "La")
        self.pid = self.project["id"]
        self.archive = Path(self.temp.name) / "archive" / "weeks1-3.zip"
        self.archive.parent.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def add(self, identifier, path, raw, **metadata):
        source = {"id": identifier, "title": identifier, "path": path,
                  "sha256": hashlib.sha256(raw).hexdigest(), **metadata}
        with self.store._connect() as db:
            db.execute("INSERT INTO library_records VALUES(?,?,?)", ("sources:" + identifier, "sources", json.dumps(source)))
        with zipfile.ZipFile(self.archive, "a") as package:
            package.writestr(path, raw)
        return source

    def test_exact_pdf_and_tracking_link_preview_preserve_bytes(self):
        raw = b"%PDF-1.4\nSmall inert fixture\n%%EOF"
        source = self.add("paper-fixture", "Week_1/sources/paper.pdf", raw, url="https://example.org/paper.pdf?version=2")
        result = preview(self.store, self.pid, url=source["url"] + "&utm_source=chat#page=2")
        self.assertEqual(result["source_id"], "paper-fixture")
        self.assertEqual(result["preview_kind"], "pdf")
        self.assertTrue(result["hash_verified"])
        self.assertEqual(read_original(self.store, self.pid, source["id"]), (raw, "application/pdf", "paper.pdf"))
        self.assertFalse(preview(self.store, self.pid, url="https://example.org/paper.pdf?version=3")["available"])

    def test_shared_doi_resolves_primary_paper_not_dataset_or_supplement(self):
        result = preview(self.store, self.pid, url="https://doi.org/10.1038/s41589-026-02176-3")
        self.assertEqual(result["source_id"], "spyci_paper")
        article = preview(self.store, self.pid, url="https://www.nature.com/articles/s41589-026-02176-3#Fig6")
        self.assertEqual(article["source_id"], "spyci_paper")
        source = next(row for row in self.store.list_sources(self.pid) if row["id"] == "spyci_dataset")
        self.assertEqual(preview(self.store, self.pid, url=source["url"])["source_id"], "spyci_dataset")

    def test_pmc_pdf_alias_excludes_supplementary_artifacts(self):
        article = preview(self.store, self.pid, url="https://pmc.ncbi.nlm.nih.gov/articles/PMC11600183/pdf/au4c00628.pdf")
        self.assertEqual(article["source_id"], "lanm_equilibrium_2024")
        other = preview(self.store, self.pid, url="https://pmc.ncbi.nlm.nih.gov/articles/PMC11600183/bin/supplement.pdf")
        self.assertIsNone(other["source_id"])

    def test_own_text_is_scoped_and_not_repeated_in_metadata(self):
        own = self.store.add_source(self.pid, "My evidence", "Evidence <script>is text</script>", "https://example.org/notes")
        result = preview(self.store, self.pid, source_id=own["id"])
        self.assertEqual(result["preview_kind"], "text")
        self.assertNotIn("text", result["source"])
        self.assertEqual(read_original(self.store, self.pid, own["id"])[0], own["text"].encode())
        other = self.store.create_project("Other", "Nd", "Dy")
        with self.assertRaisesRegex(ValueError, "Source not found"):
            read_original(self.store, other["id"], own["id"])

    def share(self, source, **changes):
        snapshot = self.store.preview_shared_evidence(self.pid, "source", source["id"])
        return self.store.promote_shared_evidence(
            self.pid, "source", source["id"], snapshot["snapshot_sha256"],
            "Reviewed for use across project evidence discussions.", **changes)

    def test_shared_snapshot_preview_and_download_work_from_another_project(self):
        text = "Reviewed evidence: Δoutput is unknown. <script>remains plain text</script>"
        own = self.store.add_source(self.pid, "Shared evidence fixture", text, "https://example.org/shared")
        shared = self.share(own)
        other = self.store.create_project("Other evidence project", "Nd", "Dy")
        result = preview(self.store, other["id"], source_id=shared["id"])
        self.assertTrue(result["available"])
        self.assertTrue(result["original_available"])
        self.assertTrue(result["text_available"])
        self.assertTrue(result["hash_verified"])
        self.assertEqual(result["preview_kind"], "text")
        self.assertEqual(result["source"]["origin"], "reviewed_shared_evidence")
        self.assertEqual(result["source"]["provenance"]["source_project_id"], self.pid)
        self.assertNotIn("text", result["source"])
        self.assertNotIn("text", result["source"]["provenance"]["record_snapshot"])
        raw, mime, filename = read_original(self.store, other["id"], shared["id"])
        self.assertEqual(raw, text.encode("utf-8"))
        self.assertEqual(mime, "text/plain; charset=utf-8")
        self.assertEqual(filename, shared["id"] + ".txt")
        # Creating a preview must not remove text from the retained provenance.
        retained = next(row for row in self.store.list_sources(other["id"]) if row["id"] == shared["id"])
        self.assertEqual(retained["provenance"]["record_snapshot"]["text"], text)
        with self.assertRaisesRegex(ValueError, "Source not found"):
            read_original(self.store, other["id"], own["id"])

    def test_shared_abstract_preview_retains_original_scope_and_indexing_notices(self):
        own = self.store.add_source(
            self.pid, "Abstract fixture", "Citation and abstract only.",
            "https://pubmed.ncbi.nlm.nih.gov/900000001/",
            evidence_kind="retrieved_literature_abstract",
            provenance={"content_scope": "Abstract only; full article not retrieved.",
                        "is_retracted": True, "notices": [{"type": "RetractionIn"}]})
        shared = self.share(own)
        other = self.store.create_project("Other literature project", "Nd", "Dy")
        result = preview(self.store, other["id"], source_id=shared["id"])
        self.assertEqual(result["source"]["evidence_kind"], "retrieved_literature_abstract")
        original_provenance = result["source"]["provenance"]["record_snapshot"]["provenance"]
        self.assertEqual(original_provenance, own["provenance"])
        self.assertTrue(original_provenance["is_retracted"])

    def test_shared_abstract_can_be_resolved_by_its_retained_doi(self):
        own = self.store.add_source(
            self.pid, "Shared DOI fixture", "Synthetic citation and abstract.",
            "https://pubmed.ncbi.nlm.nih.gov/900000003/",
            evidence_kind="retrieved_literature_abstract", provenance={"doi": "10.99999/shared-fixture"})
        shared = self.share(own)
        other = self.store.create_project("Other DOI project", "Nd", "Dy")
        result = preview(self.store, other["id"], url="https://doi.org/10.99999/shared-fixture")
        self.assertEqual(result["source_id"], shared["id"])
        self.assertTrue(result["available"])

    def test_shared_citation_uses_successor_while_explicit_id_retains_history(self):
        url = "https://www.nature.com/articles/shared-evidence-fixture"
        source = self.store.add_source(self.pid, "Earlier source", "Earlier interpretation.", url)
        earlier = self.share(source)
        revised = self.store.add_source(self.pid, "Corrected source", "Corrected interpretation.", url)
        successor = self.share(revised, supersedes_source_id=earlier["id"])
        other = self.store.create_project("Other revision project", "Nd", "Dy")
        for reference in (url, url + ".pdf"):
            self.assertEqual(preview(self.store, other["id"], url=reference)["source_id"], successor["id"])
        historical = preview(self.store, other["id"], source_id=earlier["id"])
        self.assertEqual(historical["source_id"], earlier["id"])
        self.assertEqual(historical["source"]["superseded_by_source_ids"], [successor["id"]])
        self.assertEqual(read_original(self.store, other["id"], earlier["id"])[0], b"Earlier interpretation.")

    def test_shared_excerpt_does_not_replace_an_imported_primary_document(self):
        url = "https://www.nature.com/articles/imported-primary-fixture"
        original = self.add("imported-primary", "Week_1/sources/primary.pdf", b"%PDF-1.4 fixture",
                            url=url, doi="10.99999/imported-primary")
        source = self.store.add_source(self.pid, "Reviewed excerpt", "A short source excerpt.", url,
                                       provenance={"doi": "10.99999/imported-primary"})
        self.share(source)
        other = self.store.create_project("Other primary project", "Nd", "Dy")
        for reference in (url, url + ".pdf", "https://doi.org/10.99999/imported-primary"):
            self.assertEqual(preview(self.store, other["id"], url=reference)["source_id"], original["id"])

    def test_shared_snapshot_integrity_failure_blocks_preview_and_download(self):
        own = self.store.add_source(self.pid, "Integrity fixture", "Original reviewed evidence.")
        shared = self.share(own)
        with self.store._connect() as db:
            db.execute("UPDATE library_records SET payload=? WHERE id=?",
                       (json.dumps({**shared, "text": "Unreviewed replacement."}), "sources:" + shared["id"]))
        other = self.store.create_project("Other integrity project", "Nd", "Dy")
        result = preview(self.store, other["id"], source_id=shared["id"])
        self.assertFalse(result["available"])
        self.assertFalse(result["original_available"])
        self.assertFalse(result["text_available"])
        self.assertIn("SHA-256", result["reason"])
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            read_original(self.store, other["id"], shared["id"])

    def test_hash_failure_and_traversal_are_never_served(self):
        source = self.add("corrupt", "Week_1/sources/corrupt.pdf", b"%PDF-1.4 unchanged")
        with self.store._connect() as db:
            db.execute("UPDATE library_records SET payload=? WHERE id=?", (json.dumps({**source, "sha256": "0" * 64}), "sources:corrupt"))
        result = preview(self.store, self.pid, source_id="corrupt")
        self.assertFalse(result["original_available"])
        self.assertIn("SHA-256", result["reason"])
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            read_original(self.store, self.pid, "corrupt")
        self.add("traversal", "../outside.pdf", b"%PDF-1.4")
        with self.assertRaisesRegex(ValueError, "safe relative"):
            read_original(self.store, self.pid, "traversal")

    def test_html_and_svg_originals_are_not_active_application_content(self):
        for extension in ("html", "svg"):
            self.add("active-" + extension, "Week_1/sources/file." + extension, b"<script>active()</script>")
            with self.assertRaisesRegex(ValueError, "file type"):
                read_original(self.store, self.pid, "active-" + extension)
        with self.assertRaises(ValueError):
            preview(self.store, self.pid, url="file:///C:/secret")

    def test_spreadsheet_uses_verified_text_and_only_offers_explicit_original(self):
        raw = b"PK\x03\x04spreadsheet fixture"
        text = b"Sheet 1\nCandidate,Nd,La\no-36,0.5,0.3"
        source = self.add("sheet", "Week_1/sources/sheet.xlsx", raw,
                          text_path="Week_3/sources/sheet.txt", text_sha256=hashlib.sha256(text).hexdigest())
        with zipfile.ZipFile(self.archive, "a") as package:
            package.writestr(source["text_path"], text)
        result = preview(self.store, self.pid, source_id="sheet")
        self.assertEqual(result["preview_kind"], "text")
        self.assertTrue(result["original_available"])
        self.assertTrue(result["text_available"])
        self.assertEqual(read_original(self.store, self.pid, "sheet")[0], raw)

    def test_bundled_evidence_supports_original_and_verified_text_without_legacy_archive(self):
        self.archive = Path(self.temp.name) / "source-evidence.zip"
        raw = b"%PDF-1.4\nBundled inert fixture\n%%EOF"
        text = b"Bundled source text for a portable checkout."
        source = self.add("bundled-paper", "Week_1/sources/bundled.pdf", raw,
                          text_path="Week_3/sources/bundled.txt", text_sha256=hashlib.sha256(text).hexdigest())
        with zipfile.ZipFile(self.archive, "a") as package:
            package.writestr(source["text_path"], text)
        with patch("lanm_platform.config.SOURCE_EVIDENCE", self.archive):
            result = preview(self.store, self.pid, source_id=source["id"])
            self.assertEqual(result["preview_kind"], "pdf")
            self.assertTrue(result["original_available"])
            self.assertTrue(result["text_available"])
            self.assertTrue(result["hash_verified"])
            self.assertEqual(read_original(self.store, self.pid, source["id"])[0], raw)
            excerpt = self.store.read_source(self.pid, source["id"], query="portable")
            self.assertEqual(excerpt["status"], "available")
            self.assertEqual(excerpt["excerpt"], text.decode())
            self.assertTrue(excerpt["hash_verified"])
        self.assertFalse((Path(self.temp.name) / "Week_1").exists())
        self.assertFalse((Path(self.temp.name) / "Week_3").exists())

    def test_existing_local_archives_take_precedence_over_bundled_evidence(self):
        bundled = Path(self.temp.name) / "source-evidence.zip"
        legacy = self.store.data_dir / "legacy" / "weeks1-3.zip"
        legacy.parent.mkdir()
        member = "Week_1/sources/local.pdf"
        archives = [
            (legacy, b"%PDF-1.4 legacy fixture"),
            (self.archive, b"%PDF-1.4 sibling archive fixture"),
            (bundled, b"%PDF-1.4 bundled fixture"),
        ]
        for archive, raw in archives:
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr(member, raw)
        with patch("lanm_platform.config.SOURCE_EVIDENCE", bundled):
            for archive, expected in archives:
                source = {"id": "local-paper", "title": "Archive precedence fixture", "path": member,
                          "sha256": hashlib.sha256(expected).hexdigest()}
                with self.store._connect() as db:
                    db.execute("INSERT OR REPLACE INTO library_records VALUES(?,?,?)",
                               ("sources:local-paper", "sources", json.dumps(source)))
                self.assertEqual(read_original(self.store, self.pid, source["id"])[0], expected)
                archive.unlink()

    def test_missing_local_and_bundled_archives_are_reported(self):
        source = self.add("missing-original", "Week_1/sources/missing.pdf", b"%PDF-1.4 fixture")
        self.archive.unlink()
        with patch("lanm_platform.config.SOURCE_EVIDENCE", Path(self.temp.name) / "missing-evidence.zip"):
            result = preview(self.store, self.pid, source_id=source["id"])
        self.assertFalse(result["available"])
        self.assertFalse(result["original_available"])
        self.assertIn("archive is unavailable", result["reason"])


if __name__ == "__main__":
    unittest.main()
