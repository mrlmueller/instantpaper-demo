# Phase C Report

## Scope

Phase C takes the Phase B parser bundles and turns them into one canonical normalized view per PDF.

Input contract:
- parser bundles from Phase B
- digital-PDF text blocks only
- outline, Docling, and optional GROBID structure signals
- deterministic normalization options

Output contract:
- one canonical `documents.jsonl`
- one canonical `sections.jsonl`
- one canonical `passages.jsonl`
- per-document diagnostics under `normalized/<doc_id>/`
- enough metadata for later retrieval to distinguish useful sections from structural noise

The key requirement for this phase is not only “split the PDF into sections”. It is “split the PDF into sections in a way that later ranking can trust, while preserving enough structure to explain where the information came from”.

## What I Researched

I rechecked the normalization assumptions against the parser documentation and the installed runtime:

- Docling quickstart and advanced options:
  - https://docling-project.github.io/docling/getting_started/quickstart/
  - https://docling-project.github.io/docling/usage/advanced_options/
- GROBID service docs:
  - https://grobid.readthedocs.io/en/latest/Grobid-service/
- PyMuPDF text extraction docs:
  - https://pymupdf.readthedocs.io/en/latest/recipes-text.html

The important practical conclusions for Phase C came from the run loop itself:

- outline and Docling headings often describe the same section with slightly different numbering, so exact-title dedupe is not enough
- parser output can contain useful hierarchy and useless retrieval targets at the same time
- block-level text still contains publication boilerplate, captions, and page furniture, so later phases need the normalized view to clean that before retrieval
- preserving wrapper sections is valuable for explainability, but treating them as normal retrieval units is a mistake

## Iteration History

### Iteration 1

Run:
- `36f15a3ae3ddc5d16000f6ef`

Baseline result:
- `275` sections
- `2217` passages
- severe duplicate inflation on mixed outline/Docling papers
- document-title repeats survived

Main defects:
- exact dedupe missed numbering variants
- some page-1 and page-2 lines survived as headings
- diagnostics were too thin to judge what was real structure and what was wrapper noise

### Iteration 2

Changes:
- reused top-level Docling `section_headers` when available
- added numbering-insensitive same-anchor dedupe
- strengthened page-1/page-2 document-title rejection
- expanded diagnostics with source counts, tiny-section counts, and deep-section counts

Observed result:
- sections dropped from `275` to `214`
- passages dropped from `2217` to `2156`
- `Opinion Mining and Sentiment Analysis` dropped from `159` sections to `99`

### Iteration 3

Changes:
- enriched `documents.jsonl` with normalization metadata
- added `retrieval_eligible` and `retrieval_suppression_reasons`
- added explicit structural-wrapper suppression while preserving hierarchy

Observed result:
- section count stayed `214`
- retrieval-suppressed sections became explicit instead of implicit

### Iteration 4

Changes:
- fixed the tiny-section QC logic so real `0` values were not treated as missing

Observed result:
- `0` retrieval-eligible tiny sections on the original 5-PDF set
- only one remaining warning: the 598-page book still used `8` fallback anchors

### Iteration 5: Paper-Dump-Driven Hardening

Corpus pressure test:
- baseline paper-dump run: `08ddb0af3f58296fbbc0889a`

The 22-PDF `paper-dump` corpus exposed three real weaknesses:
- caption-like blocks could still win anchor selection
- micro-taxonomy sections like `Fear` and `Reinforce` could survive as retrieval-eligible tiny sections
- publication metadata could still leak into section text and passages

Hardening changes:
- improved anchor scoring so numbering-insensitive heading-prefix matches beat caption blocks
- added caption penalties during anchor scoring
- added section-level suppression for caption-like stubs as a second safety net
- added micro-section suppression for short level-2+ body sections with very short titles
- added metadata stripping from section block text before section and passage construction
- surfaced `metadata_stripped` as a section/document diagnostic signal

Spotcheck validation:
- `23 Ways to Nudge`
  - `Fear` and `Reinforce` now remain in the structure but are no longer retrieval-eligible
- `Beyond self-selection...`
  - `Central tendencies of online and offline ratings` now expands into the full subsection instead of a 16-word caption stub
- `Evolving techniques in sentiment analysis...`
  - introduction metadata is stripped much more aggressively before passage construction

## Final Implementation Changes

Files:
- `pdf-scan/phase_c_lab.py`
- `pdf-scan/review_phase_c.py`
- `pdf-scan/review_phase_bc.py`
- `pdf-scan/pdf-scan-v3.ipynb`

Key changes:

1. Canonical heading dedupe is materially stronger.
- same-anchor headings are deduped both by exact normalized form and by numbering-insensitive normalized form

2. Anchor scoring is now caption-aware.
- heading-prefix variants are extracted from blocks before scoring
- numbering-insensitive matching is used during anchor scoring
- caption-like and metadata-like blocks are penalized during anchor selection

3. Phase C now separates structure preservation from retrieval eligibility.
- sections keep hierarchy, title path, and provenance
- sections and passages expose `retrieval_eligible`
- wrapper sections, caption-like stubs, and micro-sections are preserved structurally but suppressed for retrieval

4. Content text is cleaner before retrieval.
- metadata lines are stripped from section block text before section text and passage text are created
- section diagnostics now expose when metadata was stripped

5. `documents.jsonl` is now a useful normalization summary on its own.
- it includes strategy, heading-source mix, section coverage, fallback-anchor count, tiny-section count, retrieval-suppressed section count, structural-wrapper count, metadata-stripped section count, and normalization notes

6. The notebook and the executable lab now stay aligned.
- `pdf-scan-v3.ipynb` Phase C is a bridge into `phase_c_lab.py`
- the notebook options now show the new metadata-filter and micro-section settings explicitly

## Final Validation

Primary benchmark validation run:
- `8d6cb9bf6d443a812ed72e84`

Primary review artifact:
- `pdf-scan/runs/8d6cb9bf6d443a812ed72e84/phase_c_review/phase_c_review_summary.json`

Phase result:
- status: `success_with_warnings`
- quality band: `acceptable_with_issues`
- can continue: `true`

Benchmark totals:
- documents: `5`
- sections: `214`
- passages: `2156`
- orphan passages: `0`
- retrieval-suppressed passages: `65`
- retrieval-eligible tiny sections: `0`
- metadata-stripped sections: `22`

Benchmark improvement over the previous stabilized run:
- section count: unchanged at `214`
- passage count: unchanged at `2156`
- fallback anchors on `Judgment Under Uncertainty...`: `8 -> 3`

Per-document summary:

- `Consumers’ Decision-Making...`
  - `9` sections
  - `1` retrieval-suppressed wrapper section
  - `4` metadata-stripped sections
  - `99.85%` coverage

- `Judgment Under Uncertainty...` (`598` pages)
  - `53` sections
  - `16` retrieval-suppressed structural sections
  - `8` metadata-stripped sections
  - `3` fallback anchors
  - `100.0%` coverage

- `Whose online reviews to trust...`
  - `7` sections
  - `2` retrieval-suppressed structural sections
  - `6` metadata-stripped sections
  - `99.97%` coverage

- `Online Reviews and Information Overload...`
  - `46` sections
  - `15` retrieval-suppressed structural sections
  - `2` metadata-stripped sections
  - `99.99%` coverage

- `Opinion Mining and Sentiment Analysis`
  - `99` sections
  - `13` retrieval-suppressed structural sections
  - `2` metadata-stripped sections
  - `99.92%` coverage

## Corpus Validation

Paper-dump hardened validation run:
- `b43598fa6c8514cfa183a51e`

Artifacts:
- `pdf-scan/runs/b43598fa6c8514cfa183a51e/phase_c_review/phase_c_review_summary.json`
- `pdf-scan/runs/b43598fa6c8514cfa183a51e/phase_bc_review/phase_bc_review_summary.json`

Paper-dump totals:
- `22` documents
- `646` sections
- `3642` passages
- `161` retrieval-suppressed passages
- `96` metadata-stripped sections

Category movement after hardening:
- `strong`: `6 -> 7`
- `acceptable_with_noise`: `12 -> 13`
- `needs_follow_up`: `4 -> 2`

The two most important improvements:
- `23 Ways to Nudge`
  - retrieval-eligible tiny sections: `2 -> 0`
  - category: `needs_follow_up -> acceptable_with_noise`
- `Beyond self-selection...`
  - fallback anchors: `4 -> 1`
  - retrieval-eligible tiny sections: `1 -> 0`
  - category: `needs_follow_up -> acceptable_with_noise`

Additional improvement:
- `The effectiveness of nudging`
  - fallback anchors: `1 -> 0`
  - category: `acceptable_with_noise -> strong`

## Why These Changes Matter For Later Phases

- Phase D gets cleaner section types and section paths.
- Phase E gets fewer false-positive candidates from captions, micro-taxonomy stubs, and metadata-heavy text.
- The later “why this section is relevant” explanation becomes stronger because provenance and suppression reasons are explicit.
- Per-document abstention becomes easier because the normalized doc record already exposes whether a document mainly contains real content or mainly wrapper/back-matter structure.

This is the phase where the pipeline stops being “parser output” and becomes “retrieval-ready structure”.

## Remaining Limits

- The 598-page book still uses `3` fallback anchors.
  - much better than `8`, but still the main remaining benchmark warning
- A later independent truth-lab audit on the full `paper-dump` corpus found that the automated evaluator is harsher than the actual Phase C quality on some title-heavy papers.
  - see `160_phase_c_ground_truth_report.md` for the direct PDF inspection, HTML/page dumps, and the split between real Phase C failures and evaluator noise
- The most important confirmed Phase C issues after that audit are:
  - multi-article or magazine-like layouts that promote pull quotes as headings
  - truncated all-caps headings where a long heading is split across blocks
  - accepted-manuscript layouts where middle sections are skipped despite later sections being recovered

- Long books above the Docling policy limit still rely on fallback parsing.
  - that is fundamentally a Phase B plus Phase C combined limitation, not only a Phase C issue

- Structural suppression is still heuristic.
  - it is substantially better now
  - but it remains a policy layer, not a guaranteed semantic classifier

- Some short papers still have high section density.
  - this is acceptable when the extra units are suppressed wrappers
  - but it is still a signal to watch in future corpus tests

## Tunable Knobs Worth Reconsidering Later

- `repeated_heading_page_threshold`
  - current default: `3`
- `min_section_chars` and `min_section_words`
  - current defaults: `120` chars and `20` words
- `metadata_filter_enabled`
  - current default: `True`
- `micro_section_max_words`
  - current default: `20`
- `micro_section_max_title_words`
  - current default: `3`
- passage chunk sizes
  - current defaults: target `180`, max `260`

## Conclusion

Phase C is now good enough to move on.

It is still not perfect on the 598-page book, but it is doing the right engineering job:
- canonical section normalization across parser sources
- strong duplicate and title-repeat cleanup
- caption-aware anchor selection
- explicit suppression of wrapper sections and micro-sections as retrieval targets
- cleaner section and passage text through metadata stripping
- fully reviewable per-document diagnostics
- one validated implementation shared by the lab script and `pdf-scan-v3.ipynb`

## Final Targeted Correction Pass

I performed one final targeted Phase C hardening pass after the direct PDF inspection identified the last concrete failure classes.

Code changes in that final pass:

- added heuristic recovery for missed structural headings when the raw PDF blocks clearly contain them
- repaired truncated titles from the anchor block text before proposal filtering
- rejected sentence-like body lines promoted as headings
- tightened numeric heading detection so dataset rows such as `800 positive reviews ...` are no longer treated as numbered headings
- rejected table-like recovery rows containing checkmark-style table symbols
- normalized letter-spaced all-caps headings such as `N O T E S` and `R E F E R E N C E S` so they anchor to the correct block instead of colliding at page-start fallback

Validation runs:

- focused 4-document regression:
  - run `d014a688dc69acd48e02d075`
  - `4` docs, `60` sections, `225` passages
- final full `paper-dump` rerun:
  - run `d686ff76f34ce147287aa134`
  - `22` docs, `696` sections, `3673` passages
- final independent truth audit:
  - run `d686ff76f34ce147287aa134`
  - results stored under `phase_c_truth/`

Final corpus-level truth-audit movement versus the previous audited `paper-dump` baseline `b43598fa6c8514cfa183a51e`:

- `strong`: `11 -> 12`
- `acceptable_with_noise`: `4 -> 4`
- `needs_follow_up`: `7 -> 6`
- mean match ratio: `0.7928 -> 0.8283`
- median match ratio: `0.9606 -> 1.0`

Most important per-document changes from the final pass:

- `fake_online_reviews_literature_review_synthesis_-e9bbe09bb4bf`
  - truth-audit category: `needs_follow_up -> strong`
  - match ratio: `0.5862 -> 1.0`
  - missing truth headings: `12 -> 0`
  - the three false table-row headings on page 20 are gone
- `whose_online_reviews_to_trust_understanding_revi-22354b2e8251`
  - truth-audit category: `needs_follow_up -> acceptable_with_noise`
  - match ratio: `0.4167 -> 0.75`
  - missing truth headings: `7 -> 3`
  - recovered middle structural sections include `2. Literature review`, `3. Hypotheses development`, and `4. Data`
- `using_online_reviews_for_customer_sentiment_anal-ba995f136320`
  - match ratio: `0.4545 -> 0.5455`
  - repaired truncated titles such as `HOW ONLINE REVIEWS CAN BE USED FOR OPINION MINING`
- `a_review_of_nudges-8a314b3ef5a0`
  - letter-spaced end-matter headings now anchor correctly:
    - `NOTES`
    - `REFERENCES`
  - the remaining truth-audit misses are mainly evaluator numbering-only headings such as `1.1`, `2.3`, `2.4`, `3.1`, `6.3`, `7.1`

Final recommendation:

- freeze Phase C here
- move to Phase E with the current implementation
- keep the remaining truth-audit low-score documents as explicit watchlist documents during retrieval evaluation:
  - `to_nudge_or_not_to_nudge-16624afd839e`
  - `using_online_reviews_for_customer_sentiment_anal-ba995f136320`
  - `evolving_techniques_in_sentiment_analysis_a_comp-68fe188f165a`
  - `online_reviews_and_information_overload_the_role-42fa5aa25910`
  - `the_effectiveness_of_nudging-76e15b34d02c`

Why I am freezing it now:

- the known real structural miss in `fake_online_reviews` is fixed
- the known real structural miss in `whose_online_reviews...` is materially reduced
- the remaining worst truth-audit cases are dominated by frontmatter/title-page evaluator noise or numbering-only matching artifacts
- further generic Phase C tuning now has a higher risk of overfitting than likely payoff
