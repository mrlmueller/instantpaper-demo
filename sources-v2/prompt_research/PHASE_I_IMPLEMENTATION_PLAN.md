# Phase I Implementation Plan

Status: implementation-ready plan based on the 2026-03-10 empirical probe.

## Goal

Improve final ranking accuracy while keeping:
- `gpt-5-nano`
- strong comparability across about `160` pointwise calls per run
- structured, auditable outputs

Primary target:
- better top-20 / top-40 relevance
- especially fewer generic method papers outranking chapter-specific papers

## Recommended architecture

Use a two-step rerank:

1. Pointwise rubric rerank on the normal Phase I candidate set.
2. Pairwise refinement only on the `with_abstract` top slice.

Do not pairwise-rerank `without_abstract`.

## Step 1: Compact pointwise rubric

### Prompt contract

System prompt:

```text
You are a careful scientific-source judge.
Use ONLY the chapter contract, candidate metadata, and numbered evidence tags.
Your job is to score dimensions consistently, not to write an essay.
Treat generic but high-status papers as weak unless they clearly help this exact chapter.
Return strict JSON only.
```

User prompt template:

```text
CHAPTER_CONTRACT:
{compact_chapter_contract}

LANE:
{lane}
POOL:
{pool}

LANE_GUIDANCE:
{lane_guidance}

REQUIRED_FACETS:
{compact_required_facets_json}

CANDIDATE_METADATA:
{compact_candidate_metadata}

EVIDENCE_TAGS:
{compact_numbered_evidence_tags_json}

DIMENSION DEFINITIONS (0-4 each):
- topical_fit_0_4: how directly the source matches the chapter object/question.
- evidence_strength_0_4: how strong and specific the provided evidence tags are.
- chapter_utility_0_4: how likely the source is to help write this chapter.
- lane_fit_0_4: for match, direct topical fit; for authority, foundational value AFTER relevance.

HARD RULES:
- off_topic=true if the candidate is clearly outside the chapter's target problem.
- insufficient_info=true if evidence is too thin for a confident score.
- Without-abstract items should usually be conservative unless multiple strong evidence tags support them.
- covered_facets must be explicitly supported only.
- evidence_tag_ids must only include tags you actually used.
- brief_rationale must be short and concrete.
```

### Output schema

Use a structured schema like:

```json
{
  "topical_fit_0_4": 0,
  "evidence_strength_0_4": 0,
  "chapter_utility_0_4": 0,
  "lane_fit_0_4": 0,
  "covered_facets": [],
  "evidence_tag_ids": [],
  "off_topic": false,
  "insufficient_info": false,
  "brief_rationale": ""
}
```

### Model settings

- model: `gpt-5-nano`
- reasoning effort: `low`
- max output tokens: about `800`

Do not use `medium` as the default:
- it is more expensive
- it was less stable in the probe
- it did not improve ranking quality

## Step 2: Deterministic final pointwise score

Do not let the model emit the final 0-100 score directly.
Compute it in code from the rubric:

```text
score = round((35 * topical_fit + 25 * evidence_strength + 25 * chapter_utility + 15 * lane_fit) / 4.0)
```

Then apply deterministic caps:

1. If `off_topic=true`:
   - `score = min(score, 25)`

2. If `insufficient_info=true`:
   - `with_abstract`: `score = min(score, 45)`
   - `without_abstract`: `score = min(score, 35)`

3. If `lane=="authority"` and `topical_fit_0_4 <= 1`:
   - `score = min(score, 35)`

4. If `covered_facets` is empty:
   - `score = min(score, 30)`

This was the strongest production-shape design in the probe.

## Step 3: Pairwise refinement on the top slice

### When to run

After the pointwise rerank:
- only for `with_abstract`
- only for the top `6`
- for both `match` and `authority`

That means:
- `15` comparisons per lane
- `30` pairwise calls per run

This is cheap enough to keep because runtime does not matter here.

### Pairwise prompt

System prompt:

```text
You are comparing two scientific sources for one chapter.
Use ONLY the chapter contract, metadata, and evidence tags.
Choose the source that is more useful for this exact chapter and lane.
Return strict JSON only.
```

User prompt template:

```text
CHAPTER_CONTRACT:
{compact_chapter_contract}

LANE:
{lane}
POOL:
with_abstract

CANDIDATE_A_METADATA:
{candidate_a_metadata}

CANDIDATE_A_TAGS:
{candidate_a_tags_json}

CANDIDATE_B_METADATA:
{candidate_b_metadata}

CANDIDATE_B_TAGS:
{candidate_b_tags_json}

Choose which candidate is more useful for this chapter and lane.
```

### Pairwise schema

```json
{
  "winner": "A",
  "confidence_0_3": 0,
  "brief_rationale": ""
}
```

Allowed winners:
- `A`
- `B`
- `tie`

### Pairwise settings

- model: `gpt-5-nano`
- reasoning effort: `low`
- max output tokens: about `800`

### Pairwise ordering logic

To reduce position bias:
- randomize A/B order deterministically by hash
- map the winner back to the original candidate IDs

Ranking rule:
- round-robin over the top `6`
- winner gets `1.0 + 0.1 * confidence_0_3`
- tie gives `0.5` to each
- reorder the top `6` by total win score
- keep the rest of the ranking unchanged

## Input compaction rules

These are important for nano stability.

### Chapter contract

Use a compact deterministic chapter contract, not the whole chapter spec:
- title
- topic summary
- core object terms
- primary anchors
- must-keep constraints
- drift risks

Keep it around `900-1200` characters, not a long free-form block.

### Required facets

Pass only a compact list of the highest-priority facets:
- top `5-6` weight>=4 facets
- fields:
  - `facet_id`
  - short label

### Candidate metadata

Use:
- title
- year
- venue
- citations
- abstract presence
- abstract excerpt

Recommended abstract budget:
- pointwise: about `650` characters
- pairwise: about `500` characters per candidate

Do not include authors in the main scoring prompt.
They add tokens but did not help relevance judgment.

### Evidence tags

Pass compact numbered tags only:
- `tag_id`
- `facet_id`
- tag score
- short excerpt

Recommended excerpt length:
- about `260` characters

## Failure handling

This is mandatory.

The probe showed that nano occasionally returns:
- empty structured output
- malformed JSON

Recommended runtime behavior:

1. Retry structured-output calls up to `5` times.
2. Track total tokens/cost across retries.
3. If retries still fail:
   - pointwise fallback:
     - `score = 0`
     - `insufficient_info = true`
     - `call_failed = true`
   - pairwise fallback:
     - `winner = tie`
     - `confidence_0_3 = 0`
     - `call_failed = true`
4. Log `call_failed` in artifacts and metrics.

This should not be silent.

## What not to implement

Do not implement these as the default Phase I design:

1. `medium` reasoning on nano
- worse operationally
- more expensive
- no quality win

2. Prompt-only hard object gate
- did not become the best variant
- introduced new ranking mistakes

3. Long free-form rationale outputs
- expensive
- unnecessary
- worse for comparability

4. Pairwise rerank for `without_abstract`
- not worth the extra calls
- evidence is too weak

## Expected impact

Compared with the current baseline:

- better top-20 / top-40 ordering
- fewer generic method papers beating chapter-specific papers
- cheaper and shorter pointwise outputs
- better auditable structure
- small extra runtime from pairwise refinement

What this will not fully solve:
- noisy authority candidates created upstream
- weak or overly generous Phase H coverage tags

So the correct expectation is:
- meaningful rerank improvement
- not a complete substitute for upstream cleanup

## Implementation order

1. Replace the current Phase I pointwise prompt/schema with the compact rubric contract.
2. Add deterministic score aggregation and caps in code.
3. Add compact chapter-contract / required-facet / metadata builders.
4. Add retry + fallback accounting.
5. Add pairwise top-6 refinement for `with_abstract`.
6. Extend Phase I artifacts/metrics with:
   - `call_failed`
   - pointwise rubric subscores
   - pairwise win summaries

## Final recommendation

Default Phase I after implementation should be:

- pointwise:
  - compact rubric
  - `gpt-5-nano`
  - low reasoning
- pairwise:
  - top `6`
  - `with_abstract` only
  - low reasoning
- deterministic aggregation:
  - weighted rubric score
  - hard caps for off-topic / insufficient-info cases

This is the best Phase I design found in the live probe.
