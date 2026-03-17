# Section Usefulness Audit Report

Date: 2026-03-17
Run: `386e04657c41c805f8c1b974`
Primary corpus: `paper-dump` (`22` PDFs)
Benchmark: `benchmark/full_dump_webshop_manual_v1`

## Goal

Audit the current pipeline from the user perspective:

- Which extracted sections are actually useful for writing the target chapter?
- Which benchmark sections are truly useful when read directly?
- Why are useful sections still being missed?
- Which phase is now the real bottleneck?

This audit was done after the major Phase C hardening pass. The point was to verify whether the remaining failure is still structure extraction or whether the bottleneck has moved downstream.

## Method

### 1. Build a section inspection dataset

Using `build_section_inspection_dataset.py`, I created a merged inspection set that joins:

- all normalized sections from the run
- Phase E / F / G ranking signals
- benchmark targets and matching status
- direct PDF text excerpts for benchmark targets

Outputs:
- `runs/386e04657c41c805f8c1b974/section_inspection/all_sections.jsonl`
- `runs/386e04657c41c805f8c1b974/section_inspection/benchmark_targets.jsonl`
- `runs/386e04657c41c805f8c1b974/section_inspection/per_doc/`

### 2. Score every extracted section

Using `score_full_dump_sections.py`, I scored all `574` extracted sections on a `0-10` usefulness scale.

The scoring criterion was intentionally broad:
- not only “best lexical match”
- but “would this section make the chapter richer, more grounded, more diverse, or more scientifically useful?”

Each section received:
- `usefulness_0_to_10`
- `primary_category`
- `secondary_categories`
- a short rationale

Output:
- `runs/386e04657c41c805f8c1b974/section_inspection/section_scores_openai.jsonl`

### 3. Review all benchmark targets

Using `review_benchmark_targets.py`, I inspected all `33` benchmark targets and wrote:

- how useful they actually are
- why the current pipeline did not surface them
- which phase failed them
- which pipeline change would most likely help

Outputs:
- `runs/386e04657c41c805f8c1b974/section_inspection/benchmark_target_reviews.jsonl`
- `runs/386e04657c41c805f8c1b974/section_inspection/benchmark_target_reviews.md`

## Core Results

### 1. The pipeline is still much too strict

The current full-dump run returns only `9` useful PDFs.

The manual benchmark currently expects:
- `21` positive PDFs
- `1` negative PDF

So even after the recent D/E/F/G tuning, the app is still filtering too aggressively.

### 2. There is already a lot of useful content in the extraction output

Across `574` extracted sections:

- `217` sections scored `>= 7/10`
- `156` sections scored `>= 8/10`
- `81` sections scored `>= 9/10`

But only:
- `63` sections with score `>= 7` reached Phase G section scoring
- `45` sections with score `>= 8` reached Phase G section scoring
- `32` sections with score `>= 9` reached Phase G section scoring

Interpretation:
- the pipeline is not “finding too little useful content in the PDFs”
- it is “failing to keep enough useful content alive through the retrieval and final-decision stages”

### 3. Useful content is concentrated inside currently rejected PDFs

False-negative docs with the most high-value sections:

1. `Online Reviews and Information Overload...`
   - `20` sections scored `>= 7`
   - `15` sections scored `>= 8`
   - `7` sections scored `>= 9`
   - current `doc_match_probability = 0.0`

2. `Beyond self-selection...`
   - `15` sections scored `>= 7`
   - `11` sections scored `>= 8`
   - `4` sections scored `>= 9`
   - current `doc_match_probability = 0.0`

3. `Opinion Mining and Sentiment Analysis`
   - `17` sections scored `>= 7`
   - `9` sections scored `>= 8`
   - `3` sections scored `>= 9`
   - current `doc_match_probability = 0.3696`

4. `Fake online reviews...`
   - `10` sections scored `>= 7`
   - `5` sections scored `>= 8`
   - `2` sections scored `>= 9`
   - current `doc_match_probability = 0.0`

5. `Whose online reviews to trust?`
   - `6` sections scored `>= 7`
   - `2` sections scored `>= 8`
   - current `doc_match_probability = 0.0`

This is the clearest evidence that the current final behavior is too conservative to ship.

## Where The Pipeline Is Failing

### Phase C

Phase C is no longer the main bottleneck.

Only `2` benchmark targets were classified as structural misses:
- `Fake online reviews... :: 3.2.2 Effects on various stakeholders`
- `Fake online reviews... :: Figure 4. Influencing mechanisms of fake reviews`

That matters, but it is not the dominant failure mode anymore.

### Phase D

Phase D is still too narrow for the real task.

Important observation:
- the planner response originally contains `4` subpoints
- but the final Phase D summary keeps only `3`
- the dropped intent is:
  - `Design factors that reduce uncertainty: information, comparability, explainability, quality signals`

This matters because the missing PDFs are disproportionately rich in exactly those themes:
- review helpfulness
- fake review detection
- verified-purchase-like cues
- information overload
- review filtering
- summarization / aspect extraction
- comparison / explainability

Current active subpoints are effectively:
- decision psychology / heuristics
- digital nudging / ethics
- perceived risk / trust / complex products

What is not treated as a first-class retrieval target anymore:
- review quality / authenticity
- information presentation / filtering / comparison

That is a major source of recall loss.

Phase D also remains too literal in its lexical grounding. In `phase_d_corpus_support.json`, many chapter-derived terms still have zero support in the actual corpus, for example:
- `decision confidence`
- `Dual-Process-Ansätze`
- `ethische Leitplanken`
- `Informationsdarstellung`
- `Vergleichbarkeit`
- `Nutzerautonomie`
- `Heuristiken`

This shows the current grounding is still too close to the bilingual source phrasing and not yet robust enough for English scientific corpora.

### Phase E

Phase E is one of the two main bottlenecks.

Benchmark miss reasons show:
- `phase_e_retrieval_recall_gap`: `9`
- `phase_e_retrieval_miss`: `5`

The pattern is strongest for:
- survey papers
- review papers
- papers with generic headings but strong internal content
- sections framed around review quality, platform bias, or information presentation rather than the explicit words from the chapter spec

Typical examples:
- `Opinion Mining and Sentiment Analysis :: Review(er) quality`
- `Natural Language Processing for Analyzing Online Customer Reviews... :: Review analysis and management`
- `Fake online reviews... :: 3.3.3 Response strategies`
- `Using Online Reviews for Customer Sentiment Analysis :: INTRODUCTION`
- `Online Reviews and Information Overload... :: Signal Efficiency and Parsimony`

These sections are useful, but the current retrieval stack is not broad enough to keep them alive.

### Phase F

Phase F is a secondary issue, not the main one.

Benchmark miss reasons:
- `phase_f_rerank_downranked`: `2`
- `phase_f_rerank_miss`: `1`

That means reranking is not innocent, but it is not the main source of loss.

What it tends to do wrong:
- broad contextual introductions get downranked
- survey sections with generic titles get treated as low-precision
- useful “management / implications / customer experience” sections sometimes fail to survive against more obviously aligned nudging sections

### Phase G

Phase G is the other major bottleneck.

Benchmark miss reasons:
- `phase_g_threshold_or_doc_calibration`: `14`

This is the single largest miss bucket.

The current problem is not just “scores are low.”
It is that Phase G is still making a brittle binary PDF decision from too little evidence.

Examples:
- `Online Reviews and Information Overload...` contains many sections a human would clearly keep, but the doc still gets `0.0`
- `Beyond self-selection...` contains platform-bias and practical-implications sections that are obviously useful, but the doc still gets `0.0`
- `Whose online reviews to trust?` contains theory, reviewer-credibility cues, and managerial implications, but the doc still gets `0.0`

So the final decision layer is still much too harsh for cross-topic documents that are strongly useful but not “perfect” lexical matches.

## The User Hypothesis Was Correct

The task is not one thing. It is several things at once.

Among high-value sections in false-negative docs, the main categories are:
- `review_quality_authenticity`: `28`
- `information_presentation_filtering_comparison`: `19`
- `trust_risk_uncertainty`: `19`
- `nudging_choice_architecture`: `8`
- `decision_psychology_theory`: `6`

This is the key conceptual result of the audit.

The current pipeline still behaves as if the chapter were mostly:
- heuristics / biases
- nudging
- perceived risk / trust

But the actual useful literature for the chapter also heavily includes:
- quality signals in reviews
- fake/manipulated review problems
- helpfulness / authenticity / trustworthiness
- information overload and filtering
- comparison and aggregation design
- explainability / summarization / aspect-based presentation
- concrete product-example evidence for complex products

That is why the current pipeline can look “good” on some obvious nudging papers while still missing much of what a human chapter writer would actually want.

## Concrete Missed Sections That Should Have Surfaced

### `Online Reviews and Information Overload...`

Highly useful missed sections:
- `Information Overload in Online Platforms`
- `Information Signaling`
- `Top Reviews and Signal Concordance`
- `Signal Efficiency and Parsimony`
- `Signal Efficiency and Concordance`

Why they matter:
- they directly connect reviews, signal design, overload, uncertainty reduction, and decision confidence
- this is not marginal relevance; it is core chapter material

### `Beyond self-selection...`

Highly useful missed sections:
- `Platform biases in online reviews`
- `User biases in online reviews`
- `Main findings`
- `Practical implications`

Why they matter:
- they supply platform-level bias, review aggregation bias, transparency, design implications, and trust-relevant distortion mechanisms

### `Opinion Mining and Sentiment Analysis`

Highly useful missed sections:
- `The demand for information on opinions and sentiment`
- `Review(er) quality`
- `Implications for manipulation`
- `Economic impact of reviews`

Why they matter:
- they directly support trust, review helpfulness, manipulation, and how online opinions affect buying behavior

### `Fake online reviews...`

Highly useful missed sections:
- `3.2.1 Effects on the development of online product reviews`
- `3.2.2 Effects on various stakeholders`
- `3.3.3 Response strategies`
- `3.3.1 Features extraction`

Why they matter:
- they give direct material on uncertainty, distrust, review quality degradation, and intervention strategies

### `Whose online reviews to trust?`

Highly useful missed sections:
- `3. Hypotheses development`
- `2. Literature review`
- `6.2 Managerial implications`

Why they matter:
- they cover reviewer credibility cues, source credibility, trust in reviews, and how these affect adoption of recommendations

## What This Means For Optimization

The next optimization loop should not be “generic quality improvement.”
It should be a recall-and-calibration redesign.

Priority order:

1. **Phase D**
   - make review-quality/authenticity a first-class retrieval intent
   - make information-presentation/filtering/comparison a first-class retrieval intent
   - stop collapsing those into the broader perceived-risk bucket

2. **Phase E**
   - widen recall for review/survey papers and results/implications sections
   - rely less on title lexical overlap
   - retrieve more by internal semantic content and document-level evidence

3. **Phase G**
   - make the per-document usefulness decision much less brittle
   - aggregate more evidence from multiple strong sections
   - stop using top-section thresholds in a way that zeroes out obviously useful docs

4. **Phase F**
   - secondary tuning only after D/E/G are corrected

## Bottom Line

The current extraction layer is good enough to move on.

The main problem now is:
- the pipeline does not yet model the chapter as a multi-intent retrieval problem
- it under-recalls review-quality and information-design literature
- and it still rejects too many partially but genuinely useful PDFs at the final calibration stage

That is why the pipeline currently feels too strict.

The audit strongly supports building the next benchmark around:
- document usefulness
- section usefulness
- category labels
- miss reasons by phase

Not just “did it find the one best section?”
