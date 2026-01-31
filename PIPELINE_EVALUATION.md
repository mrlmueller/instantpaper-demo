# Pipeline Evaluation & Experiment Plan

This repo now has two notebooks that form a **repeatable evaluation loop**:

- `eval_dataset_builder.ipynb` → builds **candidates + labels** for **3 chapters** (our “queries”)
- `sources_test.ipynb` → computes **metrics** and logs results to `eval_dataset/experiments/`

The goal of this document is to define a **scientific, cautious, reproducible** experiment program so that after running the full suite we can confidently converge on a pipeline that consistently surfaces the best sources for *any* chapter.

---

## 0) Ground rules (scientific hygiene)

1) **Always evaluate on all 3 chapters** (platform theory / methodology / empirical case).  
   - Each chapter is treated as one “query”.
   - We report per-chapter metrics and a macro-average `__ALL__` row (each chapter weighted equally).

2) **Change one thing at a time** (or run a controlled sweep) and log it.  
   - Do not “tune by vibes” across multiple knobs simultaneously.

3) **Freeze evaluation logic** while tuning.  
   - If you change metric definitions, treat it as a new benchmark version.

4) **Record provenance for every run**: dataset hash, git commit, experiment tag, and notes.  
   - `sources_test.ipynb` already writes `eval_dataset/experiments/runs.csv`.

5) **Treat LLM labels as noisy ground truth**.  
   - We rely on 3 chapters to reduce overfitting, but reliability still matters.
   - Use spot checks + audits (see “Label quality”).

---

## 1) What we have right now (baseline snapshot)

From `eval_dataset/experiments/runs.csv` (run_id `20260129_232932_7da6900ddd4b`):

- Macro `ndcg@20` best among current score columns: `score_relevance_hybrid` ≈ **0.517**
- Macro `ndcg@20` for `score_hybrid_pool` ≈ **0.516** (very close)
- Macro `auc_include` is highest for `score_tfidf` ≈ **0.709** (but AUC is not a top‑K metric)

Important observation:
- `platform_methodology` and `platform_empirical_case` have only **4** `include` items each in the labeled set, which makes top‑K metrics **very sensitive**. One document moving into the top‑20 changes `p@20` by 0.05.

This is not “bad” — it simply means:
- We should prioritize **graded metrics** (e.g. `ndcg@K`, where `maybe` contributes) and/or
- We should expand labeling coverage (more labeled documents, or higher quality labels).

---

## 2) Evaluation dataset definition (what is “truth”?)

### Files

- Labeled dataset: `eval_dataset/labeled_dataset.csv`
- Per-run evaluation logs: `eval_dataset/experiments/runs.csv` and `eval_dataset/experiments/*_report.csv`

### Labels

`final_label ∈ {include, maybe, exclude}` + `final_confidence ∈ [0,100]`

Recommended interpretations:

- **Strict relevance**: `include` is relevant, `maybe/exclude` are not.
- **Graded relevance**: `include=2`, `maybe=1`, `exclude=0` (used by `ndcg@K`).
- **Confidence filtering**: optionally evaluate only rows with `final_confidence ≥ X` (e.g. 70) as a robustness check.

### Why 3 chapters

We always evaluate across the 3 chapter types to reduce the risk that we “optimize for one chapter style”.  
This is still a *small* benchmark (3 queries), so we must be cautious with claims of “significance”.

---

## 3) Metrics (what we optimize)

### Core ranking metrics (recommended primary)

- `ndcg@10`, `ndcg@20`, `ndcg@50` (graded: include > maybe > exclude)
  - Best single metric to balance “quality at top” and partial relevance.

### Supporting metrics (debugging / sanity)

- `p@K` and `r@K` using **include-only** as relevant
  - Useful to ensure we really bring true “must-use” sources to the very top.
  - Sensitive if `n_include` is small.

- `mrr_include`
  - Helps detect whether at least one strong source is ranked early.

- `auc_include`
  - Useful for “global separability”, but it can be misleading for top‑K quality.

### Reporting requirements (every run)

For each experiment, we record:
- `__ALL__` macro metrics for each evaluated score
- per-chapter metrics (all 3 chapters)
- dataset hash + git commit + experiment notes

### Anti-overfitting check (recommended with only 3 chapters)

Because we only have 3 queries, it’s easy to overfit without noticing. For any “serious” change, also do:

- **Leave-one-chapter-out (LOCO)** reporting:
  - Tune on 2 chapters, report metrics on the held-out chapter.
  - Repeat for each held-out chapter and compare.

Even if we still choose a single global setting, LOCO helps catch “works only for theory” style failures early.

---

## 4) What counts as “the pipeline” (stages + what we can test)

### Stage A — Source acquisition

Inputs: blueprint queries → OpenAlex + Semantic Scholar  
Output: `eval_dataset/stageA/stageA_combined_oa_s2_<chapter_id>.csv`

What can break / drift:
- rate limiting, missing abstracts, duplicate handling, query coverage

What we can test:
- source counts and overlap (OpenAlex vs S2)
- abstract coverage (% with usable abstract)
- candidate diversity across venues/years/types

### Stage B — Chapter blueprint generation (rubric)

Inputs: chapter spec text  
Output: `eval_dataset/blueprints/<chapter_id>.json`

What can break / drift:
- blueprint instability across runs
- facets too similar (low coverage), or too broad (retrieval noise)

What we can test:
- blueprint quality audits (cheap LLM self-check + occasional human check)
- stability check: re-run blueprint generation with a fixed seed/version and diff outputs

### Stage C — Retrieval + scoring (TF‑IDF + embeddings + fusion)

Inputs: Stage A corpus + blueprint  
Outputs: candidates + scores (`score_*` columns)

What can break / drift:
- overly small facet pools → recall collapse
- overly large pools → noise increases; embedding costs increase
- weights (`W_EMBED`, `W_TFIDF`, `CITE_WEIGHT`) not robust across chapters

What we can test:
- ablations: TF‑IDF alone vs embeddings alone vs hybrid
- weight sweeps (offline; no API calls)
- facet coverage effects (`TOP_PER_QUERY`, `FETCH_MAX_QUERIES_PER_CHAPTER`)

### Stage C.3 — LLM rerank (rubric-driven)

Inputs: blueprint + candidate title/abstract/metadata  
Outputs: rubric scores (relevance, scope_adherence, conceptual_fit, …)

What can break / drift:
- prompt too long → truncation harms judgments
- model choice too cheap → inconsistent reasoning
- “maybe” inflation or over‑strictness

What we can test:
- prompt variants (short vs long rubric)
- model variants (cheap pass1 vs expensive pass2)
- schema variants (graded scoring vs include/maybe/exclude only)

### Stage D — Diversity (MMR / facet coverage)

Inputs: ranked list + facet assignment  
Outputs: final top‑N diversified set

What can break / drift:
- duplicates / near-duplicates in final list
- over-diversifying and losing core relevance

What we can test:
- diversity vs relevance tradeoff curves (MMR lambda / facet bonus)
- “facet coverage” metrics in final top‑N

---

## 5) Experiment suite (what we should run)

Below is the proposed “full suite”. Each experiment must:
- run on all 3 chapters
- log into `runs.csv`
- include `EXPERIMENT_TAG` + short `EXPERIMENT_NOTES`

### A) Baseline / sanity

1. **Baseline evaluation** (current implementation)
   - Purpose: establish a stable reference row in `runs.csv`
   - Output: baseline report CSV + `runs.csv` entries

2. **Confidence filter robustness**
   - Run eval with `final_confidence ≥ 60/70/80`
   - Watch for metric instability; large changes mean labels are noisy.

3. **Label distribution check**
   - Track `n_include`, `n_maybe`, `n_exclude` per chapter per dataset version.
   - If includes are too rare in some chapters, expand labeling set.

### B) Stage C (retrieval + fusion) ablations (offline, cheap)

4. **Single-signal baselines**
   - TF‑IDF only
   - embeddings only
   - citations only (should perform poorly; sanity check)

5. **Fusion weight sweep**
   - Sweep `w_embed ∈ [0..1]` with per-chapter minmax normalization (as in `sources_test.ipynb`)
   - Goal: find a robust plateau (not a brittle single point).

6. **Citation weight sweep**
   - Sweep `CITE_WEIGHT` (e.g. 0.00, 0.05, 0.08, 0.12, 0.20)
   - Evaluate whether citations help “include” sources or amplify popularity bias.

7. **Breadth vs max embedding**
   - Sweep `W_EMBED_MAX` / `W_EMBED_BREADTH` (e.g. max-only vs 70/30 vs 50/50)
   - Hypothesis: breadth improves chapters needing multi-aspect coverage.

### C) Stage A/B coverage knobs (affects recall; moderate cost)

8. **Facet query count**
   - Compare `FETCH_MAX_QUERIES_PER_CHAPTER` (e.g. 8 vs 12 vs 15)
   - Measure whether more facets increases relevant docs or just noise.

9. **Per-facet pool size**
   - Sweep `TOP_PER_QUERY` (e.g. 150, 250, 400)
   - Track embed cost + quality metrics.

10. **Candidate set composition**
   - Increase `CAND_TARGET_N` (e.g. 220 → 300) and re-label
   - Goal: more evaluation signal, especially for chapters with few includes.

### D) LLM rerank experiments (costly; run after Stage C is solid)

11. **LLM rerank vs non‑LLM baseline**
   - Add a rerank score and evaluate top‑K improvements.

12. **Prompt schema variants**
   - Variant A: scores (0–100) + short notes
   - Variant B: include/maybe/exclude only (faster/cheaper)
   - Variant C: add facet hit tagging for diversity control

13. **Model ladder**
   - pass1 cheap model for all items
   - pass2 stronger model only for low-confidence / “maybe” / audit samples
   - Track total cost and metric gain.

### E) Diversity selection experiments

14. **MMR lambda sweep**
   - Evaluate top‑N quality vs diversity metrics.

15. **Facet coverage bonus**
   - Compare semantic-only diversity vs facet-aware diversity
   - Check if final set covers more facets without losing too much NDCG.

---

## 6) Persistence & reproducibility (how we track runs)

### Required persistent artifacts

- `eval_dataset/experiments/runs.csv` (append-only)
- per-run full report: `eval_dataset/experiments/<run_id>_<tag>_report.csv`
- optional sweep outputs: `*_weight_sweep.csv`, etc.

### Dataset versioning (critical for Stage B A/B)

Stage B changes (blueprint queries/rubric) can change what Stage A fetches and what gets labeled. To stay scientific:

- Build each dataset into its own folder: `eval_dataset/datasets/<dataset_tag>/...`
- Keep a **fixed evaluation rubric** (so labels mean the same across datasets): `eval_dataset/eval_rubrics/<chapter_id>.json`
- When comparing Stage B variants end-to-end:
  - Set `BLUEPRINT_VARIANT=baseline` / `coverage_v1` (etc.)
  - Set `LABEL_RUBRIC_SOURCE=eval_rubrics`
  - Rebuild datasets and evaluate each dataset separately in `sources_test.ipynb` (same metrics, same chapters)
  - Use the final cell in `sources_test.ipynb` (“Stage B end-to-end A/B compare”) to summarize and persist the comparison from `runs.csv`.

### What to put in `EXPERIMENT_NOTES`

Keep it short and concrete:
- “Sweep W_EMBED only; dataset frozen”
- “TOP_PER_QUERY 250→400; re-labeled dataset v2”
- “LLM rerank prompt v3; changed abstract truncation 1800→2400”

---

## 7) Label quality program (to make the benchmark trustworthy)

Because labels are LLM-generated, we should run a small but systematic quality loop:

1) **Audit sample each dataset version**
- Randomly sample ~20 items per chapter:
  - 5 include, 5 maybe, 10 exclude (if possible)
- Manually spot-check: does label match the chapter rubric?

2) **Disagreement / uncertainty focus**
- If `final_confidence < 60`, audit more heavily.
- If many “maybe”, consider:
  - improving rubric (must_cover/must_avoid clarity)
  - allowing longer abstracts in labeling prompt
  - using a slightly stronger label model for pass1, but keep costs bounded

3) **Stability check**
- Re-label a small fixed subset with the same prompt+model:
  - too much drift suggests the label prompt is underspecified.

---

## 8) Practical next steps (recommended order)

1) Run `sources_test.ipynb` with `CONFIDENCE_MIN = 70` and compare to baseline.
2) Do the offline fusion weight sweep (already in notebook) and choose a stable `w_embed` plateau.
3) Increase evaluation signal where needed:
   - raise `CAND_TARGET_N` and re-label (especially for chapters with few includes).
4) Only then start LLM rerank experiments (Stage C.3).
