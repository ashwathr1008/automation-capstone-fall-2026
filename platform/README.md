# LanM Research

A local research workspace for lanmodulin-based rare-earth separation. It combines conversation, project records, a shared candidate library, experimental records, and inspectable economic calculations. The starter package supplies 616 candidates, 14 source records, shared contexts/assertions/formulas, and two custom calculation methods. The application includes 22 supporting evidence files.

The platform currently uses a simplified separation unit. It can explore candidate-specific scenarios when process measurements are missing. A protein's screening profile does not supply its recovery, capacity, or useful lifetime.

## Open the application

For a fresh clone, follow the [setup instructions](../README.md) to restore the starter database and methods. The first launch creates a fresh exploration project. From `platform/`, double-click **Launch LanM Research.cmd**, or run:

```powershell
python launch.py --open-browser
```

Open http://127.0.0.1:8765. Python 3.11 or newer is required. The application uses the Python standard library and a browser interface. Keep the server running while using the browser. Ctrl+C stops a foreground server.

Conversation uses the installed Codex runtime and its existing sign-in. The launcher finds Codex on PATH or in the VS Code extension. If needed, set `LANM_CODEX_BINARY` to its executable. Calculations, evidence, and project editing also work without a model connection. Sol is the default model. Astra is available in the conversation selector on the verified local account.

## Try these questions

- “Of the lanmodulins we haven't tested in this project, which are worth investigating for Nd versus La? Explain the evidence and uncertainties.”
- “Use 80 cycles as a conservative lifetime assumption, save the reason, and recalculate. What changed?”
- “Which candidates with explicitly accepted results meet our requirements for the next scale experiment?”
- In **Build methods**: “Build a reusable separation-cost model for a Dy-focused process with explicit output, reuse, chemical, labor, and equipment assumptions. Include units and hand-calculated reference cases.”
- Back in **Research**: “Use the registered method with these new inputs and save the comparison.”
- “Search PubMed for lanmodulin column separation and reuse. Save five relevant abstracts, explain what they establish, and identify what requires the full paper.”
- “Use the LanM handbook to explain what evidence we need before treating a screening candidate as a scale-up candidate.”
- “Export the next six recommended untested candidates as a serial-dilution CSV.”
- “For this comparison, leave out the first candidate. Save the next four as our testing selection without changing the project's assumptions.” Then: “Export those four candidates.”

## Choose Research or Build methods

Use **Research** for scientific discussion, inspecting sources, comparing candidates, and running existing calculations. It can save requested project changes, including assumption revisions, sources, testing selections, and predictions. Experiment acceptance still requires an explicit instruction. Research does not expose the tools that create method drafts, check drafts, or register new methods.

Use **Build methods** when you want to create or revise a reusable calculation. It retains the research operations and adds the draft, check, and register tools. A method declares its calculation boundary, inputs and units, assumptions, references, and independently stated reference examples. Ask the agent to explain which equations or values come from sources and which are assumptions or reasoned choices. You can inspect the source, documentation, and recorded checks under **Models & methods**.

Generated methods use a restricted numerical Python environment with `math` and `statistics`, and run in a separate process with a timeout. They cannot use arbitrary packages, network requests, or file access. Passing reference checks allows a content-identified version to be registered for reuse; it establishes numerical agreement with those examples, not scientific validity. Revising the method produces a new checked version while earlier registered versions and saved results remain available.

Both modes use the same saved project records. Research keeps method-authoring tools unavailable while you work with existing analyses; Build enables authoring when it is needed. The mode selector is separate from the language-model selector. No speed or scientific-quality advantage has been established for either mode.

## Work in a project

Each project you create has a target REE, a comparison REE, feed/support conditions, assumptions, conversation, sources, experiments, and calculation history. Changing an assumption creates a revision with a reason. Earlier calculations retain their inputs and show when project inputs have changed.

Experiments start as drafts. Explicit acceptance changes a candidate's project status. Acceptance records the user's review decision. It does not independently verify the measurement. Published screening records and literature excerpts remain distinct from accepted project experiments.

The starter shared library contains **616 candidate records** and **14 source records**, with contexts, assertions, formulas, replicate observations, and source locators. Additional sources and reviewed results can be shared explicitly. The associated publication reports 621 candidates; analyses use the 616 available imported records.

Untested ranking uses target-minus-comparison normalized screening contrast across the entire eligible pool. Close scores need scientific interpretation. Updated ranking requires accepted, applicable collected-output, recovery, purity, complete-cycle-time, and observed-cycle data. It applies the project's declared purity, recovery, and cost requirements. Support, feed, target, and specified pH/temperature must match. Observed cycles do not establish maximum useful lifetime. Missing evidence can leave a candidate unranked.

Source text can be pasted into **Evidence** or saved through the conversation. Processed numerical experiment results can be entered through a candidate's record. General raw instrument-file parsing is not implemented.

Clicking a citation opens an evidence preview inside the application. Archived PDFs and images display inline, and verified source text is searchable in the same panel. **Download file** is a separate action. Links without a saved copy show the source website and an explanation of what is available. Spreadsheets, notebooks, and historical JSON files require an explicit download unless archived text is available. The preview reads retained local evidence and does not fetch new websites automatically.

**Search PubMed** in Evidence retrieves citations and available abstracts from NCBI. The conversation has the same search and PMID-retrieval tools. Results retain identifiers, publication types, indexing notices, retrieval provenance, and source hashes. Search history records the query and saved sources. Repeated retrieval of unchanged content reuses the source. A changed abstract becomes a new source. These records do not change assumptions or accepted experiments, and the preview labels them as abstracts. PubMed coverage is incomplete for REE engineering. Optional `NCBI_EMAIL` and `NCBI_API_KEY` environment variables are supported; neither is inferred from personal files or stored in source provenance.

The **LanM handbook** contains seven short sections on interpreting evidence, compatible conditions, experiments, economics, citations, and method checks. The agent receives relevant section summaries and can read sections on demand. This is an original, source-linked synthesis awaiting independent scientific review. It does not supply missing candidate measurements.

## Share evidence between projects

Sources and experimental records added to a project remain associated with that project. To make a source or an accepted experimental result available to other projects in the same workspace, explicitly ask the conversation to share it in the shared library and give the reason. For example: “Share this source in the shared library, linked to this candidate, because it documents the published reuse evidence.” An experimental result must already be accepted before it can be shared.

The agent previews the selected record, then saves an immutable shared copy with its origin, content, and sharing reason. A source can be linked to an existing candidate. Abstracts retain their abstract designation. Shared experimental results retain their conditions and their original review status, but sharing does not accept them as experiments in other projects or mark those projects' candidates tested. The operation does not create candidates or overwrite published screening profiles.

In **Evidence**, these cards are labeled **Shared evidence**. Open a card to inspect the originating project and record, linked candidate where present, and sharing reason and date. A revised item includes a **Previous shared version** link. Sharing is requested through the conversation; existing evidence preview, search, and download controls remain available.

To correct a shared item, create a new shared revision that identifies the earlier item it supersedes and records the reason. The earlier copy remains available so its provenance is preserved. Sharing makes evidence visible across projects in this workspace; distributing it to another installation requires refreshing and transferring the starter package as described below.

The agent operations are `preview_shared_evidence` and `promote_shared_evidence`. The preview returns the exact content and provenance to be shared; promotion requires that preview's content hash and a reason. This guards against copying a record that changed after it was inspected.

## Testing CSV handoff

Ask the conversation to export **1–8 candidates**, or use **Candidates → Testing batches → Create testing CSV**. The count must be supplied by the user. Each saved batch assigns candidates to **A1 through H1**, the first column of a 96-well plate. Too many candidates, duplicate selections, or insufficient eligible candidates produce an explicit error.

The MVP generates **whole-number stock-solution volumes from 35–250 µL**, written as `uL` in the CSV. Each value is the simulated volume of stock solution to dispense into that candidate's starting well before serial dilution. To narrow the range, supply `stock_volume_min_ul` and `stock_volume_max_ul` together, within 35–250 µL, in the conversation or form. Custom ranges support decimal volumes and use random values rounded to six significant digits; the exact default profile uses whole numbers. Generated values and plate assignments are saved once, so downloading a batch again produces the same CSV.

The receiving automation adds **the same fixed volume of water to every starting well**, independently of each stock volume. The water amount remains to be configured there: this is a constant addition, rather than matching each stock volume or topping each well up to a common total. Before dispensing, the automation must check **stock volume + water volume** against the selected plate's working-volume limit. The 96-well format alone does not specify that limit.

You can discuss changes before exporting. A hypothetical comparison uses temporary assumption/configuration overrides or candidate exclusions and saves its own ranking without committing project inputs. A testing selection preserves the exact ordered candidate IDs and the reason for inclusions or substitutions. Only candidates eligible in its ranking snapshot may be selected. The agent can retrieve this selection later and export it directly, including after a conversation restart. Untested screening priorities still use the declared metal-pair contrast; hypothetical lifetime changes do not alter that score. Existing accepted-evidence requirements still apply to economic ranking.

Saved batches retain the ranking/scenario, project revision, selection rationale, random seed, stock-volume range and exact values. A project change marks earlier selections and batches as historical. Creating a new batch from an outdated selection requires an explicit request to retain that historical snapshot or a new ranking; downloading an already saved batch remains available unchanged. Exporting does not mark a candidate tested or accept an experiment.

The UTF-8 CSV uses these columns:

```text
schema_version,batch_id,rank,candidate_id,candidate_name,plate_id,well,stock_volume,volume_unit,volume_basis,volume_location,water_addition_mode,recommendation_rank
```

`rank` is the order in this batch; `recommendation_rank` is the position in the source ranking, which can differ after a user-selected reordering. `volume_unit` is `uL`, `volume_basis` is `simulated`, `volume_location` is `starting_well`, and `water_addition_mode` is `constant_per_starting_well`. The current schema is `lanm_testing_batch_2`, with the saved profile `serial_dilution_mvp`. The saved batch includes `water_addition: {"mode": "constant_per_starting_well", "volume_ul": null, "configured_by": "receiving_automation"}` so an unspecified water amount stays explicit. CSV names beginning with spreadsheet formula characters receive a protective apostrophe; stable candidate IDs remain unchanged.

Previously saved `lanm_testing_batch_1` batches remain available as legacy concentration batches. Their previews and CSV downloads retain the original concentration fields, values and units.

The handoff supplies candidate identities, stock-solution volumes, destination wells and the constant-water rule. The receiving automation supplies sample locations, the fixed water volume, its dilution program and plate-reader settings. The platform does not execute that pipeline. The stored selection and versioned batch schema can support additional assay-specific exporters without tying recommendations to SpyCI-LAMBS.

Agent operations are `prioritize_candidates`, `save_testing_selection`, `create_testing_batch`, and list/read operations for selections and batches. The HTTP interface exposes project-scoped `/api/projects/{project_id}/testing-selections` and `/testing-batches` collections; download a saved batch at `/api/projects/{project_id}/testing-batches/{batch_id}/csv`.

## Economic model

The built-in method divides annual separation-unit costs by annual kilograms of **elemental target collected**. It includes material replacement, regeneration chemicals, electricity, allocated labor, annualized installed equipment, and maintenance. It reports required material inventory, cost components, specification checks, and conditional break-even lifetime. Conversation tools can save sensitivity sweeps without changing the underlying measurements or assumptions.

The boundary starts at a suitable pretreated aqueous feed and ends at an enriched collected solution. Mining, leaching, downstream refining, full plant financing, protein manufacturing design, and column transport are outside this first model. Waste treatment must be explicitly included in an input to be represented. The installed-equipment input must match the evaluated scale. Larger equipment does not automatically retain laboratory performance.

Default values are illustrative scenarios. Changing a target element alone does not establish its feed chemistry, product specification, or process performance. Conditional separation cost is not whole-plant profitability. Sensitivity sweeps are scenarios rather than statistical confidence intervals.

**Models & methods → Add scale-up prediction** records a researcher's predictions for a specified larger-column configuration. Supply the intended **total operating bed volume**, optional candidate, scale/feed/support/flow context, and basis. Predicted collected output, full cycle time, useful lifetime, production, installed equipment cost, labor hours and labor rate must be entered explicitly. Other economic assumptions can be reviewed and revised in the form. Optional purity, recovery and feed inputs remain unknown unless supplied. The conversation supports the same save/read/calculate operations and must ask for missing predictions rather than invent them.

A prediction retains its own immutable input snapshot. It inherits shared scenario assumptions only, with no automatic transfer of candidate overrides or accepted small-column measurements. Saving or calculating it does not change project assumptions, revisions, or accepted-result pools. **Calculate prediction** saves a conditional economic result and compares the required aggregate bed volume with the intended total volume; a difference over 5% is flagged for reconciliation. This is an arithmetic consistency check, not a transport, geometry or pressure-drop prediction. Equipment and labor costs are researcher-supplied for that configuration, with no automatic scaling curve. Create separate low/base/high records or a new record when the prediction changes.

## Files and storage

| Location | Contents |
| --- | --- |
| `platform/` | Application source, tests, browser interface, and documentation |
| `portable-data/research-snapshot.zip` | Compressed starter database and reusable custom methods |
| `platform/src/lanm_platform/data/source-evidence.zip` | The 22 supporting source documents, saved text, and provenance exports |
| `research-data/` | Working SQLite database, method drafts, and registered method versions |

Paths in the table are relative to the repository root. From a source checkout, data defaults to the `research-data/` folder beside `platform/`. Override it with `LANM_DATA_DIR` or `--data-dir PATH`. A package installation outside a checkout uses `%USERPROFILE%\ResearchData\LanMPlatform` by default. See the [root setup instructions](../README.md) to create a workspace.

The source evidence bundle preserves the referenced files' original paths and bytes. The application uses it automatically for verified source previews and downloads.

The starter package includes two reusable custom methods with drafts, registered versions, and numerical checks: `capture-cost` calculates simplified collected-target cost components; `separation_cost_output_lifetime_grid` compares costs across output and useful-lifetime assumptions. These complement the built-in separation-unit model. Open **Models & methods** to inspect their source, assumptions, inputs, and checks.

To refresh the shared library and tools, stop the application and run `python scripts/research_snapshot.py create` from the repository root, then commit and push the ZIP. The command exports the shared library tables and reusable method files into a starter package. See [package instructions](../portable-data/README.md) for restoration and alternate workspace locations.

## How the pieces fit

| File | Responsibility |
| --- | --- |
| `ui/` | Browser interface without a frontend framework |
| `core.py` | Scientific records, project revisions, candidate eligibility, saved runs |
| `evidence.py` | Citation matching and verified archived document previews |
| `pubmed.py` | Bounded NCBI search and abstract retrieval, with shared request pacing |
| `guidance.py`, `data/lanm_handbook.md` | Small section catalog and on-demand scientific guidance |
| `economics.py` | Independent separation-unit equations and sensitivity |
| `methods.py`, `method_worker.py` | Versioned numerical methods and checked execution |
| `mcp.py` | The scientific operations available to the agent |
| `runtime.py` | Persistent Codex conversations, streaming, cancellation |
| `server.py` | Local HTTP interface and API |
| `migration.py` | Exact candidate import and historical handoff |

The Python modules are under `src/lanm_platform/`. Numerical methods use a restricted Python subset with `math` and `statistics`, executed in a separate process with a timeout. This registry is not a general arbitrary-code hosting environment. Broader scientific packages can be added as reviewed tools when a concrete analysis needs them.

Codex supplies the model and agent runtime. This project's contribution is the LanM evidence structure, applicable-result rules, persistent assumptions, and reproducible calculations. The current checks establish specific software behavior. No controlled benchmark has established better scientific answers than a well-configured Codex, Claude, Biomni Lab, Elnora, or OpenScience setup.

Selected patterns from Biomni informed the guidance catalog, PubMed adapter, and evaluation cases; these were implemented independently. Upstream references are recorded in [NOTICE.md](NOTICE.md). The runtime uses the [Codex app-server interface](https://learn.chatgpt.com/docs/app-server). Model and tool settings follow the [official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

## Check or extend the application

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -p 'test_*.py' -v
```

Run these commands from `platform/`. Tests use temporary scientific state. `tests/live_check.py` is optional and makes real model requests only when explicitly run. Live model time varies with request, account, and service conditions.

The compact [scientific evaluation set](evaluations/README.md) covers evidence use and LanM decision-making. It runs in isolated temporary projects and separates automatic structural checks from a human scientific rubric. Model responses remain unreviewed until someone evaluates their scientific reasoning; completing a run does not establish superiority over another agent.

The private GitHub repository provides the application, starter library, reusable methods, and supporting evidence. The application and working database run locally on the computer that launches them. Shared hosting requires an authenticated deployment and an appropriate model-access arrangement.
