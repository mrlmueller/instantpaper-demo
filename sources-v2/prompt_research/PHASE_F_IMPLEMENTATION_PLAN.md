# Phase F Implementation Plan

Status:
- ready for implementation planning
- based on empirical probes from 2026-03-09
- designed to avoid overfitting to only the two tested chapters

Goal:
- improve Phase F ranking accuracy and shortlist diversity
- keep strong recall from Phases B-D
- reduce duplicate/junk leakage before downstream grounding and rerank

This plan is written so the next step can be: “please implement”.

## 1. Keep the embedding model default unchanged

Decision:
- keep `text-embedding-3-small` as the default Phase F model

Reason:
- the first probe did not show enough benefit from `text-embedding-3-large`
- packaging, staging, and hygiene were clearly higher-leverage than model size

Implementation:
- keep `cfg.embedding_model = "text-embedding-3-small"`
- do not add a `large` switch to the default path yet

## 2. Add a deterministic chapter-target embedding text

Current problem:
- Phase F currently embeds facets and candidate metadata, but it does not have one strong chapter-level semantic target

Change:
- add a new function, for example `chapter_target_embed_text(plan, chapter_title, chapter_spec_text) -> str`

Content of the target text:
- chapter title
- chapter retrieval contract / spec
- `topic_summary_en`
- `topic_summary_de`
- `core_object_terms.en`
- `core_object_terms.de`
- `primary_context_anchors.en`
- `primary_context_anchors.de`
- `must_keep_constraints`
- `drift_risks`

Rules:
- deterministic assembly only
- no LLM call in the default path
- object/corpus/domain wording must come before method language

Role in scoring:
- this becomes the primary semantic query representation for Phase F

## 3. Change candidate text packaging

Current problem:
- metadata-only text is too thin
- very long candidate text broadens similarity too much

Default candidate embedding text:
- `Title: ...`
- `Year: ...`
- `Venue: ...`
- `Abstract: ...`

Default abstract budget:
- `800` chars

Important note:
- the probe suggests that `authors` are more likely noise than signal in the main embedding text
- I would omit `authors` from the main candidate embedding text
- keep authors in artifacts and reporting, not in the main semantic representation

Implementation:
- replace the current main candidate embedding view for abstract-bearing candidates with a new deterministic builder, for example:
  - `candidate_embed_text_main(c, abstract_chars=800)`

No-abstract candidates:
- keep a separate metadata-only fallback builder
- continue to support them, but do not let them dominate the top shortlist

## 4. Add mandatory candidate hygiene before ranking output

Current problem:
- duplicate titles and junk records can survive into top-k

Add a Phase F hygiene pass with two layers:

1. Pre-embedding cleaning:
- HTML unescape titles
- strip simple HTML tags
- collapse whitespace

2. Pre-output filtering / suppression:
- hard-drop exact normalized titles like:
  - `index`
  - `references`
  - `table of contents`
  - `contents`
  - `editorial`
  - `book review`
  - `book reviews`
  - `bibliography`
  - `preface`
  - `foreword`
  - `acknowledgements`
  - `conclusion`
  - `conclusions`
  - `introduction`
- hard title-level dedup in the ranked output

Dedup key priority:
1. DOI
2. arXiv / PMID / PMCID where available
3. normalized title + year + first-author-lastname

Output rule:
- the final Phase F shortlist handed downstream must have zero exact normalized-title duplicates

## 5. Rework Stage 1 scoring around chapter-target similarity

Decision:
- make chapter-target similarity the main Stage 1 score

Default Stage 1 score:
- `stage1_semantic = cosine(chapter_target_vec, candidate_main_vec)`

Facet embeddings:
- keep them, but do not use them as the main ranking signal
- use them for:
  - auxiliary diagnostics
  - later coverage tagging support
  - optional future booster experiments

Practical implementation choice:
- Phase F v1 should not depend on facet aggregation for the primary ranking score

## 6. Keep a staged shortlist chunk rerank

Decision:
- keep a second-stage chunk rerank for abstract-bearing candidates

Shortlist size:
- default `400`

Chunking defaults:
- use sentence-like chunks
- target chunk length roughly `260-420` chars
- chunk only the early informative portion of the abstract

Default Stage 2 score:
- `final_semantic = 0.55 * stage1_semantic + 0.45 * best_chunk_similarity`

Query for chunk similarity:
- use the same deterministic `chapter_target_doc`

Why:
- this was the best stable cross-topic design in the probes
- it improved specificity on the sparse historical chapter without requiring the larger embedding model

## 7. Add light diversity control after semantic scoring

Decision:
- apply a light MMR-style diversity pass to the final shortlist before downstream handoff

Default:
- apply on the final top `40`
- `lambda` around `0.82`

Behavior:
- keep relevance dominant
- only mildly penalize near-duplicates / near-clones

Important:
- do not use diversity to rescue weak candidates
- diversity only reorders a strong shortlist after hygiene

## 8. Keep a stricter path for no-abstract candidates

Current risk:
- candidates without abstracts can surface on title-only similarity

Implementation:
- keep the separate no-abstract pool
- score it with metadata-only embeddings
- apply a stricter threshold than with-abstract candidates
- cap no-abstract contributions to the downstream shortlist

Recommended default cap:
- at most `10-15%` of the final Phase F shortlist

This is a policy choice, but it is safer than treating no-abstract records as equal citizens in the main semantic lane.

## 9. HyDE should be optional, not default

Decision:
- do not add HyDE to the default Phase F path yet

Reason:
- it helped the sparse hard-topic run somewhat
- it was less stable on the broader methods run

Implementation plan:
- Phase F v1: no HyDE
- Phase F v2 optional fallback:
  - only for sparse chapters or weak candidate pools
  - one chapter-level HyDE doc via `gpt-5-mini`
  - blend as a secondary lane, not the only lane

## 10. New config surface

Add these config knobs:
- `embedding_candidate_abstract_chars_main = 800`
- `embedding_candidate_include_venue = True`
- `embedding_candidate_include_year = True`
- `embedding_candidate_include_authors = False`
- `embedding_shortlist_stage2 = 400`
- `embedding_chunk_target_min = 260`
- `embedding_chunk_target_max = 420`
- `embedding_stage2_weight = 0.45`
- `embedding_stage1_weight = 0.55`
- `embedding_apply_mmr = True`
- `embedding_mmr_lambda = 0.82`
- `embedding_max_no_abstract_share = 0.15`
- `embedding_apply_hygiene = True`

HyDE future knobs, but disabled by default:
- `embedding_use_hyde = False`
- `embedding_hyde_model = "gpt-5-mini"`
- `embedding_hyde_blend_weight = 0.35`

## 11. Artifact / logging changes

Add explicit Phase F artifacts:
- `chapter_target_embed_text.txt`
- `phase_f_candidate_hygiene_report.json`
- `phase_f_scoring_debug.jsonl`
- `phase_f_mmr_debug.json`

Hygiene report should include:
- dropped junk-title count
- merged duplicate count
- top-k duplicate suppression count
- HTML-cleaned title count

This is important because Phase F is now doing more than “just embeddings”.

## 12. Rollout order

Implement in this order:

1. candidate hygiene and title cleaning
2. deterministic `chapter_target_embed_text(...)`
3. new main candidate text builder with `abstract_chars=800`
4. Stage 1 switch to chapter-target similarity
5. Stage 2 chunk rerank on shortlist
6. light MMR on final shortlist
7. stricter no-abstract quota
8. only later, if needed: HyDE fallback

This order keeps the changes testable and isolates the highest-impact improvements first.

## 13. Acceptance checks after implementation

Run the same two cached chapters and require:
- zero exact normalized-title duplicates in the final shortlist
- zero junk-title records in the final shortlist
- no regression in hard-topic coverage on `ca79147de41f8edbfb47c9e5`
- no collapse back to generic helpfulness-only literature on `ed2e3d3304d5ed9587592f4d`

Qualitative check:
- top 20 should contain a better balance of:
  - chapter-object papers
  - method/proxy papers
  - fewer generic contextual or boilerplate review records

## 14. Summary of concrete defaults

If I had to lock the defaults now, they would be:
- model: `text-embedding-3-small`
- query text: deterministic `chapter_target_doc`
- candidate text: `title + year + venue + abstract[:800]`
- main semantic score: `cosine(chapter_target, candidate_main)`
- stage 2: chunk rerank on top `400`
- final score: `0.55 * stage1 + 0.45 * best_chunk`
- final shortlist: hygiene + title dedup + light MMR
- no-abstract cap: `15%`
- HyDE: off by default

That is the implementation plan I would use for Phase F v1.
