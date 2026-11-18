# Aldair's LanM Research platform setup and presentation walkthrough

Prepared November 9, 2026. This guide installs **the LanM Research platform from its GitHub repository**, prepares your own demonstration records, and walks through the presentation demo.

The demo follows the existing `LanM_Demo_Walkthrough_2026-11-05.docx`: inspect candidate evidence, create a six-candidate testing CSV, and inspect and reuse the registered `capture-cost` method. Its prompts, speaking cues, and recovery routes are included here so you can use this file on its own.

**Repository:** <https://github.com/ashwathr1008/automation-capstone-fall-2026>

**Application address after launch:** <http://127.0.0.1:8765>

**Main setup path:** Windows with PowerShell. Complete installation and rehearsal before presenting; the timed demonstration itself is five minutes.

## Contents

1. [What you are installing](#1-what-you-are-installing)
2. [Hardware, software, and access](#2-hardware-software-and-access)
3. [Download and initialize the platform](#3-download-and-initialize-the-platform)
4. [Set up the conversation runtime](#4-set-up-the-conversation-runtime)
5. [Launch and check the installation](#5-launch-and-check-the-installation)
6. [Prepare your presentation project](#6-prepare-your-presentation-project)
7. [Deliver the five-minute demo](#7-deliver-the-five-minute-demo)
8. [Optional demonstrations and prompts](#8-optional-demonstrations-and-prompts)
9. [Troubleshooting and presentation fallbacks](#9-troubleshooting-and-presentation-fallbacks)
10. [Restarting, backing up, and updating](#10-restarting-backing-up-and-updating)
11. [Final rehearsal checklist](#11-final-rehearsal-checklist)

## 1. What you are installing

LanM Research is a local browser application for working with lanmodulin candidate evidence, project records, testing selections, and numerical analyses. Python runs its local server and SQLite database. You interact with it through your browser. Codex supplies the conversation and method-authoring runtime using your own signed-in account.

| Part | What it does | Where it runs |
| --- | --- | --- |
| Browser interface | Conversation, candidates, evidence, calculations, and saved records | Your computer |
| Python server and SQLite database | Store projects and run platform operations | Your computer |
| Built-in and registered numerical methods | Perform calculations with saved inputs and versions | Your computer |
| Codex runtime | Connect the conversational model to the platform's tools | Local runtime with online model access |
| PubMed search | Retrieve citations and available abstracts | Online NCBI service; retrieved records are saved locally |

After restoring the starter package, you get:

- 616 candidate records and 14 source records, with shared scientific context.
- 22 supporting evidence files for retained previews and downloads.
- The built-in separation-unit economics model.
- Two reusable custom methods, including drafts, registered versions, and numerical checks: `capture-cost` and `separation_cost_output_lifetime_grid`.

**You do not receive Ashwath's personal rehearsal projects, conversations, saved runs, or testing batches.** First launch creates a fresh **Lanmodulin exploration** project. Section 6 creates your own rehearsal artifacts. The Word walkthrough and slide deck are local presentation assets and are not required to run this tutorial.

## 2. Hardware, software, and access

### Computer and presentation equipment

The repository does not specify benchmarked minimum CPU, RAM, or disk requirements. These are practical planning targets for running the application, a browser, and presentation software together; they are not measured performance guarantees.

| Item | Practical setup for Aldair |
| --- | --- |
| Computer | A Windows 11 laptop or desktop; a 64-bit x86 machine matches the repository's Windows Codex-extension discovery path |
| CPU | A recent general-purpose laptop/desktop CPU; four or more cores is a reasonable planning target |
| RAM | Aim for at least 8 GB; 16 GB gives more room for browser tabs, slides, and screen sharing |
| Free storage | Reserve at least 2 GB for the checkout, working data, exports, and some backups; allow additional room for Python, Codex, and future evidence |
| GPU | A dedicated GPU is not required by the platform; this setup does not download and run model weights locally |
| Display | A readable browser window; 1920 × 1080 is convenient for presentation. Adjust zoom before sharing |
| Network | Internet for the initial download, Codex sign-in/model requests, and fresh PubMed searches |
| Presentation equipment | Power adapter and the appropriate display adapter, or a tested screen-sharing application |

**No laboratory hardware is required for this software demo.** A robot, liquid handler, plate reader, protein samples, and a physical separation column are not part of installation. The demo exports a file for a separate experimental workflow; it does not operate that equipment.

### Software and accounts

| Requirement | Purpose / check |
| --- | --- |
| Python **3.11 or newer** | Runs the application. Check with `python --version`; Python 3.12 is used in the current development environment |
| Modern browser | Opens the local interface and evidence previews |
| Git, if cloning | Downloads and updates the repository. Check with `git --version`. Download ZIP is an alternative |
| Repository access | Sign in to GitHub with an account that can open the repository; request access from Ashwath if needed |
| Codex executable | Required for live conversation and Build methods; the platform must be able to launch it |
| Your own Codex sign-in and model access | Required for successful model requests; repository access does not grant model access |
| Text editor or spreadsheet viewer | Convenient for opening the downloaded CSV; a text editor is sufficient |

If Python is missing, install a supported version from the [official Python Windows downloads page](https://www.python.org/downloads/windows/), enable the installer option to make Python available on PATH when offered, and reopen PowerShell. If `python` is unavailable but `py -3 --version` shows 3.11 or newer, substitute `py -3` for `python` in this guide.

The application has **no third-party Python runtime dependencies**. Running from the checkout does not require `pip install`, a virtual environment, Docker, a separate database server, or a frontend build. Presentation-generation dependencies are only needed to rebuild slides/documents, not to run the platform.

## 3. Download and initialize the platform

### Step 1 — Get the repository onto your computer

In PowerShell, move to the folder where you want to keep the platform. Clone it and enter the resulting directory:

```powershell
git clone https://github.com/ashwathr1008/automation-capstone-fall-2026.git
cd automation-capstone-fall-2026
```

Complete GitHub authentication if prompted. If the repository cannot be found, first check that you can open its page in a browser while signed in to the correct account.

**Alternative without Git:** Open the repository page, choose **Code → Download ZIP**, and extract the entire ZIP. Open PowerShell in the extracted folder containing `README.md`, `platform`, `scripts`, and `portable-data`. Do not launch files from inside the compressed ZIP. The remaining Python commands are the same; Git update commands later in this guide apply only to a clone.

From this point, run commands from the **repository root**, the folder containing this guide. Verify the essential files:

```powershell
python --version
Test-Path .\platform\launch.py
Test-Path .\scripts\research_snapshot.py
Test-Path .\portable-data\research-snapshot.zip
Test-Path .\platform\src\lanm_platform\data\source-evidence.zip
```

All four `Test-Path` commands should print `True`.

### Step 2 — Restore the supplied library and methods

**Do this before the first launch.** The server can initialize a workspace on its own, but that does not restore the custom methods supplied in the starter snapshot.

```powershell
python scripts/research_snapshot.py restore
```

Successful output is JSON with a `restored` path ending in `research-data`, an export profile, file count, and shared-table row counts. Restoration checks archive paths, file hashes, and database integrity before installing the data.

This creates the working `research-data` directory beside `platform`. You do not need to manually unzip the snapshot, edit SQLite, or import the evidence ZIP.

Restore is a **one-time initialization step**, not a command to run each time you start the app. If it says `Refusing to overwrite existing research data`, use the existing workspace or the separate-workspace instructions in Section 9. Do not delete an existing workspace to get past that message.

## 4. Set up the conversation runtime

The local interface, evidence, CSV controls, and saved-method calculations work without a model connection. To demonstrate live conversation or build a method, install and sign in to Codex on the same computer and in the same Windows environment as Python.

### Step 3 — Make Codex available

If you already have Codex, check it first:

```powershell
codex --version
```

If it is missing, use the Windows installation option in the [official Codex CLI guide](https://learn.chatgpt.com/docs/codex/cli). The official standalone Windows installer can be run in PowerShell:

```powershell
irm https://chatgpt.com/codex/install.ps1 | iex
```

This downloads and executes OpenAI's installer. Follow its prompts, then reopen PowerShell and return to the repository folder. The documented default Windows installation directory is `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin`. See the [official installer configuration documentation](https://learn.chatgpt.com/docs/config-file/environment-variables).

```powershell
codex --version
Get-Command codex
```

You can also use an existing Codex installation from the VS Code extension. The platform checks, in order:

1. The executable path in `LANM_CODEX_BINARY`, if set.
2. `codex` on PATH.
3. A Windows x86-64 Codex executable under your VS Code `openai.chatgpt-*` extension folders.

### Step 4 — Sign in and verify access

```powershell
codex login
codex login status
```

Complete browser sign-in with your own account. `codex login status` should report a signed-in authentication method. See the [official authentication guide](https://learn.chatgpt.com/docs/auth?surface=cli) for account restrictions and sign-in options. Access and usage limits depend on your account and workspace; the repository does not include credentials or a subscription.

If the runtime is installed but not found, set its exact executable path in the PowerShell window you will use to launch the platform. For a default standalone install:

```powershell
$env:LANM_CODEX_BINARY = Join-Path $env:LOCALAPPDATA 'Programs\OpenAI\Codex\bin\codex.exe'
Test-Path $env:LANM_CODEX_BINARY
& $env:LANM_CODEX_BINARY --version
& $env:LANM_CODEX_BINARY login status
```

Proceed only if the path exists. If you used another installation location, replace the value with that installation's actual `codex.exe` path. Use the same executable for sign-in and for the platform.

If that executable reports that you are signed out, sign in through its explicit path, then check again:

```powershell
& $env:LANM_CODEX_BINARY login
& $env:LANM_CODEX_BINARY login status
```

PowerShell `$env:` assignments apply to that window and processes started from it. Launch Python from that window; a separately double-clicked launcher will not inherit those temporary settings. Stop and restart the platform after changing runtime settings.

The repository defaults to `gpt-6.1-sol` and displays **Sol** and **Astra** in its selector. Those labels are configured by the application, not an account-entitlement check. Select a model that your account can use. If a different model ID is required, set `LANM_MODEL` to an ID verified with your account before launching.

## 5. Launch and check the installation

### Step 5 — Start the server

From the repository root:

```powershell
python platform/launch.py --open-browser
```

The terminal should print a LanM Research startup line with `http://127.0.0.1:8765` and the path to your research data. Your browser should open automatically. If it does not, enter that address manually.

**Keep the terminal open while using the platform.** Press **Ctrl+C** in that terminal to stop the server when finished. Closing the browser does not stop it. The address refers to the computer running the application; it is not a hosted site another computer can access.

After the initial restore, Windows users can also double-click **Launch LanM Research.cmd** in the repository root. Use the PowerShell command when you need custom environment variables or a custom data directory.

### Step 6 — Check the first-run state

| Check | Expected result |
| --- | --- |
| Project sidebar | A fresh **Lanmodulin exploration** project |
| Candidate library | 616 imported records; the visible list may be limited |
| Search `o-36` | **Melba-LanM**, candidate ID `o-36` |
| Evidence | Imported sources, including **A family portrait of lanmodulin selectivity for enhanced rare-earth separations**, or its PMC HTML version |
| Evidence preview | Retained content opens; views depend on the archived file type |
| Models & methods → Method registry | Built-in economics plus registered `capture-cost` and `separation_cost_output_lifetime_grid`; drafts may also appear |
| `capture-cost` version | Registered version **1166a29646c9** in the supplied package |
| Experiments / saved runs / testing batches | No personal rehearsal records yet |

**Agent available** means an executable was found. It does not prove authentication, network connectivity, or model access. In **Conversation**, select **Research** and send:

> Read this project's name, target and comparison elements, and accepted-experiment count. Report them without changing any project records.

A completed reply using the platform's records is the end-to-end conversation check. Resolve errors before relying on live prompts. The platform starts its Codex connection when a conversation begins; you do not need to start `codex app-server` manually.

## 6. Prepare your presentation project

The original walkthrough referred to records already saved on Ashwath's machine. Create them on yours using these steps. Each action that saves a selection, batch, or calculation creates a real local record.

### Step 7 — Create an illustrative rehearsal project

1. Click the **+** beside **PROJECTS** in the left sidebar.
2. Enter **Rehearsal: Nd scenario (illustrative)** as the project name.
3. Set **Target REE = Nd** and **Comparison REE = La**.
4. For context, enter: `Presentation rehearsal. Illustrative accounting scenarios; no laboratory measurements are being entered.`
5. Click **Create project** and select it in the sidebar.
6. Leave feed/support conditions unspecified unless you have a real basis for them. Do not enter or accept fictional experimental results.
7. Select **Research** for the conversation workflow.

The new project starts with default assumptions, including 100 useful cycles. You do not need to recreate the 120-cycle state described in older speaking notes: the five-minute walkthrough uses explicit `capture-cost` arguments and does not depend on that older scenario.

### Step 8 — Rehearse the candidate and evidence clicks

1. Open **Candidate library**, leave **All candidates** selected, and search for `o-36`.
2. Open the **Melba-LanM** row. Find **Published screening profile**, candidate identity, accession, and the metal-response bars.
3. Close the inspector with **×**.
4. Open **Evidence** and the source card **A family portrait of lanmodulin selectivity for enhanced rare-earth separations**, or its PMC HTML version.
5. Find a readable archived view. Use **Source text** or **Read archived text** when available. Test this before screen sharing.

The candidate inspector's **Source references** list contains raw IDs; open source cards from **Evidence**. A source download is a separate action from viewing it.

**Scientific point to retain:** o-36's published process example concerns **Pr/La**, while this rehearsal project uses **Nd/La**. Here o-36 demonstrates inspecting evidence. It is not being presented as the best Nd/La candidate.

Optional rehearsal **Prompt A — Research**:

> Inspect LanM candidate o-36. Read its saved screening record and available published evidence. Explain what the evidence establishes about Pr/La separation, identify the tested conditions, and distinguish that evidence from accepted experiments in this project. Cite the source records you actually inspect and list the most important missing measurements for evaluating a separation process.

Keep the resulting citations available as a fallback. Review whether the answer inspected actual sources and separated published evidence from accepted project experiments.

### Step 9 — Save the six-candidate selection and CSV

In **Conversation → Research**, paste **Prompt B** and click **Send**:

> Using this project's target and comparison elements, rank six project-untested LanM candidates with the existing screening method. Explain the ranking basis and its limitations. Save the top six as our testing selection, then export their testing CSV using the default simulated stock-solution volumes. Give me the download link and explain the CSV fields. Do not change project assumptions or create experimental results. If fewer than six candidates qualify, report the shortfall instead of substituting other candidates.

After it completes:

1. Review the ranking basis and six candidates. The untested comparison uses target-minus-comparison normalized screening contrast across the eligible pool; it is a screening priority, not a measured process-cost ranking.
2. Click **Saved testing batches** in the Conversation right rail, or open **Candidate library** and scroll to **Testing batches**.
3. Find the **6 candidates · A1–F1** batch and click **Preview**.
4. Show **Well**, **Candidate**, **Stock-solution volume**, and **Saved selection and assumptions**.
5. Click **Download CSV** and open it in a text editor or spreadsheet viewer. Keep it available for the live demo.

If the agent saved a selection but omitted the export, use **Candidate library → Create testing CSV**. Under **Candidate selection**, choose **Saved selection · [date] · 6 candidates**. Enter **6** for count, **35** for minimum stock volume, and **250** for maximum stock volume. Click **Create saved CSV**, then **Download CSV**.

Choosing **Current untested ranking** creates a new ranking basis instead of necessarily preserving the conversational shortlist. If no selection exists and you need a direct-control fallback, that option is appropriate; describe it as a direct export.

#### What the CSV actually contains

```text
schema_version,batch_id,rank,candidate_id,candidate_name,plate_id,well,stock_volume,volume_unit,volume_basis,volume_location,water_addition_mode,recommendation_rank
```

| Field or property | Meaning in this demo |
| --- | --- |
| `schema_version` | `lanm_testing_batch_2` |
| `candidate_id`, `candidate_name` | Stable identity and readable label |
| `well` | A1–F1 for six candidates: the first column of a 96-well plate |
| `stock_volume`, `volume_unit` | Simulated stock-solution volume in `uL`; defaults are whole numbers from 35 to 250 |
| `volume_basis`, `volume_location` | `simulated`, `starting_well` |
| `water_addition_mode` | `constant_per_starting_well`; the fixed water volume is configured downstream |
| `rank`, `recommendation_rank` | Position in the saved batch and source ranking; these can differ for a reordered selection |

These are **software-demo stock volumes**, not measured concentrations or an optimized assay. The receiving automation supplies stock/sample locations, the same fixed water addition for each starting well, the dilution program, and plate-reader settings. It must check combined stock plus water against the actual plate's working-volume limit.

Exporting does not execute the pipeline, mark candidates tested, or accept experiments. A new batch can have different simulated volumes. Downloading the same saved batch again preserves its original values.

### Step 10 — Inspect the registered method

1. Open **Models & methods**.
2. Under **Method registry**, choose `capture-cost` marked **Registered**, version **1166a29646c9**. Avoid a similarly named draft.
3. Inspect **Recorded check results**.
4. Expand **Complete method manifest** and find its boundary, assumptions, inputs, and references. Open **Method source** if useful.
5. Close the inspector.

Explain that registration preserves an inspectable method version, and its example checks establish numerical behavior. They do not establish physical performance or scientific validity for every candidate.

### Step 11 — Save both accounting scenarios

In **Models & methods → Use a saved method**, choose **capture-cost · v1166a29646c9** from **Method**. This dropdown is separate from the registry inspector. Check every argument; do not rely on prefilled values.

| Field / input key | Baseline | Changed scenario | Unit |
| --- | ---: | ---: | --- |
| `material_usd_per_l` | 100 | 100 | USD/L of operating material |
| `useful_cycles` | 100 | 100 | cycles |
| `regeneration_usd_per_l_cycle` | 0.1 | 0.1 | USD/L/cycle |
| `collected_target_kg_per_l_cycle` | 0.01 | 0.02 | kg collected target/L/cycle |
| `annual_fixed_cost_usd` | 1000 | 1000 | USD/year |
| `annual_collected_target_kg` | 100 | 100 | kg/year |

1. Enter the baseline column and click **Calculate & save**.
2. Check the result and open **Exact method arguments**.
3. Change only `collected_target_kg_per_l_cycle` to **0.02** and click **Calculate & save** again.
4. Expand **Assumptions and complete saved record** to inspect the method version and retained inputs.
5. Scroll to **Saved runs** and make sure both results are available.

| Component | Baseline: 0.01 kg/L/cycle | Changed: 0.02 kg/L/cycle |
| --- | ---: | ---: |
| Material replacement | $100/kg | $50/kg |
| Regeneration | $10/kg | $5/kg |
| Allocated fixed cost | $10/kg | $10/kg |
| **Total** | **$120/kg** | **$65/kg** |

For these inputs, the arithmetic is material price divided by lifetime collected output, plus regeneration cost divided by per-cycle collected output, plus annual fixed cost divided by annual collected output. Doubling per-cycle output halves the first two components. The fixed component stays unchanged because its two inputs stay unchanged.

These are illustrative accounting inputs, **not candidate measurements or a full-plant cost estimate**. This method's output input is in **kg/L/cycle**. The optional method-building exercise uses **g/L/cycle** and a different boundary; do not mix their input sets.

Leave the project **Assumptions** panel and **Save revision** alone. These runs use explicit method arguments without changing project assumptions.

## 7. Deliver the five-minute demo

In `LanM_Research_Platform_Formatting_Revision_2026-11-05.pptx`, switch from slide **14, “Demo,”** to the app and return to slide **15, “Questions on Project Direction.”** If using a revised deck, navigate by slide title because numbering may change.

Keep the server running, the rehearsal project selected, **Research** mode active, the saved CSV open, and Prompt B ready to paste.

| Time | What to click or show | What to explain |
| --- | --- | --- |
| 0:00–0:20 | Rehearsal project → Conversation → Research | The project preserves the investigation and its records |
| 0:20–1:15 | Candidate library → `o-36`; then Evidence → prepared source | Candidate information remains linked to inspectable evidence |
| 1:15–2:40 | Send Prompt B; Testing batches → Preview → Download CSV | A request becomes a saved shortlist and an experimental handoff |
| 2:40–3:30 | Models & methods → Method registry → registered `capture-cost` | The method has explicit inputs, assumptions, and numerical checks |
| 3:30–4:40 | Use a saved method → `capture-cost` → changed scenario → Calculate & save | Reuse the same version and retain exact inputs and outputs |
| 4:40–5:00 | Saved runs; return to Questions on Project Direction | The current loop includes a human handoff; further automation is proposed |

### Opening and evidence

Point to Nd/La, the four application tabs, and the absence of accepted experimental records.

Suggested words:

> “This is a persistent research project. The workspace starts with structured LanM records. I can inspect the screening data and return to the source behind it. Published evidence stays distinct from results accepted in this particular project.”

Use the source view rehearsed in Step 8. Mention the Pr/La versus Nd/La distinction when showing o-36. Avoid spending the minute scrolling through a full paper or raw data.

### Live shortlist and handoff

Paste Prompt B from Step 9 into **Conversation → Research**. While it works, explain what the request will save. When it completes, show the shortlist basis, batch preview, and CSV.

Suggested words:

> “The shortlist is saved with its basis. Its CSV is the handoff to our experimental pipeline. These numbers are simulated stock-solution volumes in microlitres. A person currently transfers the file and brings supported processed results back for the next discussion.”

If the response is pending after roughly **20–30 seconds**, use the prepared batch to keep the presentation moving. Say **“This is the saved rehearsal result.”** If you stop a request, inspect what it already saved before submitting another one; completed actions may remain.

### Method inspection and reuse

Open the registered version as in Step 10. Show the checks and a small part of the manifest.

Suggested words:

> “This method was built earlier and registered for reuse. We can inspect what it includes, where its assumptions came from, and which numerical examples it passed. Those checks establish numerical behavior, not physical performance.”

Close the inspector and use the separate **Use a saved method** form. Show the saved **$120/kg** baseline. Enter all six changed-scenario values from Step 11, including **0.02 kg/L/cycle**, and click **Calculate & save**. Expect **$65/kg**. Show **Exact method arguments** and both saved runs.

Suggested words:

> “The useful capability is reusing the same inspectable method with different explicit inputs, while retaining each result. These are illustrative accounting scenarios; I am not presenting the number as a validated separation or full-plant cost.”

### Close and return to the slides

> “Today I guide the next round. The end goal is to connect the transfers and feedback into an optional automated loop. I would like your input on the research tasks and models it should support.”

Return to the questions slide. The existing presentation asks:

1. How easy should it be to update the shared library versus project libraries?
2. How should technoeconomic models be handled: how do researchers build them, and what resources should be included?
3. What tools should be tested through the building workflow, and what questions would researchers ask?

## 8. Optional demonstrations and prompts

Use these during rehearsal or extended discussion. They are outside the five-minute core route.

### Prompt C — Reuse the registered method through conversation

Select **Research**. This is an alternative to the manual method form and should save the same two scenarios:

> Run the registered method capture-cost@1166a29646c9 twice in this project. For both runs use material_usd_per_l=100, useful_cycles=100, regeneration_usd_per_l_cycle=0.1, annual_fixed_cost_usd=1000, and annual_collected_target_kg=100. Set collected_target_kg_per_l_cycle=0.01 in the first run and 0.02 in the second. Save both runs and return a compact comparison table with the inputs that changed and each cost component. Explain that these are illustrative accounting scenarios, not measured performance or a full plant cost estimate. Keep project assumptions unchanged and do not create experimental results.

Inspect **Saved runs** afterward. Expected totals are **$120/kg** and **$65/kg**, with the component breakdown in Step 11.

### Prompt D — Build a new reusable analysis

Select **Build methods**, then use **Conversation**. Research can use existing calculations; Build methods adds the tools to create drafts, run checks, and register a method. Allow time for this exercise before the presentation.

> Build and register a reusable method named demo_material_reuse that calculates lifetime collected target per litre of packed material and material-replacement cost per kilogram of collected target. Inputs are prepared material cost in USD/L, collected target in g/L/cycle, and useful lifetime in cycles. Assume constant collected output over that lifetime; the boundary includes material replacement only. Label this relationship as an accounting calculation and distinguish it from literature-derived performance claims. Use illustrative inputs of $100/L and 0.5 g/L/cycle, and compare useful lifetimes of 50, 100, and 200 cycles. Include units, invalid-input checks, assumptions, references or stated derivation, and independent numerical reference cases: at 100 cycles, lifetime output is 0.05 kg/L and replacement cost is $2,000/kg; at 200 cycles, they are 0.1 kg/L and $1,000/kg. Run the checks, register a version, execute all three scenarios, and save the results in this project. Do not create or accept experimental measurements.

| Useful life | Lifetime collected target | Material-replacement cost |
| --- | ---: | ---: |
| 50 cycles | 0.025 kg/L | $4,000/kg |
| 100 cycles | 0.05 kg/L | $2,000/kg |
| 200 cycles | 0.1 kg/L | $1,000/kg |

Afterward, open **Models & methods → Method registry** and inspect the new registered version, **Recorded check results**, **Method source**, and **Complete method manifest**. Return to **Research** to reuse the registered method with explicit inputs.

`demo_material_reuse` is not one of the two supplied starter methods. If a rehearsal already created a draft, ask the agent to inspect and update it; previous registered versions remain preserved. If checks fail, review the failure before registration. This method covers material replacement only, so its results differ from both `capture-cost` and the built-in separation-unit model.

### Prompt E — Share evidence across local projects

Select **Research**:

> Search PubMed for lanmodulin column reuse and save up to three relevant citations and available abstracts in this project. Inspect the saved records. Share the most relevant record in the shared library with a reason explaining its usefulness and its abstract-only limitation. Preserve its original provenance. Give me the shared source ID and explain what other projects can now access. If no relevant record is returned, report that rather than inventing a source. Do not accept any experimental results or change scientific assumptions.

Open **Evidence → Shared evidence → Sharing record**. Show origin, sharing reason, and limitations. Switch to the other local project and locate the same source in **Evidence**.

Sharing makes the record available across projects **in this workspace**. It is not automatic synchronization to another computer. PubMed supplies citations and available abstracts, not automatic full-paper retrieval. Shared experimental evidence does not automatically become an accepted experiment in another project. Fresh search requires internet; optional `NCBI_EMAIL` and `NCBI_API_KEY` settings are not necessary for this basic demonstration.

### Show why the accepted-results comparison is empty

In **Candidate library**, use **Compare accepted results**. Your rehearsal project has no accepted experiments, so no candidates qualify.

Explain that processed results can be entered as drafts and accepted explicitly after review. The accepted comparison requires applicable collected-output, recovery, purity, complete-cycle-time, and observed-cycle evidence under matching conditions, as well as the project's requirements. A published screening record does not count as an accepted project experiment. Do not manufacture measurements to fill this view.

### Optional built-in economics and sensitivity

To show a different analysis boundary, use the built-in **Separation-unit economics** method and **Project scenario**. Review its assumptions before calculating. It includes material replacement, chemicals, electricity, labor, annualized equipment, and maintenance.

In Research, you can request:

> Calculate the built-in separation-unit cost using this project's current assumptions. Then save a sensitivity sweep with useful lifetime at 0.5, 1, and 2 times its current value, holding the other inputs fixed. Show a comparison table, explain which cost component changes, and identify the inputs supported by accepted measurements versus scenario assumptions. Keep the project's main assumptions unchanged and label the sweep as hypothetical scenarios rather than confidence intervals.

The restored `separation_cost_output_lifetime_grid` method can also be inspected in the registry, but its saved runs are not imported. Supply or review its own inputs when running it. Neither analysis predicts physical scale-up; assumptions and measured evidence must remain distinguishable.

## 9. Troubleshooting and presentation fallbacks

| Symptom | What to do |
| --- | --- |
| Repository cannot be found / access denied | Open the repository page while signed in. Confirm that Ashwath granted your GitHub account access, then retry |
| `python` is not recognized or opens the Store | Check `py -3 --version`. Use `py -3` if it is 3.11+; otherwise install Python and reopen the terminal |
| Cannot find `platform/launch.py` or the snapshot | Return to the repository root. Verify the four paths in Step 1 |
| Restore refuses to overwrite | Existing working data is present. Use it or initialize a separate workspace as shown below |
| Checksum or archive error | Obtain a fresh copy of the starter ZIP from the repository. Leave existing working data intact |
| Browser says connection refused | Keep the Python server running and check the URL and port printed in its terminal |
| Port 8765 is already in use | Use the already-running intended server, or launch on port 8766 as shown below |
| Agent unavailable | Check `codex --version`, executable discovery, or `LANM_CODEX_BINARY`. Restart Python from the same configured terminal |
| Agent available but conversation fails | Check login with the actual executable, model access, network, and the displayed error. Availability only checks executable presence |
| Windows cannot run Codex, or a `.cmd`/`.ps1` shim fails | Use the native executable from the standalone installation and set `LANM_CODEX_BINARY` to its actual `codex.exe` |
| Model unavailable or limit reached | Use an account-accessible model and resolve account limits; show prepared records and direct controls in the meantime |
| Missing registered `capture-cost` | Verify the data path printed at startup. Restore may have been skipped, or a different workspace may be open |
| No rehearsal project, saved runs, or batches | Expected on a fresh installation. Complete Section 6 |
| Source preview is awkward | Use the prepared view, retained source text, or saved citation. Some archived formats require an explicit download |
| Wrong method result | Check version **1166a29646c9** and all six arguments. Verify kg versus g. Do not alter project assumptions to compensate |
| Selection is historical / stale | Project settings or assumptions changed. Rerank for the current project, or deliberately use the existing batch as a historical record |
| No accepted candidates | Expected without accepted experiments. Explain what evidence is missing |

### Recover from launching before restoring, without overwriting data

Stop the app with **Ctrl+C**. From the repository root, choose a new location:

```powershell
$lanmDemoRoot = Join-Path $env:USERPROFILE 'LanM-Aldair-Demo'
python scripts/research_snapshot.py restore --target-dir "$lanmDemoRoot"
python platform/launch.py --data-dir "$lanmDemoRoot\research-data" --open-browser
```

If that target already contains `research-data`, choose a different new folder or launch the existing one. `--target-dir` names the parent folder; restore adds `research-data` beneath it. `--data-dir` points to the resulting `research-data` folder itself.

Use the same `--data-dir` on every launch of that workspace. The ordinary double-click launcher uses the default data location and will not automatically select this separate workspace.

### Use another port

```powershell
python platform/launch.py --port 8766 --open-browser
```

Open <http://127.0.0.1:8766>. Add your `--data-dir` argument if using a separate workspace. Stop an existing instance before launching another against the same working data.

### Present without a model connection

Use **Candidate library**, retained **Evidence**, direct **Create testing CSV** controls, and **Models & methods → Use a saved method**. These do not require a new model response. New literature retrieval and conversation do require network access.

If no batch exists, choose **Create testing CSV → Current untested ranking**, enter **6**, **35**, and **250**, and click **Create saved CSV**. Explain that you used the direct platform controls. Label prepared results or files as saved. A new method build is unnecessary for inspecting and reusing the supplied registered method.

## 10. Restarting, backing up, and updating

### Normal restart

From the same repository folder, run:

```powershell
python platform/launch.py --open-browser
```

For a custom workspace, include the same `--data-dir` as before. Do **not** repeat snapshot restoration. Projects, runs, and selections persist in the working data directory.

### Preserve your rehearsal and research records

Stop the server before copying its working data. Back up the **entire working data directory**, not only SQLite; it also contains reusable methods and runtime-related state.

For the default workspace, from the repository root:

```powershell
$lanmBackupDir = Join-Path $env:USERPROFILE ('LanM-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
Copy-Item -LiteralPath .\research-data -Destination $lanmBackupDir -Recurse
```

For a custom workspace, replace `.\research-data` with the exact data path printed at startup. This is your working-data backup. The repository's `research_snapshot.py create` command exports shared library content and methods while omitting personal project history; it is not a full backup of your rehearsal.

### Update the application from GitHub

Back up data and stop the application first. For a Git clone:

```powershell
git status --short
git pull --ff-only
python platform/launch.py --open-browser
```

If Git reports local changes or an update conflict, preserve those changes and resolve them with Ashwath before continuing. Avoid forced resets. An updated starter ZIP does not automatically merge into your working database, and restore refuses to overwrite it. To inspect a new starter package, create a separate workspace. Retain your `--data-dir` argument if using one.

For a ZIP download, keep the old folder and working data. Extract the updated repository into a new folder. After backing up, either launch the updated code with `--data-dir` pointing to your existing working data, or initialize a separate fresh workspace with the new starter package.

## 11. Final rehearsal checklist

- [ ] Repository downloaded, Python 3.11+ available, starter package restored.
- [ ] Server running; browser opens the expected address and data location.
- [ ] Codex executable and sign-in checked; one small conversation request completed.
- [ ] **Rehearsal: Nd scenario (illustrative)** selected, with Nd/La and no invented experiments.
- [ ] `o-36` and the archived family-portrait source open at readable zoom.
- [ ] Six-candidate selection and A1–F1 batch saved; CSV preview and download checked.
- [ ] CSV open in another window and clearly described as simulated volumes.
- [ ] Registered `capture-cost@1166a29646c9` and its recorded checks located.
- [ ] Both **$120/kg** and **$65/kg** scenarios saved with all six arguments verified.
- [ ] Prompt B ready to paste; **Research** mode selected.
- [ ] Five-minute route rehearsed, including the 20–30 second fallback to saved artifacts.
- [ ] Slide transition located by title: **Demo → Questions on Project Direction**.
- [ ] Power/display or screen sharing checked; unrelated windows closed.
- [ ] Working data backed up after preparation.

### Implementation references and verification

This guide combines the existing November 5 Word walkthrough and its source script with the current setup and interface. The original presentation files need not be present on Aldair's machine. For implementation details, see:

- [Repository setup](README.md) and [platform guide](platform/README.md).
- [Starter package behavior](portable-data/README.md) and [restore/export implementation](scripts/research_snapshot.py).
- [Python requirements](platform/pyproject.toml), [launcher](platform/launch.py), and [runtime configuration](platform/src/lanm_platform/config.py).
- [Browser controls](platform/ui/index.html) and [interface behavior](platform/ui/app.js).
- [Companion presentation prompts](platform/presentation/demo_prompts.md).

An isolated temporary-workspace check verified snapshot restoration, 616 candidates, 14 sources, zero accepted experiments, the registered method, the $120/$65 calculations, and a six-candidate CSV with stable repeated downloads. It did not alter existing research records or make live model requests. Hardware targets are planning estimates. Live conversation and any newly built method still need rehearsal on Aldair's account and computer.
