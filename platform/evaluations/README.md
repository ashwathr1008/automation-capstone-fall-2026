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

The JSON report includes the exact question and submitted prompt, fixture text and hashes, model, timing, final answer, activity events, project snapshots and saved calculation runs. No answer rubric is submitted to the model. Runtime exposes tool-name activity, not full tool arguments or returned evidence. An observed `read_source` activity therefore does not prove which source was read successfully. Citation-marker checks only find source IDs or URLs in text; they do not establish that a citation supports a claim. Both limitations are explicit in the report. Scientific reviews remain `unreviewed` regardless of those checks.

To review, copy the report to a named file and edit only each result's `scientific_review` object. Record the human reviewer's name, an ISO date, and a rating of `met`, `partial`, `not_met` or `not_applicable` for each criterion. Include a short rationale tied to the answer and evidence, plus any rubric correction needed. Set its status to `reviewed` only when the review is complete. Do not replace unreviewed fields with model self-grades. Different defensible experiment designs can meet the criteria. Have a domain scientist review both the rubric and answers before presenting scientific success rates.

For comparisons, keep case version/hash, model, prompts and fixture setup fixed and review both saved outputs using the same criteria. This runner does not calculate a composite scientific score or automate a baseline-agent comparison. Cases use archived fixtures, so the suite does not test live PubMed availability. The unit tests check runner isolation, prompt/rubric separation and honest reporting; they do not validate scientific response quality.

The task-ID, prompt and reference organization was informed by [BiomniEval1](https://github.com/snap-stanford/Biomni/blob/400c1f366b96a35ca253e13c9b06c5076af41d65/biomni/eval/biomni_eval1.py), inspected at commit `400c1f366b96a35ca253e13c9b06c5076af41d65`. That repository's code has an [Apache-2.0 license](https://github.com/snap-stanford/Biomni/blob/400c1f366b96a35ca253e13c9b06c5076af41d65/LICENSE). This runner and its cases are original implementations; no Biomni code or benchmark data were copied. We do not use its exact-match scoring for open scientific judgments.
