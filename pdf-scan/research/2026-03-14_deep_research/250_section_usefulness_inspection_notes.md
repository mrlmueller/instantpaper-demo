# Section Usefulness Inspection Notes

Date: 2026-03-17
Run: `386e04657c41c805f8c1b974`
Scope: full `paper-dump` corpus (`22` PDFs), current end-to-end A-G pipeline output

Artifacts used:
- `runs/386e04657c41c805f8c1b974/final/output.json`
- `runs/386e04657c41c805f8c1b974/section_inspection/all_sections.jsonl`
- `runs/386e04657c41c805f8c1b974/section_inspection/section_scores_openai.jsonl`
- `runs/386e04657c41c805f8c1b974/section_inspection/benchmark_target_reviews.jsonl`
- `runs/386e04657c41c805f8c1b974/section_inspection/benchmark_target_reviews.md`
- `runs/386e04657c41c805f8c1b974/section_inspection/per_doc/`

Helper scripts used:
- `build_section_inspection_dataset.py`
- `score_full_dump_sections.py`
- `review_benchmark_targets.py`

OpenAI inspection cost:
- Section scoring: `235,661` input / `94,506` output tokens, about `$0.2479`
- Benchmark target review: `23,511` input / `11,947` output tokens, about `$0.0298`
- Combined: about `$0.2777` on `gpt-5-mini`

## Findings Log

### Finding 01
The current run is still too strict at the final product level.

- Current pipeline output marks only `9` PDFs as useful.
- The manual full-dump benchmark currently expects `21` positive PDFs and `1` negative PDF.
- Practical implication: the user perception is correct. The app still behaves as an over-conservative filter.

### Finding 02
The problem is not mainly Phase C anymore.

- I scored all `574` extracted sections.
- `217` sections scored `>= 7/10` for usefulness.
- `156` sections scored `>= 8/10`.
- `81` sections scored `>= 9/10`.
- Only `63` of the `217` sections with score `>= 7` survive into Phase G section scoring.
- Practical implication: the biggest loss is now downstream recall and calibration, not only structure extraction.

### Finding 03
There are many useful sections inside PDFs that are currently labeled `no match`.

- Useful sections with score `>= 7` that live inside docs currently marked useful: `133`
- Useful sections with score `>= 7` that live inside docs currently marked not useful: `84`
- Practical implication: the app is discarding whole PDFs that already contain enough good material.

### Finding 04
The false negatives are not marginal cases. Some of them are extremely rich.

Worst false-negative docs by number of sections scored `>= 8/10`:
- `Online Reviews and Information Overload...`: `15`
- `Beyond self-selection...`: `11`
- `Opinion Mining and Sentiment Analysis`: `9`
- `Fake online reviews...`: `5`
- `Whose online reviews to trust?`: `2`
- `Using Online Reviews for Customer Sentiment Analysis`: `2`

Practical implication: the current per-document gate is suppressing strongly useful literature.

### Finding 05
The benchmark misses are dominated by late calibration and early recall, not reranking.

Benchmark miss reasons across `33` target sections:
- `phase_g_threshold_or_doc_calibration`: `14`
- `phase_e_retrieval_recall_gap`: `9`
- `phase_e_retrieval_miss`: `5`
- `phase_f_rerank_downranked`: `2`
- `phase_c_structure_issue`: `2`
- `phase_f_rerank_miss`: `1`

Practical implication: the main bottlenecks are Phase E and Phase G.

### Finding 06
The chapter is not one search intent. It is several partially independent search intents.

Among high-value sections in false-negative docs, the dominant categories are:
- `review_quality_authenticity`: `28`
- `information_presentation_filtering_comparison`: `19`
- `trust_risk_uncertainty`: `19`
- `nudging_choice_architecture`: `8`
- `decision_psychology_theory`: `6`

Practical implication: the query planning is still under-modeling the task. We are not only looking for heuristics, nudging, and trust. We are also clearly looking for:
- review authenticity / fake review / helpfulness / verified purchase style signals
- information presentation / filtering / overload / summarization / comparison / explainability
- product-example evidence for complex products

### Finding 07
Phase D is collapsing one of the intended topic families before retrieval starts.

The raw planner response contains `4` subpoints, including:
- `Design factors that reduce uncertainty: information, comparability, explainability, quality signals`

But the final Phase D summary reports only `3` active subpoints, and the final `query_views.json` contains only:
- subpoint `1`
- subpoint `2`
- subpoint `3`

The design / information-presentation subpoint is not preserved as its own retrieval view.

Practical implication: a whole family of useful sections is being de-emphasized before Phase E even runs.

### Finding 08
The lexical grounding is too literal for the bilingual chapter wording.

In `phase_d_corpus_support.json`, many source-grounded terms have zero hits:
- `decision confidence`
- `Dual-Process-Ansätze`
- `ethische Leitplanken`
- `Informationsdarstellung`
- `Vergleichbarkeit`
- `Nutzerautonomie`
- `Heuristiken`

Practical implication: being source-grounded is good, but the current implementation still fails to convert many German conceptual anchors into robust English retrieval language for the actual corpus.

### Finding 09
Survey and review papers are systematically under-recalled.

This shows up strongly in:
- `Opinion Mining and Sentiment Analysis`
- `Natural Language Processing for Analyzing Online Customer Reviews...`
- `Sentiment Analysis in E-Commerce Platforms...`
- `Evolving techniques in sentiment analysis...`

Pattern:
- the documents contain useful sections
- the useful sections often sit under generic headings
- the internal text is semantically relevant but not lexically close to the current active query views

Practical implication: section-title-heavy recall is still too weak for survey/review literature.

### Finding 10
Phase G is currently too brittle for cross-topic documents.

Examples:
- `Online Reviews and Information Overload...` has `15` sections scored `>= 8`, yet `doc_match_probability = 0.0`
- `Beyond self-selection...` has `11` sections scored `>= 8`, yet `doc_match_probability = 0.0`
- `Fake online reviews...` has `5` sections scored `>= 8`, yet `doc_match_probability = 0.0`

Practical implication: the final document decision is over-indexing on top-section thresholds and not enough on the total amount of useful evidence inside the PDF.

### Finding 11
There are still a few real Phase C misses, but they are no longer the dominant failure mode.

Confirmed remaining structural misses from benchmark review:
- `Fake online reviews... :: 3.2.2 Effects on various stakeholders`
- `Fake online reviews... :: Figure 4. Influencing mechanisms of fake reviews`

Practical implication: Phase C still matters for a few edge sections, but fixing recall/calibration will produce larger gains now.

### Finding 12
Several of the most useful currently missed sections are exactly the kinds of sections the app should surface.

Examples:
- `Online Reviews and Information Overload... :: Information Overload in Online Platforms`
- `Online Reviews and Information Overload... :: Signal Efficiency and Parsimony`
- `Beyond self-selection... :: Platform biases in online reviews`
- `Beyond self-selection... :: Practical implications`
- `Opinion Mining and Sentiment Analysis :: Review(er) quality`
- `Opinion Mining and Sentiment Analysis :: Implications for manipulation`
- `Fake online reviews... :: 3.2.1 Effects on the development of online product reviews`
- `Whose online reviews to trust? :: 3. Hypotheses development`
- `Natural Language Processing for Analyzing Online Customer Reviews... :: Review analysis and management`

Practical implication: the current misses are not obscure edge cases. They are exactly the sections a human reviewer would want.
