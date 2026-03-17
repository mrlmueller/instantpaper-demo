# Phase E Report

## Scope

Phase E is the high-recall candidate generation stage.

Input:
- normalized sections and passages from Phase C
- query plan and retrieval views from Phase D

Output:
- lane-level ranked candidates
- fused section candidate pool
- subpoint support inventory
- dense retrieval trace including embedding token usage and estimated cost

The point of Phase E is not to make the final relevance judgment. It builds a broad but structured candidate pool that later reranking and calibration stages can trust.

## Implementation

Primary implementation:
- `pdf-scan/phase_e_lab.py`

Notebook sync:
- `pdf-scan/pdf-scan-v3.ipynb`

Independent review:
- `pdf-scan/review_phase_e.py`

Key implementation decisions:
- hybrid retrieval across five lanes:
  - `section_title_lexical`
  - `section_body_lexical`
  - `section_dense`
  - `passage_lexical`
  - `passage_dense`
- reciprocal-rank style fusion across lane outputs
- xQuAD-style diversified selection across supported subpoints
- section-first final pool with passages stored as evidence
- explicit subpoint support gating before final selection
- OpenAI embedding cost tracking written into both:
  - `retrieval/phase_e_dense_trace.json`
  - `api_calls.jsonl`

Important fixes made during implementation:
- added explicit imports that the notebook-derived file was implicitly relying on
- fixed `qc_row(...)` usage to match the shared keyword-only signature
- added `record_api_call(...)` for embedding calls
- switched default embedding model from `text-embedding-3-large` to `text-embedding-3-small`
- verified pricing date/source and stored it in artifacts
- replaced the drifting notebook Phase E copy with a bridge notebook that runs the lab code

## Validation Loop

### 1. Benchmark baseline

Run:
- `2270646d3c56c160a8e30345`

Artifacts:
- `pdf-scan/runs/2270646d3c56c160a8e30345/retrieval/phase_e_summary.json`
- `pdf-scan/runs/2270646d3c56c160a8e30345/retrieval/phase_e_assessment.json`
- `pdf-scan/runs/2270646d3c56c160a8e30345/phase_e_review/phase_e_review_summary.json`

Result:
- status: `success`
- fused candidates: `115`
- supported subpoints: `3`
- dense mode: `openai`
- embedding input tokens: `632615`
- embedding estimated cost: `$0.0126523`

What this established:
- the phase ran end to end
- the hybrid lanes all produced usable candidates
- the fused pool was non-empty and structurally clean enough for continuation

### 2. Controlled variant comparison

#### Dense + `text-embedding-3-small`

Run:
- `2270646d3c56c160a8e30345`

Headline:
- `115` fused candidates
- `3` supported subpoints
- top-20 covers `4` documents
- dense support present in all top-10
- cost `$0.0126523`

#### Dense + `text-embedding-3-large`

Run:
- `690c6903817507a152d08fd6`

Artifacts:
- `pdf-scan/runs/690c6903817507a152d08fd6/phase_e_review/phase_e_review_summary.json`

Headline:
- `119` fused candidates
- `3` supported subpoints
- top-20 covers `4` documents
- cost `$0.0822393`

Conclusion:
- `3-large` cost about `6.5x` more than `3-small`
- it did not produce a clearly better top set
- it slightly increased some ethics-related concept hits in the reviewer, but not enough to justify the default cost jump

#### Lexical only

Run:
- `d11753d82d57507c6f9b0aad`

Artifacts:
- `pdf-scan/runs/d11753d82d57507c6f9b0aad/phase_e_review/phase_e_review_summary.json`

Headline:
- `115` fused candidates
- supported subpoints dropped from `3` to `2`
- average top-10 lane count dropped from `4.7` to `2.9`
- dense-only candidate count dropped to `0`
- cost `$0`

Conclusion:
- lexical-only stays functional
- but it loses semantic support and facet coverage
- dense retrieval is materially useful, not decorative

### 3. Wide-corpus validation on `paper-dump`

Run:
- `a5ee50a196ed4352bd37c6d6`

Artifacts:
- `pdf-scan/runs/a5ee50a196ed4352bd37c6d6/retrieval/phase_e_summary.json`
- `pdf-scan/runs/a5ee50a196ed4352bd37c6d6/retrieval/phase_e_assessment.json`
- `pdf-scan/runs/a5ee50a196ed4352bd37c6d6/phase_e_review/phase_e_review_summary.json`

Headline:
- `120` fused candidates
- all `4` live subpoints supported
- top-20 covers `5` documents
- top-10 spans:
  - social commerce risk/trust
  - digital nudging
  - nudging effectiveness
- dense support present in all top-10
- embedding input tokens: `1223531`
- embedding estimated cost: `$0.02447062`

Important result:
- the phase did not collapse onto the original 5 benchmark PDFs
- the candidate pool expanded into the new nudging-heavy papers as expected
- the hybrid retrieval setup stayed within a low cost envelope even on all `22` PDFs

## Why The Default Is `text-embedding-3-small`

This default was chosen after direct comparison, not by cost intuition alone.

Reasons:
- `3-small` preserved dense-lane usefulness
- `3-small` kept top-set diversity comparable to `3-large`
- `3-large` did not show enough benchmark improvement to justify the cost multiple
- the saved budget is better spent in later stages like reranking/calibration

Current default:
- embedding model: `text-embedding-3-small`
- dense retrieval: enabled
- selection strategy: `xquad`

Pricing reference verified during implementation:
- https://platform.openai.com/docs/pricing

## What Phase E Is Doing Well

- hybrid recall is real: dense lanes add candidates and subpoint support that lexical-only misses
- the fused pool is section-first and evidence-backed
- the phase respects per-document diversity better than a corpus-global greedy ranking
- subpoint gating prevents unsupported planner branches from driving candidate selection
- cost accounting is now first-class and persisted in run artifacts

## Remaining Weaknesses

- generic sections like `Introduction`, `Discussion`, or `Conclusion` still enter the top-20 in some runs
- the current independent reviewer still uses older static concept buckets (`SP1`-`SP6`) and can warn about unsupported conceptual branches even when Phase D has already suppressed them legitimately
- dense passage lanes can still concentrate on a relatively small number of documents in smaller corpora

These are not blockers for moving on, but they matter for interpretation:
- Phase E is a candidate generation phase, not the final ranking phase
- some over-broad sections are acceptable here if later reranking can demote them

## Final Assessment

Phase E is good enough to continue.

Why:
- benchmark run passed
- wide-corpus run passed
- dense retrieval was shown to be valuable
- the chosen default model was justified by direct comparison
- cost stayed low:
  - about `1.27` cents for the 5-document benchmark
  - about `2.45` cents for the 22-document dump run

Recommendation:
- freeze Phase E defaults for now
- move to the next phase
- come back only if later reranking shows a concrete upstream recall failure
