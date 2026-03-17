# Phase C Full-Dump Structural Audit

Date: 2026-03-16

## Scope

This audit took the final targeted Phase C hardening pass and validated it on:

- the original 5-document benchmark
- the full 22-document `paper-dump` corpus

The goal was to verify that the structural fixes were not overfit to the benchmark and that the remaining problems were understood from direct PDF inspection, not only from derived metrics.

## What Changed In Code

Files:

- `pdf-scan/phase_c_lab.py`
- `pdf-scan/phase_c_truth_lab.py`
- `pdf-scan/pipeline_deep_audit_lab.py`

Main changes:

- strong-outline documents suppress heuristic recovery aggressively
- `docling` supplements under strong outlines are restricted so clean outlines stay dominant
- probable multi-column pages use more geometry-aware block ordering
- no-outline noisy documents can use a stricter numbered gap-fill lane
- numbered gap-fill rejects institution lines, dates, journal/footer lines, and sentence-like numbered fragments
- if `docling` proposals exist, heuristic recovery is disabled
- title-prefix fragment rejection blocks running-header style fragments
- explicit structural headings such as `REFERENCES` can still be recovered when safe
- the independent truth audit now filters much more evaluator noise
- the deep-audit helper exports per-document page HTML and inspection notes from the actual PDFs

## Runs

Benchmark structural reruns:

- `099907eb964488daafed7d09`
- `5fbb21123a6107b4a5e2a47d`
- final benchmark run: `622f7eac8717d770dbf30a16`

Full paper-dump reruns:

- first full dump pass: `39683e7ba87b847aac55ef93`
- second full dump pass: `1fcfa3d4a7779aba286c83c5`
- third full dump pass: `ff93ad2066537a04aec219e7`
- final full dump run: `680f39e03a83984211db7a8d`

Truth-audit outputs:

- `runs/622f7eac8717d770dbf30a16/phase_c_truth_structural_hardening_benchmark_final`
- `runs/680f39e03a83984211db7a8d/phase_c_truth_structural_hardening_dump_4`

Deep inspection outputs:

- `runs/622f7eac8717d770dbf30a16/pipeline_deep_audit_benchmark_final`
- `runs/680f39e03a83984211db7a8d/pipeline_deep_audit_dump_4`

## Final Benchmark Result

Run `622f7eac8717d770dbf30a16`:

- `strong`: 3
- `acceptable_with_noise`: 2
- `needs_follow_up`: 0
- `needs_manual_review`: 0
- mean match ratio: `0.9415`
- median match ratio: `0.9434`

This means the dump-driven hardening did not regress the original benchmark.

The strongest benchmark win remains the long uncertainty book:

- `Judgment under Uncertainty...`
  - accepted headings are now close to the real outline structure
  - the old explosion of TOC fragments and author lines is gone

## Final Full-Dump Result

Run `680f39e03a83984211db7a8d`:

- `strong`: 17
- `acceptable_with_noise`: 3
- `needs_manual_review`: 2
- `needs_follow_up`: 0
- mean match ratio: `0.9648`
- median match ratio: `1.0`

This is the final state after the targeted hardening loop.

Compared with the earlier dump passes, the net effect is large:

- the corpus moved from a real `needs_follow_up` population to `0` active structural follow-up documents
- the remaining two documents are manual-review edge layouts, not confirmed structural misses
- the truth audit now says the final Phase C structure is strong on the large majority of the full dump

## Documents Inspected Closely

### Judgment under Uncertainty: Heuristics and Biases

Observed directly from the PDF and the exported inspection pack:

- the old failure mode was real: TOC fragments and author lines had been promoted as headings
- the current pass fixes that by relying on the strong `fitz` outline and suppressing heuristic recovery
- accepted headings now match the real book structure much more closely

### Consumers' Decision-Making Process on Social Commerce Platforms

Observed directly from the PDF and the exported inspection pack:

- this document stayed strong throughout
- heading structure is clean
- section and passage boundaries remain usable for later retrieval stages

### Online Reviews and Information Overload

Observed directly from the PDF and page/block inspection:

- the paper is genuinely difficult because of two-column ordering and repeated journal furniture
- the current structure is usable
- bad footer-driven gap-fill noise is no longer being injected
- remaining issues are mostly evaluator/frontmatter artifacts rather than missing core body structure

### Opinion Mining and Sentiment Analysis

Observed directly from the PDF and the outline:

- the clean `fitz` outline remains the correct backbone
- low-value `docling` detail under that outline is now much more contained
- the document is structurally in good shape for retrieval

### Whose online reviews to trust?

Observed directly from the PDF blocks and exported inspection pages:

- this accepted-manuscript PDF carries repeated manuscript noise
- the numbered gap-fill logic now recovers real missing numbered headings such as:
  - `2. Literature review`
  - `3. Hypotheses development`
  - `4. Data`
  - `6.2 Managerial implications`
  - `6.3 Limitations and future research`
- the remaining audit friction is mostly frontmatter-like material

### Fake online reviews

Observed directly from the PDF and the inspection pack:

- this document had real missing body structure before
- the final pass recovers missing sections such as:
  - `1. Introduction`
  - `2.2 Database`
  - `2.3.2 Publication sources`
  - `2.4 Conceptual Framework and Research Issues`
  - `6.2.1 Theoretical implications`
- this was a real structural fix, not evaluator noise

### Using Online Reviews for Customer Sentiment Analysis

Observed directly from the PDF and inspection pages:

- heuristic-recovery junk headings are no longer dominating
- the main article body structure is now the important extracted structure
- remaining layout difficulty comes from the paper's short, article-style formatting rather than ordinary parser failure

## Remaining Manual-Review Documents

After the final full dump rerun, the truth audit marks only these two documents as `needs_manual_review`:

- `the_effectiveness_of_nudging-76e15b34d02c`
- `to_nudge_or_not_to_nudge-16624afd839e`

Important nuance:

- these are not active `needs_follow_up` documents
- they are short, magazine-like or non-standard article layouts where the independent truth audit no longer has enough trustworthy heading evidence to score them like standard scholarly PDFs
- they should be watched later during retrieval evaluation, but they are not the same class of problem as the earlier real structural misses

## What The Remaining Problem Classes Are

### Real Phase C problem classes that were fixed

- TOC/author/title fragments promoted as headings in strong-outline documents
- bad heuristic-recovery lines in noisy short papers
- missing numbered body headings in no-outline documents
- running-header or title-prefix fragments promoted as headings
- footer/journal-furniture lines promoted through gap filling

### What remains

- short no-outline layouts that are not clean scholarly sectioned articles
- split-title / magazine-like pages where “true headings” are intrinsically ambiguous
- some frontmatter noise that is not retrieval-critical but still visually prominent in the PDF

## Recommendation

Freeze Phase C here unless a downstream retrieval/rerank failure points to a specific upstream structural miss.

Why:

1. the final full-dump audit has `0` active `needs_follow_up` documents
2. the benchmark remained stable and did not regress
3. the remaining edge cases are no longer ordinary structural extraction failures
4. further broad tuning now carries a higher risk of overfitting or reopening noise than of delivering generic wins

The right next step is to push this stabilized Phase C foundation into downstream retrieval evaluation and only come back if a later stage exposes a concrete upstream miss.
