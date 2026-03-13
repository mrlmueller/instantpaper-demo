# Scoring, No-Match, And Observability Notes

This file is for stage-specific research about:
- usefulness scoring
- no-match detection
- calibration
- run artifacts
- structured logs, metrics, and stage summaries

## Questions

- How should the pipeline decide that a PDF has no useful information?
- How should user-facing scores be defined and calibrated?
- What should be written to disk after each stage?
- What should the per-cell summaries look like in the rebuilt notebook?

## Final score design

The user-facing output should be a section usefulness score.

Recommended public scale:
- `0..100`

But the pipeline should not pretend this is calibrated until a benchmark exists.

## Internal scoring flow

### Pre-calibration raw signals

At the end of reranking, keep:
- retrieval fusion rank
- cross-encoder raw score
- optional LLM usefulness score
- subpoint coverage
- support strength
- section type penalty

### Calibration layer

Once benchmark labels exist, train a lightweight calibrator on top of those signals.

Recommended first tool:
- `CalibratedClassifierCV`

Why:
- official, stable implementation
- supports sigmoid and isotonic calibration
- integrates well with ordinary tabular feature pipelines

Recommended practical rule:
- use `sigmoid` early because it preserves ranking
- test `isotonic` only when enough labeled data exists

## No-match / abstention design

This is critical because the user explicitly wants the system to say when a PDF is not useful.

### Recommended decision objects

The final pipeline should emit two levels of decision:

1. `SectionDecision`
   - per section usefulness score
2. `DocumentDecision`
   - whether the document contains any useful information at all

### Document-level no-match signals

Use a separate doc-level feature bundle:

- top section score
- top-3 mean score
- margin between top-1 and top-2
- number of sections above a usefulness threshold
- max subpoint coverage
- whether only penalized section types ranked highly

Then calibrate a `has_useful_information` probability.

### Before benchmark labels exist

Use a conservative provisional rule:

- if no candidate section clears a raw minimum threshold
- or all strong candidates are penalized section types
- or evidence coverage is weak across all subpoints

then emit:
- `has_useful_information = false`
- `abstention_reason = ...`

Label this as provisional, not calibrated.

### Optional uncertainty layer

MAPIE / conformal prediction is worth evaluating later if you want:
- prediction sets
- explicit risk control
- abstention guarantees

This is not required for the first rebuild, but it is a strong future path if the benchmark becomes large enough.

## Run artifacts

Model the notebook artifact discipline after `sources_two_lane.ipynb`.

Recommended run layout:

```text
runs/{run_id}/
  config.json
  pdf_manifest.json
  query_plan.json
  parser/
    {doc_id}/
      metadata.json
      docling.json
      grobid.tei.xml
      pymupdf_blocks.jsonl
  normalized/
    documents.jsonl
    sections.jsonl
    passages.jsonl
  retrieval/
    lane_section_title_lexical.jsonl
    lane_section_body_lexical.jsonl
    lane_section_dense.jsonl
    lane_passage_lexical.jsonl
    lane_passage_dense.jsonl
    fused_candidates.jsonl
  rerank/
    cross_encoder.jsonl
    llm_judge.jsonl
  final/
    output.json
    per_pdf_rankings.json
    global_rankings.json
  logs.jsonl
  metrics.json
```

## Per-phase summary design

Each major cell should end with:

1. `What happened`
2. `Artifacts written`
3. `Key counts`
4. `QC checks`
5. `Preview rows`

### Example summary items by phase

#### Parsing phase

- docs parsed
- parser success rate
- docs with outlines
- docs with fallback activated

#### Section construction phase

- sections per doc
- passages per doc
- body coverage %
- penalized section counts

#### Retrieval phase

- candidates per lane
- fused candidate count
- overlap between lanes
- top candidate preview

#### Rerank phase

- sections reranked
- top score distribution
- disagreement between rerankers

#### Final phase

- docs marked useful vs no-match
- top sections
- warning count

## QC philosophy

Keep the same style as `sources_two_lane.ipynb`:
- loud failures
- compact summaries
- easy-to-scan diagnostics
- explicit paths to intermediate artifacts

## Source links

- scikit-learn calibration guide: https://scikit-learn.org/stable/modules/calibration.html
- MAPIE docs: https://mapie.readthedocs.io/en/stable/
- sources_two_lane.ipynb local reference: `sources-v2/sources_two_lane.ipynb`
