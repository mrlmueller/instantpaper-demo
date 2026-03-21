# PDF Scan Benchmark Layout

This folder contains two benchmark tracks for the section-ranking pipeline.

## Tracks

### `small_gold/`

Build this now.

Purpose:
- one chapter input
- about 4 PDFs
- fast manual inspection
- used during early iterative development

Recommended composition:
- 1 short strong-match PDF
- 1 long strong-match PDF
- 1 medium partial / difficult PDF
- 1 hard negative with slight topical overlap

### `large_suite/`

Scaffold this now, populate it later.

Purpose:
- multiple chapter inputs
- many more PDFs
- formal regression and benchmark runs once the pipeline is stable enough

## Why this split

The small suite should exist immediately because:
- it catches obvious parser / retrieval / ranking failures early
- it is cheap to inspect manually

The large suite should not be fully populated yet because:
- the canonical section schema is still evolving
- section boundary logic is not implemented yet
- early labeling on unstable outputs creates rework

## Shared rules

- Gold labels are attached to sections / chapters, not raw chunks.
- Every suite must include positive and negative documents.
- Every run should preserve intermediate artifacts so failures are explainable.

## Recommended development order

1. Build and use `small_gold/` immediately.
2. Implement parsing and section construction first.
3. Add retrieval and reranking.
4. Only after the section schema and outputs are stable, populate `large_suite/`.
