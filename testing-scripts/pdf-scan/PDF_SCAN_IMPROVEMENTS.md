# PDF Scan Research Report

Scope of this report:
- target implementation under review: `pdf-scan/pdf-scan-test.ipynb`
- goal: rank the most useful chapters / sections from one or more digital PDFs for a given input chapter description
- not a code-change pass
- section text extraction is treated as secondary

## Executive Summary

The current notebook is built around the wrong retrieval unit.

Right now the pipeline mostly does:
- retrieve raw vector-store chunks from uploaded PDFs
- ask an LLM to infer which places are relevant
- optionally recover sections later

That is fundamentally weaker than a section-first design.

For stable performance on scientific papers, reports, and books from roughly `2` to `200+` pages, the system should be redesigned around:
- explicit section / chapter candidates
- structure-aware parsing
- section-level retrieval
- second-stage reranking
- calibrated scoring

The main recommendation is:

1. Recover document structure first.
2. Build explicit section candidates.
3. Retrieve and rerank sections, not arbitrary raw chunks.
4. Use LLMs only where they add clear value.

## What Is Wrong With The Current Notebook

The notebook already proves that the basic workflow can run, but it has several structural problems for the actual task.

### 1. It ranks sections indirectly

The target task is:
- "Which chapters / sections in these PDFs are most useful for writing this input chapter?"

The notebook instead does:
- "Which raw chunks look relevant, and can an LLM infer section usefulness from them?"

That creates an avoidable recall bottleneck.

### 2. It is chunk-recall bound

If the right section is not present in the top vector-store hits, the system cannot recover later.

This is especially risky because the current design has:
- a global retrieval step
- a `max_num_results` ceiling
- evidence budgets per PDF
- post-hoc section reasoning after recall is already truncated

### 3. It uses raw PDF chunking rather than structure-aware units

Scientific PDFs often have:
- two-column layouts
- headers / footers
- references and appendices
- formulas, tables, captions
- repeated generic headings
- weak or absent semantic markup

Ranking directly from raw chunks ignores the most useful signal for this task:
- the section boundary itself

### 4. Its scores are not calibrated section scores

The notebook’s `1..10` scores are LLM judgments over limited evidence snippets. They are useful as rough internal ranking hints, but they are not a stable, calibrated user-facing section score.

### 5. Too much complexity is spent on the wrong stage

There is substantial notebook logic for:
- anchor validation
- alternate anchor derivation
- local section recovery from anchor positions

That work is not worthless, but it is not the highest-leverage path for the stated goal. The main job is not anchor recovery. The main job is correct section ranking.

## Research Findings

## 1. Digital PDF extraction is still structurally hard

Even without OCR, digital PDFs are not semantically clean inputs.

From the official `pypdf` documentation:
- PDF files do not contain a semantic layer
- concepts like paragraph, header, footer, table, and page number are not reliably represented

From the official `PyMuPDF` documentation:
- raw text extraction may not follow reading order
- block- and word-based extraction is often needed
- markdown-oriented extraction is specifically recommended for RAG / LLM workflows

What this means for your project:
- "digital PDF only" removes OCR complexity
- it does not remove structure-recovery complexity

## 2. Scientific literature is a special case and should be treated as one

Two tools stood out in the research:

### GROBID

GROBID is specifically built for scholarly PDFs and converts them into structured TEI/XML for text mining and semantic analysis.

Why it matters here:
- papers and reports often follow recognizable scholarly structure
- section titles, bibliography, metadata, and document hierarchy are first-class outputs

### Docling

Docling exposes a structured document abstraction and has chunking / hybrid chunking as explicit concepts.

Why it matters here:
- it is a better fit for a section-aware pipeline than ad-hoc raw text stitching

My conclusion:
- for scientific papers and reports, a specialized parser is very likely worth it
- for books and fallback cases, local PyMuPDF layout heuristics remain useful

## 3. Long-document retrieval should not be built as a single flat chunk search

The retrieval literature and official retrieval tooling are consistent on this point.

### Two-stage retrieval is the practical default

The official Sentence Transformers retrieve-and-rerank guidance recommends:
- a fast first-stage retriever to get a broad candidate set
- a second-stage reranker to score those candidates more accurately

That pattern maps cleanly to your task:
- stage 1: gather plausible sections
- stage 2: rerank sections for usefulness to the target chapter

### Hybrid retrieval remains strong

BEIR shows that:
- BM25 is still a strong baseline
- reranking and late-interaction models are often strongest in zero-shot settings

That matters because your queries are scientific chapter descriptions, not casual web questions. Exact lexical cues still matter a lot:
- section titles
- technical terms
- standards language
- abbreviations

### Long-document retrieval needs context

DAPR is highly relevant here. It shows that a large share of long-document passage retrieval errors come from missing document context.

Practical implication:
- a passage should not be treated as an isolated chunk
- it should carry its parent section and document context

This is one of the clearest arguments against your current raw-chunk-first notebook design.

## 4. The current OpenAI vector-store path has real strengths, but also hard limits

From the official OpenAI docs:
- `vector_stores.search` supports `filters`, `ranking_options`, and `rewrite_query`
- `max_num_results` is limited to `50`
- default chunking is `800` tokens with `400` overlap
- custom `chunking_strategy` is supported
- attached file attributes can be used for filtered search

The notebook currently uses:
- `rewrite_query=True`
- `max_num_results`
- `filters` only as top-up fallback logic

The notebook currently does not use:
- custom chunking
- ranking options
- score thresholds
- structure-aware ingestion

Conclusion:
- OpenAI vector stores can still be part of the solution
- but raw uploaded PDFs plus default chunking is not the strongest setup for your task

## Recommendation Hierarchy

## Recommended architecture: Section-first retrieval pipeline

This is the architecture I would recommend as the default target.

### Stage 1. Parse and normalize the document structure

For each PDF:

1. Read native outline / bookmarks / TOC if present.
2. Run a scholarly parser when applicable:
   - `GROBID` is the strongest candidate for papers and reports.
   - `Docling` is a strong alternative if you want a richer document-object workflow.
3. Use local PyMuPDF fallback heuristics when structured parsing is unavailable or incomplete.

Output of this stage should be a section tree:
- `doc_title`
- `section_id`
- `section_title`
- `section_level`
- `page_start`, `page_end`
- `section_text`
- paragraph / passage children

### Stage 2. Build section candidates

The retrieval unit should be:
- section / chapter as the primary candidate

And each section should also have:
- a list of paragraph or short passage children

This gives you two useful retrieval levels:
- section retrieval
- supporting passage retrieval inside the section

### Stage 3. Query decomposition

Your current idea of preprocessing the chapter description is directionally good, but it should be controlled more tightly.

Recommended query representation:
- original title
- original raw chapter description
- extracted subpoints
- must-terms
- synonyms / support terms

Important:
- do not collapse everything into only one monolithic search string
- run multiple retrieval views and fuse them

### Stage 4. First-stage retrieval

Use hybrid retrieval over sections:
- sparse lexical retrieval
- dense semantic retrieval

What should be indexed:
- section title
- section text
- optional section summary
- document title

For long sections, passage-level retrieval should be used only to support the section score, not to replace the section as the ranking unit.

### Stage 5. Second-stage reranking

Rerank only the top candidate sections.

Strong choices:
- a cross-encoder reranker
- or a carefully constrained LLM judge on a small candidate pool

Inputs to reranking:
- target chapter description
- section title
- section summary or truncated section body
- top supporting passages

### Stage 6. Scoring

Expose a direct usefulness score for each section.

Recommended internal signals:
- title relevance
- best supporting passage relevance
- average top-k passage relevance
- coverage of query subpoints
- penalty for off-scope section types

Recommended user-facing score:
- `0..100`

But only if calibrated later on a benchmark. Otherwise use bands:
- `90-100`: highly useful
- `70-89`: strong match
- `50-69`: partially useful
- `20-49`: weak / tangential
- `0-19`: not useful

## Minimal-change alternative: Keep OpenAI vector stores, but change what gets indexed

If you want to stay close to the current notebook stack, the better path is not:
- raw PDF upload -> default chunking -> search raw chunks

Instead:

1. Parse the PDF locally into structured section text.
2. Serialize sections into structured text or JSONL-like records.
3. Upload those structured records.
4. Retrieve at section granularity.
5. Rerank sections.

This keeps the hosted retrieval path while fixing the largest architectural mistake.

I would still consider this weaker than a full local structure-aware retrieval stack, but much stronger than the current raw-PDF approach.

## What I Would Not Recommend

I would not recommend spending the next iteration on:
- better anchors
- more anchor heuristics
- larger evidence snippets
- prompt-only tweaks to scoring language

Those may improve outputs at the margin, but they do not fix the main failure mode:
- the system is ranking the wrong unit too late

## Specific Areas Worth Tweaking Later

These are the biggest levers I considered that are worth tuning once the architecture is corrected.

### 1. Parser choice by document type

- `GROBID` likely strongest for scholarly articles and many reports.
- `Docling` may be strongest if you want a more flexible document-object workflow.
- `PyMuPDF` should remain the fallback and validation tool.

### 2. Retrieval granularity

- section-only retrieval is interpretable but may miss fine-grained relevance
- section + passage support is likely the best balance

### 3. Chunk size inside sections

Once sections are explicit, passage chunking still matters.

Likely useful later:
- paragraph-based chunks where possible
- otherwise small sliding windows inside a section

### 4. Title boosting

For your task, section titles are unusually important because the output is a chapter / section ranking problem, not only answer extraction.

### 5. Query fusion

Instead of one search string, fuse results from:
- full chapter description
- subpoints
- title-only query
- must-terms query

### 6. Score calibration

If you display `0..100`, calibrate it on labeled data.

Otherwise users will assume a precision that the system does not really have.

### 7. Section-type priors

Some section classes often deserve systematic penalties:
- references
- acknowledgements
- author notes
- appendices
- boilerplate front matter

But this should stay configurable, because some query types really do target appendices or evaluation sections.

## Other Important Things I Noticed

These are not the main topic, but they are likely to matter later.

### 1. Too much logic is buried inside one notebook

The current notebook mixes:
- API setup
- parsing
- retrieval
- LLM prompting
- validation
- output formatting
- cost reporting

That makes it difficult to test and benchmark reliably.

When you move to implementation, this should become:
- parser module
- retrieval module
- reranking module
- evaluation harness
- notebook only as experimentation UI

### 2. The current notebook has hidden coupling between stages

The preprocessing stage changes the retrieval behavior a lot, but there is no evaluation harness around it. That means query expansion errors are hard to catch.

### 3. The current use of hardcoded reuse IDs is practical for experimentation, but dangerous for benchmarking

For benchmark runs, inputs and index state need to be reproducible.

### 4. Cost tracking exists, but quality tracking does not

That is backward relative to your current goal. The missing piece is not more cost visibility. It is ranking quality visibility.

## Benchmark And Test System

You asked for a good system to test and benchmark this later. This is the benchmark I recommend.

## Benchmark goal

Measure whether the system can:
- find the correct sections
- rank them well
- stay stable across short and long PDFs
- produce meaningful scores

## Gold judgment unit

The gold label should be on:
- a section / chapter

Not on:
- raw vector-store chunks
- anchor strings
- generated summaries

## Annotation scale

Use this `0..3` ordinal scale first:

- `0`: irrelevant
- `1`: weak / tangential
- `2`: useful
- `3`: highly useful / central for writing the target chapter

Later you can map it to user-facing `0..100`.

## Recommended initial benchmark corpus

Start with roughly `45` documents:

- `15` short papers / reports: `2-10` pages
- `15` medium papers / surveys: `10-40` pages
- `10` long surveys / standards / reports: `40-120` pages
- `5` very long books / standards / handbooks: `120-250` pages

## Recommended initial query set

Start with `30` target chapter descriptions:

- `10` broad conceptual chapters
- `10` medium-scope chapters with multiple subpoints
- `10` narrow technical chapters

Make sure the query suite mixes:
- near-exact terminology
- paraphrased terminology
- single-concept targets
- multi-subpoint targets

## Metrics

Primary metrics:
- `nDCG@3`
- `nDCG@5`
- `Recall@3`
- `Recall@5`
- `MRR`

Secondary metrics:
- section-boundary quality
- percentage of queries with at least one gold-`3` section in top-3
- score calibration error
- runtime per document
- cost per query

## Stress tests

Include documents with:
- and without outline / bookmark metadata
- two-column layouts
- long reference sections
- appendices
- formulas and tables
- repeated generic section names
- mixed English / German terminology
- long chapters with shallow internal structure

## Regression checks to automate later

- parse success rate
- section count per document
- empty-section rate
- candidate count per query
- reranker latency
- top-k ranking stability
- cost per run

## What You Should Collect Later For The Benchmark

When you are ready to gather documents, these are the criteria I need:

### Documents

Please collect:
- `15` short scientific PDFs (`2-10` pages)
- `15` medium scientific PDFs (`10-40` pages)
- `10` long reports / surveys / standards (`40-120` pages)
- `5` very long books / standards (`120-250` pages)

### Query chapters

Please collect or write:
- `30` chapter descriptions

For each one:
- a short title
- a paragraph-length description
- optional subpoints if the chapter is complex

### Diversity requirements

The set should include:
- papers with clean headings
- papers with messy layout
- documents with and without bookmarks
- documents where the relevant section title is obvious
- documents where relevance is mostly in body text, not the heading

## Final Recommendation

If the goal is to get "close to best in the world" on this task, then the next implementation should not be:
- a better prompt around the same notebook architecture

It should be:
- a structure-first section-retrieval system

My recommended priority order is:

1. Replace raw-PDF chunk ranking with explicit section candidates.
2. Use a scholarly parser plus fallback heuristics.
3. Retrieve sections with hybrid methods.
4. Rerank sections with a stronger second-stage model.
5. Build a real benchmark before tuning further.

## Source Links

- OpenAI vector store search API reference: https://developers.openai.com/api/reference/resources/vector_stores/methods/search
- OpenAI retrieval guide: https://developers.openai.com/api/docs/guides/retrieval
- OpenAI file search guide: https://developers.openai.com/api/docs/guides/tools-file-search
- PyMuPDF text recipes: https://pymupdf.readthedocs.io/en/latest/recipes-text.html
- pypdf text extraction guide: https://pypdf.readthedocs.io/en/stable/user/extract-text.html
- GROBID principles: https://grobid.readthedocs.io/en/latest/Principles/
- Docling docs: https://docling-project.github.io/docling/
- Sentence Transformers retrieve & rerank docs: https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html
- BEIR benchmark: https://arxiv.org/abs/2104.08663
- DAPR benchmark: https://arxiv.org/abs/2305.13915
- ColBERT: https://arxiv.org/abs/2004.12832
- Dense Passage Retrieval: https://arxiv.org/abs/2004.04906
- MultiDocFusion: https://aclanthology.org/2025.emnlp-main.1062.pdf
