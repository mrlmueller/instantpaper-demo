# PDF Scan Pipeline Implementation Plan

Scope:

- target implementation file later: `pdf-scan/pdf-scan-test.ipynb`
- goal: rank the most useful sections / chapters from one or more digital PDFs for a user-provided chapter description
- this file is an implementation blueprint, not code

## Executive Decision

The rebuilt pipeline should not be a better version of the current chunk-first vector-store notebook.

It should be a new section-first pipeline with these core properties:

1. parse PDFs into a canonical structured document model
2. rank sections directly
3. use passages only as evidence for section ranking
4. combine high-recall retrieval with strong reranking
5. explicitly support `no useful information in this PDF`
6. emit rich run artifacts and per-phase summaries

## Design Principles

### 1. Rank the right unit

The main output is:

- ranked sections / chapters

Not:

- anchors
- arbitrary chunks
- generated summaries detached from structure

### 2. Preserve structure as long as possible

Do not flatten the PDF too early.

Preserve:

- outline / bookmarks
- section titles
- section hierarchy
- page spans
- section type
- parser provenance

### 3. Prefer explicit contracts between phases

Every phase must emit strict, inspectable artifacts that the next phase can consume without implicit assumptions.

### 4. Keep the notebook operationally transparent

Model the notebook style after `sources-v2/sources_two_lane.ipynb`:

- run id
- `runs/{run_id}/`
- JSON / JSONL artifacts
- structured logs
- compact end-of-cell QC summaries

### 5. Separate high recall from high precision

Do not try to solve both in one model call.

- retrieval phase optimizes recall
- reranking phase optimizes precision
- calibration phase controls user-facing confidence

## Phase Map

The rebuilt notebook should be organized into these phases.

## Phase A — Config, Run Context, Artifact Skeleton

### Purpose

Create a reproducible run environment before any PDF or LLM work happens.

### Inputs

- `chapter_title`
- `chapter_spec_text`
- `pdf_paths`
- `pipeline_version`
- environment variables

### Outputs

- `run_id`
- `run_dir`
- `config.json`
- `pdf_manifest.json`
- `logs.jsonl`
- `metrics.json`

### Implementation

Use:

- one config surface via `pydantic`
- stable `run_id` derived from chapter input + pipeline version + document hashes
- artifact paths created up front

### Required QC

- all PDF paths exist
- all PDFs are readable
- file sizes and page counts are available
- environment keys are validated

### Why this phase matters for later phases

Later phases will write many intermediate artifacts. Without a strong run context, debugging parser disagreements or retrieval failures becomes painful very quickly.

## Phase B — Document Parsing Bundle

### Purpose

Build a raw parse bundle for each PDF using complementary parsers and metadata sources.

### Inputs

- one PDF path

### Outputs

Per document:

- `metadata.json`
- `docling.json`
- `grobid.tei.xml` when applicable
- `pymupdf_blocks.jsonl`
- parser diagnostics

### Recommended parser stack

#### Always run

- Make sure that they parser can actually read the PDF, meaning implement some logic here that checks if there is
  actual text in there that can be extracted or if we would need OCR (in which case we just return that we cant read the pdf)

- `pypdf` or `PyMuPDF` for:
  - page count
  - metadata
  - outline / bookmarks
- `Docling` for:
  - structured primary parse
  - rich document abstraction
- `PyMuPDF` blocks / words for:
  - deterministic fallback
  - boundary validation

#### Run when likely scholarly / report-like

- `GROBID`

Use GROBID when the document looks like:

- article
- report
- survey
- standard-like prose PDF

### Why this is the right stack

- `Docling` is the best primary bridge into structure-aware chunking.
- `GROBID` is the most relevant scholarly enhancement for scientific literature.
- `PyMuPDF` is the most important deterministic fallback.
- outlines/bookmarks are high-precision chapter signals when present.

### Required QC

For each document, report:

- parser success / failure
- whether outline data exists
- whether Docling parse exists
- whether GROBID parse exists
- percent of pages with extracted body text
- fallback activation

### Contract into Phase C

Phase B must not emit one flattened text string.

It must emit a `ParsedDocumentBundle` with:

- metadata
- structure proposals
- layout proposals
- raw parser provenance

## Phase C — Canonical Section Graph And Passage Construction

### Purpose

Convert the parse bundle into a single canonical structure the rest of the pipeline can trust.

### Inputs

- `ParsedDocumentBundle`

### Outputs

- `documents.jsonl`
- `sections.jsonl`
- `passages.jsonl`

### Canonical objects

#### `DocumentRecord`

- `doc_id`
- `source_path`
- `sha256`
- `title`
- `page_count`
- `language_guess`
- `doc_type_guess`
- `has_outline`

#### `SectionRecord`

- `doc_id`
- `section_id`
- `parent_section_id`
- `level`
- `title`
- `title_path`
- `section_type`
- `page_start`
- `page_end`
- `char_len`
- `text`
- `contextualized_text`
- `parser_sources`
- `quality_flags`

#### `PassageRecord`

- `doc_id`
- `section_id`
- `passage_id`
- `passage_index`
- `text`
- `contextualized_text`
- `page_span`
- `token_len`

### Section-construction rules

Structural signal priority:

1. outline / bookmarks
2. Docling hierarchy
3. GROBID section structure
4. PyMuPDF heading heuristics

Mandatory section types:

- `front_matter`
- `abstract`
- `introduction`
- `background`
- `related_work`
- `methods`
- `results`
- `discussion`
- `conclusion`
- `body_other`
- `references`
- `appendix`
- `acknowledgements`
- `table_of_contents`

### Passage construction rules

Use:

- section as the primary unit
- passage as the evidence unit

Preferred chunker:

- `Docling HybridChunker`

Fallback:

- paragraph-first chunking inside the section
- token-window fallback only when paragraphs are too long

Every passage must include:

- its `title_path`
- document title if available

This is required because long-document retrieval degrades badly when passage context is missing.

### Required QC

- no orphan passages
- every passage maps to exactly one section
- body text coverage exceeds threshold
- references / appendix are detected and tagged
- no overlapping section spans except explicitly allowed cases

### Contract into Phase D and E

This phase is the linchpin. If the section graph is weak, retrieval will collapse back into chunk semantics.

Therefore the outputs of Phase C must already be retrieval-ready:

- clean text
- title path
- section type
- page span
- provenance

## Phase D — Query Planner And Retrieval Views

### Purpose

Turn the chapter input into a structured retrieval plan rather than one opaque search string.

### Inputs

- `chapter_title`
- `chapter_spec_text`

### Outputs

- `query_plan.json`

### Recommended query-plan schema

- `query_id`
- `chapter_title`
- `chapter_summary`
- `must_terms`
- `should_terms`
- `exclusions`
- `subpoints`
- `language_hints`
- `preferred_section_types`
- `penalized_section_types`
- `drift_risks`

### Recommended implementation

Use OpenAI structured outputs with strict schema validation.

Why:

- more reliable contracts than free-form JSON
- easier caching
- easier benchmarking

### Important validation rules

- no empty chapter summary
- no invented topics outside the original chapter scope
- exclusions must be short and concrete
- subpoints must be deduplicated

### Derived retrieval views

From one query plan, derive several retrieval views:

- `title_lexical`
- `summary_semantic`
- `must_terms_lexical`
- `subpoint_views[]`
- `broad_fallback`

### Required QC

- query plan schema passes
- must terms are non-empty when possible
- subpoint count is reasonable
- drift risks are logged

### Contract into Phase E

Phase E should never reconstruct queries from raw chapter text again. It should consume only the normalized `QueryPlan`.

## Phase E — High-Recall Candidate Generation

### Purpose

Generate a broad but high-quality candidate section pool.

### Inputs

- `SectionRecord[]`
- `PassageRecord[]`
- `QueryPlan`

### Outputs

- lane-specific retrieval files
- `fused_candidates.jsonl`

### Recommended retrieval design

Use a local hybrid retrieval stack with multiple lanes.

Required lanes:

1. section-title lexical retrieval
2. section-body lexical retrieval
3. section dense retrieval
4. passage lexical retrieval
5. passage dense retrieval

Passage retrieval must map back to section ids.

### Why local retrieval is the default recommendation

For this task:

- number of PDFs per run is small
- control and debuggability matter
- structure-aware units matter more than hosted convenience
- the current hosted vector-store approach imposes result ceilings and chunking assumptions

### Fusion strategy

Use Reciprocal Rank Fusion across retrieval lanes.

Why:

- robust to incomparable score scales
- strong practical hybrid baseline
- easy to inspect

### Optional future lane

If the benchmark later shows persistent recall gaps, add:

- late-interaction retrieval, e.g. ColBERT-style

Not required for the first rebuild.

### Required QC

- candidate counts by lane
- overlap between lanes
- fraction of candidates coming only from passage lanes
- section-type distribution of top fused candidates

### Contract into Phase F

Every fused candidate must include:

- `section_id`
- `doc_id`
- component lane scores
- supporting passage ids
- fused rank

Without that, reranking loses evidence traceability.

## Phase F — Section Reranking

### Purpose

Turn a high-recall candidate set into a high-precision section ranking.

### Inputs

- top fused candidates
- supporting passages
- `QueryPlan`

### Outputs

- `cross_encoder.jsonl`
- `llm_judge.jsonl` if enabled
- unified rerank result table

### Recommended reranking stack

#### Mandatory

- local cross-encoder reranker over top section candidates

#### Optional

- OpenAI LLM judge over a smaller top subset

### Why this order

Cross-encoders are strong and cheaper than asking an LLM to score every candidate.

The LLM judge should be used only when:

- the candidate set is already small
- supporting passages are already known
- the question is now usefulness, not discovery

### LLM judge output

Strict schema, including:

- `usefulness_raw`
- `topic_match_raw`
- `coverage_raw`
- `exclusion_violations`
- `top_evidence_passage_ids`
- `notes`

### Required QC

- reranked candidate count
- score distribution
- disagreement between cross-encoder and LLM judge
- top candidates per PDF

### Contract into Phase G

Phase G needs rich rerank features, not only one final score. Keep all raw component scores.

## Phase G — Calibration And No-Match Decision

### Purpose

Convert rerank signals into stable user-facing scores and decide whether a PDF contains useful information at all.

### Inputs

- rerank outputs
- calibration model or provisional thresholds

### Outputs

- `per_pdf_rankings.json`
- `global_rankings.json`
- `output.json`

### Section-level output

For each section:

- `score_0_to_100`
- `score_band`
- `support_strength`
- `subpoint_coverage`
- `evidence_preview`

### Document-level output

For each PDF:

- `has_useful_information`
- `doc_match_probability`
- `top_section_id`
- `top_section_score`
- `abstention_reason`

### Recommended no-match design

Use document-level features such as:

- top section score
- top-3 mean
- top-1 vs top-2 margin
- number of sections above threshold
- coverage across subpoints
- whether only penalized section types ranked highly

Then:

- calibrate a `has_useful_information` classifier once labels exist
- use conservative provisional rules before calibration exists

### Recommended calibration tool

Start with:

- `CalibratedClassifierCV`

Why:

- simple
- robust
- standard

### Optional future uncertainty layer

Consider:

- MAPIE / conformal prediction

only after a benchmark exists.

### Required QC

- number of PDFs classified as useful
- number classified as no-match
- threshold/margin diagnostics
- sections just below and just above threshold

## Phase H — Final Notebook Reporting And Artifact Presentation

### Purpose

Make the notebook easy to audit.

### Requirements

Each major cell ends with:

1. `What happened`
2. `Artifacts written`
3. `Key counts`
4. `QC table`
5. `Preview rows`

### Output style target

Match the spirit of `sources_two_lane.ipynb`:

- detailed enough to debug
- compact enough to scan
- explicit about costs, timings, and failures

## Phase I — Benchmark Harness

### Purpose

Provide a real measurement loop before tuning further.

### Inputs

- labeled corpus
- labeled section judgments
- fixed query suite

### Outputs

- `nDCG@3`
- `nDCG@5`
- `Recall@3`
- `Recall@5`
- `MRR`
- no-match accuracy
- calibration diagnostics
- per-slice error analysis

### Why this phase is mandatory

Without it, every later pipeline tweak becomes anecdotal.

## Recommended Build Order

Do not implement all phases at once.

Implement in this order:

1. Phase A
2. Phase B
3. Phase C
4. Phase H-style summaries for A-C
5. Phase D
6. Phase E with only lexical + dense baseline lanes
7. Phase F with only cross-encoder reranking
8. Phase G provisional no-match rules
9. Phase I benchmark harness
10. optional LLM judge and advanced late-interaction lane

## What Should Be Explicitly Dropped From The Old Pipeline

Do not carry forward these old assumptions:

- raw uploaded PDF chunks as the main ranking unit
- one global search string as the primary retrieval representation
- score generation directly from limited evidence snippets
- anchor extraction as the center of the design
- hosted vector-store result caps as the main recall budget

## What Should Be Preserved From The Old Pipeline

These ideas are still useful:

- chapter query decomposition
- strict schema outputs
- detailed cost tracking
- per-stage diagnostics
- multi-PDF support

## Key Risk Areas To Watch During Implementation

### 1. Parser disagreement

This is normal. Preserve provenance and add QC rather than forcing brittle silent merges.

### 2. Section-boundary quality

If section boundaries are weak, reranking will become noisy even with good models.

### 3. Over-aggressive filtering

References and appendices should usually be penalized, but not always dropped.

### 4. Fake score precision

Do not advertise `0..100` as calibrated until benchmark labels support it.

### 5. Hidden notebook coupling

Every phase should read artifacts from disk when practical, not only in-memory variables. That keeps runs reproducible and debuggable.

## Final Recommendation

The strongest implementation path is:

- primary parser: Docling
- scholarly enhancement: GROBID
- deterministic fallback and validation: PyMuPDF + pypdf
- canonical ranking unit: section
- evidence unit: passage
- candidate generation: local hybrid retrieval with RRF
- reranking: cross-encoder first, optional LLM judge second
- final decision: calibrated section scores plus explicit document no-match detection
- notebook UX: `sources_two_lane.ipynb`-style artifacts, logs, and summaries

This plan directly fixes the main problems identified in the old pipeline instead of tuning around them.

## Source Links

- OpenAI retrieval guide: https://developers.openai.com/api/docs/guides/retrieval
- OpenAI file search guide: https://developers.openai.com/api/docs/guides/tools-file-search
- OpenAI structured outputs: https://openai.com/index/introducing-structured-outputs-in-the-api/
- PyMuPDF text recipes: https://pymupdf.readthedocs.io/en/latest/recipes-text.html
- PyMuPDF4LLM: https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/index.html
- pypdf extraction guide: https://pypdf.readthedocs.io/en/stable/user/extract-text.html
- GROBID principles: https://grobid.readthedocs.io/en/latest/Principles/
- Docling docs: https://docling-project.github.io/docling/
- Docling chunking: https://docling-project.github.io/docling/concepts/chunking/
- Sentence Transformers retrieve & rerank: https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html
- Elastic hybrid search: https://www.elastic.co/elasticsearch/hybrid-search
- Elastic RRF reference: https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion
- Qdrant hybrid search tutorial: https://qdrant.tech/documentation/tutorials-search-engineering/hybrid-search-fastembed/
- Qdrant hybrid search with reranking: https://qdrant.tech/documentation/advanced-tutorials/reranking-hybrid-search/
- BEIR benchmark: https://arxiv.org/abs/2104.08663
- DAPR benchmark: https://arxiv.org/abs/2305.13915
- ColBERT: https://arxiv.org/abs/2004.12832
- scikit-learn calibration guide: https://scikit-learn.org/stable/modules/calibration.html
