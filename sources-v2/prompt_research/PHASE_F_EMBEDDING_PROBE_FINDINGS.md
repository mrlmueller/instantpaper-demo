# Phase F Embedding Probe Findings

Date: 2026-03-09

Scope:
- replayed Phase F embedding/ranking ideas on two cached runs:
  - `ed2e3d3304d5ed9587592f4d` (online reviews / proxy-operationalization methods chapter)
  - `ca79147de41f8edbfb47c9e5` (late-antique / Western Roman Empire hard-topic chapter)
- used the actual Phase D raw retrieval outputs, rebuilt a deduplicated candidate pool locally, and compared multiple embedding/ranking variants against the same candidate sets

Artifacts:
- script: `phase_f_embedding_probe.py`
- main result JSON: `probe_outputs/phase_f_embedding_probe_20260309-172208.json`
- markdown summary: `probe_outputs/phase_f_embedding_probe_20260309-172208.summary.md`
- per-variant top-20 CSVs: `probe_outputs/phase_f_top20_<run>_<variant>.csv`

Cost:
- estimated total probe cost: `$0.8492`
- actual final resumed run spend: `$0.5925`
- total known spend across the full probe including cached earlier passes: about `$0.85`
- this stayed within the `$1.00` cap

## Variants tested

- `topic_doc_small`
- `topic_doc_large`
- `summary_doc_small`
- `facet_meta_small`
- `facet_doc_small`
- `facet_doc_large`
- `hybrid_small`
- `hybrid_large`
- `staged_small`

Definitions:
- `topic_doc_*`: chapter title + chapter spec + planner summaries vs candidate doc text
- `summary_doc_small`: condensed chapter target with title, summaries, anchors, and core object terms
- `facet_meta_small`: weighted facet matching against metadata-only candidate text
- `facet_doc_*`: weighted facet matching against candidate doc text
- `hybrid_*`: facet-doc score + topic-doc score
- `staged_small`: `hybrid_small` stage 1 plus chunk rerank on abstract-bearing shortlist, with a diversity-aware final top 20

Candidate packaging used in the probe:
- metadata: title + year + venue + authors
- doc text: metadata + abstract truncated to `800` chars
- chunk text: sentence-like abstract chunks up to about `420` chars, on a shortlist only

## Main findings

### 1. `text-embedding-3-large` did not justify itself

Across both runs, the larger embedding model did not beat the small model on the outcomes that matter:
- cross-run average `top20_title_core_hit_rate`:
  - `topic_doc_small`: `0.475`
  - `topic_doc_large`: `0.475`
  - `hybrid_small`: `0.475`
  - `hybrid_large`: `0.350`
- cross-run average `top20_abstract_core_hit_rate`:
  - `topic_doc_small`: `0.800`
  - `topic_doc_large`: `0.800`
  - `hybrid_small`: `0.750`
  - `hybrid_large`: `0.625`

Qualitatively, the large-model variants were often a bit broader or more generic. They were not clearly worse everywhere, but they were not clearly better anywhere important enough to justify the extra cost and runtime.

Recommendation:
- keep `text-embedding-3-small` as the default Phase F model for now
- only revisit `large` later if a future benchmark shows a measurable top-k gain on judged chapters

### 2. metadata-only ranking is too weak

`facet_meta_small` consistently underperformed the doc-based variants. It can retrieve some obviously relevant papers, but it misses too much abstract-level evidence.

Cross-run averages:
- `facet_meta_small`:
  - `top20_abstract_core_hit_rate = 0.450`
  - `top20_mean_pairwise_similarity = 0.490`
- `staged_small`:
  - `top20_abstract_core_hit_rate = 0.825`
  - `top20_mean_pairwise_similarity = 0.515`

Recommendation:
- do not rely on metadata-only embeddings as the main scorer
- keep metadata embeddings only as a fallback for candidates without abstracts

### 3. richer chapter-target text works better than facet-only scoring

The strongest stage-1 signals came from query-side texts that preserved the whole chapter target:
- `summary_doc_small`
- `topic_doc_small`
- `hybrid_small`

Pure facet scoring was not enough, especially on the hard historical chapter. The embedding query needs the chapter object and the chapter-level explanatory target, not just facet narratives.

Recommendation:
- add a chapter-target embedding text to Phase F
- include chapter title, retrieval contract/spec, planner summaries, and core object terms
- use facet texts as a supporting signal, not the only signal

### 4. second-stage chunk rerank is worth keeping

`staged_small` was the best overall compromise across the two runs.

Cross-run averages:
- `staged_small`:
  - `top20_title_core_hit_rate = 0.525`
  - `top20_abstract_core_hit_rate = 0.825`
  - `top20_mean_pairwise_similarity = 0.515`
- `hybrid_small`:
  - `top20_title_core_hit_rate = 0.475`
  - `top20_abstract_core_hit_rate = 0.750`
  - `top20_mean_pairwise_similarity = 0.543`

On the Roman hard-topic run specifically:
- `hybrid_small` title-core hit rate: `0.35`
- `staged_small` title-core hit rate: `0.55`

On the online-reviews run, `staged_small` also brought in more method/proxy/preprocessing papers than the more generic review-heavy `summary_doc_small` ranking.

Recommendation:
- keep a two-stage design
- use doc-level ranking first
- rerank a shortlist with abstract chunks

### 5. diversity control helped on the final top 20

The probe used a simple MMR-like diversity step only on the final `staged_small` top 20. That helped reduce near-duplicates and lowered average pairwise similarity without collapsing relevance.

This matters because Phase F is not only about “most similar”; it is also about surfacing a useful spread of evidence and viewpoints.

Recommendation:
- add duplicate suppression and a light diversity step near the end of Phase F
- do not overdo it; a mild penalty is enough

## Topic-specific observations

### Online reviews / proxy-operationalization chapter

Best usable variants:
- `staged_small`
- `hybrid_small`

Why:
- they retrieved not only generic online-review literature reviews, but also papers on:
  - aspect extraction
  - text filtering / preprocessing
  - German review corpora
  - bias/fairness in review data
  - proxy-style causal or multi-aspect analysis

Weak pattern:
- `summary_doc_small` and `topic_doc_small` were good at surfacing broad online-review literature, but were more likely to over-weight helpfulness/review-overview papers

### Roman hard-topic chapter

Best usable variants:
- `staged_small`
- `topic_doc_small`
- `summary_doc_small`

Why:
- the candidate pool is sparse and noisy, so query-side richness matters more than facet-only matching
- `staged_small` improved object retention and diversity

Weak pattern:
- even the best variants still surfaced broad “fall of Rome / Late Antiquity” contextual papers that are only indirectly about economic explanations
- this is a candidate-pool quality limit as much as an embedding limit

## Critical non-embedding issues surfaced by the probe

### 1. duplicate candidate leakage

The rebuilt candidate pools still contained duplicate titles:
- Roman run: `24` duplicate normalized titles
- online-reviews run: `654` duplicate normalized titles

Duplicates even reached some top-20 outputs in several variants.

Implication:
- Phase E dedup / identity resolution still needs work
- otherwise Phase F can waste top slots on multiple copies of the same paper

### 2. metadata junk is present in the pool

The online-reviews pool still contains obvious low-value titles such as:
- `index`
- `references`
- `table of contents`
- `editorial`
- `book reviews`

These did not dominate the best top-20 rankings here, but they should be filtered before embeddings.

### 3. title cleaning still matters

The probe surfaced raw HTML artifacts and formatting noise in some titles, for example:
- `&lt;em&gt;...&lt;/em&gt;`
- inline HTML / superscript markup

That hurts both ranking quality and output readability.

## Practical Phase F recommendations

1. Keep `text-embedding-3-small` as the default.
2. Add a chapter-target embedding text:
   - chapter title
   - chapter retrieval contract/spec
   - planner summaries
   - core object terms / anchors
3. Keep candidate doc embeddings as the main representation:
   - title
   - year
   - venue
   - authors
   - abstract snippet
4. Keep metadata-only embeddings only as fallback for no-abstract candidates.
5. Keep a second-stage chunk rerank on the shortlist.
6. Add light diversity control and strict duplicate suppression before the final top-k.
7. Clean candidates before embedding:
   - strip HTML artifacts
   - drop index/editorial/table-of-contents style records
   - tighten dedup
8. Treat pure facet-only scoring as supplemental, not as the main scorer.

## Bottom line

The probe result is good enough to move forward with Phase F implementation work.

The most important result is not “use the larger model.” It is the opposite:
- `small` is good enough
- richer chapter-target text matters more than model size
- chunk rerank and candidate hygiene matter more than switching to `large`
