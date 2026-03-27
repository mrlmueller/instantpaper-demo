# Parsing And Section Construction Notes

This file is for stage-specific research about:
- PDF ingestion
- structure recovery
- section tree construction
- section and passage candidate creation

## Questions

- What parser stack should be primary vs fallback?
- How should headings, outlines, and sections be represented?
- How should books and long reports differ from short papers?
- How should references / appendix / boilerplate be identified early?

## Primary recommendation

Use a parser bundle, but with a clear primary path:

1. pypdf / PyMuPDF metadata and outline lane
2. Docling as the primary structured parse for all documents
3. GROBID as a scholarly enhancement lane for papers and report-like documents
4. PyMuPDF block / word extraction as deterministic fallback and validator

## Why this stack

### pypdf / PyMuPDF metadata lane

Needed for:
- page count
- outline / bookmark extraction
- cheap document sanity checks
- deterministic fallback

### Docling primary lane

Docling provides:
- a structured `DoclingDocument`
- hierarchical chunking
- hybrid chunking
- contextualized chunk serialization

This makes it the cleanest bridge between parsing and retrieval.

### GROBID scholarly enhancement lane

GROBID is explicitly designed for technical and scientific publications and operates on layout tokens, not just plain text.

Use it for:
- article-style section structure
- bibliography detection
- scholarly metadata enrichment
- cross-checking section titles and body segmentation

### PyMuPDF fallback lane

PyMuPDF remains essential because:
- it gives deterministic access to blocks and words
- it can reconstruct layout when higher-level parsers fail
- it is useful for page-span and boundary validation

## Canonical section construction

The implementation should build a canonical section tree from parser outputs, not from raw text alone.

### Priority of structural signals

1. Native outline / bookmarks
2. Docling structural headings
3. GROBID section hierarchy
4. PyMuPDF font / numbering / spacing heuristics

### Section merge rules

Use these principles:

- prefer explicit structure over inferred structure
- prefer agreement between sources over single-source guesses
- preserve parser provenance on every section
- never silently drop unmatched text; assign it to fallback sections if needed

### Required section classes

At minimum:

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
- `table_of_contents`
- `acknowledgements`

These classes are useful later for:
- priors
- penalties
- no-match decisions
- benchmark slicing

## Passage construction

Passages should be generated after sections exist.

### Recommended rule

For each canonical section:

1. keep the full section text
2. create passage chunks inside that section
3. contextualize every passage with its title path

This directly addresses the DAPR finding that missing document context causes many retrieval failures in long documents.

### Preferred chunker

Use Docling `HybridChunker` when available because it:
- starts from document hierarchy
- aligns chunking with the embedding tokenizer
- splits oversized chunks only when needed
- merges undersized peer chunks when possible
- exposes `contextualize()` to enrich chunk text with headings / metadata

### Fallback chunking

If Docling chunking is unavailable for a section:

- split by paragraphs first
- then apply token-window fallback only inside the section
- keep overlap small and local
- always prepend `title_path`

## Early filtering of bad sections

The pipeline should identify and tag early:
- references
- bibliography
- glossary
- acknowledgements
- table of contents
- blank or near-empty sections
- OCR-like junk even in digital PDFs

Do not always remove them immediately; tag them first so later stages can:
- penalize them
- or still keep them if the query actually targets such material

## Optional parser alternatives worth evaluating later

These are worth testing but should not be the default plan:

### Marker

Marker is interesting because it can emit markdown, JSON, and chunks, and explicitly claims strong PDF-to-markdown accuracy.

Why not make it the default now:
- licensing and deployment profile are more complex
- it is less directly aligned to scientific section semantics than GROBID
- we already have a cleaner primary path with Docling + GROBID + PyMuPDF

### Unstructured

Useful as another parser baseline, but the current plan does not need it as a first-line dependency.

## Cross-stage fit

The parsing stage must emit data that the retrieval stage can consume without re-parsing.

That means every `SectionRecord` and `PassageRecord` must already contain:
- `title_path`
- cleaned text
- page span
- section type
- parser provenance
- token-length metadata

## Source links

- GROBID principles: https://grobid.readthedocs.io/en/latest/Principles/
- Docling chunking: https://docling-project.github.io/docling/concepts/chunking/
- Docling hybrid chunking example: https://docling-project.github.io/docling/examples/hybrid_chunking/
- PyMuPDF text recipes: https://pymupdf.readthedocs.io/en/latest/recipes-text.html
- PyMuPDF4LLM: https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/index.html
- pypdf extraction guide: https://pypdf.readthedocs.io/en/stable/user/extract-text.html
- Marker repo: https://github.com/VikParuchuri/marker
