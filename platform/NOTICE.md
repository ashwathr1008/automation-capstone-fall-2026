# Source and data provenance

The platform's Python, browser interface, and presentation code were implemented for this capstone. The separation equations were implemented independently. No REEPS, Biomni, Elnora, or OpenScience source was copied into this version.

The Codex executable is an external runtime installed separately. Its own terms and license apply. It is not included in this repository. The local application does not copy authentication credentials into research data or source control.

Biomni's public repository informed three small design patterns: a summary catalog with on-demand guidance, separate PubMed search/retrieval operations, and task-based evaluation cases. The implementations, LanM handbook, and evaluation fixtures here were written independently. No Biomni source, biomedical guides, or evaluation dataset was copied, and no Biomni runtime dependency was added. The reviewed upstream project is licensed under [Apache 2.0](https://github.com/snap-stanford/Biomni/blob/400c1f366b96a35ca253e13c9b06c5076af41d65/LICENSE). Reviewed references:

- [Guidance loader](https://github.com/snap-stanford/Biomni/blob/400c1f366b96a35ca253e13c9b06c5076af41d65/biomni/know_how/loader.py)
- [PubMed MCP example](https://github.com/snap-stanford/Biomni/blob/1081fdaf0f12dcfe915c75acbf8a7abba2e48e5e/biomni/tool/example_mcp_tools/pubmed_mcp.py)
- [Task evaluator](https://github.com/snap-stanford/Biomni/blob/400c1f366b96a35ca253e13c9b06c5076af41d65/biomni/eval/biomni_eval1.py)

The LanM handbook links its underlying scientific papers and labels its review status. PubMed records come from NCBI E-utilities. They retain publication attribution and supplied copyright information in provenance; retrieval does not confer ownership or imply NLM endorsement. See the [NLM disclaimer](https://www.ncbi.nlm.nih.gov/About/disclaimer.html). Abstract retrieval is not full-text retrieval.

`src/lanm_platform/data/candidates.json.gz` is a compressed migration of the existing Week 3 scientific seed. It preserves 616 candidate records and associated source metadata, contexts, assertions, and formulas. Original sources retain their recorded citations, locators, and hashes. Compression and migration do not create ownership of the underlying scientific material.

The original source papers, data, and historical project artifacts remain in the local legacy archive. They are not included in the source repository. Review original publication/data rights before distributing imported scientific material publicly. The source repository is prepared for private review.

The presentation cites the relevant scientific papers and product documentation in its speaker notes. Its live-demo calculations use explicitly illustrative assumptions and do not claim new laboratory measurements.
