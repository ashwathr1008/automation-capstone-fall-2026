# Scientific evaluation cases

Nine small development cases check the reasoning we need from the LanM platform: citation support, screening versus process performance, mass basis, recovery accounting, missing candidate data, matched conditions, conflicting evidence, experiment priorities and near-tied scores.

These are author-written cases and reference criteria, **not expert-validated ground truth or an independent benchmark**. They are useful for finding failures and comparing reviewed responses. They do not establish that the platform outperforms a general agent or Biomni. Synthetic records are labeled throughout. The two publication excerpts are short author paraphrases with primary-source URLs and locators, checked on 2026-11-03.

From `platform/`, using the installed Python:

```powershell
python evaluations/run.py --list
python evaluations/run.py --prepare --all
python evaluations/run.py --run --case source_entailment --case double_recovery
python evaluations/run.py --run --all --model gpt-6.1-sol --output ../research-data/evaluations/sol-review.json
```

No arguments only lists cases. `--prepare` saves the questions, evidence and review criteria without opening a database or making model requests. Live requests require `--run` and an explicit selection. They use the signed-in Codex account and can incur its normal usage. The timeout is 300 seconds per case by default; `--timeout` changes it.

Each live case creates its own temporary data directory, project and archived fixtures, then removes them after closing its runtime. There is no existing-project or data-directory input. The imported screening library remains available inside that temporary Store. Synthetic fixture candidates such as X and Q are deliberately separate from real library candidates. Existing project databases are never opened. Default reports go to `research-data/evaluations/latest.json` beside the source checkout, respecting `LANM_DATA_DIR`; the default file is replaced on each invocation. Supply different output filenames to retain runs. Outputs inside the source checkout are rejected.

The JSON report includes the exact question and submitted prompt, fixture text and hashes, model, timing, final answer, activity events, project snapshots and saved calculation runs. No answer rubric is submitted to the model. Updated runtimes also provide `trace` records with available tool arguments/results and `metrics`; inspect their completeness rather than interpreting tool-name activity as success. An observed `read_source` activity alone does not prove which source was read successfully. Citation-marker checks only find source IDs or URLs in text; they do not establish that a citation supports a claim. Scientific reviews remain `unreviewed` regardless of those checks.

To review, copy the report to a named file and edit only each result's `scientific_review` object. Record the human reviewer's name, an ISO date, and a rating of `met`, `partial`, `not_met` or `not_applicable` for each criterion. Include a short rationale tied to the answer and evidence, plus any rubric correction needed. Set its status to `reviewed` only when the review is complete. Do not replace unreviewed fields with model self-grades. Different defensible experiment designs can meet the criteria. Have a domain scientist review both the rubric and answers before presenting scientific success rates.

For comparisons, keep case version/hash, model, prompts and fixture setup fixed and review both saved outputs using the same criteria. This runner does not calculate a composite scientific score or automate a baseline-agent comparison. Cases use archived fixtures, so the suite does not test live PubMed availability. The unit tests check runner isolation, prompt/rubric separation and honest reporting; they do not validate scientific response quality.

The task-ID, prompt and reference organization was informed by [BiomniEval1](https://github.com/snap-stanford/Biomni/blob/400c1f366b96a35ca253e13c9b06c5076af41d65/biomni/eval/biomni_eval1.py), inspected at commit `400c1f366b96a35ca253e13c9b06c5076af41d65`. That repository's code has an [Apache-2.0 license](https://github.com/snap-stanford/Biomni/blob/400c1f366b96a35ca253e13c9b06c5076af41d65/LICENSE). This runner and its cases are original implementations; no Biomni code or benchmark data were copied. We do not use its exact-match scoring for open scientific judgments.

## Comparing configured model providers

`compare.py` uses the same provider profiles and runtime constructors as the platform. It combines the nine scientific cases above with four bounded tool tasks:

| Case | Automatically checked persisted facts | Still needs review |
| --- | --- | --- |
| `tool_economics` | Saved calculation returns 66.6667 L and 0.0015 kg/L/day from the fixed inputs; no committed input changes | Whether the answer explains units, recovery accounting and scientific limits correctly |
| `tool_hypothetical` | Saved ranking contains the requested overrides; committed assumptions, configuration and experiments stay unchanged | Whether the answer explains that screen ranks do not establish process performance |
| `tool_exact_selection` | Exact candidate order and ranking are preserved in one selection and one batch, with requested bounds and seed | Accurate explanation and usable download link |
| `tool_missing_bound` | No batch is created before a missing custom volume bound is supplied | Whether the model asks the appropriate clarification |

From `platform/`:

```powershell
python evaluations/compare.py --list
python evaluations/compare.py --prepare --all --output ../benchmark-results/review-packet.json
python evaluations/compare.py --run --profile codex-default --profile qwen-local --case tool_economics --case tool_hypothetical --case tool_exact_selection --case tool_missing_bound --repeat 3 --output ../benchmark-results/tool-comparison.json
python evaluations/compare.py --run --profile codex-default --profile qwen-local --all --repeat 3 --output ../benchmark-results/full-comparison.json
```

Profile IDs must exist in the configured `model_profiles.json`; `qwen-local` is an example, not an automatic model installation. `--list` shows available IDs. A single profile is also supported for a baseline. `--run`, explicit cases or `--all`, at least one profile, and an output filename are required for live requests. `--prepare` creates no Store and makes no model requests. Outputs must be JSON files inside this workspace but outside `platform/`; use unique names to retain earlier runs. Each result is saved immediately, so a later case failure does not discard earlier results.

Every case/provider/repetition starts with a new temporary project, runtime and conversation. The templates, source fixtures and candidate library are shared; generated project/source IDs differ. Reports retain the exact submitted prompt, saved answer, available tool trace, token and timing metrics, state snapshots and author-written review rubric. Rubrics are never submitted to the model. Profile metadata records declared checkpoint, quantization and context settings when configured; credentials are excluded. Code, library and fixture hashes help identify changes between runs. All outputs are marked evaluation holdout and are not automatically training eligible.

Both adapters receive the same local research-tool allowlist. Live PubMed retrieval, project creation/listing and shared-evidence promotion are omitted. Local state-changing operations remain available so unintended committed changes can be observed. Codex additionally disables its configured web search and shell feature for these comparisons; its underlying agent scaffold can still differ from the compatible runtime's bounded tool loop. Inspect any native-tool traces before claiming strict tool parity. This is a comparison of configured systems, not an isolated causal test of model weights.

Provider order reverses on alternate repetitions. End-to-end case time includes fixture setup, new-runtime startup and teardown; runtime metrics separately describe measured model/tool time. A nonstreaming compatible endpoint reports first-token time as unknown, not its total request time. Remote queueing, model residency, warm caches, hardware, quantization, decoding defaults and provider-side changes can affect timing. Reports do not infer missing usage or prices; unknown cost is `null`, not zero. A few repetitions establish basic repeatability, not a reliable tail-latency estimate. Compare each task's paired results and failures before considering the descriptive aggregate median/p95.

For the next benchmark iteration, add a larger, previously unseen set of representative tasks before tuning on failures: literature-supported extraction, calculation setup, ambiguity handling, exact state transitions and multi-turn continuation. Separate case families by source paper, candidate/scenario and conversation, not merely random answer rows. Keep a development set for iteration and an untouched final test set. Review anonymized, shuffled model outputs with the same criteria; a scientist should judge citation entailment, biological applicability, uncertainty and the next-experiment recommendation. Tool success, familiar words, agreement with Codex and a passing numerical calculation are not substitutes for that review. Report reliability and task-specific failures alongside latency; retain timeouts and malformed tool calls in the denominator.

## Frozen-weight domain-grounding comparison

The local profiles can set `domain_grounding: true` to supply a bounded packet of existing source excerpts, handbook text and workflow guidance before the first model request. The packet is recorded in `trace` with source IDs, exact offsets and truncation flags. All weights and tool implementations remain unchanged; no teacher outputs or training dataset are collected.

Compare a plain profile with a clone using the same model, thinking setting, output budget and endpoint, changing only `domain_grounding`. Use fresh projects and conversations with the same cases. Record objective saved-state checks separately from answer correctness, source entailment and usable artifact links. This evaluates a complete retrieval-and-guidance package, not retrieval alone. Keep failed cases and retrieval misses in the report.

```powershell
python evaluations/compare.py --run --profile qwen-9b-local --profile qwen-9b-grounded --case tool_economics --case tool_hypothetical --case tool_exact_selection --case tool_missing_bound --case source_entailment --case double_recovery --output ../benchmark-results/domain-grounding-pilot.json
```

These are development cases that have already informed implementation decisions, not an untouched final test. A small pilot can show concrete improvements or regressions, but cannot establish frontier-model parity. The next reliable comparison requires unseen tasks, repeated runs and blinded domain review.
