# Paste-ready demonstration prompts

These prompts target the currently implemented platform. Use Research unless a prompt explicitly says Build methods. Prompts that save rankings, selections, sources, methods, or shared evidence create real application records. Numerical examples are illustrative scenarios, not laboratory observations. A model response still needs review; these prompts have been checked against the available tools, not all rehearsed live.

## Candidate evidence — Research

> Inspect LanM candidate o-36. Read its saved screening record and available published evidence. Explain what the evidence establishes about Pr/La separation, identify the tested conditions, and distinguish that evidence from accepted experiments in this project. Cite the source records you actually inspect and list the most important missing measurements for evaluating a separation process.

## Candidate selection and experimental handoff — Research

> Using this project's target and comparison elements, rank six project-untested LanM candidates with the existing screening method. Explain the ranking basis and its limitations. Save the top six as our testing selection, then export their testing CSV using the default simulated stock-solution volumes. Give me the download link and explain the CSV fields. Do not change project assumptions or create experimental results. If fewer than six candidates qualify, report the shortfall instead of substituting other candidates.

The current CSV contains stock-solution dispense volumes in microliters, not experimentally derived concentrations. The receiving automation supplies the fixed water addition and dilution program.

## Literature discovery — Research

> Search PubMed for lanmodulin immobilization, column separation, and reuse. Save up to five relevant citations and available abstracts. For each, explain what the abstract supports about using LanM in a separation process and what would require reading the full paper. Identify one useful follow-up research question and cite the saved sources.

## Existing measurements and next steps — Research

> Compare the candidates with accepted experiments in this project using the existing accepted-result ranking. Report which candidates meet its evidence, matching-condition, purity, recovery, and cost requirements. For excluded candidates, explain exactly what is missing or incompatible. If there are no accepted experiments, say so and explain the measurements the ranking requires. Distinguish eligibility for this comparison from demonstrated readiness to scale up.

## Build a reusable analysis — Build methods

> Build and register a reusable method named demo_material_reuse that calculates lifetime collected target per litre of packed material and material-replacement cost per kilogram of collected target. Inputs are prepared material cost in USD/L, collected target in g/L/cycle, and useful lifetime in cycles. Assume constant collected output over that lifetime; the boundary includes material replacement only. Label this relationship as an accounting calculation and distinguish it from literature-derived performance claims. Use illustrative inputs of $100/L and 0.5 g/L/cycle, and compare useful lifetimes of 50, 100, and 200 cycles. Include units, invalid-input checks, assumptions, references or stated derivation, and independent numerical reference cases: at 100 cycles, lifetime output is 0.05 kg/L and replacement cost is $2,000/kg; at 200 cycles, they are 0.1 kg/L and $1,000/kg. Run the checks, register a version, execute all three scenarios, and save the results in this project. Do not create or accept experimental measurements.

Expected illustrative outputs for rehearsal: 50 cycles gives 0.025 kg/L and $4,000/kg; 100 gives 0.05 kg/L and $2,000/kg; 200 gives 0.1 kg/L and $1,000/kg. These are material-replacement costs only, not total separation cost. If the named draft already exists, inspect and update that draft as needed; registered versions remain preserved.

## Hypothetical sensitivity analysis — Research

> Calculate the built-in separation-unit cost using this project's current assumptions. Then save a sensitivity sweep with useful lifetime at 0.5, 1, and 2 times its current value, holding the other inputs fixed. Show a comparison table, explain which cost component changes, and identify the inputs supported by accepted measurements versus scenario assumptions. Keep the project's main assumptions unchanged and label the sweep as hypothetical scenarios rather than confidence intervals.

## Share evidence across projects — Research

> Search PubMed for lanmodulin column reuse and save up to three relevant citations and available abstracts in this project. Inspect the saved records. Share the most relevant record in the shared library with a reason explaining its usefulness and its abstract-only limitation. Preserve its original provenance. Give me the shared source ID and explain what other projects can now access. If no relevant record is returned, report that rather than inventing a source. Do not accept any experimental results or change scientific assumptions.

## Compact candidates for a capabilities slide

- **Investigate:** “Inspect o-36's published Pr/La evidence and explain what is still missing for process evaluation.”
- **Select and export:** “Rank six untested candidates for this project's metal pair, explain the shortlist, and export their testing CSV.”
- **Build analysis:** “Build and register a reusable material-replacement-cost model, check numerical examples, and compare 50, 100, and 200 useful cycles.”

Use the complete prompts above for a demonstration; the short forms are slide labels. A live build can take time, so rehearse it before choosing the timed presentation route.
