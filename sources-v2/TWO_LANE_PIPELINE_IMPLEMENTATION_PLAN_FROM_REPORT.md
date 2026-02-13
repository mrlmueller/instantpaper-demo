# Two-lane literature-retrieval pipeline (OpenAlex + Semantic Scholar)

Implementation plan (v1) — updated with pre-dev quality adjustments

Date: 2026-02-10

## 0) Scope and success criteria

### Goal

Build a pipeline that takes:

- `chapter_title: str`
- `chapter_spec: str` (~200 words)

And returns **two ranked lanes** of sources:

- **Authority lane**: canonical / high-notability / high-impact, while still relevant
- **Match lane**: best topical fit, including strong partial matches on important sub-aspects

### Hard constraints (v1)

- Providers: **OpenAlex** + **Semantic Scholar Academic Graph** only
- Languages: always search **English + German**; return sources in either
- Strict separation throughout: `with_abstract` vs `without_abstract` pools are **never mixed**
- Query budget: **≤ 50 queries per provider per run**
- Quality > speed: design for long runtimes (up to ~30 minutes), especially with Semantic Scholar’s typical ~1 RPS key-based rate
- Cost target (OpenAI usage): ≈ **$0.20/run** via batching + staged pruning + rerank only top-K

### Output contract (top-level)

Return a JSON object:

- `authority_lane.with_abstract.primary_top_20` + `coverage_top_up`
- `authority_lane.without_abstract.primary_top_20` + `coverage_top_up`
- `match_lane.with_abstract.primary_top_20` + `coverage_top_up`
- `match_lane.without_abstract.primary_top_20` + `coverage_top_up`

Each item includes ids, metadata, scores, coverage tags with evidence excerpts, and (optional) rerank result.

## 1) Milestones (suggested)

M0 — Foundations

- Config + schemas + deterministic utilities

M1 — Retrieval

- Provider clients, rate limiting, retries, pagination, caching of raw responses

M2 — Candidate table

- Normalization, cross-provider dedup, strict pool split

M3 — Embedding baseline

- Atomic facets + facet embeddings + Stage 1 metadata embeddings + pruning + baseline scoring

M4 — Quality multipliers

- S2 recommendations expansion + Stage 2 abstract chunking + late interaction + coverage tags

M5 — Ranking quality

- Lane fusion + pointwise LLM reranking (top-K) + diversity top-up + authority time stratification

M6 — Validation & docs

- Unit/integration tests, run artifacts, metrics, and minimal usage docs

## 2) Proposed module breakdown (implementation-oriented)

### 2.1 Core data models (schemas)

Implement as Pydantic models or dataclasses (pick one and use consistently).

- `ChapterInput`
  - `chapter_title`, `chapter_spec_text`
  - `pipeline_version`
  - `run_id = hash(title + spec + pipeline_version)`

- `Facet` (must be **atomic**)
  - `facet_id` (stable lower_snake_case, 3–6 words)
  - `facet_label_en` (≤8 words), `facet_label_de` (≤8 words)
  - `facet_type`, `importance_weight: 1..5`
  - `text_en`, `text_de`
  - `canonical_terms.{en,de}`, `neighbor_terms.{en,de}`, `exclusion_terms.{en,de}`

- `QueryPlan`
  - `topic_summary_en`, `topic_summary_de`
  - `facets: list[Facet]`
  - `global_canonical_terms.{en,de}`
  - `global_exclusions.{en,de}`

- `ProviderQueryOpenAlex` / `ProviderQueryS2`
  - Fully-specified query objects (endpoint + params + intent tags)

- `Candidate`
  - Canonical ids: `id` (prefer DOI), `doi`, `external_ids`
  - Metadata: `title`, `authors`, `year`, `venue`, `url`, `language`, `abstract|null`
  - Provider provenance: `provider_ids` (openalex_id, s2_paperId, …), `sources[]`
  - Citation metrics: `citations` (+ optional `influential_citations`)

- `CoverageTag`
  - `facet_id`, `facet_label_en`, `score`, `excerpt` (≤240 chars)

- `Scores`
  - `match`, `authority`, `lane_score`

- `RerankResult`
  - `{ llm_score_0_100, covered_facets, rationale, insufficient_info }` (strict JSON schema)

### 2.2 Deterministic utilities

- DOI normalization (strip `https://doi.org/`, `doi:`; lowercase; trim)
- arXiv id normalization
- PMID/PMCID normalization
- Title normalization for fallback key (casefold, punctuation collapse, whitespace)
- Cosine similarity helper
- `softclip(x) = max(0, x)`
- Percentile helper (for year-normalized authority)

## 3) Work breakdown by phase

### Phase A — Config, run artifacts, and logging

Goal: one consistent config surface and a run directory keyed by `run_id`.

- [ ] Define `PipelineConfig` with:
  - Provider keys, base URLs, timeouts
  - Rate limits (S2 ~1 RPS; OpenAlex credit-aware)
  - Query cap = 50/provider
  - Embedding model (`text-embedding-3-small`) and batch sizes
  - Pruning sizes (`N1=600` per lane/pool default)
  - S2 neighbor booster: `seed_count=5`, `recs_limit_per_seed` (e.g., 200–500)
  - Rerank: `top_k_pre=40`, concurrency=20
  - Match aggregation weights: `best=0.55`, `top_m=0.25`, `cov=0.20`, `m=3`
  - Scoring constants: `t=0.30`, `t_noabs=0.35`
  - Authority constants: `classic_year_max=2004`, `recent_year_window=8`, bucket quotas
- [ ] Standardize run artifact paths under `runs/{run_id}/`:
  - `query_plan.json`
  - `openalex_queries.json`, `semanticscholar_queries.json`
  - `openalex_raw.jsonl`, `semanticscholar_raw.jsonl`
  - `semanticscholar_recommendations.jsonl` (seeded expansions)
  - `candidates_normalized.(jsonl|csv)`
  - embeddings: `embeddings_manifest.(csv|jsonl)` + vector blobs
  - `rerank_results.jsonl`
  - `output.json`
- [ ] Add structured logging + per-stage metrics (counts, timings, cache hits).

Acceptance: a stubbed run writes a complete artifact skeleton.

### Phase B — LLM: Query Planner (facet extraction; **atomic facets**)

Goal: extract 8–20 bilingual facets that drive retrieval and scoring, and prevent “everything in one facet”.

- [ ] Implement `plan_queries_llm(chapter_input) -> QueryPlan`:
  - temperature=0
  - structured outputs (strict json_schema)
  - “do not name papers/authors” constraint
  - **atomic facet rule**: each facet maps to exactly one requirement/aspect from the chapter spec (plus 2–4 neighbor facets)
  - discourage overlap: facets should be as non-overlapping as possible
- [ ] Cache `query_plan.json`.

Acceptance: schema-valid JSON; facets cover all explicit spec requirements; facets are atomic (no “mega facet”).

### Phase C — LLM: Provider-specific query generators (≤50/provider)

Goal: transform `QueryPlan` into provider-safe query objects.

#### C1) Budgeting logic (deterministic)

Let `F = len(facets)`.

- Always generate:
  - 2 global core queries (EN + DE)
  - 2×min(F, 18) facet-targeted queries (EN + DE)
  - 6 neighbor-topic queries (3 EN + 3 DE)
  - 6 methods/data/evaluation queries (3 EN + 3 DE)
- If F < 18: allocate remaining budget to expand OR synonym lists for weight 4–5 facets.

#### C2) OpenAlex query generation

- [ ] Generate `/works` query params using:
  - `search=` and/or `.search` filters (`title.search`, `abstract.search`, `title_and_abstract.search`)
  - Hygiene filters: `is_paratext:false`, `is_retracted:false` (optional)
  - Language filter: `language:en|de`
  - `per-page=200`, cursor paging (`cursor=*`; required for deep recall beyond 10k)
  - `select=` minimal fields
  - Authority: `sort=cited_by_count:desc`
  - Match: relevance, or `publication_year:desc,relevance_score:desc`
- [ ] Enforce boolean constraints:
  - Uppercase AND/OR/NOT
  - Parentheses + quotes allowed
  - Forbid `* ? ~` in boolean query strings (OpenAlex removes them; treat as invalid upstream)

#### C3) Semantic Scholar query generation

- [ ] Generate `GET /graph/v1/paper/search/bulk` queries:
  - Use operators `| + -` and quotes; wildcard `*`; fuzzy/proximity `~N`
  - Always emit EN + DE variants
  - Keep `fields` minimal for search stage
- [ ] Define hydration plan using `POST /graph/v1/paper/batch` (≤500 ids/call)
  - Request `abstract` + `authors` + `externalIds` + citation metrics

Acceptance: query objects validate (syntax + caps) and are cached.

### Phase D — Retrieval orchestrator (initial retrieval)

Goal: execute queries with caching, pagination, retries, and provider throttling.

- [ ] Implement provider clients:
  - OpenAlex: cursor pagination; `per-page=200`
  - S2: bulk search token pagination + batch hydration (≤500)
- [ ] Implement common request layer:
  - Retry/backoff for 429/5xx
  - Per-provider rate limiter (S2 ~1 RPS)
  - Request fingerprint logging (provider, endpoint, params, ts, status, retries, cache hit)
- [ ] Cache raw responses (`*.jsonl`) keyed by `run_id` and query hash.

Acceptance: rerun uses caches; transient errors don’t crash the run.

### Phase E — Normalize, deduplicate, and pool split

Goal: unify provider outputs to canonical candidates and split pools strictly.

- [ ] Normalize OpenAlex work → `Candidate`:
  - Reconstruct abstract from `abstract_inverted_index` when present
  - Capture `cited_by_count`, venue/source core flag if available
- [ ] Normalize S2 paper → `Candidate`:
  - Use batch hydration to fill `abstract` and `authors`
  - Capture `citationCount` (+ influential if available)
- [ ] Cross-provider dedup keys (in order):
  1. DOI
  2. arXiv id
  3. PMID/PMCID
  4. Fallback: (normalized_title, year, first_author_lastname)
- [ ] Merge precedence:
  - Prefer abstract-bearing record
  - Else prefer richer metadata
  - Preserve all provider ids for traceability
- [ ] Split into disjoint pools:
  - `with_abstract`: abstract present and non-empty
  - `without_abstract`: abstract missing

Acceptance: unit tests for abstract reconstruction + dedup precedence; pools are disjoint.

### Phase F — Embeddings and staged scoring (with partial-match protection)

Goal: facet-aware relevance scoring with cost controls and strong handling of “one requirement hit”.

#### F1) Embedding cache

- [ ] Cache vectors by `(text_hash, model)` with a manifest index.
- [ ] Batch embedding calls (array input).

#### F2) Stage 0: facet embeddings

- [ ] For each facet `i`:
  - `E_f_en[i] = embed(facet.text_en + canonical_terms.en)`
  - `E_f_de[i] = embed(facet.text_de + canonical_terms.de)`

#### F3) Stage 1: metadata embeddings (all candidates, both pools)

- [ ] Build metadata view:
  - `v_meta = title + venue + year + fields/keywords + publication_types`
- [ ] Embed `v_meta` and compute per-facet score:
  - `s_i = max(cos(E_f_en[i], E_meta), cos(E_f_de[i], E_meta))`
- [ ] Compute provisional match features using the **best + top-m + coverage** aggregation (see Phase G1).

#### F4) Semantic Scholar neighbor-search booster (recommendations expansion)

Goal: capture adjacent-but-relevant literature better than query expansion alone.

- [ ] After Stage 1 scoring (before final pruning), pick ~`seed_count=5` seed papers:
  - Choose highest **Match** candidates (prefer `with_abstract`), and prefer seeds with `s2_paperId`.
  - If seed lacks `s2_paperId` but has DOI/arXiv/PMID, optionally resolve it to `paperId` via S2 lookup.
- [ ] For each seed, call the Semantic Scholar **Recommendations API** (limit up to ~500) to retrieve recommended `paperId`s.
- [ ] Hydrate recommended ids via `/paper/batch`, normalize to `Candidate`, merge into candidate pool, and re-run dedup.
- [ ] Embed only new candidates’ metadata; update Stage 1 scores; then proceed to pruning.
- [ ] Cache recommendations calls and hydrated results (`semanticscholar_recommendations.jsonl`) keyed by `(run_id, seed_id)`.

Acceptance: recommendation expansion increases candidate diversity and recovers neighbor works not reachable via query strings.

#### F5) Pruning after Stage 1

- [ ] Keep `N1=600` per lane per pool (configurable).

#### F6) Stage 2: abstract chunking + late interaction (with_abstract shortlist only)

- [ ] Deterministic sentence chunking:
  - 250–400 chars target, 1-sentence overlap
- [ ] Embed chunks and compute per-facet MaxSim:
  - `s_i = max_k max(cos(E_f_en[i], E_chunk[k]), cos(E_f_de[i], E_chunk[k]))`
- [ ] Store evidence excerpt = winning chunk trimmed to ≤240 chars.
- [ ] Recompute match features with Stage 2 `s_i` (Phase G1).

#### F7) Without-abstract handling

- [ ] Build `metadata_view_rich` and optionally chunk into 2–4 segments.
- [ ] Use stricter threshold `t_noabs=0.35` for coverage, and expect reranker “insufficient_info=true” often (Phase I).

Acceptance: Stage 1 deterministically reduces candidates; Stage 2 produces evidence excerpts; strong partial matches are preserved via top-m aggregation.

### Phase G — Exact scoring formulas and lane fusion

Goal: reproducible `match`, `authority`, and lane scores.

#### G1) Match score (drop-in; partial-match friendly)

Let `w_i ∈ {1..5}` and per-facet `s_i` (Stage 2 if present else Stage 1).

- Define `g_i = w_i * s_i`
- `best = max(g_i) / 5.0`
- `top_m` (default `m=3`): let `I` be indices of the top-m values of `g_i`
  - `top_m = (Σ_{i∈I} g_i) / (Σ_{i∈I} w_i)` (if fewer than m facets exist, use what exists)
- Coverage term:
  - `cov = (Σ_i w_i * softclip(s_i - t)) / (Σ_i w_i)`
  - `softclip(x)=max(0,x)`
  - `t = 0.30` (`t_noabs = 0.35` for `without_abstract`)

Final aggregation (default weights):

- `match = 0.55*best + 0.25*top_m + 0.20*cov`

Rationale: keeps “perfect match to one key requirement” ranked high while still rewarding 2–3 strong hits and broad coverage.

#### G2) Authority score (year-normalized; v1 practical)

Goal: avoid burying strong recent work while still rewarding impact.

- Let `citations` be provider citation count (S2 `citationCount`, OpenAlex `cited_by_count`).
- Let `age_years = max(1, current_year - year + 1)` (if year missing, treat as 1).
- `citations_per_year = citations / age_years`
- Compute `c_norm` as the percentile rank of `citations_per_year` within the retrieved candidate set for the run (0..1).

Optional recency logistic (small nudge, keep modest since `citations_per_year` already reflects recency):

- `recency = 1/(1+exp(-(year-(current_year-5))/2))` (if year missing, set to 0.5)

Optional bonuses:

- +0.05 if title contains “survey/review/handbook” (and DE equivalents)
- (OpenAlex) +0.03 if a core venue/source flag exists

Compute:

- `authority = clip(0.85*c_norm + 0.15*recency + bonus, 0, 1)`

Acceptance: a very strong recent paper can outrank an older mid-impact paper when justified by citations_per_year.

#### G3) Lane fusion (exact)

- `AuthorityScore = 0.80*authority + 0.20*match`
- `MatchScore = 0.80*match + 0.20*authority`

### Phase H — Coverage tags (evidence-based)

Goal: explainability grounded in embedding evidence (not LLM inference).

- [ ] A facet is “covered” if:
  - `with_abstract`: `s_i ≥ 0.30` OR among top-2 facets by score
  - `without_abstract`: `s_i ≥ 0.35` OR top-1 facet
- [ ] Emit `coverage_tags[]` with `{facet_id, facet_label_en, score, excerpt}`.

Acceptance: every coverage tag maps to a concrete excerpt (or clear “insufficient” handling).

### Phase I — LLM reranking (pointwise; async; top-K only; honest on metadata-only)

Goal: improve ordering using evidence-grounded, schema-validated judgments.

- [ ] Pointwise rerank per lane × pool:
  - Input = chapter title + compact facet list + candidate metadata + evidence excerpts
  - Output schema (strict): `{llm_score_0_100, covered_facets, rationale, insufficient_info}`
  - temperature=0, concurrency cap=20, retries/backoff
- [ ] **Without-abstract honesty rule**:
  - For `without_abstract`, instruct the model to set `insufficient_info=true` unless metadata is unusually rich and clearly supports key facets.
  - Treat `insufficient_info=true` as a signal for cautious ranking (policy decision: lower priority unless authority is exceptional).
- [ ] Cache rerank results by `(run_id, candidate_id, lane, pool)`.
- [ ] Define final sort policy explicitly (example):
  - primary sort: `llm_score_0_100` (desc)
  - tie-break: lane score (desc)

Acceptance: rerank outputs validate; reruns reuse cache; metadata-only items do not receive overconfident high scores.

### Phase J — Diversity “coverage top-up”

Goal: add extra items from top-40/50 to cover missing high-weight facets **without changing** primary top-20.

- [ ] Implement per lane/pool:
  - `primary = top20_sorted`
  - `extended = top50_sorted`
  - `required = {facet | weight>=4}`
  - Greedy select candidates from `extended \ primary` maximizing newly covered required facets
  - Stop if no candidate adds missing coverage

Acceptance: primary top-20 unchanged; top-up increases required-facet coverage when possible.

### Phase K — Final lane construction and output formatting

Goal: emit final JSON with two lanes × two pools, each with primary and top-up.

#### K1) Authority lane time stratification (quality rule; recommended default)

Goal: guarantee “foundational + recent” within Authority lane.

- [ ] Build an authority shortlist (e.g., top 200 by `AuthorityScore`, after rerank if enabled).
- [ ] Define buckets (configurable):
  - **Classic**: `year <= classic_year_max` (default 2004)
  - **Recent**: `year >= current_year - recent_year_window` (default window 8)
  - **Middle**: everything else
- [ ] Select primary top-20 by quota (example default):
  - 8–10 from Classic
  - 8–10 from Recent
  - Fill remaining from best overall (excluding already selected)
- [ ] Within each bucket, preserve ranking order (by rerank score then lane score).

Acceptance: Authority lane contains both foundational and recent influential sources even when one dominates the raw ranking.

#### K2) Per-item fields

- ids: `id` (prefer DOI), `doi`, `provider`, `provider_ids`, `external_ids`
- metadata: `title`, `authors[]`, `year`, `venue`, `url`, `language`, `abstract|null`
- `citation_metrics`
- `scores` (`match`, `authority`, `lane_score`)
- `coverage_tags[]`
- `rerank` (if enabled)

Acceptance: output validates against a JSON schema; strict pool separation holds.

## 4) Testing and evaluation plan

### Unit tests (must-have)

- OpenAlex abstract reconstruction from `abstract_inverted_index`
- OpenAlex boolean query validator forbidding `* ? ~`
- Dedup key ordering + merge precedence
- Chunking determinism
- Match aggregation: `best + top_m + cov` (including m<3 edge cases)
- Authority year-normalization percentile (deterministic percentile function)
- Authority lane time stratification (quota selection correctness)

### Integration tests (offline fixtures)

- Normalize + dedup from saved raw response samples
- S2 recommendations expansion merge/dedup from saved rec fixtures
- End-to-end run with mocked provider + LLM outputs to validate output shape and stage boundaries

### Run-level metrics to log

- Provider call counts, cache hit rates, runtime per stage
- Candidate counts: retrieved → deduped → pool sizes → shortlist sizes
- Required facet coverage (primary vs after top-up)
- Embedding counts + estimated token usage/cost

## 5) Operational notes and risks

### Rate limits and keys

- Semantic Scholar: plan around ~1 request/second default with API key; rely on bulk + batch.
- OpenAlex: the design report notes an API key requirement date of **2026-02-13** (3 days after this plan date); implement key handling and credit-aware usage.

### Cost controls

- Stage 1 pruning is mandatory before Stage 2 chunk embeddings.
- Batch embeddings; rerank only top-K.

### Quality controls

- Never mix `with_abstract` and `without_abstract` evidence/scores.
- Coverage tags must be derived from embedding evidence (not LLM guessing).
- Prefer atomic facets; otherwise partial-match protection cannot work reliably.

## 6) Decisions to finalize early

1. Final ranking policy: pure LLM sort vs weighted blend with lane score (per lane/pool).
2. S2 recommendations expansion details: seed selection policy, limits, and caching granularity.
3. Storage format for embedding cache (npz/parquet/sqlite) and eviction strategy.
4. Authority time stratification quotas and year cutoffs (classic/recent).

## Appendix A — Prompts (ready to paste; temperature=0; structured outputs)

### Prompt 1 — Query Planner (facet extraction + bilingual terms + weights)

Use with a small planner model. Output must be strict JSON.

```text
SYSTEM:
You are a scientific literature search planner. Convert a chapter title and a ~200-word chapter specification into a bilingual (EN+DE) query plan for downstream APIs.
You must be deterministic and consistent across any domain.
Do NOT name specific papers, authors, or venues. Do NOT invent citations.

USER:
CHAPTER_TITLE:
{{chapter_title}}

CHAPTER_SPEC (instructions):
{{chapter_spec_text}}

TASK:
Return a QueryPlan JSON object with these keys:

1) topic_summary_en: 2–3 sentences
2) topic_summary_de: 2–3 sentences (natural German)

3) primary_context_anchors:
   - en: 3–8 short anchors that uniquely pin the topic (prefer proper nouns, named constructs, standard period/organism/method names)
   - de: 3–8 short anchors (German equivalents + common English terms used in German literature)
   RULES:
   - Each anchor must be 1–6 words.
   - No generic research words: analysis, study, effects, mechanism, framework, model, system, approach, dynamics, development, review, overview
     German: Analyse, Studie, Effekte, Mechanismus, Rahmen, Modell, System, Ansatz, Dynamik, Entwicklung, Überblick
   - Avoid long narrative phrases. Avoid parentheses and commas inside anchors.

4) global_canonical_terms:
   - en: 12–30 terms/phrases (topic terms + synonyms + abbreviations)
   - de: 12–30 terms/phrases (German equivalents + common English loan terms)
   TERM HYGIENE (MANDATORY for ALL term lists):
   - Each term must be <= 4 words.
   - No explanatory text, no “e.g.” / “z. B.”.
   - No parentheses, no commas, no semicolons.
   - No “modern … jargon” type commentary; only tokens likely to appear in titles/abstracts.

5) global_exclusions:
   - en: 0–12 atomic confounder terms (<= 3 words each)
   - de: 0–12 atomic confounder terms (<= 3 words each)
   EXCLUSION RULES:
   - Only include exclusions that are likely to appear in unrelated literature and cause wrong-sense retrieval.
   - No punctuation except hyphen. No parentheses. No example phrases.

6) facets: 8–20 ATOMIC facets (one requirement each).
For each facet:
- facet_id: lower_snake_case, 3–6 words, stable
- facet_type: one of ["background","theory","mechanism","methods","data","measurement","evaluation","case_context","debate","limitations","applications"]
- importance_weight: integer 1..5 (5 = explicitly required, 4 = important support, 3 = common subtopic, 2 peripheral, 1 optional)
- facet_label_en: <= 8 words
- facet_label_de: <= 8 words
- text_en: 1–2 sentences
- text_de: 1–2 sentences
- canonical_terms.en/de: 6–18 terms each (must follow TERM HYGIENE)
- neighbor_terms.en/de: 4–12 terms each (must follow TERM HYGIENE)
- exclusion_terms.en/de: 0–6 terms each (must follow EXCLUSION RULES)

QUALITY RULES:
- Cover all explicit instructions in the chapter spec via facets (no gaps).
- Add 2–4 neighbor facets that are commonly necessary but not explicitly listed.
- Keep facets non-overlapping as much as possible.
- Prefer technical terms over vague words.
- If the topic is ambiguous, add exclusions to disambiguate.

OUTPUT:
Return ONLY valid JSON. No extra text.
```

### Prompt 2 — OpenAlex Query Builder (provider-tailored, budget-aware)

```text
SYSTEM:
You generate OpenAlex /works query objects. Output ONLY valid JSON.
Goal: high precision with strong recall across ANY scientific domain.
Be deterministic.

PIPELINE CONTEXT (READ CAREFULLY):
You generate provider-safe OpenAlex /works queries for retrieval in a two-lane pipeline.
These queries only collect candidates; downstream stages deduplicate, embed, and rerank.
So: keep queries context-anchored and reasonably selective, but not ultra-narrow.

INTENTS:
- authority: broad, high-impact/core literature for the chapter context (we rank later).
- match: facet-specific topical fit (MUST still include the chapter context).

CHAPTER CONTEXT (USE THIS TO DISAMBIGUATE GENERIC TERMS):
CHAPTER_TITLE:
{{chapter_title}}

CHAPTER_SPEC_TEXT:
{{chapter_spec_text}}

OPENALEX RULES (MUST FOLLOW):
1) Boolean operators MUST be uppercase: AND / OR / NOT. Parentheses and quotes allowed.
2) Forbidden characters in search string: * ? ~  (never output these).
3) Avoid slash tokens. Do NOT output X/Y inside quotes; instead use (X OR Y).
4) Include search_field for each query:
   - match queries should use title_and_abstract.search
   - authority queries should use title_and_abstract.search, plus optionally one default.search booster per language
5) Filters must be comma-separated (no semicolons). Only use safe keys:
   language,is_paratext,is_retracted,type,from_publication_date,to_publication_date,
   primary_location.source.is_core,locations.source.is_core
6) per_page MUST be 200.
7) Sorting:
   - authority: cited_by_count:desc
   - match: relevance_score:desc (or null)

ANCHORS (MUST FOLLOW):
- Every query MUST include at least ONE term from primary_context_anchors for that language.
- Authority queries MUST be context-anchored: prefer primary_context_anchors and/or CHAPTER_TITLE.
- A second anchor is OPTIONAL for match queries (do not force the same two global anchors in every match query).
- Match queries must contain at least TWO strong signals total:
  (a) anchor AND facet-group, OR
  (b) anchor AND anchor, OR
  (c) anchor AND facet-group with >=3 facet terms.

GENERIC ANCHORS (CRITICAL):
- If you use OR-groups for anchors, NEVER include generic descriptors inside the OR-group.
  OR makes any single term sufficient, so a generic term will destroy topical anchoring.
- Examples of generic descriptors (do NOT use as anchors): decline, transformation, continuity, change, effects, mechanisms,
  analysis, study, case study, review, overview, framework, approach, process, dynamics, development.
- If a global term looks generic, do not use it as an anchor; move it into a facet group or omit it.

GERMAN ANCHOR ROBUSTNESS (CRITICAL):
- Avoid brittle long natural-language phrases as a single quoted anchor.
- Prefer compositional anchoring: two shorter anchors combined with AND; each anchor can be an OR-group of variants.
- Avoid invisible/soft hyphens and special hyphen characters; use plain characters only.

ANTI-NOISE (CRITICAL FOR AUTHORITY):
- Do NOT use generic filler abstract nouns as an authority “second group”
  (e.g., decline, transformation, continuity, change, process, analysis, study, research).
- Authority second-group terms MUST come only from:
  (a) global_canonical_terms (topic-specific; exclude generic fillers), OR
  (b) importance_weight>=4 facet canonical_terms/neighbor_terms.
- If you cannot build a non-generic second group, OMIT it (do not add generic fillers).

EXCLUSIONS (IMPORTANT):
- Use global_exclusions[language] to add a NOT-group to the query_string when exclusions exist.
- Only use atomic exclusions (<=3 words, no punctuation except hyphen). If unsure, omit exclusions rather than writing narrative NOT clauses.
- Always apply exclusions in authority queries; apply them in match queries when the query would otherwise be broad.

QUERY STYLE DIVERSITY (CRITICAL):
For MATCH intent, output a MIX of query styles across the set:
A) STRICT: (anchor1 AND anchor2) AND (facet group)
B) BALANCED: (anchor1 OR anchor_variant1 OR anchor_variant2) AND (facet group)
C) FACET-LED: (anchor1) AND (facet group with 5–10 terms), WITHOUT requiring a second global anchor.
Ensure at least 25% of match queries are FACET-LED and at least 25% are BALANCED.

BROADNESS CONTROL:
- Match queries: 1–2 anchors + 6–12 facet terms max.
- Authority queries: 1–2 anchors + 4–8 high-level terms.
- If a facet is generic (methods, causality, evidence), pair it with at least one concrete facet term.

BROADNESS TARGETS (HEURISTIC; you cannot probe counts here):
- Match queries should typically land in ~200–10,000 results.
- Authority queries can be broader (~1,000–100,000) but still anchored.
If likely too broad: add a second anchor with AND, shrink facet group to 4–6 terms, add exclusions.
If likely too narrow: loosen second anchor, expand facet group to 8–12 terms, use OR variants.

LANGUAGES:
Always generate both English and German queries.

USER:
CHAPTER_TITLE:
{{chapter_title}}

CHAPTER_SPEC_TEXT:
{{chapter_spec_text}}

INPUT_QUERY_PLAN_JSON:
{{query_plan_json}}

BUDGET:
max_queries = {{max_queries}}  # hard cap; do NOT exceed
languages = ["en","de"]

OUTPUT JSON SCHEMA:
{
  "openalex_queries": [
    {
      "intent": "authority" | "match",
      "language": "en" | "de",
      "search_field": "default.search" | "title_and_abstract.search",
      "query_string": "BOOLEAN QUERY STRING",
      "filters": "comma,separated,filters",
      "sort": "cited_by_count:desc" | "relevance_score:desc" | null,
      "per_page": 200,
      "notes": "<= 18 words"
    }
  ]
}

FILTER POLICY:
- Always include: is_paratext:false
- Always include: is_retracted:false
- Always include: language:{en|de}
- Authority lane MUST include:
  (1) one broad authority query per language WITHOUT primary_location.source.is_core:true
  (2) optionally ONE additional authority booster query per language WITH primary_location.source.is_core:true

BUDGETING (DETERMINISTIC):
- 2 authority global queries (EN+DE)
- 2 match global queries (EN+DE) with at least one BALANCED style
- For each facet with weight>=4: 1 match query EN + 1 match query DE
- If budget remains: up to 6 neighbor/method queries total (EN+DE)

SELF-CHECK (MUST DO):
- No * ? ~
- No slash tokens X/Y (use OR form)
- Every query includes a primary_context_anchors term
- MATCH queries include a mix of STRICT / BALANCED / FACET-LED
- Authority second group is not generic filler
- Filters use commas and only allowed keys
If any check fails, silently fix and output corrected JSON only.

Return ONLY JSON: { "openalex_queries": [ ... ] }
```

### Prompt 3 — Semantic Scholar Bulk Search Query Builder

```text
SYSTEM:
You generate Semantic Scholar Academic Graph bulk search queries. Output ONLY valid JSON.
Be deterministic. Use only supported bulk query operators and keep queries context-anchored.

PIPELINE CONTEXT (READ CAREFULLY):
You generate Semantic Scholar bulk search queries for retrieval in a two-lane pipeline.
These queries only collect candidates; downstream stages deduplicate, embed, and rerank.
So: keep queries context-anchored and reasonably selective (avoid generic topic-only queries).

INTENTS:
- authority: broad core literature for the chapter context (we rank later).
- match: facet-specific topical fit (MUST still include chapter context anchors).

CHAPTER CONTEXT (USE THIS TO DISAMBIGUATE GENERIC TERMS):
CHAPTER_TITLE:
{{chapter_title}}

CHAPTER_SPEC_TEXT:
{{chapter_spec_text}}

ALLOWED OPERATORS:
- Required: +term or +("a" | "b")
- Exclude: -term or -"phrase"
- OR: ("a" | "b" | "c")
- Quotes for phrases: "two words"
- Wildcard: suffix only, e.g. gene*  (GUARDRAIL: stem length >=4)
- Fuzzy/edit distance: term~1 or term~2 (GUARDRAIL: N <=2 unless term length >=8; then N<=3)
- Phrase proximity: "two word phrase" ~2..4 (GUARDRAIL: N<=4)
- No slash tokens X/Y (rewrite as ("X" | "Y"))
- Any OR-group must be parenthesized: ("a" | "b" | "c d").

MANDATORY STRUCTURE:
- Every MATCH query must have:
  + (PRIMARY_CONTEXT_OR_GROUP) + (FACET_OR_GROUP) [optional negatives]
- PRIMARY_CONTEXT_OR_GROUP:
  - Parenthesized OR-group of 2–6 primary_context_anchors (language-matched).
  - Do NOT include generic research words.
- FACET_OR_GROUP:
  - Parenthesized OR-group of 5–12 facet terms (canonical + neighbor).
  - May include bilingual variants to improve recall.

EXCLUSIONS:
- Use up to 3 atomic exclusions when they prevent wrong senses: -term or -"phrase".
- Atomic = <=3 words, no commas, no parentheses, no “e.g.”.

BROADNESS TARGETS (HEURISTIC; you cannot probe totals here):
- Match queries should typically land in ~200–10,000 results.
- Authority queries can be broader (~1,000–100,000) but still anchored.
If likely too broad: add more context anchors in TOPIC_CONTEXT_OR_GROUP, shrink FACET_OR_GROUP to 4–6 terms, add exclusions.
If likely too narrow: expand FACET_OR_GROUP to 8–12 terms, add bilingual synonyms, loosen the context group.

USER:
CHAPTER_TITLE:
{{chapter_title}}

CHAPTER_SPEC_TEXT:
{{chapter_spec_text}}

INPUT_QUERY_PLAN_JSON:
{{query_plan_json}}

BUDGET:
max_queries = {{max_queries}}
languages = ["en","de"]

OUTPUT JSON:
{
  "s2_bulk_queries": [
    {
      "intent": "authority" | "match",
      "language": "en" | "de",
      "query_string": "QUERY STRING",
      "notes": "<= 18 words"
    }
  ]
}

LANGUAGE POLICY (DOMAIN-AGNOSTIC):
- For language="en":
  - The required PRIMARY_CONTEXT_OR_GROUP is primarily English (can include German variants when helpful).
  - The required FACET_OR_GROUP is primarily English (can include German variants when helpful).
- For language="de":
  - The required PRIMARY_CONTEXT_OR_GROUP MUST include at least one German context term.
  - The required FACET_OR_GROUP SHOULD be bilingual when helpful:
    +("<DE term>" | "<EN term>" | ...), to preserve recall while remaining anchored.

AUTHORITY POLICY:
- Authority queries must be anchored and broad:
  +(PRIMARY_CONTEXT_OR_GROUP) +(HIGH_LEVEL_OR_GROUP)
  - PRIMARY_CONTEXT_OR_GROUP uses primary_context_anchors only (no generic research words).
  - HIGH_LEVEL_OR_GROUP must use topic-specific terms (global_canonical_terms or weight>=4 facets).
- Also include ONE bilingual fallback authority query:
  +("DE primary" | "EN primary") +(HIGH_LEVEL_OR_GROUP)

BUDGETING:
- Always: authority EN + authority DE + authority bilingual fallback
- Always: global match EN + global match DE
- For each weight>=4 facet: match EN + match DE
- If budget is exceeded, drop lowest-weight facets first, but keep the bilingual authority fallback.

SELF-CHECK:
- Every '|' is inside parentheses
- Wildcard only suffix and stem>=4
- ~ only within allowed N
- MATCH has >=2 required groups (two + groups)
- No slash tokens X/Y (rewrite as ("X" | "Y"))
Fix silently; output corrected JSON only.

Return ONLY JSON: { "s2_bulk_queries": [ ... ] }
```

### Prompt 4 — Pointwise Reranker (evidence-grounded, facet-aware)

```text
SYSTEM:
You are a strict scientific relevance judge. You must ONLY use the provided evidence.
Do NOT assume facts not present. If evidence is insufficient, say so.
Your job is to score how useful this source is for writing a chapter described by the input.
Be deterministic (temperature=0).

USER:
CHAPTER_TITLE:
{{chapter_title}}

FACETS (id, label_en, weight, short_description):
{{facet_list_compact}}

CANDIDATE:
- title: {{cand_title}}
- year: {{cand_year}}
- venue: {{cand_venue}}
- authors: {{cand_authors}}
- language: {{cand_lang}}
- citation_count: {{cand_citations}}
- abstract_present: {{cand_has_abstract}}

EVIDENCE:
{{#if cand_has_abstract}}
Top matching excerpts (each linked to a facet):
{{facet_excerpt_list}}
{{else}}
Metadata evidence (title/venue/keywords/etc):
{{metadata_evidence}}
{{/if}}

TASK:
Return JSON with:
- llm_score_0_100: integer
- covered_facets: array of facet_id strings that are clearly supported by EVIDENCE
- rationale: 2–4 bullet points, each must cite which evidence excerpt supports it
- insufficient_info: boolean (true if abstract missing OR evidence too thin to judge well)

SCORING GUIDELINES:
- 90–100: directly addresses at least one weight-5 facet strongly, with clear evidence
- 70–89: strong match to weight-4/5 facets or multiple medium facets
- 40–69: partial/background relevance
- 0–39: weak/off-topic

OUTPUT:
Return ONLY valid JSON. No extra text.
```
