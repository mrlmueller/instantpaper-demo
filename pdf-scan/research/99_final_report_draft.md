# Final Report Draft

## Headline conclusion

The current notebook is trying to solve a section-ranking problem with a chunk-retrieval pipeline plus LLM post-hoc reasoning.

That is the wrong center of gravity.

The project should instead become:
- a structure-aware section retrieval and ranking pipeline

## Most important design shift

Current notebook:
- retrieve raw vector-store chunks
- ask the LLM to score evidence
- optionally reconstruct sections later

Recommended future system:
- recover sections first
- retrieve section candidates second
- rerank sections third
- calibrate scores fourth

## Why this matters

Long scientific documents fail mainly when:
- structure is lost
- retrieval units are too small or too arbitrary
- chunk recall is capped too early
- passage meaning is detached from section / document context

The current notebook suffers from all four.

## Architecture direction to recommend in the final report

### Recommended target pipeline

1. Parse PDF structure
   - outlines / bookmarks first
   - GROBID or Docling for scholarly structure when possible
   - PyMuPDF block / word fallback
2. Build explicit section tree
   - section title
   - level
   - page span
   - section text
   - paragraph / passage children
3. Create two retrieval layers
   - section index
   - passage index inside sections
4. Query decomposition
   - keep original chapter description
   - derive subpoints
   - derive lexical must terms
5. Candidate generation
   - hybrid lexical + dense retrieval
   - title-aware retrieval
   - subpoint-aware multi-query fusion
6. Rerank section candidates
   - cross-encoder or strong LLM judge on top candidates only
7. Score aggregation and calibration
   - output ranked sections with transparent reasons

### Strongest likely recommendation

If architectural freedom is allowed, section-aware local indexing is more promising than raw hosted-PDF vector-store search.

If OpenAI vector stores remain in the loop, they should ideally index structured section text rather than the raw PDF directly.

## Open questions for later implementation

- best parser choice for the actual corpus mix
- reranker choice under latency / cost constraints
- whether local sparse+dense retrieval or hosted vector search is preferred
- how to calibrate user-facing scores
