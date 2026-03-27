# Phase C Ground-Truth Audit

## Scope

This report is the direct trust check for Phase C.

The earlier Phase C report validated normalization quality through pipeline diagnostics and corpus-level reviewer summaries. This audit adds a second layer: direct inspection of the PDFs themselves and comparison against an independently extracted heading set.

The goal was not to prove that every visually prominent line in a PDF is a valid section. The goal was to answer a practical question:

- can we trust Phase C to produce usable sections and passages for later retrieval over the current `paper-dump` corpus?

## Artifacts

Implementation and review helpers:

- `pdf-scan/phase_c_truth_lab.py`
- `pdf-scan/review_phase_c_truth.py`

Main audited run:

- Phase C normalized run: `b43598fa6c8514cfa183a51e`
- Truth-lab summary: `pdf-scan/runs/b43598fa6c8514cfa183a51e/phase_c_truth/aggregate_summary.json`
- Truth-lab rows: `pdf-scan/runs/b43598fa6c8514cfa183a51e/phase_c_truth/aggregate_rows.json`

Per-document inspection artifacts:

- `phase_c_truth/<doc_id>/document_summary.json`
- `phase_c_truth/<doc_id>/evaluation.json`
- `phase_c_truth/<doc_id>/truth_headings.json`
- `phase_c_truth/<doc_id>/page_texts.jsonl`
- `phase_c_truth/<doc_id>/pages/page_XXXX.html`
- `phase_c_truth/<doc_id>/index.html`

The HTML files were created so the PDF pages can be inspected locally without relying only on tables or extracted JSON.

## Method

For each PDF in `paper-dump`, the truth lab does four things:

1. read the PDF directly with PyMuPDF and save raw page text
2. extract the outline/TOC if present
3. extract visual heading candidates from the rendered text blocks
4. compare the resulting independent heading set against Phase C sections and passages from the normalized run

Important constraint:

- this is intentionally independent from the Phase C section-builder, but it is still heuristic
- therefore a low score can mean either:
  - Phase C is wrong
  - the independent evaluator mistook title-page or metadata lines for headings

Because of that, I manually inspected all seven `needs_follow_up` documents after the automatic pass.

## Aggregate Result

Automatic truth-lab result across all `22` PDFs:

- `11` strong
- `4` acceptable_with_noise
- `7` needs_follow_up
- mean match ratio: `0.7928`
- median match ratio: `0.9606`

That raw result looks harsher than the real state of Phase C.

After direct manual inspection of the seven flagged documents, the split is:

- `4` real Phase C failures
- `2` mostly evaluator noise
- `1` evaluator noise

So the true situation is better than the automatic headline suggests.

## What I Inspected

I checked the flagged cases against:

- Phase C section titles and page spans
- the independently extracted truth headings
- raw page text from the PDF
- selected HTML page dumps for local visual inspection

Representative direct findings:

- `The effectiveness of nudging`
  - the truth extractor over-counted the paper title, author block, and `Significance` box on page 1 as section headings
  - Phase C sections such as `Results`, `Discussion`, `Conclusion`, and `Materials and Methods` are real
  - verdict: evaluator noise, not a meaningful Phase C failure

- `Evolving techniques in sentiment analysis...`
  - most missing truth rows are page-1 metadata, affiliations, `OPEN ACCESS`, or split title lines
  - Phase C still contains one real bad heading: `The hybrid CNN and BiLSTMs were enhanced with an`
  - verdict: mostly evaluator noise, but not perfectly clean

- `Online Reviews and Information Overload...`
  - most missing truth rows are title-page content, author names, or article-frontmatter
  - the main real noise is limited to some appendix/table handling and a split title token in `Alternative Measure of Signal Reaffirmatio n`
  - verdict: mostly evaluator noise

- `TO NUDGE, OR NOT TO NUDGE`
  - real Phase C failure
  - Docling promoted pull quotes and adjacent article content into section titles:
    - `' ' little evidence to suggest that nudges are an alternative`
    - `' ' influencing choices at the margin`
    - `THE PERSISTENCE OF HEALTH INEQUALITIES IN MODERN WELFARE STATES: THE ROLE OF HEALTH BEHAVIOURS`
  - this is not evaluator noise; it is a layout-handling problem

- `Using Online Reviews for Customer Sentiment Analysis`
  - real Phase C failure
  - headings are truncated and partially split:
    - `HOW ONLINE REVIEWS CAN BE`
    - `SENTIMENT ANALYSIS ON ONLINE REVIEWS`
    - `Using Online Reviews for`
  - the document is usable, but the sectioning is not clean enough

- `Whose online reviews to trust?`
  - real Phase C failure
  - middle major sections are missing:
    - `2. Literature review`
    - `3. Hypotheses development`
    - `4. Data`
  - later sections are recovered correctly, which means this is not a global parser collapse but a partial structural miss

- `Fake online reviews`
  - real Phase C failure
  - one bad heading is still promoted from body text:
    - `produced by the other 19 countries or regions.`
  - several real subsections are still skipped

## Practical Verdict

Phase C is good enough to continue the pipeline, but not good enough to treat as fully solved.

What I trust now:

- ordinary scholarly papers with conventional section structure
- large outline-rich documents like the 598-page book, with some known fallback debt
- most retrieval-eligibility suppression decisions
- passage generation for the majority of the corpus

What I do not trust yet:

- magazine-like or multi-article layouts
- some accepted-manuscript PDFs with heavy frontmatter
- long all-caps or split headings that are broken across blocks
- cases where body pull quotes visually resemble headings

## Why This Matters For Retrieval

This audit changes how to interpret later retrieval failures.

If Phase D or Phase E misses something on these four documents:

- `to_nudge_or_not_to_nudge-16624afd839e`
- `using_online_reviews_for_customer_sentiment_anal-ba995f136320`
- `whose_online_reviews_to_trust_understanding_revi-22354b2e8251`
- `fake_online_reviews_literature_review_synthesis_-e9bbe09bb4bf`

then the first suspect should be Phase C structure quality, not the retrieval logic.

On the other hand, if a later phase fails on:

- `the_effectiveness_of_nudging-76e15b34d02c`
- `evolving_techniques_in_sentiment_analysis_a_comp-68fe188f165a`
- `online_reviews_and_information_overload_the_role-42fa5aa25910`

then the raw truth-lab score alone should not be treated as evidence that Phase C is broken.

## Conclusion

Phase C holds up better under direct PDF inspection than the raw truth-lab headline suggests.

The audit result is:

- the corpus is not overfit to the original 5-PDF benchmark
- most of the `paper-dump` corpus is already in a trustworthy state
- there are still four concrete layout classes where Phase C needs more hardening

So the correct conclusion is not “Phase C is perfect.”

The correct conclusion is:

- Phase C is strong enough for continued pipeline development
- later retrieval benchmarking should explicitly track the four confirmed structural-failure documents
- a future Phase C hardening pass should focus on layout-specific errors, not broad generic retuning

## Post-Hardening Addendum

I ran one more targeted hardening pass after this audit and revalidated it on both the focused failure set and the full `paper-dump` corpus.

Final validation runs:

- focused 4-document regression: `d014a688dc69acd48e02d075`
- final 22-document rerun: `d686ff76f34ce147287aa134`
- final truth audit: `d686ff76f34ce147287aa134/phase_c_truth`

Headline movement from the earlier full-corpus truth audit baseline `b43598fa6c8514cfa183a51e`:

- `strong`: `11 -> 12`
- `acceptable_with_noise`: `4 -> 4`
- `needs_follow_up`: `7 -> 6`
- mean match ratio: `0.7928 -> 0.8283`
- median match ratio: `0.9606 -> 1.0`

What the final hardening pass actually fixed:

- `fake_online_reviews_literature_review_synthesis_-e9bbe09bb4bf`
  - moved from `needs_follow_up` to `strong`
  - the page-20 dataset rows no longer become headings
  - recovered subsections now line up with the PDF and the truth audit matches `29/29`
- `whose_online_reviews_to_trust_understanding_revi-22354b2e8251`
  - moved from `needs_follow_up` to `acceptable_with_noise`
  - the formerly missing middle sections are now recovered
- `using_online_reviews_for_customer_sentiment_anal-ba995f136320`
  - still flagged, but the core truncation problem is materially better
  - repaired headings now include:
    - `HOW ONLINE REVIEWS CAN BE USED FOR OPINION MINING`
    - `Using Online Reviews for Enthusiasm Analysis`
- `a_review_of_nudges-8a314b3ef5a0`
  - letter-spaced headings such as `N O T E S` and `R E F E R E N C E S` now anchor correctly
  - the remaining misses are mostly truth-extractor numbering fragments, not missing real sections

What remains low-scoring after the final pass:

- `to_nudge_or_not_to_nudge-16624afd839e`
- `using_online_reviews_for_customer_sentiment_anal-ba995f136320`
- `evolving_techniques_in_sentiment_analysis_a_comp-68fe188f165a`
- `online_reviews_and_information_overload_the_role-42fa5aa25910`
- `the_effectiveness_of_nudging-76e15b34d02c`
- `a_review_of_nudges-8a314b3ef5a0`

How to interpret those remaining low scores:

- `to_nudge_or_not_to_nudge-16624afd839e`
  - still a real layout challenge because the source PDF is magazine-like and visually messy
- `using_online_reviews_for_customer_sentiment_anal-ba995f136320`
  - still a real, but narrowed, split-heading case
- `evolving_techniques_in_sentiment_analysis_a_comp-68fe188f165a`
  - still largely evaluator noise from title-page and affiliation lines
- `online_reviews_and_information_overload_the_role-42fa5aa25910`
  - still largely evaluator noise from title/frontmatter handling
- `the_effectiveness_of_nudging-76e15b34d02c`
  - still dominated by evaluator frontmatter/title-box artifacts
- `a_review_of_nudges-8a314b3ef5a0`
  - now mostly numbering-only truth-heading mismatches rather than real missing sections

Final audit conclusion after hardening:

- the original four confirmed structural-failure documents are no longer all in the “real failure” bucket
- the strongest genuine improvement is on `fake_online_reviews...`, which is now clean enough to trust
- the remaining weak scores are not enough to justify another broad Phase C retune
- Phase C should now be treated as frozen and Phase E should be evaluated against it
