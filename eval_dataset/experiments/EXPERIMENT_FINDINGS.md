# Experiment Findings Log

Goal: scientifically improve the literature-retrieval pipeline so it reliably ranks the best sources highest **across different chapter types** (not overfitting to one chapter).

This file is an **append-only lab notebook**: after each run where you paste results, we record:
- what changed,
- what dataset + labels were used,
- what the metrics say,
- what decision we take next.

---

## Current evaluation setup (pinned)

- Chapters: `platform_theory`, `platform_methodology`, `platform_empirical_case`
- Dataset tag (current benchmark):
  - `stageB_coverage_v1_v1__platform_methodology_labels_v2_b62a29d1b69b__platform_empirical_case_labels_v3_3e82ebaea202__platform_theory_labels_v3_96297d620195`
- Label source: `eval_dataset/eval_rubrics` + adjudication patches (methodology v2, empirical v3, theory v3; applied with confidence≥70)
- Primary metric (selection): `ndcg@20` on `__ALL__` macro row
- Secondary metrics: `p@20`, `mrr_include`, `auc_include`

---

## Findings (chronological)

### 2026-01-30 — Stage B A/B (end-to-end dataset rebuild)

**What changed**
- Compared Stage B blueprint variants **baseline** vs **coverage_v1** (true end-to-end: new candidate pools + new labeled datasets).

**Datasets**
- `eval_dataset/datasets/stageB_baseline_v1/labeled_dataset.csv`
- `eval_dataset/datasets/stageB_coverage_v1_v1/labeled_dataset.csv`

**Result**
- Winner: `coverage_v1` (large improvement across metrics).
- Macro deltas (coverage − baseline):
  - `ndcg@20`: `+0.077777`
  - `p@20`: `+0.116667`
  - `mrr_include`: `+0.601147`
  - `auc_include`: `+0.149065`

**Artifacts**
- `eval_dataset/experiments/20260130_180516_stageB_ab_compare.csv`
- Logged in `eval_dataset/experiments/runs.csv` (`experiment=stageB_ab_eval`)

**Decision**
- ✅ Stage B finalized to `coverage_v1`.

---

### 2026-01-30 — Stage C weight grid search (on Stage B winner dataset)

**What changed**
- Tuned Stage C scoring weights on the pinned dataset `stageB_coverage_v1_v1`.

**Best macro (by `ndcg@20`)**
- `w_embed_max=0.0`, `w_embed=0.7`, `cite_weight=0.08`
- Macro: `ndcg@20≈0.657353`, `p@20≈0.166667`, `mrr_include≈0.672414`, `auc_include≈0.809621`

**Generalization check**
- LOCO avg holdout `ndcg@20≈0.638579` (leave-one-chapter-out selection).

**Artifacts**
- `eval_dataset/experiments/20260130_184909_7370e7a6e85f_stageC_grid_v1_sweep.csv`
- `eval_dataset/experiments/20260130_184909_7370e7a6e85f_stageC_grid_v1_loco.csv`
- Logged in `eval_dataset/experiments/runs.csv` (`experiment=stageC_grid_v1_best`)

**Decision**
- ✅ Stage C finalized to the grid-search winner.

---

### 2026-01-31 — Stage C.3 LLM rerank v1 (full rerank, API)

**What changed**
- Tested an LLM scoring model (`gpt-5-nano`) to rerank *all* docs in the dataset (660 requests).

**Result**
- Full LLM rerank **worse** than `score_stageC_final` on macro ranking quality:
  - `score_stageC_final`: `ndcg@20≈0.657353`, `mrr_include≈0.672414`, `auc_include≈0.809621`
  - `score_llm_rerank_v1`: `ndcg@20≈0.638844`, `mrr_include≈0.500000`, `auc_include≈0.763654`
  - Delta (LLM − StageC_final): `ndcg@20≈-0.01851`, `mrr_include≈-0.172414`, `auc_include≈-0.045967`

**Cost**
- ~660 requests, cost ≈ **$0.305** (single run; cached outputs stored on disk).

**Artifacts**
- `eval_dataset/experiments/20260131_094226_7370e7a6e85f_stageC3_rerank_v1_scored.csv`
- `eval_dataset/experiments/20260131_094226_7370e7a6e85f_stageC3_rerank_v1_eval.csv`
- `eval_dataset/experiments/20260131_094226_7370e7a6e85f_stageC3_rerank_v1_cost.csv`
- Logged in `eval_dataset/experiments/runs.csv` (`experiment=stageC3_rerank_v1`)

**Decision**
- ❌ Do not use “full rerank v1” in production.
- Next: test whether LLM signal helps *only as a shortlist/tie-breaker* (cheap realistic usage).

---

### 2026-01-31 — Stage C.3 offline analysis (no API): “use LLM as a weak signal”

**What changed**
- Reused the saved scored CSV from the full rerank run and tested two offline strategies:
  1) **Score fusion**: mix `score_stageC_final` with chapter-normalized LLM score.
  2) **Top-N rerank**: only rerank inside the Stage C top-N shortlist using LLM.

**Results (macro)**
- Baseline: `score_stageC_final ndcg@20≈0.657353`

**(1) Score fusion**
- Best `alpha_llm=0.20`
- `ndcg@20≈0.698042`, `p@20≈0.183333`, `mrr_include≈0.673077`, `auc_include≈0.830124`
- Delta vs StageC_final: `+0.040688 ndcg@20`

**(2) Top-N rerank**
- Best `topn=50`
- `ndcg@20≈0.704317`, `p@20≈0.183333`, `mrr_include≈0.672414`, `auc_include≈0.814356`
- Delta vs StageC_final: `+0.046963 ndcg@20`

**Artifacts**
- `eval_dataset/experiments/20260131_102202_7370e7a6e85f_stageC3_mix_sweep_v1.csv`
- `eval_dataset/experiments/20260131_102202_7370e7a6e85f_stageC3_topn_sweep_v1.csv`

**Important caveat**
- These best settings were selected on the same dataset they’re evaluated on → **potential overfitting**.

**Next step**
- Run **LOCO** selection for `alpha_llm` and `topn` (choose on 2 chapters, evaluate on the 3rd) to confirm the improvement generalizes.

---

### 2026-01-31 — Stage C.3 LOCO validation (no API): confirm generalization

**What changed**
- Validated the offline gains with **LOCO** (leave-one-chapter-out):
  - choose `alpha_llm` / `topn` on 2 chapters (train),
  - evaluate the chosen parameter on the 3rd chapter (holdout),
  - report holdout deltas vs the Stage C baseline.

**Result: score fusion**
- Selected `alpha_llm=0.20` for all three holdouts.
- Avg LOCO holdout:
  - `ndcg@20≈0.698042`
  - Delta vs Stage C: `+0.040688 ndcg@20`
- Holdout deltas vs Stage C:
  - `platform_empirical_case`: `+0.066688`
  - `platform_methodology`: `+0.000000`
  - `platform_theory`: `+0.055377`

**Result: top-N shortlist rerank**
- Selected `topn=50` for all three holdouts.
- Avg LOCO holdout:
  - `ndcg@20≈0.704317`
  - Delta vs Stage C: `+0.046963 ndcg@20`
- Holdout deltas vs Stage C:
  - `platform_empirical_case`: `+0.072752`
  - `platform_methodology`: `+0.000000`
  - `platform_theory`: `+0.068138`

**Artifacts**
- `eval_dataset/experiments/20260131_103051_7370e7a6e85f_stageC3_mix_loco_v1.csv`
- `eval_dataset/experiments/20260131_103051_7370e7a6e85f_stageC3_topn_loco_v1.csv`

**Decision (provisional “final”)**
- ✅ Stage C.3 should be implemented as: **rerank only within the Stage C top-50 shortlist** using the LLM signal.
- Rationale: best LOCO `ndcg@20`, and it’s cost-efficient in production (only ~50 LLM calls per chapter).

**Next step**
- Optional refinement: test a blended within-topN score (mix Stage C + LLM within the shortlist) to see if it beats “pure LLM order in top-50”.

---

### 2026-01-31 — Stage C.3 refinement (no API): top-50 blend (Stage C + LLM) within shortlist

**What changed**
- Tested a refinement of Stage C.3 on the scored rerank CSV:
  - shortlist = top-50 by `score_stageC_final`
  - within shortlist, order by `1 + ((1−beta)*score_stageC_final + beta*llm_norm)`
  - outside shortlist, keep Stage C order.

**Macro sweep**
- Best macro (single-dataset) `ndcg@20≈0.709987` at many `beta` values (`beta≈0.35…0.95` all tied).

**LOCO result (generalization)**
- Avg LOCO holdout `ndcg@20≈0.703793`
- Avg delta vs Stage C baseline: `+0.046440 ndcg@20`
- Holdout deltas vs Stage C:
  - `platform_empirical_case`: `+0.072752`
  - `platform_methodology`: `+0.000000`
  - `platform_theory`: `+0.066566`

**Artifacts**
- `eval_dataset/experiments/20260131_104816_7370e7a6e85f_stageC3_topn_blend_beta_sweep_v1.csv`
- `eval_dataset/experiments/20260131_104816_7370e7a6e85f_stageC3_topn_blend_beta_loco_v1.csv`

**Decision**
- Keep the simpler Stage C.3 final: **pure LLM ordering within top-50**.
- Reason: the blend’s LOCO avg is slightly worse than pure top-50 rerank (`0.703793` vs `0.704317`).

---

### 2026-01-31 — Stage D (diversity selection) sweep v1: TF-IDF MMR over shortlist

**What changed**
- Tested a Stage D selection step on top of finalized Stage C.3:
  - Baseline ranking: `score_stageC3_topn_final`
  - Build a per-chapter shortlist pool (top-`topm`)
  - Compute TF-IDF cosine similarity within the pool
  - Select top-20 using MMR with parameter `lambda` (higher = more relevance, lower = more diversity)

**Baseline macro**
- `score_stageC3_topn_final`: `ndcg@20≈0.704317`, `p@20≈0.183333`, `auc_include≈0.814356`

**Best sweep result (macro)**
- `topm=150`, `lambda=1.0`
- `ndcg@20≈0.720766`, `p@20≈0.183333`, `auc_include≈0.824719`
- `mean_pairwise_sim_top20≈0.163598`

**Note on diversity tradeoff**
- More diverse settings exist (lower `mean_pairwise_sim_top20`) but reduced `ndcg@20` in this sweep.

**Artifacts**
- `eval_dataset/experiments/20260131_105825_7370e7a6e85f_stageD_mmr_tfidf_sweep_v1.csv`

**Interpretation / caution**
- The winner is `lambda=1.0` (pure relevance). That suggests the diversity penalty did not help relevance under current labels.
- The ndcg lift vs baseline may be influenced by tie-breaking inside the shortlist → validate with LOCO before finalizing.

**Next step**
- Run LOCO validation to pick `(topm, lambda)` on 2 chapters and evaluate on the 3rd.

---

### 2026-01-31 — Stage D (diversity selection) LOCO validation v1: TF-IDF MMR

**Result**
- LOCO-selected params (by holdout):
  - `platform_empirical_case`: `topm=100`, `lambda=1.0`
  - `platform_methodology`: `topm=150`, `lambda=1.0`
  - `platform_theory`: `topm=150`, `lambda=1.0`
- Avg LOCO holdout:
  - `ndcg@20≈0.720766`
  - Delta vs Stage C.3 baseline: `+0.016449 ndcg@20`
  - Mean pairwise similarity (top-20): `≈0.165248`
  - Similarity delta vs baseline: `≈-0.032354` (less redundant)

**Artifacts**
- `eval_dataset/experiments/20260131_111059_7370e7a6e85f_stageD_mmr_tfidf_loco_v1.csv`

**Interpretation**
- LOCO consistently selects `lambda=1.0` (i.e., “pure relevance” inside the shortlist).
- Gains appear to come from deterministic shortlist selection / tie-breaking effects, with a modest reduction in redundancy.

**Next step**
- Try a facet-aware diversity selector (using `facet_best_i`) to enforce broader coverage while preserving `ndcg@20`.

---

### 2026-01-31 — Stage D alternative sweep v1 (no API): facet-cap using `facet_best_i`

**What changed**
- Tested a facet-aware selector that caps how many items in the top-20 can come from the same facet (facet proxy = `facet_best_i`).

**Baseline**
- Baseline ranking: `score_stageC3_topn_final` with `ndcg@20≈0.704317`

**Sweep results (topm=150, k=20)**
- Best by `ndcg@20`:
  - `max_per_facet=3`: `ndcg@20≈0.716853`, `p@20=0.200000`, `auc_include≈0.851805`
  - `unique_facets_top20≈8.33`
- More facet coverage (but lower ndcg):
  - `max_per_facet=1`: `unique_facets_top20≈11.67`, `ndcg@20≈0.700214`
  - `max_per_facet=2`: `unique_facets_top20≈11.00`, `ndcg@20≈0.703773`

**Artifacts**
- `eval_dataset/experiments/20260131_112610_7370e7a6e85f_stageD_facet_cap_sweep_v1.csv`

**Next step**
- Run LOCO validation for `max_per_facet` (and optionally `topm`) to confirm it generalizes before finalizing.

---

### 2026-01-31 — Stage D alternative LOCO v1 (no API): facet-cap using `facet_best_i`

**Result**
- Avg LOCO holdout:
  - `ndcg@20≈0.684274`
  - Delta vs Stage C.3 baseline: `-0.020043 ndcg@20`
- Diversity proxies:
  - Avg similarity delta: `≈-0.001270` (almost unchanged)
  - Avg unique facets delta: `≈+3.33` (more facet coverage)

**Artifacts**
- `eval_dataset/experiments/20260131_113212_7370e7a6e85f_stageD_facet_cap_loco_v1.csv`

**Decision**
- ❌ Do not use facet-cap as the default Stage D: it substantially hurts relevance across chapters.
- Keep it as an optional “diversity mode” if you ever want maximum facet coverage (with known relevance tradeoff).

---

### 2026-02-01 — Stage C.3 stability fix v1 (no API): deterministic tie-break inside top-50

**What changed**
- Added a deterministic tie-break for the Stage C.3 shortlist rerank:
  - shortlist = top-50 by `score_stageC_final`
  - primary = normalized LLM score (within shortlist)
  - tie-breakers = `score_stageC_final` (and `score_cite_norm` if present), then stable id/index
  - assign unique rank scores (`2.0 - r*1e-6`) to eliminate score ties

**Why**
- Baseline `score_stageC3_topn_final` can have many equal values (LLM scores are integers → many ties after minmax), so tie-order depended on CSV row order.

**Result (macro)**
- Baseline: `score_stageC3_topn_final ndcg@20≈0.704317`
- Tie-break: `score_stageC3_topn_tiebreak_v1 ndcg@20≈0.709987`
- Delta (tiebreak − baseline):
  - `ndcg@20`: `+0.005670`
  - `auc_include`: `+0.002008`
  - `p@20`: `+0.000000`
  - `mrr_include`: `+0.000000`

**Artifacts**
- `eval_dataset/experiments/20260201_012959_7370e7a6e85f_stageC3_topn_tiebreak_v1_eval.csv`
- Appended to `eval_dataset/experiments/runs.csv` (`experiment=stageC3_topn_tiebreak_v1`)

**Decision**
- ✅ Adopt deterministic tie-break as the **final Stage C.3 scoring behavior** (more scientific/reproducible and slightly better).

**Next step**
- Re-test Stage D methods using this improved Stage C.3 baseline (to check whether prior Stage D gains were mostly tie-breaking).

---

### 2026-02-01 — Stage D sweep v2 (no API): TF‑IDF MMR on top of Stage C.3 tie-break baseline

**What changed**
- Re-ran the Stage D TF‑IDF MMR sweep, but now using the improved baseline `score_stageC3_topn_tiebreak_v1` (instead of the older `score_stageC3_topn_final`).

**Baseline macro**
- `score_stageC3_topn_tiebreak_v1 ndcg@20≈0.709987`

**Key result**
- Best `ndcg@20` in the sweep is **exactly equal** to baseline (`≈0.709987` at `lambda=1.0`).
- Interpretation: the earlier Stage D “relevance gains” were largely explained by fixing shortlist tie-handling (now moved into Stage C.3).

**Diversity note (secondary)**
- The sweep suggests we can reduce redundancy (lower TF‑IDF similarity proxy) with very small relevance impact by lowering `lambda` (e.g. `lambda≈0.6`).
- We must confirm this with LOCO using a consistent similarity measurement before adopting it as a default.

**Artifacts**
- `eval_dataset/experiments/20260201_122034_7370e7a6e85f_stageD_mmr_tfidf_sweep_v2.csv`

**Decision**
- Stage D is **not needed** for relevance once Stage C.3 tie-breaking is fixed.
- Keep Stage D as an optional “diversity mode” candidate and validate with LOCO (v2) next.

---

### 2026-02-01 — Stage D LOCO v2 (no API): diversity-mode selection hurts relevance on average

**What changed**
- LOCO selection for Stage D “diversity mode”:
  - On train (2 chapters): pick the setting with lowest redundancy (TF‑IDF sim) among those within `NDCG_DROP_MAX=0.01` of the baseline.
  - Evaluate that chosen setting on the holdout chapter.

**Result**
- Avg LOCO holdout:
  - `ndcg@20≈0.701988`
  - Delta vs baseline (`score_stageC3_topn_tiebreak_v1`): `≈-0.007999 ndcg@20`
  - Similarity delta: `≈-0.03838` (less redundant)
- Biggest failure mode: `platform_theory` holdout lost substantial relevance (`≈-0.0323 ndcg@20`).

**Artifacts**
- `eval_dataset/experiments/20260201_122748_7370e7a6e85f_stageD_mmr_tfidf_loco_v2.csv`

**Decision**
- ❌ Do not include Stage D as default (even as a “safe diversity mode”) under the current selection rule.
- If you want diversity in the UI later, we can expose it as an explicit toggle with a warning (“may reduce relevance”).

---

### 2026-02-01 — Stage C.3 TOPN tuning v2 (no API): top-50 remains optimal

**What changed**
- Swept shortlist size `TOPN` for Stage C.3 (with deterministic tie-break) to see if we can reduce production cost without losing relevance.

**Macro sweep result**
- Best: `TOPN=50` with `ndcg@20≈0.709987` (all smaller TOPN values dropped notably).
- Larger TOPN values (`75/100`) were worse, consistent with “LLM signal is helpful as a shortlist reranker, but harmful if applied too broadly.”

**LOCO**
- LOCO selected `TOPN=50` for all holdouts.
- Avg LOCO holdout `ndcg@20≈0.709987`.

**Artifacts**
- `eval_dataset/experiments/20260201_123141_7370e7a6e85f_stageC3_topn_tradeoff_sweep_v2.csv`
- `eval_dataset/experiments/20260201_123141_7370e7a6e85f_stageC3_topn_tradeoff_loco_v2.csv`

**Decision**
- ✅ Keep `TOPN=50` as the finalized Stage C.3 shortlist size.

---

### 2026-02-01 — Implementation fix: Stage C.3 top-50 model test v2 notebook stability + cost accounting

**What happened**
- The `st_stageC3_rerank_topn_model_v2` cell successfully produced 150 cached rerank results but crashed during merge due to a column name mismatch (`llm_score`/`llm_notes` vs `llm_score_topn_v2`/`llm_notes_topn_v2`).

**Fix**
- Standardized the shortlist scoring columns to `llm_score_topn_v2` + `llm_notes_topn_v2` and updated the merge accordingly.
- Corrected cost reporting so cached rerank results contribute `0` to “this run” cost/tokens/requests, while still reporting an “estimated total incl cached” number for reproducibility.

**Next step**
- Re-run `st_stageC3_rerank_topn_model_v2` to produce `*_stageC3_rerank_topn_model_v2_{scored,eval,cost}.csv` and compare `score_stageC3_topn_tiebreak_v2` vs `v1`.

---

### 2026-02-01 — Stage C.3 top-50 rerank model test v2: `gpt-5-mini` is worse than v1

**Setup**
- Evaluated the top-50 shortlist reranker using `gpt-5-mini` (`st_stageC3_rerank_topn_model_v2`).
- Compared against the existing Stage C.3 baseline (`score_stageC3_topn_tiebreak_v1`) from the pinned scored dataset.

**Cost (estimated total incl cached)**
- ~150 requests total (50 per chapter)
- `input_tokens≈77,162`, `output_tokens≈108,405`
- `cost_usd≈0.2361005`

**Macro result**
- Baseline: `score_stageC3_topn_tiebreak_v1 ndcg@20≈0.709987`, `mrr_include≈0.672414`, `auc_include≈0.816363`
- New: `score_stageC3_topn_tiebreak_v2 ndcg@20≈0.681493`, `mrr_include≈0.422414`, `auc_include≈0.813200`
- Delta (v2 − v1): `ndcg@20≈-0.028494`, `mrr_include≈-0.25`

**Per-chapter diagnosis (why it got worse)**
- `platform_theory` is the main failure:
  - `ndcg@20≈0.731333 → 0.661772` (Δ `≈-0.0696`)
  - first `include` moved from rank `1 → 4` (MRR include `1.0 → 0.25`)
- `platform_methodology` unchanged (still first include at rank `58`).
- `platform_empirical_case` slightly worse (`ndcg@20≈0.715248 → 0.699327`) but first include stays at rank `1`.

**Artifacts**
- `eval_dataset/experiments/20260201_133637_0d8287ddb87a_stageC3_rerank_topn_model_v2_scored.csv`
- `eval_dataset/experiments/20260201_133637_0d8287ddb87a_stageC3_rerank_topn_model_v2_eval.csv`
- `eval_dataset/experiments/20260201_133637_0d8287ddb87a_stageC3_rerank_topn_model_v2_cost.csv`
- Appended to `eval_dataset/experiments/runs.csv` (`experiment=stageC3_rerank_topn_model_v2`)

**Decision**
- ❌ Do not switch Stage C.3 to `gpt-5-mini` under the current prompt/rubrics.
- ✅ Keep Stage C.3 production model as `gpt-5-nano` (current best-performing + cheaper).

---

### 2026-02-01 — Stage C.3 downstream tuning attempt: re-tuning Stage C weights overfits (reject)

**Question**
- Should we retune Stage C weights (`w_embed_max`, `w_embed`, `cite_weight`) to optimize the *final* Stage C.3 output (instead of optimizing Stage C alone)?

**Method**
- Offline grid search using `*_stageC3_rerank_v1_scored.csv` (full LLM scores already present).
- For each weight triple:
  - Recompute `score_stageC_tmp` from `score_embed_max`, `score_embed_mean_top3`, `score_tfidf`, `score_cite_norm`
  - Apply the Stage C.3 deterministic top-50 rerank using `score_llm_rerank_v1`
  - Evaluate `ndcg@20` (macro)
- Validate with LOCO (select weights on 2 chapters, evaluate on holdout).

**Baseline (current production weights)**
- `w_embed_max=0.0`, `w_embed=0.7`, `cite_weight=0.08`
- `ndcg@20≈0.709987`

**Macro sweep (overfit)**
- Best macro weights: `w_embed_max=0.2`, `w_embed=0.7`, `cite_weight=0.12`
- `ndcg@20≈0.721354` (looks +`0.0114` better), but `auc_include` drops notably.

**LOCO (generalization)**
- Avg LOCO holdout `ndcg@20≈0.675814` (delta vs baseline `≈-0.03417`)
- Worst failure: holdout `platform_empirical_case` `ndcg@20≈0.619592` (delta `≈-0.09566`)

**Artifacts**
- `eval_dataset/experiments/20260201_150906_0d8287ddb87a_stageC3_stageC_joint_grid_v1_sweep.csv`
- `eval_dataset/experiments/20260201_150906_0d8287ddb87a_stageC3_stageC_joint_grid_v1_loco.csv`

**Decision**
- ❌ Do not retune Stage C weights based on this grid: it overfits and hurts LOCO generalization.
- ✅ Keep the existing Stage C weights as final.

---

### 2026-02-01 — Stage C.3 LLM bucketization v1: no effect (expected; implementation kept raw LLM ordering)

**What happened**
- Tested bucketing the `llm_score` within the top-50 shortlist (bucket sizes 1/2/5/10).
- Macro + LOCO were identical across all bucket sizes.

**Explanation**
- In v1 we sorted by `bucket` **and then by raw `llm_score`**, so the bucket size could not change ordering.
- Treat v1 as a “null test” (baseline sanity check).

**Artifacts**
- `eval_dataset/experiments/20260201_155806_0d8287ddb87a_stageC3_llm_bucket_sweep_v1.csv`
- `eval_dataset/experiments/20260201_155806_0d8287ddb87a_stageC3_llm_bucket_loco_v1.csv`

**Next step**
- Run v2 which removes raw-LLM ordering inside the bucket (bucket becomes the only LLM signal, with Stage C / citations as tie-breakers).

---

### 2026-02-01 — Stage C.3 LLM bucketization v2: still no effect (ordering already stable)

**Result**
- Even when using bucket-only LLM ordering (no raw `llm_score` tie-break inside buckets), bucket sizes `1/2/5/10/20` produced identical macro + LOCO metrics.

**Interpretation**
- For the current dataset, the Stage C + citation tie-breakers (and/or the distribution of `llm_score` in the top-50) already yield a stable ordering; coarsening the LLM signal does not change relevant rankings.

**Artifacts**
- `eval_dataset/experiments/20260201_160426_0d8287ddb87a_stageC3_llm_bucket_sweep_v2.csv`
- `eval_dataset/experiments/20260201_160426_0d8287ddb87a_stageC3_llm_bucket_loco_v2.csv`

**Decision**
- ❌ Do not add bucketization to the production pipeline (no measurable benefit).

---

### 2026-02-01 — Stage C rank-normalization vs minmax: worse (reject)

**Goal**
- Test if replacing per-chapter minmax normalization with rank/percentile normalization improves generalization.

**Result (macro)**
- Baseline `score_stageC3_topn_tiebreak_v1`: `ndcg@20≈0.709987`, `mrr_include≈0.672414`, `auc_include≈0.816363`
- Ranknorm `score_stageC3_ranknorm_tiebreak_v1`: `ndcg@20≈0.672150`, `mrr_include≈0.506536`, `auc_include≈0.806169`
- Delta (ranknorm − baseline): `ndcg@20≈-0.037837`, `mrr_include≈-0.165878`

**Observation**
- `platform_methodology` first include improved slightly (`58 → 51`), but `platform_empirical_case` got worse (`1 → 2`) and overall relevance dropped.

**Artifacts**
- `eval_dataset/experiments/20260201_163358_0d8287ddb87a_stageC3_stageC_norm_rank_v1_scored.csv`
- `eval_dataset/experiments/20260201_163358_0d8287ddb87a_stageC3_stageC_norm_rank_v1_eval.csv`

**Decision**
- ❌ Do not change Stage C normalization; keep current minmax-based approach.

---

### 2026-02-01 — Stage C.3 shortlist base-score column sweep v1: keep `score_stageC_final` (best macro, best LOCO)

**Question**
- Can we improve Stage C.3 by changing the *base score column* used to pick the top-50 shortlist?

**Macro sweep**
- Best macro remains `score_stageC_final` (`ndcg@20≈0.709987`).
- Some alternatives move the first `include` for `platform_methodology` far up (e.g. `score_tfidf` rank `4`, `score_stageC1` rank `5`), but their overall macro `ndcg@20` is much worse.

**LOCO**
- Selecting a base column on train chapters overfits and fails on holdout:
  - holdout `platform_empirical_case`: train picks `score_tfidf` → holdout `ndcg@20≈0.574966` (delta `≈-0.140282`).
- Avg LOCO holdout `ndcg@20≈0.663226` (delta vs baseline `≈-0.046761`).

**Artifacts**
- `eval_dataset/experiments/20260201_163950_0d8287ddb87a_stageC3_base_scorecol_sweep_v1.csv`
- `eval_dataset/experiments/20260201_163950_0d8287ddb87a_stageC3_base_scorecol_loco_v1.csv`

**Decision**
- ✅ Keep shortlist base score as `score_stageC_final` (production baseline).
- Follow-up idea: instead of switching the base score, test *shortlist expansion* (union of top-N from multiple signals) to bring rare `include` items into the rerankable set without harming other chapters.

---

### 2026-02-01 — Next test prepared: Stage C.3 shortlist expansion via union-of-toplists (offline)

**Why**
- Current best pipeline (`score_stageC3_topn_tiebreak_v1`) cannot improve `platform_methodology` because its first `include` is still around rank ~58 (outside the top-50 rerank shortlist).

**Test**
- Cell: `st_stageC3_shortlist_union_sweep_v1` in `sources_test.ipynb` (RUN_MODE=`rerank_analysis`).
- Method: shortlist = `UNION(top-50 by score_stageC_final, top-K by another signal)` where the alternate signal is tested from:
  - `score_tfidf`, `score_stageC1`, `score_relevance_hybrid`, `score_hybrid_pool`
- Then apply the finalized Stage C.3 deterministic rerank inside the expanded shortlist using the existing `llm_score` from the pinned scored CSV.

**Outputs**
- Saves:
  - `*_stageC3_shortlist_union_sweep_v1.csv`
  - `*_stageC3_shortlist_union_loco_v1.csv`
- Appends the **best macro row** to `eval_dataset/experiments/runs.csv` (`experiment=stageC3_shortlist_union_best_v1`).
- Saves a best scored CSV for follow-up: `*_stageC3_shortlist_union_best_v1_scored.csv`.

**Decision**
- Pending: run the cell and adopt only if LOCO improves (or at least does not regress) while pulling the `platform_methodology` `include` into the rerankable shortlist.

---

### 2026-02-01 — Stage C.3 shortlist expansion via union-of-toplists: hurts LOCO (reject)

**What changed**
- Ran `st_stageC3_shortlist_union_sweep_v1` to test: `shortlist = UNION(top-50 by score_stageC_final, top-K by alt_col)`, then apply the finalized deterministic Stage C.3 rerank using existing `llm_score`.

**Key macro observation**
- For small `alt_k` (5/10/20), the union was effectively identical to the top-50 baseline (union size stayed 50; no extra calls; identical metrics).
- To pull the `platform_methodology` first `include` into the shortlist you need a large expansion (e.g. `alt_col=score_tfidf, alt_k=50`), which increases LLM calls by ~`+13` per chapter on average.

**LOCO result (generalization)**
- Avg LOCO holdout `ndcg@20≈0.682334` (delta vs baseline `≈-0.027653`) → clear regression.
- Failures:
  - holdout `platform_empirical_case`: `Δ ndcg@20≈-0.059957` and first include rank `1 → 2`
  - holdout `platform_theory`: `Δ ndcg@20≈-0.023001`

**Artifacts**
- `eval_dataset/experiments/20260201_171046_0d8287ddb87a_stageC3_shortlist_union_sweep_v1.csv`
- `eval_dataset/experiments/20260201_171046_0d8287ddb87a_stageC3_shortlist_union_loco_v1.csv`
- Best macro row appended to `eval_dataset/experiments/runs.csv` (for traceability; it matches baseline because the macro winner was the “no-op” union).

**Decision**
- ❌ Do not adopt shortlist union expansion as a default strategy.
- Next: try **robust rank-fusion (RRF) in Stage C** to bring TF‑IDF‑strong docs into the top-50 without changing `TOPN` or blowing up cost.

---

### 2026-02-01 — Stage C RRF → Stage C.3 (offline) run started: initial signal looks negative; notebook bug fixed

**What happened**
- Ran `st_stageC3_stageC_rrf_sweep_v1` to test Reciprocal Rank Fusion (RRF) as an alternative Stage C score feeding into the finalized Stage C.3 top-50 reranker.

**Partial result (macro sweep)**
- Baseline (`score_stageC3_topn_tiebreak_v1`): `ndcg@20=0.709987`; first-include ranks: `{empirical: 1, methodology: 58, theory: 1}`.
- Best macro RRF config seen in the sweep was still worse than baseline:
  - best: `emb_col=score_embed_max`, `rrf_k=10`, `w_tfidf=1.0`, `w_cite=0.25`
  - macro `ndcg@20≈0.706649`
  - `platform_methodology` first include rank worsened (`58 → 79`).

**Issue**
- Cell crashed during LOCO because `pandas.groupby(...).apply(...)` returns a **DataFrame** (not Series) when there is only one group (holdout subset), causing:\n
  `ValueError: Cannot set a DataFrame with multiple columns to the single column _rank_emb`

**Fix**
- Updated the cell to compute per-group ranks via a manual loop (no `groupby.apply`), so LOCO works for single-chapter subsets.

**Next step**
- Re-run `st_stageC3_stageC_rrf_sweep_v1` to get full LOCO results + saved artifacts, then decide (likely reject if LOCO confirms regression).

---

### 2026-02-01 — Stage C RRF → Stage C.3 LOCO results: large regression (reject)

**Result (macro sweep)**
- Baseline: `ndcg@20=0.709987` (`score_stageC3_topn_tiebreak_v1`)
- Best macro RRF config was still worse than baseline:
  - `emb_col=score_embed_max`, `rrf_k=10`, `w_tfidf=1.0`, `w_cite=0.25`
  - `ndcg@20≈0.706649` (Δ `≈-0.003338`)
  - `platform_methodology` first include rank worsened: `58 → 79`

**Result (LOCO)**
- Avg LOCO holdout `ndcg@20≈0.652856` (Δ vs baseline `≈-0.057131`) → unacceptable.
- Biggest failure: holdout `platform_empirical_case` collapsed:
  - `ndcg@20≈0.535507` vs baseline `0.715248` (Δ `≈-0.179741`)

**Artifacts**
- `eval_dataset/experiments/20260201_180236_0d8287ddb87a_stageC3_stageC_rrf_sweep_v1.csv`
- `eval_dataset/experiments/20260201_180236_0d8287ddb87a_stageC3_stageC_rrf_loco_v1.csv`
- `eval_dataset/experiments/20260201_180236_0d8287ddb87a_stageC3_stageC_rrf_best_v1_scored.csv`

**Decision**
- ❌ Reject RRF as a Stage C replacement under current labels/rubrics.

---

### 2026-02-01 — Stage C.3 shortlist mixing (Stage C + TF‑IDF) for top-50 membership: no benefit (reject)

**Question**
- Can we bring `platform_methodology` INCLUDEs into the rerankable top-50 without expanding `TOPN`, by selecting the shortlist via a soft mix:\n
  `mix = (1-gamma)*norm(score_stageC_final) + gamma*norm(score_tfidf)` ?

**Result**
- Any `gamma > 0` reduced macro relevance and still did **not** pull the first `platform_methodology` include into the top-50 (it stayed ≈ rank `58` or got worse).
- LOCO always selected `gamma=0.0`, giving identical results to baseline (no generalizable improvement).

**Artifacts**
- `eval_dataset/experiments/20260201_181346_0d8287ddb87a_stageC3_shortlist_mix_tfidf_sweep_v1.csv`
- `eval_dataset/experiments/20260201_181346_0d8287ddb87a_stageC3_shortlist_mix_tfidf_loco_v1.csv`
- Best macro row appended to `eval_dataset/experiments/runs.csv`.

**Decision**
- ❌ Do not adopt shortlist mixing as a default strategy.

---

### 2026-02-01 — Stage C.3 shortlist “rescue by conservative swaps” v1: no improvement (reject)

**Question**
- Can we keep `TOPN=50` (cost unchanged) but “rescue” missed INCLUDEs by swapping a small number of TF‑IDF/StageC1-strong docs into the Stage C top‑50 shortlist?

**Result**
- The macro winner is the **no-op** configuration (`swaps=0`), identical to baseline:
  - `ndcg@20=0.709987`
  - `platform_methodology` first include rank stays at `58`.
- Configs that actually apply swaps (e.g. `alt_rank_max=50`, `stagec_rank_max=100`, `swaps=10`) can move `platform_methodology`’s first include up (≈`38`), but macro relevance collapses (`ndcg@20≈0.670`).
- LOCO selection also chooses the no-op (`swaps=0`) for all holdouts → no generalizable improvement.

**Artifacts**
- `eval_dataset/experiments/20260201_220858_0d8287ddb87a_stageC3_shortlist_rescue_intersection_sweep_v1.csv`
- `eval_dataset/experiments/20260201_220858_0d8287ddb87a_stageC3_shortlist_rescue_intersection_loco_v1.csv`
- Best macro row appended to `eval_dataset/experiments/runs.csv` (no-op baseline).

**Decision**
- ❌ Do not adopt shortlist rescue swaps as a default strategy.

---

### 2026-02-01 — Label audit (platform_methodology): evaluation bottleneck identified

**What we inspected**
- Used the pinned scored dataset `eval_dataset/experiments/20260131_094226_7370e7a6e85f_stageC3_rerank_v1_scored.csv`.
- Looked specifically at `chapter_id=platform_methodology` because it remains the weakest chapter on `mrr_include`.

**Observed label distribution (platform_methodology, n=220)**
- `include`: `2`
- `maybe`: `104`
- `exclude`: `114`

**The 2 INCLUDE items (and why this matters)**
- INCLUDE #1: “Shaping Participation: How Digital Platform Design Influences User Participation” (2025)
  - Abstract explicitly mentions a **structured literature review (99 articles)** → plausibly “methodology-relevant”.
  - Ranks: `score_stageC_final=58`, `score_tfidf=48`, `score_stageC1=71`, `llm_score=50`.
- INCLUDE #2: “Halo or Cannibalization? … Platform Markets” (2021, Journal of Marketing)
  - More like an **empirical platform-market study** than “how to run a structured literature review”.
  - Ranks: `score_stageC_final=81`, `score_tfidf=43`, `score_stageC1=41`, `llm_score=66`.

**Key implication for the pipeline**
- Our finalized Stage C.3 strategy is “rerank only inside Stage C top-50”.
- But for `platform_methodology`, the first INCLUDE appears at ~rank `58` under `score_stageC_final` → it is **never eligible** for reranking, so Stage C.3 cannot fix it.
- Interestingly, both INCLUDEs would be **inside top-50 by TF‑IDF** (`43`, `48`), but all attempts to inject TF‑IDF into shortlist selection (union/mix/rescue/RRF) regressed LOCO on the other chapters.

**Interpretation (most likely)**
- We are hitting a **label/rubric reliability bottleneck**, not just a scoring bottleneck:
  - Very few INCLUDEs → high variance evaluation for that chapter.
  - At least one INCLUDE looks questionable for the “methodology” chapter, suggesting label noise or rubric misalignment.

**Decision**
- ✅ Stop trying more Stage C / Stage C.3 shortlist hacks for now (we already exhausted the safe ones).
- Next scientific step: **label adjudication / rubric check** for `platform_methodology` (lightweight GPT pass on a small subset) to confirm whether the two INCLUDEs are correct and to identify additional true INCLUDEs among top-ranked MAYBEs.

---

### 2026-02-01 — Tooling fix: label adjudication cache filenames (Windows-safe) + legacy cache reuse

**Problem**
- `platform_methodology` contains `merge_key`s with characters invalid in Windows filenames (e.g. `|`), which broke caching and aborted the adjudication run.

**Fix**
- Cache file naming now uses a short `sha1` hash + a heavily-sanitized slug (Windows-safe).
- Added compatibility to reuse already-written cache files from the previous naming scheme (so reruns don’t re-spend tokens).
- Made the run robust to per-item failures (`asyncio.gather(..., return_exceptions=True)`) so one failure doesn’t discard the whole run.

---

### 2026-02-01 — Label adjudication (platform_methodology) v1 results: strong disagreement with existing labels

**Run**
- Notebook cell: `st_label_adjudication_methodology_v1` (first pass; strict interpretation of the rubric)
- Saved:
  - `eval_dataset/experiments/20260201_230412_7370e7a6e85f_label_adjudication_platform_methodology_v1.csv`
  - `eval_dataset/experiments/20260201_230412_7370e7a6e85f_label_adjudication_platform_methodology_v1_cost.csv`

**Selection**
- 40 items (existing label mix): `include=2`, `maybe=20`, `exclude=18`

**Adjudicated labels (new_label)**
- `exclude`: 36
- `maybe`: 4
- `include`: 0

**Most important observation**
- Both existing `include` labels were flipped to `exclude` with high confidence:
  - “Shaping Participation: How Digital Platform Design Influences User Participation” → `include → exclude (90)`
  - “Halo or Cannibalization? … Platform Markets” → `include → exclude (85)`

**Interpretation**
- This is strong evidence that `platform_methodology` labels are unreliable / under-defined for what counts as `include` vs `maybe`.
- If we keep optimizing Stage C/C.3 against these labels, we risk “scientifically correct overfitting” to noisy ground truth.

**Decision**
- ✅ Treat this as a **label-quality red flag**, not a ranking failure.
- Next: run a v2 adjudication with **explicit label definitions** (`include=methodology`, `maybe=mechanism background`, `exclude=unrelated`) and better selection (uses Stage C-ish score, plus methodology facets) before re-labeling the whole chapter.

---

### 2026-02-01 — Label adjudication (platform_methodology) v2 results: rubric clarified, many MAYBEs become INCLUDE

**Run**
- Notebook cell: `st_label_adjudication_methodology_v1` (v2 prompt behavior: explicit label definitions + chapter rubric)
- Saved:
  - `eval_dataset/experiments/20260201_231855_7370e7a6e85f_label_adjudication_platform_methodology_v2.csv`
  - `eval_dataset/experiments/20260201_231855_7370e7a6e85f_label_adjudication_platform_methodology_v2_cost.csv`

**Selection**
- 40 items selected (mostly top-ranked by `score_hybrid_pool` + methodology facets)
- Existing label mix: `maybe=37`, `include=2`, `exclude=1`

**Adjudicated labels (new_label)**
- `include`: 9
- `maybe`: 31
- `exclude`: 0 (in this 40-item slice)

**Key changes**
- 8 items flipped `maybe → include`, heavily concentrated in **structured review methodology / search strategy** papers (even if from other domains).
- 1 item flipped `include → maybe` (“Shaping Participation…”), indicating earlier INCLUDEs may have been over-confident.
- 1 item flipped `exclude → maybe` (network-effects background but not clearly methodological).

**Interpretation**
- v1 vs v2 shows the bottleneck wasn’t just “label noise”, but **label definition ambiguity** for the methodology chapter.
- v2 appears more aligned with the chapter’s goal: “structured literature analysis + framework development + operationalization”, where general systematic review/search-method sources are legitimately useful.

**Decision**
- ✅ Proceed with **full-chapter relabel** for `platform_methodology` using v2 definitions (all 220 docs), then create a **new dataset tag** and re-run evaluation on all 3 chapters.

---

### 2026-02-01 — Full relabel (platform_methodology) v2: label distribution fixed, new dataset created

**Run**
- Mode: full chapter (`MAX_ITEMS=220`), score column for selection: `score_hybrid_pool`
- Model: `gpt-5-mini`
- Cached: 40/220 items reused from previous cache
- Totals (estimated incl cached): `requests=220`, `input_tokens≈123,237`, `output_tokens≈7,986`, `cost_usd≈$0.0468`
- Saved adjudication:
  - `eval_dataset/experiments/20260201_235817_7370e7a6e85f_label_adjudication_platform_methodology_v2.csv`
  - `eval_dataset/experiments/20260201_235817_7370e7a6e85f_label_adjudication_platform_methodology_v2_cost.csv`

**Label comparison (counts)**
- Old → New (`exclude/include/maybe`):
  - `old_exclude`: `64 exclude`, `9 include`, `41 maybe`
  - `old_include`: `1 include`, `1 maybe`
  - `old_maybe`: `2 exclude`, `13 include`, `89 maybe`
- Total changed labels: `66`
- Low-confidence (<70): `12` items (includes at least one obvious-domain mismatch labeled `include` with confidence `8` → should be filtered by confidence in dataset application).

**Dataset update**
- Base: `eval_dataset/datasets/stageB_coverage_v1_v1/labeled_dataset.csv`
- New dataset tag created:
  - `stageB_coverage_v1_v1__platform_methodology_labels_v2_b62a29d1b69b`
- Chapter label counts before → after:
  - before: `include=2`, `maybe=104`, `exclude=114`
  - after: `include=23`, `maybe=131`, `exclude=66`
- Manifest:
  - `eval_dataset/datasets/stageB_coverage_v1_v1__platform_methodology_labels_v2_b62a29d1b69b/manifest.json`

**Rerank-analysis compatibility**
- Wrote a label-synced scored CSV so all Stage C.3 offline analyses run under the updated labels without re-calling any models:
  - `eval_dataset/experiments/20260201_235817_b62a29d1b69b_stageC3_rerank_v1_scored.csv`

**Decision**
- ✅ We can now re-run Stage C / Stage C.3 / Stage D offline analyses **scientifically** (methodology chapter no longer has only 2 INCLUDEs).

---

### 2026-02-02 — Re-eval Stage C vs Stage C.3 under updated methodology labels (no API)

**Scored CSV used (labels synced)**
- `eval_dataset/experiments/20260201_235817_b62a29d1b69b_stageC3_rerank_v1_scored.csv`

**Baseline macro**
- `score_stageC_final`:
  - `ndcg@20=0.564176`, `p@20=0.200000`, `mrr_include=0.777778`, `auc_include=0.744907`
- `score_llm_rerank_v1`:
  - `ndcg@20=0.553981`, `p@20=0.200000`, `mrr_include=0.555556`, `auc_include=0.648356`

**Result: Stage C.3 offline sweep (macro)**
- Best score fusion: `alpha_llm=0.20` → `ndcg@20=0.609165` (delta vs Stage C: `+0.044990`)
- Best top‑N shortlist rerank: `TOPN=50` → `ndcg@20=0.615441` (delta vs Stage C: `+0.051265`)
- Artifacts:
  - `eval_dataset/experiments/20260202_000629_b62a29d1b69b_stageC3_mix_sweep_v1.csv`
  - `eval_dataset/experiments/20260202_000629_b62a29d1b69b_stageC3_topn_sweep_v1.csv`

**LOCO validation (generalization)**
- Score fusion LOCO avg: `ndcg@20=0.609165` (avg delta vs Stage C: `+0.044990`)
- Top‑N rerank LOCO avg: `ndcg@20=0.615441` (avg delta vs Stage C: `+0.051265`)
- Selected params are stable (again picks `alpha_llm=0.2`, `TOPN=50`).
- Artifacts:
  - `eval_dataset/experiments/20260202_000629_b62a29d1b69b_stageC3_mix_loco_v1.csv`
  - `eval_dataset/experiments/20260202_000629_b62a29d1b69b_stageC3_topn_loco_v1.csv`

**Interpretation**
- The “LLM only as a shortlist reranker” result **still holds** under corrected labels.
- However, the Stage C baseline is now much weaker on `platform_methodology` (chapter ndcg@20 ≈ `0.403847`), so the next scientific lever is likely **retuning Stage C weights under the new labels** (optimize for Stage C.3 final, not Stage C alone).

---

### 2026-02-02 — Stage C (RRF shortlist builder) cite-weight sweep v2 (no API): small macro gain, empirical-case risk

**Baseline (current production-like)**
- Stage C.3 tie-break baseline: `ndcg@20=0.620942` (TOPN=50, deterministic tie-break within shortlist).

**What changed**
- Tested Stage C alternative: **RRF** for shortlist membership, then Stage C.3 tie-break rerank inside TOPN.
- Swept `w_cite` inside RRF while keeping `rrf_k=10`, `w_emb=1.0`, `w_tfidf=1.0`, `TOPN=50`.

**Macro sweep**
- Best: `w_cite=0.35` → `ndcg@20=0.627652` (delta vs baseline: `+0.006710`), `p@20=0.233333`, `mrr_include=0.833333`.
- Next: `w_cite=0.25` → `ndcg@20=0.625684` (delta: `+0.004741`).
- Low `w_cite` (≤0.12) collapses relevance / mrr on this setup.

**LOCO (picked on 2 chapters, evaluated on 1)**
- Selected `w_cite=0.35` for all holdouts.
- Holdout deltas vs baseline:
  - `platform_empirical_case`: `-0.016015` (regression)
  - `platform_methodology`: `+0.023673`
  - `platform_theory`: `+0.012472`
- Avg LOCO delta: `+0.006710` (matches macro sweep because selection is stable).

**Artifacts**
- `eval_dataset/experiments/20260202_093711_57bce9d4fe21_stageC3_stageC_rrf_cite_sweep_v2.csv`
- `eval_dataset/experiments/20260202_093711_57bce9d4fe21_stageC3_stageC_rrf_cite_loco_v2.csv`

**Interpretation**
- RRF with higher `w_cite` likely improves theoretical/methodological chapters but can hurt the empirical case chapter.
- Next: choose a **conservative** `w_cite` by inspecting per-chapter tradeoffs (macro + worst-chapter delta) before accepting RRF into the final pipeline.

---

### 2026-02-02 — RRF cite-weight choice v3 (no API): macro vs worst-chapter tradeoff

**Baseline**
- Stage C.3 tie-break baseline: `ndcg@20=0.620942`

**Per-chapter deltas (new - baseline)**
- `w_cite=0.20`: macro `ndcg@20=0.625467` (delta `+0.004525`), worst-chapter delta `-0.019011` (empirical)
- `w_cite=0.25`: macro `ndcg@20=0.625684` (delta `+0.004741`), worst-chapter delta `-0.018361` (empirical)
- `w_cite=0.35`: macro `ndcg@20=0.627652` (delta `+0.006710`), worst-chapter delta `-0.016015` (empirical)

**Recommendation (within tested set)**
- ✅ `w_cite=0.35` is best by macro and “least-bad” worst-chapter delta among `{0.20, 0.25, 0.35}`.

**Decision**
- ⚠️ Do **not** lock RRF into the final pipeline yet: empirical-case evaluation is high-variance (only ~2 INCLUDEs historically), so we first need to improve **label reliability** for `platform_empirical_case`.
- Next action: run label adjudication v2 for `platform_empirical_case` (pilot 40 → then full 220 if the pilot looks sane), then re-run this RRF decision step.

---

### 2026-02-02 — Empirical-case label adjudication pilot (26 docs): INCLUDEs likely wrong, “maybe/exclude” boundary needs tightening

**Run**
- Chapter: `platform_empirical_case`
- Pilot selection: `26` docs (MAX_ITEMS=40; many overlaps between top-by-stage and top-by-tfidf)
- Stage score column: `score_hybrid_pool`
- Totals: `requests=26`, `input_tokens=14,536`, `output_tokens=987`, `cost_usd≈$0.0056`
- Saved:
  - `eval_dataset/experiments/20260202_103909_b62a29d1b69b_label_adjudication_platform_empirical_case_v2.csv`
  - `eval_dataset/experiments/20260202_103909_b62a29d1b69b_label_adjudication_platform_empirical_case_v2_cost.csv`

**Outcome**
- New labels contained **no `include`** in this pilot slice.
- Both existing INCLUDEs flipped `include → maybe` (likely correct; they were not clear “empirical platform case evidence” sources).
- Many `exclude → maybe` flips occurred for “network effects” papers in non-target contexts (risk: `maybe` becomes too permissive).

**Interpretation**
- The empirical-case `include` definition was too strict (“public data + multiple dimensions”), causing `include` to collapse to 0 in the pilot slice.
- The `maybe/exclude` boundary is too loose for cross-domain “network effects” papers; rubric needs to push wrong-domain items to `exclude`.

**Decision / changes made**
- Updated label adjudication prompt to **chapter-aware label definitions** and made empirical-case `include` more realistic (platform-specific + evidence-based, one dimension is enough).
- Updated pilot selection to also sample platform-name / “case study” hits for `platform_empirical_case` (so the pilot actually tests the `include` boundary).
- Bumped prompt version to `v3_chapter_label_defs` to avoid reusing cached v2 outputs.

**Next**
- Re-run the empirical-case pilot (MAX_ITEMS=40) under v3; if includes appear and domain mismatches are mostly `exclude`, proceed to full 220 + apply to create a new dataset tag.

---

### 2026-02-02 — Empirical-case adjudication v3 pilot (40 docs): include signal recovered, but needs confidence filtering

**Run**
- Chapter: `platform_empirical_case`
- Selected: `40` docs (MAX_ITEMS=40)
- Existing label mix: `exclude=19`, `maybe=19`, `include=2`
- Totals: `requests=40`, `input_tokens=26,592`, `output_tokens=1,477`, `cost_usd≈$0.0096`
- Saved:
  - `eval_dataset/experiments/20260202_105638_b62a29d1b69b_label_adjudication_platform_empirical_case_v3.csv`
  - `eval_dataset/experiments/20260202_105638_b62a29d1b69b_label_adjudication_platform_empirical_case_v3_cost.csv`

**New label mix (in this 40-item slice)**
- `include`: 11
- `maybe`: 20
- `exclude`: 9

**Key flips**
- Several `maybe → include` flips for platform-specific empirical sources (e.g., App Store / Grab / Airbnb).
- Old INCLUDE still flipped `include → maybe` when it was theoretical-only (good).

**Issues spotted**
- A couple of “include” outputs had **very low confidence** (e.g., 8–9), which should not be applied blindly.

**Decision**
- ✅ Proceed to **full-chapter relabel** for `platform_empirical_case` (220 docs) using v3.
- Apply conservatively with `LABEL_ADJUDICATION_APPLY_CONFIDENCE_MIN=70` to avoid low-confidence mislabels.

---

### 2026-02-02 — Empirical-case adjudication v3 full (220 docs): INCLUDEs increased, apply with confidence≥70

**Run**
- Chapter: `platform_empirical_case`
- Mode: full chapter (`MAX_ITEMS=220`)
- Existing label mix: `exclude=163`, `maybe=55`, `include=2`
- Totals (estimated incl cached): `requests=220`, `input_tokens≈144,694`, `output_tokens≈8,048`, `cost_usd≈$0.0523`
- Saved:
  - `eval_dataset/experiments/20260202_110405_b62a29d1b69b_label_adjudication_platform_empirical_case_v3.csv`
  - `eval_dataset/experiments/20260202_110405_b62a29d1b69b_label_adjudication_platform_empirical_case_v3_cost.csv`

**Label comparison (counts)**
- `old_exclude`: `109 exclude`, `2 include`, `52 maybe`
- `old_maybe`: `2 exclude`, `14 include`, `39 maybe`
- `old_include`: `1 include`, `1 maybe`
- Total changed labels: `71`
- Low-confidence (<70): `21` items

**New-label distribution (full chapter)**
- `include=17`, `maybe=92`, `exclude=111`

**Decision**
- ✅ Apply adjudication to the dataset with `LABEL_ADJUDICATION_APPLY_CONFIDENCE_MIN=70` (keeps 199/220 rows; avoids low-confidence INCLUDEs).
- Next: create the new dataset tag + label-synced scored CSV, then rerun Stage C/C.3 analyses and re-evaluate the RRF `w_cite` decision.

**Applied**
- New dataset tag:
  - `stageB_coverage_v1_v1__platform_methodology_labels_v2_b62a29d1b69b__platform_empirical_case_labels_v3_3e82ebaea202`
- Label-synced scored CSV (for rerank_analysis):
  - `eval_dataset/experiments/20260202_111802_3e82ebaea202_stageC3_rerank_v1_scored.csv`

---

### 2026-02-02 — Rerank-analysis rerun on updated labels (methodology v2 + empirical v3 applied)

**Pinned dataset**
- Tag:
  - `stageB_coverage_v1_v1__platform_methodology_labels_v2_b62a29d1b69b__platform_empirical_case_labels_v3_3e82ebaea202`
- Label distribution (per chapter):
  - `platform_empirical_case`: `exclude=115`, `maybe=90`, `include=15`
  - `platform_methodology`: `exclude=66`, `maybe=131`, `include=23`
  - `platform_theory`: `exclude=100`, `maybe=101`, `include=19`

**Stage C baseline (macro, __ALL__)**
- `score_stageC_final`: `ndcg@20≈0.564176`, `p@20≈0.200000`, `mrr_include≈0.777778`, `auc_include≈0.744907`

**Stage C.3 confirmation (offline, using cached rerank-v1 scores)**
- Best **score fusion**: `alpha_llm=0.20` → `ndcg@20≈0.609165` (Δ vs Stage C: `+0.044990`)
- Best **top‑N shortlist rerank**: `topn=50` → `ndcg@20≈0.615441` (Δ vs Stage C: `+0.051265`)
- LOCO still selects `alpha_llm=0.20` and `topn=50` for all holdouts.

**Artifacts**
- `eval_dataset/experiments/20260202_000629_b62a29d1b69b_stageC3_mix_sweep_v1.csv`
- `eval_dataset/experiments/20260202_000629_b62a29d1b69b_stageC3_topn_sweep_v1.csv`
- `eval_dataset/experiments/20260202_000629_b62a29d1b69b_stageC3_mix_loco_v1.csv`
- `eval_dataset/experiments/20260202_000629_b62a29d1b69b_stageC3_topn_loco_v1.csv`

**Decision**
- ✅ Stage C.3 design remains correct under the improved labels: **top‑50 shortlist rerank + deterministic tie-break**.

---

### 2026-02-02 — Stage C weight retune “optimized for Stage C.3” is overfitting (reject)

**What changed**
- Tried to retune Stage C weights to maximize the *post‑Stage‑C.3* metric (macro `ndcg@20`), using the pinned dataset.

**Single-dataset best**
- `w_embed_max=0.5`, `w_embed=0.6`, `cite_weight=0.08` → macro `ndcg@20≈0.621967`

**Generalization (LOCO)**
- Avg LOCO holdout `ndcg@20≈0.583189`
- Avg LOCO delta vs baseline (current Stage C weights): `≈-0.023649`

**Artifacts**
- `eval_dataset/experiments/20260202_112421_45cf8edd2af2_stageC3_stageC_joint_grid_v1_sweep.csv`
- `eval_dataset/experiments/20260202_112421_45cf8edd2af2_stageC3_stageC_joint_grid_v1_loco.csv`

**Decision**
- ❌ Do **not** retune Stage C weights “for Stage C.3” — it improves the training macro but hurts LOCO → classic overfitting.
- ✅ Keep the existing finalized Stage C weights (`w_embed_max=0.0`, `w_embed=0.7`, `cite_weight=0.08`).

---

### 2026-02-02 — Stage C RRF citation weight sweep v2: small macro gain but harms empirical and fails LOCO (reject)

**What changed**
- Tested a Stage C **RRF-style** merge with a larger citation weight `w_cite` to see if it helps before Stage C.3.

**Macro sweep**
- Best macro: `w_cite=0.20` → `ndcg@20≈0.610786` (Δ vs base `+0.003948`)

**LOCO holdout deltas vs base (selected `w_cite` per holdout)**
- `platform_empirical_case` (selected `w_cite=0.35`): `Δ ndcg@20≈-0.045675` (worst-case harm)
- `platform_methodology` (selected `w_cite=0.20`): `Δ ndcg@20≈+0.024238`
- `platform_theory` (selected `w_cite=0.20`): `Δ ndcg@20≈+0.008348`

**Generalization (LOCO)**
- Avg LOCO delta vs base: `≈-0.004363`

**Artifacts**
- `eval_dataset/experiments/20260202_112435_def239c4acaf_stageC3_stageC_rrf_cite_sweep_v2.csv`
- `eval_dataset/experiments/20260202_112435_def239c4acaf_stageC3_stageC_rrf_cite_loco_v2.csv`

**Decision**
- ❌ Do **not** adopt the RRF `w_cite` change: hurts the empirical chapter and does not generalize under LOCO.

---

### Next (scientific hygiene)

We now have improved labels for:
- ✅ `platform_methodology` (v2)
- ✅ `platform_empirical_case` (v3, applied with confidence≥70)

To avoid “uneven ground truth quality”, the next step is to run the same adjudication on:
- ⏳ `platform_theory` (full 220 docs), then apply with confidence≥70 and rerun rerank-analysis once more.

---

### 2026-02-02 — Theory adjudication v3 full (220 docs) + apply (confidence≥70): INCLUDEs increased substantially

**Run**
- Chapter: `platform_theory`
- Mode: full chapter (`MAX_ITEMS=220`)
- Existing label mix: `maybe=101`, `exclude=100`, `include=19`
- Totals: `requests=220`, `input_tokens=116,887`, `output_tokens=8,284`, `cost_usd≈$0.04579`
- Saved:
  - `eval_dataset/experiments/20260202_124639_3e82ebaea202_label_adjudication_platform_theory_v3.csv`
  - `eval_dataset/experiments/20260202_124639_3e82ebaea202_label_adjudication_platform_theory_v3_cost.csv`

**Changes**
- Total changed labels: `69`
- Low-confidence (<70): `29` (not applied)

**Applied (confidence≥70)**
- Applied rows: `191/220`
- Before (chapter): `include=19`, `maybe=101`, `exclude=100`
- After  (chapter): `include=54`, `maybe=88`, `exclude=78`

**New dataset + scored CSV**
- New dataset tag:
  - `stageB_coverage_v1_v1__platform_methodology_labels_v2_b62a29d1b69b__platform_empirical_case_labels_v3_3e82ebaea202__platform_theory_labels_v3_96297d620195`
- Label-synced scored CSV:
  - `eval_dataset/experiments/20260202_124639_96297d620195_stageC3_rerank_v1_scored.csv`

**Decision**
- ✅ All 3 chapters now have adjudicated labels → we can treat this dataset as the new “main benchmark” for pipeline tuning.

---

### 2026-02-02 — Rerank-analysis on the fully adjudicated dataset (all 3 chapters): baseline improved, Stage C retuning still overfits

**Pinned dataset**
- `stageB_coverage_v1_v1__platform_methodology_labels_v2_b62a29d1b69b__platform_empirical_case_labels_v3_3e82ebaea202__platform_theory_labels_v3_96297d620195`

**Baseline after Stage C.3 (macro, __ALL__)**
- Stage C weights (kept): `w_embed_max=0.0`, `w_embed=0.7`, `cite_weight=0.08`
- Macro: `ndcg@20≈0.659435`, `p@20≈0.416667`, `mrr_include≈0.833333`, `auc_include≈0.722174`
- First INCLUDE ranks (sanity): `empirical_case=1`, `methodology=2`, `theory=1`

**Stage C weight retune “for Stage C.3”**
- Single-dataset best: `w_embed_max=0.0`, `w_embed=0.5`, `cite_weight=0.12` → `ndcg@20≈0.673464`
- LOCO avg holdout: `ndcg@20≈0.633036` (Δ vs baseline `≈-0.026398`)
- Decision: ❌ reject (still overfitting under stronger labels).
- Artifacts:
  - `eval_dataset/experiments/20260202_124919_b9c347f21d03_stageC3_stageC_joint_grid_v1_sweep.csv`
  - `eval_dataset/experiments/20260202_124919_b9c347f21d03_stageC3_stageC_joint_grid_v1_loco.csv`

**Shortlist “rescue” intersections**
- Single-dataset best improved macro (`ndcg@20≈0.677447`), but LOCO average delta vs base was `0.0` (no generalizable improvement).
- Decision: ❌ keep baseline (not worth complexity).
- Artifacts:
  - `eval_dataset/experiments/20260202_124931_b9c347f21d03_stageC3_shortlist_rescue_intersection_sweep_v1.csv`
  - `eval_dataset/experiments/20260202_124931_b9c347f21d03_stageC3_shortlist_rescue_intersection_loco_v1.csv`

**RRF citation-weight sweep (re-check)**
- Best macro in sweep was worse than baseline:
  - `w_cite=0.20` → `ndcg@20≈0.658292` (Δ `≈-0.001143`)
- LOCO deltas vs base (selected `w_cite=0.20`):
  - `platform_empirical_case`: `Δ ndcg@20≈-0.020742`
  - `platform_methodology`: `Δ ndcg@20≈+0.024238`
  - `platform_theory`: `Δ ndcg@20≈-0.006925`
  - Avg LOCO delta: `≈-0.001143`
- Decision: ❌ reject (hurts empirical + net-negative).
- Artifacts:
  - `eval_dataset/experiments/20260202_124932_da4629e6f35d_stageC3_stageC_rrf_cite_sweep_v2.csv`
  - `eval_dataset/experiments/20260202_124932_da4629e6f35d_stageC3_stageC_rrf_cite_loco_v2.csv`

---

### 2026-02-02 — Stage C.3 TOPN tradeoff (fully adjudicated dataset): TOPN=75 wins macro, but harms methodology and breaks Stage D synergy

**Sweep (macro)**
- `TOPN=50` (baseline): `ndcg@20≈0.659435`, `p@20≈0.416667`, `mrr_include≈0.833333`
- `TOPN=75`: `ndcg@20≈0.672256` (Δ `≈+0.012821`), `p@20≈0.433333`, `mrr_include≈0.777778`

**Per-chapter ndcg@20 delta (TOPN=75 − TOPN=50)**
- `platform_empirical_case`: `≈+0.054035`
- `platform_methodology`: `≈-0.013273`
- `platform_theory`: `≈-0.002298`

**Decision**
- ✅ Keep `TOPN=50` as the production default:
  - It’s cheaper (50 calls/chapter vs 75) and avoids harming the methodology chapter.
  - It is the **only** setting that pairs well with Stage D MMR (see next section).

**Artifacts**
- `eval_dataset/experiments/20260202_131649_96297d620195_stageC3_topn_tradeoff_sweep_v2.csv`
- `eval_dataset/experiments/20260202_131649_96297d620195_stageC3_topn_tradeoff_loco_v2.csv`

---

### 2026-02-02 — Stage D finalized (fully adjudicated dataset): MMR TF‑IDF improves relevance + reduces redundancy

**What changed**
- Added a Stage D “diverse top‑K” re-ranker on top of Stage C.3:
  - pool = top‑`topm` by `score_stageC3_topn_tiebreak_v1`
  - selection = MMR using TF‑IDF similarity
  - ranking = chosen docs sorted by `score_stageC3_signal_v1` then `score_stageC3_topn_tiebreak_v1`

**Best sweep setting (macro)**
- `topm=100`, `lambda=0.6` (also ties with 0.7–0.9)
- Macro: `ndcg@20≈0.675737` (Δ vs Stage C.3 baseline `≈+0.016302`)
- Redundancy proxy (avg TF‑IDF mean pairwise sim top‑20): `≈0.1346` (baseline was `≈0.17–0.19`)

**Per-chapter ndcg@20 delta (topm=100, lambda=0.6)**
- `platform_empirical_case`: `≈+0.049199`
- `platform_methodology`: `≈+0.001704`
- `platform_theory`: `≈-0.001996` (negligible)

**Decision**
- ✅ Stage D finalized as the default “final selection” step:
  - `TOPN=50`, `K_SELECT=20`, `topm=100`, `lambda=0.6`
- Optional: expose a future UI toggle (“more diversity”) by lowering `lambda` (more novelty), at the cost of some relevance risk.

**Artifacts**
- `eval_dataset/experiments/20260202_131649_96297d620195_stageD_mmr_tfidf_sweep_v2.csv`
- `eval_dataset/experiments/20260202_131855_96297d620195_stageD_mmr_tfidf_loco_v2.csv`

---

### 2026-02-02 — Production hardening (source_final): Stage C.3 prompt v2 + label/confidence gating

**Why**
- Production surfaced an off-scope failure mode: the LLM can overweight keyword overlap in the wrong domain/context.

**What changed (code)**
- `source_final.ipynb` Stage C.3 now asks the LLM for:
  - `label` = `include|maybe|exclude`
  - `confidence` (0–100)
  - `score` (0–100, explicitly anchored)
- Stage C.3 ordering within the shortlist uses:
  - primary: `label_rank` (include > maybe > exclude)
  - then: `minmax(score)` within the chapter shortlist
  - then deterministic tie-breaks (`score_stageC_final`, citations, id)
- Stage D relevance signal uses `1 + minmax(score)` within top-N and gates out `exclude` / low-confidence items.

**How to validate**
- Run `source_final.ipynb` (Restart Kernel + Run All) and check if obvious off-scope items disappear from top-20.
- Paste the JSON summary block back into this chat so we can inspect the saved CSVs.

---

### 2026-02-02 — Production QA: exclude leakage fixed (source_final)

**Observation (production run `20260202_185354`)**
- Top‑20 contained LLM‑labeled `exclude` items despite Stage C.3 reranking:
  - `platform_empirical_case`: **8 excludes** in top‑20
  - `platform_methodology`: **1 exclude** in top‑20

**Root cause**
- Stage D’s relevance signal boosted shortlist items based on LLM score even when the LLM label was `exclude`, allowing excluded items to float into the final top‑20.

**Fix (code)**
- Stage C.3: only assigns the “2.x shortlist band” to items with `llm_label in {include, maybe}` (and confidence gate).
- Stage D: only applies `1 + minmax(llm_score)` to non‑`exclude` + sufficiently confident items, and filters `exclude` out of the MMR pool.
- Export safety: top‑20 CSV export filters out any remaining `exclude` rows (failsafe).

**Next**
- Re-run `source_final.ipynb` and confirm the QA summary prints **0 excludes** in top‑20 for all chapters.

---

### 2026-02-02 — Production QA: “blank llm_label” issue → adaptive Stage C.3 top‑N

**Observation (production run `20260202_204422`)**
- Excludes were successfully removed from top‑20, but `platform_empirical_case` top‑20 still contained **blank** `llm_label` entries (unscored tail docs), which were often off‑scope (e.g., unrelated regulation/accounting/politics papers).
- Root cause: in `platform_empirical_case`, the LLM labeled **35/50** of the Stage C top‑50 as `exclude`, leaving only **15** non‑exclude candidates — fewer than the desired `k_select=20`.

**Fix (code)**
- Stage C.3 now **adaptively expands** the per‑chapter shortlist beyond 50 (in steps) until it has at least `min_non_exclude` (=20 by default), up to a cap (`topn_max`).
- Stage D now selects only from the **scored** shortlist (`_in_topn`) and filters out `exclude` and blank labels.

**Next**
- Re-run `source_final.ipynb` and confirm the QA summary shows:
  - `platform_empirical_case`: **0 blanks** and **0 excludes** in top‑20
  - all chapters: top‑20 rows have `llm_label/llm_confidence/llm_notes` populated.

**Validation (production run `20260202_220223`)**
- Stage C.3 expansion actually triggered only for `platform_empirical_case`:
  - `topn_used_by_chapter`: `empirical_case=75`, `methodology=50`, `theory=50`
  - Additional Stage C.3 cost (beyond cached 150): **25 requests**, `cost≈$0.0111`
- QA summary (top‑20):
  - `platform_empirical_case`: `include=4`, `maybe=16` (no excludes, no blanks)
  - `platform_methodology`: `include=1`, `maybe=19`
  - `platform_theory`: `include=20`

---

### 2026-02-02 — Generalization smoke test: Zero Trust Architecture (source_final)

**Observation (production run `20260202_222323`)**
- Chapter: `zero_trust_architecture` (unseen domain, non‑platform topic)
- Stage C pool size: `stageC_all rows=1313`
- Stage C.3: `topn_used_by_chapter={"zero_trust_architecture": 50}`, `requests=50`, `cost≈$0.0255`
- QA summary (top‑20): `llm_label counts = {"include": 20}`

**What’s good**
- Strong evidence the pipeline is **chapter‑agnostic**: the rubric-driven rerank produced coherent, on‑topic results without any platform-specific heuristics.
- No regressions from earlier QA fixes: no `exclude` leakage and no blank/unscored rows in top‑20.

**Red flags / limitations surfaced**
- Top‑20 is dominated by **low‑prestige / generic venues** (e.g., IJSRM/WJARR/IJRASET‑like outlets). This suggests Stage C.3 currently optimizes primarily for **topic fit**, not **authority/evidence level**.
- Canonical standards can be present in Stage A but still fail to show up in top‑20 due to Stage C prefilter + abstract limitations:
  - `https://doi.org/10.6028/nist.sp.800-207` (OpenAlex) ranked ~**213** by `score_stageC_final` → did not enter the Stage C.3 top‑N shortlist (no LLM label/score).
  - `10.6028/nist.sp.800-207-draft` (Semantic Scholar) ranked **6** by `score_stageC_final` but was labeled `maybe` with a low LLM score (likely because the abstract snippet is high‑level and doesn’t expose the document’s detailed reference architecture).

**Implications / next improvements (chapter‑agnostic)**
- Add an explicit **authority/evidence** dimension (LLM field or heuristic) so standards/surveys and reputable venues outrank generic on‑topic articles.
- Improve shortlist **recall for standards** whose abstracts are boilerplate:
  - shortlist union: `(top-N by score_stageC_final) ∪ (top-K by score_tfidf) ∪ (top-K by citations)` before LLM scoring.
- Normalize `doi_norm` consistently (e.g., always `10.x/...`) to improve dedupe across OpenAlex/Semantic Scholar and prevent citation splitting across duplicates.
