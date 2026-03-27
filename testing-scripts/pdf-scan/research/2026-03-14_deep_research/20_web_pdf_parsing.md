# Web Research - PDF Parsing And Structure

Purpose:
- Capture external findings on reliable digital PDF parsing, section recovery, long-document handling, parser ensembles, and page-span reconstruction.

## Primary Sources Reviewed

- Docling Quickstart: `https://docling-project.github.io/docling/getting_started/quickstart/`
- Docling Advanced options: `https://docling-project.github.io/docling/usage/advanced_options/`
- Docling Chunking: `https://docling-project.github.io/docling/concepts/chunking/`
- Docling Confidence Scores: `https://docling-project.github.io/docling/concepts/confidence_scores/`
- Docling Pipeline options: `https://docling-project.github.io/docling/reference/pipeline_options/`
- Docling Technical Report: `https://arxiv.org/abs/2408.09869`
- PyMuPDF text extraction docs: `https://pymupdf.readthedocs.io/en/latest/recipes-text.html`
- PyMuPDF `Document.get_toc()`: `https://pymupdf.readthedocs.io/en/latest/document.html#Document.get_toc`
- pypdf extract-text docs: `https://pypdf.readthedocs.io/en/stable/user/extract-text.html`
- pypdf outline handling docs: `https://pypdf.readthedocs.io/en/latest/user/handling-outlines.html`
- GROBID REST API docs: `https://grobid.readthedocs.io/en/latest/Grobid-service/`
- Detect-Order-Construct paper: `https://arxiv.org/abs/2401.11874`

## Source-Based Findings

### 1. Docling is a strong primary parser, but it should not be trusted blindly

Docling’s own technical report describes it as a self-contained open-source PDF conversion package built around layout analysis and table structure models. Its public docs show that the basic unit is a `DoclingDocument`, and its native chunkers operate directly on that structured representation rather than on flattened text.

Operationally useful Docling capabilities from the docs:
- `DocumentConverter.convert(...)` can impose `max_num_pages` and `max_file_size`.
- `PdfPipelineOptions` exposes toggles like `do_ocr`, `do_table_structure`, `generate_page_images`, and related pipeline controls.
- Confidence reporting exists at both page and document level, with aggregate grades such as `mean_grade` and `low_grade`.

Important fit for this project:
- Because this project is digital-PDF only, `do_ocr` should remain off.
- Docling confidence grades are valuable as QC signals, but not as the only health signal.
- Native hierarchical / hybrid chunkers are relevant mainly for evidence construction, not for replacing the canonical section graph.

### 2. PyMuPDF is the most useful deterministic backstop

PyMuPDF’s text docs explicitly note that extracted text may not follow natural reading order. The same docs recommend using block-level and word-level extraction, because both carry positional information that can be used to reconstruct better ordering and support geometric validation.

Most useful PyMuPDF primitives for this pipeline:
- `page.get_text("blocks")` or `page.get_text("dict")` for block geometry and text.
- `page.get_text("words")` for fine-grained word boxes.
- `Document.get_toc()` for outline/bookmark extraction.

Implication:
- PyMuPDF should remain the canonical geometry lane for:
  - anchor validation
  - page-span construction
  - outline recovery
  - fallback section heuristics when higher-level parsers disagree

### 3. pypdf is valuable for semantic caveats and outline redundancy, not for layout fidelity

pypdf’s extract-text docs explicitly warn that text extraction is hard because PDFs do not store text in a semantically meaningful way. The same docs also state that pypdf is not OCR software.

Useful pypdf roles:
- independent outline extraction via `reader.outline`
- independent page-destination lookup via `get_destination_page_number()`
- metadata lane

Implication:
- Keep pypdf as a cheap second opinion on bookmarks / metadata.
- Do not rely on pypdf for layout-grounded section boundaries.

### 4. GROBID is the right scholarly enhancement lane

The GROBID service docs show that `/api/processFulltextDocument` returns structured TEI and supports:
- `teiCoordinates` for selected TEI elements
- `segmentSentences=1`
- page slicing through `start` and `end`
- `204` when no structured content can be extracted

This is especially relevant because:
- the user corpus is scholarly / report-like often enough
- GROBID supports partial-page processing, which is valuable for long documents

Implication:
- GROBID should be added for papers / reports when available.
- For very long documents, it is reasonable to process page windows or split PDFs, then merge TEI-derived structure back into the canonical graph.
- This page-window strategy is an inference from the API design plus the current long-document constraints.

### 5. Structure reconstruction is a first-class problem, not a side effect of parsing

The Detect-Order-Construct paper frames hierarchical document structure analysis as a combination of:
- object detection
- reading order prediction
- hierarchical tree construction

This is important because the current notebook mostly treats heading proposals as enough. The literature signals that:
- reading order
- hierarchy
- section tree construction

are separate problems that should be validated, not assumed.

## Design Conclusions For This Repo

1. Recommended parser stack:
- `PyMuPDF` for page text coverage, words, blocks, and TOC
- `pypdf` for metadata + independent outline lane
- `Docling` as the default structured parse
- `GROBID` for scholarly PDFs when available

2. Recommended section-construction principle:
- Never trust one parser’s section tree directly.
- Build a canonical section graph from parser proposals plus geometry anchors.

3. Recommended long-document handling:
- Do not skip Docling only because the document is long.
- Prefer:
  - full parse if runtime is acceptable and cached
  - otherwise split the PDF into page windows and merge results
  - otherwise use outline-first plus PyMuPDF block validation

This split-and-merge recommendation is an inference from the sources plus the current repo behavior.

4. Recommended QC signals per document:
- digital text coverage
- outline presence / quality
- Docling confidence grades
- parser agreement on page count
- parser agreement on headings
- fallback-anchor count
- section coverage percentage
- tiny-section ratio
- giant-section ratio

5. Recommended hard rule for this project:
- If embedded text coverage is poor and OCR would be required, stop and emit `unsupported_requires_ocr`.

Questions to answer here:
- Which parser stacks are most reliable for digital PDFs with scholarly structure?
- How do Docling, GROBID, PyMuPDF, and pypdf complement each other?
- How should long PDFs be handled without OCR?
- What are best practices for heading detection, outline recovery, and section-boundary validation?
- What metrics matter for parser QC?
