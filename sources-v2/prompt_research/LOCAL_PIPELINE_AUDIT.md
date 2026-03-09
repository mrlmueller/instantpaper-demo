# Local Pipeline Audit

## Goal

Identify prompt and adjacent pipeline issues that plausibly reduce:
- relevance and accuracy
- recall and coverage
- ranking quality in the top results

## OpenAI Touchpoints

Prompt-bearing stages:
- Phase B `PLANNER_SYSTEM_PROMPT` and `PLANNER_USER_PROMPT_TEMPLATE`
- Phase C `OPENALEX_QUERY_BUILDER_*`
- Phase C `S2_BULK_QUERY_BUILDER_*`
- Phase I rerank `SYSTEM_PROMPT` and `_build_user_prompt(...)`

OpenAI but not prompt-driven:
- Phase F embeddings via `client.embeddings.create(...)`

Adjacent non-LLM stages that affect LLM quality:
- Phase F facet text construction and metadata text packaging
- Phase H coverage tag construction

## Concrete Findings From Code And Runs

### 1. Phase B planner can suppress the most distinctive chapter object

Evidence:
- March 7 retrieval run `25e6243ac55a5904fb1fcdfe` produced anchors such as `User generated content`, `Proxy variable`, `Natural language processing`, `Transformers`, `Rating metadata`.
- The chapter itself is explicitly about `online reviews as secondary data`, yet `online reviews` was not retained as a primary anchor.

Why this likely happens:
- The anchor rules ban generic research words including `review`.
- For this domain, `online reviews` is not generic noise; it is the core object of study.

Downstream effect:
- Phase C inherits broader, method-heavy anchors.
- Retrieval shifts toward generic NLP, topic modeling, and LLM survey literature.

### 2. Phase B over-weights general method facets

Evidence:
- March 7 retrieval run `25e6243ac55a5904fb1fcdfe` has many weight-5 facets for generic methodology: `text_preprocessing_steps`, `scalable_text_methods`, `measurement_and_metric_design`, `annotation_and_labeling`, `error_sources_and_mitigation`.
- These facets are useful, but they dominate the plan alongside the true chapter context.

Impact:
- Strong retrieval pressure toward broadly methodological NLP papers.
- Weak separation between "methods relevant to online-review secondary data" and "methods papers in general."

### 3. Phase B diagnostics are mostly hygiene checks, not specificity checks

Evidence:
- `diagnose_query_plan(...)` checks counts, duplicate IDs, term hygiene, and generic-anchor regex matches.
- It does not check whether anchors preserve the chapter's core entities, data source, or domain object.

Impact:
- Plans can pass validation while still being semantically under-specified.

### 4. Phase C OpenAlex builder is highly dependent on Phase B anchor quality

Evidence:
- March 7 retrieval run `25e6243ac55a5904fb1fcdfe` used an OpenAlex authority booster with `("Natural language processing" OR "Transformers" OR "Latent Dirichlet Allocation")`.
- That query shape is unsurprisingly capable of pulling broad NLP survey literature.

Impact:
- High-authority but weakly chapter-specific candidates enter the pool early.

### 5. Phase C S2 builder is still brittle on negative-term formatting

Evidence:
- March 7 retrieval run `25e6243ac55a5904fb1fcdfe`: `lint_failed` attempt 1 with `S2: non-atomic negative terms`.
- Previous run: same stage failed attempt 1 with non-atomic negatives.

Observed pattern:
- The model tends to generate quoted negatives that normalize poorly or get escaped awkwardly.

Impact:
- Extra retries and more chances for drift.
- Suggests the prompt is asking the model to do syntax management that deterministic post-processing could own more safely.

### 6. Phase I rerank is over-trusting upstream evidence

Evidence from the March 7 retrieval run top results:
- `Cheap, Quick, and Rigorous: Artificial Intelligence and the Systematic Literature Review`
- `Language Model Behavior: A Comprehensive Survey`
- `Large language models (LLMs): survey, technical frameworks, and future challenges`

These are method-adjacent, but too generic for the chapter compared with the chapter's actual target: online reviews as secondary data and proxy operationalization.

Likely cause:
- The reranker is instructed to use only `coverage_tags` and metadata.
- Coverage tags are derived from facet similarity, and the facet set itself is very method-heavy.

### 7. Phase H coverage tags amplify generic-method false positives

Evidence from code:
- With abstracts: a paper gets coverage tags for all facets with score `>= t` or the top 2 facets regardless.
- Without abstracts: top 1 facet is always included.

Impact:
- Even weakly relevant generic method papers arrive at Phase I with a bundle of seemingly grounded evidence tags.
- This inflates rerank confidence and encourages facet over-claiming.

### 8. Embedding text packaging is functional but minimal

Evidence:
- Facet embedding text is basically `facet narrative + canonical terms`.
- Candidate metadata view is title/venue/year/authors, with richer extras only for some cases.

Possible impact:
- The embedding space may under-represent chapter-specific object constraints versus broad methodological similarity.

### 9. OpenAlex query contract is partly stale relative to current provider docs

Evidence from code:
- The prompt and validator enforce `default.search` / `title_and_abstract.search`.
- `_normalize_openalex_query(...)` rejects `*`, `?`, and `~`.
- `_openalex_params(...)` still maps field-specific search into filter syntax such as `title_and_abstract.search:<query>`.

Why this matters:
- Current OpenAlex docs favor the top-level `search` parameter and document richer search capabilities than the current prompt allows.
- Even without changing code immediately, this is a real quality constraint and not just a documentation detail.

### 10. Rerank model choice is conservative relative to the user's stated quality objective

Evidence:
- Phase I hard-codes `MODEL_RERANK = 'gpt-5-nano'`.

Impact:
- If runtime and cost are genuinely secondary, rerank is a natural place to spend a stronger model on the top slice because this is the stage that directly shapes the user's top results.

### 11. Embedding model choice is also conservative

Evidence:
- Config default uses `embedding_model = 'text-embedding-3-small'`.

Impact:
- Given the stated priority on recall/quality over cost/runtime, the current embedding setup is likely optimized more for efficiency than for maximum semantic quality.

## Follow-up After The Phase B Update

### 12. The Phase B schema update fixed the biggest planner failure

Evidence from `17d29aaee1fecc8cf1a34025/query_plan.json`:
- anchors now include `online reviews`, `user reviews`, `review platforms`, `review text`, `secondary data`, and `text-based proxies`
- `core_object_terms`, `must_keep_constraints`, `drift_risks`, and `facet_group` are now present

Interpretation:
- the planner now preserves the chapter object much more reliably
- downstream query stages now have enough structure to distinguish object, method, context, and limitation signals

### 13. The Phase B update did not fix the weighting problem

Evidence from `17d29aaee1fecc8cf1a34025/query_plan.json`:
- 13 of 15 facets are weight `>=4`
- among those high-priority facets, `facet_group="method"` appears 6 times
- `topic_summary_en` still opens with a methods-first framing

Impact:
- the object is now protected, but methods still consume too much of the top-priority retrieval budget
- this is likely to keep pushing Phase C toward method-heavy expansions unless explicitly corrected

### 14. Empty queries are common, but the current pattern is not fully healthy

Cross-run cache counts:
- `25e6243ac55a5904fb1fcdfe`: OpenAlex `15/40` empty, S2 `14/33` empty
- `0eb47e270f7586fd6f09795c`: OpenAlex `19/40` empty, S2 `7/33` empty
- `4af2666be828e5054ccf4d31`: OpenAlex `21/42` empty, S2 `5/35` empty

Interpretation:
- some empty queries are a healthy by-product of narrow exploratory coverage
- the bigger problem is not the raw count alone, but whether entire query families or entire provider-language slices collapse at once

### 15. The S2 empty-query problem is strongly concentrated in German lexical designs

Evidence:
- in `25e6243ac55a5904fb1fcdfe`, every German S2 query returned `0` records
- in `0eb47e270f7586fd6f09795c`, several of those same German slots returned substantial counts:
  - `query_i=5`: `757`
  - `query_i=9`: `144`
  - `query_i=13`: `553`
  - `query_i=25`: `4`
  - `query_i=31`: `31`

Interpretation:
- S2 is not inherently failing on the topic
- the failure mode is prompt/query-design specific
- when the planner preserves direct review anchors better, German S2 queries become much more viable

### 16. The provider contract explains why S2 is sensitive here

Combined local-plus-doc interpretation:
- S2 bulk keyword search matches titles and abstracts
- the S2 FAQ indicates search generally does not expand abbreviations/acronyms
- literal DE mirroring, niche translated compounds, and acronym-heavy shorthand are therefore high-risk choices for S2 bulk search

Impact:
- provider-specific language strategy matters
- S2 should not be driven by a rigid EN/DE symmetry rule
- English and bilingual fallback queries should carry more of the S2 recall burden than they do now

### 17. Live provider probing confirmed both contract drift and provider quirks

Observed in direct probing on 2026-03-08:
- OpenAlex top-level `search` for `online reviews` was far broader than `title_and_abstract.search` for the same phrase
- OpenAlex wildcard, fuzzy, and proximity syntax all worked live
- S2 bulk worked anonymously, while S2 standard search returned `429` anonymously
- S2 bulk `limit` did not behave like a trustworthy page-size cap in repeated tests

Impact:
- the current OpenAlex restrictions are now clearly local-code restrictions, not provider restrictions
- S2 prompt design and adjacent retrieval logic need to account for live bulk-endpoint quirks, not only for cached run behavior

### 18. Replay of the actual generated Phase C queries surfaced the next real bottleneck

I replayed the generated OpenAlex and S2 query sets from run `17d29aaee1fecc8cf1a34025` directly against the live providers.

Most important findings:
- OpenAlex:
  - current zero-query rate was `26.9%`
  - EN zero-query rate was `0.0%`
  - DE zero-query rate was `87.5%`
  - alternate-surface/current median ratio was `20.06`
- S2:
  - bulk zero-query rate was `11.8%`
  - both zero-yield queries were German
  - negative ablations changed totals only marginally

Interpretation:
- the next main Phase C problem is not simply "too many dead narrow queries"
- it is "some query families are alive but too generic"

Concrete local examples:
- OpenAlex broad authority and reporting/workflow families produced large counts with weakly chapter-specific top titles
- S2 workflow / evaluation / reproducibility families also produced large totals with generic top titles
- German collapse remained real, but bilingual fallback only rescued authority-style cases, not every DE match family

Impact:
- OpenAlex broad `search` should likely be treated more selectively later
- S2 negatives are lower-priority than facet lexicality and family prioritization
- DE viability is family-specific, not a global on/off switch

## Cross-Run Comparison

`25e6243ac55a5904fb1fcdfe` is the clearest bad retrieval run:
- planner drifted toward generic methods
- S2 had `14/33` empty queries
- all German S2 queries were empty

`0eb47e270f7586fd6f09795c` looked healthier:
- anchors included `online reviews`, `user reviews`, `customer feedback`, `app stores`, `hospitality platforms`
- S2 had only `7/33` empty queries
- several German S2 queries produced substantial counts instead of collapsing to zero

`17d29aaee1fecc8cf1a34025` is the best planner cache so far:
- object retention is much better
- new schema fields make downstream control stronger
- retrieval did not run yet, so Phase C behavior still needs validation

`4af2666be828e5054ccf4d31` is a useful older retrieval comparison:
- OpenAlex still had many empty queries
- S2 had only `5/35` empty queries
- this shows S2 can produce strong coverage when query families align better with provider behavior

Interpretation:
- current prompt wording and query-family design are still not robust enough
- Phase B object retention is much better now, but Phase C still needs provider-specific yield control

## Hypotheses To Validate With External Research

1. Planner prompts should explicitly separate:
- chapter object / corpus
- task / analytical method
- target construct / proxy
- exclusions / confounders

2. Query generation prompts should use retrieval-specific guidance:
- must-have anchors
- drift controls
- facet budgeting by recall value
- provider-specific syntax ownership split between prompt and deterministic code

3. Rerank prompts should score against chapter-conditional must-haves instead of flat facet accumulation.

4. Evaluation should combine:
- recall-oriented judged pools
- top-k ranking metrics
- facet coverage metrics
- error taxonomy for drift, missed core papers, and generic-method false positives
