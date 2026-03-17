# D/E/F Tuning Loop Against Full 22-Paper Benchmark

## Scope

Primary test bed: `benchmark/full_dump_webshop_manual_v1`

- 22 judged PDFs
- 21 positive docs
- 1 negative doc
- 33 manually anchored section targets

Baseline run under test: `386e04657c41c805f8c1b974`

This loop focused on D/E/F first, with the full 22-paper suite as the main regression bed and only a cheap final calibration sweep on top of the best D/E/F stack.

## What Changed

### Phase D

Files:

- `pdf-scan/phase_d_lab.py`

Changes:

- tightened bridge-term filtering so junk phrases like trailing-stopword fragments do not survive
- expanded the bridge corpus inventory beyond titles/headings to include sampled section snippets from retrieval-eligible sections
- updated the bridge prompt to use titles, headings, and snippets instead of titles/headings only

Intent:

- improve corpus-aware query expansion without hardcoding benchmark-specific topics
- surface corpus-side vocabulary that is absent from the chapter text but important for retrieval

### Phase E

Files:

- `pdf-scan/phase_e_lab.py`

Changes:

- replaced title-only doc rescue scoring with document-summary rescue
- document summaries now use:
  - doc title
  - heading preview
  - short sampled section previews
- doc rescue now prefers sections that already have fused evidence and only lightly boosts additional within-doc candidates
- rescue prioritization now de-emphasizes docs that are already strongly represented in the fused pool

Intent:

- rescue semantically relevant docs with weak/raw titles
- promote useful sections inside rescued docs without flooding the fused pool with generic sections

### Phase F

Files:

- `pdf-scan/phase_f_lab.py`

Changes:

- enriched the global rerank query with bridge terms
- enriched subpoint rerank queries with linked bridge terms

Intent:

- stop reranking from collapsing back to the literal chapter wording after Phase D/E had already expanded recall

### Harness / Benchmarking

Files:

- `pdf-scan/phase_def_benchmark_search.py`
- `pdf-scan/phase_b_lab.py`
- `pdf-scan/pdf_reporting.py`
- `pdf-scan/evaluate_manual_benchmark.py`

Changes:

- added new search variants for high-recall D/E/F stacks
- fixed JSONL robustness issues so iterative reruns no longer crash on partial rows
- added the best observed end-to-end variant to the search harness for future reruns

## Full-Dump Results

### Previous strong probe before this loop

Artifact:

- `runs/386e04657c41c805f8c1b974/phase_def_benchmark_search/light_doc_rescue_probe.json`

Results:

- doc recall: `0.2381`
- Phase E anchor hit@doc-top10: `0.3636`
- Phase F anchor hit@doc-top10: `0.2424`
- Phase G anchor hit@doc-top5: `0.2424`

### Best D/E/F stack from this loop

Artifact:

- `runs/386e04657c41c805f8c1b974/phase_def_benchmark_search/summary_doc_rescue_max_rerank.json`

Results:

- doc recall: `0.2857`
- doc precision: `1.0`
- structure presence recall: `0.9394`
- Phase E anchor hit@doc-top10: `0.4545`
- Phase F anchor hit@doc-top10: `0.3333`
- Phase G anchor hit@doc-top5: `0.3333`

This is the best D/E/F result observed in this loop.

### Calibration sweep on top of the best D/E/F stack

Artifacts:

- `runs/386e04657c41c805f8c1b974/phase_def_benchmark_search/g_relaxed_1.json`
- `runs/386e04657c41c805f8c1b974/phase_def_benchmark_search/g_relaxed_2.json`
- `runs/386e04657c41c805f8c1b974/phase_def_benchmark_search/g_relaxed_3.json`

Best probe:

- `g_relaxed_3`

Results:

- doc recall: `0.4286`
- doc precision: `1.0`
- Phase G anchor hit@doc-top5: `0.3333`

Interpretation:

- the D/E/F stack is materially better than before
- final document usefulness is now partly bottlenecked by calibration, not just retrieval
- relaxing G increases doc recall without changing anchor hit, which means the section pool is stronger than the original final thresholds allowed

## What Improved Concretely

- several bridge terms are now corpus-grounded and useful instead of noisy fragments
- the best D/E/F stack raised Phase E anchor coverage from `0.3636` to `0.4545`
- the best D/E/F stack raised Phase F anchor hit from `0.2424` to `0.3333`
- the best D/E/F stack raised end-to-end doc recall from `0.2381` to `0.2857`
- a relaxed G pass on the same D/E/F outputs raised doc recall further to `0.4286`

Current best true-positive docs after the stronger D/E/F stack include:

- `consumers_decision_making_process_on_social_comm-7a6fd346a557`
- `digital_nudging_altering_user_behavior_in_digita-790f8fc6abef`
- `digital_nudging-c70013fb5862`
- `digital_nudging_with_recommender_systems-b0730604bb9e`
- `judgment_under_uncertainty_heuristics_and_biases-5d61ba1a71f6`
- `the_effectiveness_of_nudging-76e15b34d02c`

## Remaining False-Negative Clusters

The main remaining misses are not random. They cluster into a few groups:

### Review / trust papers with still-missed anchors

- `whose_online_reviews_to_trust_understanding_revi-22354b2e8251`
- `natural_language_processing_for_analyzing_online-152aaa107e77`
- `online_reviews_and_information_overload_the_role-42fa5aa25910`
- `opinion_mining_and_sentiment_analysis-d837b2bce0b4`

Pattern:

- strong relevant sections exist structurally
- some anchors still do not enter the top candidate pool or final section scores remain too low

### Short review-analysis papers with weak final scoring

- `using_online_reviews_for_customer_sentiment_anal-ba995f136320`
- `sentiment_analysis_in_e_commerce_platforms_a_rev-0c59fc64f2e7`
- `evolving_techniques_in_sentiment_analysis_a_comp-68fe188f165a`

Pattern:

- limited good section surfaces
- current scoring still underestimates indirect usefulness

### Fake-review paper with structurally present but retrieval-missed targets

- `fake_online_reviews_literature_review_synthesis_-e9bbe09bb4bf`

Pattern:

- structure is mostly there
- several manual anchors still do not surface in Phase E/F strongly enough

## Main Conclusion

Phase C is no longer the main bottleneck for this benchmark.

The most effective improvements in this loop were:

1. corpus-aware bridge expansion with better hygiene
2. document-summary rescue in Phase E
3. letting Phase F rerank a much larger candidate pool with richer bridge-aware queries

The strongest current configuration is:

- search variant: `summary_doc_rescue_max_rerank`
- optional relaxed calibration on top: `g_relaxed_3`

## Sources Used

- PyTerrier RM3 / query reformulation docs: https://pyterrier.readthedocs.io/en/stable/terrier/api.html
- PyTerrier dense PRF docs: https://pyterrier.readthedocs.io/en/latest/ext/pyterrier-dr/prf.html
- Sentence Transformers retrieve-rerank docs: https://www.sbert.net/examples/sparse_encoder/applications/retrieve_rerank/README.html
- Sentence Transformers cross-encoder evaluation docs: https://www.sbert.net/docs/cross_encoder/training_overview.html
- ColBERT paper: https://arxiv.org/abs/2004.12832

## Recommended Next Step

Freeze the current D/E/F code changes and do a focused false-negative loop on:

- review/trust papers
- fake-review papers
- short survey/review-analysis papers

That next loop should target:

- Phase E candidate surfacing for missed anchors
- Phase G calibration for clearly useful but mid-score documents
