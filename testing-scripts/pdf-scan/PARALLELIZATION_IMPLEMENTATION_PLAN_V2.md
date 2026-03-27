# PDF Scan Pipeline — Parallelization & Multi-Chapter Implementation Plan V2

> Status: planning only, no implementation in this document
>
> Scope for implementation:
> - First: `pdf-scan/` only
> - Later: integrate the same architecture into FastAPI / Cloud Run split execution

## 1. Purpose

This document replaces the older [PARALLELIZATION_GUIDE.md](<projektverzeichnis>/pdf-scan/PARALLELIZATION_GUIDE.md) as the working implementation plan.

The old guide is still directionally useful, but the pipeline has changed materially since then:

- the pipeline is now split into a CPU stage and a GPU stage
- Phase F is the main GPU-heavy reranking stage
- the current production architecture already separates `A-E` and `F-G`
- reporting, benchmarking, and run inspection are much richer now than when the old guide was written

So the new plan must be based on the current real system, not the earlier all-in-one local flow.

## 2. Current Baseline

### Current execution shape

- CPU runner: [run_pipeline_cpu.py](<projektverzeichnis>/pdf-scan/run_pipeline_cpu.py)
  - runs `A -> B -> C -> D -> E`
- GPU runner: [run_pipeline_gpu.py](<projektverzeichnis>/pdf-scan/run_pipeline_gpu.py)
  - resumes an existing run dir and runs `F -> G`

### Current structural assumptions

- exactly one chapter/topic per run
- run directory is flat
  - shared `retrieval/`, `rerank/`, `final/`
- `RunArtifacts` in [phase_a_lab.py](<projektverzeichnis>/pdf-scan/phase_a_lab.py) is single-chapter
- Phase D takes one chapter spec
- Phase E retrieves one candidate pool
- Phase F reranks one global candidate pool
- Phase G makes one final per-PDF decision set

### Current bottlenecks relevant to parallelization

- `A-C` are corpus-wide and expensive enough that they should not be repeated per chapter
- `E` still does non-trivial dense/lexical work and should reuse shared section/passage data
- `F` is fast on GPU now, but still the phase most sensitive to memory pressure and batching strategy
- the current run/reporting model assumes a single query plan and a single retrieval/rerank output surface

## 3. High-Level Goal

Extend the pipeline from:

```text
A -> B -> C -> D -> E -> F -> G
```

to:

```text
CPU stage:
  A -> B -> C -> Shared Retrieval Cache Prep -> (D/E per chapter in parallel)

GPU stage:
  (F/G per chapter with bounded concurrency) -> Aggregate output
```

The core idea remains the same as in the old guide:

- run corpus parsing/normalization once
- share expensive corpus-level data across chapters
- fan out chapter-specific retrieval and ranking work
- keep chapter failures isolated
- allow the same PDF/section to appear in multiple chapters

## 4. Questions To Confirm

These are the main open decisions I want confirmed before implementation.

### Q1. Input format for multi-chapter local runs

Recommended default:

- support a `chapters/` folder containing one markdown file per chapter
- each file uses the current `Text Thema.md` style:
  - first non-empty line = chapter title
  - remainder = chapter spec

Alternative:

- one JSON manifest containing all chapters

Recommendation:

- implement both, but treat the `chapters/*.md` folder as the primary user-facing format

### Q2. Should single-chapter runs also use the new multi-chapter layout?

Recommended default: yes

Why:

- one run layout everywhere
- simpler reporting
- simpler FastAPI parity later

That means even one chapter would live under:

```text
runs/<run_id>/chapters/chapter_01/
```

### Q3. Do you want Phase H aggregation implemented in the first `pdf-scan/` pass?

Recommended default: yes, but lightweight

Meaning:

- include a real aggregate output folder
- aggregate chapter outputs into one top-level result
- do not over-engineer cross-chapter deduplication yet

### Q4. What should happen when one chapter fails?

Recommended default:

- other chapters continue
- run finishes as partial success
- aggregate output marks failed chapters explicitly

### Q5. How aggressive should chapter concurrency be by default?

Recommended default:

- CPU chapter fanout (`D/E`): `min(3, chapter_count)`
- GPU chapter fanout (`F/G`): `1` by default, optionally `2` on strong GPUs

Why:

- CPU can overlap multiple retrieval-heavy chapter jobs reasonably well
- GPU reranking is memory-sensitive and should start conservative

### Q6. Should shared embeddings/cache be reusable across different runs with the same corpus?

Recommended default for first pass: no cross-run cache

Meaning:

- cache shared embeddings inside a run
- do not yet introduce a global persistent cache keyed by corpus hash

Why:

- much simpler correctness model
- easier rollout
- enough to unlock chapter parallelization

## 5. Target Architecture

## 5.1 New execution model

### Stage 1: shared corpus preparation

Run once:

- Phase A: resolve inputs and run identity
- Phase B: parse PDFs
- Phase C: normalize sections/passages
- Phase C.5: build shared retrieval-ready cache

Phase C.5 is conceptually new and should produce:

- shared section text table
- shared passage text table
- shared lexical inputs
- shared dense embeddings
- metadata about embedding model, dimensions, counts, and cost

### Stage 2: per-chapter CPU fanout

For each chapter:

- Phase D: query planning
- Phase E: high-recall retrieval

These should run in parallel with a bounded chapter worker pool.

### Stage 3: per-chapter GPU fanout

For each chapter:

- Phase F: reranking
- Phase G: final scoring / per-PDF decision

This should run with bounded GPU concurrency and explicit batching.

### Stage 4: aggregate results

Phase H should:

- collect chapter outputs
- write unified run-level output
- preserve per-chapter outputs without collapsing them

## 5.2 Shared vs chapter-local artifacts

### Shared

- manifest/config
- parser output
- normalized sections/passages
- retrieval cache inputs
- shared embeddings
- shared lexical index inputs
- shared PDF reports base data

### Per chapter

- chapter config
- query plan
- retrieval lanes
- fused candidates
- rerank results
- final scores
- chapter-specific reports

## 6. Proposed New Run Layout

```text
runs/<run_id>/
├── config.json
├── pdf_manifest.json
├── metrics.json
├── api_calls.jsonl
├── logs.jsonl
├── run.log
│
├── phase_a/
├── parser/
├── normalized/
├── shared/
│   ├── retrieval_cache/
│   │   ├── phase_c5_config.json
│   │   ├── phase_c5_summary.json
│   │   ├── section_embeddings.npy
│   │   ├── section_ids.json
│   │   ├── passage_embeddings.npy
│   │   ├── passage_ids.json
│   │   ├── bm25_inputs.json
│   │   └── embedding_metadata.json
│   └── reports/
│
├── chapters/
│   ├── chapter_01/
│   │   ├── chapter_config.json
│   │   ├── retrieval/
│   │   ├── rerank/
│   │   ├── final/
│   │   └── reports/
│   ├── chapter_02/
│   └── ...
│
└── aggregate/
    ├── phase_h_config.json
    ├── phase_h_summary.json
    └── output.json
```

## 7. Data Model Changes

## 7.1 `PhaseAConfig`

Current `PhaseAConfig` in [phase_a_lab.py](<projektverzeichnis>/pdf-scan/phase_a_lab.py) is single-chapter.

It should be replaced with:

- `ChapterSpec`
- `PhaseAConfig.chapters: list[ChapterSpec]`

Backward-compatibility inside `pdf-scan/` is not necessary if we migrate the local runners in the same pass.

Recommended compatibility rule:

- local runner may still accept a single theme markdown
- but internally it becomes `chapters=[chapter_01]`

## 7.2 `RunArtifacts`

Current `RunArtifacts` is flat and single-chapter.

It should become:

- shared paths
- `chapter_artifacts: dict[str, ChapterArtifacts]`
- aggregate paths

### Suggested new classes

- `ChapterSpec`
- `ChapterArtifacts`
- `SharedRetrievalCacheArtifacts`
- extended `RunArtifacts`

## 7.3 `RunContext`

`RunContext` should gain:

- chapter registry
- helper to create per-chapter artifact skeletons
- helper to open chapter-specific child contexts

Recommended design:

- keep one global `RunContext`
- derive light `ChapterRunContext` views for `D-G`

That avoids re-plumbing everything as fully separate run contexts.

## 8. Phase-by-Phase Changes

## 8.1 Phase A

Files:

- [phase_a_lab.py](<projektverzeichnis>/pdf-scan/phase_a_lab.py)
- [run_pipeline_cpu.py](<projektverzeichnis>/pdf-scan/run_pipeline_cpu.py)

Changes:

- accept multiple chapter inputs
- compute `run_id` from:
  - all chapter specs
  - document manifest
  - pipeline version
- write:
  - `chapters/` metadata
  - chapter configs
- build new run skeleton

## 8.2 Phase B

Files:

- [phase_b_lab.py](<projektverzeichnis>/pdf-scan/phase_b_lab.py)

Changes:

- no semantic changes required
- only ensure output remains shared and reusable for multi-chapter downstream work

## 8.3 Phase C

Files:

- [phase_c_lab.py](<projektverzeichnis>/pdf-scan/phase_c_lab.py)

Changes:

- no chapter-specific logic
- output remains shared
- may need a small API cleanup so downstream phases can load normalized rows without assuming one retrieval/final output surface

## 8.4 Phase C.5 shared retrieval cache

This should be a new shared stage.

Recommended file:

- `phase_c5_lab.py`

Responsibilities:

- load normalized sections and passages
- build text payloads for lexical retrieval
- compute section embeddings once
- compute passage embeddings once
- persist deterministic row-id maps

This stage should be designed so Phase E never recomputes corpus embeddings per chapter.

## 8.5 Phase D

Files:

- [phase_d_lab.py](<projektverzeichnis>/pdf-scan/phase_d_lab.py)

Changes:

- accept a `ChapterRunContext`
- write chapter-local outputs
- preserve current query-plan richness
- no shared mutable state

Important:

- D must remain chapter-specific
- D outputs should be independent so failed chapters do not poison the run

## 8.6 Phase E

Files:

- [phase_e_lab.py](<projektverzeichnis>/pdf-scan/phase_e_lab.py)

Changes:

- load shared retrieval cache from Phase C.5
- do not recompute section/passage embeddings per chapter
- keep chapter-specific retrieval lanes and fused candidates

Important:

- retrieval lane logic stays chapter-specific
- corpus vectors/index inputs stay shared

## 8.7 Phase F

Files:

- [phase_f_lab.py](<projektverzeichnis>/pdf-scan/phase_f_lab.py)
- [run_pipeline_gpu.py](<projektverzeichnis>/pdf-scan/run_pipeline_gpu.py)

Changes:

- run per chapter on GPU
- chapter-local rerank outputs
- explicit bounded concurrency
- explicit GPU memory-aware batching

Recommended default:

- one chapter at a time on GPU initially
- optional experimental `--max-gpu-chapter-concurrency 2`

## 8.8 Phase G

Files:

- [phase_g_lab.py](<projektverzeichnis>/pdf-scan/phase_g_lab.py)

Changes:

- final output becomes chapter-local
- aggregate output moves to H

## 8.9 Phase H

Recommended new file:

- `phase_h_lab.py`

Responsibilities:

- collect all chapter `final/output.json`
- produce one run-level aggregate view
- preserve duplicates across chapters
- expose per-chapter summaries and run-level summary

## 9. Local Runner Changes

## 9.1 CPU runner

File:

- [run_pipeline_cpu.py](<projektverzeichnis>/pdf-scan/run_pipeline_cpu.py)

Target behavior:

- accept either:
  - one `--theme-md`
  - or one `--chapters-dir`
  - or one `--chapters-manifest`
- run:
  - `A -> B -> C -> C.5`
- then fan out:
  - `D/E` per chapter

### Recommended CLI additions

- `--chapters-dir`
- `--chapters-manifest`
- `--max-cpu-chapter-concurrency`
- `--end-phase`

## 9.2 GPU runner

File:

- [run_pipeline_gpu.py](<projektverzeichnis>/pdf-scan/run_pipeline_gpu.py)

Target behavior:

- reconstruct multi-chapter run context
- find chapter-local retrieval outputs
- run `F/G` for each chapter
- write aggregate H output

### Recommended CLI additions

- `--chapter-id` for targeted reruns
- `--max-gpu-chapter-concurrency`
- `--skip-phase-h`

## 10. Concurrency Model

## 10.1 CPU side

Recommended:

- one shared corpus pipeline path
- bounded chapter worker pool for `D/E`

Default:

- `max_cpu_chapter_concurrency = min(3, chapter_count)`

Why:

- avoids unbounded OpenAI/embedding fanout
- avoids dense retrieval task oversubscription
- still overlaps query planning and retrieval work well

## 10.2 GPU side

Recommended:

- default chapter concurrency = `1`
- explicit experimental mode = `2`

Why:

- reranker memory pressure is the main operational risk
- a stable default matters more than squeezing the last throughput out immediately

## 10.3 Error isolation

Per chapter:

- D/E failure should not stop other chapters
- F/G failure should not stop other chapters

Run-level status:

- success
- partial_success
- error

## 11. Reporting Changes

Files:

- [pdf_reporting.py](<projektverzeichnis>/pdf-scan/pdf_reporting.py)

Required updates:

- run dashboard must show:
  - chapter list
  - chapter status
  - shared stage status
- per-PDF reporting likely needs a chapter selector because the same PDF will now have:
  - multiple retrieval views
  - multiple rerank views
  - multiple final decisions

Recommended structure:

- keep shared per-PDF structural data once
- attach chapter-local retrieval/rerank/final blocks beneath it

## 12. Benchmarking & Validation

We should not implement this without dedicated validation, because concurrency bugs are easy to miss.

## 12.1 Required validation layers

1. Single-chapter equivalence
- new multi-chapter architecture with one chapter should match current outputs closely

2. Two-chapter overlap case
- verify shared corpus processing runs once
- verify chapter outputs do not overwrite each other

3. Failure isolation
- deliberately break one chapter
- ensure others still complete

4. GPU chapter rerun
- rerun one chapter F/G without rebuilding the whole run

5. Reporting correctness
- chapter-specific reports match chapter-specific outputs

## 12.2 Benchmark suites to use

Primary:

- current exhaustive benchmark suites already in `pdf-scan/benchmark/`

Recommended test modes:

- one chapter only
- 2-3 chapters on same corpus
- mixed-topic chapters on same corpus

## 13. Implementation Order

Recommended order:

1. Add new chapter-aware config and run layout in Phase A
2. Add shared retrieval cache stage C.5
3. Make D/E chapter-local while reading shared data
4. Update CPU runner for chapter fanout
5. Make F/G chapter-local
6. Update GPU runner
7. Add H aggregate output
8. Update reporting
9. Add validation harness and rerun benchmarks

## 14. Risks

### Risk 1: stale assumptions in flat-path helpers

A lot of helper code likely assumes:

- one `query_plan.json`
- one `retrieval/`
- one `rerank/`
- one `final/`

This is the biggest structural migration risk.

### Risk 2: OpenAI call fanout gets too aggressive

Parallel D/E across chapters can spike:

- planner calls
- embedding calls
- judge calls if any CPU-side work expands

We need explicit concurrency caps.

### Risk 3: GPU oversubscription

Even if one chapter rerank works well, two chapters concurrently may hit:

- OOM
- degraded throughput
- unstable latency

So the default should stay conservative.

### Risk 4: reporting explosion

Per-PDF reports can become too noisy if we simply duplicate every chapter block.

The reporting redesign should be explicit, not incidental.

## 15. Future FastAPI Integration Plan

Not for implementation yet, but we should design with it in mind now.

### Desired FastAPI shape later

- CPU job:
  - `A -> B -> C -> C.5 -> D/E fanout`
- GPU job:
  - `F/G fanout -> H`

### Important consequences

- handoff contract must become chapter-aware
- handoff bundle should contain:
  - shared cache artifacts
  - chapter-local retrieval outputs
  - chapter manifest
- Firestore run schema will need:
  - shared stage progress
  - per-chapter stage progress
  - aggregate run status

### Important planning rule

The `pdf-scan/` implementation should not hardcode local-only assumptions that make the later CPU/GPU Cloud Run handoff harder.

That means:

- deterministic chapter manifests
- deterministic artifact paths
- clean schema versioning in handoff artifacts

## 16. Recommendation

Implement this in one controlled local-first pass inside `pdf-scan/`, but keep the rollout narrow:

- first target: multi-chapter support with chapter-local D/E/F/G and shared A/B/C/C.5
- conservative default concurrency
- strong validation
- no FastAPI implementation yet

That gives the highest value with the lowest risk.

## 17. Immediate Next Step

Before implementation, confirm the six questions in Section 4.

My recommended defaults are:

- input format: `chapters/*.md` plus optional manifest
- single-chapter uses new chapter layout too
- include Phase H now
- failed chapters do not stop others
- CPU chapter concurrency default `min(3, chapter_count)`
- GPU chapter concurrency default `1`
- no cross-run shared cache yet
