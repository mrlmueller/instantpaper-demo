# API And Package Notes

This file tracks exact behaviors and limits from current documentation for the APIs and packages relevant to `pdf-scan/pdf-scan-test.ipynb`.

Targets:
- OpenAI vector stores / file search / responses API
- PyMuPDF
- any alternative parsing stack considered during research

## Questions to answer

- What are the current retrieval limits and filtering options?
- What chunking behavior is fixed versus configurable?
- Which package behaviors matter for long digital PDFs?
- Where do the notebook assumptions match or fight the underlying tools?

## OpenAI vector stores / retrieval

### Confirmed current behaviors

From the current OpenAI docs:

- `vector_stores.search` supports:
  - `query`
  - `filters`
  - `max_num_results`
  - `ranking_options`
  - `rewrite_query`
- `max_num_results` is limited to `1..50`
- `ranking_options` exposes:
  - `ranker`
  - `score_threshold`
- attribute-based filtering is supported on attached `vector_store.file` attributes

From the retrieval guide:

- default chunking is:
  - `max_chunk_size_tokens = 800`
  - `chunk_overlap_tokens = 400`
- custom `chunking_strategy` is supported when adding files
- `max_chunk_size_tokens` must be between `100` and `4096`
- `chunk_overlap_tokens` must not exceed half of chunk size
- file limits:
  - maximum file size `512 MB`
  - maximum `5,000,000` tokens per file
- attributes are supported and intended for semantic search filtering

### Implications for `pdf-scan-test.ipynb`

The notebook currently:
- uses `max_num_results`
- uses `rewrite_query=True`
- uses `filters` only in top-up fallback logic

The notebook currently does not use:
- custom `chunking_strategy`
- `ranking_options`
- `score_threshold`
- a first-class section-level ingestion format

This matters because:
- a 50-result ceiling is tight for multi-PDF and long-book scenarios
- raw default chunking is not aligned to section boundaries
- section ranking quality is bounded by chunk recall

### Important architectural observation

If OpenAI vector stores remain part of the system, the best use is probably not:
- upload raw PDFs directly and trust default chunking

A stronger pattern would be:
- parse locally into structured text or section objects first
- then upload that structured representation

That would let the vector store operate on better units.

## PyMuPDF

Confirmed from official docs:

- `page.get_text()` is raw and may not follow normal reading order
- `get_text("blocks")` provides position-aware text blocks
- `get_text("words")` provides word coordinates
- markdown-oriented extraction is explicitly recommended for RAG / LLM workflows

Implication:
- PyMuPDF is useful as a low-level layout recovery tool
- but it should be used deliberately, not as a "plain text and hope" extractor

## pypdf

Confirmed from official docs:

- PDF has no semantic layer
- extraction can be memory intensive on large content streams
- digitally born PDFs may contain outline items / bookmarks

Implication:
- pypdf is informative for constraints and metadata handling
- it is not a full scientific-structure parser

## GROBID

Confirmed from official docs:

- GROBID is designed for extracting and restructuring scientific PDFs
- output is a machine-friendly structured TEI/XML representation
- its purpose is downstream text mining / information extraction / semantic analysis

Implication:
- this is one of the strongest candidates if the target corpus is mostly scientific papers and reports

## Docling

Confirmed from official docs:

- Docling exposes a structured document abstraction
- chunking and hybrid chunking are first-class concepts
- confidence scores and information extraction are built into the ecosystem

Implication:
- Docling is promising if the project wants a more modern document-object workflow rather than hand-built PDF heuristics

## Source links

- OpenAI vector store search API reference: https://developers.openai.com/api/reference/resources/vector_stores/methods/search
- OpenAI retrieval guide: https://developers.openai.com/api/docs/guides/retrieval
- OpenAI file search guide: https://developers.openai.com/api/docs/guides/tools-file-search
- PyMuPDF text recipes: https://pymupdf.readthedocs.io/en/latest/recipes-text.html
- pypdf text extraction guide: https://pypdf.readthedocs.io/en/stable/user/extract-text.html
- GROBID principles: https://grobid.readthedocs.io/en/latest/Principles/
- Docling docs: https://docling-project.github.io/docling/
