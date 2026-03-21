# Phase F Report

## Scope

Phase F turns the high-recall Phase E candidate pool into a precision-oriented section ranking.

Implemented artifacts:

- `pdf-scan/phase_f_lab.py`
- `pdf-scan/review_phase_f.py`
- `pdf-scan/pdf-scan-v3.ipynb`

Primary outputs:

- `rerank/phase_f_candidate_packs.jsonl`
- `rerank/cross_encoder.jsonl`
- `rerank/llm_judge.jsonl`
- `rerank/rerank_results.jsonl`
- `rerank/phase_f_summary.json`
- `rerank/phase_f_assessment.json`

## Final design

### Inputs

- Phase E fused section candidates
- supporting passages
- Phase D query plan

### Outputs

- candidate packs with traceable evidence
- local cross-encoder scores
- optional OpenAI usefulness judgments on a small top subset
- unified rerank table with raw features preserved for Phase G

### Final stack

- mandatory local reranker: `BAAI/bge-reranker-v2-m3`
- optional judge: `gpt-5-mini` on a small diversified subset

### Why this stack won

- `BAAI/bge-reranker-v2-m3` handled the bilingual / cross-domain candidate packs much better than the English MS MARCO baseline.
- The OpenAI judge is useful, but only as a light secondary signal. It is not stable enough to dominate the ranking.

## Implementation notes

Key implementation decisions:

- candidate packs are evidence-first, not section-first
  - the reranker now sees the best supporting passages before the longer section excerpt
- the judge blend was reduced to `0.20`
  - this keeps the judge as a refinement layer instead of letting it overpower the local reranker
- inconsistent judge rows are filtered out of blending
  - some structured outputs returned `0/0/0` raw scores while the free-text note said the section was highly relevant
  - these rows are now marked inconsistent and ignored for scoring
- Phase F main is cache-aware for Phase B-E
  - rerank experiments no longer need to rebuild parsing or embeddings when compatible artifacts already exist

## Validation

### Benchmark run

Run:

- `2270646d3c56c160a8e30345`

Artifacts:

- `pdf-scan/runs/2270646d3c56c160a8e30345/rerank/phase_f_summary.json`
- `pdf-scan/runs/2270646d3c56c160a8e30345/phase_f_review/phase_f_review_summary.json`

Result:

- status: `success_with_warnings`
- reviewer category: `strong`
- candidate packs: `60`
- rerank results: `60`
- judged rows used in blending: `8`
- inconsistent judge rows filtered: `2`
- judge disagreement average: `0.32166383`
- latest Phase F OpenAI cost: `$0.008236`

Top reranked examples:

1. `The Trust Building Mechanisms in Social Commerce`
2. `35 Variants of uncertainty`
3. `Conclusion`
4. `1 Judgment under uncertainty: Heuristics and biases`
5. `3 Subjective probability: A judgment of representativeness`

Interpretation:

- the top set is coherent and evidence-backed
- the theoretical heuristics/uncertainty book still ranks strongly, which is expected for this chapter spec
- after the inconsistency filter, the judge no longer incorrectly zeroes obviously relevant theory sections

### Paper-dump run

Run:

- `298d23d84ce6933a316dfa71`

Artifacts:

- `pdf-scan/runs/298d23d84ce6933a316dfa71/rerank/phase_f_summary.json`
- `pdf-scan/runs/298d23d84ce6933a316dfa71/phase_f_review/phase_f_review_summary.json`

Result:

- status: `success_with_warnings`
- reviewer category: `strong`
- candidate packs: `67`
- rerank results: `67`
- judged rows used in blending: `8`
- inconsistent judge rows filtered: `2`
- judge disagreement average: `0.21048441`
- latest Phase F OpenAI cost: `$0.008666`

Top reranked examples:

1. `The Trust Building Mechanisms in Social Commerce`
2. `Consumer Purchase Intention in Social Commerce`
3. `Consumers’ Decision-Making Process on Social Commerce Platforms`
4. `3.2 Identified Psychological Effects and Nudges`
5. `Information Overload in Online Platforms`
6. `Effects of Perceived Risk on Purchase Intention in Social Commerce`

Interpretation:

- the reranker now surfaces a diverse and substantively useful mix across trust, nudging, information overload, and review credibility
- top-20 coverage spans `6` documents, which is good for the per-PDF objective

## Model comparison

I ran a direct comparison on the same benchmark candidate packs.

Compared models:

- `BAAI/bge-reranker-v2-m3`
- `cross-encoder/ms-marco-MiniLM-L-6-v2`

Result:

- `BAAI/bge-reranker-v2-m3` produced meaningful separation and strong top results
- `cross-encoder/ms-marco-MiniLM-L-6-v2` collapsed to near-zero probabilities on the same long candidate packs and gave clearly worse rankings

Conclusion:

- keep `BAAI/bge-reranker-v2-m3` as the Phase F default
- do not use the MS MARCO MiniLM reranker as the default for this pipeline

## Problems found and fixed

### 1. Judge contradictions

Observed failure:

- some judge responses returned `usefulness_raw = 0`, `topic_match_raw = 0`, `coverage_raw = 0`
- the same row’s notes still said the section was highly relevant

Fix:

- detect contradiction between raw scores and notes
- mark row as inconsistent
- exclude it from score blending

### 2. Candidate pack ordering

Observed failure:

- long generic section text sometimes diluted strong supporting evidence

Fix:

- move supporting evidence ahead of the long section excerpt in the packed candidate text

### 3. Judge dominance

Observed failure:

- the judge could move a candidate too aggressively relative to the cross-encoder

Fix:

- lower `llm_judge_blend` to `0.20`

## Remaining caveats

- generic but content-rich sections like `Introduction` or `Conclusion` can still rank highly when they genuinely summarize the target concepts well
- this is acceptable for now because the pipeline objective is usefulness for writing, not only section-title specificity
- Phase G should still calibrate per-PDF usefulness and make the final abstention / confidence decision

## Recommendation

Phase F is good enough to continue.

Recommended next step:

- implement Phase G
- preserve all Phase F raw features
- calibrate per-PDF usefulness and explicit no-match behavior there

## Sources

- Hugging Face Transformers sequence classification docs: https://huggingface.co/docs/transformers/en/tasks/sequence_classification
- BAAI reranker model card: https://huggingface.co/BAAI/bge-reranker-v2-m3
- OpenAI structured outputs docs: https://platform.openai.com/docs/guides/structured-outputs
- OpenAI pricing: https://platform.openai.com/docs/pricing
