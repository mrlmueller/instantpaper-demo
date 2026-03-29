# Stage Blueprint Notes

This note tracks the second-pass implementation design.

Goal:
- turn the research conclusions into implementable pipeline stages
- define stage contracts so adjacent stages fit cleanly together
- ensure the final pipeline is observable and benchmarkable

## Questions

- What are the exact stages of the rebuilt pipeline?
- What does each stage consume and emit?
- What artifacts should be persisted after each stage?
- Which failure modes should short-circuit later stages?
- What summaries should print at the end of each notebook cell?

## Proposed phase map

Align the rebuilt notebook to the same style as `sources_two_lane.ipynb`:
- explicit phases
- strict schemas
- run artifacts under `runs/{run_id}/`
- structured logs
- per-phase metrics
- compact verification block at the end of each major cell

## Phase A — Config, run context, artifact skeleton

### Input

- `chapter_title`
- `chapter_spec_text`
- `pdf_paths`
- pipeline version
- environment keys / local tool availability

### Output

- `run_id`
- `run_dir`
- config snapshot
- artifact skeleton
- `pdf_manifest.json`
- `logs.jsonl`
- `metrics.json`

### Why this phase exists

The current notebook is too opaque. Before doing any ranking work, the rebuilt pipeline needs the same operational surface as `sources_two_lane.ipynb`.

## Phase B — Multi-source document parsing bundle

### Input

- PDF path

### Output

- per-document parse bundle, with raw outputs from:
  - pypdf / PyMuPDF metadata lane
  - Docling primary parse lane
  - GROBID scholarly enhancement lane where applicable
  - PyMuPDF fallback layout lane

### Key idea

Do not immediately force one parser output to be "truth". Preserve a raw parse bundle first.

## Phase C — Canonical document model: sections and passages

### Input

- parse bundle from Phase B

### Output

- normalized `DocumentRecord`
- normalized `SectionRecord[]`
- normalized `PassageRecord[]`
- section-type labels
- diagnostics about coverage, overlap, and parser agreement

### Key idea

This is the most important architectural shift:
- the pipeline’s primary ranking unit becomes the section

## Phase D — Query planning and decomposition

### Input

- chapter title
- chapter description

### Output

- strict `QueryPlan`
- retrieval views for:
  - title-focused lexical search
  - body semantic search
  - subpoint retrieval
  - exclusions
  - likely section-type priors

### Key idea

The retrieval stage should not receive one monolithic search string.

## Phase E — Candidate generation (high-recall retrieval)

### Input

- `SectionRecord[]`
- `PassageRecord[]`
- `QueryPlan`

### Output

- scored candidate sections
- supporting passage ids
- component scores by retrieval lane
- fused ranking before rerank

### Key idea

Use multiple retrieval lanes and fuse them. The output unit remains a section, even when passages are used for evidence.

## Phase F — Section reranking

### Input

- top candidate sections from Phase E
- supporting passages
- query plan

### Output

- reranked sections
- multi-criterion usefulness scores
- rationale fields
- model agreement / disagreement diagnostics

### Key idea

Rerank sections, not only passages. Passages support the section decision.

## Phase G — Calibration and no-match decision

### Input

- rerank outputs
- calibration model / thresholds

### Output

- final `0..100` section usefulness score
- per-PDF no-match decision
- global top sections across all PDFs
- uncertainty / abstention metadata

### Key idea

The pipeline must be able to say:
- "this PDF does not contain useful information for this chapter"

and do so explicitly.

## Phase H — Output package and stage summaries

### Input

- all prior artifacts

### Output

- final JSON
- human-readable notebook tables
- per-phase verification summaries
- failure / warning registry

## Cross-stage contracts

These are the core normalized types the implementation should use.

### `DocumentRecord`

- `doc_id`
- `source_path`
- `sha256`
- `title`
- `authors`
- `year`
- `language_guess`
- `page_count`
- `has_outline`
- `parser_bundle_status`
- `doc_type_guess`

### `SectionRecord`

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

### `PassageRecord`

- `doc_id`
- `section_id`
- `passage_id`
- `passage_index`
- `page_span`
- `text`
- `contextualized_text`
- `token_len`

### `QueryPlan`

- `query_id`
- `chapter_title`
- `chapter_summary`
- `must_terms`
- `should_terms`
- `exclusions`
- `subpoints`
- `language_hints`
- `likely_section_types`
- `drift_risks`

### `CandidateSection`

- `doc_id`
- `section_id`
- `lane_scores`
- `supporting_passage_ids`
- `supporting_passage_scores`
- `fusion_score`
- `retrieval_rank`

### `RerankResult`

- `doc_id`
- `section_id`
- `rerank_score_raw`
- `coverage_score`
- `support_strength`
- `match_type`
- `top_evidence`
- `notes`

### `DocumentDecision`

- `doc_id`
- `has_useful_information`
- `doc_match_probability`
- `top_section_id`
- `top_section_score`
- `abstention_reason`

## Per-phase summary block requirements

Every major notebook phase should end with:

1. timing
2. paths written
3. counts
4. QC checks with `OK/WARN/FAIL`
5. one short preview table

Modeled after the style of `sources_two_lane.ipynb`.

## Source links

- GROBID: https://grobid.readthedocs.io/en/latest/Principles/
- Docling chunking: https://docling-project.github.io/docling/concepts/chunking/
- OpenAI retrieval guide: https://developers.openai.com/api/docs/guides/retrieval
- Sentence Transformers retrieve & rerank: https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html
