# Phase B/C Paper-Dump Evaluation

## Verdict

Testing Phase B and Phase C on `paper-dump` was the right move.

The first corpus run exposed real Phase C weaknesses that the original 5-PDF benchmark did not expose. I then used those findings to harden Phase C and reran the corpus. The second run is materially better.

The main conclusion now is:
- Phase B is robust enough on this corpus.
- Phase C is substantially more robust than before.
- The remaining real follow-up cases are now concentrated in parser fallback and long-book behavior, not in ordinary paper normalization.

## Evaluation Runs

Baseline corpus run:
- `08ddb0af3f58296fbbc0889a`

Hardened corpus run:
- `b43598fa6c8514cfa183a51e`

Artifacts for the hardened run:
- `pdf-scan/runs/b43598fa6c8514cfa183a51e/phase_b_review/phase_b_review_summary.json`
- `pdf-scan/runs/b43598fa6c8514cfa183a51e/phase_c_review/phase_c_review_summary.json`
- `pdf-scan/runs/b43598fa6c8514cfa183a51e/phase_bc_review/phase_bc_review_summary.json`

Corpus:
- `22` PDFs
- page-count range: `4` to `598`

## What the First Corpus Run Exposed

The baseline corpus run surfaced three concrete Phase C defects:

1. Caption-like blocks could become retrieval-eligible sections.
- confirmed on `Beyond self-selection...`

2. Micro-taxonomy sections could survive as retrieval-eligible tiny sections.
- confirmed on `23 Ways to Nudge`
- examples: `Fear`, `Reinforce`

3. Publication metadata could leak into section and passage text.
- confirmed on `Evolving techniques in sentiment analysis...`

These were real problems, not cosmetic noise.

## Hardening Changes Applied

I used those findings to harden Phase C in `pdf-scan/phase_c_lab.py`.

Main changes:
- improved anchor scoring so numbering-insensitive heading-prefix matches beat caption blocks
- added caption penalties during anchor scoring
- added section-level caption-stub suppression as a safety net
- added micro-section suppression for short level-2+ body sections with very short titles
- added metadata stripping from section block text before section/passage construction
- added `metadata_stripped` diagnostics to sections and document summaries

I also synced the notebook bridge:
- `pdf-scan/pdf-scan-v3.ipynb`

## Before/After Summary

Baseline run:
- `645` sections
- `3641` passages
- `6` strong
- `12` acceptable with noise
- `4` need follow-up

Hardened run:
- `646` sections
- `3642` passages
- `7` strong
- `13` acceptable with noise
- `2` need follow-up

Interpretation:
- the total structure graph barely changed
- the quality of the difficult cases improved
- this is what we want: better section quality without destabilizing the corpus-wide output

## Phase B Findings

Phase B performed well on both corpus runs.

Stable strengths:
- `20/22` PDFs reached success-like Docling output
- `3` documents used chunked Docling recovery
- only `2/22` documents used parser fallback
- no success-like Docling document was headerless

The two fallback documents are still:
- `Consumers’ Decision-Making Process on Social Commerce Platforms...`
  - Docling failure
- `Judgment Under Uncertainty Heuristics and Biases`
  - skipped by the `400`-page policy limit

Phase B conclusion:
- good enough on this corpus
- the remaining parser limitation is still the long-book / invalid-Docling lane

## Phase C Findings After Hardening

### 1. Caption leak fixed

`Beyond self-selection...`

Before:
- fallback anchors: `4`
- retrieval-eligible tiny sections: `1`
- category: `needs_follow_up`

After:
- fallback anchors: `1`
- retrieval-eligible tiny sections: `0`
- category: `acceptable_with_noise`

Most important effect:
- `Central tendencies of online and offline ratings` now expands into the real subsection instead of a 16-word caption stub

### 2. Micro-taxonomy leak fixed

`23 Ways to Nudge`

Before:
- retrieval-eligible tiny sections: `2`
- category: `needs_follow_up`

After:
- retrieval-eligible tiny sections: `0`
- category: `acceptable_with_noise`

Important nuance:
- `Fear` and `Reinforce` still exist structurally
- they are now suppressed for retrieval instead of being removed
- that is the right behavior

### 3. Metadata stripping added

Corpus-wide:
- metadata-stripped sections in the hardened run: `96`

Examples:
- `Evolving techniques in sentiment analysis...`
- `Fake online reviews...`
- `Natural language processing for analyzing online customer reviews...`

This matters because it reduces the chance that later retrieval and reranking treat DOI/citation/editor boilerplate as evidence.

### 4. Long-book anchoring improved

`Judgment Under Uncertainty...`

Before:
- fallback anchors: `8`

After:
- fallback anchors: `3`

This is still the hardest document in the current test set, but the anchor behavior is materially better now.

## Document-by-Document Judgment After Hardening

Strong:
- `Evolving techniques in sentiment analysis a comprehensive review`
- `Fake online reviews Literature review, synthesis, and directions for future research`
- `Natural language processing for analyzing online customer reviews a survey, taxonomy, and open research challenges`
- `Opinion Mining and Sentiment Analysis`
- `Sentiment Analysis in E-Commerce Platforms A Review of Current Techniques and Future Directions`
- `Using Online Reviews for Customer Sentiment Analysis`
- `The effectiveness of nudging`

Acceptable with noise:
- `23 Ways to Nudge`
- `A review of nudges`
- `Beyond self-selection the multilayered online review biases at the intersection of users, platforms and culture`
- `Development of methodology for classification of user experience (UX) in online customer review`
- `Digital Nudging`
- `Digital Nudging Altering User Behavior in Digital Environments`
- `Digital nudging with recommender systems`
- `Improving decisions about health wealth and happiness`
- `Online Reviews and Information Overload The Role of Selective, Parsimonious, and Concordant Top Reviews`
- `Sentiment Analysis of Product Reviews Using Machine Learning and Pre-Trained LLM`
- `Shining a Light on Dark Patterns`
- `TO NUDGE, OR NOT TO NUDGE`
- `Whose online reviews to trust Understanding reviewer trustworthiness and its impact on business`

Needs follow-up:
- `Consumers’ Decision-Making Process on Social Commerce Platforms Online Trust, Perceived Risk, and Purchase Intentions`
  - Docling failure
  - fallback parser path only
- `Judgment Under Uncertainty Heuristics and Biases`
  - Docling skipped by page-limit policy
  - fallback parser path only
  - still uses `3` fallback anchors

## What This Tells Us About Overfitting

The original 5-PDF benchmark was not enough.

This corpus proved that the pipeline was not narrowly overfitted to one topic, but it also showed exactly where the weak spots were:
- caption-rich pages
- taxonomy-heavy short papers
- publication-metadata-heavy papers
- long-book fallback paths

The key result is that these weaknesses were detectable and fixable only because the paper-dump run existed.

So this was not just a good idea. It was necessary.

## What Improved Quantitatively

Category movement:
- `strong`: `6 -> 7`
- `acceptable_with_noise`: `12 -> 13`
- `needs_follow_up`: `4 -> 2`

Meaningful document-level improvements:
- `23 Ways to Nudge`
  - `needs_follow_up -> acceptable_with_noise`
- `Beyond self-selection...`
  - `needs_follow_up -> acceptable_with_noise`
- `The effectiveness of nudging`
  - `acceptable_with_noise -> strong`

Fallback-anchor improvements:
- `Beyond self-selection...`: `4 -> 1`
- `Judgment Under Uncertainty...`: `8 -> 3`
- `The effectiveness of nudging`: `1 -> 0`

One small regression worth noting:
- `Digital Nudging` picked up `1` fallback anchor in the hardened run where it previously had `0`

That regression is minor compared with the improvements, but it should stay on the watch list.

## Remaining Priorities

Priority 1:
- keep improving the long-book fallback lane
- especially the 400+ page outline-first path

Priority 2:
- keep an eye on short papers with very dense outlines
- these are mostly acceptable now, but still noisier than ideal

Priority 3:
- expand corpus testing again after later retrieval phases are improved
- the same pressure-testing pattern should continue

## Final Conclusion

The paper-dump evaluation did exactly what it needed to do.

It found problems the original benchmark missed.
Those problems were real.
They were then fixed or materially reduced.

The hardened result is better in the way that matters:
- fewer real follow-up failures
- cleaner section anchors
- no remaining retrieval-eligible tiny sections in the previously bad cases
- cleaner section and passage text
- no instability explosion in total section or passage counts

So yes, this corpus test was the correct move, and it made the pipeline more robust.
