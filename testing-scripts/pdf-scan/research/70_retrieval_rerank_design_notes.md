# Retrieval And Rerank Design Notes

This file is for stage-specific research about:
- query decomposition
- first-stage retrieval
- candidate fusion
- section reranking
- cross-stage data compatibility

## Questions

- How should the chapter query be represented for retrieval?
- Which retrieval units should be indexed?
- How should title, section summary, body, and passage evidence interact?
- How should section scores be aggregated from retrieval evidence?

## Query representation

Do not feed retrieval with one single giant prompt string.

Instead, generate a strict `QueryPlan` with several retrieval views:

- `title_query`
- `summary_query`
- `must_terms_query`
- `subpoint_queries[]`
- `exclusion_terms`
- `preferred_section_types`

## Why this design

The current notebook already hints at this need with:
- must terms
- should terms
- subpoints
- exclusions

But it still collapses too much into one global search string.

## Query planning method

Use OpenAI structured outputs for the query planner.

Why:
- schema reliability
- easier caching
- easier diagnostics
- simpler downstream contracts

Important implementation note from OpenAI’s structured output guidance:
- schema conformance is much stronger than plain JSON mode
- but values can still be wrong, so this stage still needs validation

## Recommended retrieval units

### Primary ranking unit

- section

### Supporting evidence unit

- passage

This gives the best balance between:
- interpretability
- recall
- precision

## Recommended first-stage retrieval design

Use a local hybrid candidate generation stack.

### Why local, not hosted vector-store-first

For this use case:
- document count per run is modest
- control matters more than hosted convenience
- the current OpenAI vector store path has a hard `50` result ceiling
- structure-aware local indices are easier to tune and inspect

### Required retrieval lanes

At minimum:

1. `section_title_lexical`
2. `section_body_lexical`
3. `section_dense`
4. `passage_lexical`
5. `passage_dense`

Each lane returns section ids, even if it retrieves passages internally.

### Fusion

Use Reciprocal Rank Fusion as the default lane combiner.

Why:
- strong practical baseline
- robust across incomparable score scales
- little tuning needed
- well documented in Elastic and common hybrid-search practice

## Recommended local retrieval substrate

The implementation plan should stay substrate-agnostic, but the practical ranking order is:

### Default implementation path

- lexical retrieval locally over sections and passages
- dense embeddings locally or via API
- RRF fusion in Python

This is the simplest high-control design for a notebook pipeline.

### If a dedicated engine is needed later

Two strong directions:

- Elasticsearch / OpenSearch for mature lexical + hybrid retrieval + explainability
- Qdrant for dense+sparse+late-interaction experimentation

## Reranking design

### Mandatory reranking stage

After fusion, rerank top section candidates with a stronger model.

### Recommended reranking stack

1. local cross-encoder over top candidate sections
2. optional LLM judge over a smaller top subset for deeper usefulness scoring

### Why cross-encoder first

Sentence Transformers’ official guidance is clear:
- retrieve broadly first
- rerank with a cross-encoder on the candidate set

It also explicitly notes that if you only have a small paragraph set inside one document, you can skip retrieval and directly cross-encode that smaller pool. That is useful for:
- per-document refinement
- tie-breaking among top sections in one PDF

### LLM judge usage

Use an LLM judge only after the candidate pool is already small and evidence-rich.

The LLM should score:
- topical match
- explanatory depth
- direct usefulness for writing the chapter
- subpoint coverage
- exclusion violations

And must output strict structured JSON.

## Score aggregation before calibration

The reranking stage should produce several raw signals:

- `title_match_score`
- `best_passage_score`
- `topk_passage_mean`
- `subpoint_coverage_score`
- `section_type_penalty`
- `cross_encoder_score`
- `llm_usefulness_score` if used

Do not compress these too early into one opaque number.

## Optional advanced lane

If recall remains a problem after the basic hybrid stack is working, add an optional late-interaction retrieval lane, e.g. ColBERT-style.

This is not required for v1 of the rebuild, but it is the most plausible next upgrade if the benchmark later shows:
- dense recall is still missing good sections
- lexical retrieval is too brittle on paraphrased chapter descriptions

## Cross-stage fit

The retrieval stage assumes the parsing stage already produced:
- contextualized section text
- contextualized passage text
- section titles and title paths
- section types
- page spans

Without that, retrieval will be forced back into raw chunk semantics, which is exactly what the redesign is trying to avoid.

## Source links

- OpenAI structured outputs announcement: https://openai.com/index/introducing-structured-outputs-in-the-api/
- Sentence Transformers retrieve & rerank: https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html
- OpenAI retrieval guide: https://developers.openai.com/api/docs/guides/retrieval
- Elastic hybrid search overview: https://www.elastic.co/elasticsearch/hybrid-search
- Elastic RRF reference: https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion
- Qdrant hybrid search tutorial: https://qdrant.tech/documentation/tutorials-search-engineering/hybrid-search-fastembed/
- Qdrant hybrid search with reranking: https://qdrant.tech/documentation/advanced-tutorials/reranking-hybrid-search/
- DAPR benchmark: https://arxiv.org/abs/2305.13915
- BEIR benchmark: https://arxiv.org/abs/2104.08663
- ColBERT: https://arxiv.org/abs/2004.12832
