# Web Research - Benchmarking And Evaluation

Purpose:
- Capture external findings on evaluating document retrieval, section ranking, passage evidence quality, abstention, and benchmark suite design.

## Primary Sources Reviewed

- BEIR benchmark paper: `https://arxiv.org/abs/2104.08663`
- M-LongDoc benchmark paper: `https://arxiv.org/abs/2411.06176`
- Calibrated selective classification: `https://arxiv.org/abs/2208.12084`
- SelectiveNet: `https://arxiv.org/abs/1901.09192`

## Source-Based Findings

### 1. The benchmark must test heterogeneity, not just one topic

BEIR’s core lesson is that narrow, homogeneous evaluation badly overestimates generalization. That transfers directly here:
- one chapter topic is not enough
- one document style is not enough
- one PDF length bucket is not enough

M-LongDoc reinforces this from the long-document side:
- long multimodal / long-context document understanding benchmarks surface different failure modes than short-document tests

Implication:
- the local small-gold suite is useful but not sufficient

### 2. This project needs judged negatives, not only judged positives

Because the user explicitly wants:
- useful sections per PDF
- and explicit "nothing useful here" decisions

the benchmark must include:
- positive documents with clearly useful sections
- partially relevant documents
- high-overlap but misleading negatives
- clearly irrelevant negatives

### 3. Evaluate both ranking quality and abstention quality

Inference from retrieval and selective-prediction literature:
- section ranking alone is not enough
- document-level accept / abstain quality is a separate metric family

Recommended evaluation layers:
- document usefulness detection
- section ranking
- evidence quality
- abstention calibration

### 4. Coverage-risk evaluation is appropriate for no-match behavior

Selective prediction literature suggests evaluating models by how error changes as coverage changes. That idea transfers well here:
- coverage = fraction of PDFs for which the system claims useful content
- risk = fraction of those accepted PDFs that are wrongly accepted

This is an inference from selective-classification sources, adapted to per-PDF relevance detection.

## Recommended Benchmark Design For This Repo

### A. Benchmark objects

Each chapter spec should have:
- `chapter_id`
- `title`
- `description`
- optional `subpoints`

Each PDF should have:
- `doc_id`
- metadata manifest
- page count bucket
- doc type bucket

Each chapter x document judgment should contain:
- `doc_useful_label`: `useful`, `partially_useful`, `not_useful`
- `doc_useful_confidence`
- `notes`

If useful or partially useful:
- judged relevant section ids or page spans
- optional subsection ids
- supported subpoints
- evidence notes

### B. Metrics

Document-level:
- precision / recall / F1 for `useful` vs `not useful`
- separate score for strict positive-only (`useful`) and lenient positive (`useful` + `partially_useful`)
- risk-coverage curve for abstention threshold tuning

Section-level:
- Recall@k on relevant sections
- nDCG@k with graded labels:
  - 2 = highly useful
  - 1 = partially useful
  - 0 = not useful

Evidence-level:
- page-span overlap with judged pages
- evidence precision: fraction of returned evidence passages that truly support the claimed section usefulness

### C. Suite composition

Minimum recommended suite after expansion:
- 5 to 8 chapter specs
- 8 to 15 PDFs per chapter pool
- document length buckets:
  - short: 2-10 pages
  - medium: 11-40 pages
  - long: 41-120 pages
  - very long: 121-400+ pages

Document role buckets:
- clearly relevant
- relevant only in one subsection
- partial thematic overlap
- lexical trap negative
- generic methods / survey trap
- clearly irrelevant negative

### D. Practical next step from the current repo

The existing `small_gold` suite should become:
- a judgment pilot suite
- not yet the final benchmark

Immediate annotation target:
- the 5 existing PDFs for the current webshop decision-psychology chapter
- add explicit document-level and section-level labels
- use that to calibrate the next pipeline iteration before expanding to more chapters

Questions to answer here:
- What is the right benchmark unit: document, section, subsection, or passage?
- Which metrics should be used for per-document usefulness detection?
- How should judged negatives and abstention quality be evaluated?
- How should long vs short PDFs be represented in the suite?
