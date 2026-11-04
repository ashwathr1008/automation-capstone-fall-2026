# Automation Capstone Fall 2026

A local LanM research platform for exploring rare-earth separation with a shared scientific library and reusable calculation methods.

## Included

- The research application, browser interface, tests, and documentation.
- A starter SQLite database with **616 candidates**, **14 source records**, and shared contexts, assertions, and formulas.
- **22 supporting evidence files**, including original documents, saved text, and provenance exports.
- The built-in separation-unit cost model and sensitivity calculations.
- Two custom methods, with editable drafts, registered versions, and numerical reference checks: `capture-cost` and `separation_cost_output_lifetime_grid`.
- Tools for creating and restoring the shared library and methods package.

## Start a project

Install Python 3.11 or newer. From a fresh clone:

```powershell
git clone https://github.com/ashwathr1008/automation-capstone-fall-2026.git
cd automation-capstone-fall-2026
python scripts/research_snapshot.py restore
python platform/launch.py --open-browser
```

Restoring installs the starter database and custom methods. The first launch creates a fresh exploration project, ready for your research. The application uses the bundled source evidence automatically for verified previews and downloads.

On Windows, **Launch LanM Research.cmd** also opens the application. Keep the server window open while using http://127.0.0.1:8765; Ctrl+C stops it. Conversation features use the local Codex installation and its sign-in. See the [platform instructions](platform/README.md) for research features and runtime configuration.

To create a separate workspace, use `python scripts/research_snapshot.py restore --target-dir PATH_TO_EMPTY_FOLDER`, then launch with `python platform/launch.py --data-dir PATH_TO_EMPTY_FOLDER/research-data --open-browser`.

## Repository layout

| Path | Contents |
| --- | --- |
| `platform/` | Application source, tests, browser interface, and documentation |
| `platform/src/lanm_platform/data/` | Candidate library, LanM handbook, and supporting evidence bundle |
| `scripts/` | Shared-library export, restoration, evidence-bundle tools, and tests |
| `portable-data/research-snapshot.zip` | Compressed starter database and custom methods, with SHA-256 manifest |
| `research-data/` | Working database and methods created by restoration and used by the application |

## Refresh shared library and tools

Stop the application, then run from the repository root:

```powershell
python scripts/research_snapshot.py create
git add portable-data/research-snapshot.zip
git commit -m "Update shared library and tools"
git push
```

The export packages the shared candidate/source library and reusable method files as a starter workspace. It verifies the SQLite database and records file hashes. Creating, committing, and pushing a new package publishes an explicit update. [Package details](portable-data/README.md).

## Check the code

From the repository root, run the packaging tests:

```powershell
python -m unittest discover -s scripts/tests -p 'test_*.py' -v
```

Run the application tests from `platform/`:

```powershell
cd platform
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -p 'test_*.py' -v
```

The tests use temporary state. Optional live evaluations exercise the configured model runtime. The application runs locally on the computer that launches it.
