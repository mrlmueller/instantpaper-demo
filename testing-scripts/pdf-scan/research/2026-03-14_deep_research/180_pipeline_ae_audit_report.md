# Full A-E Audit and Hardening Pass

Date: 2026-03-15

## Scope

This pass audited the complete pipeline from Phase A through Phase E, with emphasis on:

- reading the actual Phase E retrieved sections and supporting passages
- manually inspecting suspicious benchmark and `paper-dump` candidates
- tracing retrieval errors back into Phase C normalization when necessary
- rerunning the benchmark and the 22-PDF `paper-dump` corpus after each targeted fix

The goal was not just to improve metrics, but to remove concrete bad retrieval behaviors that would mislead later ranking and reporting.

## Main Problems Found

### 1. Metadata-only sections could still rank

Concrete example:

- `digital_nudging-c70013fb5862`
- section title: `Digital Nudging`
- section text was essentially title-page metadata / open-access boilerplate

This section was retrieval-eligible because it was just above the tiny-section cutoff and its title looked semantically relevant.

### 2. Frontmatter lines still leaked into some abstract-like sections

Concrete example:

- `consumers_decision_making_process_on_social_comm-7a6fd346a557`
- section title: `Consumers’ Decision-Making Process on Social Commerce Platforms`
- section text previously began with:
  - `This article was submitted to`
  - `a section of the journal`

The section itself was useful, but the frontmatter leak made the output dirtier than acceptable.

### 3. Heuristic recovery still promoted some garbage headings

Concrete examples from the long heuristics book:

- `c. Was quite unconcerned about how people reacted to him. d`
- `1. A time limit was implied for the depression. 2`
- citation-list / author-fragment headings

These were not ordinary weak matches. They were real normalization defects caused by list items or fragments being mistaken for headings.

### 4. Phase E was still too forgiving of low-evidence candidates

Even after earlier fixes, some generic or weakly supported candidates could remain too high because fused ranking trusted title/body recall more than evidence density.

## Code Changes

### Phase C

Updated file:

- `pdf-scan/phase_c_lab.py`

Changes made:

- added frontmatter metadata patterns for:
  - `this article was submitted to`
  - `a section of the journal`
  - `this article belongs to the section`
- added structural suppression for metadata-block sections
- added structural suppression for very short residual metadata sections
- added heuristic heading-noise rejection for:
  - short author-like headings
  - citation-list style headings
  - discourse-fragment headings
  - list-item headings that look like sentence fragments
  - enumerated multi-item pseudo-headings like `1. ... 2`

### Phase E

Updated file:

- `pdf-scan/phase_e_lab.py`

Changes made:

- added ranking penalties for:
  - zero supporting passages
  - single supporting passage
  - generic titles with only weak evidence
- kept the existing generic-title evidence bonus, but balanced it with stronger evidence-aware selection

### Audit Tool

Used file:

- `pdf-scan/review_pipeline_ae.py`

This reviewer remained useful for surfacing suspicious sections, but one current warning class (`journal_header`) still has at least one evaluator-noise false positive.

## Final Validation Runs

### Benchmark

Run:

- `2270646d3c56c160a8e30345`

Artifacts:

- `runs/2270646d3c56c160a8e30345/retrieval/phase_e_summary.json`
- `runs/2270646d3c56c160a8e30345/retrieval/phase_e_assessment.json`
- `runs/2270646d3c56c160a8e30345/pipeline_ae_review/pipeline_ae_review_summary.json`
- `runs/2270646d3c56c160a8e30345/pipeline_ae_review/pipeline_ae_review.md`

Headline result:

- review category: `strong`
- fused candidates: `120`
- embedding cost: `$0.01101818`
- top-20 suspicious candidates: `0`
- top-50 suspicious candidates: `1`

Important outcome:

- the bad questionnaire-item heading `1. A time limit was implied for the depression. 2` was removed from the top-20
- the `Consumers’ Decision-Making Process...` section is now clean frontmatter-wise and remains substantively useful

### 22-PDF `paper-dump`

Run:

- `298d23d84ce6933a316dfa71`

Artifacts:

- `runs/298d23d84ce6933a316dfa71/retrieval/phase_e_summary.json`
- `runs/298d23d84ce6933a316dfa71/retrieval/phase_e_assessment.json`
- `runs/298d23d84ce6933a316dfa71/pipeline_ae_review/pipeline_ae_review_summary.json`
- `runs/298d23d84ce6933a316dfa71/pipeline_ae_review/pipeline_ae_review.md`

Headline result:

- review category: `strong`
- fused candidates: `120`
- embedding cost: `$0.02021552`
- top-20 suspicious candidates: `1`
- top-50 suspicious candidates: `2`

Important outcome:

- the bad metadata-only `Digital Nudging` section is gone from the top results
- the top-20 now contains real trust / review / information-overload / digital-nudging sections across 6 documents
- the paper-dump top-20 is materially more diverse than earlier audit passes

## Manual Spot Checks

The following were manually re-read after the final fixes:

- `The Trust Building Mechanisms in Social Commerce`
- `Consumers’ Decision-Making Process on Social Commerce Platforms`
- `Information Overload in Online Platforms`
- `Digital Nudging -- Guiding Judgment and Decision-Making in Digital Choice Environments`
- `3.2 Identified Psychological Effects and Nudges`
- `6.2.2 Practical implications` from `fake_online_reviews...`

Manual judgment:

- the first five are legitimate, useful retrieval hits
- `6.2.2 Practical implications` appears substantively valid; the reviewer flag on it looks like evaluator noise rather than a real retrieval defect

## Remaining Risks

These are the main residual issues after the final hardening pass:

- the benchmark still over-indexes on the long heuristics book because it is semantically rich for uncertainty / risk language
- some benchmark top-50 items from the long book remain broad or oddly titled, even though the worst normalization artifacts were removed
- some generic sections (`Introduction`, `Conclusion`, `Abstract`) still appear in top-50 when they carry real conceptual signal
- some table-heavy sections from `online_reviews_and_information_overload...` can still surface in top-50 because the paper is genuinely central to the topic and some table-adjacent sections contain substantive interpretation

## Conclusion

This pass materially improved trustworthiness of the current pipeline state.

The most important change is not a small score bump. It is that the pipeline now rejects a class of normalization defects that previously produced plausible-looking but actually bad retrieval hits. The remaining issues are mostly ranking tradeoffs and evaluator noise, not the same kind of upstream extraction failure.

This is a substantially cleaner A-E baseline for Phase F onward.
