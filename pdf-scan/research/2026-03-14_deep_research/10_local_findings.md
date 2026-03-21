# Local Findings

## Benchmark Inventory

Known local suite:
- Suite id: `small_gold_webshop_decision_psychology_v1`
- Chapter count: 1
- Document count: 5
- Gold judgments present: no

Chapter spec summary:
- German chapter description with mixed German and English terminology.
- Real topics: decision psychology under uncertainty, digital nudging / choice architecture, perceived risk / trust in online shopping, uncertainty reduction.

Document inventory:
- `doc_001_short_document_candidate`: short social commerce / trust / perceived risk paper.
- `doc_002_very_long_document_candidate`: book-length `Judgment under Uncertainty`.
- `doc_003_medium_document_candidate_a`: online reviews / reviewer trustworthiness.
- `doc_004_medium_document_candidate_b`: online reviews / information overload.
- `doc_005_long_document_candidate`: opinion mining / sentiment analysis review.

Initial benchmark conclusion:
- This suite is currently a candidate pool, not a judged benchmark.
- It is useful for stress-testing short, medium, long, and very long PDFs.
- It still needs section-level labels and explicit negative judgments.

## Current Notebook State

Notebook observed:
- `pdf-scan-test.ipynb`: old vector-store-first approach.
- `pdf-scan-v2.ipynb`: new section-first rebuild, but only through Phase E.

Implementation gap vs plan:
- Implemented: Phase A, B, C, D, E.
- Missing from notebook flow: Phase F reranking, Phase G calibration / no-match, Phase H final reporting, Phase I benchmark harness.

## Observed Local Failure Modes

Phase B:
- Digital-PDF readability detection works reasonably.
- Docling success is inconsistent.
- Long documents may skip Docling due to page limits.
- GROBID is not configured in the current run.

Phase C:
- Structure preservation is better than the old notebook.
- Some documents normalize too coarsely and retain only a few top-level sections.
- Some documents create many near-heading fragments with tiny word counts.

Phase D:
- Query-term grounding is too literal.
- Many useful terms are pruned because they are not near-literal matches to the source chapter wording.
- This weakens lexical recall precisely where controlled expansion is needed.

Phase E:
- Retrieval is currently corpus-global, then fused, which still allows strong documents to dominate.
- Support calibration is too permissive.
- Broad phrases and weak unigrams can cause false trust assignment.
- Phase assessment can look healthy even when top candidates are semantically off-target.

## Immediate Design Implications

- Treat per-PDF retrieval and per-PDF abstention as core design goals.
- Separate:
  - source-grounded query anchoring
  - controlled bilingual / synonym expansion
  - evidence trust calibration
- Add a real reranking phase before final outputs.
- Add explicit no-match logic per document.
- Add judged benchmark artifacts before claiming quality.

## Current Cost / Size Snapshot

Observed in run `67507862e53171c27bfb2ac9`:
- Dense embedding input volume: 620,346 tokens across 5 PDFs.
- If priced at `text-embedding-3-large`, this is about `$0.080645` total, about `$0.016129` per PDF on average.
- If priced at `text-embedding-3-small`, this is about `$0.012407` total, about `$0.002481` per PDF on average.

Implication:
- The cost budget does not force a weak pipeline.
- It does favor:
  - smaller embedding models for broad candidate generation
  - expensive reranking only on a reduced per-document candidate set

## Current Normalization Granularity Snapshot

Observed from normalized artifacts:
- Total sections: 188
- Sections with fewer than 40 words: 38 (`20.21%`)
- Median section length: `433.5` words
- Maximum section length: `14,738` words

Implication:
- The current section graph mixes:
  - over-fragmented sections
  - very large sections that still need better subdivision or better passage evidence handling

Per-document section / passage load in the observed run:
- `consumers_decision_making_process_on_social_comm-7a6fd346a557`: 9 sections, 40 passages
- `judgment_under_uncertainty_heuristics_and_biases-5d61ba1a71f6`: 53 sections, 1541 passages
- `online_reviews_and_information_overload_the_role-42fa5aa25910`: 46 sections, 174 passages
- `opinion_mining_and_sentiment_analysis-d837b2bce0b4`: 73 sections, 321 passages
- `whose_online_reviews_to_trust_understanding_revi-22354b2e8251`: 7 sections, 69 passages

Inference:
- Per-document reranking is fully feasible.
- For small and medium PDFs, cross-encoder reranking can score nearly all sections.
- For very long PDFs, first-stage retrieval should reduce the candidate set before expensive reranking.
