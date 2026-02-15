# Two-Lane Pipeline — Fix List (Hand-off to Developer)

Context:

- Audit report: `sources-v2/runs/d5a67f10a618dec647502773/TWO_LANE_PIPELINE_AUDIT.md`
- Notebook implementation: `sources-v2/sources_two_lane.ipynb`
- Blueprint/target design: `sources-v2/TWO_LANE_PIPELINE_IMPLEMENTATION_PLAN_FROM_REPORT.md`
- Constraints: optimize for **result quality** (precision + recall + usability); **artifact-only validation**; **no micro tuning**.

This document lists **high-impact** fixes only, with implementation-level guidance and concrete “done when” criteria.

---

## P0 — Must-fix (quality/usability blockers)

### P0.1 Remove provenance-based lane eligibility (“lane isolation”)

**Problem:** The authority lane is built from query provenance (`candidate.intents`) rather than from the unified candidate universe. In the audited run, only **231 / 9,245** candidates were authority-eligible, meaning canonical results retrieved by `match` queries (e.g., `10.1017/chol9780521780537`) can never appear in the authority lane or be reranked there.

**Root cause:** In Phase F shortlisting, `_eligible(cid, lane)` is implemented as `lane in intents_by_id[cid]`, and every shortlist filters with `_eligible(...)` plus an explicit “lane isolation” assertion.

**Fix (implementation):** Build both lanes from the **same candidate universe** and differentiate lanes by **scoring + topical gating**, not by which query retrieved the item. Keep `candidate.intents` only as provenance/debug info. Concretely: remove `_eligible(...)` from the Phase F shortlist filter; remove/replace the “lane leak” assertion; and ensure Stage 2 / rerank selection is driven by lane scores (and optional anchor gates), not by provenance.

**Done when (acceptance):**

- Authority lane contains canonical items even if they came only from `match` queries.
- Authority lane pool sizes are comparable to match lane pool sizes (no tiny “authority-only” universe).
- `rankings_stagei.json` shows materially higher overlap between `match/*` and `authority/*` (expected when both lanes draw from the same universe).

**Where to change:**

- `sources-v2/sources_two_lane.ipynb` — search `def _eligible` and `# Assertion: lane isolation`.

---

### P0.2 Add hard hygiene filters for reviews/paratext and TOC-like abstracts

**Problem:** Paratext/review records appear in the top results (e.g., `Choice Reviews Online`; explicit `Book Review:` titles). The current paratext filter only matches a few prefixes (`editorial`, `preface`, etc.) and misses high-frequency “review-like” noise that is not useful as a scientific source for chapter writing.

**Root cause:** `_PARATEXT_RE` is too narrow, and hygiene relies on provider flags like `is_paratext:false` that don’t reliably exclude review venues in OpenAlex/S2. Coverage/rerank can also be fooled by TOC-like “abstracts” that are actually chapter lists.

**Fix (implementation):** Introduce **hard exclusion** (or at minimum “always downrank”) rules before scoring/rerank:

- Exclude by **venue**: `Choice Reviews Online` (and similar known review outlets).
- Exclude by **title patterns**: `^Book Review:` / `Review of` / `Recension` / `Rezension` / `From the Editor` / `New Book Chronicle`, etc.
- Detect **TOC-like abstracts** (many numbered items, “Contents”, dense chapter headings, repeated delimiters) and treat them as low-quality text:
  - Either drop such candidates outright (recommended for usability), or
  - Strip TOC sections before embedding/rerank evidence extraction so they can’t dominate relevance signals.

**Done when (acceptance):**

- `Choice Reviews Online` count in top-200 rankings is **0** for all lane/pool outputs.
- `Book Review:` titles are **0** in all top ranks.
- Rerank no longer awards high scores primarily due to TOC/chapter-list text.

**Where to change:**

- `sources-v2/sources_two_lane.ipynb` — search `_PARATEXT_RE`, `is_paratext_title`, and the candidate normalization section in Phase E.

---

### P0.3 Make the authority lane relevance-safe (anchor gating for _with_abstract_ too)

**Problem:** The authority lane surfaces off-topic, high-citation items (e.g., comparative political economy/anthropology) because “authority” is currently allowed to mean “highly cited + vaguely institutional”.

**Root cause:** Authority lane selection uses authority scoring but does not enforce explicit topical anchors for `with_abstract`. The only strict topical gate in the notebook is currently applied to `authority/without_abstract` (metadata-only safety gate), not to `authority/with_abstract`.

**Fix (implementation):** Enforce explicit topical gating for authority lane _before_ shortlisting and rerank:

- Require at least one **primary context anchor** (from `query_plan.json.primary_context_anchors`) in title+abstract.
- Optionally require one **economy/fiscal anchor** (a small list derived from key facets) to prevent generic “state”/“institutions” papers from passing.
- Apply the same gating to S2 recommendations before adding them to the candidate pool.

**Done when (acceptance):**

- Obvious off-topic authority-top results disappear without needing score-weight tweaks.
- Authority top-20 stays focused on the chapter’s domain while still preferring high-authority works.

**Where to change:**

- `sources-v2/sources_two_lane.ipynb` — Phase F shortlist building (authority lane filters).

---

### P0.4 Fix S2 recommendations expansion: add provenance + relevance gating (or disable)

**Problem:** `candidates_expanded.jsonl` adds +1,345 S2-recommended candidates, but all of them have `sources=None` (no provenance). Some reach the final shortlist and are irrelevant (e.g., modern bibliometrics).

**Root cause:** The recommendation expansion path adds candidates but does not populate the `sources` field and does not apply the same anchor/exclusion gates.

**Fix (implementation):**

- Populate provenance when expanding from `semanticscholar_recommendations.jsonl` (e.g., `sources=[{provider:'semanticscholar_recommendations', seed_paperId, rank, intent:'match'}]`).
- Apply the same **anchor + hygiene** filters used for authority/match shortlisting to recommendations before scoring/rerank.
- If provenance + gating cannot be implemented quickly, **disable** recommendation expansion to avoid injecting untraceable noise.

**Done when (acceptance):**

- All expanded candidates have non-null `sources` provenance.
- No recommendation-derived candidates reach the shortlist unless they pass the same relevance/hygiene rules as normal candidates.

**Where to change:**

- `sources-v2/sources_two_lane.ipynb` — Phase F “S2 recommendations” section.

---

### P0.5 Implement the missing final output contract (`output.json`)

**Problem:** The pipeline does not emit a single consumable artifact; users must manually interpret multiple intermediate files (`rankings_stagei.json`, `scores_final.jsonl`, `rerank_results.jsonl`, etc.).

**Root cause:** The notebook stops at Phase I and doesn’t implement the blueprint’s output contract (and the blueprint’s later phases like diversity top-up / final formatting).

**Fix (implementation):** Emit a stable `output.json` in the run directory that contains the final curated results:

- For each lane/pool, include top-N “source cards” with: id/doi/title/year/venue/citations/url/provider_ids, lane scores, coverage tags + excerpts, and rerank rationale/score.
- Include run metadata: run_id, created_at, input title/spec, pipeline_version/config hash, git commit hash.
- (Optional but recommended) include facet coverage summaries and a “coverage top-up” list if you implement Phase J/K from the blueprint.

**Done when (acceptance):**

- `sources-v2/runs/<run_id>/output.json` exists after a run and can be used directly by a chapter-writing workflow.
- The schema is stable across runs (versioned if needed).

**Where to change:**

- `sources-v2/sources_two_lane.ipynb` — after Phase I completes (`rankings_stagei.json` exists).
- Blueprint reference: `sources-v2/TWO_LANE_PIPELINE_IMPLEMENTATION_PLAN_FROM_REPORT.md` (Output contract + Phases J/K).

---

## P1 — High leverage stabilizations / precision upgrades

### P1.1 Make query generation robust to truncation / invalid JSON

**Problem:** The OpenAlex query builder had multiple recoverable failures (`openai_call_failed`: max output tokens, invalid JSON). This can still fail hard in other runs.

**Root cause:** Large LLM outputs + insufficient schema/continuation strategy.

**Fix (implementation):** Use strict structured output and chunking:

- Generate queries in smaller batches (e.g., per language × per intent).
- Enforce a JSON schema response format (and validate/repair on the fly).
- Add a continuation mechanism (“emit next N queries starting at index K”) so retries don’t restart from scratch.

**Done when (acceptance):**

- Query builders consistently produce parseable JSON in one pass (or recover deterministically).
- `logs.jsonl` shows **0** query-builder failures across several runs.

---

### P1.2 Fix/replace OpenAlex “authority” query patterns that drift off-topic

**Problem:** Authority queries using `default.search` (even with `is_core`) admit off-topic, highly cited material that later stages must filter out.

**Root cause:** `default.search` is less controlled than `title_and_abstract.search` and is not anchored tightly enough to the chapter context.

**Fix (implementation):** Prefer topical search fields and anchor constraints for authority queries:

- Use `title_and_abstract.search` with explicit primary anchors and economics/fiscal anchors.
- Consider removing `default.search` authority queries entirely if they cannot be made relevance-safe.
- Apply `global_exclusions` downstream as hard filters for authority-lane candidates (when query-side NOT is not reliable).

**Done when (acceptance):**

- Authority candidate pool is large (good recall) but stays on-topic without relying on rerank to “clean it up”.

---

### P1.3 Make coverage tagging evidence more reliable (prevent TOC/paratext from becoming “evidence”)

**Problem:** Coverage tags and rerank prompts can be driven by TOC-like text and paratext titles, causing inflated facet coverage and LLM scores for unusable sources.

**Root cause:** Evidence extraction uses fallback excerpts for `without_abstract` and may treat chapter lists as semantically rich evidence.

**Fix (implementation):**

- For `without_abstract`, downgrade confidence or avoid producing coverage tags beyond “very low confidence” unless other evidence exists.
- For `with_abstract`, remove/ignore TOC-like spans before chunking and evidence selection.
- Add a “hygiene_flags” field that rerank sees explicitly (e.g., `possible_toc`, `review_like`) so the LLM can downrank.

**Done when (acceptance):**

- Coverage excerpts look like genuine summaries/claims, not chapter lists.
- Rerank rationales reference real evidence rather than TOCs.

---

### P1.4 Add run metadata + reproducibility guards (prevent mixed/incompatible artifacts)

**Problem:** Some key run inputs (chapter title/spec, pipeline version) are not carried into `query_plan.json`, and observability is split between `run.log` and `logs.jsonl`.

**Root cause:** Metadata isn’t persisted as a first-class artifact; `run.log` is incomplete in the audited run dir.

**Fix (implementation):**

- Write a `run_meta.json` at Phase A with all inputs and config hashes (including the notebook/pipeline version and git commit).
- Treat `logs.jsonl` as the source of truth (or ensure `run.log` is complete for all phases, not only early failures).

**Done when (acceptance):**

- A run directory is self-contained: you can reconstruct inputs, config, and outputs without external state.

---

### P1.5 Reduce over-pruning if cost/time are not constraints

**Problem:** Stage 2 scoring and rerank only see a limited slice of candidates. If early pruning excludes high-quality but slightly lower stage-1 hits, recall suffers.

**Root cause:** Fixed shortlist sizes (`prune_n1`, etc.) and Stage 2 restricted to shortlist.

**Fix (implementation):** Increase the candidate budget for Stage 2 + rerank or move pruning later:

- Score more (or all) `with_abstract` candidates in Stage 2 if feasible, then prune.
- Rerank more than top-40 per lane/pool (or add an adaptive rerank budget based on score uncertainty).

**Done when (acceptance):**

- Canonical-but-not-perfectly-ranked items still have a path to reach the final top ranks.
- Quality improves without needing score weight tuning.

---

## Suggested verification checklist (artifact-only)

After implementing the above, validate using only run artifacts (no web):

- Hygiene: counts of `Choice Reviews Online` and `Book Review:` in top-200 are zero across all lane/pool outputs.
- Lane health: authority lane size is not tiny; authority top ranks include canonical domain sources even if retrieved by match queries.
- Recommendation provenance: every expanded candidate has provenance; shortlist contains no modern bibliometric drift.
- Output contract: `output.json` exists and contains all final cards with rerank + coverage evidence.
- Logs: query builder and rerank are stable (no repeated schema/JSON failures).
