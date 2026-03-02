# Two-Lane Sources Search (V2) — App Integration Implementation Plan

Date: 2026-03-02

This is a hand-off ready implementation plan to **rip out** the current Quellen-Finder “paper search” pipeline and replace it end-to-end with the **two-lane pipeline** implemented in `sources-v2/sources_two_lane.ipynb`.

The notebook is the **source of truth** for all retrieval/scoring/rerank logic. The integration work must preserve output equivalence (same rankings/results) while:

- extracting notebook code into production Python modules,
- removing *read-time* caching (always run from scratch),
- adding per-run model settings,
- persisting **top-40 results per lane/pool** to Firestore,
- persisting **proxy telemetry** for plots and run inspection,
- supporting **cancellation** and **concurrent runs**,
- enforcing an OpenAI hard budget cap of **$2.00/run**,
- writing local-only artifacts (dev only), retaining max 10 runs.

---

## 0) Scope

### In scope

- Backend (FastAPI):
  - New start + cancel endpoints for two-lane sources runs.
  - New background job that runs the extracted two-lane pipeline.
  - Firestore persistence for:
    - results: `4 lane/pool combos × top 40 = 160 docs/run`
    - telemetry: small set of “proxy” docs per run for plots + run summary
  - Cancellation via Firestore flag (polled at phase boundaries).
  - Budget cap enforcement ($2.00 OpenAI spend/run).
  - Local dev artifacts (optional), retain latest 10.
  - Remove the old sources-search pipeline (no longer callable).

- Frontend (Next.js):
  - New Quellen-Finder UI that exposes:
    - lanes: `match` and `authority`
    - pools: `with_abstract` always visible; `without_abstract` behind a toggle
    - sorting and filtering (client-side)
    - compact table + “details dialog” per paper
    - run summary + plots (from telemetry docs)
    - cancel button for running jobs
  - Replace old sources-search UI usage; do not reuse the old table layout.

### Out of scope (explicitly)

- No “Add as Quelle” / extraction / ingestion into your Quellen manager.
- No changes to pipeline logic/scoring; **no “fix list” items** beyond what the notebook already does.
- No production artifact storage (Cloud Run should not persist artifacts).
- No cross-run caching in prod (providers/embeddings/rerank all from scratch).

---

## 1) Reference implementation (source of truth)

- Pipeline notebook: `sources-v2/sources_two_lane.ipynb`
- Supporting docs (for understanding only; notebook still wins):
  - `sources-v2/PHASE_F_AND_G_DEEP_DIVE.md`
  - `sources-v2/TWO_LANE_PIPELINE_CHEATSHEET.md`
  - `sources-v2/TWO_LANE_PIPELINE_FIXES.md` (do **not** implement extra items right now)

---

## 2) Current system (what gets replaced)

### Frontend

- `app/components/quellen-finder/QuellenFinder.tsx`
  - Starts old run via `POST ${FASTAPI}/api/quellen-finder/sources-search`
  - Displays old results from Firestore subcollection `sourcesResults`

### Backend

- FastAPI route: `fastapi/main.py` → `POST /api/quellen-finder/sources-search`
- Job: `fastapi/services/quellen_finder_sources_job.py`
- Old pipeline code: `fastapi/services/quellen_finder_sources_service.py` + `fastapi/services/quellen_finder_sources_pipeline.py`

### Firestore

- Runs live under: `users/{uid}/projects/{projectId}/researchRuns/{runId}`
- Client can read researchRuns but cannot write (per `firestore.rules`); server writes with admin SDK.

---

## 3) Target architecture (high level)

### 3.1 Firestore layout (server-owned, user-readable)

Keep using `projects/{projectId}/researchRuns/{runId}` and add two subcollections:

- `twoLaneResults` — final top-40 results per lane/pool (160 docs)
- `twoLaneTelemetry` — per-run proxy telemetry for summary + plots (small number of docs)

Why this structure:

- matches `firestore.rules` best practice: research runs are server-owned artifacts
- avoids Firestore 1 MiB doc limit (results stored as many small docs)
- avoids DB blow-up even if retrieval pulls 50k+ records (store **aggregates only**)

### 3.2 Backend execution model

For now: implement exactly like existing background jobs (`BackgroundTasks`).

Important (Cloud Run note): this pattern can be unreliable on Cloud Run unless configured (CPU allocation, request lifecycle). For local dev it’s fine; plan a follow-up to move long jobs to Cloud Tasks / PubSub / Cloud Run Jobs once behavior is verified.

### 3.3 “No caching” interpretation (must-follow)

- No *read-time* caches: do not skip phases based on saved files.
- Artifacts may be written (dev-only) for inspection but are **write-only** and never used to short-circuit compute.

---

## 4) Firestore contract (detailed)

### 4.1 Run doc: `.../researchRuns/{runId}`

Create a new `kind` to avoid mixing with legacy runs:

- `kind = "sources_two_lane"`

Run status enum must include:

- `queued` | `running` | `success` | `error` | `cancelled`

Recommended fields (minimum viable):

- Identity:
  - `kind`, `status`, `projektId`, `kapitelIds[]`, `kapitelSnapshots[]`
  - `createdAt`, `updatedAt`, `startedAt`, `finishedAt`
- Per-run settings (persist what was used):
  - `twoLaneSettings.models.planner`
  - `twoLaneSettings.models.openalex_query_builder`
  - `twoLaneSettings.models.s2_query_builder`
  - `twoLaneSettings.models.rerank` (only `gpt-5-nano` or `gpt-5-mini`)
  - `twoLaneSettings.models.embedding` (e.g. `text-embedding-3-small|text-embedding-3-large`)
- Progress:
  - `progress.stage` (string, e.g. `phase_d_retrieval`)
  - `progress.message`
  - `progress.current`, `progress.total` (optional)
- Cancellation:
  - `cancelRequestedAt: Timestamp|null`
  - `cancelledAt: Timestamp|null`
- Error:
  - `errorMessage: string|null` (trim to <=1000 chars)
- Headline run summary (small):
  - `summary.counts` (provider record totals, candidates totals, stage2 scored, rerank tasks)
  - `summary.costUsd.total`, `summary.costUsd.byStage`
  - `summary.timeS.byStage`

### 4.2 Results subcollection: `.../researchRuns/{runId}/twoLaneResults/{resultId}`

Write exactly **top 40** per lane/pool, after the pipeline fully completes.

Doc id strategy (recommended; deterministic, no indexes needed):

- `{lane}__{pool}__{rank3}` (e.g. `match__with_abstract__001`)

Fields (store only what UI needs; trim heavy strings):

- `lane`: `"match" | "authority"`
- `pool`: `"with_abstract" | "without_abstract"`
- `rank`: `1..40`
- `id`: canonical id (DOI preferred; matches notebook output)
- `doi`, `title`, `authors[]`, `year`, `venue`, `url`, `language`
- `abstract`: string trimmed to **5000 chars**
- `citations`, `influential_citations` (if available)
- `provider`, `provider_ids`, `external_ids`, `sources[]` (optional; helpful for debugging)
- `scores`: (mirror notebook `output.json` card `scores`)
  - `match`, `authority`, `match_lane`, `authority_lane`, `best`, `top_m`, `cov`
- `coverage_tags[]`: list of:
  - `facet_id`, `score`, `excerpt` (already short; keep)
  - Do **not** duplicate facet labels here; resolve via telemetry facet table.
- `rerank` (if present; all strings trimmed):
  - `llm_score_0_100`
  - `covered_facets[]`
  - `rationale`: string trimmed to **5000 chars**
  - `insufficient_info`
- `createdAt`: Timestamp

### 4.3 Telemetry subcollection: `.../researchRuns/{runId}/twoLaneTelemetry/{docId}`

Goal: enable a “run report UI” with plots without storing raw records/candidates.

Store small aggregated “proxy” datasets:

- histograms (1D) and heatmaps (2D) instead of raw point clouds
- top-N preview tables instead of full candidate lists
- query-level counts (≤50/provider) instead of record-level data

Recommended docs:

1) `plan`
2) `queries_openalex`
3) `queries_s2`
4) `phase_d`
5) `phase_e`
6) `phase_f`
7) `phase_g` (light)
8) `final_report`

---

## 5) API contract

### 5.1 Start run

Add a new route (recommended):

- `POST /api/quellen-finder/sources-two-lane/start` → `202 Accepted`

Request body (Pydantic):

```json
{
  "projekt_id": "…",
  "kapitel_id": "…",
  "models": {
    "planner": "gpt-5-mini",
    "openalex_query_builder": "gpt-5-mini",
    "s2_query_builder": "gpt-5-mini",
    "rerank": "gpt-5-nano",
    "embedding": "text-embedding-3-small"
  }
}
```

Validation rules:

- `rerank` must be `gpt-5-nano` or `gpt-5-mini` (reject `gpt-5.2`)
- other model fields must be valid known strings (keep allowlist small initially)

Response:

```json
{ "status": "queued", "run_id": "...", "projekt_id": "...", "kapitel_id": "...", "queued_at": "..." }
```

Concurrency: allow multiple concurrent runs (remove “already running” guard).

### 5.2 Cancel run

- `POST /api/quellen-finder/sources-two-lane/cancel` → `200 OK`

Body:

```json
{ "projekt_id": "...", "run_id": "..." }
```

Server action:

- set `cancelRequestedAt = SERVER_TIMESTAMP` on the run doc
- if status is terminal (`success|error|cancelled`), return idempotent “already finished”

---

## 6) Backend implementation plan (step-by-step)

### 6.1 Extract the notebook into a Python module

Create a new package, e.g.:

- `fastapi/services/two_lane_sources/`
  - `pipeline.py` (orchestrator)
  - `providers_openalex.py`
  - `providers_semanticscholar.py`
  - `openai_calls.py` (Responses API + embeddings wrappers)
  - `telemetry.py` (hist/heatmap builders + top-N tables)
  - `artifacts.py` (dev-only artifact writing + retention)
  - `types.py` (Pydantic models for settings + internal structs)

Extraction strategy:

- Use the notebook as the canonical logic; port functions with minimal changes.
- Keep phase boundaries conceptually identical (B/C/D/E/F/G/H/I/K).
- Remove any “FORCE_REBUILD_*” and cache-hit logic; compute every time.

### 6.2 Budget cap enforcement ($2.00 OpenAI spend/run)

Rules:

- Track `openai_cost_usd_so_far` as the sum of **actual** costs from completed OpenAI calls.
- After each OpenAI call, if `openai_cost_usd_so_far > 2.00`, mark run `error` and stop before the next OpenAI call.
- Before starting rerank, do a safety pre-check using an estimate:
  - `gpt-5-nano` rerank estimate ~ `$0.30/run`
  - `gpt-5-mini` estimate should be scaled based on pricing (use `CostService.resolve_model_pricing` ratio)
  - If `openai_cost_usd_so_far + rerank_estimate > 2.00`, error out **before** launching rerank tasks.

Error behavior for budget breach:

- Option B: **delete partial outputs**.
  - Implementation recommendation: do not write `twoLaneResults` / `twoLaneTelemetry` until the very end of a successful run. Then budget errors automatically produce zero output docs.
  - Always write a useful `errorMessage` to the run doc.

### 6.3 Cancellation

Mechanism:

- `cancelRequestedAt` on run doc indicates cancellation requested.
- Pipeline checks for cancellation:
  - after each phase completes
  - before launching expensive sub-steps (embeddings batches, rerank batches)

Cancellation behavior:

- Stop early, mark run status `cancelled`, set `cancelledAt`, set progress `stage="cancelled"`.
- Do not write results/telemetry (consistent with “write only on success”).

### 6.4 Local dev artifacts (write-only, keep last 10)

Requirement:

- Write artifacts inside `fastapi/` (dev only).
- Retain max **10** run folders; delete older completed ones.
- Must not delete in-progress runs.

Recommendation:

- Root: `fastapi/.two_lane_artifacts/<runId>/`
- Enable via env var: `TWO_LANE_ARTIFACTS=1` (default off)
- Add an in-progress marker file (e.g. `.in_progress`) that is removed on terminal state.
- Cleanup rule: keep newest 10 directories **without** `.in_progress`.

Artifacts to write (dev only; do not use for caching):

- `query_plan.json`
- `openalex_queries.json`
- `semanticscholar_queries.json`
- `metrics.json` (stage timings/costs/counts)
- `output.json` (notebook-like consumer output)
- optional: `rankings_stagei.json` (if produced)

### 6.5 Firestore writing strategy (efficient + safe)

- While running: only update the run doc (status/progress).
- On success:
  - write `twoLaneResults` (160 docs) + `twoLaneTelemetry` (≈8 docs) in batched commits (<=500 writes/commit).
  - mark run doc `success` with summary fields.

---

## 7) Telemetry spec (exactly what to store)

This maps your requested “what happened inside the run” data to efficient Firestore storage.

### 7.1 `plan` doc (Facets + global term previews)

Store:

- `facets[]`: `{ facet_id, facet_label_en, facet_label_de, facet_type, importance_weight }`
- `primary_context_anchors`: `{ en[], de[] }`
- `global_canonical_terms`: `{ en[], de[] }`
- `global_exclusions`: `{ en[], de[] }`

### 7.2 `queries_openalex` + `queries_s2`

Store:

- `queries[]` with stable ids:
  - OpenAlex: `oa_000..oa_049`
  - S2: `s2_000..s2_049`
- For each query:
  - `{ query_id, intent, language, query_string, filters/search_field (OA), notes }`

Also store query string length distribution:

- `query_len_chars_hist.openalex` and `.s2`:
  - `{ bin_edges[], counts[] }` + `{min, p50, p95, max}`

### 7.3 `phase_d` doc (retrieval)

Store:

- Provider summary:
  - `openalex.records_total`, `openalex.query_failed`, `openalex.queries_total`
  - `s2.records_total`, `s2.query_failed`, `s2.queries_total`
- Records by intent/lang (2×2 table per provider):
  - `records_by_intent_lang.openalex.{match|authority}.{en|de} = count`
  - same for `s2`
- Query-level counts (≤50/provider):
  - `per_query_counts.openalex[]`: `{ query_id, record_count, failed, zero_results }`
  - `per_query_counts.s2[]`: same
- Zero-result query ids:
  - `zero_result_query_ids.openalex[]`, `.s2[]`
- Year distribution of retrieved records:
  - `year_counts.openalex.{year:int => count:int}`
  - `year_counts.s2.{year:int => count:int}`

Plot enablement:

- “records per query” bar chart uses `per_query_counts`.
- “year distribution” uses `year_counts`.

### 7.4 `phase_e` doc (candidates)

Store:

- “At a glance” (directly from notebook logic):
  - record totals, normalized_total, deduped_candidates, merges, shares, filters, pool counts, doi share, year-missing share
- “Counts by lane/pool”:
  - list of `{ lane: match|authority|both|unknown, pool, n }`
- “Top cited but NO anchors” (top 20):
  - list of `{ id, doi, title_trunc, year, cites, pool, sources[] }`
- “Top econ-hit candidates” (top 20):
  - list of `{ id, doi, title_trunc, year, cites, econ_hits, anchor_hit, pool }`

### 7.5 `phase_f` doc (embeddings + scoring)

Store:

- “At a glance” values:
  - embedding model, batch size, facets, candidates, stage2_candidates, stage2_scored, embedding cost estimate, thresholds
- Anchor hit rate (top20) table:
  - list of `{ lane, pool, hit, total, pct }`
- Coverage diagnostics (required facets, top20):
  - list of `{ lane, pool, facet_id, weight, covered_n, covered_pct }`
  - list of missing required facets per lane/pool
- Top preview tables per lane/pool (store small, e.g. top 12):
  - minimal columns for UI: `{rank, id, title_trunc, year, cites, match_lane, authority_lane, anchor_hit, top_facets_str}`

Plots (proxy data):

- Lane score histograms (store as hists, not per-candidate scores):
  - `hists.match_lane.with_abstract`, `.without_abstract`
  - `hists.authority_lane.with_abstract`, `.without_abstract`
- Match vs authority 2D heatmap:
  - `heatmaps.match_vs_authority.with_abstract`: `{ x_edges[], y_edges[], counts_flat[] }`
  - optional: same for `without_abstract`
- Citation distribution hist:
  - `{ bin_edges[], counts[] }` (consider log-binning)

### 7.6 `phase_g` doc (light)

Store:

- Anchor hit rates (top20) (mirrors notebook Phase G)
- Any “counts” that are cheap and helpful:
  - unique ids scored in `scores_final`
  - lane/pool shortlist sizes

### 7.7 `final_report` doc (what user sees after run completes)

Store:

- Models used by stage:
  - `{ planner, openalex_query_builder, s2_query_builder, embedding, rerank }`
- Time per stage (seconds):
  - `{ phase_b, phase_c_openalex, phase_c_s2, phase_d, phase_e, phase_f, phase_g, phase_h, phase_i, phase_k }`
- Cost per stage + total (USD):
  - same keys; include token totals if available

Plots:

- “papers vs lane score”:
  - can be derived from `twoLaneResults` (top40), but also store lane hists for clarity.
- “lane score vs rank”:
  - derive from `twoLaneResults`.
- “papers vs year/cites/tags”:
  - derive from `twoLaneResults` + store citation/year hists for context.
- Rerank:
  - `rerank_score_hist.{with_abstract,without_abstract}` (from reranked tasks)
  - `rerank_vs_lane_points[]` (≤160 points):
    - `{ lane, pool, lane_score, llm_score_0_100 }`

---

## 8) Frontend/UI implementation plan

### 8.1 Replace Quellen-Finder sources UI

Goal: a modern responsive UX that does not horizontally overflow on small screens.

Recommended structure:

- Keep route: `app/(protected)/quellen-finder/page.tsx`
- Replace component implementation:
  - Create a new component (e.g. `app/components/quellen-finder/TwoLaneQuellenFinder.tsx`)
  - Either delete or fully deprecate the old sources-search portion of `QuellenFinder.tsx`

### 8.2 UX requirements (must-have)

- Lanes exposed: Match / Authority (Tabs)
- Pools:
  - With-abstract always available
  - Without-abstract behind a toggle (“Show without-abstract”)
- Sorting + filtering:
  - default: `rank asc`
  - allow: lane score, rerank score, year, cites
  - filtering by title/authors/venue/doi
- Results table:
  - compact columns (no giant raw JSON column)
  - click row opens a details dialog
- Details dialog:
  - Summary + link (DOI/URL)
  - Abstract (trimmed)
  - Coverage tags (facet refs + excerpts)
  - Rerank score + rationale (trimmed)
- Run report view:
  - headline counts, timings, costs (total + by phase)
  - plots from `twoLaneTelemetry/*`
- Cancel button for running runs

### 8.3 Suggested UI layout

- Header: chapter selection + “Start run” button + status badge + cancel
- Settings panel (per-run):
  - planner model
  - OpenAlex query builder model
  - S2 query builder model
  - rerank model (nano/mini only)
  - embedding model
  - (keep everything else fixed to notebook defaults for now)
- Main:
  - Tabs: `Results` | `Run report`
  - Results: lane tabs + pool toggle + search + sort controls + table
  - Run report: summary cards + charts

### 8.4 Charts

No chart library is currently included. Decide one:

- Recommended: `recharts` (simple, good enough for hist/line/scatter/heatmap-like via custom)
- Alternative: `chart.js` + `react-chartjs-2`

The telemetry contract is designed to work with any of these.

---

## 9) Validation & “done when”

### Output equivalence (critical)

For a fixed chapter input + model settings:

- The integrated backend produces the same top results as the notebook:
  - same ids in `top 40` per lane/pool
  - same ordering (ranks)
  - same lane scores and rerank outputs (within normal nondeterminism only where the notebook is nondeterministic)

### Backend acceptance

- Starting a run creates a run doc with `kind="sources_two_lane"`.
- Multiple concurrent runs are possible.
- Cancel sets `cancelRequestedAt`; job ends with `status="cancelled"`.
- No results/telemetry are written until the pipeline finishes successfully.
- Abstract/rationale strings are trimmed to <=5000 chars.
- Budget cap:
  - if OpenAI spend exceeds $2, run ends with `status="error"` and no result docs exist.
  - rerank is blocked if remaining budget is too low.
- Dev artifacts:
  - written only when enabled
  - stored under `fastapi/.two_lane_artifacts/`
  - only last 10 completed runs retained

### Frontend acceptance

- UI is responsive on small screens (no required horizontal scrolling).
- Lanes/pools are usable and discoverable.
- Table is compact; details are in dialog.
- Run report shows meaningful counts/costs/timing + plots.

---

## 10) Implementation work breakdown (suggested order)

1) Backend: new Firestore schema + types + writer helpers
2) Backend: pipeline extraction into `fastapi/services/two_lane_sources/*`
3) Backend: start + cancel endpoints + background job wiring
4) Backend: budget enforcement + cancellation checks
5) Backend: telemetry builders + Firestore writes on success
6) Backend: dev artifact writer + retention cleanup
7) Frontend: new responsive Quellen-Finder UI
8) Frontend: telemetry-driven run report + charts
9) Remove legacy sources-search endpoint/UI and confirm no references remain

