# Phase F Design Probe Findings

Date: 2026-03-09

Purpose:
- move from “embedding model A vs B” to actual Phase F design choices
- test defaults that can be implemented without overfitting to one chapter

Runs:
- `ca79147de41f8edbfb47c9e5`:
  - sparse, hard historical topic
- `ed2e3d3304d5ed9587592f4d`:
  - high-yield methods / online-reviews topic

Artifacts:
- script: `phase_f_design_probe.py`
- result JSON: `probe_outputs/phase_f_design_probe_20260309-181711.json`
- summary: `probe_outputs/phase_f_design_probe_20260309-181711.summary.md`
- top-20 CSVs: `probe_outputs/phase_f_design_top20_<run>_<variant>.csv`

Additional spend:
- estimated embedding cost: `$0.2890`
- HyDE generation cost: `$0.0042`
- actual total cost: `$0.2962`

## What was tested

### Query-side representations

- `topic_r800`
- `summary_r800`
- `target_r400`
- `target_r800`
- `target_r1400`
- `target_core800`
- `hyde_r800`
- `hyde_hybrid_r800`
- `staged_target_r800`
- `staged_hyde_hybrid_r800`

Definitions:
- `target_*` = deterministic chapter-target document built from:
  - chapter title
  - chapter spec
  - planner summaries
  - core object terms
  - anchors
  - must-keep constraints
  - drift risks
- `hyde_*` = hypothetical relevant-paper abstract generated with `gpt-5-mini`
- `staged_*` = shortlist chunk rerank plus diversity control

### Candidate packaging

- `rich_400` = title + year + venue + authors + abstract[:400]
- `rich_800` = title + year + venue + authors + abstract[:800]
- `rich_1400` = title + year + venue + authors + abstract[:1400]
- `core_800` = title + abstract[:800]

### Hygiene

Top-k hygiene was enforced in the design probe:
- drop exact junk-title patterns
- final title-level dedup in the ranking output

## Main findings

### 1. `target_doc` is the right new default query representation

`target_doc` was the most implementation-ready query representation:
- deterministic
- planner-aligned
- more controllable than HyDE
- less generic than summary-only ranking on the methods chapter

It did not dominate every metric on every run, but it was the most stable basis for a concrete Phase F design.

### 2. `800` chars is the best current default for candidate abstract packaging

Observed pattern:
- `400` chars was often too thin
- `1400` chars often improved abstract-hit proxies but broadened the ranking and pulled in more contextual drift
- `800` chars was the best compromise

Interpretation:
- for the main candidate embedding text, use a medium abstract slice, not a minimal snippet and not a very long one

### 3. HyDE is interesting but not stable enough for default use

HyDE helped the sparse hard-topic run:
- Roman hard-topic:
  - `hyde_r800` title-core hit rate `0.50`
  - `staged_hyde_hybrid_r800` title-core hit rate `0.50`

But it was less stable on the online-reviews run:
- online-reviews:
  - `staged_hyde_hybrid_r800` title-core hit rate dropped to `0.40`
  - it also introduced some odd or less central items

Recommendation:
- do not make HyDE the default
- keep it as an optional fallback for sparse / hard topics later

### 4. staged rerank remains the strongest overall design

Cross-run averages:
- `staged_target_r800`
  - score `0.5671`
  - title-core `0.500`
  - abstract-core `0.800`
  - pairwise similarity `0.5273`
- `staged_hyde_hybrid_r800`
  - score `0.5597`
  - title-core `0.450`
  - abstract-core `0.825`
  - pairwise similarity `0.5189`

Interpretation:
- chunk rerank plus light diversity is worth keeping
- the non-HyDE staged variant is the safer default

### 5. hygiene should be mandatory, not optional

The design probe forced top-k hygiene and all tested variants ended with:
- `duplicate_titles = 0`
- `junk_titles = 0`

This is a strong argument for making hygiene a mandatory part of Phase F output assembly.

### 6. candidate metadata helps a bit as a stabilizer

`core_800` often looked better for the online-reviews methods chapter, but it was less safe on the hard historical topic:
- it surfaced `Conclusions` and other overly generic records more easily in the Roman run

Interpretation:
- pure `title + abstract` can be attractive on method-heavy chapters
- but a small amount of metadata stabilizes the harder topic

Recommendation:
- default to a light rich representation, not pure metadata and not pure title+abstract
- if simplifying later, remove `authors` first rather than dropping all metadata

## Practical conclusions

Recommended default direction:
1. deterministic `chapter_target_doc`
2. candidate doc text with abstract around `800` chars
3. staged shortlist chunk rerank
4. mandatory hygiene and title-level dedup
5. keep HyDE as a future fallback, not as default

## Things this probe did not prove

- it did not prove that one exact weight is globally optimal
- it did not prove that HyDE is bad in general
- it did not test many chapter families beyond the two contrasting runs

So the implementation plan should prefer robust defaults and config knobs over aggressive hard-coded tuning.
