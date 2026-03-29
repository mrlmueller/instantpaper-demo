# Phase E Solution Research

Date: 2026-03-14

## Scope

This note covers the Phase E problems identified after the first real retrieval run:

- unsupported chapter subpoints were still pulling in substitute sections
- generic sections such as `Introduction`, `Conclusion`, and `Research Design` appeared high in the ranking
- the current global fusion had no explicit notion of subpoint support vs. subpoint absence

The user explicitly rejected the simplistic fix of aggressively demoting generic sections. The new target is:

- keep generic sections eligible when they contain real evidence
- improve unsupported-subpoint handling
- avoid overfitting to the current chapter topic

## Local Diagnosis

Standalone scripts used:

- [phase_e_failure_lab.py](<projektverzeichnis>/pdf-scan/phase_e_failure_lab.py)
- [review_phase_e.py](<projektverzeichnis>/pdf-scan/review_phase_e.py)
- [phase_e_solution_search.py](<projektverzeichnis>/pdf-scan/phase_e_solution_search.py)

Run artifacts:

- [diagnosis.md](<projektverzeichnis>/pdf-scan/runs/67507862e53171c27bfb2ac9/phase_e_failure_lab/diagnosis.md)
- [phase_e_review_report.md](<projektverzeichnis>/pdf-scan/runs/67507862e53171c27bfb2ac9/phase_e_review/phase_e_review_report.md)
- [solution_search_report.md](<projektverzeichnis>/pdf-scan/runs/67507862e53171c27bfb2ac9/phase_e_solution_search/solution_search_report.md)

Main local findings:

1. The corpus really does support `SP1`, `SP5`, and `SP6`.
2. After tightening anchor patterns and excluding penalized sections, `SP2`, `SP3`, and `SP4` have effectively no trusted support in this 5-document corpus.
3. Generic titles are not the real problem by themselves.
   Most generic sections in the top 20 were high-evidence sections, not junk.
4. The real ranking failure is unsupported-facet substitution.
   The system returns something semantically adjacent when a facet is absent instead of saying that the facet is not present.
5. Dense retrieval was not the dominant local failure in the current top set.
   The review found no dense-only or dense-without-anchor candidates in the top 40 after the current Phase E run.

## Brainstormed Fix Directions

Candidate directions considered before external research:

1. Stronger generic-section penalty.
   Rejected as the primary fix because the local audit showed many generic sections contain real evidence.

2. Evidence-aware generic handling.
   Keep generic titles eligible, but rank them by supporting-passage evidence density instead of title priors.

3. Per-subpoint candidate pools plus diversified global ranking.
   Avoid letting the strongest facets absorb all ranking mass.

4. Supported-facet gating / abstention.
   If a facet has no trusted corpus evidence, do not force coverage; mark it unsupported.

5. Dense lexical anchoring.
   Useful as a safety mechanism for future runs, but not the main current bottleneck.

## External Research

### 1. Diversification over aspects / subtopics

- Santos et al., xQuAD:
  https://www.researchgate.net/publication/220479696_Explicit_Search_Result_Diversification_through_Sub-queries
  Takeaway: diversification should use explicit sub-queries/aspects instead of a single flat relevance score.

- Carbonell and Goldstein, MMR:
  https://www.researchgate.net/publication/243774776_The_use_of_mmr_and_diversity-based_reranking_in_document_reranking_and_summarization
  Takeaway: reranking should balance relevance and novelty/coverage, not only raw relevance.

Relevance here:

- Phase E currently behaves like a flat scorer with fusion.
- The user query is inherently multi-aspect.
- A diversified reranking step is a better fit than more aggressive title priors.

### 2. Unsupported-query / abstention signals

- MacAvaney et al., “Towards Query Performance Prediction for Dense Retrieval”:
  https://arxiv.org/abs/2409.01492
  Takeaway: dense retrieval quality is query-dependent; a single fixed retrieval behavior is unreliable across query types.

- Rajasekaran et al., “Unanswerability in Retrieval Augmented Generation”:
  https://aclanthology.org/2025.coling-main.627.pdf
  Takeaway: systems need explicit handling for unsupported questions instead of always returning something.

Relevance here:

- The Phase E problem is partly an answerability problem.
- Some chapter facets are unsupported by this corpus, so the correct behavior is controlled abstention, not forced nearest-neighbor retrieval.

### 3. Multi-view indexing / long-document evidence

- Lawrie et al., “Multi-Content Heterogeneous Information Retrieval”:
  https://arxiv.org/abs/2406.10444
  Takeaway: using multiple complementary views such as raw text, keywords, and summaries improves retrieval robustness over single-view indexing.

- Rane et al., “MC-Indexing: Multi-Chunk Indexing for Long-Document Retrieval”:
  https://arxiv.org/abs/2506.19381
  Takeaway: long-document retrieval benefits from indexing multiple chunk views instead of one flat representation.

Relevance here:

- Phase E already uses several views.
- The next improvement should preserve that multi-view design, but organize selection by facet support rather than only by fused relevance.

### 4. Query expansion caution

- “Exploring the Best Practices of Query Expansion with Large Language Models”:
  https://aclanthology.org/2024.findings-emnlp.1034
  Takeaway: expansion can help, but uncontrolled expansion also increases drift and is not a substitute for better retrieval control.

Relevance here:

- The current issue is not primarily “too few terms”.
- More expansion would likely worsen SP3/SP4 substitution unless tied to explicit support checks.

### 5. Passage-first reranking

- Nogueira and Cho, “Passage Re-ranking with BERT”:
  https://arxiv.org/abs/1901.04085
  Takeaway: strong passage-level reranking remains a high-value step after recall-oriented retrieval.

Relevance here:

- This supports keeping generic sections eligible when they have strong passage evidence.
- It also supports moving the precision burden to the reranking stage instead of solving everything with title priors.

## Experimental Harness

The new comparison harness is:

- [phase_e_solution_search.py](<projektverzeichnis>/pdf-scan/phase_e_solution_search.py)

It tests:

- flat baseline ranking
- generic-evidence-aware flat ranking
- round-robin diversification
- xQuAD-style diversification
- supported-facet-only variants
- supported-facet plus abstention

Test coverage was intentionally broader than the single benchmark chapter:

- single-topic probes for all 5 document themes
- paraphrase probes
- composite multi-aspect probes across different documents
- negative unsupported probes

This is meant to reduce overfitting to the current chapter wording.

## Experimental Result

Best current variant:

- `xquad_supported_generic_abstain`

Artifact:

- [solution_search_candidates.json](<projektverzeichnis>/pdf-scan/runs/67507862e53171c27bfb2ac9/phase_e_solution_search/solution_search_candidates.json)

Headline result:

- total score: `101.6`
- multi-probe score: `41.6`
- single-probe score: `60.0`
- abstain successes: `2`
- generic low-evidence top10 total: `1`

Why it won:

1. It preserved the single-topic retrieval behavior.
2. It correctly abstained on the negative unsupported probes.
3. It did not rely on aggressive generic-title suppression.
4. It reduced low-evidence generic leakage relative to the diversification-heavy alternatives.

Why some alternatives lost:

- `round_robin_all_facets` increased facet coverage, but it also forced unsupported facets and raised low-evidence generic leakage.
- `flat_baseline` kept strong positive retrieval performance, but it completely failed the negative unsupported probes.
- `xquad_all_facets` still forced unsupported facets because it diversified over all requested facets, not only supported ones.

## Recommended Fix Direction

The best supported Phase E design change is:

1. Keep generic sections eligible.
2. Add a facet-support inventory step before final selection.
3. Only diversify over facets with trusted corpus support.
4. Add explicit abstention / unsupported-facet signaling for absent facets.
5. Rank generic sections by evidence density from section text and supporting passages, not by title stereotypes.

Concretely, the notebook implementation should move toward:

- Phase E recall:
  keep the current multi-lane candidate generation

- Phase E selection:
  replace pure global fusion ordering with support-aware diversified selection

- Output contract:
  return both
  - a global candidate list
  - facet/subpoint support diagnostics
  - unsupported facet list

This is the most defensible next step before Phase F.

## OpenAI Budget

User granted up to 2 USD for OpenAI calls in this line of work.

No extra OpenAI calls were used in the standalone failure-lab and solution-search scripts yet.
The current analysis stayed local plus web research.
