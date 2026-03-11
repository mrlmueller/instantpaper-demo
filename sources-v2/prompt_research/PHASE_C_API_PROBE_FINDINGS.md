# Phase C API Probe Findings

Status: live API probe run and summarized on 2026-03-08.

## Goal

Probe the real OpenAlex and Semantic Scholar APIs before changing Phase C prompts, so the report reflects observed provider behavior rather than only docs and cached pipeline runs.

## Probe assets

- Probe script:
  - `sources-v2/prompt_research/phase_c_api_probe.py`
- Local venv:
  - `sources-v2/prompt_research/.venv_phase_c_probe/`
- Output artifacts:
  - `sources-v2/prompt_research/probe_outputs/phase_c_api_probe_20260308-164502.json`
  - `sources-v2/prompt_research/probe_outputs/phase_c_api_probe_20260308-164708.json`
  - `sources-v2/prompt_research/probe_outputs/phase_c_api_probe_20260308-164848.json`
  - `sources-v2/prompt_research/probe_outputs/phase_c_api_probe_20260308-164900.json`
  - `sources-v2/prompt_research/probe_outputs/phase_c_api_probe_20260308-164916.json`
  - `sources-v2/prompt_research/probe_outputs/phase_c_api_probe_20260308-164921.json`
  - `sources-v2/prompt_research/probe_outputs/phase_c_api_probe_20260308-164925.json`
  - `sources-v2/prompt_research/probe_outputs/phase_c_api_probe_20260308-164936.json`

## OpenAlex findings

### 1. Top-level `search` is dramatically broader than `title_and_abstract.search`

Observed with the same direct object phrase plus the same English filters:
- `search=online reviews` -> `meta.count=4,222,853`
- `filter=...,title_and_abstract.search:online reviews` -> `meta.count=254,273`

Interpretation:
- the current provider contract difference is real in practice, not just in docs
- top-level `search` is a much broader retrieval surface than the field-specific title/abstract filter

### 2. Advanced search operators worked live

Observed:
- `search=review*` -> `200`, nonzero, very broad
- `search=operationalization~1` -> `200`, nonzero
- `search="online reviews"~2` -> `200`, nonzero

Interpretation:
- wildcard, fuzzy, and proximity are not theoretical-only features; they worked live in the current API
- the current pipeline ban on `* ? ~` is therefore a local code/validation constraint, not a live OpenAlex constraint

### 3. Exact phrase AND can collapse quickly

Observed:
- `("online reviews" AND "proxy operationalization")` -> `0`
- `("online reviews" AND "selection bias")` -> `546` on top-level `search`, `26` on `title_and_abstract.search`

Interpretation:
- Boolean phrase conjunctions can be useful, but only when the paired phrases plausibly co-occur in titles/abstracts/records
- exact phrase AND is easy to over-constrain

## Semantic Scholar findings

### 1. Bulk search worked anonymously; standard search did not

Observed:
- `GET /graph/v1/paper/search/bulk` returned `200` repeatedly without an API key
- `GET /graph/v1/paper/search` returned `429` consistently without an API key

Interpretation:
- for ad hoc probing without a key, bulk search is the practical endpoint
- standard search should not be relied on anonymously for evaluation tooling

### 2. Direct English anchors beat abstract anchors

Observed:
- direct English object query -> `total=33`
- abstract-anchor query from the degraded run -> `total=4`
- bilingual fallback -> `total=23`

Interpretation:
- direct object phrases materially outperform abstract substitutes for this chapter
- bilingual fallback is useful, but the main recall burden should still sit on English object-first queries

### 3. German S2 queries are viable only in a narrow way

Observed:
- bad-run German query -> `total=0`
- better-run German query -> `total=2`
- simplified German direct query -> `total=0`
- German object + English facet query -> `total=2`

Interpretation:
- the live API does not support a broad German-mirroring strategy here
- German S2 queries should be used selectively and surgically
- English or bilingual fallback should remain the backbone

### 4. A third required group is expensive

Observed:
- two required groups -> `total=27`
- three required groups -> `total=3`

Interpretation:
- the third required group should be treated as a drift-control tool of last resort, not the default strong form

### 5. Bulk `limit` is not trustworthy as a tight cap

Observed on the same broad query:
- `limit=10` returned `749` or `1000`
- `limit=1` returned `935` or `1000`
- `limit=100` returned `797` or `1000`

Interpretation:
- the live bulk endpoint did not behave like a strict server-side page-size limiter
- any local logic that assumes `limit` tightly controls page size should be treated as unsafe until revalidated

### 6. Some edge-case syntax is unstable

Observed:
- longer negative phrase `-"systematic literature review"` returned `500` once and `200` later
- acronym-heavy query returned `200` once and `500` later

Interpretation:
- provider acceptance on these edge cases is not stable enough to trust blindly
- the pipeline's stricter local linting may be conservative, but it is not irrational

## Practical implications for the report

### OpenAlex

- Treat provider-contract drift as confirmed:
  - current OpenAlex `search` and advanced operators really do work live
- Prefer top-level `search` for broader authority-style queries
- Use `title_and_abstract.search` only for intentionally tighter match families
- Avoid exact phrase AND unless the phrase pair is realistically co-occurring

### Semantic Scholar

- Keep English object-first queries as the main recall backbone
- Use bilingual fallback as a second layer
- Use German-only S2 queries sparingly
- Avoid defaulting to three required groups
- Do not assume bulk `limit` behaves like a normal page-size cap
- Treat longer negatives and acronym-heavy groups as unstable edge cases

## Next useful probe directions

1. Test the same S2 probes again with a real `SEMANTICSCHOLAR_API_KEY`, if available.
2. Compare OpenAlex top-level `search` against a code-built semantic-group assembly later.
3. Once prompt rewrites are ready, replay a focused subset of these probes against generated query candidates before full pipeline reruns.
