"""Create and restore a starter library and generated methods, without history.

Stop the application before creating a snapshot so its database and method files
represent the same moment. SQLite's backup API also includes committed WAL data.
Only shared library tables and generated method artifacts are exported. Projects,
conversations, experiments, runs, sources, and runtime state remain local.
Restoration never overwrites an existing research-data directory. This is not a
full research backup.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tempfile
import time
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / "portable-data" / "research-snapshot.zip"
DATABASE = "research-data/research.sqlite3"
MANIFEST = "manifest.json"
EXPORT_PROFILE = "starter-library-and-methods"
FORMAT_VERSION = 2
SHARED_TABLES = {"metadata", "candidates", "library_records"}
EMPTY_TABLES = {
    "projects", "revisions", "experiments", "runs", "messages", "sources",
    "literature_searches", "scale_predictions", "testing_selections",
    "testing_batches", "events", "sqlite_sequence",
}
METHOD_FILES = {"method.py", "manifest.json", "checks.json"}
SLIDE_EXTENSIONS = {".ppt", ".pptx", ".pptm", ".pps", ".ppsx", ".ppsm", ".pot", ".potx", ".potm", ".odp", ".key"}
EXCLUDED_PARTS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", "cache", "caches",
    "credentials", "secrets", ".aws", ".ssh", ".codex", ".runtime",
}
PRIVATE_NAMES = {"auth.json", "credentials.json", "secrets.json", "id_rsa", "id_ed25519", "runtime_threads.json"}
MAX_UNCOMPRESSED = 2 * 1024 ** 3
MAX_ARCHIVE = 100 * 1024 ** 2
MAX_FILES = 10000
CHUNK = 1024 * 1024


def _excluded(path: PurePosixPath) -> bool:
    parts = [part.lower() for part in path.parts]
    return (
        any(part in EXCLUDED_PARTS for part in parts)
        or any(re.search(r"slide|presentation|powerpoint|speaker[_ -]?notes", part) for part in parts)
        or any(part == ".env" or part.startswith(".env.") for part in parts)
        or parts[-1] in PRIVATE_NAMES
        or path.suffix.lower() in SLIDE_EXTENSIONS | {".log", ".pid", ".pyc", ".pyo", ".pem", ".p12", ".pfx"}
    )


def _safe_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name or "\\" in name or path.is_absolute()
        or name != path.as_posix() or len(path.parts) < 2
        or path.parts[0] != "research-data"
        or any(part in {".", ".."} or ":" in part or part.endswith((".", " ")) for part in path.parts)
        or any(re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part) for part in path.parts)
        or _excluded(path)
    ):
        raise ValueError(f"Unsafe or excluded archive member: {name!r}")
    if name != DATABASE and not _method_path(path):
        raise ValueError(f"Unexpected research data path: {name!r}")
    return path


def _method_path(path: PurePosixPath) -> bool:
    return (len(path.parts) == 5 and path.parts[:2] == ("research-data", "methods")
            and path.parts[2] in {"drafts", "versions"} and path.name in METHOD_FILES)


def _quick_check(database: Path) -> None:
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        rows = connection.execute("PRAGMA quick_check").fetchall()
    if rows != [("ok",)]:
        raise ValueError("SQLite integrity check failed")


def _check_schema(connection) -> None:
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if tables != SHARED_TABLES | EMPTY_TABLES:
        raise ValueError("Unrecognized database tables; review the starter export policy before sharing this database")
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type NOT IN ('table','index') LIMIT 1").fetchone():
        raise ValueError("Unexpected database views or triggers; starter export refused")


def _verify_starter(database: Path) -> dict:
    _quick_check(database)
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        _check_schema(connection)
        for table in sorted(EMPTY_TABLES):
            if connection.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone():
                raise ValueError(f"Starter database contains private or project history in {table}")
        if connection.execute("PRAGMA freelist_count").fetchone()[0] != 0:
            raise ValueError("Starter database has not been compacted after removing private history")
        return {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                for table in sorted(SHARED_TABLES)}


def _make_starter(database: Path) -> dict:
    """Remove private rows and their recoverable page contents from a copy only."""
    with closing(sqlite3.connect(database)) as connection:
        _check_schema(connection)
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute("PRAGMA foreign_keys=OFF")
        with connection:
            for table in sorted(EMPTY_TABLES):
                connection.execute(f'DELETE FROM "{table}"')
        # Rebuild the standalone database, removing free pages and unused cells.
        connection.execute("VACUUM")
    return _verify_starter(database)


def _backup_database(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"Database must be an existing regular file: {source}")
    started = time.monotonic()

    def progress(status, remaining, total):
        if time.monotonic() - started > 60:
            raise ValueError("Database backup timed out; stop the application and retry")

    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(destination)) as snapshot:
            original.backup(snapshot, pages=256, progress=progress)
    _quick_check(destination)


def _source_files(data_dir: Path):
    methods = data_dir / "methods"
    if methods.is_symlink():
        raise ValueError(f"Refusing symlinked methods directory: {methods}")
    for category in ("drafts", "versions"):
        directory = methods / category
        if not directory.exists():
            continue
        if directory.is_symlink():
            raise ValueError(f"Refusing symlinked data directory: {directory}")
        for method in sorted(directory.iterdir()):
            if method.is_symlink():
                raise ValueError(f"Refusing symlinked method directory: {method}")
            if not method.is_dir():
                continue
            for filename in sorted(METHOD_FILES):
                file = method / filename
                relative = PurePosixPath("research-data", *file.relative_to(data_dir).parts)
                if _excluded(relative):
                    continue
                if file.is_symlink():
                    raise ValueError(f"Refusing symlinked method artifact: {file}")
                if file.is_file():
                    yield relative.as_posix(), file


def create_snapshot(data_dir: Path, output: Path) -> dict:
    data_dir = data_dir.resolve()
    output = output.resolve()
    if output == data_dir or data_dir in output.parents:
        raise ValueError("Snapshot output must be outside the live research-data directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".research-snapshot-", dir=output.parent) as temporary:
        temporary = Path(temporary)
        database = temporary / "research.sqlite3"
        _backup_database(data_dir / "research.sqlite3", database)
        shared_rows = _make_starter(database)
        files = [(DATABASE, database), *_source_files(data_dir)]
        if len(files) > MAX_FILES or sum(file.stat().st_size for _, file in files) > MAX_UNCOMPRESSED:
            raise ValueError("Snapshot exceeds the supported file count or uncompressed size")
        manifest = {"format": "lanm-research-snapshot", "version": FORMAT_VERSION,
                    "export_profile": EXPORT_PROFILE, "shared_table_rows": shared_rows, "files": {}}
        staged = temporary / "snapshot.zip"
        with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, file in sorted(files):
                _safe_member(name)
                digest = hashlib.sha256()
                size = 0
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                with file.open("rb") as original, archive.open(info, "w") as member:
                    while block := original.read(CHUNK):
                        member.write(block)
                        digest.update(block)
                        size += len(block)
                manifest["files"][name] = {"size": size, "sha256": digest.hexdigest()}
            archive.writestr(MANIFEST, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        if staged.stat().st_size >= MAX_ARCHIVE:
            raise ValueError("Compressed snapshot reaches GitHub's 100 MiB file limit; use a release asset or external data storage")
        size = staged.stat().st_size
        os.replace(staged, output)
    return {"archive": str(output), "files": len(files), "bytes": size,
            "export_profile": EXPORT_PROFILE, "shared_table_rows": shared_rows}


def restore_snapshot(archive_path: Path, target_dir: Path) -> dict:
    target_dir = target_dir.resolve()
    destination = target_dir / "research-data"
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"Refusing to overwrite existing research data: {destination}. Restore to an empty location instead.")
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        names = [item.filename for item in members]
        if len(names) > MAX_FILES + 1 or len(names) != len(set(name.casefold() for name in names)):
            raise ValueError("Archive has too many files or duplicate member names")
        if names.count(MANIFEST) != 1 or DATABASE not in names:
            raise ValueError("Archive must contain one manifest and a research database")
        if sum(item.file_size for item in members) > MAX_UNCOMPRESSED:
            raise ValueError("Archive exceeds the supported uncompressed size")
        if archive.getinfo(MANIFEST).file_size > 4 * 1024 ** 2:
            raise ValueError("Archive manifest is too large")
        manifest = json.loads(archive.read(MANIFEST))
        if (not isinstance(manifest, dict) or manifest.get("format") != "lanm-research-snapshot"
                or manifest.get("version") != FORMAT_VERSION or manifest.get("export_profile") != EXPORT_PROFILE):
            raise ValueError("Not a supported starter snapshot; full research backups cannot be restored as starter data")
        records = manifest.get("files")
        if not isinstance(records, dict) or set(records) != set(names) - {MANIFEST}:
            raise ValueError("Manifest does not exactly match the archive contents")
        for member in members:
            mode = member.external_attr >> 16
            if member.is_dir() or (mode & 0o170000) not in {0, 0o100000}:
                raise ValueError(f"Archive member is not a regular file: {member.filename!r}")
            if member.filename == MANIFEST:
                continue
            _safe_member(member.filename)
            record = records[member.filename]
            if not isinstance(record, dict) or record.get("size") != member.file_size or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", ""))):
                raise ValueError(f"Invalid manifest record: {member.filename!r}")
        target_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".research-restore-", dir=target_dir) as temporary:
            temporary = Path(temporary)
            for name, record in records.items():
                path = temporary.joinpath(*PurePosixPath(name).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with archive.open(name) as source, path.open("xb") as output:
                    while block := source.read(CHUNK):
                        digest.update(block)
                        output.write(block)
                if digest.hexdigest() != record["sha256"]:
                    raise ValueError(f"Checksum mismatch: {name!r}")
            shared_rows = _verify_starter(temporary / DATABASE)
            if shared_rows != manifest.get("shared_table_rows"):
                raise ValueError("Starter database row counts do not match the manifest")
            # Install only after every member and the database have been verified.
            if destination.exists() or destination.is_symlink():
                raise ValueError(f"Research data appeared during restore; refusing to overwrite: {destination}")
            os.rename(temporary / "research-data", destination)
    return {"restored": str(destination), "files": len(records),
            "export_profile": EXPORT_PROFILE, "shared_table_rows": shared_rows}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Export shared library and generated methods without project history; stop the application first")
    create.add_argument("--data-dir", type=Path, default=ROOT / "research-data")
    create.add_argument("--output", type=Path, default=DEFAULT_ARCHIVE)
    restore = commands.add_parser("restore", help="Verify and restore into a location with no research-data directory")
    restore.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    restore.add_argument("--target-dir", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        result = create_snapshot(args.data_dir, args.output) if args.command == "create" else restore_snapshot(args.archive, args.target_dir)
    except (OSError, ValueError, sqlite3.Error, zipfile.BadZipFile, RuntimeError) as error:
        parser.exit(1, f"Snapshot failed: {error}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
