# P0.1 Validation Report — Remove lane isolation

Run compared: `4af2666be828e5054ccf4d31`

- **Before snapshot:** `sources-v2/runs/_snapshots/4af2666be828e5054ccf4d31__before_p0_1_lane_isolation__20260301_122746/`
- **After snapshot:** `sources-v2/runs/_snapshots/4af2666be828e5054ccf4d31__after_p0_1_lane_isolation__20260301_125356/`

## 1) Core acceptance checks

### A1) Authority lane can contain match-only papers (and rerank them)

These ids were **absent** from `authority/with_abstract` **before**, but are present **after** (rank in `rankings_stagei.json → rankings.authority.with_abstract`):

- `10.1111/ijcs.13067`: before `None` → after `16`
- `10.1080/08961530.2020.1712293`: before `None` → after `36`
- `10.1016/j.caeai.2024.100246`: before `None` → after `37`

All 3 are within the rerank window (`top_k_pre=40`) after the change.

### A2) Authority lane universe is no longer provenance-capped

From **after** `metrics.json → stages.phase_f.counts.prune`:

- `with_abstract` available candidates: `match=43530`, `authority=43530`
- `without_abstract` available candidates: `match=21346`, `authority=21346`
- `authority/without_abstract` after relevance gate: `14091` (expected; this gate already existed)

Intent mix in the **after** authority shortlist (`kept_intent_mix.authority.with_abstract`):

- `match_only: 521`, `authority_only: 47`, `both: 32`

This is the direct “lane isolation is gone” proof: the authority shortlist is now mostly `match_only` provenance.

### A3) Rerank volume unchanged

- `cache/rerank/*.json`: `160` files (before) and `160` files (after)
- `rerank_results.jsonl`: `160` lines (before) and `160` lines (after)

### A4) Match lane regression check (with_abstract)

Set-diff on `rankings_stagei.json → rankings.match.with_abstract[:40]`:

- kept `38`, new `2`, dropped `2` (very stable)

`match/without_abstract[:40]` is identical (kept `40`).

## 2) Observed side effect (expected): authority relevance drift increased

`authority/with_abstract` changed materially (top40 set diff):

- kept `12`, new `28`, dropped `28`

Example: the canonical review `10.1145/3290605.3300733` (“23 Ways to Nudge”) moved:

- `authority/with_abstract`: rank `1` → rank `61` (no longer reranked)
- but it remains strong in `match/with_abstract`: rank `8` → rank `13`

The new `authority/with_abstract` top ranks include more generic “AI trust / LLM / ML” survey material, which may be off-topic for the chapter depending on your intended authority-lane semantics.

**Recommendation:** land **P0.3 authority relevance gating for `with_abstract`** next (anchor/facet-based topical gate), now that authority uses the full universe.

