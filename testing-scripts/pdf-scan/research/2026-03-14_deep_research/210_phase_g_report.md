# Phase G - Calibration and no-match decision

## Goal

Phase G converts reranked section candidates into stable section scores and a final per-PDF decision:

- does this PDF contain useful information for the chapter?
- if yes, which sections are the best evidence?
- if not, why was it rejected?

This is the first phase that answers the actual product question at document level.

## Inputs

- `rerank/rerank_results.jsonl`
- `normalized/documents.jsonl`
- `query_plan.json`
- `retrieval/phase_e_subpoint_support.json`

## Outputs

- `final/section_scores.jsonl`
- `final/doc_features.jsonl`
- `final/per_pdf_rankings.json`
- `final/global_rankings.json`
- `final/output.json`
- `final/phase_g_summary.json`
- `final/phase_g_assessment.json`
- `final/calibration_trace.json`

## What was implemented

- section-level provisional scoring on top of Phase F rerank output
- support-strength labels and evidence previews per section
- per-document usefulness / no-match decisions
- explicit abstention reasons such as:
  - `top_section_below_threshold`
  - `only_generic_sections_ranked_high`
  - `only_penalized_sections_ranked_high`
  - `low_document_match_probability`
  - `no_ranked_sections`
- calibration trace reporting that states whether scores are learned or rule-based

## Calibration status

True learned calibration was not used yet.

Reason:

- there are still no labeled document judgments in `benchmark/small_gold/judgments`
- `sklearn` is not installed in the current environment

So Phase G currently uses conservative provisional rules and writes that explicitly to `calibration_trace.json`.

## Validation runs

### Benchmark

Run: `2270646d3c56c160a8e30345`

Result:

- `2` useful PDFs
- `3` no-match PDFs
- review category: `strong`

Top useful PDFs:

- `Judgment under Uncertainty: Heuristics and Biases`
- `Consumers' Decision-Making Process on Social Commerce Platforms`

Top benchmark artifacts:

- `final/output.json`
- `final/doc_features.jsonl`
- `phase_g_review/phase_g_review_summary.json`

### Paper dump

Run: `298d23d84ce6933a316dfa71`

Result:

- `5` useful PDFs
- `17` no-match PDFs
- review category: `strong`

Useful PDFs:

- `Online Reviews and Information Overload The Role of Selective, Parsimonious, and Concordant Top Reviews`
- `Consumers' Decision-Making Process on Social Commerce Platforms: Online Trust, Perceived Risk, and Purchase Intentions`
- `Digital Nudging`
- `Digital Nudging: Altering User Behavior in Digital Environments`
- `Digital nudging with recommender systems: Survey and future directions`

Important abstention behavior:

- `Whose online reviews to trust?` was rejected with `only_generic_sections_ranked_high`
- sentiment-analysis survey papers were mostly rejected with `top_section_below_threshold`
- two PDFs with no viable downstream candidates ended with `no_ranked_sections`

## Why this phase matters

Phase E and Phase F are still retrieval and ranking machinery.

Phase G turns that into a usable answer format for chapter writing:

- per PDF: useful or not useful
- per useful PDF: top relevant sections
- per rejected PDF: reason for rejection

Without this phase, the pipeline can rank sections but cannot safely abstain.

## Current limitations

- section scores are not yet probability-calibrated from labels
- Phase G will not rescue a PDF if Phase E/F only surfaced weak evidence
- borderline documents remain sensitive to upstream candidate quality

## Recommended next step

Move to Phase H / final presentation and then Phase I benchmark labeling.

The biggest quality jump from here will not come from more Phase G heuristics. It will come from:

1. labeled document and section judgments
2. learned calibration
3. end-to-end benchmark evaluation of abstention quality
