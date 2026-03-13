# Benchmark Notes

This file collects ideas for a benchmark and test suite for chapter/section ranking.

## Goal

Design a benchmark that can show:
- whether the correct chapter/section is retrieved
- whether ranking is stable across document length and genre
- whether scores are meaningful
- whether regressions are caught early

## Open items

- corpus composition
- annotation scheme
- scoring rubric
- offline metrics
- stress tests
- latency and cost tracking

## Proposed benchmark design

The benchmark should measure the actual target task:
- given a chapter description
- rank the most useful sections / chapters from one or more PDFs

It should not only measure answer generation quality.

## Unit of judgment

The gold label should be attached to:
- a document section / chapter

Not to:
- raw chunks
- arbitrary evidence snippets

## Suggested label scale

Use ordinal relevance labels first, then map to user-facing scores later.

Recommended annotation scale:

- `0`: irrelevant
- `1`: weak / tangential
- `2`: useful
- `3`: highly useful / central for writing the target chapter

Why:
- easier for human annotation
- supports ranking metrics like nDCG naturally
- later can be mapped to 0-100 or 0-10 bands

## Suggested dataset shape for the first serious benchmark

### Documents

Recommended initial corpus:

- 15 short papers or reports: `2-10` pages
- 15 medium papers or surveys: `10-40` pages
- 10 long surveys / standards / reports: `40-120` pages
- 5 very long books / standards / handbooks: `120-250` pages

Total starting corpus:
- about `45` documents

This is large enough to expose failure modes without being impossible to annotate.

### Query set

Recommended initial query suite:

- 30 target chapter descriptions

Query mix:

- 10 broad conceptual chapters
- 10 medium-scope chapters with several subpoints
- 10 narrow technical chapters

Variation dimensions:

- lexical match vs paraphrase
- single-topic vs multi-subpoint
- title-heavy vs description-heavy
- specific terminology vs synonym-heavy

## Annotation process

For each query:

1. Annotate all major sections in a small candidate pool per document.
2. Mark section relevance on the `0..3` scale.
3. Note the reason:
   - definition
   - mechanism
   - evaluation
   - related work
   - background only
   - off-scope

This reason metadata becomes useful later for error analysis.

## Recommended metrics

Primary metrics:

- `nDCG@3`
- `nDCG@5`
- `Recall@3`
- `Recall@5`
- `MRR`

Secondary metrics:

- section boundary accuracy
- percentage of runs where at least one gold `3` section is in top-3
- score calibration error if exposing numeric scores
- latency per document
- cost per query

## Stress-test buckets

The benchmark should explicitly include:

- PDFs with and without outline/bookmark metadata
- two-column papers
- documents with heavy references / appendix sections
- documents with repeated generic headings
- documents with many formulas or tables
- mixed English / German terminology
- books with very long chapters
- reports with shallow heading hierarchy

## Regression checks to automate later

- extraction success rate
- number of sections detected per document
- empty-section rate
- average passages per section
- retrieval candidate count per document
- reranker latency
- top-k ranking stability across reruns

## Proposed folder structure for later implementation

Do not create it yet in this pass, but this is the shape to use:

```text
pdf-scan/
  benchmark/
    corpus/
      raw/
      manifests/
      parsed/
    queries/
      chapter_specs/
    judgments/
    runs/
    reports/
```

## Source links

- BEIR benchmark: https://arxiv.org/abs/2104.08663
- DAPR benchmark: https://arxiv.org/abs/2305.13915
