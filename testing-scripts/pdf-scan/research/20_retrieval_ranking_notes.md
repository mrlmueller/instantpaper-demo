# Retrieval And Ranking Notes

This file collects findings about:
- long-document retrieval
- scientific-document passage/section retrieval
- hierarchical retrieval
- section-level ranking
- score calibration and evaluation

## Questions to answer

- How do strong systems retrieve relevant sections from long documents?
- Should ranking happen at chunk, passage, or section level?
- What is the best role for embeddings, BM25, hybrid retrieval, rerankers, and LLM judging?
- How should multiple passages support one section score?
- How should scores be normalized across PDFs of very different length?

## Findings

### 1. Two-stage retrieval is the current practical default

Sentence Transformers’ official retrieve-and-rerank guidance recommends:
- an efficient first-stage retriever to pull a large candidate set, e.g. around 100 candidates
- a second-stage cross-encoder reranker to score those candidates more accurately

Implication:
- one-stage section ranking is usually not enough
- first-stage recall and second-stage precision should be separated explicitly

### 2. Re-ranking is strong, but candidate quality is everything

The same Sentence Transformers guidance is clear that the reranker only improves the candidate set it receives.

Implication:
- if the correct section never enters the candidate pool, no later model will rescue it
- the current notebook has this exact weakness because it ranks sections indirectly from a limited chunk recall set

### 3. Hybrid retrieval is still hard to beat

BEIR shows:
- BM25 remains a robust baseline
- re-ranking and late-interaction models perform best on average in zero-shot settings
- dense-only methods are often more efficient but can underperform on generalization

Implication:
- the future pipeline should not rely on dense retrieval alone
- sparse lexical signals are especially important for technical terms, section titles, and standards language

### 4. Long-document retrieval needs document context

DAPR is especially relevant to this project. It studies passage retrieval in long documents and reports that a large share of retrieval errors comes from missing document context.

Its findings:
- long-document passage retrieval is materially different from short-text retrieval
- hybrid retrieval helps overall but can still fail on hard queries that require document context
- contextualized passage representations help when passage meaning depends on the parent document

Implication:
- passages should carry section title, parent title, and possibly document title
- ranking isolated chunks without section context is structurally weak

### 5. Structure-aware chunking helps long documents

MultiDocFusion reports retrieval precision gains from explicitly leveraging document hierarchy.

Even though it targets industrial multimodal documents, the core lesson transfers:
- hierarchy-aware chunking matters
- naive fixed-size chunking loses section semantics

Implication:
- for this notebook’s target task, section-aware chunking is likely more important than elaborate anchor extraction

### 6. Late interaction is attractive if a local retrieval stack is allowed

ColBERT’s late interaction design offers a strong compromise:
- finer-grained matching than simple dense bi-encoders
- cheaper than full cross-encoder scoring over very large corpora
- supports pre-computed document representations

Implication:
- if the project outgrows a notebook or hosted vector-store prototype, late-interaction retrieval is worth considering for high recall on scientific text

## Recommended ranking formulation

The output the user wants is a ranked list of chapters / sections with a usefulness score.

That should be modeled directly:

1. Build explicit section candidates.
2. Retrieve section candidates with hybrid methods.
3. Expand each candidate with its best supporting passages.
4. Rerank sections, not just raw chunks.
5. Produce a calibrated section score.

### Recommended retrieval units

- Primary unit: section / chapter
- Secondary unit: paragraph or short passage inside a section

### Recommended first-stage features

- lexical title match
- lexical body match
- dense semantic similarity
- document-title and section-title similarity
- subpoint coverage from the query decomposition

### Recommended second-stage features

- query vs section-title/body reranking
- query vs top-k passage reranking
- title boost when the section heading itself is directly aligned
- penalties for references, bibliography, appendix, acknowledgements, boilerplate

### Recommended score aggregation

Section score should come from several signals, not only one LLM judgment:

- title score
- best-passage score
- average of top-k supporting passage scores
- query-subpoint coverage
- section-type priors

If a 0-100 score is exposed to users, it should ideally be calibrated on a labeled validation set. Otherwise, score bands are safer than fake precision.

## Strategic conclusions for the notebook

The current notebook mostly does:
- chunk retrieval
- LLM evidence scoring
- optional section recovery later

The stronger architecture is:
- section recovery first
- candidate generation second
- reranking third
- score calibration fourth

That is a real architectural change, not a prompt tweak.

## Source links

- Sentence Transformers retrieve & rerank docs: https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html
- BEIR benchmark: https://arxiv.org/abs/2104.08663
- DAPR benchmark: https://arxiv.org/abs/2305.13915
- ColBERT: https://arxiv.org/abs/2004.12832
- Dense Passage Retrieval (DPR): https://arxiv.org/abs/2004.04906
- MultiDocFusion: https://aclanthology.org/2025.emnlp-main.1062.pdf
