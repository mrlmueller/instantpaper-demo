# Prompt Research Workspace

Purpose: maintain an iterative, source-backed audit of prompt quality and adjacent retrieval/scoring issues in `sources-v2`.

Scope:
- Phase B query planner
- Phase C OpenAlex query builder
- Phase C Semantic Scholar bulk query builder
- Phase F embeddings/text packaging where relevant
- Phase H coverage tag generation where it affects LLM grounding
- Phase I rerank prompt and evidence contract
- Benchmarking and evaluation design for recall, relevance, and ranking quality

Working files:
- `LOCAL_PIPELINE_AUDIT.md`: concrete findings from code, debug artifacts, and recent runs
- `SOURCE_LEDGER.md`: research source inventory with credibility notes
- `RESEARCH_NOTES_PROMPTING.md`: prompt engineering and structured-output research notes
- `RESEARCH_NOTES_RETRIEVAL_AND_RANKING.md`: retrieval, query generation, reranking, and evaluation notes
- `PHASE_C_API_PROBE_FINDINGS.md`: live-provider experiment findings for OpenAlex and Semantic Scholar
- `PHASE_C_QUERY_REPLAY_FINDINGS.md`: replay findings from the actual generated Phase C queries
- `PROMPT_OPTIMIZATION_REPORT.md`: final synthesized report for the user

Method:
1. Audit local pipeline behavior and real artifacts first.
2. Research each failure mode using primary/high-credibility sources.
3. Record findings incrementally with notes aimed at future iterations.
4. Synthesize optimized prompts plus non-prompt recommendations at the end.

Current status:
- Local audit complete for the current pass.
- External research complete for the current pass.
- Final synthesis drafted in `PROMPT_OPTIMIZATION_REPORT.md`.
- Follow-up addendum integrated for the Phase B update, zero-result query behavior, and Semantic Scholar-specific query-yield fixes.
- Live Phase C API probe completed and summarized in `PHASE_C_API_PROBE_FINDINGS.md`.
- Live replay of the actual generated Phase C queries completed and summarized in `PHASE_C_QUERY_REPLAY_FINDINGS.md`.
