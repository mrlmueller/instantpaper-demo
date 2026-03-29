# End-to-End False-Negative Audit

Date: 2026-03-16

## Scope

This audit targeted the full A-G pipeline after the final Phase C structural hardening pass.

The main goal was not structural extraction anymore. It was false-negative reduction:

- rerun the full pipeline on the full `paper-dump` corpus of 22 PDFs
- inspect the PDFs that still came back as `has_useful_information = false`
- trace those failures back through Phase D, E, F, and G
- patch the downstream stages without overfitting to the 5-document benchmark

## Runs

### Full dump

- initial end-to-end full dump run: `386e04657c41c805f8c1b974`
- all downstream tuning iterations were rerun on the same run id by force-rebuilding later phases

Final full-dump artifacts:

- run root: `pdf-scan/runs/386e04657c41c805f8c1b974`
- final decisions: `pdf-scan/runs/386e04657c41c805f8c1b974/final/output.json`
- per-document features: `pdf-scan/runs/386e04657c41c805f8c1b974/final/doc_features.jsonl`
- per-PDF review pages: `pdf-scan/runs/386e04657c41c805f8c1b974/pdf_reports/`

### Benchmark smoke/regression

- benchmark end-to-end rerun: `1b851b3297d936aa4f9ac087`

Benchmark artifacts:

- run root: `pdf-scan/runs/1b851b3297d936aa4f9ac087`
- final decisions: `pdf-scan/runs/1b851b3297d936aa4f9ac087/final/output.json`

## What Was Wrong Initially

The first full-dump end-to-end run was too conservative.

Observed failure pattern:

- only `2/22` PDFs were marked useful
- clearly useful theory / nudging PDFs were landing just below threshold
- some trust / review papers were being retrieved, but their scores stayed too low to survive Phase G
- some semantically useful documents were not getting any LLM-judge attention because the judge budget was spent almost entirely on already-high-ranking candidates

The main downstream failure classes were:

1. Phase D query planning was still too narrow in places.
2. Phase F was too harsh on candidates with zero linked evidence passages even when the section text itself was strong.
3. Phase G provisional rules were rejecting strong partial matches that were clearly useful in practice.

## What Changed

Files changed:

- `pdf-scan/phase_d_lab.py`
- `pdf-scan/phase_f_lab.py`
- `pdf-scan/phase_g_lab.py`

### Phase D

Changes:

- added English retrieval aliases for key German chapter terms
- demoted low-support must-term examples such as `Consumer Electronics` out of the must-term set
- created `retrieval_should_terms` so retrieval can use semantically useful English concepts even when the original German source phrase has zero lexical hits
- broadened preferred section-type normalization so the planner cannot over-narrow subpoints to an implausibly small set of section types

Why this mattered:

- the old plan carried too many zero-hit German phrases straight into retrieval
- that diluted semantic queries and made some relevant sections look less relevant than they really were

### Phase F

Changes:

- added fallback evidence extraction from the section's own passages when no lane-linked supporting passage existed
- diversified the LLM-judge selection across documents instead of concentrating the budget only on the already-strongest candidates

Why this mattered:

- long relevant sections were being punished simply because no passage lane attached explicit evidence rows
- review/trust documents were not even being judged, so they had no chance to be rescued as semantically useful

### Phase G

Changes:

- added an explicit `strong_partial_case` rule for documents with:
  - a high partial top section
  - good top-3 consistency
  - substantial subpoint coverage
  - strong evidence support

Why this mattered:

- the old provisional rules only recognized “fully clear wins”
- they were too brittle for useful-but-not-perfectly-thresholded documents

## Final Full-Dump Result

Final full-dump state for run `386e04657c41c805f8c1b974`:

- useful PDFs: `5`
- no-match PDFs: `17`

The final useful set is:

- `Consumers' Decision-Making Process on Social Commerce Platforms`
- `Digital nudging with recommender systems`
- `The effectiveness of nudging`
- `Judgment Under Uncertainty: Heuristics and Biases`
- `Digital Nudging: Altering User Behavior in Digital Environments`

Near-threshold but still rejected:

- `Digital Nudging`
- `A review of nudges`

Still under-retrieved / under-ranked:

- `Whose online reviews to trust?`
- `Online Reviews and Information Overload`
- `23 Ways to Nudge`

## Practical Improvement Over The First Full-Dump Run

The first full-dump run had only `2` useful PDFs.

After the downstream hardening pass:

- final useful PDFs increased to `5`
- `Judgment Under Uncertainty...` moved from rejected to accepted
- `The effectiveness of nudging` moved from rejected to accepted
- `Digital Nudging: Altering User Behavior in Digital Environments` moved from rejected to accepted

This was not just threshold lowering. The retrieval-side evidence got better too:

- query planning became less poisoned by unsupported German phrases
- candidate packs gained fallback evidence instead of empty evidence rows
- the LLM judge covered more documents instead of only the already-easy ones

## Benchmark Result

Benchmark run `1b851b3297d936aa4f9ac087` remained stable:

- useful PDFs: `2`
- no-match PDFs: `3`

The useful benchmark PDFs are:

- `Judgment Under Uncertainty: Heuristics and Biases`
- `Consumers' Decision-Making Process on Social Commerce Platforms`

This means the full-dump tuning did not break the original benchmark behavior.

## What I Verified Directly

I did not stop at summary metrics.

I directly inspected:

- the full-dump `query_plan.json`
- per-PDF `phase_e_retrieval.json`
- per-PDF `phase_f_rerank.json`
- per-PDF `phase_g_final.json`
- candidate texts and evidence snippets for the strongest false negatives

The important direct observations were:

- `Online Reviews and Information Overload` is still a real downstream miss; the section `Information Overload in Online Platforms` is useful, but the reranker still undervalues it
- `Whose online reviews to trust?` is still semantically useful, and the LLM judge recognizes that, but the full ranking stack still leaves it too low
- `Judgment Under Uncertainty...` is now correctly treated as useful
- `The effectiveness of nudging` is now correctly treated as useful

## Current Interpretation

The pipeline is now materially better end to end than it was at the start of this audit.

It is no longer mainly blocked by structural extraction. The main residual gap is now retrieval/rerank recall for semantically useful trust/review papers that are not close lexical matches to the chapter framing.

In other words:

- the main false negatives are now downstream semantic misses
- not the old Phase C heading/structure failures

## Recommendation

Freeze Phase C.

For the next iteration, focus only on the remaining review/trust false negatives:

- `Whose online reviews to trust?`
- `Online Reviews and Information Overload`
- `23 Ways to Nudge`

That next pass should focus on:

1. richer retrieval aliases for uncertainty-reduction / review-signal language
2. stronger judge-aware rescue of semantically useful review/trust papers
3. possibly one dedicated retrieval view for uncertainty-reduction mechanisms and quality signals

At this point, further broad structural work would be lower value than targeted downstream recall work.
