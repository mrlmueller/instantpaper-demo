# Phase I Rerank Probe Findings

Status: completed on 2026-03-10.

## Scope

Goal:
- design the strongest practical Phase I reranking stage while keeping `gpt-5-nano`
- test prompt drift, ranking quality, and operational stability on real cached pipeline data

Runs tested:
- `ca79147de41f8edbfb47c9e5`
- `25e6243ac55a5904fb1fcdfe`

Data used:
- Phase G rankings
- candidate metadata / abstracts
- Phase H coverage tags
- query plan / chapter contract

Primary probe script:
- `phase_i_rerank_probe.py`

Main probe outputs:
- `probe_outputs/phase_i_rerank_probe_20260310-212306.json`
- `probe_outputs/phase_i_rerank_probe_20260310-212306.summary.md`
- `probe_outputs/phase_i_rerank_probe_20260310-230753.json`
- `probe_outputs/phase_i_rerank_probe_20260310-230753.summary.md`

## Spend

Total known Phase I probe spend across pilots and full runs:
- about `$1.30`

Final two full passes:
- full comparison pass: about `$0.2283`
- object-gate follow-up: about `$0.2703`

This stayed comfortably below the user-approved `$3` ceiling.

## Variants tested

Pointwise:
- `baseline_current`
  - close to the current Phase I design
  - single 0-100 score
  - long rationale
- `contract_low`
  - compact single-score prompt
  - low reasoning effort
- `rubric_low`
  - compact 4-dimension rubric
  - low reasoning effort
- `rubric_medium`
  - same rubric, medium reasoning effort
- `rubric_object_gate`
  - stronger prompt-level object-fit gate
  - low reasoning effort

Top-slice pairwise refinement:
- `*_pairwise_top6`
  - round-robin pairwise comparisons over the top 6 `with_abstract` items per lane
  - deterministic A/B order randomization by hash
  - win-count reorder

Reference labels:
- `gpt-5-mini`
- grade scale `0..3`
- applied to the pooled top candidates across variants

## Main empirical result

Best overall design:
- `rubric_low_pairwise_top6`

Why:
- best mean `nDCG@20`
- best practical balance of cost, stability, and quality
- no operational failure in the main pass
- pairwise refinement improved ordering where it mattered: the `with_abstract` top slice

### Aggregate comparison

From the final pass `phase_i_rerank_probe_20260310-230753.json`:

| variant | mean_ndcg20 | mean_p10 | mean_off_topic_top20 |
| --- | ---: | ---: | ---: |
| `baseline_current` | `0.889` | `0.762` | `0.188` |
| `contract_low` | `0.851` | `0.662` | `0.188` |
| `rubric_low` | `0.904` | `0.787` | `0.188` |
| `rubric_low_pairwise_top6` | `0.919` | `0.787` | `0.188` |
| `rubric_medium` | `0.847` | `0.750` | `0.188` |
| `rubric_object_gate` | `0.885` | `0.750` | `0.188` |
| `rubric_object_gate_pairwise_top6` | `0.884` | `0.750` | `0.188` |

Interpretation:
- the compact rubric beats the current baseline even before pairwise refinement
- the pairwise top-6 pass gives the best ranking lift
- the compact single-score contract prompt underperformed
- medium reasoning is not worth it on nano
- the stricter object-gate prompt did not improve the overall result

## Stability and operational behavior

### Main operational lesson

The biggest unexpected Phase I finding was operational:
- nano often spent the whole output budget on hidden reasoning and returned no JSON at all
- this happened especially with longer prompts and medium reasoning effort

That forced two concrete design conclusions:
- the prompt must stay compact
- `reasoning_effort="low"` is the right default for nano

### Stability summary

From the final pass:

| variant | repeat_diff_mean | shuffle_diff_mean | call_fail_rate |
| --- | ---: | ---: | ---: |
| `contract_low` | `9.09` | `8.91` | `0.000` |
| `rubric_low` | `12.41` | `7.22` | `0.000` |
| `rubric_object_gate` | `7.34` | `9.00` | `0.031` |
| `rubric_medium` | `6.69` | `7.31` | `0.156` |

Interpretation:
- all nano variants still have non-trivial score drift
- medium reasoning is materially worse operationally
- low-reasoning rubric variants are usable; medium-reasoning rubric is not a good production default

### Token / cost profile

Main pointwise pass only:

| variant | mean_input_tokens | mean_output_tokens | mean_cost_per_call |
| --- | ---: | ---: | ---: |
| `baseline_current` | `1271.0` | `1868.4` | `$0.000811` |
| `contract_low` | `1247.8` | `436.9` | `$0.000232` |
| `rubric_low` | `1259.4` | `586.3` | `$0.000293` |
| `rubric_medium` | `1601.0` | `2287.8` | `$0.000982` |

Pairwise refinement:

| variant | mean_input_tokens | mean_output_tokens | mean_cost_per_call |
| --- | ---: | ---: | ---: |
| `contract_low` | `2099.8` | `417.3` | `$0.000251` |
| `rubric_low` | `1862.6` | `416.7` | `$0.000249` |
| `rubric_medium` | `2328.2` | `409.9` | `$0.000256` |

Interpretation:
- `rubric_low` is much cheaper than the current baseline while ranking better
- `rubric_medium` is both worse and more expensive
- pairwise top-6 is cheap enough to keep if runtime does not matter

## Manual top-list read

### Roman run (`ca79147de41f8edbfb47c9e5`)

`rubric_low_pairwise_top6` improved the `match/with_abstract` top slice in a direction that looks semantically right:
- `The Growth and Decline of the Western Roman Empire...`
- `The Roman Dominate from the Perspective of Demographic-Structural Theory`
- `Vice-versa: The iron trade in the western Roman Empire...`
- `Division of labor, specialization and diversity in the ancient Roman cities...`

This is better aligned with the chapter than several weaker baseline placements.

But the authority lane remains noisy:
- `Christianization and Latinization`
- `Why were the UK and USA unprepared for the COVID-19 pandemic?`
- `Fluent but Not Factual...`

Interpretation:
- Phase I can improve ordering
- it cannot fully repair upstream authority-pool noise by prompt changes alone

### Online-reviews / proxy-operationalization run (`25e6243ac55a5904fb1fcdfe`)

`rubric_low_pairwise_top6` produced a better top `match/with_abstract` slice:
- `Comparison of text preprocessing methods`
- `Evaluating the Effectiveness of Text Pre-Processing in Sentiment Analysis`
- `Recommender Systems Based on Collaborative Filtering Using Review Texts`
- `A scoping review of preprocessing methods for unstructured text data`

This is materially better than variants that let broad topic-modeling or generic LLM survey papers dominate.

### Object-gate follow-up

The object-gate prompt did not become the new winner.

Why not:
- it slightly improved some authority placements
- but it also over-corrected and surfaced obviously wrong items in other places

Examples:
- `Topic modeling in software engineering research`
- `Cultural Landscapes: Exploring the Imprint of the Roman Empire on Modern Identities`
- `The phonetics and phonology of Eastern Andalusian Spanish`

Interpretation:
- a stronger prompt-only object gate is not the right solution
- the right fix is still the compact rubric plus pairwise refinement, with upstream pool cleanup left to earlier phases

## Conclusions

1. Keep `gpt-5-nano`, but use a compact rubric prompt and `reasoning_effort="low"`.
2. Replace the current long 0-100 prompt with a structured multidimensional rubric.
3. Compute the final score deterministically in code from rubric dimensions.
4. Add a pairwise refinement pass only for the top `with_abstract` slice.
5. Do not use medium reasoning as the default nano setting.
6. Do not adopt the stricter prompt-level object gate as the main design.
7. Keep explicit retry + conservative fallback handling, because operational failure rate is a real quality dimension for this stage.

## Recommended default Phase I design

- pointwise pass on the normal Stage G shortlist
- variant:
  - `rubric_low`
- pairwise refinement:
  - top `6` only
  - `with_abstract` only
  - both `match` and `authority`
- no pairwise refinement for `without_abstract`
- compact chapter contract
- compact evidence tags
- deterministic scoring caps for:
  - `off_topic`
  - `insufficient_info`
  - weak authority topical fit
  - empty facet support

Implementation-ready details are in:
- `PHASE_I_IMPLEMENTATION_PLAN.md`
