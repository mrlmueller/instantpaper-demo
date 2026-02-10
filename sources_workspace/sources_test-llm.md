# `sources_test-llm.ipynb` — cell-by-cell pipeline walkthrough

This document explains what each cell in `sources_test-llm.ipynb` does, what files/data it produces, and how that output is consumed by later stages. It’s written at a “high → mid” level so you can reproduce the pipeline conceptually (even if you change parameters/models later).

---

## What this notebook is

The notebook implements an end-to-end “sources pipeline” for one or more chapter/topic texts:

1. **Stage B**: build a _chapter blueprint_ + _year bounds_ + an _API query plan_ (LLM-generated, cached).
2. **Stage A**: execute the query plan against **OpenAlex** and **Semantic Scholar**, merge/dedupe into a per-chapter corpus (cached).
3. **Stage C**: build a candidate pool and compute _offline_ relevance scores (TF‑IDF + embeddings + authority heuristics) (cached).
4. **Stage C.3**: use an LLM to rerank a small shortlist (top‑N) (cached).
5. **Stage D**: choose a diverse final top‑K using MMR over TF‑IDF similarity (offline).
6. **Final run**: export CSVs + a run summary and print diagnostics.

Key design principle: **cache everything expensive** (LLM + APIs + embeddings), and use signatures/prompt versions so caches automatically invalidate when inputs change.

---

## Prerequisites / configuration (very important)

Required:

- `OPENAI_API_KEY` (Stage B, embeddings in Stage C, LLM rerank in Stage C.3).

Optional but strongly recommended:

- `OPENALEX_API_KEY` (OpenAlex allows unauthenticated requests, but keys reduce friction/rate limits).
- `SEMANTICSCHOLAR_API_KEY` (without a key, Semantic Scholar can rate-limit heavily and become very slow).

The notebook loads a `.env` at the repo root (if present) and does minimal dependency checks.

---

## Output layout & caching strategy

All pipeline outputs go under:

`sources_workspace/final_pipeline/`

### Stage B (blueprints & query plans)

`final_pipeline/stageB_blueprints/`

- `blueprint_v3/<chapter_id>.json`
- `year_bounds_v2/<chapter_id>.json`
- `query_plan_service_agents_v1/<chapter_id>.json`
- `gapfill_v2/<chapter_id>.json` (if enabled/used)

These JSONs include a `_meta` section with `prompt_version` / `created_at_utc` so the notebook can detect stale caches.

### Stage A (API retrieval)

`final_pipeline/stageA/<chapter_id>/<sig>/`

- `openalex.csv` (raw-ish OpenAlex rows for that chapter)
- `semantic_scholar.csv` (raw-ish S2 rows for that chapter)
- `stageA_combined.csv` (merged, deduped corpus used downstream)
- `openalex_concepts.json` (concept lookup/debug)
- Semantic Scholar extras (for resumability/caching):
  - `semantic_scholar.progress.json`
  - `semantic_scholar.abstracts.json`

The `<sig>` is a SHA1 hash of the **query plan + Stage A knobs**. If anything relevant changes, the signature changes and a new folder is created.

### Stage C (pool + scoring)

`final_pipeline/stageC/<chapter_id>/<sig>/stageC_pool_scored.csv`

Plus a combined “all chapters” file:
`final_pipeline/stageC/<RUN_ID>_stageC_all_pool_scored.csv`

Embeddings are cached separately:
`sources_workspace/.embed_cache/`

- `eval_doc_embeds_<model>_<hash>.npz`
- `eval_query_embeds_<model>_<hash>.json`

### Stage C.3 (LLM rerank cache)

`final_pipeline/stageC3_rerank_cache_v1/<rubric_sig>/<chapter_id>/<doc_sig>.json`

The rubric signature depends on the chapter blueprint rubric fields + prompt version + model.

### Final exports

`final_pipeline/results/`

- `<RUN_ID>_full_scored.csv` (everything with all scores/signals)
- `<RUN_ID>_<chapter_id>_top30.csv` (per-chapter top‑30, with query attribution)
- `<RUN_ID>_<chapter_id>_query_productivity_top30.csv` (per-chapter query productivity summary)
- `<RUN_ID>_top30_all_chapters.csv` (global top‑30 across chapters)
- `<RUN_ID>_run_summary.json` (concise machine-readable summary: paths + knobs + costs)

---

## Data objects (mental model)

You’ll see these concepts repeatedly:

- **Chapter spec** (input): `{chapter_id, title, original_text_language, original_text, ...}`
- **Blueprint** (Stage B output): a structured “search strategy” (scope, facets, anchors, negatives, guidance).
- **Query plan** (Stage B output): a list of API queries with metadata and filters:
  - `service`: `openalex` or `semanticscholar`
  - `kind`: `anchor|facet|proxy|authority`
  - `language`: `en|de`
  - `cap`: max works/papers to fetch
  - `use_no_year`: whether to omit year filters
  - `filters`: `{year_min, year_max, language, concept_ids}`
  - `query`: the actual query string (dialect-specific)
- **Stage A corpus**: merged/deduped records with:
  - a stable `merge_key`
  - merged title/abstract/doi/year/venue/citations
  - provenance fields `sources`, `queries`, `query_ids`, etc.
- **Stage C pool**: Stage A corpus + scoring columns (`score_tfidf`, embedding scores, citation signals, final score).
- **Stage C.3 output**: Stage C pool + LLM label/score/confidence on the shortlist + a calibrated final ordering column.
- **Stage D output**: Stage C.3 output + an MMR-selected diverse top‑K signal.

---

## Execution order (recommended)

Run the notebook top-to-bottom:

1. Config → 2) Stage B → 3) Stage A → 4) Stage C weights → 5) Stage C → 6) Stage C.3 → 7) Stage D → 8) Final run

You can re-run later stages without recomputing earlier ones because all the heavy work is cached to disk.

---

## Cell-by-cell explanation

### Cell 0 (markdown) — Intro / status (`id=sf_intro`)

**Purpose**

- Human-facing note about what stages are considered “finalized” and what this notebook contains.

**Produces**

- No data; documentation only.

**Used by later**

- Not used programmatically.

---

### Cell 1 (code) — Config + chapter inputs (`id=sf_config`)

**Purpose**

- Validate environment and dependencies, set up output directories, define chapter inputs, and print a config summary.

**Core actions**

- Loads `.env` from repo root (minimal loader).
- Requires `OPENAI_API_KEY`.
- Defines output dirs:
  - `OUT_DIR = sources_workspace/final_pipeline/`
  - `STAGEB_DIR`, `STAGEA_DIR`, `STAGEC_DIR`, `RESULTS_DIR`
- Defines `CHAPTERS` (the list of topics to process) and normalizes it:
  - ensures `chapter_id`, `title`, `original_text_language`, `original_text` exist
  - generates stable-ish ids if missing

**Produces (in-memory)**

- `CHAPTERS`: normalized chapter specs
- `RUN_ID`: timestamp string used in export filenames
- helpers: `print_section`, `print_table`, plotting helpers, model price table

**Used by later**

- Every stage loops over `CHAPTERS`.
- Every stage writes to `OUT_DIR` subfolders.

---

### Cell 2 (markdown) — Stage B header (`id=sf_stageB_header`)

Just a section divider + short note about Stage B being finalized.

---

### Cell 3 (code) — Stage B: blueprint + year bounds + per-API query plans (`id=sf_stageB_build`)

**Purpose**

- For each chapter: generate and cache
  1. a structured **BlueprintV3**
  2. **YearBoundsV2** (soft min/max year + “no year” policy)
  3. a **QueryPlanV2** using **two service-specific LLM agents**:
     - one specialized for OpenAlex Works API query dialect
     - one specialized for Semantic Scholar `paper/search`

**Core actions**

- Defines Pydantic models:
  - blueprint + anchors + facets
  - year bounds policy
  - query plan objects (service, kind, caps, filters, etc.)
- Defines prompt templates for:
  - `blueprint_v3`
  - `year_bounds_v2`
  - `query_plan_service_agents_v1` (OpenAlex + Semantic Scholar)
  - `gapfill_v2` (optional refinement step)
- Creates Agents SDK `Agent`s that return JSON validated against the models.
- Implements caching:
  - reads `final_pipeline/stageB_blueprints/<stage>/<chapter_id>.json`
  - validates schema + `prompt_version` before using cache
- Query planning details:
  - Each service agent is instructed with that API’s dialect rules.
  - Output is **auto-fixed** (dedupe, sanitize, clamp caps, fix facet_ids/filters/years).
  - Validation is intentionally **lenient**: the plan is allowed to have fewer than the target count if queries are good.

**Produces (on disk)**

- Stage B JSON caches per chapter under `final_pipeline/stageB_blueprints/...` (see “Output layout” above).

**Produces (in-memory)**

- `blueprints`: `Dict[chapter_id -> ChapterBlueprint]` (compat object consumed by later stages)
- `blueprint_v3_by_chapter`, `year_bounds_v2_by_chapter`, `query_plans_by_chapter`: full structured objects
- usage/cost summaries for Stage B LLM calls (`bp_totals`, etc.)

**Used by later**

- Stage A uses `query_plans_by_chapter` to actually hit OpenAlex/S2.
- Stage A and Stage C use `blueprints[chapter_id]` to:
  - build concept-term lists for OpenAlex concept filtering
  - build TF‑IDF/embedding query text
  - apply negative-term soft downranking and rubric guidance
- Stage C.3 uses `blueprints` as the per-chapter scoring rubric.

---

### Cell 4 (markdown) — Stage A header (`id=92454089`)

Section divider for API retrieval.

---

### Cell 5 (code) — Stage A: OpenAlex + Semantic Scholar retrieval + merge (`id=146b3405`)

**Purpose**

- Execute the Stage B query plan against OpenAlex and Semantic Scholar.
- Merge and dedupe results into a per-chapter corpus used by Stage C.

**Core actions**

1. **OpenAlex fetch**
   - Uses `https://api.openalex.org/works` with cursor pagination.
   - Applies filters for language and year bounds (unless `use_no_year`).
   - Optional concept filtering:
     - looks up OpenAlex concept IDs from blueprint terms
     - applies the concept filter to some queries (by kind/share) to avoid overly broad pulls.
   - Query placement is configurable via `OA_QUERY_MODE`:
     - `search` (recommended): query goes in `search=...`, filters go in `filter=...`
     - legacy `title_and_abstract_filter`: query is embedded into `filter=title_and_abstract.search:...` (very restrictive)

2. **Semantic Scholar fetch**
   - Uses `https://api.semanticscholar.org/graph/v1/paper/search`
   - Sanitizes queries to avoid boolean/punctuation that S2 doesn’t like.
   - Has request caching + long backoff/retry logic (S2 is rate-limited without an API key).
   - Optionally fetches abstracts via `paper/batch` to enrich results.

3. **Merge + dedupe**
   - Standardizes OpenAlex and S2 records into a common schema.
   - Dedupes within source and across sources (DOI/title-based keys).
   - Produces one merged record per `merge_key`.
   - Aggregates provenance:
     - `queries`, `query_ids`, `query_kinds`, `query_services`, `query_languages`

4. **Diagnostics**
   - Builds a “per query” table with `raw_hits_openalex`, `raw_hits_s2`, `raw_hits_total`
   - Tracks how many final records were retrieved by each query (`stageA_hits`, `stageA_unique_hits`, share).

**Produces (on disk)**
Per chapter, per signature:

- `final_pipeline/stageA/<chapter_id>/<sig>/openalex.csv`
- `final_pipeline/stageA/<chapter_id>/<sig>/semantic_scholar.csv`
- `final_pipeline/stageA/<chapter_id>/<sig>/stageA_combined.csv`

**Produces (in-memory)**

- `stageA_by_chapter[chapter_id] = df_stageA` (merged corpus)
- `stageA_stats` and the printed summary table

**Used by later**

- Stage C loads `stageA_combined.csv` (or uses `stageA_by_chapter` if already in memory).
- Final run uses Stage A provenance columns for “query attribution”.

---

### Cell 6 (markdown) — Stage C weights header (`id=sf_stageC_header`)

Section divider explaining that Stage C weights were chosen via prior experiments.

---

### Cell 7 (code) — Stage C finalized scoring weights (`id=sf_stageC_scoring`)

**Purpose**

- Defines the _final_ Stage C scoring function used later in the Stage C production cell.

**Core actions**

- Declares the finalized weights:
  - `STAGEC_W_EMBED_MAX`, `STAGEC_W_EMBED`, `STAGEC_CITE_WEIGHT`
- Defines helpers:
  - `minmax_by_group()` — normalize within chapter
  - `add_stagec_final_scores()` — compute `score_stageC_final` from:
    - embedding-based relevance (max/breadth combo)
    - TF‑IDF similarity
    - authority/citation normalization

**Produces**

- Functions used directly in the Stage C production cell.

**Used by later**

- Cell 9 calls `add_stagec_final_scores()` to populate `score_stageC_final`.

---

### Cell 8 (markdown) — Stage C production header (`id=a5885f56`)

Section divider describing that Stage C writes scored pools to `final_pipeline/stageC/`.

---

### Cell 9 (code) — Stage C: pool building + embeddings + scoring (cached) (`id=09965995`)

**Purpose**

- Turn the Stage A corpus into a _scored candidate pool_ for each chapter.

**Core actions**

1. Load Stage A corpus:
   - Uses in-memory `stageA_by_chapter[cid]` if available
   - Otherwise loads the newest `final_pipeline/stageA/<cid>/*/stageA_combined.csv`

2. Build `doc_text` per record:
   - `title + "\n\n" + abstract`

3. Compute “authority” signals (citations):
   - robust citation normalization (log + clipped minmax)
   - citation velocity (citations per age) blended into `score_cite_norm`

4. Compute TF‑IDF relevance per chapter:
   - fit a `TfidfVectorizer` on all `doc_text`
   - compute cosine similarity of a “chapter query text” (blueprint main query + facets + keywords) → `score_tfidf`

5. Candidate pool via **facet-union**
   - For main query + each facet query:
     - take top‑`TOP_PER_QUERY` docs by TF‑IDF similarity
   - Union those docs into a smaller pool (improves efficiency for embeddings).

6. Compute embedding relevance (cached):
   - Embeds truncated doc text (`MAX_CHARS_PER_EMBED`) and query texts using `text-embedding-3-small`.
   - Caches embeddings under `sources_workspace/.embed_cache/`.
   - Produces embedding-based scores:
     - `score_embed_max`, `score_embed_mean_top3`, plus normalized variants.

7. Combine into finalized Stage C score:
   - Calls `add_stagec_final_scores()` to add `score_stageC_final`.
   - Applies lightweight quality adjustments:
     - multi-source boost, missing-abstract penalty
     - survey/review/standard title boost
     - peer-reviewed/preprint soft preference
     - venue blocklist penalty (config-driven)
     - blueprint negative-term soft penalty

8. Persist outputs:
   - writes `final_pipeline/stageC/<cid>/<sig>/stageC_pool_scored.csv`
   - writes combined `final_pipeline/stageC/<RUN_ID>_stageC_all_pool_scored.csv`

**Produces**

- Per-chapter scored pools (CSV) + combined pool (CSV)
- In-memory: `stageC_by_chapter`, `stageC_all`, `embed_totals` (embedding cost tracking)

**Used by later**

- Stage C.3 rerank takes `stageC_all` and reorders a shortlist.
- Final run loads the latest combined Stage C CSV if `stageC_all` isn’t in memory.

---

### Cell 10 (code) — Stage C.3: LLM shortlist rerank (cached) (`id=sf_stageC3_final`)

**Purpose**

- Use an LLM only where it helps: _rerank within a shortlist_ instead of rewriting/overhauling retrieval.

**Core actions**

- Defines a small schema output (`label`, `score`, `confidence`, `notes`) and an LLM prompt that uses the chapter blueprint as rubric.
- Selects the per-chapter top‑N by `score_stageC_final` and reranks them via LLM judgments.
- Adaptive expansion:
  - If the top‑N contains too many `exclude` labels, it expands the shortlist in chunks until it has enough `{include, maybe}` items for Stage D to pick a final top‑20.
- Caching:
  - Each doc’s judgment is cached under `final_pipeline/stageC3_rerank_cache_v1/…`
  - The cache key depends on a rubric signature so changes to rubric/prompt/model invalidate caches.
- Produces a calibrated ordering column:
  - `score_stageC3_topn_final` is designed so that:
    - high-confidence `{include, maybe}` items dominate the top ranks
    - everything else falls back to Stage C score ordering

**Produces**

- In-memory: `stageC3_df` (Stage C pool + LLM fields)
- In-memory: `stageC3_totals` (cost/time summary)
- On disk: per-doc rerank cache JSON files

**Used by later**

- Stage D uses Stage C.3 outputs to:
  - avoid selecting unlabeled tail items
  - use an LLM-derived relevance signal for MMR selection
- Final run exports top‑30s and a cost summary including Stage C.3.

---

### Cell 11 (markdown) — Stage D header (`id=sf_stageD_header`)

Section divider describing the final diversity selection step.

---

### Cell 12 (code) — Stage D: TF‑IDF MMR diversity selection (offline) (`id=sf_stageD_code`)

**Purpose**

- Reduce redundancy in the final list while preserving relevance.

**Core actions**

1. Build a Stage D relevance signal:
   - For docs scored by Stage C.3 and not excluded:
     - `score_stageC3_signal_v1 = 1 + minmax(llm_score) + small_authority_boost`
   - For everything else:
     - fallback to Stage C score

2. MMR selection over TF‑IDF similarity:
   - Consider top‑M items (default `STAGED_TOPM=100`) from the Stage C.3 shortlist.
   - Build TF‑IDF vectors of (title + abstract) for the pool.
   - Run Maximal Marginal Relevance (MMR) to pick `k_select=20` items:
     - maximize relevance while penalizing similarity to already chosen items

3. Encode the final selection as a strict ordering score:
   - chosen items get `score_stageD_final = 3.0 - r*1e-6`
   - unchosen items keep their baseline score (so you can still inspect beyond the top‑20)

**Produces**

- Functions used by the final run cell:
  - `add_stagec3_signal_v1()`
  - `add_stageD_mmr_tfidf_v2()`

**Used by later**

- Cell 14 runs these functions to compute the final exported ranking.

---

### Cell 13 (markdown) — Final run header (`id=2c855c98`)

Section divider explaining where outputs go and what “Run All” should produce.

---

### Cell 14 (code) — Final run: Stage C.3 + Stage D + exports (`id=2b12579f`)

**Purpose**

- Orchestrate the “production” end-to-end output:
  - ensure Stage C pool is loaded
  - run Stage C.3 rerank (cached)
  - run Stage D selection (offline)
  - export CSVs + run summary + diagnostics

**Core actions**

- Loads `stageC_all` from disk if it’s not in memory.
- Runs Stage C.3:
  - `stageC3_df, stageC3_totals = await stagec3_rerank_topn(...)`
- Optionally runs Stage D (if enabled):
  - `add_stagec3_signal_v1()` then `add_stageD_mmr_tfidf_v2()`
  - chooses the final scoring column (`final_score_col`)
- Exports:
  - full scored output CSV
  - per-chapter top‑30 CSVs (filtered to exclude `exclude`)
  - global top‑30 CSV
  - query attribution + productivity tables per chapter
  - run summary JSON with paths + knobs + cost totals
- Plots (debug):
  - score vs rank, chapter composition, label composition, authority vs final score
- QA sanity checks:
  - warns if `exclude` or blank labels appear in exported top‑30s

**Produces (on disk)**
Everything under `final_pipeline/results/` (see “Output layout” above).

**Used by later**

- This is the end of the notebook pipeline; outputs are meant for external consumption.

---

### Cell 15 (code) — Empty cell (`id=38efb6ce`)

No-op. Safe to ignore/remove.

---

## Common “gotchas” (practical notes)

- **Semantic Scholar without an API key** can return many `429 Too Many Requests` and make Stage A painfully slow (or effectively non-functional). Set `SEMANTICSCHOLAR_API_KEY`.
- **OpenAlex query placement matters**:
  - embedding long boolean queries into `filter=title_and_abstract.search:...` is often too restrictive.
  - using `search=...` with constraints in `filter=` is usually much higher recall.
- **Caching is signature-based**: if you change a knob and don’t see changed results, you may be reading an older `<sig>` folder. The notebook usually selects the newest by mtime, but you can force rebuild via the `FORCE` / `FETCH_FORCE` flags per stage.
