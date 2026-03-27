# Phase E/F Joint Testing Report

## Scope

This pass tested Phase E and Phase F together on the current stabilized pipeline state. The goal was not only to compare retrieval against reranking, but to read actual retrieved sections and evidence passages, identify contradictory judge behavior, and verify that the saved outputs match the real content.

Corpora used:

- benchmark run `2270646d3c56c160a8e30345`
- paper-dump run `298d23d84ce6933a316dfa71`

Key artifacts:

- `runs/<run_id>/retrieval/*`
- `runs/<run_id>/rerank/*`
- `runs/<run_id>/phase_e_review/*`
- `runs/<run_id>/phase_f_review/*`
- `runs/<run_id>/phase_ef_review/*`

## Test protocol

The joint test loop used four layers:

1. Re-read saved Phase E fused candidates and Phase F rerank rows.
2. Compare top-k composition, generic-title contamination, and document diversity.
3. Manually inspect actual candidate text and supporting passages for promoted, demoted, and suspicious rows.
4. Trace any contradiction back into code and rerun the phase if the issue was real.

## Real issue found and fixed

Phase F had a real robustness gap in `judge_payload_is_inconsistent()` inside `phase_f_lab.py`.

The issue:

- some LLM judge outputs returned raw scores of `0/0/0`
- the free-text notes still clearly said the section was relevant or useful
- one such row was being blended as `judge_score = 0.0` instead of being rejected as inconsistent

This was not just reviewer noise. It directly affected rerank scores.

Fix applied:

- broadened inconsistency detection to catch phrases like `relevant to`, `highly useful`, `helpful for`, and more general positive notes such as `section discusses`, `section explains`, `section covers`, `section provides`
- added a small negative-marker guard so obviously negative notes are not falsely flagged

After the fix, Phase F was rerun on both corpora and the review artifacts were regenerated.

## Quantitative result

### Benchmark

Phase E to Phase F:

- top-10 overlap: `6`
- top-20 overlap: `15`
- generic titles in top-10: `3 -> 0`
- generic titles in top-20: `3 -> 0`
- top-10 verdicts: `7 strong / 3 partial -> 10 strong`
- top-20 verdicts: `16 strong / 4 partial -> 20 strong`

Important behavior:

- two generic introductions were pushed out of the top-20
- stronger judgment-under-uncertainty sections were promoted into the top-10
- the benchmark top-20 is still concentrated in `2` documents, which is acceptable for a global ranker but confirms that Phase G must remain per-document

### Paper-dump

Phase E to Phase F:

- top-10 overlap: `7`
- top-20 overlap: `16`
- generic titles in top-10: `4 -> 0`
- generic titles in top-20: `6 -> 0`
- top-10 verdicts: `6 strong / 4 partial -> 10 strong`
- top-20 verdicts: `11 strong / 9 partial -> 20 strong`

Important behavior:

- top-10 remains diverse across `4` documents
- top-20 now concentrates into `5` documents instead of `6`
- this is a tradeoff, not a failure: the documents that remain are the ones with the strongest direct signal for the current chapter description

## Manual verification highlights

The following rows were inspected directly from `rerank_results.jsonl`, `llm_judge.jsonl`, and the saved evidence snippets.

### Good promotions / retained hits

- `Consumer Purchase Intention in Social Commerce`
  - final rank `2`
  - contains trust antecedents, perceived security/value, reputation effects, recommender explanation mode, and purchase-intention linkage
  - this is clearly useful for trust, perceived risk, and uncertainty-reduction framing

- `Information Overload in Online Platforms`
  - final rank `4`
  - directly discusses information uncertainty, overload, online reviews as signals, and reduced uncertainty through platform-provided signals
  - this is one of the cleanest S1/S3/S4 matches in the corpus

- `The Valence of Top Reviews and Information`
  - final rank `10`
  - discusses featured/top reviews, information overload, parsimonious information, heuristics, and review-based signaling
  - previously undercut by contradictory judge output; after the inconsistency fix it sits where it belongs

- `3. Taxonomy and catalog of nudging mechanisms`
  - final rank `13`
  - no longer over-promoted, but still surfaces as a useful digital-nudging framing section
  - strong for choice-architecture language, weaker for trust/review-specific content

### Correct demotions

- `1. Introduction` from `Whose online reviews to trust?`
  - `phase E rank 2 -> phase F rank 27`
  - still a useful introduction, but correctly no longer crowds out more specific trust / overload / nudging sections

- `Digital Nudging -- Guiding Judgment and Decision-Making in Digital Choice Environments`
  - `phase E rank 11 -> phase F rank 31`
  - good definitional text, but too generic compared with more specific nudging sections

- `6.2.2 Practical implications` from `Fake online reviews...`
  - `phase E rank 18 -> phase F rank 53`
  - correct downrank; evidence is dominated by references and backmatter-like content

## Residual issues

The main remaining problems are not top-ranking failures in E/F.

- `More popular Less popular Variable Mean Std. dev`
  - still exists as a noisy normalized section
  - currently around rank `34`, not top-20
  - this is upstream Phase C debt, not a Phase E/F top-result failure

- some `Introduction` / `Conclusion` rows are still valid and remain in top-20 when they contain real signal
  - this is acceptable as long as they are not generic and content-empty

- benchmark global ranking still collapses to a small number of documents
  - this is exactly why Phase G should finalize usefulness per PDF rather than treating global top-k as the end product

## Conclusion

Phase E/F now holds up well under a more adversarial audit.

What this testing round established:

- Phase F is materially improving Phase E, not just reshuffling it
- generic-title contamination is removed from the top results
- manually read evidence supports the high-ranked rows
- the most important concrete bug in this pass was the Phase F judge inconsistency gate, and it is now fixed

Current readiness:

- strong enough to continue into Phase G
- with one important caveat: remaining mid-rank noise should be treated as upstream normalization debt, not as a reason to block the per-document decision phase
