# LanM local training corpus

This is a small, reproducible domain-adaptation corpus for supervised training. It teaches platform tool contracts, short verified tool-use dialogues, citation-preserving extraction and the distinction between assumptions and accepted measurements. It is not a collection of expert reasoning traces or a complete ingestion of every paper.

Build it from the original bundled platform assets:

```powershell
python local-training/prepare_lanm_training.py
python -m unittest discover -s local-training/tests -v
```

The builder makes no model or network requests, touches no live research database, and uses isolated temporary stores. Its fixed input allowlist contains the original platform implementation, MCP tool definitions, science instructions, handbook, candidate library and source-evidence archive. It never opens benchmark results, evaluation cases, saved model answers or conversations. The generated data is ignored by Git; source code and this description are retained.

## Records and tool coverage

The corpus contains 366 training records and 47 validation records:

| Record type | Training | Validation | Total |
|---|---:|---:|---:|
| Exact tool-contract descriptions | 41 | 0 | 41 |
| Verified local tool dialogues | 200 | 26 | 226 |
| Original assertions, contexts, formulas and text excerpts | 118 | 21 | 139 |
| Labelled authored-handbook sections | 7 | 0 | 7 |
| Total | 366 | 47 | 413 |

Every one of the 41 MCP input contracts is included. Deterministic reference actors execute 240 calls covering 39 distinct local tools; 226 dialogues are retained after the split restrictions below. `search_pubmed` and `fetch_pubmed` have schema-derived documentation only: no query runs and no fake retrieved results are included. Tool execution establishes that a demonstration can run against the implementation; it does not validate the scientific assumptions of a tool or paper.

Synthetic examples include project configuration, shared and candidate-specific assumptions, saved economics and sensitivity analyses, ranking and selections, software-demo CSV batches, draft and explicitly accepted processed records, scale scenarios, source archiving and local sharing, and building/checking/registering/reusing a simple arithmetic method. Values, project IDs and source-note text are generated independently of the benchmark. The examples perform no laboratory work.

Each dialogue supplies the invoked tool's exact schema and up to two deterministic distractor schemas. Tool responses contain verified original fields. To fit a small model's context, the builder omits redundant input-detail catalogs, long nested ranking/selection snapshots, sequences, and incidental timestamps/paths; `list_runs` uses identity, method, state and summary fields. It does not rewrite retained values. Per-record provenance includes hashes of both the normalized complete result and the displayed subset. The manifest records this transformation. These are short tool-use demonstrations, not long autonomous-agent trajectories.

For `list_sources` only, one distractor schema is included so that the complete returned source catalog fits the fixed 4096-token context. This context-length correction changes no tool arguments, tool results or assistant answers.

## Evidence coverage

The original library contains 14 source records, 402 assertions, 10 contexts and 15 formulas. The corpus uses 72 assertions, all 10 contexts and all 15 formulas. Text extraction is limited to 42 verified passages from six source records:

| Source ID | Passages | Split |
|---|---:|---|
| `spyci_paper` | 7 | Training |
| `spyci_supplement` | 7 | Training |
| `spyci_pmc_2026` | 7 | Training |
| `lanm_equilibrium_2024` | 7 | Training |
| `cmi_lanm_valuation` | 2 | Training |
| `smerigan_shi_2025_arxiv_v1` | 12 | Validation |

Multiple source records can belong to one paper. These counts must not be described as six independent studies or as all full papers being trained on. Other source records appear through structured original records or catalog metadata, not archived-text question/answer examples. `manifest.json` distinguishes these cases source by source. Images and chart heights are not used to invent numeric assertions.

Archive text is checked against the original source's SHA-256 before extracting a passage. Each passage retains its source ID, URL, archive member, character offsets and excerpt hash. Assertions retain their evidence kind, original locator and context limits. Answers are extractive or derived directly from stored fields; no teacher model supplies new paper claims. The seven handbook sections are labelled as authored guidance with their recorded review status.

## Split and interpretation

All excerpts, assertions, contexts and formulas from the Smerigan source (`paper:arxiv-2504.10495v1`) are held out together. That paper is removed from the isolated actors' library views before constructing training dialogues. The validation set contains 21 records from this paper and 26 dialogues from one independent synthetic project family. Only source-independent or synthetic-state tools from that family are retained for validation. Original-paper retrieval and candidate-screening dialogues remain in training.

Training and validation have disjoint group IDs and no identical message/tool content hashes. General tool contracts and scientific concepts occur in both splits; the validation set is a small adaptation holdout, not an untouched scientific benchmark or a test of unseen tool APIs. Parameter variations within the five training project families intentionally share tool workflows. The separately frozen benchmark is not a training-data source.

## Files and validation

`data/train.jsonl` and `data/validation.jsonl` contain OpenAI-style `messages` and `tools`, with JSON objects for function arguments. IDs, group labels, split labels and provenance sit outside the messages. No artificial reasoning text is added. The trainer is responsible for rendering the official model chat template, masking loss to assistant spans and rejecting overlong sequences without silently truncating answers.

`data/manifest.json` records corpus and source hashes, source coverage, retained and executed tool counts, split rules, input allowlist, exclusions and limitations. The builder's seven tests verify exact tool schemas, no network execution, correct candidate-specific scope, source excerpts and locators, actual paper exclusion, restricted output paths, unmodified retained response fields, and byte-identical JSONL output across independent builds. Timestamped manifests naturally differ by build time.

Dataset integrity and a successful fine-tuning run do not establish improved model performance. Report the actual training settings and separate held-out evaluation results before claiming an improvement over a base model.
