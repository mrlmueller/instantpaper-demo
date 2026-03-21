# PDF Extraction Notes

This file collects findings about reliable extraction from digital PDFs, especially scientific literature and long documents.

## Questions to answer

- Which tools are most reliable for digital scientific PDFs?
- How should text be segmented for 2-page to 200-page documents?
- How should document structure be recovered?
- What breaks on multi-column layouts, headers/footers, references, and books?
- Which approaches are suitable if the real goal is section/chapter ranking rather than full-text extraction?

## Rough hypotheses

- Pure raw text extraction is probably not enough for stable chapter ranking.
- Structure-aware parsing is likely more important than anchor recovery.
- Scholarly PDFs may benefit from specialized parsers instead of generic PDF text extraction alone.

## Findings

### 1. Digital PDFs are still structurally weak inputs

Even when OCR is not needed, PDF text extraction is inherently noisy because PDF stores layout for rendering, not a semantic representation of headings, paragraphs, tables, headers, or footers.

Implication:
- "digital PDF" does not mean "easy structured text"
- reliable chapter ranking still needs structure recovery

Primary sources:
- pypdf docs: PDF files do not contain a semantic layer and there is no reliable built-in notion of header, footer, page number, table, or paragraph
- PyMuPDF docs: plain extraction is not prettified and may not be in reading order

### 2. Raw page text is a poor default for scientific documents

PyMuPDF explicitly documents that `page.get_text()` may produce:
- wrong reading order
- unexpected line breaks
- raw text without layout cleanup

It recommends using:
- `get_text("blocks")` for position-aware reading order reconstruction
- `get_text("words")` for coordinate-level logic
- markdown-oriented extraction for RAG/LLM use cases

Implication for the notebook:
- ranking based on raw chunked PDF text risks mixing columns, headers, and footers
- if local parsing remains part of the pipeline, text should be reconstructed from blocks / words, not only raw page text

### 3. Scientific PDFs benefit from specialized parsers

GROBID is explicitly designed for technical and scientific publications and converts PDFs into structured TEI XML for downstream text mining and semantic analysis.

Docling is built around a structured `DoclingDocument` abstraction and exposes chunking, hybrid chunking, serialization, confidence scores, and information extraction paths.

Implication:
- for papers, reports, and books with scholarly structure, a specialized parser is likely a better foundation than manual heuristic section recovery inside the notebook
- the real gain is not "more text", but explicit document structure

### 4. Bookmarks / outlines matter

pypdf distinguishes digitally born PDFs as potentially containing outline items / bookmarks.

Implication:
- PDF outlines / table-of-contents metadata should be used as a first-class structural signal
- they can provide high-precision chapter boundaries when present

### 5. Large-document handling is not just about page count

pypdf documents that text extraction can be memory-intensive for large content streams, with rare cases requiring very large RAM footprints.

Implication:
- benchmarking should track memory, not only retrieval quality
- long books and standards need page-by-page or section-by-section processing rather than monolithic extraction

## Practical conclusions for the target system

For the user’s goal, the parsing layer should prioritize this order:

1. Native outline / bookmarks / table of contents if present.
2. Structured scholarly parser:
   - likely GROBID first for scientific papers
   - Docling as another strong candidate, especially if a richer document object and chunking pipeline is useful
3. Local fallback heuristics:
   - PyMuPDF blocks / words
   - heading detection from font size, numbering, boldness, position

This is a major shift from the current notebook, which effectively starts from raw vector-store chunks and only later tries to infer section structure.

## Source links

- OpenAI Retrieval guide: https://developers.openai.com/api/docs/guides/retrieval
- PyMuPDF text recipes: https://pymupdf.readthedocs.io/en/latest/recipes-text.html
- pypdf text extraction guide: https://pypdf.readthedocs.io/en/stable/user/extract-text.html
- GROBID principles: https://grobid.readthedocs.io/en/latest/Principles/
- Docling docs: https://docling-project.github.io/docling/
