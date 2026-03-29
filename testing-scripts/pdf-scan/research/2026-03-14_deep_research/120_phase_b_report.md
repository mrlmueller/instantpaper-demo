# Phase B Report

## Scope

Phase B takes the Phase A run context plus the selected PDF manifest and produces one parser bundle per PDF.

Input contract:
- digital PDF files only
- stable run context from Phase A
- per-phase parser options

Output contract:
- per-document parser artifacts under `parser/<doc_id>/`
- phase-level summary and assessment
- enough structure signals for Phase C to build sections without reparsing PDFs

The core requirement for this phase is not just “extract text”. It is “extract enough reliable structure that later phases can decide where relevant information lives”.

## What I Researched

I rechecked the parser lane against primary sources and the installed runtime:

- Docling quickstart and parser configuration docs:
  - https://docling-project.github.io/docling/getting_started/quickstart/
  - https://docling-project.github.io/docling/usage/advanced_options/
- GROBID service docs:
  - https://grobid.readthedocs.io/en/latest/Grobid-service/
- PyMuPDF text extraction docs:
  - https://pymupdf.readthedocs.io/en/latest/recipes-text.html
- pypdf text extraction docs:
  - https://pypdf.readthedocs.io/en/stable/user/extract-text.html

Two important implementation decisions came from the review loop rather than directly from docs:

- `partial_success` from Docling can still contain a usable document with section headers. The original code threw that away.
- For Docling chunked retries, `max_num_pages` is effectively checked against the full PDF, not only the requested `page_range`. That behavior is an inference from runtime experiments with the installed `docling==2.79.0`, not a direct statement from the docs.

## Iteration History

### Iteration 1

Executable lab:
- `pdf-scan/phase_b_lab.py`

Run:
- `26924cb6233d80eb58d75860`

Observed result:
- 5/5 PDFs readable without OCR
- Docling success-like on 3/5 PDFs
- 598-page book skipped by page limit
- 94-page `Opinion Mining and Sentiment Analysis` only `partial_success`
- fallback active on 3/5 PDFs

Main defects:
- `partial_success` documents were not exported, so Phase C lost usable Docling headers
- over-limit docs were only marked as skipped, not meaningfully diagnosed
- no structured retry data existed for later review

### Targeted probes

I ran direct Docling experiments outside the pipeline.

Findings:
- the 94-page opinion-mining paper produced a `partial_success` result with a real document and many section headers
- the 7-page consumer paper is considered invalid by Docling even when page ranges are used
- the 598-page book is also invalid to Docling on a chunk probe, so forcing Docling on it is not a free win

### Iteration 2

Changes:
- exported Docling documents for success-like results, not only `success`
- added `section_headers`, `document_summary`, `attempts`, and `chunking` metadata to `docling.json`
- added chunk-retry support
- added aggregate review script `pdf-scan/review_phase_b.py`

Intermediate issue:
- the first chunk-retry implementation failed for the 94-page document because chunk calls used `max_num_pages=chunk_size`
- that made Docling reject the full PDF as invalid even though the chunk range itself was small

### Iteration 3

Fix:
- chunk retries now keep `max_num_pages` at least as large as the full document/page-limit guard

Final default:
- automatic chunk retry is enabled up to 400 pages by default
- this pushes the strong-parse lane further into the larger-document range instead of treating anything above 200 pages as fallback-only
- larger documents still run through deterministic fallback and can be manually opted into heavier Docling handling later

## Final Implementation Changes

Files:
- `pdf-scan/phase_b_lab.py`
- `pdf-scan/review_phase_b.py`
- `pdf-scan/pdf-scan-v3.ipynb`

Key changes:

1. Docling artifacts are now useful even when the conversion is imperfect.
- `partial_success` documents are preserved
- `docling.json` now carries `section_headers`, `document_summary`, `attempts`, `selected_mode`, and optional `chunking`

2. Chunked recovery exists for medium-length documents.
- default retry lane for docs up to 400 pages
- chunk size default: 20 pages
- retry thread count default: 1
- this recovered the 94-page paper into a full Docling success

3. The long-document path is explicit instead of ambiguous.
- documents above the default chunk range are marked as `skipped_page_limit`
- the assessment tells you that fallback is carrying those files

4. Reviewability improved substantially.
- per-document Docling mode is surfaced in summaries
- per-document section-header counts are surfaced
- review script classifies error patterns and validates chunk metadata

5. `pdf-scan-v3.ipynb` now points at the validated Phase B implementation.
- I replaced the stale inline Phase B notebook code with a notebook bridge into `phase_b_lab.py`
- this matches the Phase A approach and avoids another code fork

## Final Validation

Final validation run:
- `36f15a3ae3ddc5d16000f6ef`

Review artifact:
- `pdf-scan/runs/36f15a3ae3ddc5d16000f6ef/phase_b_review/phase_b_review_summary.json`

Phase result:
- status: `success_with_warnings`
- quality band: `acceptable_with_issues`
- can continue: `true`

Observed behavior on the 5 benchmark PDFs:

- `Consumers’ Decision-Making...`
  - Docling still fails
  - fallback stays active
  - outline exists, so Phase C still has structure to work with

- `Judgment Under Uncertainty...` (598 pages)
  - Docling is skipped by default page-limit policy
  - fallback stays active
  - outline exists and PyMuPDF coverage is high

- `Whose online reviews to trust...`
  - Docling success
  - 48 extracted section headers
  - no fallback needed

- `Online Reviews and Information Overload...`
  - Docling success
  - 53 extracted section headers
  - no fallback needed

- `Opinion Mining and Sentiment Analysis`
  - original single-pass Docling: `partial_success`
  - chunk retry: `success`
  - selected mode: `chunked`
  - 104 extracted section headers
  - fallback no longer needed

The most important improvement is that fallback activation dropped from 3 documents to 2, and the recovered document is inside your target size range.

## Why These Changes Matter For Later Phases

- Phase C gets better section proposals because Docling headers are now preserved for `partial_success` and recovered via chunking when needed.
- Phase C can trust the per-document parser diagnostics more because `docling_mode` and `docling_section_header_count` are now visible.
- Later evaluation becomes easier because parser failures are distinguishable:
  - true Docling-invalid PDF
  - over-limit policy skip
  - memory-driven partial parse
- The notebook is now executable against the validated code path instead of a diverged inline copy.

## Remaining Limits

- GROBID is still not configured, so scholarly TEI structure recovery is absent.
- Some PDFs are simply invalid for Docling even though PyMuPDF and pypdf can read them.
- Default chunk retry now stops at 400 pages. That is the current default ceiling for the stronger Docling lane.

## Tunable Knobs Worth Reconsidering Later

- `docling_chunk_size`
  - `20` worked well on the 94-page paper
  - larger chunks may reduce runtime but increase memory risk

- `docling_chunk_max_pages`
  - default is now `400`
  - if later you want heavier support for very large 400+ page PDFs, this is the first lever to raise

- `docling_chunk_num_threads`
  - `1` is conservative for stability
  - higher values may speed up chunk retries but could reintroduce memory problems

- `docling_page_limit`
  - now `400`
  - should stay aligned with the chunk retry policy unless we intentionally add a separate “heavy long-doc mode”

## Conclusion

Phase B is now good enough to move on.

The phase is not “perfect parser everywhere”, but it is now doing the right engineering job:
- reliable digital-PDF readability checks
- strong deterministic fallback
- preserved structure on partial Docling outputs
- chunked recovery for medium-length failures
- explicit diagnostics for the cases Docling still cannot handle
