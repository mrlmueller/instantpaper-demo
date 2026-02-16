# Two‑Lane Pipeline Cheat Sheet (Phases A–K)

This is a **change‑impact aware** guide to the two‑lane literature retrieval pipeline implemented in:

- Notebook (source of truth): `sources-v2/sources_two_lane.ipynb`
- Blueprint (intended design, not 1:1 implemented): `sources-v2/TWO_LANE_PIPELINE_IMPLEMENTATION_PLAN_FROM_REPORT.md`
- Example run used for concrete snippets/counts: `sources-v2/runs/4af2666be828e5054ccf4d31/`

> **Phase J is intentionally missing** in the notebook (not implemented). The cheat sheet still documents where it would slot in.

---

## How to use this cheat sheet

When you want to change the pipeline:

1. **Find the phase** you plan to edit (A…K).
2. Read **Inputs → Outputs → Caching & invalidation → Downstream impact**.
3. Use the **Rerun matrix** (Appendix C) to avoid stale caches and inconsistent artifacts.
4. When debugging a run, start with:
   - `runs/<run_id>/metrics.json` (durations + stage counts + usage summaries)
   - `runs/<run_id>/logs.jsonl` (structured event stream; provider requests, cache hits/writes, errors)
   - `runs/<run_id>/run.log` (human‑readable logger output; much shorter than `logs.jsonl`)

Conventions used in this doc:

- Paths are **relative** (e.g. `runs/<run_id>/query_plan.json`).
- Small JSON snippets use `…` for omitted fields.
- “Downstream impact” bullets explicitly connect phases (what changes propagate and why).

---

## Glossary & invariants

### Core terms

- **Run**: one execution of the notebook for one `(chapter_title, chapter_spec_text, pipeline_version)`. A run’s artifacts live under `runs/<run_id>/…`.
- **`run_id`**: stable hash computed from `chapter_title + chapter_spec_text + pipeline_version` (Phase A).
- **Lane**:
  - `match`: prioritize topical fit + facet coverage.
  - `authority`: prioritize scholarly importance **but still should be relevant**.
- **Pool** (hard separation throughout):
  - `with_abstract`: candidates that have an abstract text.
  - `without_abstract`: candidates without an abstract; treated as metadata‑only.
- **Facet**: an **atomic** (single idea) bilingual (EN+DE) retrieval/scoring aspect produced by the query planner (Phase B). Facet order becomes the canonical index for all `facet_scores[*]` arrays downstream.
- **Primary context anchors**: short bilingual anchor terms that keep queries and scoring on‑topic.
- **Candidate**: normalized, cross‑provider deduplicated record with canonical ID and provenance (`sources`, `intents`) (Phase E).
- **Stage 1 scoring**: metadata‑embedding similarity against facet embeddings (Phase F).
- **Stage 2 scoring**: abstract chunk embeddings + MaxSim‑like aggregation per facet (Phase F; `with_abstract` shortlist only).
- **Coverage tags**: per‑record facet evidence excerpts (Phase H).
- **Rerank**: top‑K per lane/pool pointwise LLM scoring; used to reorder the top segment (Phase I).

### Hard invariants (pipeline‑wide)

- **Pool non‑mixing**: `with_abstract` and `without_abstract` are **never** mixed for ranking/rerank selection.
- **Bilingual retrieval requirement**: query builders must emit **English + German** queries (Phase C QC enforces).
- **Query budget**: ≤ `cfg.max_queries_per_provider` (default 50) per provider per run (Phase C QC enforces).
- **Facet index stability**: downstream `facet_scores_*` arrays assume the facet order written to `runs/<run_id>/facets_index.json`.

### Important current behaviors (affect tuning)

- **Lane isolation exists today (Phase F pruning)**: lane shortlists are built from `candidate.intents` provenance (`_eligible(cid, lane) := lane in candidate.intents`). This can shrink the authority universe and is called out in `sources-v2/TWO_LANE_PIPELINE_AUDIT.md` + `sources-v2/TWO_LANE_PIPELINE_FIXES.md`.
- **Artifacts often embed absolute paths** (Windows) inside JSON fields (e.g. `metrics.json`), but the pipeline logic uses `run_ctx` paths. This cheat sheet uses relative paths.

---

## Pipeline overview (A → K; J missing)

```mermaid
flowchart LR
  A[Phase A<br/>Run setup + config + logging] --> B[Phase B<br/>LLM query plan (facets + anchors)]
  B --> C[Phase C<br/>LLM provider query builders]
  C --> D[Phase D<br/>Retrieval + per-query caches<br/>+ raw aggregates]
  D --> E[Phase E<br/>Normalize + dedup + pool split]
  E --> F[Phase F<br/>Embeddings + Stage1 + prune<br/>+ Stage2 chunk scoring]
  F --> G[Phase G<br/>Lane fusion + scores_final<br/>+ rankings_stageg]
  G --> H[Phase H<br/>Coverage tags + evidence excerpts]
  H --> I[Phase I<br/>LLM rerank top-K<br/>+ rankings_stagei]
  I --> K[Phase K<br/>Final lane construction<br/>+ output.json]

  J[Phase J<br/>Coverage top-up<br/>(not implemented)] -. intended slot .-> K
```

---

## Run directory layout (`runs/<run_id>/…`)

This directory is the unit of reproducibility. Files fall into four buckets:

- **Inputs (cached)**: deterministic outputs of earlier phases that later phases reuse.
- **Cache**: per-query / per-text caches that are safe to delete (will rebuild).
- **Derived**: intermediate artifacts that later phases consume.
- **Final**: `output.json`.
- **Observability**: `metrics.json`, `logs.jsonl`, `run.log`.

> The notebook writes most files atomically via `*.tmp` then rename. If a run crashes, you may see leftover `*.tmp` or `*.failed.*` files; they are debugging artifacts, not pipeline inputs.

### LLM planner + builders (cached inputs to later phases)

- `runs/<run_id>/query_plan.json` (Phase B; consumed by Phases C + F)
  - Stable debug (last successful call): `runs/<run_id>/query_plan.raw_output.json`, `runs/<run_id>/query_plan.openai_meta.json`
  - Attempts (per validation retry): `runs/<run_id>/query_plan_attempt<N>.*` (system/user prompt, response.json, output_text.txt, raw_output.json, call_meta.json, openai_meta.json)
  - Cache-invalid marker: `runs/<run_id>/query_plan.cache_invalid.json` (written if `query_plan.json` exists but fails strict validation)

- `runs/<run_id>/openalex_queries.json` (Phase C OpenAlex builder; consumed by Phase D)
  - Stable debug: `runs/<run_id>/openalex_queries.raw_output.json`, `runs/<run_id>/openalex_queries.openai_meta.json`
  - Attempts: `runs/<run_id>/openalex_queries_attempt<N>.*`
  - Cache-invalid marker: `runs/<run_id>/openalex_queries.cache_invalid.json`

- `runs/<run_id>/semanticscholar_queries.json` (Phase C S2 builder; consumed by Phase D)
  - Stable debug: `runs/<run_id>/s2_bulk_queries.raw_output.json`, `runs/<run_id>/s2_bulk_queries.openai_meta.json`
  - Attempts: `runs/<run_id>/s2_bulk_queries_attempt<N>.*`
  - Cache-invalid marker: `runs/<run_id>/s2_bulk_queries.cache_invalid.json`

### Retrieval (cache + derived aggregates)

- Per-query provider caches (**cache**; safe to delete to force refetch):
  - `runs/<run_id>/cache/openalex/<query_hash>.jsonl` (Phase D; 1 file/OpenAlex query)
  - `runs/<run_id>/cache/semanticscholar/<query_hash>.jsonl` (Phase D; 1 file/S2 query)
  - Failure debug (if a query errors mid-write): `runs/<run_id>/cache/<provider>/<query_hash>.jsonl.failed.<timestamp>`

- Raw aggregates (**derived**; rebuilt from the “used cache paths” in query order):
  - `runs/<run_id>/openalex_raw.jsonl` (Phase D; consumed by Phase E)
  - `runs/<run_id>/semanticscholar_raw.jsonl` (Phase D; consumed by Phase E)

### Candidate universe (derived)

- `runs/<run_id>/candidates_normalized.jsonl` + `runs/<run_id>/candidates_normalized.csv` (Phase E; consumed by Phases F + K)
- `runs/<run_id>/candidates_expanded.jsonl` (Phase F; optional; does **not** overwrite Phase E outputs; consumed by Phases G/H/I/K when present)
- `runs/<run_id>/semanticscholar_recommendations.jsonl` (Phase F; append-only provenance of S2 Recommendations expansion)

### Embeddings (cache + derived manifests)

- Run-local vector cache (**cache**; expensive to rebuild):
  - `runs/<run_id>/embeddings_vectors/<model>/*.f32` (Phase F)
- Shared global vector cache (**cache**; shared across runs):
  - `sources-v2/embeddings_cache_global/<model>/*.f32` (Phase F)
- Manifests (**derived**):
  - `runs/<run_id>/embeddings_manifest.jsonl` (Phase F; append-only; which hashes were hit/created)
  - `runs/<run_id>/embeddings_manifest.csv` (Phase A skeleton placeholder; currently left empty by the notebook)

### Scoring + rankings (derived)

- Facet index contract:
  - `runs/<run_id>/facets_index.json` (Phase F; canonical facet order + weights; consumed by Phases G/H/I/K)
- Scoring outputs:
  - `runs/<run_id>/scores_stage1.jsonl` (Phase F; all candidates)
  - `runs/<run_id>/shortlists_stage1.json` (Phase F; pruned ids per lane/pool)
  - `runs/<run_id>/scores_stage2.jsonl` (Phase F; Stage2-scored ids only; includes `evidence_chunks`)
  - `runs/<run_id>/scores_final.jsonl` (Phase G; later **rewritten** by Phase H to embed `coverage_tags`)
- Ranking outputs:
  - `runs/<run_id>/rankings_stageg.json` (Phase G; lane/pool rankings from fused scores)

### Coverage + rerank (derived + cache)

- Coverage tags:
  - `runs/<run_id>/coverage_tags.jsonl` (Phase H; compact `{id,pool,coverage_tags}`; derived)
- Rerank cache (**cache**):
  - `runs/<run_id>/cache/rerank/<task_hash>.json` (Phase I; 1 file per candidate × lane × pool task)
- Rerank aggregates (**derived**):
  - `runs/<run_id>/rerank_results.jsonl` (Phase I; aggregated rerank outputs + OpenAI meta)
  - `runs/<run_id>/rankings_stagei.json` (Phase I; stageg rankings with top‑K reranked)

### Final output + observability

- Final output:
  - `runs/<run_id>/output.json` (Phase K)
- Observability:
  - `runs/<run_id>/metrics.json` (stage durations, counts, OpenAI usage/cost, etc.)
  - `runs/<run_id>/logs.jsonl` (structured events from `log_event`; includes cache hits/writes + HTTP request traces)
  - `runs/<run_id>/run.log` (human-readable logger stream; short)

---

## Example run summary (`4af2666…`)

Example run directory: `runs/4af2666be828e5054ccf4d31/` (created `2026-02-15T15:41:38Z`, updated `2026-02-15T16:12:04Z`).

**Counts**

- Phase C queries: OpenAlex `42`, S2 bulk `35` (budget cap is 50/provider).
- Phase D retrieval records: OpenAlex `11,139`, S2 `19,618` (all cache writes; no cache hits).
- Phase E candidates: normalized `30,507` → deduped `25,524` (merges `4,886`), pools: `with_abstract=15,625`, `without_abstract=9,899`.
- Phase F: S2 recommendations expansion enabled; post-expansion candidate count `26,922`; Stage2 scored `1,133` (with-abstract shortlist union).
- Phase G shortlist size: `1,686` unique ids (these are the only ids carried forward into `scores_final.jsonl`).
- Phase H coverage tags: `13,830` total; fallback excerpts `2,007` (all `without_abstract` tags in this run).
- Phase I rerank: tasks `160` (= top‑40 × 4 lane/pool groups), failures `0`.
- Phase K output: top‑N `20` per lane/pool; rerank rows loaded `160`.

**Costs (list-price estimates from local price table)**

- Planner (Phase B): `$0.0553`
- Query builders (Phase C): OpenAlex `$0.0609`, S2 `$0.0472`
- Embeddings (Phase F): `$0.0481`
- Rerank (Phase I): `$0.1608`
- Total: **`$0.3723`**

**Durations (from `metrics.json`)**

- Slowest stages: planner `444s`, retrieval `294s`, rerank `275s`, OpenAlex builder `240s`, S2 builder `178s`.
- Phase F/G overall timers are `null` in this run because the notebook does not wrap the full phase in `stage_timer` (only sub-stages are timed for Phase F).

**Artifact size snapshot**

- Biggest top-level files: `openalex_raw.jsonl` `72.70 MB`, `candidates_expanded.jsonl` `54.37 MB`, `candidates_normalized.jsonl` `51.94 MB`, `semanticscholar_raw.jsonl` `44.12 MB`.
- Cache folders:
  - `cache/openalex/`: `42` files (`72.70 MB`)
  - `cache/semanticscholar/`: `35` files (`44.12 MB`)
  - `cache/rerank/`: `160` files (`311 KB`)
  - `embeddings_vectors/`: `35,391` files (`207.37 MB`)

---

## Artifact manifest (example run `4af2666…`)

Columns: artifact path is relative to `runs/<run_id>/…`.

| Artifact                                                        | Produced by                                  | Consumed by                 | Notes                                                                                                                                                              |
| --------------------------------------------------------------- | -------------------------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `runs/<run_id>/query_plan.json`                                 | Phase B (cells 08–09)                        | Phases C, F                 | Strict `QueryPlan` JSON (facets + anchors). Cache reused unless `FORCE_REBUILD_QUERY_PLAN`.                                                                        |
| `runs/<run_id>/query_plan.raw_output.json`                      | Phase B (cell 08)                            | —                           | Last successful raw JSON from OpenAI (debug).                                                                                                                      |
| `runs/<run_id>/query_plan.openai_meta.json`                     | Phase B (cell 08)                            | —                           | OpenAI usage/cost/meta for last success (debug).                                                                                                                   |
| `runs/<run_id>/query_plan_attempt1.*`                           | Phase B (cell 08)                            | —                           | Attempt bundle (prompts + response + raw_output + meta). Not consumed downstream.                                                                                  |
| `runs/<run_id>/query_plan_attempt2.*`                           | Phase B (cell 08)                            | —                           | Attempt bundle (this run needed 2 attempts due to lint failure).                                                                                                   |
| `runs/<run_id>/openalex_queries.json`                           | Phase C (cells 10–11)                        | Phase D                     | Provider query objects (`OpenAlexQuery[]`). Cache reused unless `FORCE_REBUILD_PROVIDER_QUERIES`.                                                                  |
| `runs/<run_id>/openalex_queries.raw_output.json`                | Phase C (cell 10)                            | —                           | Last successful raw JSON from OpenAI (debug).                                                                                                                      |
| `runs/<run_id>/openalex_queries.openai_meta.json`               | Phase C (cell 10)                            | —                           | OpenAI usage/cost/meta for last success (debug).                                                                                                                   |
| `runs/<run_id>/openalex_queries_attempt1.*`                     | Phase C (cell 10)                            | —                           | Attempt bundle (prompts + response + raw_output + meta).                                                                                                           |
| `runs/<run_id>/semanticscholar_queries.json`                    | Phase C (cells 10–11)                        | Phase D                     | Provider query objects (`S2BulkQuery[]`). Cache reused unless `FORCE_REBUILD_PROVIDER_QUERIES`.                                                                    |
| `runs/<run_id>/s2_bulk_queries.raw_output.json`                 | Phase C (cell 10)                            | —                           | Last successful raw JSON from OpenAI (debug).                                                                                                                      |
| `runs/<run_id>/s2_bulk_queries.openai_meta.json`                | Phase C (cell 10)                            | —                           | OpenAI usage/cost/meta for last success (debug).                                                                                                                   |
| `runs/<run_id>/s2_bulk_queries_attempt1.*`                      | Phase C (cell 10)                            | —                           | Attempt bundle (prompts + response + raw_output + meta).                                                                                                           |
| `runs/<run_id>/cache/openalex/*.jsonl` (42 files)               | Phase D (cell 12)                            | Phase D (aggregate rebuild) | Per-query OpenAlex caches: one JSONL row per retrieved work, tagged with `{provider, query_hash, intent, language, rank, work}`. Safe to delete to refetch.        |
| `runs/<run_id>/cache/semanticscholar/*.jsonl` (35 files)        | Phase D (cell 12)                            | Phase D (aggregate rebuild) | Per-query S2 caches: one JSONL row per hydrated paper, tagged with `{provider, query_hash, intent, language, rank, paper}`. Safe to delete to refetch.             |
| `runs/<run_id>/openalex_raw.jsonl`                              | Phase D (cell 12)                            | Phase E                     | Aggregate concatenation of “used cache paths” in query order. Rebuilt every run (even if caches are hits).                                                         |
| `runs/<run_id>/semanticscholar_raw.jsonl`                       | Phase D (cell 12)                            | Phase E                     | Same as above for S2.                                                                                                                                              |
| `runs/<run_id>/candidates_normalized.jsonl`                     | Phase E (cell 14)                            | Phases F, K                 | Canonical `Candidate` JSONL (deduped, with provenance `sources[]` and `intents[]`). Cache reused if present and upstream not forced.                               |
| `runs/<run_id>/candidates_normalized.csv`                       | Phase E (cell 14)                            | —                           | Convenience view for humans; not used downstream.                                                                                                                  |
| `runs/<run_id>/semanticscholar_recommendations.jsonl`           | Phase F (cell 15)                            | —                           | Append-only provenance log for S2 Recommendations expansion: `{seed_paperId, paperId, rank}`.                                                                      |
| `runs/<run_id>/candidates_expanded.jsonl`                       | Phase F (cell 15)                            | Phases G, H, I, K           | Expanded candidate pool after S2 Recommendations merge/dedup. When present, later phases join metadata from this file (instead of normalized).                     |
| `runs/<run_id>/embeddings_manifest.jsonl`                       | Phase F (cell 15)                            | —                           | Append-only embedding manifest (hashes, cache hits, file paths). Helpful for debugging cache behavior.                                                             |
| `runs/<run_id>/embeddings_manifest.csv`                         | Phase A (cell 04/05)                         | —                           | Placeholder created in artifact skeleton; currently left empty.                                                                                                    |
| `runs/<run_id>/embeddings_vectors/<model>/*.f32` (35,391 files) | Phase F (cell 15)                            | Phase F                     | Run-local embedding cache (float32 vectors). Large; safe to delete but expensive to rebuild.                                                                       |
| `sources-v2/embeddings_cache_global/<model>/*.f32`              | Phase F (cell 15)                            | Phase F                     | Global embedding cache (shared across runs; used as cache hits). Not inside `runs/<run_id>/`.                                                                      |
| `runs/<run_id>/facets_index.json`                               | Phase F (cell 15)                            | Phases G, H, I, K           | Canonical facet id order + weights. All downstream `facet_scores[*]` arrays are aligned to this file.                                                              |
| `runs/<run_id>/scores_stage1.jsonl`                             | Phase F (cell 15)                            | Phase G                     | Stage 1 scores per candidate: match parts + lane scores + `facet_scores_stage1[]`.                                                                                 |
| `runs/<run_id>/shortlists_stage1.json`                          | Phase F (cell 15)                            | Phase F (Stage2), Phase G   | Pruned ids per lane/pool. Also the contract for which ids proceed into `scores_final.jsonl`.                                                                       |
| `runs/<run_id>/scores_stage2.jsonl`                             | Phase F (cell 15)                            | Phase G                     | Stage 2 scores (with-abstract shortlist only): `facet_scores_stage2[]` + `evidence_chunks[]`.                                                                      |
| `runs/<run_id>/scores_final.jsonl`                              | Phase G → rewritten by Phase H (cells 16–17) | Phases H, I, K              | Final merged rows for shortlisted ids: `scores{…}`, `facet_scores{stage,scores[]}`, plus `evidence_chunks[]`; Phase H rewrites this file to add `coverage_tags[]`. |
| `runs/<run_id>/rankings_stageg.json`                            | Phase G (cell 16)                            | Phases H, I, K (fallback)   | Lane/pool rankings based on fused score recomputation.                                                                                                             |
| `runs/<run_id>/coverage_tags.jsonl`                             | Phase H (cell 17)                            | —                           | Compact export of coverage tags (also embedded into `scores_final.jsonl` in Phase H).                                                                              |
| `runs/<run_id>/cache/rerank/*.json` (160 files)                 | Phase I (cell 18)                            | Phase I (aggregate)         | Per-task rerank caches keyed by `(run_id, id, lane, pool)`. Safe to delete to rerun rerank.                                                                        |
| `runs/<run_id>/rerank_results.jsonl`                            | Phase I (cell 18)                            | Phase K                     | Aggregated rerank outputs + OpenAI meta for all tasks.                                                                                                             |
| `runs/<run_id>/rankings_stagei.json`                            | Phase I (cell 18)                            | Phase K                     | Stage G rankings with top‑K replaced by rerank order (two-tier sort).                                                                                              |
| `runs/<run_id>/output.json`                                     | Phase K (cell 19)                            | —                           | Final output (`two_lane_output_v1`): two lanes × two pools, `primary_top_20`, empty `coverage_top_up` (Phase J missing).                                           |
| `runs/<run_id>/metrics.json`                                    | Phase A+ (cells 04–19)                       | Phase K + humans            | Structured per-stage metrics: durations, counts, OpenAI usage/cost, embedding stats. Contains absolute paths in some fields (Windows).                             |
| `runs/<run_id>/logs.jsonl`                                      | Phase A+ (cells 04–19)                       | Phase K + humans            | Structured event stream from `log_event`: cache hits/writes, HTTP requests, errors, rebuild markers. Contains absolute paths.                                      |
| `runs/<run_id>/run.log`                                         | Phase A+ (cells 04–19)                       | —                           | Human-readable logger output (compact).                                                                                                                            |

---

## Notebook cell map (`sources_two_lane.ipynb`)

Cell indices are 0-based (as stored in the `.ipynb`). Cell `id` is the stable Jupyter cell id.

| Phase   | Notebook cell (index, id) | Stage key in `metrics.json` / `logs.jsonl`                                                               | Main responsibilities                                                                                                       |
| ------- | ------------------------- | -------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| 0       | 02, `1b6e3b7b`            | —                                                                                                        | User inputs: chapter text + `pipeline_version` + FORCE flags + `PRUNE_N1_NO_ABS`.                                           |
| A.0     | 03, `d3f3ac7f`            | —                                                                                                        | Imports, dotenv load, formatting/QC helpers, table printers.                                                                |
| A.1     | 04, `e8cc3f52`            | —                                                                                                        | `PipelineConfig`, `RunContext/RunArtifacts`, `log_event`, `stage_timer`, JSON/JSONL helpers.                                |
| A.2     | 05, `8b49a97b`            | `phase_a`                                                                                                | Build config from env + overrides, compute `run_id`, create run dir + artifact skeleton, inventory report.                  |
| B.1     | 06, `fbf0f4fb`            | —                                                                                                        | Pydantic `QueryPlan/Facet/BilingualTerms` models (strict).                                                                  |
| B.2     | 07, `b2eb0b5d`            | —                                                                                                        | `openai_json_schema_call` + usage/cost parsing + debug dumping.                                                             |
| B.3     | 08, `1d3de58c`            | `phase_b_query_planner`                                                                                  | Planner prompt + JSON schema + hygiene lints + caching + retries.                                                           |
| B.4     | 09, `6cc4a2c3`            | `phase_b_query_planner`                                                                                  | Run planner, print/QC facets, show cost.                                                                                    |
| C.0–C.3 | 10, `b84430b0`            | `phase_c_openalex_query_builder`, `phase_c_s2_query_builder`                                             | Provider query schemas/prompts + deterministic normalizers/lints + cache.                                                   |
| C.4     | 11, `c83fc2d4`            | `phase_c_*`                                                                                              | Run both query builders + QC summaries/plots.                                                                               |
| D       | 12, `6d0e1c3e`            | `phase_d_retrieval` (metrics), `phase_d_openalex_retrieval` / `phase_d_semanticscholar_retrieval` (logs) | Retrieval clients, rate limiting, retries, per-query caches, raw aggregates, metrics.                                       |
| E       | 14, `d8aacd00`            | `phase_e_candidates`                                                                                     | Normalize OA/S2 raw → `Candidate`, cross-provider dedup + merge precedence, pool split, write JSONL+CSV.                    |
| F       | 15, `3837b017`            | `phase_f_*` sub-stages + `phase_f` (counts only)                                                         | Embedding caches (local+global), Stage1 scoring, S2 rec expansion, prune + lane isolation, Stage2 chunk scoring + evidence. |
| G       | 16, `a68590e2`            | `phase_g` (counts only)                                                                                  | Recompute exact formulas, build `scores_final.jsonl` + `rankings_stageg.json`, QC.                                          |
| H       | 17, `98b29fb2`            | `phase_h_coverage_tags`                                                                                  | Compute coverage tags and excerpts; write `coverage_tags.jsonl`; rewrite `scores_final.jsonl` to embed `coverage_tags`.     |
| I       | 18, `phase_i_rerank`      | `phase_i_rerank`                                                                                         | Rerank top‑K per lane/pool with caches; write `rerank_results.jsonl` + `rankings_stagei.json`.                              |
| K       | 19, `c2f3d8a1`            | `phase_k_output`                                                                                         | Select rankings used; authority time bucketing; assemble `two_lane_output_v1`; write `output.json`.                         |
| —       | 20, `9d4dcdb5`            | —                                                                                                        | Final report/dashboard (summaries + links).                                                                                 |

---

## Phase A — Config, run artifacts, and logging

**Prev:** Phase 0 (User Inputs cell) → **Next:** Phase B (LLM Query Planner)

### 1) Goal

Create a single, stable **run context** (config + paths + logging) so every downstream phase can:

- read/write under `runs/<run_id>/…`
- log to `logs.jsonl` + `run.log`
- record timing/counts into `metrics.json`

### 2) Inputs

**User inputs (cell 02, `1b6e3b7b`)**

- `chapter_title` (string)
- `chapter_spec_text` (string; run_id changes if this text changes)
- `pipeline_version` (string; also part of run_id)
- `FORCE_REBUILD_QUERY_PLAN` (Phase B cache bypass)
- `FORCE_REBUILD_PROVIDER_QUERIES` (Phase C cache bypass)
- `FORCE_REBUILD_RETRIEVAL` (Phase D cache bypass)
- `PRUNE_N1_NO_ABS` (overrides `cfg.prune_n1_without_abstract`; affects Phase F pruning and therefore Stage2 workload/cost)

**Environment variables (cell 03, `d3f3ac7f`)**

- Required (the notebook QC marks missing as `FAIL`):
  - `OPENAI_API_KEY` (Phases B/C/I)
  - `OPENALEX_API_KEY` (Phase D)
  - `SEMANTICSCHOLAR_API_KEY` (Phase D + Phase F rec expansion; Phase D can still run without, but QC expects it)
- Recommended:
  - `OPENALEX_EMAIL` or `OPENALEX_MAILTO` (OpenAlex etiquette; Phase D attaches as `mailto=…`)

**Filesystem / repo context**

- Repo root is discovered (walk up until `.git/`).
- Notebook dir is discovered by searching for `sources_two_lane.ipynb`; `cfg.runs_root` defaults to `<notebook_dir>/runs`.

### 3) Outputs

**Run identity + paths**

- `run_id` (24 hex chars): `stable_hash(pipeline_version, chapter_title, chapter_spec_text)`
- `run_dir`: `runs/<run_id>/`
- `RunArtifacts` path bundle used everywhere downstream

**Artifact skeleton (created/touched; Phase A.2, cell 05 `8b49a97b`)**

- Ensures directories exist:
  - `runs/<run_id>/`
  - `runs/<run_id>/embeddings_vectors/`
- Touches JSONL files (creates empty file if missing):
  - `openalex_raw.jsonl`, `semanticscholar_raw.jsonl`
  - `semanticscholar_recommendations.jsonl`
  - `candidates_normalized.jsonl`
  - `embeddings_manifest.jsonl`
  - `rerank_results.jsonl`
  - `logs.jsonl`
- Touches logger file:
  - `run.log`
- Creates empty CSV placeholders if missing:
  - `candidates_normalized.csv`
  - `embeddings_manifest.csv` (currently stays empty in later phases)
- Initializes `metrics.json` (if missing):
  - `{run_id, created_at_utc, stages:{}}`

### 4) Processing (How it works)

Key code locations to edit (Phase A.1/A.2):

- `PipelineConfig` + `PipelineConfig.from_env` (cell 04)
- `compute_run_id` / `stable_hash` (cell 04)
- `RunArtifacts`, `RunContext.create_artifact_skeleton` (cell 04)
- `setup_run_logger`, `log_event`, `stage_timer` (cell 04)

Step-by-step:

1. **Discover paths**: determine `REPO_ROOT` and `NOTEBOOK_DIR` (cell 03).
2. **Load env**: load `REPO_ROOT/.env` (`override=True`), then `fastapi/.env` (`override=False`) (cell 03).
3. **Build config**: `cfg = PipelineConfig.from_env(...)` (cell 05).
4. **Apply notebook override**: `cfg.prune_n1_without_abstract = PRUNE_N1_NO_ABS` (cell 05).
5. **Compute run_id**: `run_id = compute_run_id(chapter_title, chapter_spec_text, cfg.pipeline_version)` (cell 05).
   - Phase B.4 recomputes `run_id` and will rebuild `run_ctx` paths if it detects a mismatch (useful when cells are run out of order after editing inputs).
6. **Materialize paths**: build `RunArtifacts(...)` pointing into `runs/<run_id>/…` (cell 05).
7. **Create skeleton + logger**: `run_ctx.create_artifact_skeleton(overwrite=False)` and `setup_run_logger(run_ctx)` (cell 05).
8. **Log + metrics**:
   - `log_event(..., stage="phase_a", event="run_initialized", run_id=…, run_dir=…)`
   - `stage_timer(..., "phase_a")` writes `metrics.json` `stages.phase_a.last_duration_s`

### 5) Caching & invalidation

- **`run_id` is the cache namespace**. If you change any of:
  - `pipeline_version`
  - `chapter_title`
  - `chapter_spec_text`

  …then **every downstream cached artifact moves** to a different `runs/<run_id>/` directory.

- `create_artifact_skeleton(overwrite=False)` is **idempotent**: it creates missing files but does not overwrite existing ones (except `metrics.json` only when missing).
- FORCE flags are not used in Phase A, but they control whether later phases reuse Phase B/C/D cached artifacts.

### 6) QC / Metrics / Logs

**Notebook QC/prints**

- Phase A.0 prints:
  - which `.env` files were loaded
  - package versions (`openai`, `pydantic`, `python-dotenv`)
  - QC table for env var presence (presence only; no secrets printed)
- Phase A.2 prints:
  - “At a glance” config summary (budget, prune values, embedding model)
  - QC for artifact skeleton presence
  - A warning if `embeddings_vectors/` file count is huge (suggests prior cached runs)

**`metrics.json` contract**

- Top-level shape: `{run_id, created_at_utc, stages:{...}, updated_at_utc}`
- `stage_timer(run_ctx, "<stage_key>")` sets:
  - `metrics["stages"][stage_key]["last_duration_s"] = …`
- Phase A writes:
  - `stages.phase_a.initialized_at_utc`
  - `stages.phase_a.last_duration_s`

**`logs.jsonl` contract**

- `log_event` appends records like:
  - `{ts, stage, event, ...fields}`
- “Chatty” events (HTTP requests + cache hits/writes) are logged at `DEBUG` to keep console readable; full detail is still in `logs.jsonl`.

### 7) Tuning knobs

Phase A is where knobs are **defined** (in `PipelineConfig`) and **wired** (from env + notebook overrides). High-impact knobs include:

- Identity: `pipeline_version`, `runs_root` (affects run_id + artifact locations).
- LLM (planner/builders): `openai_model_planner`, `openai_reasoning_effort`, `openai_timeout_s`, `openai_max_output_tokens_planner`.
- Provider throttles: `openalex_rps`, `semanticscholar_rps`, `*_timeout_s`.
- Hard cap: `max_queries_per_provider` (Phase C).
- Pruning: `prune_n1`, `prune_n1_without_abstract` (Phase F).
- Embeddings: `embedding_model`, `embedding_batch_size` (Phase F; affects cache paths + storage growth).
- Rerank: `rerank_top_k_pre`, `rerank_concurrency` (Phase I; affects cost/latency).
- Scoring thresholds: `scoring_t`, `scoring_t_noabs` (Phases F/G/H/I).
- Authority buckets: `authority_classic_year_max`, `authority_recent_year_window`, `authority_bucket_quotas` (Phase K).

### 8) Downstream impact (change propagation)

- If you change **`compute_run_id` / `stable_hash`**, every phase’s artifacts move to new directories; this is the “nuclear invalidation” knob.
- If you change **`runs_root` or any artifact filenames in `RunArtifacts`**, downstream phases will fail to find expected files (Phase B/C/D/E/F/G/H/I/K all read these exact paths).
- If you change **env loading precedence**, you can silently switch API keys or base directories; this affects Phases B/C/I (OpenAI) and D/F (providers).
- If you change **`log_event` record shape** or stop writing `cache_hit/cache_write`, Phase K’s `run_costs.cache_status` inference (from `logs.jsonl`) becomes unreliable.
- If you change **`stage_timer` behavior** or stage keys, `metrics.json` rollups and the “Example run summary” style debugging becomes harder; Phase K also reads metrics for `run_costs`.
- If you change **`PRUNE_N1_NO_ABS` override wiring**, you directly change Phase F’s metadata-only shortlist size, which changes:
  - Phase F compute cost (Stage2 workload depends on pruned with-abstract union)
  - Phase G/H/I/K candidate universe carried forward (shortlists determine `scores_final.jsonl` content)

### 9) Example from run `4af2666…`

- First `logs.jsonl` record (redacted to relative paths):
  - `{"ts":"2026-02-15T15:41:38+00:00","stage":"phase_a","event":"run_initialized","run_id":"4af2666be828e5054ccf4d31","run_dir":"runs/<run_id>"}`
- `metrics.json` initializes with `stages:{}` and later contains:
  - `stages.phase_a.initialized_at_utc = "2026-02-15T15:41:38+00:00"`
  - `stages.phase_a.last_duration_s = 0.044`

### 10) Blueprint alignment

Blueprint intent (Phase A in `TWO_LANE_PIPELINE_IMPLEMENTATION_PLAN_FROM_REPORT.md`):

- One consistent `PipelineConfig`
- Standardized run artifact paths under `runs/{run_id}/…`
- Structured logging + per-stage metrics

Notebook status:

- Implemented: `PipelineConfig` covers provider URLs/keys, rate limits, query cap, embedding model/batch size, pruning sizes, rerank knobs, scoring weights/thresholds, and authority constants.
- Implemented: artifact skeleton creation + idempotent run logger + `metrics.json` stage timing.
- Delta: `embeddings_manifest.csv` exists but remains empty in the current notebook; the manifest used in practice is `embeddings_manifest.jsonl`.

---

## Phase B — LLM Query Planner (facets + anchors; strict hygiene)

**Prev:** Phase A (Run setup) → **Next:** Phase C (Provider query builders)

### 1) Goal

Turn the chapter description into a strict, reusable `QueryPlan` that drives the entire rest of the pipeline:

- **8–20 atomic facets** (bilingual, weighted)
- **primary context anchors** (bilingual; keep queries on-topic)
- global canonical terms and exclusions

Phase B is where you win/lose the pipeline: facet quality determines provider query quality (Phase C), pruning behavior (Phase F), coverage tags (Phase H), and rerank evidence usefulness (Phase I).

### 2) Inputs

**Config knobs used**

- `cfg.openai_api_key` (required)
- `cfg.openai_model_planner` (default `gpt-5-mini`; used for planner and Phase C builders)
- `cfg.openai_reasoning_effort` (default `high`)
- `cfg.openai_timeout_s` (default `43200` seconds)
- `cfg.openai_max_output_tokens_planner` (default `100000`)
- User flag: `FORCE_REBUILD_QUERY_PLAN` (ignore `query_plan.json` cache)

**Required artifacts**

- `runs/<run_id>/` exists and `run_ctx` is initialized (Phase A).
- Optional cache input: `runs/<run_id>/query_plan.json` (used when present and not forced).

### 3) Outputs

**Artifacts created/rewritten**

- `runs/<run_id>/query_plan.json` (cache; validated strict JSON)
- Stable debug (last successful call):
  - `runs/<run_id>/query_plan.raw_output.json`
  - `runs/<run_id>/query_plan.openai_meta.json`
- Attempts (per retry):
  - `runs/<run_id>/query_plan_attempt<N>.*`

**Debug/error markers**

- `runs/<run_id>/query_plan.cache_invalid.json` (written if cached `query_plan.json` fails validation)
- `runs/<run_id>/query_plan_attempt<N>.error.json` (written if the OpenAI call throws)

### 4) Processing (How it works)

Key code locations to edit:

- Models: `BilingualTerms`, `Facet`, `QueryPlan`, `ChapterInput` (cell 06)
- OpenAI helper: `openai_json_schema_call` (cell 07)
- Planner: `QUERY_PLAN_JSON_SCHEMA`, `planner_user_prompt`, `diagnose_query_plan`, `plan_queries_llm` (cell 08)

Step-by-step mechanics:

1. **Build `ChapterInput`** (cell 09) and recompute `run_id`.
   - If `chapter_title/spec/pipeline_version` changed since Phase A, Phase B.4 rebuilds `run_ctx` paths to the new `runs/<run_id>/…` before continuing.
2. **Cache read** (`plan_queries_llm`):
   - If `query_plan.json` exists and `FORCE_REBUILD_QUERY_PLAN=False`, load it and validate with `QueryPlan.model_validate`.
   - If it fails validation, write `query_plan.cache_invalid.json`, log `cache_invalid`, and fall back to regeneration.
3. **Strict JSON-schema call**:
   - Uses OpenAI Responses API with `text.format = {type: json_schema, strict: true}`.
   - Runs `background=True` and polls `responses.retrieve` until terminal status (avoids long HTTP read timeouts).
4. **Deterministic hygiene linting** (`diagnose_query_plan`):
   - Facet count must be 8–20.
   - `facet_id` must be unique; weights must be 1–5.
   - `primary_context_anchors.{en,de}` must be 3–8 items each and “hygienic”:
     - no `e.g.` / `z. B.` / parentheses / commas / semicolons
     - max word count (anchors use `max_words=6`)
     - must not contain generic research words (e.g., “system”, “model”, “framework”, …) as standalone anchors.
   - Canonical term lists must be hygienic (`max_words=4`).
   - Exclusions must be atomic (`<=3` words, no punctuation beyond hyphen).
   - Rough overlap warning: identical canonical term sets across facets.
5. **Retry loop (max 3 attempts)**:
   - On lint failure, the next attempt appends a `LINT_FEEDBACK` block to the user prompt with the error summary.
   - Each attempt writes `query_plan_attempt<N>.*` plus a `lint_failed` event in `logs.jsonl`.
6. **Cache write + metrics**:
   - Write validated plan to `query_plan.json`.
   - Write `metrics.json` under stage `phase_b_query_planner` with full OpenAI meta (usage + local cost estimate).

Key invariants established here:

- Facets are bilingual and ordered; later phases treat facet index order as canonical.
- Anchors are treated as “context-only”; later query builders enforce anchor presence.
- Exclusions are atomic; later builders will drop non-atomic exclusions.

### 5) Caching & invalidation

- Cache hit criteria:
  - `runs/<run_id>/query_plan.json` exists
  - `FORCE_REBUILD_QUERY_PLAN=False`
  - file validates against strict Pydantic `QueryPlan`
  - and is not a placeholder object (`{"_meta":{"placeholder":true}}`)
- Regeneration triggers:
  - `FORCE_REBUILD_QUERY_PLAN=True`
  - cache file missing
  - cache invalid (schema drift / corrupted JSON / hygiene lint tightened)
  - run_id changed (new run directory)

Downstream rerun rule of thumb:

- If you change anything about planner prompts/schema/lints, **rerun Phase B → K** (because facets/anchors flow everywhere).

### 6) QC / Metrics / Logs

**Notebook QC/prints (Phase B.4, cell 09)**

- Facet table: id, type, weight, term counts + term previews.
- QC checks:
  - facet count bounds (8–20)
  - anchors present (EN+DE)
  - missing canonical terms ratio
  - duplicate facet ids
  - weight variety
  - global exclusions present
  - diagnostics issues count
- Prints topic summaries (EN/DE).
- Prints OpenAI usage + estimated cost (or “cache hit — no new tokens billed”).

**`metrics.json`**

- Stage key: `phase_b_query_planner`
- Fields:
  - `last_duration_s`
  - `openai` meta blob (model_used, response_id, usage, cost_estimate, latency, status)

**`logs.jsonl`**

Typical events for this phase:

- `cache_hit` / `cache_write` (when loading/writing `query_plan.json`)
- `cache_invalid` (when cached file fails validation)
- `lint_failed` (when hygiene checks fail; includes attempt and raw_path)
- `openai_error` (exceptions; includes attempt)

### 7) Tuning knobs

The planner is tuned by a mix of **prompt quality** and **deterministic lint strictness**.

High-leverage knobs:

- `chapter_spec_text` specificity: too short/too broad reduces facet quality.
- Facet count bounds (hard-coded in diagnostics: 8–20).
- Anchor hygiene:
  - If anchors become too strict, you’ll see repeated lint failures and forced regeneration costs.
  - If anchors become too loose, Phase C/D retrieval drifts and Phase F pruning has to compensate.
- Exclusion atomicity: more exclusions can reduce drift but can also suppress recall if overdone.
- Model choice + reasoning effort: affects compliance with strict schema and lints (cost vs reliability trade-off).

### 8) Downstream impact (change propagation)

- If you change **facet order**, every downstream `facet_scores[*]` array changes meaning (Phases F/G/H/I/K). This is the most dangerous silent break.
- If you change **facet_ids** (renames), coverage tags and rerank `covered_facets` change; any tooling that keys by `facet_id` must be updated.
- If you weaken **anchor hygiene**, Phase C queries can lose “context-only” separation and retrieval drift increases (Phase D cost ↑, Phase E noise ↑).
- If you strengthen **anchor hygiene too far**, Phase B may fail to produce a plan; if it does produce one, Phase C validators will reject provider queries that “miss anchors”.
- Primary context anchors are also reused in Phase F pruning (notably the `authority/without_abstract` relevance gate), so changing anchors can change which metadata-only authority candidates survive even if your provider queries barely change.
- If you change **importance weights**, it affects:
  - match aggregation (Phase F/G)
  - which facets count as “required” (weight>=4) in QC + rerank prompts (Phases F/G/I)
  - coverage-tag frequency stats (Phase H)
- If you change **global exclusions**, it affects Phase C negative terms and therefore provider recall vs noise.

### 9) Example from run `4af2666…`

- This run needed **2 planner attempts** due to deterministic hygiene rejection:
  - `logs.jsonl` shows a `lint_failed` event for attempt 1 because anchors contained generic terms (`System 1`, `System 2`).
- Resulting plan characteristics:
  - `query_plan.json` facets: `16`
  - anchors: `8` EN + `8` DE
  - global exclusions: `8` EN + `8` DE
- OpenAI usage/cost (from `metrics.json`):
  - `input_tokens=1,376`, `output_tokens=27,461`, estimated cost `$0.0553`

### 10) Blueprint alignment

Blueprint intent (Phase B):

- 8–20 bilingual **atomic** facets
- strict structured output (json_schema)
- cache `query_plan.json`

Notebook status:

- Implemented: strict Pydantic + strict JSON schema + deterministic hygiene lints + retries.
- Implemented: caching via `query_plan.json` with explicit `FORCE_REBUILD_QUERY_PLAN`.
- Delta: blueprint calls for `temperature=0`; the notebook does not pass an explicit temperature parameter and relies on strict schema + reasoning model behavior for determinism.

---

## Phase C — LLM provider query builders (OpenAlex + S2; ≤50/provider)

**Prev:** Phase B (QueryPlan) → **Next:** Phase D (Retrieval + caches)

### 1) Goal

Transform the `QueryPlan` into two provider-specific query lists:

- OpenAlex `/works` query objects (filters + sort + per-page)
- Semantic Scholar bulk search query strings (advanced syntax)

These queries are _candidate generators_: downstream phases deduplicate, embed, prune, and rerank — so Phase C must balance:

- **anchored breadth** (recall) vs **drift control** (precision)
- bilingual coverage (EN+DE)
- query budget (≤50/provider)

### 2) Inputs

**Config knobs used**

- `cfg.max_queries_per_provider` (default `50`; hard cap; Phase C trims and logs `budget_trim`)
- `cfg.openai_api_key` (required)
- `cfg.openai_model_planner` (default `gpt-5-mini`)
- `cfg.openai_reasoning_effort` (default `high`)
- `cfg.openai_timeout_s` (default `43200` seconds)
- User flag: `FORCE_REBUILD_PROVIDER_QUERIES` (ignore cached query JSONs)

**Required artifacts**

- `runs/<run_id>/query_plan.json` (Phase B output)
- Optional cache inputs:
  - `runs/<run_id>/openalex_queries.json`
  - `runs/<run_id>/semanticscholar_queries.json`

### 3) Outputs

**Artifacts created/rewritten**

- `runs/<run_id>/openalex_queries.json` (cache output; strict list of `OpenAlexQuery`)
- `runs/<run_id>/semanticscholar_queries.json` (cache output; strict list of `S2BulkQuery`)

**Stable debug (last successful call)**

- OpenAlex builder:
  - `runs/<run_id>/openalex_queries.raw_output.json`
  - `runs/<run_id>/openalex_queries.openai_meta.json`
- S2 builder:
  - `runs/<run_id>/s2_bulk_queries.raw_output.json`
  - `runs/<run_id>/s2_bulk_queries.openai_meta.json`

**Attempts / debug bundles**

- `runs/<run_id>/openalex_queries_attempt<N>.*`
- `runs/<run_id>/s2_bulk_queries_attempt<N>.*`

**Debug/error markers**

- `runs/<run_id>/openalex_queries.cache_invalid.json`
- `runs/<run_id>/s2_bulk_queries.cache_invalid.json`

### 4) Processing (How it works)

Key code locations to edit:

- Provider query models + schemas + templates + validators:
  - `OpenAlexQuery`, `S2BulkQuery`
  - `OPENALEX_QUERY_BUILDER_*`, `S2_BULK_QUERY_BUILDER_*`
  - `_normalize_openalex_query`, `_normalize_s2_query`
  - `_validate_*` helpers
  - `build_openalex_queries_llm`, `build_s2_bulk_queries_llm`
  - (all in cell 10)
- QC dashboards: Phase C.4 runner (cell 11)

Mechanics overview:

1. **Sanitize plan for builders**:
   - `_sanitize_plan_for_query_builders(plan)` drops non-atomic exclusions from the plan before embedding into prompts.
   - This is a deliberate safety valve: Phase B is allowed to over-generate exclusions; Phase C keeps only atomic ones.
2. **Cache load (if not forced)**:
   - Reads cached JSON, validates each item via Pydantic, then normalizes deterministically.
   - Trims to `max_queries_per_provider` if needed and re-writes the cache in normalized form.
3. **LLM call (strict JSON schema)**:
   - Uses `openai_json_schema_call(...)` (same helper as Phase B) and writes attempt debug bundles.
4. **Deterministic normalization + validation** (this is where most “silent drift” is prevented):
   - **OpenAlex** (`_normalize_openalex_query`):
     - Forbids `* ? ~` in `query_string` (treats as invalid upstream).
     - Rewrites slash tokens `X/Y` to OR-groups (outside URLs/DOIs).
     - Uppercases boolean ops outside quotes; collapses whitespace.
     - Lints `NOT ...` clauses so negatives stay atomic.
     - Canonicalizes `filters`:
       - enforces `is_paratext:false,is_retracted:false,language:<lang>` prefix
       - rejects unknown filter keys
     - Sets policy defaults:
       - `per_page=200` (hard)
       - `match` forces `search_field="title_and_abstract.search"`
       - `authority` forces `sort="cited_by_count:desc"`
   - **S2** (`_normalize_s2_query`):
     - Validates advanced operators and negative-term atomicity.
     - Enforces: match queries have `>=2` required components (`+...`).
     - Enforces: every `|` is inside parentheses.
     - Forbids `?` in `query_string` (S2-specific).
5. **Coverage checks**:
   - Both providers must include both languages (`en`,`de`) and both intents (`authority`,`match`).
   - Anchor presence: every query must contain at least one primary anchor term (per language).
   - OpenAlex match “anchor fingerprint diversity”: prevents too many match queries sharing the same anchor fingerprint (anti-dominance drift control).
6. **Write cache + metrics**:
   - Writes `openalex_queries.json` / `semanticscholar_queries.json`.
   - Updates `metrics.json` stages:
     - `phase_c_openalex_query_builder`
     - `phase_c_s2_query_builder`

Key invariants established here:

- Provider query lists are bilingual and contain both intents.
- OpenAlex query strings contain only the subset of boolean syntax the pipeline expects.
- Filters are canonicalized so Phase D retrieval behavior is predictable.

### 5) Caching & invalidation

- Cache hit criteria (per provider):
  - cached file exists
  - `FORCE_REBUILD_PROVIDER_QUERIES=False`
  - cached JSON validates and passes deterministic normalization/validation
- Cache invalidation triggers:
  - force flag set
  - schema drift / stricter validators
  - planner changed facets/anchors (Phase B), requiring different queries

Important interaction with Phase D:

- Phase D caches are keyed by a stable hash of the **provider query object**.
- If Phase C changes query objects, Phase D will naturally create new cache files (old caches remain on disk but are unused).
- If Phase D retrieval logic changes but Phase C query objects stay the same, Phase D will reuse existing cache files unless you set `FORCE_REBUILD_RETRIEVAL=True` (Phase D does not schema-validate caches).

### 6) QC / Metrics / Logs

**Notebook QC/prints (Phase C.4, cell 11)**

- Budget checks: query count ≤ `max_queries_per_provider` for each provider.
- Language + intent coverage checks (must include `en,de` and `authority,match`).
- Duplicate query ratio and duplicate query listings (warn/fail thresholds come from Phase A constants).
- Anchor coverage stats for match queries.
- OpenAlex forbidden-character scan (`* ? ~`).
- Previews of the first `TOP_N_PREVIEW` queries per provider.
- Optional plots: query length histogram and query-count bar charts.

**`metrics.json`**

- Stage keys:
  - `phase_c_openalex_query_builder`
  - `phase_c_s2_query_builder`
- Fields:
  - `last_duration_s`
  - `openai` meta blob (usage + local cost estimate)
  - `query_count`

**`logs.jsonl`**

- Events: `cache_hit`, `cache_write`, `cache_invalid`, `budget_trim`, `lint_failed`, `openai_call_failed`.

### 7) Tuning knobs

- `max_queries_per_provider` (main recall/latency lever; affects Phase D runtime and cache size).
- Query templates (provider prompts): anchored breadth vs drift.
- Deterministic validators:
  - OpenAlex filter allowlist (if you allow more filter keys, you widen the search surface).
  - Anchor fingerprint diversity threshold (default max share `0.60`).
  - S2 advanced-op guardrails (quotes, parentheses, match structure).
- Provider policy defaults:
  - OpenAlex `authority` sort = cited-by-count.
  - Match queries use title+abstract search field.

### 8) Downstream impact (change propagation)

- If you increase **query breadth** (more queries or broader strings), Phase D returns more records → Phase E candidates grow → Phase F embedding cost and runtime grow.
- If you weaken **anchor enforcement**, Phase D drift increases and Phase E has to filter more noise (paratext/type filters won’t save you from off-topic domains).
- If you change OpenAlex **filters** (e.g., date/type/core-venue), you directly change the candidate universe and therefore authority percentile normalization (Phases F/G).
- If you change S2 **match structure** constraints, you change which candidates are eligible for Stage2 (Phase F) and how much evidence Phase H can produce.
- If Phase C emits fewer `without_abstract` candidates (by tightening queries), Phase F’s `PRUNE_N1_NO_ABS` becomes less relevant; if it emits many, `PRUNE_N1_NO_ABS` becomes a major cost/quality control.

### 9) Example from run `4af2666…`

- Query counts (from `metrics.json`): OpenAlex `42`, S2 `35`.
- Example OpenAlex query object (from `openalex_queries.json`):
  - intent=`authority`, lang=`en`, `filters="is_paratext:false,is_retracted:false,language:en"`, sort=`cited_by_count:desc`
- Example S2 match query string (from `semanticscholar_queries.json`):
  - begins `+(...) +(...)` (two required groups), bilingual anchors present.
- Downstream effect in this run:
  - Phase D fetched OpenAlex `11,139` and S2 `19,618` raw records.

### 10) Blueprint alignment

Blueprint intent (Phase C):

- Provider-safe query objects, deterministic budgeting, strict caps, caching.

Notebook status:

- Implemented: strict schemas + deterministic normalization/validation + caching per provider.
- Implemented: OpenAlex forbids `* ? ~`; S2 enforces `|`-in-parentheses and match queries with `>=2` `+` components.
- Delta: budgeting logic differs from the blueprint’s proposed C1 allocation (neighbor/method queries); the notebook uses a simpler deterministic scheme (always authority EN/DE + bilingual fallback, global match EN/DE, and facet-targeted queries primarily for weight>=4 facets).

---

## Phase D — Retrieval orchestrator (providers + per-query caches)

**Prev:** Phase C (provider queries) → **Next:** Phase E (normalize + dedup)

### 1) Goal

Execute provider queries reliably and reproducibly:

- enforce rate limits
- retry transient failures
- cache per-query results
- rebuild aggregate raw JSONLs deterministically

Phase D is primarily an **I/O + caching** phase. Its output volume (records fetched) controls Phase E candidate counts and, indirectly, Phase F cost.

### 2) Inputs

**Config knobs used**

- OpenAlex:
  - `cfg.openalex_base_url` (default `https://api.openalex.org`)
  - `cfg.openalex_api_key` (optional but recommended; QC expects set)
  - `cfg.openalex_email` (optional; sent as `mailto`)
  - `cfg.openalex_timeout_s` (default `60`)
  - `cfg.openalex_rps` (default `10`)
- Semantic Scholar:
  - `cfg.semanticscholar_base_url` (default `https://api.semanticscholar.org/graph/v1`)
  - `cfg.semanticscholar_api_key` (optional; QC expects set)
  - `cfg.semanticscholar_timeout_s` (default `60`)
  - `cfg.semanticscholar_rps` (default `1`)
- User flag: `FORCE_REBUILD_RETRIEVAL` (ignore per-query cache files and refetch)

**Required artifacts**

- `runs/<run_id>/openalex_queries.json` (Phase C)
- `runs/<run_id>/semanticscholar_queries.json` (Phase C)
- Cache directories (created if missing):
  - `runs/<run_id>/cache/openalex/`
  - `runs/<run_id>/cache/semanticscholar/`

### 3) Outputs

**Artifacts created/rewritten**

- Per-query caches:
  - `runs/<run_id>/cache/openalex/<query_hash>.jsonl`
  - `runs/<run_id>/cache/semanticscholar/<query_hash>.jsonl`
- Aggregates rebuilt from used caches (always rewritten):
  - `runs/<run_id>/openalex_raw.jsonl`
  - `runs/<run_id>/semanticscholar_raw.jsonl`

**Debug/attempt files**

- If a query fails mid-write, the temp file is preserved as:
  - `runs/<run_id>/cache/<provider>/<query_hash>.jsonl.failed.<timestamp>`

### 4) Processing (How it works)

Key code locations to edit (cell 12, `6d0e1c3e`):

- `RateLimiter`
- `request_json` (common HTTP layer + retries + structured logging)
- `_query_hash` (stable cache key)
- `fetch_openalex_to_cache`
- `fetch_s2_to_cache`
- `rebuild_aggregate_jsonl`

Step-by-step mechanics:

1. **Compute stable query hashes**:
   - `_query_hash(provider, q)` hashes `json.dumps(q.model_dump(sort_keys=True))`.
   - This makes cache filenames stable across runs as long as query objects are identical.
2. **Per-query cache policy**:
   - If `cache_path` exists and `FORCE_REBUILD_RETRIEVAL=False`, log `cache_hit` and skip fetching that query.
   - Otherwise, fetch into `*.tmp` then rename to `*.jsonl` (atomic write).
3. **OpenAlex retrieval** (`fetch_openalex_to_cache`):
   - Endpoint: `GET {openalex_base_url}/works`
   - Cursor pagination: start `cursor="*"` and follow `meta.next_cursor`.
   - `per-page=200`, `select=` minimal fields.
   - Writes JSONL rows tagged with provenance:
     - `{run_id, provider="openalex", query_hash, query_i, intent, language, rank, work:{...}}`
4. **S2 retrieval** (`fetch_s2_to_cache`):
   - Bulk search: `GET {s2_base_url}/paper/search/bulk` with `fields="paperId"` and `limit=100`.
   - Token pagination: follow `token` (or `next`) until exhausted.
   - Hydration: for each page, hydrate paper ids via `POST {s2_base_url}/paper/batch` in chunks of ≤500.
   - Writes JSONL rows:
     - `{run_id, provider="semanticscholar", query_hash, query_i, intent, language, rank, paper:{...}}`
5. **Retries/backoff + rate limiting** (`request_json` + `RateLimiter`):
   - Retries 429 and 5xx with exponential backoff + jitter (up to max wait).
   - Logs an `http_request` event for every attempt with:
     - provider, endpoint, status, retries, elapsed_s, and params (API keys redacted)
6. **Aggregate rebuild**:
   - After fetching, Phase D rebuilds:
     - `openalex_raw.jsonl` by concatenating the “used cache paths” in query order.
     - `semanticscholar_raw.jsonl` similarly.
   - Logs `aggregate_rebuilt`.

Key invariants enforced here:

- All provider records are tagged with provenance fields needed by Phase E.
- Aggregate raw JSONLs are deterministic functions of the set/order of used cache files.

### 5) Caching & invalidation

Cache hit vs rebuild:

- Per-query cache hit if `cache/<provider>/<query_hash>.jsonl` exists and `FORCE_REBUILD_RETRIEVAL=False`.
- Aggregate raw JSONLs are always rebuilt from the used cache paths (even if every query was a cache hit).

Force flags:

- `FORCE_REBUILD_RETRIEVAL=True` forces refetch for every query (overwriting cache files).

Critical gotcha:

- If you change **retrieval code** (fields selected, ranking params, bulk_limit, etc.), existing cache files may become “schema-stale” but Phase D won’t notice. In that case you must force rebuild or delete caches.

### 6) QC / Metrics / Logs

**Notebook QC/prints**

- Phase D prints per-provider query counts, then tables of per-query cache status (`hit` vs `write`) and record counts.

**`metrics.json`**

- Stage key: `phase_d_retrieval`
- Fields:
  - `last_duration_s`
  - `openalex.{cache_hits,cache_writes,query_failed,records}`
  - `semanticscholar.{cache_hits,cache_writes,query_failed,records}`

**`logs.jsonl`**

- High-volume events:
  - `http_request` (every request attempt; includes endpoint + status + retries)
  - `cache_hit` / `cache_write` per query cache file
  - `query_failed` per failing query hash (tmp preserved)
  - `aggregate_rebuilt` after raw JSONL rebuild

### 7) Tuning knobs

- Provider RPS:
  - `openalex_rps` (higher = faster but risk of throttling)
  - `semanticscholar_rps` (typically the dominant runtime limiter)
- Timeouts: `openalex_timeout_s`, `semanticscholar_timeout_s`
- Retrieval field sets (hard-coded constants):
  - OpenAlex `select=` list
  - S2 batch `fields=` list

### 8) Downstream impact (change propagation)

- If you change **query objects** (Phase C), Phase D’s per-query cache keys change → you fetch a different record universe → everything downstream changes (E→K).
- If you change **rate limits/timeouts**, Phase D runtime changes but outputs should remain equivalent (unless provider throttling changes effective pagination completeness).
- If you change **selected fields** (especially abstract/ids/citations), Phase E normalization/dedup changes, authority scoring changes (F/G), and output fields change (K).
- If Phase D returns more records, Phase E merges increase and Phase F embedding cost increases (metadata embeddings scale with candidate count).

### 9) Example from run `4af2666…`

- OpenAlex:
  - queries: `42`
  - cache: `42` writes, `0` hits
  - records: `11,139`
- Semantic Scholar:
  - queries: `35`
  - cache: `35` writes, `0` hits
  - records: `19,618`
- Aggregate outputs written:
  - `openalex_raw.jsonl` `72.70 MB`
  - `semanticscholar_raw.jsonl` `44.12 MB`

### 10) Blueprint alignment

Blueprint intent (Phase D):

- provider clients with pagination, throttling, retries
- per-query cache keyed by query hash
- structured request logging

Notebook status:

- Implemented: OpenAlex cursor pagination + S2 bulk token pagination + batch hydration.
- Implemented: retry/backoff + per-provider rate limiting + structured `http_request` logs.
- Implemented: per-query caches + aggregate rebuild of raw JSONLs.

---

## Phase E — Normalize, deduplicate, and pool split

**Prev:** Phase D (raw provider JSONLs) → **Next:** Phase F (embeddings + scoring)

### 1) Goal

Convert provider-specific raw records into a single canonical `Candidate` universe that is:

- cross-provider deduplicated
- provenance-preserving (so later phases can reason about lane eligibility)
- split into strict pools (`with_abstract` vs `without_abstract`)

Phase E is the “schema bridge” between retrieval (Phase D) and scoring (Phase F).

### 2) Inputs

**Config knobs used**

- Indirectly tied to upstream: Phase E rebuild behavior is controlled by `FORCE_REBUILD_RETRIEVAL` (there is no separate “force candidates rebuild” flag).

**Required artifacts**

- `runs/<run_id>/openalex_raw.jsonl` (Phase D)
- `runs/<run_id>/semanticscholar_raw.jsonl` (Phase D)
- Output targets:
  - `runs/<run_id>/candidates_normalized.jsonl`
  - `runs/<run_id>/candidates_normalized.csv`

### 3) Outputs

**Artifacts created/rewritten**

- `runs/<run_id>/candidates_normalized.jsonl` (canonical `Candidate` JSONL)
- `runs/<run_id>/candidates_normalized.csv` (human-friendly view)

**What a `Candidate` contains (high level)**

- Canonical identity: `id` (+ `doi` + `external_ids`)
- Metadata: title, authors, year, venue, url, abstract, language(s)
- Provenance:
  - `provider_ids` (all provider record ids merged)
  - `sources[]`: per-hit provenance (`provider`, `query_hash`, `query_i`, `intent`, `language`, `rank`)
  - `intents[]`: union of intents observed across sources (drives lane eligibility downstream)
- Signals: `citations`, `influential_citations`
- Pool: `pool ∈ {"with_abstract","without_abstract"}`

### 4) Processing (How it works)

Key code locations to edit (cell 14, `d8aacd00`):

- `CandidateSource`, `Candidate`
- `reconstruct_abstract_from_inverted_index` (OpenAlex)
- `normalize_openalex_record`, `normalize_s2_record`
- Dedup keys:
  - `_key_candidates` (dedup index keys used during merge)
  - `_final_candidate_id` (final canonical id policy)
- Merge policy: `merge_partials`
- Orchestrator: `build_candidates_from_raw`

Step-by-step mechanics:

1. **Cache reuse (fast path)**:
   - If `candidates_normalized.jsonl` has data and `force_rebuild=False`, Phase E loads it and reuses it.
   - Safety: if the cached file contains duplicate candidate ids, Phase E ignores it and rebuilds.
2. **Stream normalization**:
   - OpenAlex rows: read each JSONL line, extract `work`, filter paratext titles and unwanted OpenAlex types, reconstruct abstract, map to a provider-neutral partial candidate dict.
   - S2 rows: read `paper`, filter paratext titles, map to partial candidate dict.
3. **Cross-provider dedup + merge**:
   - Build a dedup index over keys (in priority order):
     1. DOI
     2. arXiv id
     3. PMID
     4. PMCID
     5. fallback `(normalized_title, year, first_author_lastname)`
   - If a new partial hits any indexed key, merge it into the existing candidate:
     - abstract: prefer non-empty; if both present, keep the longer
     - citations/influential: max
     - year: if conflict, pick min (older) to be conservative
     - provenance: union provider_ids + append unique sources + union intents + union languages
4. **Finalize pools + canonical ids**:
   - `pool = "with_abstract"` if abstract text is non-empty, else `"without_abstract"`.
   - Final `Candidate.id` policy:
     - prefer DOI
     - else `arxiv:<id>` / `pmid:<id>` / `pmcid:<id>`
     - else a hashed fallback from `(normalized_title|year|first_author_lastname)`
   - Collision handling: if the computed final id collides, fallback to `cand_<internal_cid>`.
5. **Deterministic output ordering**:
   - Sort candidates by `citations desc`, then `title casefold`, then `id`.
6. **Write outputs atomically**:
   - JSONL + CSV are written to `*.tmp` then renamed.
7. **Metrics + event log**:
   - Writes `metrics.json` stage `phase_e_candidates.counts` with normalized/dedup/merge counts.
   - Logs `cache_write` (`provider="candidates"`) with pool counts and merge stats.

Key invariants established here:

- Pools are disjoint and validated by assertions.
- `Candidate.intents` is the source of truth for lane eligibility used in Phase F pruning.

### 5) Caching & invalidation

- Cache hit criteria:
  - `candidates_normalized.jsonl` exists and has at least one non-empty line
  - `FORCE_REBUILD_RETRIEVAL=False` (Phase E uses this flag as its rebuild toggle)
  - cached ids are unique (no collisions)
- Rebuild triggers:
  - `FORCE_REBUILD_RETRIEVAL=True`
  - cached file missing/empty
  - cached file contains duplicate ids

Gotcha (important for tuning):

- If you change Phase E normalization/dedup logic, **you must delete** `candidates_normalized.jsonl` (and CSV) or set `FORCE_REBUILD_RETRIEVAL=True` to force a rebuild. Otherwise Phase E may silently reuse stale candidates.

### 6) QC / Metrics / Logs

**Notebook QC/prints**

- “At a glance” summary:
  - raw record counts, normalized_total, dedup ratio, merge ratio
  - pool sizes and `with_abstract` share
  - DOI share, year-missing share
  - filtered paratext/type counts
- Assertions:
  - pool split disjointness
  - no duplicate candidate ids

**`metrics.json`**

- Stage key: `phase_e_candidates`
- Fields:
  - `last_duration_s`
  - `counts`: cache*hit, raw*\*\_records, normalized_total, normalized_by_provider, deduped_candidates, merges, filtered counts, pool_counts, file paths

**`logs.jsonl`**

- Writes `cache_write` with provider `"candidates"` and summary fields (`records`, `merges`, pool counts).

### 7) Tuning knobs

Phase E is mostly deterministic. The primary “knobs” are actually **upstream**:

- Phase C query breadth and provider filters (controls how noisy the raw record pool is).
- Phase D selected fields (if you drop abstract/id fields, dedup quality degrades).

Within Phase E itself, tuning is code-level:

- Paratext/type filters (`is_paratext_title`, OpenAlex type blacklist).
- Dedup key ordering and fallback behavior.
- Merge precedence rules (abstract, year, citations).
- Canonical id policy (changing this has huge downstream cache impact).

### 8) Downstream impact (change propagation)

- If you change the **canonical id policy** (`Candidate.id`), you invalidate:
  - Phase F embedding caches keyed by text hashes but referenced per candidate
  - Phase I rerank caches (cache key includes candidate id)
  - any external tooling keyed by candidate id (output.json consumers)
- If you change **dedup keys** or merge precedence, you change:
  - which records survive and what metadata they carry
  - authority normalization percentiles (Phases F/G)
  - pool split ratio (affects Phase F Stage2 evidence capacity)
- If `Candidate.intents` becomes wrong or incomplete, Phase F lane isolation will prune away candidates from a lane (especially damaging for Authority lane).
- If `with_abstract` share is low, Phase F’s Stage2 becomes much less useful, and Phase H must rely more on fallback excerpts.

### 9) Example from run `4af2666…`

From `metrics.json` (`phase_e_candidates.counts`):

- raw records: OpenAlex `11,139`, S2 `19,618`
- normalized_total: `30,507`
- deduped_candidates: `25,524` (merges `4,886`)
- pools: `with_abstract=15,625`, `without_abstract=9,899`
- filtered: paratext titles `109`, OpenAlex types `140`

### 10) Blueprint alignment

Blueprint intent (Phase E):

- reconstruct OpenAlex abstract from `abstract_inverted_index`
- dedup precedence DOI > arXiv > PMID/PMCID > fallback
- merge precedence prefers abstract-bearing records
- strict pool split

Notebook status:

- Implemented: abstract reconstruction, dedup precedence, merge precedence, pool split assertions.
- Implemented: provenance (`sources[]`, `intents[]`) for later lane isolation and debugging.
- Delta: Phase E rebuild is coupled to `FORCE_REBUILD_RETRIEVAL` rather than having an explicit “FORCE_REBUILD_CANDIDATES” knob.

---

## Phase F — Embeddings + staged scoring (Stage1 → prune → Stage2)

**Prev:** Phase E (candidates) → **Next:** Phase G (exact recomputation + rankings)

### 1) Goal

Compute facet-aware relevance and authority scores cheaply but robustly:

- Stage 1: metadata-only embeddings for _all_ candidates
- Prune to keep costs bounded
- Stage 2: abstract chunk embeddings + late interaction for `with_abstract` shortlist only
- Optional: expand candidates via Semantic Scholar Recommendations (neighbor booster)

Phase F is where most compute cost lives (embeddings), and where “match vs authority” separation becomes real.

### 2) Inputs

**Config knobs used**

- Embeddings:
  - `cfg.embedding_model` (default `text-embedding-3-small`)
  - `cfg.embedding_batch_size` (default `256`)
- Scoring aggregation (used in Stage 1 and Stage 2 match):
  - `cfg.match_m` (default `3`)
  - `cfg.match_weight_best` (default `0.55`)
  - `cfg.match_weight_top_m` (default `0.25`)
  - `cfg.match_weight_cov` (default `0.20`)
  - `cfg.scoring_t` (default `0.30` for `with_abstract`)
  - `cfg.scoring_t_noabs` (default `0.35` for `without_abstract`)
- Pruning:
  - `cfg.prune_n1` (default `600` per lane for `with_abstract`)
  - `cfg.prune_n1_without_abstract` (default `300` per lane for `without_abstract`; overridden by user `PRUNE_N1_NO_ABS`)
- S2 Recommendations expansion:
  - `cfg.s2_neighbor_seed_count` (default `5`)
  - `cfg.s2_recs_limit_per_seed` (default `300`)
  - `cfg.semanticscholar_api_key`, `cfg.semanticscholar_rps`, `cfg.semanticscholar_timeout_s`

**Required artifacts**

- `runs/<run_id>/query_plan.json` (facets + anchors; Phase B)
- `runs/<run_id>/candidates_normalized.jsonl` (Phase E)
- Output targets (Phase F writes all of these):
  - `runs/<run_id>/facets_index.json`
  - `runs/<run_id>/scores_stage1.jsonl`
  - `runs/<run_id>/shortlists_stage1.json`
  - `runs/<run_id>/scores_stage2.jsonl`
  - `runs/<run_id>/embeddings_manifest.jsonl`
  - `runs/<run_id>/embeddings_vectors/<model>/*.f32`
  - optional: `runs/<run_id>/candidates_expanded.jsonl`, `runs/<run_id>/semanticscholar_recommendations.jsonl`

### 3) Outputs

**Artifacts created/rewritten**

- Facet index contract:
  - `runs/<run_id>/facets_index.json` (facet ids + labels + weights; canonical order)
- Stage 1:
  - `runs/<run_id>/scores_stage1.jsonl` (all candidates; includes `facet_scores_stage1[]`)
  - `runs/<run_id>/shortlists_stage1.json` (pruned ids per lane/pool)
- Optional expansion:
  - `runs/<run_id>/semanticscholar_recommendations.jsonl` (append-only provenance)
  - `runs/<run_id>/candidates_expanded.jsonl` (merged expanded pool)
- Stage 2:
  - `runs/<run_id>/scores_stage2.jsonl` (Stage2-scored ids only; includes `facet_scores_stage2[]` + `evidence_chunks[]`)
- Embedding caches/manifests:
  - `runs/<run_id>/embeddings_manifest.jsonl` (append-only)
  - `runs/<run_id>/embeddings_vectors/<model>/*.f32` (run-local cache)
  - plus shared global cache under `sources-v2/embeddings_cache_global/<model>/*.f32`

### 4) Processing (How it works)

Key code locations to edit (cell 15, `3837b017`):

- Embedding cache + IO:
  - `_text_hash`, `_vector_path`, `_global_vector_path`, `_link_or_copy`
  - `embed_texts_cached`
- Text views:
  - `facet_embed_text` (what gets embedded for facets)
  - `candidate_meta_view` (what gets embedded for candidate metadata)
  - `chunk_abstract` (Stage2 chunking)
- Scoring:
  - `compute_match` (best + top-m + cov)
  - `compute_authority_scores` (percentile citations/year + recency + bonuses)
- Expansion + pruning:
  - `_s2_recommendations_expand`
  - `_eligible` (lane isolation)
  - authority/no-abs gate: `NOABS_AUTH_MIN_MATCH`

Phase F sub-stages (roughly in notebook order):

**F1) Load inputs + write facet index**

- Loads `QueryPlan` and candidate JSONL.
- Writes `facets_index.json` with:
  - `facet_ids` (order matters)
  - `facets[]` rows (labels, weights, type)

**F2) Facet embeddings**

- Embeds `2 × #facets` texts (EN + DE) where:
  - `facet_embed_text(f, "en") = f.text_en + "Canonical terms: …"`
  - `facet_embed_text(f, "de") = f.text_de + "Kanonische Begriffe: …"`
- Uses `embed_texts_cached(..., kind="facet")`.

**F3) Metadata embeddings + Stage 1 scoring**

- Builds `meta_texts`:
  - `with_abstract`: a compact view (title/venue/year/authors)
  - `without_abstract`: `rich=True` adds DOI/external ids/language/url (to help metadata-only scoring)
- Embeds all candidates’ metadata via `embed_texts_cached(..., kind="meta")`.
- For each candidate:
  - per-facet score: `s_i = max(cos(facet_en[i], meta), cos(facet_de[i], meta))`
  - match aggregation via `compute_match(...)` with:
    - `t = cfg.scoring_t` (`with_abstract`) or `cfg.scoring_t_noabs` (`without_abstract`)
  - authority score via `compute_authority_scores`:
    - citations-per-year percentile within the run candidate set
    - recency logistic nudge
    - bonuses: +0.05 for review/survey terms in title; +0.03 if `venue_is_core=True`
  - lane fusion:
    - `match_lane = 0.80*match + 0.20*authority`
    - `authority_lane = 0.80*authority + 0.20*match`
- Writes `scores_stage1.jsonl`.

**F4) Semantic Scholar Recommendations expansion (optional)**

- Seed selection (default `seed_count=5`):
  - choose highest `match_lane` candidates
  - prefer `with_abstract`
  - require an existing S2 `paperId` in `candidate.provider_ids["semanticscholar"]`
- For each seed, call Recommendations API:
  - `POST https://api.semanticscholar.org/recommendations/v1/papers`
  - append `{seed_paperId, paperId, rank}` to `semanticscholar_recommendations.jsonl` (skips already-seen ids per seed)
- Hydrate new ids via S2 graph `POST /paper/batch` and merge into the candidate pool (dedup by DOI/arXiv/PMID/PMCID/fallback title-year-author).
- Persist expanded pool to `candidates_expanded.jsonl` (does not overwrite Phase E outputs).
- Embed only new candidates’ metadata (`kind="meta_recs"`) and append their Stage1 score rows.
- **Recompute authority percentiles across the expanded pool**, then update lane scores for all Stage1 rows.

**F5) Pruning after Stage 1 (lane/pool shortlists)**

- Build lane eligibility from Phase E provenance:
  - `_eligible(cid, lane) := lane in candidate.intents`
- For each lane × pool:
  - keep top `N1_WITH_ABS` (with-abstract) or `N1_NO_ABS` (no-abstract) by lane score
- Extra gate for `authority/without_abstract` to prevent off-topic “high-cite metadata-only” domination:
  - keep only if `match_stage1 >= 0.22` **or** a primary anchor appears in `title+venue+year`
- Writes `shortlists_stage1.json` and asserts no lane leaks. This shortlist is the contract Phase G uses to decide which ids even exist in `scores_final.jsonl`.

**F6) Stage 2 (with-abstract shortlist union only)**

- `stage2_ids = union(match.with_abstract shortlist, authority.with_abstract shortlist)`
- Chunk abstracts deterministically:
  - normalize whitespace, truncate to 6000 chars
  - sentence split, 250–400 char target, 1-sentence overlap
  - cap: 25 chunks per abstract
- Embed all chunks (`kind="chunk"`) and compute per-facet scores:
  - score per chunk = `max(cos(en_facet, chunk), cos(de_facet, chunk))`
  - aggregate facet score:
    - if ≥2 chunks: `0.5*(top1 + top2)` (not pure max)
    - else: top1
  - evidence excerpt = best-scoring chunk (trimmed to ≤240 chars), aligned by facet index
- Recompute match + lane scores for Stage2 candidates and refresh with-abstract shortlist orderings.
- Writes `scores_stage2.jsonl` (Stage2 candidates only).

### 5) Caching & invalidation

**Embedding cache (local + global)**

- Cache key is `(embedding_model, text_hash)` where `text_hash` is a stable hash of whitespace-normalized text.
- Hit order:
  1. run-local `runs/<run_id>/embeddings_vectors/<model>/<hash>.f32`
  2. global `sources-v2/embeddings_cache_global/<model>/<hash>.f32` (linked/copied into run-local on use)
- There is no FORCE flag for embeddings in the user inputs; Phase F always tries to reuse caches.

**Recommendations expansion cache**

- `semanticscholar_recommendations.jsonl` is append-only and used as a “seen set” per seed paper.
- If you want a clean expansion rerun for the same run_id, delete `semanticscholar_recommendations.jsonl` and `candidates_expanded.jsonl`.

**Pruning/scoring outputs**

- Stage1/Stage2 outputs are rewritten every run of the cell (no cache reuse).

Downstream rerun rule of thumb:

- If you change anything about facet embeddings, metadata view, pruning, or Stage2 aggregation, **rerun Phase F → K**.

### 6) QC / Metrics / Logs

**Notebook QC/prints**

- Prints Stage1 summary and prune table (`eligible`, `kept`, top/min scores) per lane/pool.
- Prints Stage2 summary (`stage2_candidates`, `chunks_embedded`, `stage2_scored`).
- Prints an artifacts list for quick navigation.
- Optional plots:
  - `match_lane` distributions by pool
  - match vs authority scatter
  - required facet coverage in match/with-abstract top20

**`metrics.json`**

- Sub-stage timers (durations):
  - `phase_f_facet_embeddings`
  - `phase_f_metadata_embeddings`
  - `phase_f_stage1_scoring`
  - `phase_f_s2_recommendations` (if enabled)
  - `phase_f_chunk_embeddings`
  - `phase_f_stage2_scoring`
- Rollups under `stages.phase_f` (counts + embedding stats; note: `phase_f.last_duration_s` may be `null`):
  - `counts.{candidates,facets,stage2_candidates,stage2_scored}`
  - `embeddings` stats per kind (`facet`, `meta`, optional `meta_recs`, `chunk`)
  - `embeddings_total.prompt_tokens` + `cost_usd_est`

**`logs.jsonl`**

- Embedding cache hits/writes are not logged via `log_event` (they’re recorded in `embeddings_manifest.jsonl` instead).
- Other Phase F events are limited; most diagnostics are printed/metrics-based.

### 7) Tuning knobs

High-impact tuning levers:

- `prune_n1` / `prune_n1_without_abstract`:
  - controls Stage2 candidate volume and therefore chunk embedding cost/runtime
  - also controls how many candidates even reach Phase G/H/I/K
- `s2_neighbor_seed_count`, `s2_recs_limit_per_seed`:
  - increases recall/diversity but also changes the authority percentile baseline (scores for existing candidates can shift)
- Match aggregation parameters (`t`, `m`, weights):
  - affects partial-match friendliness and ranking stability
- `NOABS_AUTH_MIN_MATCH` gate:
  - affects how aggressively metadata-only authority candidates are filtered for relevance
- `embedding_model`:
  - changes cache namespace and cost profile; affects both quality and storage growth

### 8) Downstream impact (change propagation)

- If you change **`Candidate.intents` semantics** (Phase E) or Phase F’s `_eligible`, you change lane isolation and therefore:
  - which ids enter `shortlists_stage1.json`
  - which ids get Stage2 evidence
  - which ids appear in `scores_final.jsonl` (Phase G contract)
- If you change **pruning** sizes, you directly change:
  - Stage2 workload (`chunks_embedded`)
  - Phase I rerank task list (top-K comes from rankings built over the pruned universe)
  - the “evidence quality” distribution in Phase H (more with-abstract = more real excerpts)
- If you enable/disable **S2 recommendations expansion**, you change:
  - candidate universe size
  - authority percentile normalization baseline (shifts authority scores globally)
  - which seeds/neighbor works appear downstream
- If you change **Stage2 aggregation** (avg top2 vs max), you change match scores and coverage tags quality (Phase H relies on evidence chunks).
- If you change **chunking**, you change both:
  - Stage2 scores (facet MaxSim surface)
  - evidence excerpts (what the reranker and coverage tags are grounded in)

### 9) Example from run `4af2666…`

- Candidate counts:
  - Phase E deduped: `25,524`
  - Phase F post-expansion pool: `26,922`
- Recommendations expansion:
  - `semanticscholar_recommendations.jsonl` contains `1,500` rows from `5` seeds (300/seed in this run).
- Stage2:
  - `stage2_scored = 1,133`
- Embeddings usage (from `metrics.json` `phase_f.embeddings_total`):
  - prompt tokens `2,403,508`
  - estimated cost `$0.0481`

### 10) Blueprint alignment

Blueprint intent (Phase F):

- embedding cache + staged pruning
- Stage2 late interaction (MaxSim) with evidence excerpts
- without-abstract handling expects many `insufficient_info=true` reranks
- S2 neighbor booster with optional seed id resolution

Notebook status:

- Implemented: local+global embedding cache, batching, staged pruning, Stage2 evidence excerpts.
- Implemented: S2 Recommendations expansion (requires existing S2 `paperId`; no DOI→paperId resolution step).
- Delta: Stage2 per-facet aggregation uses `0.5*(top1+top2)` rather than pure max.
- Delta: metadata view is simpler than blueprint’s suggested “fields/keywords/publication types” enrichment; it relies on title/venue/year/authors (+ rich IDs for no-abs).

---

## Phase G — Exact scoring formulas and lane fusion (scores_final + rankings_stageg)

**Prev:** Phase F (Stage1/Stage2 scores + shortlists) → **Next:** Phase H (coverage tags)

### 1) Goal

Recompute final, reproducible scores and rankings from Phase F artifacts:

- recompute `match` from per-facet scores (Stage2 where available, else Stage1)
- recompute `authority` from citations/year normalization across the run’s candidate set
- compute lane fusion scores (`match_lane`, `authority_lane`)
- write the compact downstream contract:
  - `scores_final.jsonl`
  - `rankings_stageg.json`

Phase G is the “single source of truth” for lane scores used by coverage tags, rerank selection, and final output.

### 2) Inputs

**Config knobs used**

- `cfg.match_m`, `cfg.match_weight_best`, `cfg.match_weight_top_m`, `cfg.match_weight_cov`
- `cfg.scoring_t` (`with_abstract` threshold)
- `cfg.scoring_t_noabs` (`without_abstract` threshold)

**Required artifacts**

- `runs/<run_id>/facets_index.json` (Phase F; facet order + weights)
- `runs/<run_id>/scores_stage1.jsonl` (Phase F)
- `runs/<run_id>/shortlists_stage1.json` (Phase F)
- Optional:
  - `runs/<run_id>/scores_stage2.jsonl` (Phase F; Stage2 subset)
  - `runs/<run_id>/candidates_expanded.jsonl` (Phase F; used as join file if present)
  - else: `runs/<run_id>/candidates_normalized.jsonl` (Phase E)

### 3) Outputs

**Artifacts created/rewritten**

- `runs/<run_id>/scores_final.jsonl`
- `runs/<run_id>/rankings_stageg.json`

### 4) Processing (How it works)

Key code locations to edit (cell 16, `a68590e2`):

- `compute_match_g1` (exact match aggregation)
- `compute_authority_scores_g2` (authority normalization)
- Main join logic building `scores_final_by_id`

Step-by-step mechanics:

1. **Load facet contract** (`facets_index.json`):
   - establishes `facet_ids[]` and `facet_weights[]` alignment.
2. **Choose candidate join file**:
   - if `candidates_expanded.jsonl` has data, use it; else use Phase E `candidates_normalized.jsonl`.
3. **Recompute authority baseline**:
   - compute `citations_per_year = citations / age_years`
   - compute percentile rank across the run candidate set (only positive values contribute)
   - recency logistic nudge + review/core-venue bonuses
   - note: missing year uses `age_years=10` in the notebook implementation
4. **Load Stage1/Stage2**:
   - `scores_stage1.jsonl` provides `facet_scores_stage1[]` + Stage1 match parts
   - `scores_stage2.jsonl` provides `facet_scores_stage2[]` + `evidence_chunks[]` for Stage2 candidates
5. **Determine the universe carried forward**:
   - `ids_needed` = union of all ids in `shortlists_stage1.json` across lane×pool (deduped, order preserved).
   - Only these ids appear in `scores_final.jsonl`.
6. **Build final rows** (per id):
   - choose facet scores:
     - `with_abstract` and Stage2 present → use Stage2 facet scores + evidence chunks
     - otherwise → use Stage1 facet scores
   - recompute match parts (`best`, `top_m`, `cov`, `match`) using the exact G1 formula and `t`/`t_noabs`.
   - recompute lane fusion:
     - `match_lane = 0.80*match + 0.20*authority`
     - `authority_lane = 0.80*authority + 0.20*match`
   - attach minimal join metadata (title, doi, year, citations, venue, url, provider_ids)
7. **Write artifacts**:
   - `scores_final.jsonl`: JSONL rows sorted by id.
   - `rankings_stageg.json`: per lane/pool ids sorted by the recomputed lane score.

### 5) Caching & invalidation

- Phase G does not do “cache reuse”; it overwrites its outputs whenever the cell is run.
- True invalidation drivers are upstream:
  - Phase F pruning controls which ids are present in `scores_final.jsonl`.
  - Phase F Stage2 scoring controls which ids have Stage2 facet scores/evidence.

### 6) QC / Metrics / Logs

**Notebook QC/prints**

- “At a glance” summary:
  - shortlist_unique_ids, stage2 availability/usage
  - missing candidates / missing Stage1 scores
  - required facet counts (weight>=4) and thresholds
- Top‑20 diagnostics per lane/pool:
  - anchor hit rates (based on QueryPlan anchors over title+abstract)
  - missing required facets in top20
- Optional plots:
  - top20 lane_score bars (anchor hits highlighted)

**`metrics.json`**

- Stage key: `phase_g`
- Fields:
  - `counts.{shortlist_unique_ids,missing_candidates,missing_stage1_scores,stage2_available}`
  - `artifacts.{scores_final_jsonl,rankings_json}`
- Note: `phase_g.last_duration_s` may be `null` (the notebook does not wrap the full phase in `stage_timer`).

**`logs.jsonl`**

- Phase G does not emit many structured `log_event`s; it is primarily metrics + printed QC.

### 7) Tuning knobs

- Match aggregation parameters (`t`, `t_noabs`, `m`, weights) — changes ranking stability and partial-match behavior.
- Authority normalization constants (age_years handling, percentile definition, bonuses) — changes authority lane ordering and Phase K stratification outcomes.

### 8) Downstream impact (change propagation)

- If you change Phase G formulas, you change:
  - `scores_final.jsonl` content (Phase H reads and rewrites it)
  - rerank selection baseline (Phase I tasks are drawn from rankings derived from these scores)
  - output ordering and bucket quotas outcomes (Phase K)
- If you change which ids are included (via Phase F pruning or Phase G ids_needed logic), you change:
  - coverage tag totals (Phase H loops over `scores_final_by_id`)
  - rerank task list and cache keys (Phase I)
  - final output size and contents (Phase K)
- If you change authority percentile computation (candidate universe, year handling), you can shift authority scores for all candidates (global rescaling effect).

### 9) Example from run `4af2666…`

From `metrics.json` (`phase_g.counts`):

- `shortlist_unique_ids = 1,686`
- `stage2_available = 1,133`
- `missing_candidates = 0`, `missing_stage1_scores = 0`

Artifacts:

- `scores_final.jsonl` size `10.69 MB`
- `rankings_stageg.json` produced and later used as the Phase I baseline.

### 10) Blueprint alignment

Blueprint intent (Phase G):

- exact match formula (best + top-m + cov)
- authority normalization by citations/year percentile + recency
- exact lane fusion

Notebook status:

- Implemented: formulas match the blueprint structure and weights.
- Delta: blueprint suggests treating missing year as `age_years=1`; the notebook uses `age_years=10` when year is missing (affects authority for missing-year items).

---

## Phase H — Coverage tags (evidence-grounded; rewrites scores_final)

**Prev:** Phase G (scores_final + rankings) → **Next:** Phase I (rerank uses coverage tags)

### 1) Goal

Attach explainability to each shortlisted record by emitting `coverage_tags[]`:

- which facets are “covered” for this record
- the embedding score for that facet
- a short excerpt that grounds the claim (prefer Stage2 evidence chunks)

Phase H also **rewrites `scores_final.jsonl`** in-place to embed `coverage_tags` so Phase I and Phase K can consume a single file.

### 2) Inputs

**Config knobs used**

- `cfg.scoring_t` (threshold for `with_abstract`)
- `cfg.scoring_t_noabs` (threshold for `without_abstract`)
- Hard-coded “always include top facets” policy:
  - `with_abstract`: always include top 2 facets
  - `without_abstract`: always include top 1 facet

**Required artifacts**

- `runs/<run_id>/facets_index.json` (Phase F)
- `runs/<run_id>/scores_final.jsonl` (Phase G)
- `runs/<run_id>/rankings_stageg.json` (Phase G; used for preview tables)
- Candidate join file for fallback excerpts:
  - `runs/<run_id>/candidates_expanded.jsonl` if present/non-empty, else `candidates_normalized.jsonl`

### 3) Outputs

**Artifacts created/rewritten**

- `runs/<run_id>/coverage_tags.jsonl` (compact export: `{id,pool,coverage_tags}`)
- `runs/<run_id>/scores_final.jsonl` (rewritten to embed `coverage_tags` and padded arrays)

### 4) Processing (How it works)

Key code locations to edit (cell 17, `98b29fb2`):

- Covered-facet rule and tag building loop
- `_excerpt_for_tag` fallback logic
- Rewrite logic for `scores_final.jsonl`

Step-by-step mechanics:

1. Load `facets_index.json` to get:
   - `facet_ids[]` (canonical order)
   - `label_by_fid` (used to fill `facet_label_en`)
2. Load candidate join file into `candidates_by_id` (used only for excerpt fallbacks).
3. Load `scores_final.jsonl` into `scores_final_by_id` (dict keyed by id).
4. For each record:
   - normalize `facet_scores.scores` to length `len(facet_ids)` (pad with 0.0)
   - normalize `evidence_chunks` to length `len(facet_ids)` (pad with `None`)
   - choose `T` and `topN` based on pool:
     - `with_abstract`: `T=cfg.scoring_t`, `topN=2`
     - `without_abstract`: `T=cfg.scoring_t_noabs`, `topN=1`
   - compute covered facet indices:
     - all facets with `score >= T`
     - plus the topN facets by score (always included)
   - build `coverage_tags[]` sorted by score desc:
     - `{facet_id, facet_label_en, score, excerpt}`
5. Excerpt selection (`_excerpt_for_tag`):
   - prefer Stage2 evidence chunk at the same facet index (`evidence_chunks[ix]`)
   - else fallback to:
     - candidate abstract (trimmed) if present
     - else metadata string `title | venue | year`
     - else title
6. Write outputs:
   - `coverage_tags.jsonl` (compact export)
   - rewrite `scores_final.jsonl` so each row now contains `coverage_tags`
7. Log + metrics:
   - `log_event(stage="phase_h_coverage_tags", event="cache_write", provider="coverage_tags", ...)`
   - `metrics.json` stage `phase_h_coverage_tags.counts` with totals and fallback counters

### 5) Caching & invalidation

- Phase H overwrites its outputs whenever run; it does not reuse `coverage_tags.jsonl`.
- Invalidation drivers:
  - any change to `scores_final.jsonl` (Phase G/F)
  - any change to facet order/weights (`facets_index.json`)
  - any change to thresholds/topN policy (`t`, `t_noabs`, hard-coded topN)

### 6) QC / Metrics / Logs

**Notebook QC/prints**

- “At a glance”:
  - `records_scored_final`, `coverage_tags_total`
  - avg tags/record per pool
  - `fallback_excerpt_tags`, `empty_excerpt_fallbacks`
- Preview tables:
  - top5 per lane/pool with top tags + excerpt
  - facet coverage frequency in top20 per lane/pool
- Optional plots:
  - histogram of coverage tag counts per record

**`metrics.json`**

- Stage key: `phase_h_coverage_tags`
- Fields:
  - `last_duration_s`
  - `counts.{records_scored_final,coverage_tags_total,records_by_pool,tags_by_pool,fallback_excerpt_tags,empty_excerpt_fallbacks,...}`

**`logs.jsonl`**

- Single summary event `cache_write` (provider `"coverage_tags"`) for the whole phase.

### 7) Tuning knobs

- Thresholds:
  - `scoring_t` (with-abstract)
  - `scoring_t_noabs` (no-abstract)
- “Always include top facets” policy:
  - raising/lowering `topN` changes tag verbosity and rerank evidence payload size.
- Excerpt fallback preference:
  - if you tighten excerpt rules, expect more `insufficient_info=true` reranks (Phase I).

### 8) Downstream impact (change propagation)

- Phase I rerank prompts are built from `coverage_tags` excerpts. If coverage tags are noisy or generic, rerank becomes unreliable.
- Phase K includes `coverage_tags` in `output.json`. Any change to tag selection changes the output contract seen by consumers.
- Because Phase H rewrites `scores_final.jsonl`, any tool that reads `scores_final.jsonl` must assume it may contain `coverage_tags` (and padded arrays).
- If Stage2 evidence chunks are sparse (few `with_abstract` candidates), Phase H will fall back to abstract/metadata excerpts and `insufficient_info` rates in Phase I will increase.

### 9) Example from run `4af2666…`

From `metrics.json` (`phase_h_coverage_tags.counts`):

- `records_scored_final = 1,686`
- `coverage_tags_total = 13,830`
- `records_by_pool`: `with_abstract=1,133`, `without_abstract=553`
- `fallback_excerpt_tags = 2,007` (all fallback excerpts in this run were from `without_abstract`)
- `empty_excerpt_fallbacks = 0`

### 10) Blueprint alignment

Blueprint intent (Phase H):

- covered if threshold hit OR among top facets (top-2 for with-abstract, top-1 for no-abstract)
- coverage tags must be grounded in embedding evidence

Notebook status:

- Implemented: selection rule matches blueprint; prefers Stage2 evidence chunks where available.
- Implemented: explicit fallback excerpt rules when evidence chunks are missing.

---

## Phase I — LLM rerank top‑K (pointwise; cached; pool-separated)

**Prev:** Phase H (coverage tags embedded) → **Next:** Phase K (final output; Phase J is missing)

### 1) Goal

Improve ordering in the top segment of each lane/pool by applying a pointwise, evidence-grounded LLM reranker:

- rerank only top‑K per lane/pool (cost control)
- enforce honesty for metadata-only (`without_abstract`)
- cache results per `(run_id, id, lane, pool)`

Phase I does **not** change scores; it produces a new ranking file that reorders only the top segment.

### 2) Inputs

**Config knobs used**

- `cfg.rerank_top_k_pre` (default `40`) → K tasks per lane/pool
- `cfg.rerank_concurrency` (default `20`)
- `cfg.scoring_t`, `cfg.scoring_t_noabs` (used only for fallback coverage-tag computation if Phase H was skipped)
- OpenAI key:
  - `cfg.openai_api_key` or env `OPENAI_API_KEY` (required)

**Hard-coded model policy (code-level)**

- `MODEL_RERANK = "gpt-5-nano"`
- `reasoning_effort="medium"`, `max_output_tokens=8000`, `timeout_s=180`
- `RETRIES = 3`

**Required artifacts**

- `runs/<run_id>/facets_index.json` (Phase F)
- `runs/<run_id>/scores_final.jsonl` (Phase G; should already include `coverage_tags` from Phase H, but Phase I can compute a fallback)
- `runs/<run_id>/rankings_stageg.json` (Phase G; baseline ranking to rerank)
- Candidate join file (metadata for prompt):
  - `runs/<run_id>/candidates_expanded.jsonl` if present/non-empty, else `candidates_normalized.jsonl`

### 3) Outputs

**Artifacts created/rewritten**

- Per-task rerank caches:
  - `runs/<run_id>/cache/rerank/<task_hash>.json`
- Aggregated rerank outputs:
  - `runs/<run_id>/rerank_results.jsonl`
- Reranked rankings:
  - `runs/<run_id>/rankings_stagei.json`

### 4) Processing (How it works)

Key code locations to edit (cell 18, `phase_i_rerank`):

- Task selection (top‑K per lane/pool)
- Prompt builder (`_build_user_prompt`) + lane guidance
- JSON schema (`RERANK_JSON_SCHEMA`) + sanitizer (`_clean_rerank`)
- Cache path (`_cache_path`) and aggregation logic
- Two-tier sort policy for `rankings_stagei.json`

Step-by-step mechanics:

1. Load facets + build `facet_ids[]`, required facets (`weight>=4`), and label maps.
2. Load `scores_final.jsonl` into memory.
   - If `coverage_tags` are missing (Phase H skipped), Phase I computes a fallback coverage_tags list from facet scores + evidence/metadata (same thresholds/topN idea).
3. Load baseline rankings from `rankings_stageg.json`.
4. Build rerank task list:
   - for each lane (`match`,`authority`) and each pool:
     - take the first `K` ids from `rankings_stageg.json`
   - total tasks = `K × 4` (unless a group has fewer than K)
5. Cache-first execution:
   - For each task `(id, lane, pool)`, check cache file:
     - hit → append a `cache_hit=True` row to `rerank_results.jsonl` rows
     - miss/bad cache → schedule for OpenAI call
6. Pointwise rerank calls (thread pool):
   - Prompt includes: chapter title, lane/pool, required facets, candidate metadata, and compact `coverage_tags` excerpts.
   - Output schema (strict): `{llm_score_0_100, covered_facets, rationale, insufficient_info}`
   - Without-abstract honesty rule in the system prompt:
     - if pool is `without_abstract`, set `insufficient_info=true` unless evidence supports multiple required facets.
   - Each success is written to `cache/rerank/<task_hash>.json` and added to `rerank_results.jsonl`.
7. Build `rankings_stagei.json` (rerank affects top segment only):
   - For each lane/pool:
     - `top = first K ids`
     - `tail = remaining ids`
     - sort `top` (only those with rerank results) by:
       - `(insufficient_info, -llm_score_0_100, -stageg_lane_score)`
     - output = `top_sorted + top_fail + tail` (so missing reranks fall after reranked items)

### 5) Caching & invalidation

- Cache key:
  - `stable_hash("rerank", run_id, lane, pool, candidate_id)` → `<task_hash>.json`
- There is no notebook FORCE flag for rerank; to rerun rerank you must:
  - delete `runs/<run_id>/cache/rerank/*.json` (or the whole folder), and rerun Phase I
- If you change prompt/schema/model or the `coverage_tags` payload shape, you should clear rerank caches; otherwise you’ll silently reuse old judgments.

### 6) QC / Metrics / Logs

**Notebook QC/prints**

- Prints “At a glance”:
  - model, top_k_per_lane_pool, concurrency
  - tasks_total, cache_hits, api_calls, failures
  - cost_usd_new and cost_usd_total
  - artifact paths for `rerank_results.jsonl` and `rankings_stagei.json`

**`metrics.json`**

- Stage key: `phase_i_rerank`
- Fields:
  - `last_duration_s`
  - `counts` including:
    - tasks_total, cache_hits, bad_cache, api_calls, failures
    - token totals (in/cached/out) and cost totals/new
    - `insufficient_by_lane_pool`
    - `latency_s_p50`
    - artifact paths for rerank_results and rankings_stagei

**`logs.jsonl`**

- Per-task `cache_hit` / `cache_write` events (with id/lane/pool + cache path).
- `rerank_failed` events for any call failures.

### 7) Tuning knobs

- `rerank_top_k_pre` (K): main cost/quality trade-off.
- `rerank_concurrency`: latency vs rate-limit risk.
- Prompt payload:
  - which metadata fields are included
  - how many coverage tags/excerpts you pass through
- Sort policy:
  - current implementation pushes `insufficient_info=true` items down inside the top-K

### 8) Downstream impact (change propagation)

- Phase K will prefer `rankings_stagei.json` when present; Phase I therefore directly affects the final output ordering.
- If you increase K, you increase:
  - rerank costs
  - the number of rerank cache files
  - the proportion of the ranking influenced by the LLM
- If your coverage tags are weak (Phase H fallback-heavy), rerank becomes noisy and `insufficient_info` rates increase (especially `without_abstract`).

### 9) Example from run `4af2666…`

From `metrics.json` (`phase_i_rerank.counts`):

- `tasks_total = 160` (K=40 across 4 lane/pool groups)
- `cache_hits = 0`, `api_calls = 160`, `failures = 0`
- cost: `$0.1608` (new and total)
- median latency (p50): `23.41s`
- `insufficient_by_lane_pool` includes:
  - `authority/without_abstract: 14` (metadata-only honesty rule in action)

### 10) Blueprint alignment

Blueprint intent (Phase I):

- strict schema `{llm_score_0_100, covered_facets, rationale, insufficient_info}`
- top-K only, cached by `(run_id, id, lane, pool)`
- metadata-only honesty rule

Notebook status:

- Implemented: strict JSON schema calls, caching, concurrency, retries, and two-tier ranking update.
- Delta: model is hard-coded (`gpt-5-nano`) rather than configurable via `PipelineConfig`.

---

## Phase J — Not implemented (coverage top-up)

Blueprint intent:

- After rerank, add an extra “coverage top-up” list per lane/pool that improves coverage of **required facets** (typically weight>=4) **without changing** the primary top‑20.

Where it would slot:

- Conceptually between **Phase I** (reranked ordering) and **Phase K** (final output formatting).
- Inputs would likely be:
  - `rankings_stagei.json` (preferred) or `rankings_stageg.json`
  - `scores_final.jsonl` (needs `coverage_tags` from Phase H)
  - `facets_index.json` (to determine required facets)
- Output would be something like:
  - `coverage_top_up` lists per lane/pool, inserted into `output.json`
  - (optionally) a dedicated artifact file for debugging the greedy selection

How the notebook references Phase J today:

- Phase G QC fix text suggests: “consider coverage top-up (Phase H/J)”.
- Phase K explicitly says it is skipping Phase J and emits `coverage_top_up: []` in `output.json`.

Current behavior (important downstream consequence):

- Your final `output.json` always contains empty `coverage_top_up` lists, so any “required facet coverage gaps” must be solved earlier (Phase B/C/F/G/H/I) rather than patched later.

---

## Phase K — Final lane construction and `output.json` formatting

**Prev:** Phase I (reranked rankings; Phase J absent) → **Final**

### 1) Goal

Assemble the final, consumer-facing JSON output:

- choose which ranking file to use (reranked vs baseline)
- enforce pool separation in final lists
- apply authority time stratification (classic/mid/recent quotas)
- emit `two_lane_output_v1` to `runs/<run_id>/output.json`

### 2) Inputs

**Config knobs used**

- Authority time stratification:
  - `cfg.authority_classic_year_max` (default `2004`)
  - `cfg.authority_recent_year_window` (default `8`)
  - `cfg.authority_bucket_quotas` (default `{"classic":8,"mid":6,"recent":6}`)
- Output size:
  - `TOP_N = 20` (hard-coded in the notebook)

**Required artifacts**

- `runs/<run_id>/facets_index.json` (Phase F)
- `runs/<run_id>/scores_final.jsonl` (Phase G; should include `coverage_tags` from Phase H)
- Rankings:
  - prefers `runs/<run_id>/rankings_stagei.json` (Phase I) if present
  - else falls back to `runs/<run_id>/rankings_stageg.json` (Phase G)
- Candidate join file:
  - prefers `runs/<run_id>/candidates_expanded.jsonl` if present/non-empty
  - else uses `runs/<run_id>/candidates_normalized.jsonl`
- Optional:
  - `runs/<run_id>/rerank_results.jsonl` (Phase I; used to attach rerank info to cards)
- Repo metadata:
  - `git rev-parse HEAD` and `git status --porcelain` (best-effort; can be `null`)

### 3) Outputs

**Artifacts created/rewritten**

- `runs/<run_id>/output.json`

### 4) Processing (How it works)

Key code locations to edit (cell 19, `c2f3d8a1`):

- Ranking selection: `rankings_path = rankings_stagei.json if exists else rankings_stageg.json`
- Pool/year helpers: `_pool_of`, `_year_of`, `_bucket_for_year`
- Authority picker: `_select_authority_primary`
- Card builder: `_card`
- Output assembly: `output_obj`

Step-by-step mechanics:

1. Load facet index (labels + weights) for output embedding.
2. Load `scores_final.jsonl` into `scores_by_id` (must exist).
3. Load candidate join file into `candidates_by_id` (for authors, abstract, external ids, sources, etc.).
4. Load rerank results (optional) into `rerank_by_key[(id,lane,pool)]`.
5. Load rankings from `rankings_stagei.json` (if present) else stageg.
6. Enforce strict pool separation in final rankings:
   - drop any id whose `_pool_of(id)` doesn’t match the target pool.
7. Select primary top‑20 per lane/pool:
   - `match` lane: first 20 ids in ranking order.
   - `authority` lane: apply time stratification buckets:
     - classic: `year <= classic_year_max`
     - recent: `year >= (current_year - recent_year_window)`
     - mid: everything else (including missing year)
     - pick in bucket order `classic → recent → mid` up to quota, then fill remaining to 20 from best overall.
8. Build card objects for selected ids:
   - join metadata + scores + coverage tags
   - attach rerank result if present for that lane/pool
9. Assemble `two_lane_output_v1`:
   - includes redundant convenience views:
     - `rankings` (full ids)
     - `top` (cards)
     - `authority_lane.{pool}.primary_top_20` and `match_lane.{pool}.primary_top_20`
   - emits empty `coverage_top_up` lists (Phase J not implemented)
10. Write `output.json` under `stage_timer("phase_k_output")` and log a `cache_write` event.

### 5) Caching & invalidation

- Phase K overwrites `output.json` whenever run; no cache reuse.
- Reproducibility gotcha:
  - authority bucketing uses `current_year = date.today().year`. Re-running Phase K in a different calendar year can change bucket boundaries and therefore the selected authority top‑20, even if rankings and scores are unchanged.

### 6) QC / Metrics / Logs

**Notebook QC/prints**

- “At a glance”:
  - rankings_used path, rerank_rows_loaded, top_n, bucket settings, output.json path
- QC block checks:
  - list sizes, pool separation, etc.

**`metrics.json`**

- Stage key: `phase_k_output`
- Fields:
  - `last_duration_s`
  - `counts.{rankings_used,rerank_rows_loaded,top_n,output_json}` (paths may be absolute)

**`logs.jsonl`**

- Logs `cache_write` with provider `"output"` and fields like `top_n`, `rerank_loaded`, `rankings_used`.

### 7) Tuning knobs

- Authority stratification:
  - `classic_year_max`, `recent_year_window`, `bucket_quotas`
  - changing quotas changes the mix of foundational vs recent sources
- Output size: hard-coded `TOP_N=20`
- Output payload:
  - card fields included (abstract included only if present; coverage tags always included if Phase H ran)

### 8) Downstream impact (change propagation)

- If you change only output formatting/card fields, you usually only need to rerun Phase K (no need to redo retrieval/embeddings).
- If you change authority stratification logic, it changes which authority items appear in `primary_top_20`, but does not change underlying rankings/scores.
- Consumers of `output.json` may rely on:
  - `schema_version`
  - `rankings` id lists
  - `top` card fields
  - the presence of `coverage_top_up` (currently always empty)

### 9) Example from run `4af2666…`

From `metrics.json` (`phase_k_output.counts`):

- `rankings_used = rankings_stagei.json`
- `rerank_rows_loaded = 160`
- `top_n = 20`

Artifact:

- `output.json` size `1.22 MB`

### 10) Blueprint alignment

Blueprint intent (Phase K):

- emit final JSON with two lanes × two pools, each with `primary_top_20` + `coverage_top_up`
- authority time stratification recommended

Notebook status:

- Implemented: authority time stratification with configurable quotas and cutoffs.
- Implemented: output contains `primary_top_20` and embeds `coverage_tags` and `rerank` where available.
- Delta: Phase J is not implemented, so `coverage_top_up` is always `[]`.

---

## Appendix A — Schema quick reference (example run `4af2666…`)

Tiny examples are taken from `runs/4af2666be828e5054ccf4d31/` and truncated with `…`. Any absolute paths inside artifacts are omitted or rewritten as `runs/<run_id>/…`.

### `runs/<run_id>/query_plan.json`

**Type:** JSON object

**Key fields**

- `topic_summary_en`, `topic_summary_de`
- `primary_context_anchors.{en,de}` (lists of short anchors used later for QC and pruning gates)
- `facets[]` (atomic bilingual facets)
- `global_canonical_terms.{en,de}`, `global_exclusions.{en,de}`

**Facet object (`facets[]`)**

- `facet_id` (stable key; used everywhere downstream)
- `facet_label_en`, `facet_label_de`
- `facet_type` (`theory|mechanism|methods|…`)
- `importance_weight` (`1..5`)
- `text_en`, `text_de`
- `canonical_terms.{en,de}`, `neighbor_terms.{en,de}`, `exclusion_terms.{en,de}`

Example (first facet):

```json
{
  "facet_id": "decision_confidence_and_metacognition",
  "facet_label_en": "Decision confidence and metacognition",
  "facet_label_de": "Entscheidungssicherheit und Metakognition",
  "facet_type": "theory",
  "importance_weight": 5,
  "text_en": "Define decision confidence … online purchase behavior.",
  "canonical_terms": {
    "en": ["decision confidence", "choice certainty", "…"],
    "de": ["Entscheidungssicherheit", "…"]
  },
  "neighbor_terms": { "en": ["…"], "de": ["…"] },
  "exclusion_terms": { "en": ["…"], "de": ["…"] }
}
```

### `runs/<run_id>/facets_index.json`

**Type:** JSON object (the “facet order contract”)

**Key fields**

- `facet_ids[]` (canonical order; index alignment for all `facet_scores_*[]` arrays)
- `facets[]` (subset of facet metadata: ids + labels + weights + types)

Example (trimmed):

```json
{
  "facet_ids": [
    "decision_confidence_and_metacognition",
    "heuristics_and_biases_in_ecommerce",
    "…"
  ],
  "facets": [
    {
      "facet_id": "decision_confidence_and_metacognition",
      "importance_weight": 5,
      "facet_type": "theory"
    },
    "…"
  ]
}
```

### `runs/<run_id>/openalex_queries.json`

**Type:** JSON object `{ "openalex_queries": OpenAlexQuery[] }`

**OpenAlexQuery fields**

- `intent` (`match|authority`)
- `language` (`en|de`)
- `search_field` (e.g., `title_and_abstract.search`)
- `query_string` (OpenAlex boolean)
- `filters` (comma-separated OpenAlex filters)
- `sort` (e.g., `cited_by_count:desc`)
- `per_page` (typically `200`)
- `notes` (human explanation; not used by the provider)

Example:

```json
{
  "intent": "authority",
  "language": "en",
  "search_field": "title_and_abstract.search",
  "query_string": "(\"Decision Confidence\" OR \"Dual Process Theory\" OR …) AND (\"consumer electronics\" OR …)",
  "filters": "is_paratext:false,is_retracted:false,language:en",
  "sort": "cited_by_count:desc",
  "per_page": 200,
  "notes": "Broad authoritative English literature …"
}
```

### `runs/<run_id>/semanticscholar_queries.json`

**Type:** JSON object `{ "s2_bulk_queries": S2BulkQuery[] }`

**S2BulkQuery fields (as produced by the notebook)**

- `intent` (`match|authority`)
- `language` (`en|de`)
- `query_string` (S2 bulk-search syntax; escaped quotes in JSON)
- `notes`

Example:

```json
{
  "intent": "authority",
  "language": "en",
  "query_string": "+(\\\"Decision Confidence\\\" | \\\"Heuristics and Biases\\\" | …) +(\\\"decision confidence\\\" | …)",
  "notes": "Authority: English overview of core chapter topics"
}
```

### `runs/<run_id>/openalex_raw.jsonl` / `runs/<run_id>/semanticscholar_raw.jsonl`

**Type:** JSONL; each row is a provider result “enveloped” with query provenance.

**OpenAlex row fields**

- `run_id`, `provider="openalex"`, `query_hash`, `query_i`, `intent`, `language`, `rank`
- `work` (OpenAlex work object; full API payload)

Example (trimmed):

```json
{
  "run_id": "4af2666be828e5054ccf4d31",
  "provider": "openalex",
  "query_hash": "…",
  "query_i": 5,
  "intent": "match",
  "language": "en",
  "rank": 117,
  "work": {
    "id": "https://openalex.org/W1972912785",
    "doi": "https://doi.org/10.1108/09590551011027122",
    "publication_year": 2010,
    "cited_by_count": 147,
    "abstract_inverted_index": { "…": [0, 12, 33] }
  }
}
```

**Semantic Scholar row fields**

- `run_id`, `provider="semanticscholar"`, `query_hash`, `query_i`, `intent`, `language`, `rank`
- `paper` (S2 paper payload; includes `paperId`, `externalIds`, and sometimes `abstract`)

Example (trimmed):

```json
{
  "run_id": "4af2666be828e5054ccf4d31",
  "provider": "semanticscholar",
  "query_hash": "…",
  "query_i": 0,
  "intent": "authority",
  "language": "en",
  "rank": 1,
  "paper": {
    "paperId": "015816b55b6cb1b1c452009187c75da55ad09044",
    "externalIds": { "DOI": "10.1145/2655673" },
    "year": 2014,
    "citationCount": 0,
    "abstract": null
  }
}
```

### `runs/<run_id>/candidates_normalized.jsonl` / `runs/<run_id>/candidates_expanded.jsonl`

**Type:** JSONL; each row is a canonical `Candidate` (deduped across providers).

**Key fields**

- Identity: `id` (prefer DOI), `doi`, `external_ids`
- Metadata: `title`, `authors[]`, `year`, `venue`, `url`, `language`, `languages[]`, `abstract|null`
- Provenance: `provider_ids{openalex:[…],semanticscholar:[…]}`, `sources[]`, `intents[]`
- Metrics: `citations`, `influential_citations`, `venue_is_core`
- Pool split: `pool` (`with_abstract|without_abstract`)

Example (trimmed):

```json
{
  "id": "10.5860/choice.46-0977",
  "doi": "10.5860/choice.46-0977",
  "title": "Nudge: improving decisions about health, wealth, and happiness",
  "year": 2008,
  "pool": "with_abstract",
  "provider_ids": {
    "openalex": ["https://openalex.org/W1481908410"],
    "semanticscholar": ["7cdaa5916a53db2b8403620854d6dac6fccd2f0b"]
  },
  "sources": [
    {
      "provider": "openalex",
      "query_hash": "…",
      "query_i": 5,
      "intent": "match",
      "language": "en",
      "rank": 117
    },
    "…"
  ],
  "intents": ["authority", "match"]
}
```

Notes:

- `candidates_expanded.jsonl` has the same row schema, but the set of rows may include S2 Recommendations additions (Phase F) and updated provenance/dedup merges.

### `runs/<run_id>/scores_stage1.jsonl`

**Type:** JSONL; Stage 1 scores for (expanded) candidates.

**Key fields**

- `id`, `pool`, `year`, `citations`
- `facet_scores_stage1[]` (float list aligned to `runs/<run_id>/facets_index.json.facet_ids`)
- Aggregates: `match_stage1`, `authority`, `match_lane`, `authority_lane`, plus parts `best`, `top_m`, `cov`

Example (trimmed):

```json
{
  "id": "10.5860/choice.46-0977",
  "pool": "with_abstract",
  "year": 2008,
  "citations": 1251,
  "facet_scores_stage1": [0.3585, 0.327, 0.2196, "…"],
  "best": 0.4655,
  "top_m": 0.4103,
  "cov": 0.0332,
  "match_stage1": 0.3652,
  "authority": 0.8802
}
```

### `runs/<run_id>/shortlists_stage1.json`

**Type:** JSON object (pruning contract for later phases)

**Key fields**

- `match.{with_abstract,without_abstract} = [candidate_id…]`
- `authority.{with_abstract,without_abstract} = [candidate_id…]`

Example (trimmed):

```json
{
  "match": {
    "with_abstract": [
      "cand_c4238344b1a57423c88ad418",
      "10.1073/pnas.2107346118",
      "…"
    ]
  },
  "authority": {
    "with_abstract": [
      "10.1145/3491102.3517638",
      "10.1080/0144929x.2023.2286535",
      "…"
    ]
  }
}
```

### `runs/<run_id>/scores_stage2.jsonl`

**Type:** JSONL; Stage 2 (chunk) scores for the Stage2 subset (with-abstract shortlist only).

**Key fields**

- `id`
- `facet_scores_stage2[]` and `evidence_chunks[]` (both aligned to `facets_index.json`)
- `match_stage2` plus parts `best2`, `top_m2`, `cov2`

Example (trimmed):

```json
{
  "id": "10.1001/jamanetworkopen.2018.5011",
  "facet_scores_stage2": [0.2989, 0.3077, 0.2936, "…"],
  "evidence_chunks": ["If nudging or defaults are used …", "…"],
  "match_stage2": 0.4253
}
```

### `runs/<run_id>/scores_final.jsonl`

**Type:** JSONL; final merged shortlist rows (rewritten by Phase H to embed coverage tags).

**Key fields**

- `id`, `pool`, plus compact metadata (`title`, `doi`, `year`, `citations`, `venue`, `url`, `provider_ids`)
- `scores{match,authority,match_lane,authority_lane,best,top_m,cov}`
- `facet_scores{stage,scores[]}` (where `stage ∈ {"stage1","stage2"}`)
- `evidence_chunks[]` (aligned to facets; may be `null`/empty for without-abstract)
- `coverage_tags[]` (added in Phase H)

Example (trimmed):

```json
{
  "id": "10.1001/jamanetworkopen.2018.5011",
  "pool": "with_abstract",
  "scores": {
    "match": 0.4253,
    "authority": 0.44,
    "match_lane": 0.4397,
    "authority_lane": 0.4327
  },
  "facet_scores": {
    "stage": "stage2",
    "scores": [0.2989, 0.3077, 0.2936, "…"]
  },
  "coverage_tags": [
    {
      "facet_id": "digital_nudging_design_patterns",
      "facet_label_en": "Digital nudging design patterns",
      "score": 0.5273,
      "excerpt": "As defined by Thaler and Sunstein …"
    },
    "…"
  ]
}
```

### `runs/<run_id>/rankings_stageg.json` / `runs/<run_id>/rankings_stagei.json`

**Type:** JSON object with lane/pool ordered id lists.

**Key fields**

- `run_id`, `generated_at_utc`
- `rankings.match.{with_abstract,without_abstract} = [candidate_id…]`
- `rankings.authority.{with_abstract,without_abstract} = [candidate_id…]`

Example (trimmed):

```json
{
  "run_id": "4af2666be828e5054ccf4d31",
  "generated_at_utc": "2026-02-15T16:07:25+00:00",
  "rankings": {
    "match": {
      "with_abstract": ["10.1080/0144929x.2023.2286535", "…"],
      "without_abstract": ["10.1016/j.paid.2018.07.033", "…"]
    },
    "authority": {
      "with_abstract": ["10.1145/3491102.3517638", "…"],
      "without_abstract": ["10.1006/cpac.1998.0305", "…"]
    }
  }
}
```

Notes:

- `rankings_stageg.json`: pure score-based ordering (Phase G).
- `rankings_stagei.json`: top‑K per lane/pool replaced by rerank order (Phase I).

### `runs/<run_id>/coverage_tags.jsonl`

**Type:** JSONL; per-id coverage tag export.

**Key fields**

- `id`, `pool`
- `coverage_tags[]` each `{facet_id, facet_label_en, score, excerpt}`

Example (trimmed):

```json
{
  "id": "10.1001/jamanetworkopen.2018.5011",
  "pool": "with_abstract",
  "coverage_tags": [
    {
      "facet_id": "digital_nudging_design_patterns",
      "score": 0.5273,
      "excerpt": "As defined by Thaler and Sunstein …"
    },
    "…"
  ]
}
```

### `runs/<run_id>/rerank_results.jsonl`

**Type:** JSONL; one row per rerank task (id × lane × pool).

**Key fields**

- Routing: `id`, `lane`, `pool`, `cache_hit`
- `rerank` (strict schema): `{llm_score_0_100:int, covered_facets:[facet_id…], rationale:str, insufficient_info:bool}`
- `openai` (request meta + usage + cost estimate)

Example (trimmed):

```json
{
  "ts": "2026-02-15T16:10:57+00:00",
  "run_id": "4af2666be828e5054ccf4d31",
  "id": "10.1002/bdm.2035",
  "lane": "authority",
  "pool": "with_abstract",
  "cache_hit": false,
  "rerank": {
    "llm_score_0_100": 78,
    "covered_facets": ["decision_confidence_and_metacognition", "…"],
    "insufficient_info": false
  },
  "openai": {
    "model_requested": "gpt-5-nano",
    "model_used": "gpt-5-nano-2025-08-07",
    "usage": { "input_tokens": 1782, "output_tokens": 4367 },
    "cost_estimate": { "total_cost_usd": 0.0018359 }
  }
}
```

### `runs/<run_id>/output.json` (`two_lane_output_v1`)

**Type:** JSON object; final contract for consumers.

**Key fields**

- Identity: `schema_version`, `run_id`, `pipeline_version`, `generated_at_utc`, `config_hash`
- Repro meta: `git`, `run_costs`, `artifacts`
- Retrieval plan: `facets` (planner facets snapshot)
- Rankings:
  - `rankings.{match,authority}.{with_abstract,without_abstract}` (ordered id lists)
  - `top.{match,authority}.{with_abstract,without_abstract}` (top‑20 “cards”, each with metadata + scores + coverage + rerank)
- Lane outputs (consumer-facing):
  - `match_lane.{with_abstract,without_abstract}.{primary_top_20,coverage_top_up}` (lists of card objects)
  - `authority_lane.{with_abstract,without_abstract}.{primary_top_20,coverage_top_up}` (lists of card objects)
  - `authority_lane.time_stratification` (bucket settings + picked/available counts)

Example (trimmed; `chapter_spec_text` omitted):

```json
{
  "schema_version": "two_lane_output_v1",
  "run_id": "4af2666be828e5054ccf4d31",
  "pipeline_version": "two_lane_v1",
  "rankings": {
    "match": { "with_abstract": ["10.1080/0144929x.2023.2286535", "…"] },
    "authority": { "with_abstract": ["10.1145/3491102.3517638", "…"] }
  },
  "match_lane": {
    "with_abstract": {
      "primary_top_20": [
        {
          "id": "10.1080/0144929x.2023.2286535",
          "title": "Data-driven digital nudging: …"
        },
        "…"
      ],
      "coverage_top_up": []
    },
    "without_abstract": {
      "primary_top_20": [
        {
          "id": "10.1016/j.paid.2018.07.033",
          "title": "Dimensions of decision-making: …"
        },
        "…"
      ],
      "coverage_top_up": []
    }
  },
  "authority_lane": {
    "with_abstract": {
      "primary_top_20": [
        { "id": "10.1080/09512749908719280", "title": "The US and ASEM: …" },
        "…"
      ],
      "coverage_top_up": []
    },
    "without_abstract": {
      "primary_top_20": [
        {
          "id": "10.1006/cpac.1998.0305",
          "title": "Designing Accountability: …"
        },
        "…"
      ],
      "coverage_top_up": []
    },
    "time_stratification": {
      "classic_year_max": 2004,
      "recent_year_window": 8,
      "bucket_quotas": { "classic": 8, "mid": 6, "recent": 6 }
    }
  }
}
```

---

## Appendix B — Config & environment index

This appendix lists the knobs that actually exist in the notebook today (user cell + `PipelineConfig`) and where they flow downstream.

### User cell toggles (cell 02, `1b6e3b7b`)

| Key                              | Default in notebook | Used by phase(s)                                       | Downstream impact notes                                                                                                                                   |
| -------------------------------- | ------------------: | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `chapter_title`                  |  (chapter-specific) | A (run_id), B/C/I prompts, `output.json`               | Changing it changes `run_id` (new run folder) and changes the LLM planning/building behavior.                                                             |
| `chapter_spec_text`              |  (chapter-specific) | A (run_id), B/C/I prompts, `output.json`               | Same: changes `run_id` and the entire retrieval/scoring outcome.                                                                                          |
| `pipeline_version`               |       `two_lane_v1` | A (run_id + config), `output.json`                     | Treat as a “semantic version”: changing it intentionally invalidates caches via new `run_id`.                                                             |
| `FORCE_REBUILD_QUERY_PLAN`       |             `False` | B                                                      | When `True`, ignores cached `query_plan.json` and re-calls the planner. Forces rerun of C→K if you want a coherent run.                                   |
| `FORCE_REBUILD_PROVIDER_QUERIES` |             `False` | C                                                      | When `True`, ignores cached provider query JSONs and re-calls query builders. Forces rerun of D→K for coherent artifacts.                                 |
| `FORCE_REBUILD_RETRIEVAL`        |             `False` | D (and indirectly E/F/…)                               | When `True`, refetches providers (ignores per-query caches) and rebuilds raw aggregates. Forces rerun of E→K.                                             |
| `PRUNE_N1_NO_ABS`                |               `300` | A (cfg override), F (prune), downstream via shortlists | Lowers cost by shrinking without-abstract work; can reduce recall/coverage and can starve later phases (coverage tags, rerank, authority stratification). |

### Environment variables (read in `PipelineConfig.from_env`, cell 04, `e8cc3f52`)

| Env var                   | Required?   | Used by phase(s)        | Notes                                                                |
| ------------------------- | ----------- | ----------------------- | -------------------------------------------------------------------- |
| `OPENAI_API_KEY`          | Yes         | B, C, F (embeddings), I | Missing → hard error before planner/embeddings/rerank.               |
| `OPENALEX_API_KEY`        | Yes         | D                       | Missing → OpenAlex retrieval fails (QC marks as `FAIL`).             |
| `SEMANTICSCHOLAR_API_KEY` | Yes         | D (+ F recommendations) | Missing → S2 retrieval/recs may fail or be throttled; QC expects it. |
| `OPENALEX_EMAIL`          | Recommended | D                       | Used as `mailto=` etiquette parameter.                               |
| `OPENALEX_MAILTO`         | Recommended | D                       | Alias for `OPENALEX_EMAIL`; one of them is enough.                   |

### `PipelineConfig` fields (cell 04, `e8cc3f52`) — defaults and phase reach

`PipelineConfig` is the notebook’s single config surface (Pydantic model, `extra="forbid"`). Defaults below are from the class definition; any user overrides happen in Phase A.2.

**Identity / layout**

- `pipeline_version="two_lane_v1"` — affects run identity and `output.json`.
- `runs_root=<notebook_dir>/runs` — where run folders live.

**OpenAI (planner + builders)**

- `openai_api_key=None` (from env) — Phases B/C; also required for F embeddings and I rerank.
- `openai_model_planner="gpt-5-mini"` — used for Phase B planner and both Phase C query builders.
- `openai_reasoning_effort="high"` — passed to the OpenAI call helpers for B/C.
- `openai_timeout_s=43200.0` — long ceiling for notebook runs.
- `openai_max_output_tokens_planner=100000` — budget for structured planner/builder outputs.

**Provider endpoints + throttling**

- `openalex_base_url="https://api.openalex.org"` — Phase D.
- `openalex_api_key=None` (from env) — Phase D.
- `openalex_email=None` (from env `OPENALEX_EMAIL`/`OPENALEX_MAILTO`) — Phase D.
- `openalex_timeout_s=60.0`, `openalex_rps=10.0` — Phase D.
- `semanticscholar_base_url="https://api.semanticscholar.org/graph/v1"` — Phase D (+ F rec expansion).
- `semanticscholar_api_key=None` (from env) — Phase D (+ F rec expansion).
- `semanticscholar_timeout_s=60.0`, `semanticscholar_rps=1.0` — Phase D (+ F rec expansion).

**Hard caps**

- `max_queries_per_provider=50` — Phase C lints enforce this cap for both OA and S2.

**Embeddings**

- `embedding_model="text-embedding-3-small"` — Phase F (facet/meta/chunk embeddings).
- `embedding_batch_size=256` — Phase F (embedding batching).

**Stage 1 pruning**

- `prune_n1=600` — Phase F: keep top-N per lane/pool (with-abstract pool).
- `prune_n1_without_abstract=300` — Phase F: keep top-N per lane/pool (without-abstract pool); overridden by user cell `PRUNE_N1_NO_ABS`.

**S2 neighbor booster**

- `s2_neighbor_seed_count=5` — Phase F: how many seeds per lane/pool (with-abstract) for S2 Recommendations.
- `s2_recs_limit_per_seed=300` — Phase F: cap per seed.

**Rerank (Phase I)**

- `rerank_top_k_pre=40` — top-K candidates per lane/pool to rerank.
- `rerank_concurrency=20` — async concurrency.

**Match aggregation (used in F + recomputed in G)**

- `match_weight_best=0.55`, `match_weight_top_m=0.25`, `match_weight_cov=0.20`
- `match_m=3`

**Scoring constants**

- `scoring_t=0.30` — threshold for `cov` in `with_abstract` scoring (Phases F/G).
- `scoring_t_noabs=0.35` — threshold for `cov` in `without_abstract` scoring (Phases F/G).

**Authority time stratification (Phase K output selection)**

- `authority_classic_year_max=2004`
- `authority_recent_year_window=8`
- `authority_bucket_quotas={"classic": 8, "mid": 6, "recent": 6}`

Notes / gotchas:

- There is no `FORCE_REBUILD_RERANK` flag: rerank invalidation is by changing the run id, changing task hashes (content changes), or deleting `runs/<run_id>/cache/rerank/`.
- The rerank model is currently effectively hard-coded to `gpt-5-nano` in Phase I metrics (even though planner/builders use `cfg.openai_model_planner`).

---

## Appendix C — Rerun matrix (“If you change X, rerun Y”)

The notebook writes phase artifacts to `runs/<run_id>/…` and then reuses them. For a _coherent_ run, rerun from the earliest phase that _consumes_ what you changed.

Important: most tuning changes do **not** change `run_id` (only `chapter_title`, `chapter_spec_text`, and `pipeline_version` do). If you want clean separation between experiments, bump `pipeline_version` to force a new run folder.

| Change type                                                                               | Rerun (phases / notebook cells)                                                                      | Cache notes / invalidation                                                                                                                                                                                                                                                                                   |
| ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Change `chapter_title` or `chapter_spec_text`                                             | A.2 (cell 05) → B (06–09) → C (10–11) → D (12) → E (14) → F (15) → G (16) → H (17) → I (18) → K (19) | New `run_id` → new `runs/<run_id>/` folder; old artifacts remain untouched. Global embedding cache can still be reused.                                                                                                                                                                                      |
| Change `pipeline_version` only                                                            | Same as above                                                                                        | Also creates a new `run_id` by design (cache invalidation knob).                                                                                                                                                                                                                                             |
| Change planner prompt / schema / lint rules (Phase B)                                     | B (06–09) → C → D → E → F → G → H → I → K                                                            | Set `FORCE_REBUILD_QUERY_PLAN=True` or delete `runs/<run_id>/query_plan.json`. Because facets/anchors drive queries and scoring, you typically also force rebuild provider queries + retrieval for coherence.                                                                                                |
| Change query builder prompts / templates / lints (Phase C)                                | C (10–11) → D → E → F → G → H → I → K                                                                | Set `FORCE_REBUILD_PROVIDER_QUERIES=True` or delete `openalex_queries.json` + `semanticscholar_queries.json`. Old per-query retrieval caches are keyed by query hash; they’ll be bypassed naturally for new queries (but old files remain).                                                                  |
| Change retrieval settings (rate limits, pagination, field selection) (Phase D)            | D (12) → E → F → G → H → I → K                                                                       | Set `FORCE_REBUILD_RETRIEVAL=True` or delete `runs/<run_id>/cache/openalex/` + `runs/<run_id>/cache/semanticscholar/` (and optionally the aggregate `*_raw.jsonl`).                                                                                                                                          |
| Change normalization / dedup keys / merge precedence / pool split (Phase E)               | E (14) → F → G → H → I → K                                                                           | Raw caches can stay. Expect candidate ids and pool membership to change; rerank caches become irrelevant for changed ids. Consider deleting derived files: `candidates_*.jsonl`, `scores_*.jsonl`, `rankings_*.json`, `coverage_tags.jsonl`, `rerank_results.jsonl`, `output.json`.                          |
| Change pruning sizes (e.g., `PRUNE_N1_NO_ABS`, `cfg.prune_n1*`)                           | A.2 (cell 05) → F → G → H → I → K                                                                    | `PRUNE_N1_NO_ABS` does not change `run_id`; it overrides `cfg.prune_n1_without_abstract`. If you rerun only F+ you’ll overwrite shortlists/scores in-place.                                                                                                                                                  |
| Change embedding model / embedding cache logic                                            | F (15) → G → H → I → K                                                                               | Changing `cfg.embedding_model` changes vector cache namespaces. For a clean rebuild inside the same run id, delete `runs/<run_id>/embeddings_vectors/` and `runs/<run_id>/embeddings_manifest.jsonl`. Global cache in `sources-v2/embeddings_cache_global/` may also need cleanup if you want “cold” timing. |
| Change Stage 1 / Stage 2 scoring logic, thresholds, match weights (Phase F compute_match) | F (15) → G → H → I → K                                                                               | Pruning and Stage2 selection depend on Stage1 scores; rerun F to keep shortlists coherent.                                                                                                                                                                                                                   |
| Change only Phase G fusion/recompute formulas (no changes to pruning/Stage2 subset)       | G (16) → H → I → K                                                                                   | Safe only if you keep the same `shortlists_stage1.json` and the same stage1/stage2 facet score arrays. If your change would affect pruning, rerun F instead.                                                                                                                                                 |
| Change coverage tag selection / evidence fallback rules (Phase H)                         | H (17) → I → K                                                                                       | Phase H rewrites `scores_final.jsonl` (adds `coverage_tags`). Rerank task inputs include coverage tags → rerun I for coherence; caches will miss naturally when payload changes, but you can delete `cache/rerank/` to force.                                                                                |
| Change rerank prompt/schema/model or `cfg.rerank_*`                                       | I (18) → K                                                                                           | No FORCE flag exists. Delete `runs/<run_id>/cache/rerank/` to avoid mixing old/new rerank results.                                                                                                                                                                                                           |
| Change authority time stratification quotas / year cutoffs (Phase K)                      | K (19) only                                                                                          | Does not change underlying `rankings_stagei.json` ordering; only changes which authority items are selected into top‑20 buckets.                                                                                                                                                                             |
| Change output formatting / card fields only                                               | K (19) only                                                                                          | Cheapest iteration loop: keep all upstream artifacts.                                                                                                                                                                                                                                                        |

---

## Appendix D — Blueprint deltas (high signal)

This consolidates the “Blueprint alignment” notes from each phase into the most important, tuning-relevant differences between the blueprint (`TWO_LANE_PIPELINE_IMPLEMENTATION_PLAN_FROM_REPORT.md`) and what `sources_two_lane.ipynb` currently does.

- Phase J (coverage top-up) is not implemented, so all `coverage_top_up` arrays in `output.json` are always empty.
- Phase C budgeting is not implemented as the deterministic formula in the blueprint; the notebook relies on LLM-generated queries + lints and only enforces the ≤50/provider cap.
- Stage 2 per-facet chunk aggregation uses **avg(top1, top2)** chunk similarity (if ≥2 chunks) instead of pure MaxSim; this reduces “single lucky chunk” spikes but is a blueprint delta.
- S2 recommendations expansion seeds require an existing S2 `paperId` on the candidate; the “resolve DOI/arXiv/PMID → paperId for seeds” option from the blueprint is not implemented.
- Default pruning for `without_abstract` is effectively **lower** than the blueprint baseline (`prune_n1_without_abstract=300` vs blueprint’s “N1=600 per lane/pool”), which can reduce recall for metadata-only sources.
- Rerank currently uses `gpt-5-nano` (per `metrics.json`), and there is no config field or FORCE flag to switch models or invalidate rerank caches besides deleting `runs/<run_id>/cache/rerank/`.
- Full-phase timing is incomplete: Phase F and Phase G don’t wrap the entire phase with `stage_timer`, so `metrics.json` has sub-stage timings but no reliable “whole phase” duration.
- The artifact skeleton creates `embeddings_manifest.csv`, but the notebook’s embedding cache uses `embeddings_manifest.jsonl` (CSV remains empty in the example run).
- Some artifacts embed absolute Windows paths (notably in `metrics.json`, `logs.jsonl`, and `output.json.artifacts`), even though the doc uses relative `runs/<run_id>/…` paths.
- `output.json` contains extra “redundant convenience views” (`rankings`, `top`, `facets`, `run_costs`, `artifacts`, `git`) beyond the blueprint’s minimal lane-only contract.

---

## Appendix E — Example run summary (`4af2666…`)

All numbers below are from `runs/4af2666be828e5054ccf4d31/metrics.json` unless stated otherwise.

### Identity

- `run_id`: `4af2666be828e5054ccf4d31`
- `created_at_utc`: `2026-02-15T15:41:38+00:00`

### Counts (end-to-end)

- Phase C queries:
  - OpenAlex: `42`
  - Semantic Scholar: `35`
- Phase D retrieval records (raw, pre-dedup):
  - OpenAlex: `11,139`
  - Semantic Scholar: `19,618`
- Phase E candidates:
  - normalized total: `30,507`
  - deduped candidates: `25,524`
  - pools: `with_abstract=15,625`, `without_abstract=9,899`
- Phase F expanded + scoring:
  - expanded candidates: `26,922`
  - facets: `16`
  - Stage2 scored (with-abstract shortlist union): `1,133`
- Phase G shortlist carried forward into `scores_final.jsonl`:
  - unique ids: `1,686`
- Phase I rerank:
  - tasks: `160` (40 × 4 lane/pool combinations)
  - cache hits: `0`
  - failures: `0`

### Cost (OpenAI)

- Planner (Phase B): `$0.055266`
- Query builders (Phase C): `$0.060933` (OpenAlex) + `$0.047231` (S2) = `$0.108164`
- Embeddings (Phase F): `$0.048070` (facet + meta + meta_recs + chunk)
- Rerank (Phase I): `$0.160845`
- Total (sum): **`$0.372345`** (≈ `$0.3723`)

### Durations (`last_duration_s`)

| Stage                            | Duration (s) |
| -------------------------------- | -----------: |
| `phase_b_query_planner`          |      444.128 |
| `phase_c_openalex_query_builder` |      240.368 |
| `phase_c_s2_query_builder`       |      178.200 |
| `phase_d_retrieval`              |      293.554 |
| `phase_e_candidates`             |        5.516 |
| `phase_f_metadata_embeddings`    |      164.960 |
| `phase_f_stage1_scoring`         |       77.299 |
| `phase_f_s2_recommendations`     |       35.825 |
| `phase_f_chunk_embeddings`       |       52.179 |
| `phase_f_stage2_scoring`         |       25.664 |
| `phase_i_rerank`                 |      274.669 |
| `phase_k_output`                 |        0.038 |

Notes:

- Phase F has sub-stage timings above, but no single “whole Phase F” timer.
- Phase G has counts/artifact paths, but no `last_duration_s` in this run.

### Artifact size snapshot (from filesystem)

- Biggest top-level files: `openalex_raw.jsonl` `72.70 MB`, `candidates_expanded.jsonl` `54.37 MB`, `candidates_normalized.jsonl` `51.94 MB`, `semanticscholar_raw.jsonl` `44.12 MB`.
- Cache folders:
  - `cache/openalex/`: `42` files (`72.70 MB`)
  - `cache/semanticscholar/`: `35` files (`44.12 MB`)
  - `cache/rerank/`: `160` files (`311 KB`)
  - `embeddings_vectors/`: `35,391` files (`207.37 MB`)
