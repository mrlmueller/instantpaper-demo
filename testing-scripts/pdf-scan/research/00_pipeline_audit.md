# Current Pipeline Audit

Target under review: `pdf-scan/pdf-scan-test.ipynb`

## Scope

The user goal for the pipeline is:
- input one or more digital PDFs
- support small and large documents, roughly 2 to 200+ pages
- find the most relevant chapters/sections for an input chapter description
- output ranked relevant chapters/sections with usefulness / fit scores

The user explicitly said section text extraction is not the main goal in this pass.

## Notebook stage map

1. Environment + OpenAI client setup.
2. Chapter input:
   - `CHAPTER_TITLE`
   - `CHAPTER_DESCRIPTION`
3. LLM preprocessing:
   - compress chapter description
   - derive `SUBPOINTS`, `MUST_TERMS`, `SHOULD_TERMS`, `PREFERRED_SEARCH_TERMS`, `HARD_EXCLUSIONS`, `SCOPE_NOTES`
4. PDF upload / reuse:
   - local path or existing OpenAI `file_id`
   - attach files to one vector store
5. Retrieval:
   - build one global `search_query`
   - call `client.vector_stores.search(...)`
   - split hits back by `file_id`
   - optional per-file top-up retrieval
   - optional subpoint-specific top-up retrieval
6. Per-PDF LLM evidence extraction:
   - feed evidence snippets from one PDF at a time
   - ask LLM to output scored hits with anchors and summaries
7. Postprocess:
   - validate anchors against evidence
   - drop weak/invalid results
   - group outputs by subpoint
8. Optional Stage 3 curation:
   - local PyMuPDF heading/anchor logic to merge into distinct PDF sections

## Important current design choice

The notebook does not rank sections directly.

It does this instead:
- retrieve top vector-store chunks
- ask an LLM to infer the best matching places from those chunks
- optionally recover local section boundaries later

This means section ranking quality is bottlenecked by:
- chunk recall in the initial vector-store search
- how well those chunks preserve section identity
- whether the right PDF gets enough evidence at all
- whether the LLM can infer section-level relevance from partial evidence

## Likely failure modes already visible from the notebook

### 1. Section ranking is downstream of chunk recall

If the right section does not appear in the top retrieved chunks, it cannot be ranked correctly later.

### 2. Global top-k retrieval is capped

The notebook requests a global search and then redistributes hits per PDF. This is structurally risky for:
- many PDFs
- long books
- documents with many relevant sections

Even with top-up logic, the first-stage recall budget is tight.

### 3. The ranking target is underspecified

The user wants ranked chapters/sections.

The notebook mainly outputs:
- evidence anchors
- per-hit scores
- per-subpoint grouping

This is not the same as a stable section/chapter ranking model with calibrated scores.

### 4. Retrieval is not aligned to document structure

The main search operates on vector-store chunks rather than:
- detected sections
- chapter titles
- section summaries
- section-level passage pools

That weakens both interpretability and stability.

### 5. Preprocessing may distort the original query intent

The LLM-generated search spec can help, but it can also:
- omit important concepts
- add weak synonyms
- overfit to surface terminology
- flatten nuanced scope constraints

### 6. Stage 3 does work outside the main goal

A lot of notebook complexity is spent on anchor validation and section recovery. The user clarified that this is not the main priority for this pass.

## Initial hypothesis before research

The strongest likely architectural direction is:
- recover document structure first
- represent sections explicitly
- rank sections using structure-aware retrieval and reranking
- only use LLMs where they add clear value

Research still needed before making concrete recommendations.
