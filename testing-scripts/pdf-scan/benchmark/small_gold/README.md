# Small Gold Suite

Build this suite now.

## Target shape

- exactly 1 chapter input
- 5 PDFs

Recommended document roles:
- `short_document_candidate`
- `very_long_document_candidate`
- `medium_document_candidate_a`
- `medium_document_candidate_b`
- `long_document_candidate`

## What to add here

### `chapters/`

This is now populated with:
- `chapters/chapter_001_webshop_decision_psychology.json`

### `documents/`

The active suite now uses the real PDF filenames already present in `documents/`.

### `manifests/`

This is now populated with:
- `manifests/suite_manifest.json`
- five document manifests

### `judgments/`

Add one judgment JSON per `(chapter, document)` pair based on `../schemas/section_judgments.template.json`.

Do not populate judgments until the canonical section outputs from the new pipeline are stable.

See also:
- `ROLE_ASSIGNMENT.md`
- `judgments/ANNOTATION_PLAN.md`

Important:
- these are document-profile assignments only
- they are not relevance labels

## What this suite is for

Use this suite on every major implementation step:
- after parsing
- after section construction
- after retrieval
- after reranking
- after no-match logic changes

The goal is not large-scale benchmarking yet. The goal is fast, reliable iteration with manual inspectability.
