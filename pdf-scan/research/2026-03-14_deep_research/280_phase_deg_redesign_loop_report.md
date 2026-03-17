# Phase D/E/G Redesign Loop

## Scope

- Benchmark suite: `full_dump_webshop_manual_v2_exhaustive`
- Primary test bed: full `22`-PDF dump
- Frozen baseline run: `386e04657c41c805f8c1b974`
- Redesign experiment run: `7f935a57200c4361a3f09466`

This loop focused on the real bottleneck exposed by the exhaustive benchmark:

- Phase C structure was no longer the dominant problem.
- Phase D was still too narrow.
- Phase E was still missing some gold sections, especially in survey / review / trust papers.
- Phase G was the largest document-level recall bottleneck.

## What Changed

### Benchmark evaluation

The benchmark evaluator now separates:

- `gold_section_anchor_metrics`
- `exhaustive_section_anchor_metrics`

This matters because the exhaustive suite contains every section judgment, while the gold subset is the right target for model selection and search-loop comparisons.

Files:

- `tools/benchmark/evaluate_manual_benchmark.py`

### Phase D redesign

Changes:

- added a new `planner_prompt_mode="coverage"`
- rewrote the coverage prompt to use clearer titled blocks and explicit recall-oriented guidance
- added broader but still source-grounded planning instructions for:
  - theory and mechanisms
  - operational factors and design implications
  - quality / trust / authenticity / failure-signal evidence
  - supporting scientific context when it enriches the chapter
- added new retrieval views:
  - `should_terms_lexical`
  - `support_context_semantic`
  - `subpoint_lexical_views`

Files:

- `phase_d_lab.py`

### Phase E redesign

Changes:

- updated lane weights for the new Phase D view kinds
- let lexical and dense retrieval benefit from:
  - `should_terms_lexical`
  - `support_context_semantic`
  - `subpoint_lexical`

Files:

- `phase_e_lab.py`

### Phase G redesign

Changes:

- made document scoring less top-section-fragile
- added `broad_support_case`
- increased the weight of multi-section evidence and partial useful sections
- exposed new calibration controls:
  - `broad_support_min_sections`
  - `broad_support_top1_floor`
  - `broad_support_probability_bonus`

Files:

- `phase_g_lab.py`

### Search harness

Changes:

- default benchmark switched to `full_dump_webshop_manual_v2_exhaustive`
- leaderboard now ranks by gold metrics instead of the old undifferentiated anchor total
- added redesign variants centered on broader Phase D planning and broader Phase G calibration

Files:

- `phase_def_benchmark_search.py`

## Prompting Research Used

Prompt changes were guided by official OpenAI documentation, not by benchmark-specific hardcoding.

Sources:

- OpenAI Prompting Guide: <https://platform.openai.com/docs/guides/text?api-mode=responses>
- Structured Outputs: <https://platform.openai.com/docs/guides/structured-outputs>
- Prompt Generation / Prompt Optimization: <https://platform.openai.com/docs/guides/prompt-generation>

Applied takeaways:

- structure prompts into clearly separated sections instead of one dense block
- state the objective and constraints explicitly
- keep the output schema tight and typed
- iterate against evals instead of trusting prompt intuition

## Frozen Baseline

Run:

- `runs/386e04657c41c805f8c1b974`

Gold benchmark metrics:

- doc recall: `0.4286`
- doc precision: `1.0`
- gold Phase E hit@doc-top10: `0.4222`
- gold Phase F hit@doc-top10: `0.3689`
- gold Phase G hit@doc-top5: `0.2711`

This baseline was already better than the earlier under-strict runs, but it was still missing too many useful PDFs.

## Redesign Sweep Results

Run:

- `runs/7f935a57200c4361a3f09466`

Variant leaderboard:

1. `coverage_prompt_dual_views_broad_g`
   - doc recall: `0.3810`
   - gold Phase E hit@doc-top10: `0.4089`
   - gold Phase F hit@doc-top10: `0.3378`
   - gold Phase G hit@doc-top5: `0.2622`
2. `coverage_prompt_max_recall`
   - doc recall: `0.3333`
   - gold Phase E hit@doc-top10: `0.4978`
   - gold Phase F hit@doc-top10: `0.3600`
   - gold Phase G hit@doc-top5: `0.2711`

Interpretation:

- the broader D/E stack clearly improved retrieval recall
- the best D/E stack did not automatically improve document recall
- that confirmed Phase G was still too strict even after the D/E redesign

Artifacts:

- `runs/7f935a57200c4361a3f09466/phase_def_benchmark_search/leaderboard.json`
- `runs/7f935a57200c4361a3f09466/phase_def_benchmark_search/coverage_prompt_max_recall.json`

## G-only Calibration Sweep on the Best D/E Stack

I then held the best D/E/F stack fixed (`coverage_prompt_max_recall`) and swept Phase G only.

Important results:

- `g_ultra_recall`
  - doc recall: `0.5238`
  - doc precision: `1.0`
- `g_super_open_v2`
  - doc recall: `0.6667`
  - doc precision: `1.0`
  - useful docs surfaced: `14`

Winning artifact:

- `runs/7f935a57200c4361a3f09466/phase_def_benchmark_search/g_super_open_v2.json`

The final run output now reflects that winning operating point, because `g_super_open_v2` was the last applied Phase G sweep on the experiment run.

## Best Current Operating Point

Best combined stack right now:

- Phase D/E/F variant: `coverage_prompt_max_recall`
- Phase G calibration: `g_super_open_v2`

Best current full-dump outcome:

- doc recall: `0.6667`
- doc precision: `1.0`
- surfaced useful PDFs: `14 / 21`

New useful PDFs now surfaced that were previously being rejected:

- `23_ways_to_nudge`
- `a_review_of_nudges`
- `beyond_self_selection_the_multilayered_online_reviews...`
- `online_reviews_and_information_overload...`
- `whose_online_reviews_to_trust...`
- `opinion_mining_and_sentiment_analysis`
- `natural_language_processing_for_analyzing_online_customer_reviews...`

This is the main practical gain from the loop: the pipeline is no longer collapsing almost entirely onto the digital-nudging cluster plus the strongest trust paper.

## Remaining False Negatives

The remaining `7` false-negative PDFs in the best current operating point are:

- `development_of_methodology_for_classification_of...`
- `evolving_techniques_in_sentiment_analysis...`
- `fake_online_reviews_literature_review_synthesis...`
- `improving_decisions_about_health_wealth_and_happiness...`
- `sentiment_analysis_in_e_commerce_platforms...`
- `to_nudge_or_not_to_nudge`
- `using_online_reviews_for_customer_sentiment_analysis`

These split into two groups:

1. Low-ranking upstream misses

- very low top-section scores
- needs more D/E/F work, not more G relaxation

2. Thin-support document calls

- decent top section but weak multi-section support in the current reranked output
- needs better section surfacing or more tolerant support aggregation

## Cost

Run-level OpenAI cost for the redesign experiment:

- total: `$1.48733571`
- Phase D: `$0.20055375`
- Phase E: `$0.63438476`
- Phase F: `$0.65239720`

Artifact:

- `runs/7f935a57200c4361a3f09466/api_calls.jsonl`

## Conclusion

The redesign loop produced a real improvement.

What improved materially:

- broader Phase D planning improved retrieval recall
- the new view set improved Phase E gold-section surfacing
- the biggest gain came from acknowledging that the pipeline was under-calling useful PDFs and redesigning Phase G accordingly

What did **not** improve yet:

- final top-5 section quality did not move much beyond the previous best stack
- the remaining false negatives still require more upstream work, especially around survey / review / fake-review literature that is useful but not yet ranked strongly enough

The current best operating point is good enough to continue iterating from, and it is materially less strict than the older pipeline.
