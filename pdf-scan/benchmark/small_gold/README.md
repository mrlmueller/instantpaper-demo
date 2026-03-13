# Small Gold Suite

Build this suite now.

## Target shape

- exactly 1 chapter input
- 4 PDFs

Recommended document roles:
- `short_strong_match`
- `long_strong_match`
- `partial_difficult_match`
- `hard_negative_overlap`

## What to add here

### `chapters/`

This is now populated with:
- `chapters/chapter_001_webshop_decision_psychology.json`

### `documents/`

Drop the four PDFs here.

Recommended filenames to match the manifest stubs:
- `doc_001_short_strong_match.pdf`
- `doc_002_long_strong_match.pdf`
- `doc_003_partial_difficult_match.pdf`
- `doc_004_hard_negative_overlap.pdf`

### `manifests/`

This is now populated with:
- `manifests/suite_manifest.json`
- four document manifest stubs

### `judgments/`

Add one judgment JSON per `(chapter, document)` pair based on `../schemas/section_judgments.template.json`.

Do not populate judgments until the canonical section outputs from the new pipeline are stable.

## What this suite is for

Use this suite on every major implementation step:
- after parsing
- after section construction
- after retrieval
- after reranking
- after no-match logic changes

The goal is not large-scale benchmarking yet. The goal is fast, reliable iteration with manual inspectability.
