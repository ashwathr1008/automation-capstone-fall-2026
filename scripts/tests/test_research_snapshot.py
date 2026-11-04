"""Exercise privacy-safe library exports and failure-safe restoration."""
import hashlib
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import zipfile


SPEC = importlib.util.spec_from_file_location("research_snapshot", Path(__file__).resolve().parents[1] / "research_snapshot.py")
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "platform" / "src"))
from lanm_platform.core import Store


class ResearchSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / "research-data"
        self.data.mkdir()
        self.database = self.data / "research.sqlite3"
        Store(self.data)
        self.private_marker = "PRIVATE_CONVERSATION_REHEARSAL_SENTINEL_7623"
        with closing(sqlite3.connect(self.database)) as connection:
            for table in sorted(snapshot.EMPTY_TABLES - {"sqlite_sequence"}):
                columns = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
                values = [1 if column[2] == "INTEGER" else self.private_marker * 150 for column in columns]
                connection.execute(f'INSERT INTO "{table}" VALUES({",".join("?" for _ in values)})', values)
            connection.commit()
        self.archive = self.root / "portable-data" / "research-snapshot.zip"

    def put(self, relative, text="fixture"):
        path = self.data / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def rewrite(self, mutate):
        with zipfile.ZipFile(self.archive) as original:
            contents = {name: original.read(name) for name in original.namelist()}
        mutate(contents)
        with zipfile.ZipFile(self.archive, "w", zipfile.ZIP_DEFLATED) as modified:
            for name, body in contents.items():
                modified.writestr(name, body)

    def assert_no_restored_state(self, target):
        self.assertFalse((target / "research-data").exists())
        self.assertEqual(list(target.iterdir()) if target.exists() else [], [])

    def shared_rows(self, path):
        with closing(sqlite3.connect(path)) as connection:
            return {table: connection.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()
                    for table in snapshot.SHARED_TABLES}

    def reseal_member(self, files, name, body):
        files[name] = body
        manifest = json.loads(files[snapshot.MANIFEST])
        manifest["files"][name] = {"size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        files[snapshot.MANIFEST] = json.dumps(manifest).encode()

    def test_starter_retains_library_and_exact_methods_but_physically_removes_all_history(self):
        artifacts = {
            "method.py": "def evaluate(): return 3\n",
            "manifest.json": '{"digest":"fixed-method-digest","version":"example@123"}',
            "checks.json": '{"digest":"fixed-method-digest","passed":true,"reference_cases":[{"expected":3}]}',
        }
        for category in ("drafts", "versions"):
            for name, text in artifacts.items():
                self.put(f"methods/{category}/example/{name}", text)
        before = self.database.read_bytes()
        original_rows = self.shared_rows(self.database)
        result = snapshot.create_snapshot(self.data, self.archive)
        self.assertEqual(result["export_profile"], "starter-library-and-methods")
        self.assertEqual(self.database.read_bytes(), before)
        self.assertIn(self.private_marker.encode(), before)
        target = self.root / "restored"
        snapshot.restore_snapshot(self.archive, target)
        restored_db = target / snapshot.DATABASE
        self.assertEqual(self.shared_rows(restored_db), original_rows)
        self.assertNotIn(self.private_marker.encode(), restored_db.read_bytes())
        self.assertNotIn(self.private_marker.encode("utf-16le"), restored_db.read_bytes())
        with closing(sqlite3.connect(restored_db)) as restored:
            for table in snapshot.EMPTY_TABLES:
                self.assertEqual(restored.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0], 0)
            self.assertEqual(restored.execute("PRAGMA freelist_count").fetchone()[0], 0)
        for category in ("drafts", "versions"):
            for name, text in artifacts.items():
                self.assertEqual((target / f"research-data/methods/{category}/example/{name}").read_bytes(),
                                 (self.data / f"methods/{category}/example/{name}").read_bytes())

    def test_readonly_backup_includes_committed_library_updates_in_wal(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("INSERT INTO metadata VALUES ('wal-library-update','committed library metadata')")
            connection.execute("INSERT INTO messages(id,project_id,payload) VALUES ('wal-message','private-project',?)", (self.private_marker,))
            connection.commit()
            original = self.database.read_bytes()
            original_wal = self.database.with_name("research.sqlite3-wal").read_bytes()
            snapshot.create_snapshot(self.data, self.archive)
            self.assertEqual(self.database.read_bytes(), original)
            self.assertEqual(self.database.with_name("research.sqlite3-wal").read_bytes(), original_wal)
            target = self.root / "restored"
            snapshot.restore_snapshot(self.archive, target)
            with closing(sqlite3.connect(target / snapshot.DATABASE)) as restored:
                self.assertEqual(restored.execute("SELECT value FROM metadata WHERE key='wal-library-update'").fetchone()[0], "committed library metadata")
                self.assertEqual(restored.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)
                self.assertEqual(restored.execute("PRAGMA journal_mode").fetchone()[0], "delete")

    def test_only_expected_method_artifacts_can_be_exported(self):
        for name in ["runtime_threads.json", "installation_manifest.json", "server.log", "methods/slides/deck.pdf", "methods/PowerPoint_export.pdf", "methods/Deck.pptx", "methods/Deck.pdf", "methods/.env", "methods/auth.json", "methods/ordinary-paper.pdf", "methods/versions/example/conversation.json", "methods/drafts/example/transcript.txt", "methods/versions/example/private/nested.json", "workspaces/research/evidence.txt", "workspaces/.codex/auth.json", "workspaces/package.zip", "uploads/conversation.json", "attachments/chat.txt", "evidence/session.json", "methods/__pycache__/example.pyc"]:
            self.put(name)
        self.put("methods/versions/example/method.py", "def evaluate(): return 3")
        snapshot.create_snapshot(self.data, self.archive)
        with zipfile.ZipFile(self.archive) as package:
            self.assertEqual(set(package.namelist()), {snapshot.MANIFEST, snapshot.DATABASE, "research-data/methods/versions/example/method.py"})

    def test_existing_data_is_untouched(self):
        snapshot.create_snapshot(self.data, self.archive)
        before = self.database.read_bytes()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            snapshot.restore_snapshot(self.archive, self.root)
        self.assertEqual(self.database.read_bytes(), before)
        self.assertFalse(list(self.root.glob(".research-restore-*")))

    def test_checksum_failure_leaves_no_restored_files(self):
        self.put("methods/versions/example/method.py", "original")
        snapshot.create_snapshot(self.data, self.archive)
        self.rewrite(lambda files: files.__setitem__("research-data/methods/versions/example/method.py", b"tampered"))
        target = self.root / "restored"
        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            snapshot.restore_snapshot(self.archive, target)
        self.assert_no_restored_state(target)

    def test_traversal_even_with_valid_manifest_is_rejected(self):
        snapshot.create_snapshot(self.data, self.archive)
        def mutate(files):
            name = "research-data/methods/../../outside.txt"
            files[name] = b"outside"
            manifest = json.loads(files[snapshot.MANIFEST])
            manifest["files"][name] = {"size": 7, "sha256": hashlib.sha256(b"outside").hexdigest()}
            files[snapshot.MANIFEST] = json.dumps(manifest).encode()
        self.rewrite(mutate)
        target = self.root / "restored"
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            snapshot.restore_snapshot(self.archive, target)
        self.assert_no_restored_state(target)
        self.assertFalse((self.root / "outside.txt").exists())

    def test_unmanifested_member_is_rejected_before_restoring(self):
        snapshot.create_snapshot(self.data, self.archive)
        self.rewrite(lambda files: files.__setitem__("research-data/methods/unexpected.py", b"extra"))
        target = self.root / "restored"
        with self.assertRaisesRegex(ValueError, "exactly match"):
            snapshot.restore_snapshot(self.archive, target)
        self.assert_no_restored_state(target)

    def test_bad_database_with_valid_hash_is_rejected(self):
        snapshot.create_snapshot(self.data, self.archive)
        self.rewrite(lambda files: self.reseal_member(files, snapshot.DATABASE, b"not a SQLite database"))
        target = self.root / "restored"
        with self.assertRaises(sqlite3.DatabaseError):
            snapshot.restore_snapshot(self.archive, target)
        self.assert_no_restored_state(target)

    def test_unknown_tables_fail_closed_without_replacing_previous_export(self):
        self.archive.parent.mkdir()
        self.archive.write_bytes(b"previous export remains intact")
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("CREATE TABLE unexpected_private_notes (body TEXT)")
            connection.execute("INSERT INTO unexpected_private_notes VALUES (?)", (self.private_marker,))
            connection.commit()
        with self.assertRaisesRegex(ValueError, "Unrecognized database tables"):
            snapshot.create_snapshot(self.data, self.archive)
        self.assertEqual(self.archive.read_bytes(), b"previous export remains intact")

    def test_original_full_backup_cannot_be_relabelled_as_starter(self):
        snapshot.create_snapshot(self.data, self.archive)
        self.rewrite(lambda files: self.reseal_member(files, snapshot.DATABASE, self.database.read_bytes()))
        target = self.root / "restored"
        with self.assertRaisesRegex(ValueError, "private or project history"):
            snapshot.restore_snapshot(self.archive, target)
        self.assert_no_restored_state(target)

    def test_old_export_profile_is_rejected(self):
        snapshot.create_snapshot(self.data, self.archive)
        def mutate(files):
            manifest = json.loads(files[snapshot.MANIFEST])
            manifest["version"] = 1
            manifest.pop("export_profile")
            files[snapshot.MANIFEST] = json.dumps(manifest).encode()
        self.rewrite(mutate)
        target = self.root / "restored"
        with self.assertRaisesRegex(ValueError, "full research backups"):
            snapshot.restore_snapshot(self.archive, target)
        self.assert_no_restored_state(target)

    def test_manifest_cannot_authorize_generic_transcript_files(self):
        snapshot.create_snapshot(self.data, self.archive)
        self.rewrite(lambda files: self.reseal_member(files, "research-data/workspaces/conversation.json", b"private chat"))
        target = self.root / "restored"
        with self.assertRaisesRegex(ValueError, "Unexpected research data path"):
            snapshot.restore_snapshot(self.archive, target)
        self.assert_no_restored_state(target)


if __name__ == "__main__":
    unittest.main()
