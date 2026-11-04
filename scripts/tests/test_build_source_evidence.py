"""Verify selection and integrity of the current platform's evidence assets."""

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


SPEC = importlib.util.spec_from_file_location("build_source_evidence", Path(__file__).resolve().parents[1] / "build_source_evidence.py")
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)


class BuildSourceEvidenceTests(unittest.TestCase):
    def test_includes_only_referenced_assets_with_original_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source, output, library = folder / "original.zip", folder / "evidence.zip", folder / "library.json.gz"
            raw = b"verified source text"
            record = {"id": "reference", "path": "Week_3/sources/source.txt", "sha256": hashlib.sha256(raw).hexdigest()}
            with gzip.open(library, "wt", encoding="utf-8") as stream:
                json.dump({"sources": [record]}, stream)
            with zipfile.ZipFile(source, "w") as package:
                package.writestr(record["path"], raw)
                package.writestr("old_app.py", b"obsolete code")
                package.writestr("history.sqlite3", b"obsolete database")
                package.writestr("slides.pptx", b"slide deck")
            original_hash = evidence.sha256_file(source)
            report = evidence.build_evidence(source, output, library)
            self.assertEqual(report["source_files"], 1)
            self.assertEqual(evidence.sha256_file(source), original_hash)
            with zipfile.ZipFile(output) as package:
                self.assertEqual(set(package.namelist()), {record["path"], evidence.MANIFEST})
                self.assertEqual(package.read(record["path"]), raw)
            with self.assertRaises(FileExistsError):
                evidence.build_evidence(source, output, library)

    def test_rejects_missing_or_changed_required_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source, output, library = folder / "original.zip", folder / "evidence.zip", folder / "library.json.gz"
            record = {"id": "reference", "path": "sources/source.txt", "sha256": hashlib.sha256(b"original").hexdigest()}
            with gzip.open(library, "wt", encoding="utf-8") as stream:
                json.dump({"sources": [record]}, stream)
            with zipfile.ZipFile(source, "w") as package:
                package.writestr(record["path"], b"changed")
            with self.assertRaisesRegex(ValueError, "recorded hash"):
                evidence.build_evidence(source, output, library)
            self.assertFalse(output.exists())
            with zipfile.ZipFile(source, "w") as package:
                package.writestr("unrelated.txt", b"unrelated")
            with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
                evidence.build_evidence(source, output, library)

    def test_rejects_non_evidence_paths_and_skips_inline_sources(self):
        digest = hashlib.sha256(b"source").hexdigest()
        for name in ("slides/deck.pdf", "../source.txt", "app.py", "old.sqlite3", "rehearsals.zip"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                evidence.collect_references([{"id": "reference", "path": name, "sha256": digest}])
        refs = evidence.collect_references([
            {"id": "reference", "path": "source.txt", "sha256": digest},
            {"id": "inline", "text": "stored in database", "path": "unused.txt"},
        ])
        self.assertEqual(set(refs), {"source.txt"})


if __name__ == "__main__":
    unittest.main()
