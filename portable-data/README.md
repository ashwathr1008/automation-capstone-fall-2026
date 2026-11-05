# Shared library and methods package

`research-snapshot.zip` provides a starter SQLite database and reusable calculation methods for a new research workspace. The database contains **616 candidates**, **14 source records**, and shared contexts, assertions, and formulas. The package also contains editable drafts and registered versions of two custom methods: `capture-cost` and `separation_cost_output_lifetime_grid`, with their numerical reference checks.

A manifest records each file's size and SHA-256 hash. The application supplies the built-in separation-unit cost model and uses the **22 supporting evidence files** in `platform/src/lanm_platform/data/source-evidence.zip` for verified source previews and downloads.

## Create a workspace

From a fresh clone's root, before launching the application:

```powershell
python scripts/research_snapshot.py restore
python platform/launch.py --open-browser
```

Restoration verifies archive paths, file hashes, and SQLite integrity, then installs the starter database and methods in `research-data/`. The first launch creates a fresh exploration project.

To create a separate workspace:

```powershell
python scripts/research_snapshot.py restore --target-dir PATH_TO_EMPTY_FOLDER
python platform/launch.py --data-dir PATH_TO_EMPTY_FOLDER/research-data --open-browser
```

## Refresh shared library and tools

Project sources and experiments can first be promoted explicitly to the shared library through LanM Research. Sharing creates an immutable copy with provenance and a reason; experimental results must already be accepted. Shared copies are available to other projects using that working database. They do not become accepted experiments in those projects, and they do not overwrite candidate screening records. Corrections create a new shared revision referencing the earlier copy.

Refreshing the starter package is the separate step that distributes shared records and reusable methods to another installation. Export includes explicitly shared source text and experimental-result snapshots; ordinary project sources, conversations, assumptions, and experiments stay in their project. It is a snapshot for creating a workspace, not automatic synchronization between running installations.

Stop the application, then run from the repository root:

```powershell
python scripts/research_snapshot.py create
git add portable-data/research-snapshot.zip
git commit -m "Update shared library and tools"
git push
```

Creation exports the shared library tables and reusable method files into a starter package, verifies the prepared database, and writes the compressed ZIP with a new manifest. Commit and push the ZIP to publish the update.

For another working-data location, use `create --data-dir PATH`; `--output PATH` selects a different ZIP destination. Restore accepts `--archive PATH` to read another package.
