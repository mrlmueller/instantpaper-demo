# PDF Scan Pipeline Research Report

Date: 2026-03-14
Scope: digital PDFs only, per-document usefulness decisions, section/subsection-first ranking

## Executive Summary

The current `pdf-scan-v2.ipynb` is directionally correct because it preserves structure and ranks sections instead of arbitrary chunks. However, it is incomplete relative to the implementation plan and still fails in three important ways:

1. it does not yet produce a real per-PDF usefulness decision
2. it lacks a true reranking and calibration stage
3. its current query grounding and support logic create both false negatives and false positives

The best target system for this repo is:
- section-first
- per-document
- hybrid retrieval
- evidence-backed reranking
- explicit abstention per PDF

## Main Diagnosis

### What is already good

- The Phase A-E notebook layout is much better than the old vector-store-first notebook.
- The parser bundle idea is right.
- The canonical section / passage artifacts are the right direction.
- The run artifact design is good and worth keeping.

### What is broken or missing

#### 1. The notebook stops before the important decision phases

The plan clearly includes:
- Phase F reranking
- Phase G calibration and no-match decision
- Phase H final reporting
- Phase I benchmark harness

The current notebook ends after candidate generation, which is too early. Candidate generation is recall work, not final decision work.

#### 2. Query grounding is too literal

Current Phase D prunes many useful terms when they are not close enough to the exact chapter wording. This suppresses good lexical recall for:
- bilingual phrasing
- reasonable paraphrases
- legitimate domain expansions

#### 3. Support trust is too permissive

Current Phase E allows weak broad phrases and weak unigrams to contribute too much to trusted support. This makes semantically off-target sections look healthier than they are.

#### 4. The pipeline is still too corpus-global

The user’s real question is:
- what is useful in PDF A?
- what is useful in PDF B?
- and which PDFs have nothing useful?

The current fused retrieval still behaves more like pooled corpus retrieval than per-document screening.

#### 5. Section granularity is inconsistent

The normalized outputs currently mix:
- tiny near-empty sections
- useful subsection-sized sections
- overly broad parent sections that should be further constrained by evidence

## Recommended Target Architecture

### Output contract

The primary output should be one result object per PDF:

- `doc_id`
- `title`
- `useful_label`: `useful`, `partially_useful`, `not_useful`, `uncertain`
- `confidence`
- `decision_reason`
- `ranked_sections`

Each returned section should include:
- `section_id`
- `title_path`
- `page_start`
- `page_end`
- `section_type`
- `why_useful`
- `supported_subpoints`
- `evidence_passages`
- `section_confidence`

### Parsing and section construction

Recommended parser stack:
- `PyMuPDF` as deterministic geometry/text/outline lane
- `pypdf` as metadata + outline redundancy lane
- `Docling` as primary structured parse
- `GROBID` as optional scholarly enhancement lane

Recommended hard rule:
- if the PDF is not digitally readable and OCR would be required, emit `unsupported_requires_ocr`

Recommended long-document behavior:
- do not skip high-page-count documents only because they are long
- try full parse when runtime is acceptable and cache results
- otherwise split large PDFs into page windows and merge structure proposals
- keep outline-first fallback when strong bookmarks exist

### Canonical section graph

The canonical graph should be the stable truth used by later phases.

Recommended rules:
- preserve subsections whenever parser evidence supports them
- penalize or collapse sections under a minimum usable size
- flag giant sections that need stronger evidence-based narrowing
- retain parser provenance and anchor confidence

Important thresholds to tune:
- tiny section threshold: around `40-60` words
- minimum section threshold for standalone ranking: around `120-180` words
- giant section warning threshold: around `3000-5000` words

### Query planning

Replace the current over-literal grounding with a two-layer query plan:

1. source-grounded anchors
- terms clearly present in the chapter text

2. controlled expansions
- bilingual equivalents
- direct paraphrases
- narrow domain synonyms

Controlled expansions must be marked as expansions, not as source anchors.

Recommended rule:
- do not let the planner invent new topical branches
- do allow valid EN/DE equivalents and narrow paraphrases

### Retrieval

Retrieval should run per document, not globally first.

Recommended first-stage lanes per document:
- section title BM25
- section body BM25
- section dense embeddings
- optional passage dense evidence lane

Recommended dense default:
- `text-embedding-3-small` for recall

Reason:
- the observed corpus size is small enough that reranking quality matters more than premium embedding spend
- local cost estimates from the existing run support this

### Reranking

This is the largest missing part of the notebook.

Recommended reranking design:
- rerank sections per document
- use passages only as evidence for the section judgment
- score top-K candidate sections with a cross-encoder or LLM judge

Practical strategy by document size:
- small / medium PDFs: rerank all candidate sections or all non-penalized sections
- long / very long PDFs: rerank the top `15-30` retrieved sections

Recommended rerank output fields:
- direct topical match
- subpoint support
- specificity vs genericity
- evidence strength
- confidence
- abstain indicator

### Calibration and no-match

Per-document abstention must be explicit.

Recommended decision features:
- best rerank score
- gap between top useful and top non-useful candidate
- number of independently supported subpoints
- evidence agreement across retrieval lanes
- lexical / phrase anchor quality
- section type penalties

Recommended document decision logic:
- `useful` if one or more sections pass a calibrated threshold with strong evidence
- `partially_useful` if only narrow or weakly supported sections pass
- `not_useful` if no section reaches the calibrated threshold
- `uncertain` if signals disagree strongly

## Concrete Changes Recommended For `pdf-scan-v2.ipynb`

### Phase B

- Stop using page count alone as the Docling skip gate.
- Add stronger per-document parser diagnostics:
  - Docling confidence grades
  - outline agreement
  - block-order anomalies
  - heading disagreement count

### Phase C

- Add a tiny-section cleanup pass.
- Add a giant-section warning / subdivision pass.
- Preserve subsection structure more aggressively when Docling provides it.
- Add stronger heading-anchor diagnostics.

### Phase D

- Split terms into:
  - `source_anchors`
  - `controlled_expansions`
- Do not drop valid English / German equivalents just because they are not literal.
- Add explicit provenance tags for each term.

### Phase E

- Change retrieval from pooled corpus-first to per-document candidate generation.
- Keep diversified subpoint coverage, but apply it inside each document.
- Tighten trusted-support logic:
  - broad unigrams alone should never yield trusted support
  - generic phrases like `risk`, `trust`, `confidence`, `uncertainty` need stronger co-evidence

### New Phase F

- Add section reranking.
- Save rerank artifacts as JSONL for each document.
- Include evidence passages and judge rationale fields.

### New Phase G

- Add per-document usefulness classification.
- Persist decision thresholds and confidence features.
- Emit explicit no-match reasons.

### New Phase H

- Final report should be grouped by document.
- Each document should show:
  - decision
  - top sections
  - page spans
  - evidence
  - why / why not

### New Phase I

- Add a benchmark harness over chapter specs x PDF pools.
- Persist judged outputs and metrics per run.

## Parameter And Technique Levers Worth Tuning

These are the highest-value knobs to test:

### 1. Embedding model

- default candidate generation with `text-embedding-3-small`
- compare against `text-embedding-3-large` only on judged benchmarks

### 2. Candidate quotas per document

- small docs: rerank nearly everything
- medium docs: rerank top `20-40`
- very long docs: rerank top `25-50` after hybrid recall

### 3. Support trust rules

Potential stricter rules:
- require phrase hit or multi-signal agreement
- require one lexical lane plus one semantic lane
- require evidence passage support for generic section titles

### 4. Section-type priors

Tune preferences by chapter type:
- background-heavy chapters should favor introduction / background / discussion
- measurement-heavy chapters should upweight methods / appendix

### 5. Passage construction

Test passage sizes around:
- target `120-180` words for dense evidence
- upper bound `220-260` words

Reason:
- smaller evidence units reduce topic bleed inside large sections

### 6. Long-document handling

Test:
- full-parse caching
- page-window parse-and-merge
- outline-first with targeted validation

## Benchmark And Test System

### Immediate benchmark truth

The current `small_gold` suite is not yet a gold benchmark. It is a candidate pool with:
- 1 chapter spec
- 5 PDFs
- no judgments

So the immediate next step is annotation, not leaderboard reporting.

### Recommended benchmark layers

#### Layer 1: Pilot judged suite

Use the existing chapter:
- `chapter_001_webshop_decision_psychology`

Judge all 5 current PDFs for:
- document usefulness label
- relevant section ids / page spans
- supported subpoints
- negative / trap notes

#### Layer 2: Multi-chapter core suite

Add `4-7` more chapter specs with different profiles:
- technical architecture chapter
- methods / measurement chapter
- theory / psychology chapter
- policy / standards chapter
- highly specific niche chapter

Good seed already present in repo history / notebooks:
- the Zero Trust Architecture chapter from the older notebook can become one core benchmark query

#### Layer 3: Hard negatives

For each chapter, include:
- lexical-overlap negative PDFs
- generic survey negatives
- method-only negatives
- clearly irrelevant negatives

### Recommended labels

Document-level label:
- `2 = useful`
- `1 = partially_useful`
- `0 = not_useful`

Section-level label:
- `2 = highly_useful`
- `1 = useful_but_limited`
- `0 = not_useful`

### Recommended metrics

Document-level:
- precision / recall / F1 on usefulness
- macro-F1 across chapter specs
- risk-coverage curve for abstention

Section-level:
- Recall@k
- nDCG@k with graded section labels

Evidence-level:
- evidence precision
- judged page-span overlap

Operational:
- parser failure rate
- unsupported-digital-PDF rate
- mean runtime by length bucket
- API cost by phase and by PDF

### Recommended benchmark artifact layout

Per chapter suite:
- `chapter_spec.json`
- `document_manifests/*.json`
- `judgments/*.json`
- `expected_outputs/*.json` optional later

Per judgment file:
- document usefulness label
- relevant sections
- page spans
- supported subpoints
- notes on traps and exclusions

## Other Important Observations

### 1. Global fusion should stop being the user-facing worldview

Cross-document fusion is still useful internally, but the user-facing result should be per-document. This better matches the real task and reduces domination by one very strong source.

### 2. The current phase assessments are too optimistic

The existing QC summaries often declare success even when semantic quality is visibly weak. Future phase assessments should incorporate judged relevance signals once benchmark data exists.

### 3. Generic section titles need stricter handling

Sections named `Introduction`, `Background`, `Discussion`, or `Research Design` are not useful just because one evidence passage matches. Generic titles need stronger evidence agreement.

### 4. Book-length documents are not the same task as article-length documents

The 598-page `Judgment under Uncertainty` PDF surfaces different issues:
- broader conceptual drift
- large internal topical spread
- many sections with plausible but weak overlap

This should be handled explicitly with long-document heuristics and stricter calibration.

## Recommended Build Order

1. Add judged labels for the current 5-PDF pilot suite.
2. Implement Phase F reranking and Phase G per-document calibration.
3. Refactor Phase E to run per-document retrieval.
4. Tighten query grounding and support trust logic.
5. Improve long-document parsing strategy.
6. Expand benchmark chapters and hard negatives.

## Source Links

- Docling Quickstart: `https://docling-project.github.io/docling/getting_started/quickstart/`
- Docling Advanced options: `https://docling-project.github.io/docling/usage/advanced_options/`
- Docling Chunking: `https://docling-project.github.io/docling/concepts/chunking/`
- Docling Confidence Scores: `https://docling-project.github.io/docling/concepts/confidence_scores/`
- Docling Pipeline options: `https://docling-project.github.io/docling/reference/pipeline_options/`
- Docling Technical Report: `https://arxiv.org/abs/2408.09869`
- PyMuPDF text extraction docs: `https://pymupdf.readthedocs.io/en/latest/recipes-text.html`
- PyMuPDF TOC docs: `https://pymupdf.readthedocs.io/en/latest/document.html#Document.get_toc`
- pypdf extract-text docs: `https://pypdf.readthedocs.io/en/stable/user/extract-text.html`
- pypdf outline docs: `https://pypdf.readthedocs.io/en/latest/user/handling-outlines.html`
- GROBID REST API docs: `https://grobid.readthedocs.io/en/latest/Grobid-service/`
- Detect-Order-Construct: `https://arxiv.org/abs/2401.11874`
- BEIR: `https://arxiv.org/abs/2104.08663`
- ColBERT: `https://arxiv.org/abs/2004.12832`
- Sentence Transformers retrieve-rerank docs: `https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html`
- OpenAI pricing: `https://platform.openai.com/docs/pricing`
- OpenAI embeddings:
  - `https://developers.openai.com/api/docs/models/text-embedding-3-small`
  - `https://developers.openai.com/api/docs/models/text-embedding-3-large`
- xQuAD reference: `https://ir.webis.de/anthology/2010.ecir_conference-2010.11/`
- SelectiveNet: `https://arxiv.org/abs/1901.09192`
- Calibrated selective classification: `https://arxiv.org/abs/2208.12084`
- M-LongDoc: `https://arxiv.org/abs/2411.06176`
