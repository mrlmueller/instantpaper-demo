# Web Research - Retrieval, Reranking, And Abstention

Purpose:
- Capture external findings on section retrieval, passage evidence, reranking, per-document balancing, calibrated abstention, and confidence.

## Primary Sources Reviewed

- BEIR benchmark paper: `https://arxiv.org/abs/2104.08663`
- ColBERT paper: `https://arxiv.org/abs/2004.12832`
- Sentence Transformers retrieve-rerank docs: `https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html`
- OpenAI embedding pricing page: `https://platform.openai.com/docs/pricing`
- OpenAI embedding model pages:
  - `https://developers.openai.com/api/docs/models/text-embedding-3-small`
  - `https://developers.openai.com/api/docs/models/text-embedding-3-large`
- xQuAD / explicit diversification reference:
  - `https://ir.webis.de/anthology/2010.ecir_conference-2010.11/`
- Calibrated selective classification:
  - `https://arxiv.org/abs/2208.12084`
- SelectiveNet:
  - `https://arxiv.org/abs/1901.09192`

## Source-Based Findings

### 1. Hybrid retrieval is still the correct default

BEIR remains the most relevant broad retrieval benchmark in this set. Its abstract-level result is clear:
- BM25 is a strong, robust baseline.
- late-interaction and reranking approaches tend to achieve the best zero-shot effectiveness
- but they are more computationally expensive

Implication for this repo:
- keep lexical retrieval
- keep dense retrieval
- do not expect dense-only retrieval to be sufficient

### 2. Cross-encoders are the right precision tool once candidates are small enough

The Sentence Transformers retrieve-rerank documentation explicitly describes the standard pattern:
- first retrieve a broad candidate set with lexical search or a bi-encoder
- then rerank the top candidates with a cross-encoder

The same docs explicitly note that for in-document search on a small paragraph set, one can skip the retrieval stage and score all units directly with the cross-encoder.

Implication:
- For small / medium PDFs, it is feasible to rerank all sections directly.
- For long PDFs, retrieve first, then rerank.

### 3. ColBERT is powerful, but likely optional here

The ColBERT paper argues for late interaction as a way to retain fine-grained query-document matching while allowing document-side precomputation. The paper reports strong effectiveness and much better efficiency than full pairwise BERT scoring.

Inference for this repo:
- ColBERT is attractive if the section collection becomes large or if section + passage search must scale hard.
- For the current per-PDF setting, a simpler hybrid-first-stage plus cross-encoder rerank design is probably enough.
- This is an inference from the paper plus the local section counts in the repo.

### 4. Per-PDF balancing should be explicit, not accidental

The current notebook still fuses candidates across the whole corpus. The user goal is different:
- each PDF should receive its own usefulness decision
- one strong PDF should not suppress others

The xQuAD diversification literature is relevant here, but not in the notebook’s current cross-document form. The important transferable idea is:
- diversify by explicit subtopics / subqueries

Inference:
- xQuAD-style diversification should happen within each document across chapter subpoints, not across all documents together.

### 5. Dense embedding choice should favor cost-effective recall

OpenAI’s current pricing and model pages show:
- `text-embedding-3-small`: `$0.02 / 1M` input tokens
- `text-embedding-3-large`: `$0.13 / 1M` input tokens
- `text-embedding-3-large` is positioned as the more capable model for English and non-English tasks

Local budget implication using the observed run:
- current 620,346 embedding-input tokens would cost about `1.24` cents with `3-small`
- the same run costs about `8.06` cents with `3-large`

Inference:
- use `text-embedding-3-small` for broad recall unless quality tests prove it insufficient
- spend the saved budget on stronger reranking and calibration

### 6. Abstention should be treated as selective prediction

The selective-classification literature is not retrieval-specific, but it is directly useful conceptually:
- SelectiveNet optimizes prediction plus rejection
- calibrated selective classification emphasizes risk-coverage behavior and calibration among accepted predictions

Inference for this repo:
- each PDF-level usefulness decision should be evaluated as a selective prediction problem:
  - accept = "this PDF has useful sections"
  - reject = "no useful material found"
- thresholds should be tuned against coverage-risk trade-offs, not just raw top-score heuristics

## Design Conclusions For This Repo

1. Retrieval unit:
- retrieve sections as the primary unit
- retrieve passages only as supporting evidence for section decisions

2. Ranking architecture:
- per-document retrieval, not one global pool first
- lexical title lane
- lexical body lane
- dense section lane
- optional dense passage lane
- per-document reranking over top-K sections

3. Evidence principle:
- a section should not be judged useful because of broad unigrams alone
- require agreement across:
  - section score
  - evidence passage score
  - lexical or phrase grounding
  - section-type prior

4. Per-document output:
- `useful`: yes / no / uncertain
- if yes:
  - ranked section list
  - why useful
  - which subpoints it supports
  - page spans
  - top evidence passages
- if no:
  - explicit abstention reason

5. Cost-aware recommendation:
- dense retrieval with `text-embedding-3-small`
- cross-encoder or LLM judge only on reduced per-document candidate sets
- cache all embeddings and rerank inputs by run id and content hash

## Current Repo-Specific Warnings

- The current source-term pruning is too literal in Phase D.
- The current trust logic in Phase E is too permissive for weak anchors.
- This combination creates false-positive support while still dropping useful lexical anchors.

Questions to answer here:
- What retrieval architecture best supports section-first ranking?
- How should section and passage evidence interact?
- Which rerankers are strongest for document/section relevance?
- How should per-document balancing be done?
- How should "no useful information in this PDF" be modeled and calibrated?
