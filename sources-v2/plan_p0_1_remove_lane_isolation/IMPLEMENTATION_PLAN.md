# P0.1 — Remove provenance-based lane eligibility (“lane isolation”)

**Decision:** **Go with revisions** (high-impact, but the plan needs to be made implementation- and verification-complete).

This document is a hand-off ready implementation plan for updating the two-lane pipeline in `sources-v2/sources_two_lane.ipynb`.

---

## 0) High-impact gate

**Targets a major failure mode:** yes — lane composition is currently determined by *which query retrieved a record* (`candidate.intents`), not by the unified candidate universe + lane scoring.

**Primary objective improved:**

- **Top‑N ordering quality** (especially `authority/with_abstract`)
- **Reproducibility / stability** (lane membership stops depending on retrieval provenance quirks)

**Constraint honored:** rerank volume stays fixed (`rerank_top_k_pre` unchanged).

---

## 1) Problem statement (evidence + scope)

### Affected slice

- **Phase F (cell “Phase F — …”, section `# F5: Prune after Stage 1`)**
- **Lane/pool:** primarily `authority/with_abstract` (but the issue is symmetric: match lane also excludes `authority`-only candidates)
- **Ranking artifacts impacted:** `runs/<run_id>/shortlists_stage1.json` → `rankings_stageg.json` → `rankings_stagei.json` → `output.json`

### Concrete evidence (artifact-based)

Use the existing example run:

- `run_id = 4af2666be828e5054ccf4d31` (dir: `sources-v2/runs/4af2666be828e5054ccf4d31/`)
- `query_plan.json` topic: decision confidence / heuristics & biases / digital nudging in online purchase contexts (anchors include “Decision Confidence”, “Digital Nudging”, “Perceived Risk”, “Consumer Electronics”, “Online Trust”).

**E1 — Authority lane is constrained to a tiny provenance subset**

In this run’s candidate universe (`candidates_normalized.jsonl`):

- total `with_abstract` candidates: **43,504**
- `authority`-intent `with_abstract` candidates: **1,702** (≈3.9%)

So `authority/with_abstract` selection is forced to come from a small provenance-defined slice, regardless of what the global lane scores would prefer.

**E2 — “Missed must-have” examples (match-only, high-authority, not eligible today)**

The following **match-only** candidates are absent from `rankings_stagei.json → rankings.authority.with_abstract` solely because `lane in candidate.intents` is required in Phase F pruning:

- `10.1111/ijcs.13067` — *The influence of perceived risk on purchase intention in e‑commerce—Systematic review …* (intents: `['match']`)
- `10.1016/j.caeai.2024.100246` — *Integrating the adapted UTAUT model … trust and perceived risk …* (intents: `['match']`)
- `10.1080/08961530.2020.1712293` — *The Impact of Perceived Usefulness of Online Reviews, Trust and Perceived Risk …* (intents: `['match']`)

Each of these would rank very highly by `authority_lane` if the authority lane used the unified universe (verified by recomputing top‑600 `authority_lane` using `scores_stage1.jsonl` without provenance filtering).

**E3 — “Bad top‑N authority/with_abstract” examples (off-topic drift)**

Current `authority/with_abstract` top ranks include items that are clearly off-topic relative to `query_plan.json` anchors (examples from `shortlists_stage1.json` / `rankings_stagei.json`):

- `10.1097/inf.0000000000003499` — *Effective Approaches to Combat Vaccine Hesitancy*
- `10.1145/3579520` — *Reviewing Interventions to Address Misinformation …*
- `10.3390/su16031166` — *Enhancing Work Productivity through Generative Artificial Intelligence …*

Lane isolation contributes because it **prevents** highly relevant match-only high-authority items from ever competing in the authority lane, so off-topic authority-provenance items can survive in the top segment.

### Root cause (confirmed in code)

In `sources-v2/sources_two_lane.ipynb` Phase F pruning:

- `_eligible(cid, lane)` is `lane in intents_by_id[cid]`
- Every lane/pool shortlist filters by `_eligible(...)`
- An explicit assertion enforces “lane isolation” (`# Assertion: lane isolation`)

---

## 2) Change hypothesis (why this works + side effects)

### Mechanism

Change the lane definition from:

- “a paper is eligible for a lane if it was retrieved by that lane’s queries”

to:

- “a paper is eligible for all lanes; lanes differ by **lane scoring + topical gating**, not retrieval provenance”

This ensures:

- any relevant canonical paper can compete in the authority lane (even if retrieved only by match queries)
- any relevant high-authority paper retrieved only by authority queries can compete in the match lane
- lane membership becomes stable under small retrieval/query-builder variations

### Predicted side-effects (must be handled)

- **Authority lane can drift more** if topical gating is not explicit (because the authority lane now considers the full universe).
- **Stage 2 workload may increase** in runs where `authority`-intent pools are < `prune_n1` (Stage2 uses the union of both with-abstract shortlists).
- **Lane overlap will increase** (expected) — the two lanes become two orderings over the same universe, not two disjoint universes.

Success is therefore defined by *quality + stability* checks (below), not by “overlap increased” alone.

---

## 3) New contract (lane semantics)

### Lane eligibility

- **All candidates are eligible for both lanes** (subject only to pool separation + lane-specific topical/hygiene gates).
- `candidate.intents` remains **provenance/debug only**.

### Pool non-mixing (unchanged invariant)

- `with_abstract` and `without_abstract` are never mixed in shortlist/rank/rerank/output.

---

## 4) Implementation (exact edits)

### 4.1 Phase F — remove provenance eligibility from pruning

File: `sources-v2/sources_two_lane.ipynb`

Locate Phase F section:

- search `# F5: Prune after Stage 1`
- search `def _eligible`
- search `# Assertion: lane isolation`

**Change A — shortlist filtering**

Replace:

- `rows = [r for r in stage1_records if pool==... and _eligible(id, lane)]`

With:

- `rows = [r for r in stage1_records if pool==...]`
- keep existing `authority/without_abstract` relevance gate (`NOABS_AUTH_MIN_MATCH` OR `_anchor_hit_meta`) as-is

**Change B — remove lane isolation assertion**

Remove the loop that asserts `not bad` based on `_eligible`.

Replace with a correctness check that still matters under the new contract:

- all shortlist ids exist in `record_by_id`
- all shortlist ids match the target `pool`
- shortlist lengths are `<= keep`

**Change C — keep provenance only**

Keep `intents_by_id` (optional) only for diagnostics, e.g. to print:

- among kept ids per lane/pool: counts of `match-only`, `authority-only`, `both`

But do not use it as a hard filter.

### 4.2 Phase F — Stage2 selection (no change in volume contract)

Keep:

- `stage2_ids = union(match.with_abstract shortlist, authority.with_abstract shortlist)`

This does not increase rerank volume and is consistent with “lanes share universe” semantics.

### 4.3 Downstream phases (no algorithm changes required)

No Phase G/H/I/K logic needs changes because they already consume:

- `shortlists_stage1.json` (lane/pool ids)
- `scores_stage2.jsonl` for Stage2-scored ids
- rerank tasks drawn from lane/pool rankings top‑K

---

## 5) Reproducibility & cache invalidation

This change alters **which ids** enter Phase G and therefore all downstream artifacts.

### Minimum rerun scope

Re-run:

- **Phase F → Phase K**

### Recommended invalidation (to avoid stale artifacts)

For the test run directory, delete before rerun:

- `shortlists_stage1.json`
- `scores_stage2.jsonl` (Stage2 subset changes)
- `scores_final.jsonl`, `rankings_stageg.json`
- `coverage_tags.jsonl` (rewrites `scores_final.jsonl`)
- `rerank_results.jsonl`, `rankings_stagei.json`
- `output.json`

Keep retrieval caches (`cache/`, `*_raw.jsonl`, `candidates_normalized.jsonl`) unless you are intentionally re-testing retrieval.

---

## 6) Observability & QC (additions)

Add Phase F counters/prints (artifact-based, deterministic):

- `available_total[lane][pool]` (pre-gate count; now identical across lanes per pool)
- `available_after_gate[lane][pool]` (post-gate, e.g. authority/no-abs)
- `kept[lane][pool]`
- provenance mix in kept sets:
  - `kept_intents_match_only`, `kept_intents_authority_only`, `kept_intents_both`

These should be written to `metrics.json` under `stages.phase_f` in addition to being printed.

---

## 7) Verification plan (acceptance criteria)

### Baseline run(s)

- Baseline artifacts: `sources-v2/runs/4af2666be828e5054ccf4d31/`
- Record the baseline copies of:
  - `shortlists_stage1.json`
  - `rankings_stagei.json`
  - `output.json`

### Comparison run(s)

Re-run **Phase F → K** after implementing the change (same inputs, same run directory, or copy baseline artifacts first).

### Acceptance tests

**A1 — Authority lane includes match-only canonical items**

In the comparison run:

- the “missed must-have” ids listed in **E2** appear in `rankings_stagei.json → rankings.authority.with_abstract` (ideally within top‑200; top‑40 preferred)

**A2 — Authority lane pool sizes are no longer provenance-capped**

In Phase F logs/metrics:

- `available_total['authority']['with_abstract'] == total_with_abstract_candidates` (not ≈ authority-intent count)
- `available_total['match']['with_abstract'] == total_with_abstract_candidates` (symmetry)

**A3 — Top‑N quality does not regress**

In the comparison run’s `authority/with_abstract` top‑20:

- off-topic exemplars from **E3** are removed from top‑20 (or move materially down), replaced by on-topic candidates (judged by anchor hits and/or facet coverage tags)

**A4 — Rerank volume unchanged**

- Phase I tasks remain `4 * rerank_top_k_pre` (typically 160)

**A5 — Reproducibility**

- Re-running Phase F → K twice (with caches unchanged) yields identical `rankings_stagei.json` and `output.json` (byte-identical preferred; if timestamps differ, ids/order must match)

### Quick regression checks (must not worsen)

- `match/without_abstract` top results remain sensible (no new systematic junk).
- pool non-mixing holds in output (`output.json` lists contain only ids from the correct pool).

---

## 8) Notes / optional follow-up

Removing lane isolation increases the need for **explicit authority relevance gating** (see P0.3 in `sources-v2/TWO_LANE_PIPELINE_FIXES.md`). If the authority lane becomes broader but less relevant, land P0.3 immediately after (or in the same PR) to keep authority results on-topic without increasing rerank volume.

