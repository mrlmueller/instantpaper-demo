# Quellen-Finder Query Builder Lint Investigation

## Scope

This investigation focused on intermittent pipeline failures in the two-lane Quellen-Finder query builders, with special attention to:

- `phase_c_openalex_query_builder`
- `phase_c_s2_query_builder`
- the deterministic lint layer after the OpenAI JSON-schema calls
- actual provider behavior for generated queries

The concrete reproduction case used:

- `project_id = D6WAuHW3kontPlOkFN6O`
- `kapitel_id = 9n6A4J430W7dbspdcYYg`
- `run_id = hf5uawmdonQjmf1bDu2u`
- chapter title: `Automatisierung der Dokumentenanalyse mittels NLP/LLM`

The historical Cloud Run failure for this case was an OpenAlex query-builder hard fail caused by lint retries exhausting after:

- `anchor fingerprint concentration too high`
- `query missing required anchor`
- `match query missing core object term`

## What Was Added

Two reusable investigation scripts were added:

- [backend/scripts/replay_two_lane_query_builders.py](<projektverzeichnis>/backend/scripts/replay_two_lane_query_builders.py)
- [backend/scripts/analyze_two_lane_query_builder_lints.py](<projektverzeichnis>/backend/scripts/analyze_two_lane_query_builder_lints.py)

These scripts:

- load the exact Firestore chapter input and run settings
- call the OpenAI Responses API directly with the same prompts, schemas, models, and reasoning settings as the pipeline
- rerun the current deterministic lints locally
- compare the active OpenAlex fingerprint lint to the older legacy behavior
- probe OpenAlex and Semantic Scholar directly for generated queries
- report duplicate function definitions in [backend/services/two_lane_sources/pipeline.py](<projektverzeichnis>/backend/services/two_lane_sources/pipeline.py)

## Commands Run

Replay the real case:

```powershell
python backend\scripts\replay_two_lane_query_builders.py `
  --project-id D6WAuHW3kontPlOkFN6O `
  --kapitel-id 9n6A4J430W7dbspdcYYg `
  --run-id hf5uawmdonQjmf1bDu2u `
  --user-id 2SpiVrPA0mONzFISUcLE8btDu9Q2 `
  --planner-attempts 1 `
  --openalex-attempts 3 `
  --s2-attempts 3 `
  --probe-top-k 3
```

Analyze the saved artifacts:

```powershell
python backend\scripts\analyze_two_lane_query_builder_lints.py `
  --run-dir backend\.two_lane_artifacts\investigations\D6WAuHW3kontPlOkFN6O_9n6A4J430W7dbspdcYYg_hf5uawmdonQjmf1bDu2u
```

Then additional independent sampling was run from the saved plan:

- OpenAlex independent samples: `4`
- S2 independent samples: `4`
- additional targeted OpenAlex failed-fingerprint capture: `1`

Total OpenAI usage across all investigation calls:

- input tokens: `121,742`
- cached input tokens: `91,008`
- output tokens: `244,007`
- reasoning tokens: `202,560`
- total tokens: `365,749`

## Key Findings

### 1. The OpenAlex failure is real, intermittent, and strongly linter-driven

For this exact chapter and run settings, one direct replay passed cleanly on the first OpenAlex attempt, but independent resampling from the same saved plan showed:

- OpenAlex: `3 / 4` independent generations failed
- Semantic Scholar: `4 / 4` independent generations passed

All reproduced OpenAlex failures in the independent sampling were caused by the same lint:

- `OpenAlex: anchor fingerprint concentration too high`

This means the failure is not tied to one impossible chapter. It is stochastic instability at the query-builder output plus an aggressive deterministic lint.

Artifacts:

- [independent_sampling.json](<projektverzeichnis>/backend/.two_lane_artifacts/investigations/D6WAuHW3kontPlOkFN6O_9n6A4J430W7dbspdcYYg_hf5uawmdonQjmf1bDu2u/independent_sampling.json)
- [openalex_summary.json](<projektverzeichnis>/backend/.two_lane_artifacts/investigations/D6WAuHW3kontPlOkFN6O_9n6A4J430W7dbspdcYYg_hf5uawmdonQjmf1bDu2u/openalex_summary.json)

### 2. `pipeline.py` has shadowed duplicate definitions, and the active OpenAlex fingerprint validator is the stricter one

The analyzer found `13` duplicate function definitions in [backend/services/two_lane_sources/pipeline.py](<projektverzeichnis>/backend/services/two_lane_sources/pipeline.py).

Most relevant duplicates:

- `diagnose_query_plan`
- `_normalize_openalex_query`
- `_normalize_s2_query`
- `_find_anchor_terms_in_text`
- `_validate_openalex_anchor_presence`
- `_validate_s2_anchor_presence`
- `_validate_openalex_match_anchor_fingerprint_diversity`

The critical bug is that the later `_validate_openalex_match_anchor_fingerprint_diversity` definition overrides the earlier one.

The earlier version excludes "always-on" anchors before judging diversity. The active later version does not.

That difference matters a lot in this case because the planner puts core object anchors like:

- `balance sheet`
- `BWA`
- `Bilanzen`

into `primary_context_anchors`, and those naturally appear in nearly every valid match query.

Artifacts:

- [lint_analysis.json](<projektverzeichnis>/backend/.two_lane_artifacts/investigations/D6WAuHW3kontPlOkFN6O_9n6A4J430W7dbspdcYYg_hf5uawmdonQjmf1bDu2u/lint_analysis.json)

### 3. The reproduced failed OpenAlex sample would fail under the active lint and pass under the legacy logic

A targeted failed OpenAlex sample was captured in:

- [openalex_failed_fingerprint_case.json](<projektverzeichnis>/backend/.two_lane_artifacts/investigations/D6WAuHW3kontPlOkFN6O_9n6A4J430W7dbspdcYYg_hf5uawmdonQjmf1bDu2u/openalex_failed_fingerprint_case.json)

For that one sample:

- active fingerprint EN share: `0.9231` with fingerprint `('balance sheet', 'bwa')`
- active fingerprint DE share: `0.7273` with fingerprint `('bilanzen', 'bwa')`
- legacy fingerprint EN: `pass = true`
- legacy fingerprint DE: `pass = true`

Why the legacy logic passes:

- it treats `balance sheet`, `BWA`, `Bilanzen`, and similar object anchors as always-on anchors
- it removes them from the diversity heuristic
- after removing them, the output no longer shows pathological low diversity

This is the strongest evidence that the current OpenAlex hard fail is at least partly caused by the linter itself, not only by bad model output.

### 4. The planner mixes object anchors, workflow anchors, and method anchors in one list

The saved plan for this chapter contains:

- `primary_context_anchors.en = ["balance sheet", "BWA", "financial contracts", "market follow up", "bank back office", "automated document analysis", "LLM", "NLP for finance"]`
- `core_object_terms.en = ["balance sheet", "BWA", "financial contract", "financial statement", "accounting report", "banking document"]`

This is semantically muddy.

`primary_context_anchors` currently contains a mix of:

- object/corpus terms
- business-process context
- method terminology

That is acceptable for a loose "must include some chapter anchor" check, but it is a poor basis for a diversity heuristic. A query family can be perfectly healthy while still reusing the same core object anchors.

### 5. Provider probes show a second problem: passing lints do not guarantee good retrieval

This investigation also looked at actual provider results.

Examples:

- A passed OpenAlex match query for `"balance sheet" / "financial contract" / "LLM"` returned only `5` hits, with top results about legal documentation, procurement, and other generic AI applications.
- Several passed or sampled OpenAlex authority queries returned strongly off-topic literature.
- A passed S2 authority probe returned an unrelated Korean banknote paper.

Artifacts:

- [openalex_passed_match_probe.json](<projektverzeichnis>/backend/.two_lane_artifacts/investigations/D6WAuHW3kontPlOkFN6O_9n6A4J430W7dbspdcYYg_hf5uawmdonQjmf1bDu2u/openalex_passed_match_probe.json)
- [openalex_failed_fingerprint_probes.json](<projektverzeichnis>/backend/.two_lane_artifacts/investigations/D6WAuHW3kontPlOkFN6O_9n6A4J430W7dbspdcYYg_hf5uawmdonQjmf1bDu2u/openalex_failed_fingerprint_probes.json)
- [openalex/openalex_attempt_1/provider_probes.json](<projektverzeichnis>/backend/.two_lane_artifacts/investigations/D6WAuHW3kontPlOkFN6O_9n6A4J430W7dbspdcYYg_hf5uawmdonQjmf1bDu2u/openalex/openalex_attempt_1/provider_probes.json)
- [s2/s2_attempt_1/provider_probes.json](<projektverzeichnis>/backend/.two_lane_artifacts/investigations/D6WAuHW3kontPlOkFN6O_9n6A4J430W7dbspdcYYg_hf5uawmdonQjmf1bDu2u/s2/s2_attempt_1/provider_probes.json)

So the current system has both problems at once:

- OpenAlex hard-fails too often on one brittle structural lint
- both providers can still produce poor retrieval even when lints pass

### 6. For this exact case, S2 hard-failure was not reproduced

The S2 builder did not fail in the direct replay or the `4` independent samples for this chapter.

That does not mean S2 is fully healthy:

- it shares some shadowed helpers in the same file
- it can still retrieve off-topic results while passing lint

But for this concrete reproduction, the major pipeline-stopper is OpenAlex, not S2.

## Root Cause Assessment

### Primary root cause

The active OpenAlex fingerprint diversity lint is too aggressive because it measures diversity on `primary_context_anchors` without excluding always-on object anchors.

### Contributing causes

- duplicate function definitions in [backend/services/two_lane_sources/pipeline.py](<projektverzeichnis>/backend/services/two_lane_sources/pipeline.py) hide which validator is actually in force
- the planner's `primary_context_anchors` field mixes multiple semantic roles
- the lints optimize for structural variety, not for observed provider quality
- the OpenAlex prompt still allows many query sets that are syntactically valid but semantically broad or drift-prone

## Recommended Fixes

### Fix 1. Remove duplicate definitions and keep one canonical validator block

This should be done first.

Without this, the code is difficult to reason about and future edits can silently target the wrong implementation.

### Fix 2. Replace the active OpenAlex fingerprint validator with the legacy "variable anchors only" behavior

Short-term safe fix:

- keep the diversity heuristic
- exclude anchors that appear in `>= 90%` of match queries
- only compute fingerprint concentration on the remaining variable anchors

That directly addresses the reproduced false-positive failures.

### Fix 3. Stop using `primary_context_anchors` as one mixed semantic bucket

Split the planner output into at least:

- `core_object_anchors`
- `workflow_context_anchors`
- `method_context_terms`

Then:

- mandatory anchoring can use the union
- fingerprint diversity should use only non-core, variable anchors

### Fix 4. Add a cheap provider smoke check after query generation

Current lints can pass obviously poor retrieval queries.

Suggested cheap check:

- probe only a very small subset of generated queries
- inspect top few titles/abstract snippets
- require at least some object-anchor presence in the returned records

This is especially useful for OpenAlex because the passed samples still showed major drift.

### Fix 5. Do not fail the entire run immediately on the first fingerprint-diversity violation

Safer retry policy:

- first failure: regenerate with feedback
- second failure: attempt auto-repair by injecting facet-specific non-core anchors or pruning repetitive match families
- only then fail hard

That reduces pipeline fragility while the query-builder prompts are improved.

## Suggested Engineering Order

1. Remove duplicate definitions in [backend/services/two_lane_sources/pipeline.py](<projektverzeichnis>/backend/services/two_lane_sources/pipeline.py).
2. Restore the legacy always-on-anchor exclusion in the OpenAlex fingerprint lint.
3. Add regression tests using saved failed outputs from this investigation.
4. Refactor planner schema to split anchor types.
5. Add a provider smoke-check gate for query quality.

## Regression-Test Material Collected

These artifacts are suitable as future golden fixtures:

- [query_plan.json](<projektverzeichnis>/backend/.two_lane_artifacts/investigations/D6WAuHW3kontPlOkFN6O_9n6A4J430W7dbspdcYYg_hf5uawmdonQjmf1bDu2u/query_plan.json)
- [openalex_failed_fingerprint_case.json](<projektverzeichnis>/backend/.two_lane_artifacts/investigations/D6WAuHW3kontPlOkFN6O_9n6A4J430W7dbspdcYYg_hf5uawmdonQjmf1bDu2u/openalex_failed_fingerprint_case.json)
- [independent_sampling.json](<projektverzeichnis>/backend/.two_lane_artifacts/investigations/D6WAuHW3kontPlOkFN6O_9n6A4J430W7dbspdcYYg_hf5uawmdonQjmf1bDu2u/independent_sampling.json)

These are especially useful for:

- a unit test that proves the active fingerprint lint rejects a case the legacy logic accepts
- a test that checks duplicate-function detection on `pipeline.py`
- a smoke test that verifies provider probes on the generated queries are not obviously off-topic
