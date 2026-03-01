# Phase F + Phase G deep dive (two-lane pipeline)

This document explains—in human language—what **Phase F** and **Phase G** are doing in the two‑lane literature-retrieval pipeline implemented in `sources-v2/sources_two_lane.ipynb`, and how embeddings turn into ranked paper lists.

**Scope**

- **Phase F**: build embeddings, compute Stage 1 scores (metadata-only), prune, then compute Stage 2 scores (abstract chunks) for a shortlist.
- **Phase G**: recompute the exact scoring formulas from Phase F artifacts, then write the “downstream contract” files: `scores_final.jsonl` + `rankings_stageg.json`.

If you understand these phases, you can usually (a) diagnose “why is this paper ranked here?” and (b) identify which knob or code path to change to improve relevance.

---

## Mental model (what the pipeline is trying to accomplish)

You want papers that match a *multi-part* description you provided at the top of the pipeline. The pipeline therefore tries to score each candidate paper on two mostly-separate axes:

1. **Topical match** (does the content align with the query facets?) → embedding similarity.
2. **Authority** (is it influential / foundational / high signal?) → citations/year + recency + small bonuses.

Then it produces two ranked lists (“lanes”) so you can get both perspectives:

- **Match lane**: mostly topical match, with a small authority nudge.
- **Authority lane**: mostly authority, with a small topicality nudge + extra guardrails when only metadata is available.

The key idea is: *a good result should score well on multiple important facets, not just one*, and *authority should not overpower topicality when the text evidence is weak (especially without abstracts)*.

---

## Glossary (terms used in Phase F/G)

- **Candidate**: a normalized paper record from Phase E (and optionally expanded in Phase F). At minimum: `id`, `title`, `venue`, `year`, `authors`, `citations`, and maybe `abstract`.
- **Pool**:
  - `with_abstract`: abstract text available → eligible for Stage 2 chunk scoring.
  - `without_abstract`: no abstract → metadata-only scoring; stricter thresholds and extra gating.
- **Facet**: an atomic query component from the LLM query plan (Phase B), bilingual (EN+DE), with an `importance_weight` (in this notebook: 3–5).
- **Facet order contract**: `runs/<run_id>/facets_index.json` defines the canonical facet order. All `facet_scores[...]` arrays are aligned to this order.
- **Stage 1**: metadata-only embedding scoring for *all* candidates.
- **Stage 2**: abstract-chunk embedding scoring for a *shortlist* (with-abstract only).
- **Lane**: `match` vs `authority`. Each lane has separate rankings per pool.

---

## What Phase F does (step by step)

Phase F is where almost all embedding compute happens. It’s designed to:

- score a large candidate pool cheaply (Stage 1),
- prune aggressively to control cost,
- then spend extra compute on a smaller set using abstract evidence (Stage 2),
- while keeping “match” and “authority” signals separable.

**Where to find it in code:** in `sources-v2/sources_two_lane.ipynb`, search for the section header **“Phase F — Embeddings and staged scoring (with partial-match protection)”**.

### F1) Embedding cache (how expensive calls are avoided)

Embeddings are cached on disk so repeated runs don’t keep re-paying for the same vectors.

Key behavior (conceptually):

1. Turn each text into a stable `text_hash`.
2. Look for an existing vector file for `(model, text_hash)`:
   - first in the run-local cache (`runs/<run_id>/embeddings_vectors/<model>/...`),
   - then in a shared global cache (`sources-v2/embeddings_cache_global/<model>/...`).
3. If missing, call the embedding API in batches, store vectors as float32 (`.f32`), and append an entry to `embeddings_manifest.jsonl`.

Why you should care:

- If you change how texts are constructed (facet text, metadata view, chunking), you will change hashes and “invalidate” cache hits.
- If vectors are missing or corrupted, you can get silent score shifts or failures downstream.

### F2) Facet embeddings (what exactly gets embedded for the query)

Each facet is embedded twice—English and German—and later the best similarity wins.

The embedded facet text is:

- facet description text (EN or DE),
- plus a “canonical terms” list appended as plain text.

Result:

- `facet_en[facet_id]` and `facet_de[facet_id]` vectors exist for every facet.
- Phase F precomputes inverse vector norms so cosine similarity is cheap.

**Implication:** facet wording and canonical terms are *directly* part of what “relevance” means. Weak / ambiguous facet text leads to weak discriminative scoring.

### F3) Stage 1 — metadata embeddings + per-facet similarities (for all candidates)

Each candidate gets **one metadata embedding** (Stage 1). The embedded metadata text is a deterministic “view” of the candidate:

- Always: title, venue, year, authors.
- Additionally (for `without_abstract`): DOI + external IDs + language + URL (a richer view to make metadata-only scoring less brittle).

For each candidate and each facet:

1. Compute cosine similarity against the English facet embedding.
2. Compute cosine similarity against the German facet embedding.
3. Use `max(en_sim, de_sim)` as the facet score (language-robust scoring).

This produces:

- `facet_scores_stage1[]`: one float per facet, aligned to `facets_index.json`.

### F3) Stage 1 — “match” aggregation (partial-match protection)

The pipeline does **not** rank by a single best facet similarity. It computes a match score designed to prefer papers that:

- have at least one very strong facet match (**best**),
- match multiple facets strongly (**top_m**),
- and exceed a threshold on many facets (**coverage**, `cov`).

Definitions (using the facet order contract):

- `s_i` = facet score for facet `i` (cosine similarity, typically 0..1)
- `w_i` = facet importance weight (3..5)
- `g_i = w_i * s_i`

Components:

1. **Best-hit term**
   - `best = max(g_i) / 5.0`
   - The `/ 5.0` is a normalization assumption: max facet weight is ~5.
2. **Top‑m mean term** (default `m = 3`)
   - Take indices of the `m` largest `g_i`.
   - `top_m = sum(g_i over top m) / sum(w_i over top m)`
   - This is effectively a weighted mean similarity over the strongest facets.
3. **Coverage-above-threshold term**
   - Choose a threshold `t`:
     - `t = scoring_t` for `with_abstract` (default 0.30)
     - `t = scoring_t_noabs` for `without_abstract` (default 0.35)
   - `cov = sum(w_i * max(s_i - t, 0)) / sum(w_i)`

Final match score (defaults shown):

- `match = 0.55*best + 0.25*top_m + 0.20*cov`

**Why this helps ranking quality**

- A paper that spikes on one facet but is weak everywhere else will have:
  - high `best`,
  - mediocre `top_m` (because the next-best facets are weak),
  - near-zero `cov` (because most facets don’t exceed `t`).
- A paper that is consistently on-topic across many facets will have:
  - good `best`,
  - good `top_m`,
  - materially positive `cov`.

So the match score is “anti-cheat” against *single-facet partial matches*.

### F3) Stage 1 — authority score (citations/year percentile + recency)

Authority is computed for every candidate from the candidate universe of this run.

Steps (conceptually):

1. Compute `citations_per_year = citations / age_years`
   - `age_years = max(1, current_year - year + 1)`
   - if `year` is missing, the notebook uses `age_years = 10` (a pragmatic fallback).
2. Convert citations/year into a **percentile rank** over the run’s candidates:
   - only positive values count towards the percentile distribution
   - percentile uses `i / (N + 1)` to avoid saturating at exactly 1.0
3. Add a small **recency** term via a logistic function centered roughly around `current_year - 5`.
4. Add small bonuses:
   - +0.05 if the title looks like a review/survey/handbook/etc. (EN+DE terms)
   - +0.03 if the venue is marked as “core” (`venue_is_core == True`)
5. Combine and clip:
   - `authority = clip01(0.85*percentile + 0.15*recency + bonus)`

**Important property:** authority is **relative to the candidate universe**. If you add/remove lots of candidates (or enable S2 expansion), percentile ranks can shift.

### F3) Stage 1 — lane fusion scores (used for pruning + rankings later)

Two lane scores are computed from the two base axes:

- `match_lane = 0.80*match + 0.20*authority`
- `authority_lane = 0.80*authority + 0.20*match`

This is a simple, intentional “cross-contamination”:

- match lane prefers topicality but softly prefers reputable papers,
- authority lane prefers authority but softly prefers topicality.

### F4) Optional — Semantic Scholar recommendations expansion (neighbor booster)

If enabled, Phase F can expand the candidate universe by fetching Semantic Scholar recommendations for a small number of “seed” papers.

What it does (high level):

1. Pick `seed_count` seeds from the current candidates:
   - prioritize `with_abstract`,
   - then highest `match_lane`,
   - and only seeds that have a Semantic Scholar `paperId`.
2. Call the recommendations endpoint for each seed and log `{seed_paperId, paperId, rank}` to `semanticscholar_recommendations.jsonl`.
3. Hydrate those recommended `paperId`s via `/paper/batch` and normalize them into the same candidate schema.
4. Deduplicate/merge into the pool (DOI/title/year-based keys).
5. Score only newly-added candidates (Stage 1 metadata embedding + facet similarity).
6. Recompute **authority percentiles** over the expanded universe and update `authority` + lane fusion values for all Stage 1 records.

This can improve recall, but it also changes the authority distribution because the candidate universe changes.

### F5) Prune after Stage 1 (build the shortlists)

Phase F then selects a bounded set of candidates to carry forward.

It writes four shortlists (`shortlists_stage1.json`):

- lane ∈ `{match, authority}`
- pool ∈ `{with_abstract, without_abstract}`

Selection rule:

1. Filter Stage 1 records by pool.
2. Sort by the lane-specific fused score (`match_lane` or `authority_lane`).
3. Keep only the top N:
   - `with_abstract`: `prune_n1` (default 600) per lane
   - `without_abstract`: `prune_n1_without_abstract` (default 300) per lane

**Special gate (crucial): authority + without_abstract**

Metadata-only + authority is a dangerous combination: highly-cited off-topic papers can dominate if you don’t have abstract evidence to counter them.

So the notebook applies a topicality gate for `authority/without_abstract` before sorting:

- keep if `match_stage1 >= NOABS_AUTH_MIN_MATCH` (0.22), **or**
- keep if a primary query anchor appears in `title + venue + year`.

This is deliberately simple and cheap. It’s a “last line of defense” against off-topic authority spam when abstracts are missing.

**Note on lane membership vs provenance**

The notebook keeps `candidate.intents` (which query family retrieved a paper) **only for debugging**. Lane shortlists are built from the unified candidate universe—lane membership is determined by scoring + gating, not by retrieval provenance.

### F6) Stage 2 — abstract chunk scoring (late interaction on a shortlist)

Stage 2 is run only for candidates in the **union** of both `with_abstract` shortlists (match ∪ authority), because that’s where abstract evidence is available and most valuable.

Mechanics:

1. Chunk each abstract:
   - normalize whitespace
   - truncate to 6000 characters
   - split into sentences, then pack into ~250–400 character chunks
   - take at most the first 25 chunks
2. Embed every chunk (cached like everything else).
3. For each candidate and each facet:
   - compute chunk similarity to facet (English and German; take max per chunk)
   - aggregate across chunks as:
     - `facet_score_stage2 = avg(top1, top2)` if ≥2 chunks,
     - else just top1.
   - store one **evidence chunk**: the single best chunk text for that facet (truncated).
4. Aggregate the Stage 2 facet scores into `match_stage2` using the same `best/top_m/cov` formula as Stage 1.
5. Update the in-memory lane fusion scores for these candidates and rewrite the ordering of the `with_abstract` shortlists (membership is unchanged; order is refreshed).

Why Stage 2 tends to improve relevance:

- Metadata is often too weak to disambiguate topic. Abstract chunks contain the discriminative terms.
- Averaging top‑1 and top‑2 chunks reduces “single lucky chunk” spikes (a mild robustness improvement over pure max).
- Evidence chunks later enable explainability (“this facet is covered because this abstract snippet matches it”).

---

## What Phase G does (step by step)

Phase G exists because Phase F is an operational, multi-step phase:

- Stage 1 writes files.
- Stage 2 updates scores for a subset.
- Candidate expansion (optional) changes the candidate universe and authority percentiles.

Phase G recomputes the *exact* formulas from the persisted artifacts and writes compact outputs that downstream phases rely on.

**Where to find it in code:** in `sources-v2/sources_two_lane.ipynb`, search for the section header **“Phase G — Exact scoring formulas and lane fusion”**.

### G1) Load the facet order + weights contract

Phase G loads `facets_index.json` and rebuilds `facet_weights[]` in facet order.

This is the hard contract: if facet order changes, every downstream `facet_scores[...]` array becomes meaningless unless it’s regenerated.

### G2) Choose the candidate join universe

Phase G joins metadata into the final output rows.

- If `candidates_expanded.jsonl` exists and is non-empty, use it.
- Otherwise use `candidates_normalized.jsonl`.

This matters because authority percentiles are computed relative to this universe.

### G3) Recompute authority over the run’s candidate universe

Phase G recomputes `authority_by_id` over the chosen candidate universe using the same practical formula as Phase F.

This makes authority reproducible and ensures it’s aligned to the *actual* universe used in this run.

### G4) Load Stage 1 + Stage 2 score files

- `scores_stage1.jsonl`: provides `facet_scores_stage1[]` and Stage 1 match parts.
- `scores_stage2.jsonl` (optional): provides `facet_scores_stage2[]` and `evidence_chunks[]` for the Stage 2 subset.
- `shortlists_stage1.json`: defines which ids are “carried forward”.

### G5) Decide the downstream universe (`ids_needed`)

Phase G computes:

- `ids_needed = union(all shortlists across lane × pool)` (deduped, order-preserving)

Only `ids_needed` appear in `scores_final.jsonl`.

This is one of the biggest “gotchas” when debugging:

- A paper can exist in the candidate pool and even have Stage 1 scores,
- but if it gets pruned out in Phase F, it will not show up in the final contract files at all.

### G6) Build final score rows (per shortlisted id)

For each `cid` in `ids_needed`:

1. Determine `pool` (`with_abstract` vs `without_abstract`).
2. Pick which facet score array to use:
   - if `pool == with_abstract` and Stage 2 scores exist → use Stage 2 facet scores + evidence chunks
   - else → use Stage 1 facet scores
3. Ensure the facet score array length matches the facet contract (clip/pad with zeros if needed).
4. Recompute match using the exact G1 formula with the pool-specific threshold (`t` vs `t_noabs`).
5. Fetch recomputed authority.
6. Recompute lane fusion (`match_lane`, `authority_lane`).
7. Attach minimal metadata (title, doi, year, citations, venue, url, provider ids).

### G7) Write the downstream contract artifacts

Phase G writes:

- `scores_final.jsonl`: one compact JSON row per shortlisted id, including:
  - `scores{match,authority,match_lane,authority_lane,best,top_m,cov}`
  - `facet_scores{stage,scores[]}`
  - `evidence_chunks[]` (Stage 2 only; otherwise empty/None)
- `rankings_stageg.json`: the actual ranked id lists per lane/pool:
  - for each lane/pool, sort shortlist ids by the recomputed lane score from `scores_final.jsonl`.

Downstream phases treat these files as the single source of truth.

---

## Examples (run-grounded, so the math feels real)

The examples below use the run id:

- `4af2666be828e5054ccf4d31`

In this repo, the run’s **facet/anchor contract + candidates** live under:

- `sources-v2/runs/4af2666be828e5054ccf4d31/` (notably `query_plan.json`, `facets_index.json`, `candidates_normalized.jsonl`)

The run’s **Phase F/G score artifacts** are currently snapshotted under:

- `sources-v2/runs/_snapshots/4af2666be828e5054ccf4d31__before_p0_1_lane_isolation__20260301_122746/` (notably `scores_stage1.jsonl`, `scores_stage2.jsonl`, `scores_final.jsonl`, `rankings_stageg.json`)

This run is useful because it exercises the full Phase F→G path end-to-end:

- Candidate universe (`sources-v2/runs/4af2666be828e5054ccf4d31/candidates_normalized.jsonl`): **64,838** papers
- Stage 1 scored (`sources-v2/runs/_snapshots/4af2666be828e5054ccf4d31__before_p0_1_lane_isolation__20260301_122746/scores_stage1.jsonl`): **64,838** records (all candidates)
- Shortlists (`sources-v2/runs/_snapshots/4af2666be828e5054ccf4d31__before_p0_1_lane_isolation__20260301_122746/shortlists_stage1.json`):
  - `match/with_abstract`: 600
  - `match/without_abstract`: 300
  - `authority/with_abstract`: 600
  - `authority/without_abstract`: 300
- Stage 2 scored (`sources-v2/runs/_snapshots/4af2666be828e5054ccf4d31__before_p0_1_lane_isolation__20260301_122746/scores_stage2.jsonl`): **1,093** records  
  (= the union of the two `with_abstract` shortlists; there were 107 overlaps between match/with_abstract and authority/with_abstract)
- Phase G final contract (`sources-v2/runs/_snapshots/4af2666be828e5054ccf4d31__before_p0_1_lane_isolation__20260301_122746/scores_final.jsonl`): **1,644** records  
  (= union of all shortlists across lane×pool)

### Example setup: anchors + facet contract (this is what “relevance” means in this run)

**Primary context anchors** (used earlier for query hygiene, and later for pruning gates):

- EN: `Heuristics and Biases`, `Dual Process Theory`, `Digital Nudging`, `Choice Architecture`, `Decision Confidence`, `Perceived Risk`, `Consumer Electronics`, `Online Trust`
- DE: `Heuristiken und Biases`, `Dualprozess Theorie`, `Digitales Nudging`, `Wahlarchitektur`, `Entscheidungssicherheit`, `Wahrgenommenes Risiko`, `Online Vertrauen`, `Consumer Electronics`

**Facet order contract**: `sources-v2/runs/4af2666be828e5054ccf4d31/facets_index.json` defines the `facet_ids[]` order. All arrays below use this order.

| ix | facet_id | w | label_en |
|---:|---|---:|---|
| 0 | `decision_psychology_confidence` | 5 | Decision psychology and confidence |
| 1 | `heuristics_biases_online` | 5 | Heuristics and biases online |
| 2 | `dual_process_confidence` | 5 | Dual process and confidence |
| 3 | `decision_confidence_measurement` | 5 | Measuring decision confidence |
| 4 | `choice_architecture_digital_nudging` | 5 | Choice architecture and digital nudging |
| 5 | `nudge_design_ethics_limits` | 5 | Ethics transparency and autonomy |
| 6 | `manipulative_dark_patterns` | 5 | Manipulative patterns and dark patterns |
| 7 | `perceived_risk_dimensions` | 5 | Perceived risk and uncertainty |
| 8 | `trust_and_signals` | 4 | Trust signals and mechanisms |
| 9 | `information_presentation_complex_products` | 5 | Information presentation for complex products |
| 10 | `explainability_quality_signals` | 4 | Explainability and quality signals |
| 11 | `uncertainty_reduction_interventions` | 5 | Interventions to reduce uncertainty |
| 12 | `measurement_methods_webshop` | 4 | Measurement methods in webshop research |
| 13 | `behavioral_outcomes_metrics` | 4 | Behavioral outcomes and metrics |
| 14 | `product_complexity_consumer_electronics` | 5 | Consumer electronics product complexity |
| 15 | `personalization_recommender_effects` | 3 | Personalization and recommender effects |
| 16 | `legal_ethical_regulatory_considerations` | 3 | Legal ethical and regulatory considerations |

---

### Example 1 — Stage 2 improves topical match (with abstract evidence)

**Paper:** `10.1093/jla/laaa006`  
**Title:** “Shining a Light on Dark Patterns”  
**Pool:** `with_abstract`  
**Final artifact row:** `sources-v2/runs/_snapshots/4af2666be828e5054ccf4d31__before_p0_1_lane_isolation__20260301_122746/scores_final.jsonl`

#### What happens in Stage 1 (metadata-only)

From `sources-v2/runs/_snapshots/4af2666be828e5054ccf4d31__before_p0_1_lane_isolation__20260301_122746/scores_stage1.jsonl`:

- `match_stage1 = 0.3749`
- `best = 0.4770`, `top_m = 0.4258`, `cov = 0.0306`

Interpretation:

- Metadata already hints at relevance (it’s not random), but coverage is still low.
- Coverage is low because many facets don’t exceed the threshold strongly when you only embed title/venue/year/authors.

#### What happens in Stage 2 (chunked abstract)

From `sources-v2/runs/_snapshots/4af2666be828e5054ccf4d31__before_p0_1_lane_isolation__20260301_122746/scores_stage2.jsonl` and then recomputed in Phase G:

- `match_stage2 = match = 0.5476` (this becomes the final `match` in `scores_final.jsonl`)
- `best = 0.6827`, `top_m = 0.5925`, `cov = 0.1199`
- `authority = 0.9319`

You can see *all three* match components rise—especially `cov`. That’s the “partial-match protection” doing what it’s supposed to do: once the abstract reveals that the paper consistently hits many facets, the match score climbs.

#### How Phase G turns that into a lane ranking

Lane fusion (exact numbers from `scores_final.jsonl`):

- `match_lane = 0.80*match + 0.20*authority`
- `match_lane = 0.80*0.5476 + 0.20*0.9319 = 0.6244`

So even within the match lane, this paper gets a small bump from being high-authority.

#### Which facets drove the score (top weighted facet hits)

Top facets by `w_i * s_i` using **Stage 2** facet scores (`facet_scores.stage = stage2`):

1. `manipulative_dark_patterns` (w=5): `s=0.683`
2. `choice_architecture_digital_nudging` (w=5): `s=0.561`
3. `nudge_design_ethics_limits` (w=5): `s=0.534`
4. `heuristics_biases_online` (w=5): `s=0.524`
5. `uncertainty_reduction_interventions` (w=5): `s=0.405`

And this is what “evidence chunks” are for: `scores_stage2.jsonl` (and then `scores_final.jsonl`) carries a per-facet excerpt of the best abstract chunk (truncated). For this paper, the top facets’ evidence chunks clearly mention dark patterns, nudging, and cognitive biases—i.e., the abstract contains direct topical evidence.

#### What exactly Stage 2 “fixed” vs Stage 1 (largest per-facet deltas)

Biggest facet score improvements (`stage2 - stage1`) for this paper:

- `manipulative_dark_patterns`: `0.477 → 0.683` (+0.206)
- `heuristics_biases_online`: `0.318 → 0.524` (+0.206)
- `uncertainty_reduction_interventions`: `0.209 → 0.405` (+0.197)
- `choice_architecture_digital_nudging`: `0.388 → 0.561` (+0.173)
- `measurement_methods_webshop`: `0.276 → 0.447` (+0.171)

That’s exactly the behavior you want from Stage 2: it doesn’t just “add noise”; it pushes up the facets that the abstract *actually supports*.

---

### Example 2 — Without an abstract, coverage is harder (and the threshold is stricter)

**Paper:** `10.1007/s11238-021-09802-7`  
**Title:** “Poverty and economic decision making: a review of scarcity theory”  
**Pool:** `without_abstract`  
**Final artifact row:** `sources-v2/runs/_snapshots/4af2666be828e5054ccf4d31__before_p0_1_lane_isolation__20260301_122746/scores_final.jsonl` uses `facet_scores.stage = stage1` (no Stage 2)

Final Phase G scores:

- `match = 0.3340`
- `authority = 0.9983`
- `authority_lane = 0.80*0.9983 + 0.20*0.3340 = 0.8655`
- `cov = 0.0081` (very small)

Why `cov` is tiny here:

- For `without_abstract`, the threshold is stricter (`t_noabs = 0.35`).
- Metadata embeddings often don’t push many facet scores *above* 0.35, even for relevant papers.
- So match is dominated by `best` + `top_m` (a few good facet hits), while `cov` contributes little.

Top facets by `w*s` (Stage 1 facet scores):

- `heuristics_biases_online`: `s=0.432`
- `decision_psychology_confidence`: `s=0.393`
- `perceived_risk_dimensions`: `s=0.313`
- `choice_architecture_digital_nudging`: `s=0.304`

Practical implication:

- `without_abstract` papers can still rank well (especially in the authority lane), but their match score is inherently less “evidence-rich” because the pipeline never sees abstract text.

---

### Example 3 — The authority/no-abstract gate prevents off-topic “citation monsters”

This example demonstrates *why* the `authority/without_abstract` gate exists.

**Paper (in the candidate pool + Stage 1 scored):** `10.1016/j.jenvman.2023.117754`  
**Title:** “Paying for green: A scoping review of alternative financing models for nature-based solutions”  
**Venue:** Journal of Environmental Management  
**Pool:** `without_abstract`

Stage 1 scores (from `sources-v2/runs/_snapshots/4af2666be828e5054ccf4d31__before_p0_1_lane_isolation__20260301_122746/scores_stage1.jsonl`):

- `match_stage1 = 0.2141` (below the gate threshold 0.22)
- `authority = 1.0000`
- `authority_lane = 0.80*1.0000 + 0.20*0.2141 = 0.8428`

So this paper is *extremely authoritative* under the citations/year percentile model, and it would rank very high in an authority-only list.

But:

- it does not meet the topicality minimum (`match_stage1 < 0.22`), and
- none of the primary context anchors appear in `title + venue + year` for this record.

Therefore, Phase F drops it from `authority/without_abstract` *before* selecting the top‑300 shortlist.

This is exactly the intended protection mechanism:

- without abstracts, the pipeline can’t “prove” topicality with chunk evidence,
- so it enforces a cheap minimum topicality test to stop off-topic, high-citation domains from hijacking the authority lane.

---

## Tuning knobs and “what changes if I tweak this?”

This section is intentionally separated from the “how it works” explanation and the run-grounded examples. It’s meant to answer: **what can I change to make relevant papers rank higher—and what side effects will that have?**

### First: a practical rule about reruns

Most knobs below change which candidates make it into shortlists (Phase F), and/or change Stage 2 scoring eligibility. So in practice:

- If you change **any match scoring logic, thresholds, weights, pruning rules, Stage 2 chunking/aggregation**, rerun **Phase F → Phase G** (and then downstream phases that consume `scores_final.jsonl`).
- If you change **facet plan** (facets/anchors/weights), you almost always want to rerun at least **Phase F → Phase G**, and often earlier phases too, because retrieval and scoring are then “about a different query”.

### 1) Facets + facet weights (the biggest lever, even though they’re produced earlier)

**What to change**

- Facet text (EN+DE) and canonical terms.
- `importance_weight` distribution across facets.
- Whether you have too many “overlapping” facets that all mean the same thing.

**What happens if you change it**

- Every per-facet similarity changes immediately, in both Stage 1 and Stage 2.
- Because match is an aggregation across facets, you’re essentially redefining the objective function.

**Common failure patterns**

- **Facet too broad** → many candidates get medium similarity → rankings flatten and noise rises.
- **Facet too narrow / too jargon-heavy** → true positives don’t match in metadata and get pruned before Stage 2 can rescue them.
- **Overlapping facets** → `top_m` and `cov` become less meaningful (you reward “the same concept” multiple times).

**Very important implementation detail**

- The `best` term normalizes as `max(w_i*s_i)/5.0`, which assumes the max weight is ~5.  
  If you ever expand weights beyond 5, revisit that divisor or you will silently rescale match.

### 2) The texts you embed (facet_embed_text + candidate_meta_view + chunking)

You can think of Stage 1 and Stage 2 as two different “views” of the same paper:

- Stage 1 sees a *metadata view* (title/venue/year/authors, optionally identifiers).
- Stage 2 sees an *abstract evidence view* (many small chunks).

**What to change**

- `candidate_meta_view(...)`: which fields are present, and how they’re formatted.
  - If “relevant but not ranking” papers have weak titles but strong abstracts, Stage 1 won’t rescue them—so you may want to enrich metadata (e.g., include keywords/concepts if available).
  - If you include too many non-semantic fields (IDs/URLs), you may dilute the embedding signal.
- `facet_embed_text(...)`: whether canonical terms are informative or generic/noisy.
- `chunk_abstract(...)`: chunk sizing and selection (see Stage 2 tuning below).

**What happens if you change it**

- You change the embedding inputs → you invalidate embedding caches and change similarity geometry.
- In practice this can massively alter pruning outcomes, which is often where recall is lost.

### 3) Match aggregation parameters (`m`, weights, thresholds)

Match is built from `best`, `top_m`, and `cov`. These knobs are how you decide what “relevance” means mathematically.

#### Thresholds: `scoring_t` vs `scoring_t_noabs`

Only the **coverage** term uses the threshold.

- Lowering `t` / `t_noabs`:
  - increases `cov` for many candidates,
  - makes match scoring more “forgiving” (more papers look broadly covered),
  - can improve recall but often increases noise.
- Raising `t` / `t_noabs`:
  - makes coverage stricter,
  - reduces “kinda sorta related” results,
  - can increase precision but can also suppress good papers (especially metadata-only).

`t_noabs` being higher is intentional: without abstract evidence, the system demands stronger metadata similarity before treating a facet as “covered”.

#### `match_m` (how many facets “count” in top_m)

- Smaller `m` (e.g., 2):
  - encourages “sharp” matching on a couple facets,
  - increases the chance of partial-match false positives.
- Larger `m` (e.g., 4–6):
  - encourages multi-facet alignment,
  - can penalize niche but still relevant papers that strongly match only a subset of facets.

#### Weights: `match_weight_best`, `match_weight_top_m`, `match_weight_cov`

- High `match_weight_best` → more single-facet dominance.
- High `match_weight_cov` → more multi-facet breadth requirement.
- High `match_weight_top_m` → “several strong facets” matters more than sheer breadth.

**A useful mapping from symptoms → knob**

- “Top results match only one facet” → increase `match_weight_cov`, increase `match_m`, and/or raise `scoring_t`.
- “Top results are broad but not specific enough” → increase `match_weight_best` slightly and/or reduce `match_m`.
- “Metadata-only papers never rank well even when relevant” → lower `scoring_t_noabs` a bit, or enrich metadata text.

### 4) Pruning sizes (recall vs cost vs Stage 2 opportunity)

The prune step is the biggest structural bottleneck:

- if a paper is not in a Phase F shortlist, it will never appear in `scores_final.jsonl`.

**What to change**

- `prune_n1` (with-abstract per lane)
- `prune_n1_without_abstract` (no-abstract per lane)

**What happens if you change it**

- Larger shortlists:
  - higher Stage 2 cost (more chunk embeddings),
  - but better recall and more chances for Stage 2 to “correct” weak metadata.
- Smaller shortlists:
  - cheaper,
  - but you become extremely dependent on Stage 1 metadata matching quality.

When you see “Stage 2 can clearly improve match, but the good papers never make it to Stage 2”, the fix is often **prune size** (or Stage 1 metadata view quality).

### 5) Stage 2 chunk scoring choices (quality vs robustness)

Stage 2 is where you actually “prove” facet coverage using abstract evidence.

**What to change**

- Abstract truncation length (currently 6000 chars).
- Chunk size targets (currently ~250–400 chars).
- Max chunks per abstract (currently 25).
- Per-facet chunk aggregation (currently `avg(top1, top2)`).

**What happens if you change it**

- More / larger chunks:
  - better chance to capture the relevant part of long abstracts,
  - but higher embedding cost and potentially more false positives (more chances to hit a facet by accident).
- Fewer / smaller chunks:
  - cheaper and often sharper evidence,
  - but easier to miss coverage if the abstract is long or the relevant passage is later.

**Aggregation choice**

- Current: `avg(top1, top2)` per facet.
  - Pros: reduces single-lucky-chunk spikes.
  - Cons: can slightly under-score a facet that is genuinely concentrated in one sentence.
- If you see “facet score spikes that don’t feel real” → consider keeping `avg(top1, top2)` or even `avg(top1..top3)`.
- If you see “true positives have one perfect sentence but still score low” → consider `top1` or a weighted blend.

### 6) S2 recommendations expansion (recall booster with side effects)

If you enable/scale expansion:

- You add candidates that were not retrieved by the original provider queries.
- Authority percentiles are recomputed over a larger universe (so authority values can shift).

**What to tune**

- Seed selection strategy (currently “top match_lane, prioritize with_abstract”).
- `s2_neighbor_seed_count` and `s2_recs_limit_per_seed`.

**Typical issues**

- Too many neighbors → candidate universe explodes → authority percentiles shift and rankings become harder to interpret.
- Bad seeds (early drift) → you expand into an off-topic neighborhood.

### 7) Authority model tuning (when “highly cited” is not what you want)

Authority is intentionally simple and mostly monotonic in citations/year percentile.

**What to change**

- The blend `0.85*percentile + 0.15*recency` (more recency favors newer work).
- Review/core-venue bonuses (can over-reward surveys or specific venues).
- The age fallback for missing year (`age_years = 10`).

**Key limitation**

- Authority is not field-normalized. If your candidate universe spans multiple research areas with different citation norms, citations/year percentiles still mix those norms.

### 8) Lane fusion weights (how much the lanes “leak” into each other)

The current blend (`0.80/0.20`) is a policy choice.

**What happens if you change it**

- If you reduce leakage (e.g., `match_lane = match`):
  - match lane becomes “purer topicality”,
  - but you may surface low-authority noise.
- If you increase leakage:
  - you get more “balanced” lists,
  - but lanes become less distinct (authority starts reshaping match rankings more aggressively).

### 9) The `authority/without_abstract` topicality gate (`NOABS_AUTH_MIN_MATCH`)

This gate exists because metadata-only authority ranking is otherwise extremely vulnerable.

**What to change**

- The numeric minimum (`NOABS_AUTH_MIN_MATCH` = 0.22).
- The anchor-hit heuristic (title+venue+year substring match).

**How it behaves**

- Raise the threshold → fewer off-topic authority papers survive → but you may lose legitimate meta-only authority papers with weak titles.
- Lower the threshold → more authority papers survive → but risk of off-topic domination increases.

If you adjust match scoring parameters (`scoring_t_noabs`, `match_weight_*`, `match_m`), revisit this threshold because it is expressed in “match score units”.

### 10) How to debug a “bad ranking” quickly (using Phase F/G artifacts)

When a paper is “too high” or “too low”, you usually want to answer three questions:

1. **Was it even carried forward?**  
   If it’s not in `scores_final.jsonl`, it was pruned in Phase F. Look at `scores_stage1.jsonl` and `shortlists_stage1.json`.
2. **Which facets made it score high?**  
   In `scores_final.jsonl`, take `facet_scores.scores[]` and map indices using `facets_index.json`. Compute `w_i*s_i` and inspect the top facets.
3. **Is the evidence real (Stage 2) or just metadata vibes?**  
   If `facet_scores.stage == stage2`, inspect `evidence_chunks[ix]` as the facet-grounded excerpt. If it’s `stage1`, you’re relying on the metadata view; consider improving metadata text or increasing prune size so Stage 2 can evaluate more papers.

If you keep a tight loop of: **inspect top facets → inspect evidence (if available) → adjust facet plan / thresholds / pruning**, you can usually make ranking improvements without guesswork.
