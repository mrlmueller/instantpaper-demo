# Prompt Optimization Report

Status: updated after the Phase B schema/prompt follow-up and a targeted zero-result query audit on 2026-03-08.

## Scope

This report covers all stages in `sources-v2` where OpenAI outputs directly shape retrieval quality, plus adjacent non-LLM stages that amplify or dampen those effects:
- Phase B query planner
- Phase C OpenAlex query builder
- Phase C Semantic Scholar bulk query builder
- Phase I rerank prompt
- Phase F embedding-text construction
- Phase H coverage-tag construction
- benchmarking for recall, relevance, and ranking quality

Important framing:
- the biggest issue is not one bad prompt
- the main issue is cross-stage drift
- the planner can under-specify the chapter object
- the query builders then expand the wrong thing
- Phase H makes weak matches look well-supported
- Phase I over-trusts that evidence

The prompt texts below are written as:
- drop-in replacements that preserve the current JSON schemas and overall stage contracts
- optional stronger upgrades that would need code/schema changes later

Follow-up note:
- this revision incorporates the Phase B schema update that has already been applied locally
- it also adds practical tuning guidance for reducing avoidable zero-result queries, especially in Semantic Scholar

## Executive summary

### Main diagnosis

The current pipeline is strong overall, but it is vulnerable to a specific failure mode:
- concrete chapter objects get abstracted away too early
- generic methods become over-represented
- broad, high-authority method papers enter the pool
- later stages treat those papers as well-grounded because facet coverage is too generous

In an earlier up-to-date retrieval run (`25e6243ac55a5904fb1fcdfe`), the chapter was about online reviews as secondary data and proxy operationalization, but the query plan over-centered:
- natural language processing
- transformers
- latent dirichlet allocation
- rating metadata

and under-centered:
- online reviews
- user reviews
- customer reviews

That was the core optimization target.

The newest planner-only run (`17d29aaee1fecc8cf1a34025`) now fixes most of that specific failure:
- anchors preserve `online reviews`, `user reviews`, `review platforms`, and `text-based proxies`
- the planner now exposes `core_object_terms`, `must_keep_constraints`, `drift_risks`, and `facet_group`

The remaining issue is weighting, not object loss:
- 13 of 15 facets are still weight `>=4`
- 6 of those 13 high-priority facets are `facet_group="method"`

So the object is now protected much better, but methods still consume too much of the top-priority budget.

### Highest-leverage changes

1. Keep tuning the planner so the high-weight facet budget is object-led, not method-led.
2. Rewrite both query builders so every query family stays anchored to the chapter object, not only to methods or facets.
3. Reduce avoidable zero-result queries by making language strategy and query-family design provider-specific instead of mechanically mirroring every query.
4. Rewrite rerank so generic method surveys score conservatively unless the evidence explicitly ties them to the chapter target.
5. Make Phase H coverage tags more conservative; they currently make false positives look evidence-rich.
6. Build a judged benchmark pool so prompt changes are measured against recall, top-k quality, and query-yield health, not impressions.

## Evidence base

This report is based on:
- local code and run-artifact audit in `LOCAL_PIPELINE_AUDIT.md`
- exact request payloads under `sources-v2/openai_request_debug`
- cross-run cache-yield comparisons across `17d29aaee1fecc8cf1a34025`, `25e6243ac55a5904fb1fcdfe`, `0eb47e270f7586fd6f09795c`, and `4af2666be828e5054ccf4d31`
- current OpenAI docs on prompting, evals, reasoning best practices, and structured outputs
- current OpenAlex and Semantic Scholar provider docs
- retrieval and reranking papers including Query2doc, HyDE, Promptagator, RankGPT, and pairwise ranking prompting
- systematic-review search guidance including PRESS and PRISMA-S

See `SOURCE_LEDGER.md` for the exact source list.

## What belongs in the system prompt vs user prompt

### System prompt

Use the system prompt for stable, cross-run behavior:
- role
- optimization priority order
- grounding policy
- anti-drift rules
- what to do when constraints conflict

For this project, every system prompt should encode:
- preserve the chapter object before broadening
- use only supported evidence or inputs
- do not optimize away concrete domain nouns
- prefer conservative, on-topic recall over generic breadth

### User prompt

Use the user prompt for run-specific material:
- chapter title
- chapter spec
- query plan JSON
- provider budget
- schema description
- lane/pool info
- current required facets

This split matters because the stable anti-drift policy should not be repeated ad hoc in every run.

## Phase B — Query Planner

### Diagnosis

The planner remains the single biggest leverage point, but the post-update state is now materially better than the March 7 planner.

Historical issues that the update substantially improved:
- generic-looking words were banned too aggressively at token level
- chapter-object retention was not explicit enough
- validation focused more on hygiene than on specificity

Remaining issues after the update:
- high-weight facets are still too method-heavy
- the English summary still leads with a methods-first framing
- some exclusions are too aggressive for a recall-oriented chapter
- one of the `must_keep_constraints` is implementation-specific rather than retrieval-specific

### Post-update read of the current Phase B cache

In `17d29aaee1fecc8cf1a34025/query_plan.json`, the planner now does the most important thing correctly:
- the core object is explicit in anchors and `core_object_terms`
- `must_keep_constraints` and `drift_risks` make downstream control much easier
- `facet_group` gives later stages a usable distinction between object, context, data, limitation, and method

What I would still change after reading that cache:
- make `topic_summary_en` start from the object, not from `surveys methodological literature`
- reduce the number of weight `5` and weight `4` facets when the chapter is not primarily a methods chapter
- reserve more of the top-priority budget for `object`, `data_proxy`, `construct`, and `limitation`
- remove synthesis-genre exclusions such as `review article`, `literature review`, and `systematic review` unless they are clearly wrong-sense for the chapter
- keep `must_keep_constraints` focused on scientific retrieval constraints; `exclude project-specific keyword lists` reads more like local scope management than like a literature-search invariant

### Drop-in replacement: `PLANNER_SYSTEM_PROMPT`

```text
You are a scientific literature search planner for a multi-stage academic retrieval pipeline.
Your job is not to describe a topic in generic academic language. Your job is to preserve the chapter's exact retrieval target so downstream query builders can find the right literature.

Priority order:
1) Preserve the chapter's core object, corpus, domain, or context exactly.
2) Preserve the main constructs, questions, outcomes, or debates.
3) Preserve data-source, proxy, measurement, and validity constraints.
4) Add useful neighboring facets without diluting the core object.
5) Add exclusions only for true wrong-sense confounders.

Rules:
- If a phrase is central to the chapter object, keep it even if one token inside the phrase is generic.
- Do not replace concrete chapter nouns with broader abstractions.
- Method terms are supporting context unless the chapter is explicitly about methods.
- Do not name specific papers, authors, or venues. Do not invent citations.
- Be deterministic and return only valid JSON.
```

### Drop-in replacement: `PLANNER_USER_PROMPT_TEMPLATE`

```text
CHAPTER_TITLE:
{{chapter_title}}

CHAPTER_SPEC (retrieval contract):
{{chapter_spec_text}}

TASK:
Return a QueryPlan JSON object with the existing schema.

HOW TO INTERPRET THE CHAPTER:
Preserve these distinctions in the plan:
- chapter object / corpus / domain context
- target construct / question / outcome
- data source / proxy / measurement constraints
- analytical methods
- exclusions / wrong-sense confounders

PRIORITY ORDER:
1) preserve the chapter's core object/corpus/domain exactly
2) preserve the main constructs/questions/outcomes
3) preserve data/proxy/measurement constraints
4) add useful neighboring facets without diluting the object
5) add exclusions only for true wrong-sense confounders

Return a QueryPlan JSON object with these keys:

1) topic_summary_en: 2-3 sentences
2) topic_summary_de: 2-3 sentences (natural German)

Summary rules:
- State the chapter object, the main construct/question, and the role of data/proxies/methods.
- Do not generalize away the named corpus/object.

3) primary_context_anchors:
   - en: 4-10 short anchors
   - de: 4-10 short anchors
   RULES:
   - Each anchor must be 1-6 words.
   - At least 2 anchors per language should name the core object/corpus/domain when available.
   - Pure method anchors are allowed only if genuinely central; they must never be the majority.
   - Avoid vague standalone research words such as analysis, study, effects, framework, model, system, approach, dynamics, development, overview.
   - A full phrase may be kept if the phrase itself is chapter-critical, even if one word inside it is generic.
   - Avoid long narrative phrases. Avoid parentheses and commas inside anchors.

4) global_canonical_terms:
   - en: 12-30 terms/phrases
   - de: 12-30 terms/phrases
   TERM HYGIENE:
   - Each term must be <= 4 words.
   - No explanatory text, no “e.g.” / “z. B.”.
   - No parentheses, no commas, no semicolons.
   - Preserve important chapter wording if it is likely to appear in titles/abstracts.
   - Ensure the list includes object terms first, then construct/data/proxy terms, then method terms.

5) global_exclusions:
   - en: 0-12 atomic confounder terms
   - de: 0-12 atomic confounder terms
   EXCLUSION RULES:
   - Only include exclusions that are likely to appear in unrelated literature and cause wrong-sense retrieval.
   - <= 3 words each
   - No punctuation except hyphen
   - If unsure, omit the exclusion

6) facets: 8-18 ATOMIC facets.
For each facet:
- facet_id: lower_snake_case, 3-6 words, stable
- facet_type: one of ["background","theory","mechanism","methods","data","measurement","evaluation","case_context","debate","limitations","applications"]
- importance_weight: integer 1..5
- facet_label_en: <= 8 words
- facet_label_de: <= 8 words
- text_en: 1-2 sentences
- text_de: 1-2 sentences
- canonical_terms.en/de: 6-18 terms each
- neighbor_terms.en/de: 4-12 terms each
- exclusion_terms.en/de: 0-6 terms each

FACET RULES:
- Cover every explicit instruction in the chapter spec.
- Add 2-4 useful neighboring facets that support retrieval, but keep the plan centered on the named chapter object.
- If the chapter is not primarily a methods chapter, generic methods facets must not dominate the weight>=4 set.
- For any methods/data/measurement facet, write it as methods/data/measurement FOR this chapter object, not as a generic field overview.
- If the chapter mentions proxies, secondary data, validity, bias, or representativeness, add the relevant facets when supported by the spec.
- Keep facets non-overlapping as much as possible.

QUALITY CHECKS:
- If your top anchors would retrieve generic method papers but not the chapter object, revise them.
- If the plan drops the concrete object/corpus in favor of abstractions, revise it.
- If an exclusion is not a clear wrong-sense confounder, omit it.

OUTPUT:
Return ONLY valid JSON. No extra text.
```

### What I would tune further

- Anchor count:
  - `4-10` is safer than `3-8` for recall-oriented planning.
- High-weight budget:
  - if the chapter is not explicitly methods-centric, keep the weight>=4 set closer to `8-10` facets than `13+`.
- Method-facet cap:
  - if the chapter is not explicitly methods-centric, cap method-heavy weight>=4 facets at roughly one-third.
- Object anchor preservation:
  - strongly consider a deterministic validator that checks whether at least one top anchor matches a noun phrase from the chapter title/spec.
- Summary framing:
  - force the first summary sentence to name the chapter object/corpus before methods.
- Exclusion discipline:
  - treat synthesis terms as high-risk exclusions; they can remove exactly the kind of methodological overview papers this chapter may legitimately need.

### Implemented schema upgrades and one next idea

The following schema upgrades have now been implemented locally:
- `core_object_terms`
- `must_keep_constraints`
- `drift_risks`
- `facet_group`

That materially improves downstream control.

One further upgrade worth considering later:
- add a lightweight per-facet retrieval preference such as `query_family_preference` or `retrieval_priority`, so Phase C can prefer object+data/proxy and object+limitations queries before method-heavy expansions

## Phase C.1 — OpenAlex Query Builder

### Diagnosis

Main issues:
- too much freedom to broaden into method-only or method-dominant queries
- prompt and validator assume an older OpenAlex search surface
- current implementation still leans on `default.search` / `title_and_abstract.search` handling
- prompt forbids `* ? ~`, while current OpenAlex docs support richer search features

Important distinction:
- the prompt rewrite below stays inside the current code constraints
- but the report also recommends later provider-contract updates

### Post-update query-yield read

Across three recent retrieval runs, OpenAlex empty-query counts were:
- `15/40` in `25e6243ac55a5904fb1fcdfe`
- `19/40` in `0eb47e270f7586fd6f09795c`
- `21/42` in `4af2666be828e5054ccf4d31`

Interpretation:
- this is higher than ideal, but not automatically a defect
- some empty OpenAlex queries are a healthy by-product of narrow exploratory coverage
- the bigger lever is to make sure the empties are concentrated in deliberately narrow long-tail probes, not in core authority or core object+construct families

### Live API probe findings

Direct probe results on 2026-03-08 confirmed that current live OpenAlex behavior is materially different from the current pipeline assumptions:
- `search=online reviews` with English filters returned `4,222,853` hits
- `title_and_abstract.search:online reviews` with the same filters returned `254,273`
- `review*`, `operationalization~1`, and `"online reviews"~2` all returned `200` with nonzero results
- exact phrase conjunctions are easy to over-constrain:
  - `("online reviews" AND "proxy operationalization")` returned `0`
  - `("online reviews" AND "selection bias")` returned `546` on top-level `search` and `26` on `title_and_abstract.search`

Interpretation:
- the current provider contract drift is real
- top-level `search` is much broader than `title_and_abstract.search`
- wildcard, fuzzy, and proximity syntax worked live
- exact phrase AND should be used cautiously even if the provider accepts it

### Generated-query replay findings

I replayed the actual generated OpenAlex query set from run `17d29aaee1fecc8cf1a34025` against live OpenAlex.

High-signal results:
- `26` queries total
- current zero-query rate: `26.9%`
- EN zero-query rate: `0.0%`
- DE zero-query rate: `87.5%`
- median alternate-surface/current ratio: `20.06`

Most important interpretation:
- the replay does confirm large surface lift from `title_and_abstract.search` to top-level `search`
- but it also shows that broad `search` is not automatically good retrieval

Examples:
- authority query `Platform effects, bias, and validity in review data`
  - current `search` count: `21,410`
  - alternate `title_and_abstract.search` count: `1,245`
  - top results were still generic enough to suggest drift
- match query `Reporting and reproducibility practices for studies using reviews`
  - current `title_and_abstract.search` count: `473`
  - alternate `search` count: `20,954`
  - top results were mostly generic reproducibility / data-source papers
- match query `Practical sampling and sample construction from raw reviews`
  - count: `55`
  - top results were still weakly review-specific
- match query `Principles to design text-based proxies and lexicon/classifier approaches`
  - count: `64`
  - top results were mostly generic lexicon / sentiment-analysis papers

German replay behavior:
- only one DE OpenAlex query was materially alive (`13` results)
- targeted bilingual rescue for the failed DE authority query increased count from `0` to `1,384`
- targeted bilingual rescue for a failed DE proxy-match query remained `0`

Interpretation:
- bilingual fallback can rescue broad DE authority failures
- it does not rescue every DE method/proxy facet
- the current OpenAlex problem is therefore two-part:
  - some DE families are lexically dead
  - some EN authority/method families are alive but too broad

### Drop-in replacement: `OPENALEX_QUERY_BUILDER_SYSTEM_PROMPT`

```text
You generate OpenAlex /works query objects for a multi-stage scientific retrieval pipeline.
Your job is to maximize useful recall without losing the chapter's true object.

Priority order:
1) Keep every query inside the chapter object, corpus, or domain.
2) Cover the main constructs, data/proxy constraints, and required facets.
3) Add breadth through controlled synonym and facet variation.
4) Add authority boosters only when they remain chapter-anchored.
5) Prefer simpler provider-safe syntax over clever but brittle syntax.

Do not output prose. Output only valid JSON.
Be deterministic.
```

### Drop-in replacement: `OPENALEX_QUERY_BUILDER_USER_PROMPT_TEMPLATE`

```text
PIPELINE CONTEXT:
You generate provider-safe OpenAlex /works query objects for a two-lane retrieval pipeline.
These queries only collect candidates, but you must still prevent generic-method drift now.

CHAPTER_TITLE:
{{chapter_title}}

CHAPTER_SPEC_TEXT:
{{chapter_spec_text}}

INPUT_QUERY_PLAN_JSON:
{{query_plan_json}}

BUDGET:
max_queries = {{max_queries}}
languages = ["en","de"]

GOAL HIERARCHY:
- authority: canonical/high-impact literature that is still clearly about the chapter object
- match: strongest topical fit for the chapter, including strong partial matches on required facets
- do not spend budget on queries that are mainly about a generic method with weak chapter-object anchoring

OPENALEX OUTPUT JSON SCHEMA:
{
  "openalex_queries": [
    {
      "intent": "authority" | "match",
      "language": "en" | "de",
      "search_field": "default.search" | "title_and_abstract.search",
      "query_string": "BOOLEAN QUERY STRING",
      "filters": "comma,separated,filters",
      "sort": "cited_by_count:desc" | "relevance_score:desc" | null,
      "per_page": 200,
      "notes": "<= 18 words"
    }
  ]
}

IMPORTANT IMPLEMENTATION NOTE:
The current pipeline will place these query strings into OpenAlex search fields and validates them conservatively.
So for THIS task:
- use readable boolean query strings
- use quotes for multiword phrases that should stay together
- do NOT use * ? ~ here
- AND/OR/NOT must be uppercase
- avoid slash tokens X/Y; rewrite as (X OR Y)

MANDATORY RETRIEVAL RULES:
1) Every query MUST include at least one term from primary_context_anchors[language].
2) Every MATCH query must include:
   - one core object/corpus/domain anchor
   - and one construct/data/method group that is meaningful only inside that object
3) At least 60% of MATCH queries must include a non-method phrase that names the chapter object, data source, or domain context.
4) Pure method-only queries are NOT allowed.
5) Authority queries may be broader, but they must still remain about the chapter object; citations alone do not justify breadth.
6) Use exclusions only for true wrong-sense confounders. If exclusions are weak or messy, omit them.

FILTER POLICY:
- filters MUST include: is_paratext:false, is_retracted:false, language:<en|de>
- use only safe keys already supported by the implementation:
  language,is_paratext,is_retracted,type,from_publication_date,to_publication_date,
  primary_location.source.is_core,locations.source.is_core

search_field policy:
- match -> "title_and_abstract.search"
- authority -> "title_and_abstract.search" for most queries, plus optionally 1 booster per language using "default.search"

QUERY FAMILIES TO COVER:
- authority core EN + DE or bilingual fallback
- optional authority boosters EN + DE when both are lexically plausible
- global object+construct match EN plus at least one DE or bilingual core query
- object+facet queries for weight>=4 facets, with DE used selectively
- if budget remains, prefer object+data/proxy or object+limitations expansions before generic method expansions

LANGUAGE POLICY:
- do not mirror every English query into German mechanically
- if the German rendering becomes too literal, niche, or implementation-like, prefer one bilingual fallback over a dead DE clone
- keep DE coverage for queries whose object phrase and facet phrase are both likely to appear in German titles/abstracts

QUERY SHAPES:
- CORE: ("core object" OR variants) AND ("construct" OR variants)
- OBJECT+DATA: ("core object" OR variants) AND ("data" OR "proxy" OR "measurement" variants)
- OBJECT+METHOD: ("core object" OR variants) AND ("specific method" OR close variants)
- AUTHORITY: ("core object" OR variants) AND ("field-defining construct/data phrase" OR variants)

BUDGETING:
- authority: 2 queries (EN + DE or bilingual fallback) + up to 2 boosters
- match: global match EN + at least one DE or bilingual core query
- match: for each facet with weight>=4 -> 1 EN query, plus DE only when the phrasing is likely to survive title/abstract search
- if budget remains -> extra object-anchored expansions only

SELF-CHECK:
- Would this query still retrieve many generic method surveys if the object phrase were removed? If yes, strengthen it.
- Does every query include an object anchor, not only a method term? If not, fix it.
- Are exclusions atomic and provider-safe? If not, omit them.
- Are boolean operators uppercase and filters safe? If not, fix them.

Return ONLY JSON.
```

### What I would tune further

- Query-family weights:
  - use more budget on object+construct and object+data/proxy queries before method-heavy expansions.
- Authority boosters:
  - keep them, but only after the core authority queries are strongly chapter-anchored.
- Query diversity:
  - require diversity over object phrase combinations, not only over facets.
- Search surface:
  - the generated-query replay suggests not every authority query should default to top-level `search`; later test one tight `title_and_abstract.search` authority core plus at most one broad `search` booster.
- Exact phrase conjunctions:
  - avoid `"phrase" AND "phrase"` unless the pair is realistically co-occurring; the live probe showed this can collapse to zero quickly.
- Empty-query interpretation:
  - treat `~30-50%` empty OpenAlex queries as tolerable only if the non-empty queries are the right ones and core families remain alive.
- German fallback:
  - keep bilingual fallback available for failed DE authority families, but do not assume it will rescue DE method/proxy match families.
- Generic method-facet drift:
  - sampling, proxy-design, and reporting families still need stronger object conditioning even when they produce nonzero counts.

### Optional stronger upgrades for later

1. Stop asking the model for fully assembled OpenAlex boolean strings.
2. Ask it for semantic groups instead:
   - `object_terms`
   - `construct_terms`
   - `data_or_proxy_terms`
   - `method_terms`
   - `exclusions`
   - `intent`
   - `language`
3. Assemble the final provider query deterministically in code.
4. Revisit the OpenAlex stage against the current provider docs:
   - current docs favor `search`
   - `.search` filters are legacy
   - advanced search features should be code-gated, not prompt-guessed

## Phase C.2 — Semantic Scholar Bulk Query Builder

### Diagnosis

Main issues:
- current prompt allows a lot of syntax complexity
- retries are repeatedly triggered by negative-term formatting
- the builder is doing both semantic planning and brittle syntax assembly
- it still needs stronger control against generic method drift
- it is still too easy to over-constrain title/abstract matching with literal bilingual mirroring

### Post-update S2 yield findings

This is the clearest practical issue from the cache review.

Across recent runs:
- `25e6243ac55a5904fb1fcdfe`: `14/33` S2 queries were empty
- `0eb47e270f7586fd6f09795c`: `7/33` S2 queries were empty
- `4af2666be828e5054ccf4d31`: `5/35` S2 queries were empty

The strongest local pattern is not random provider noise:
- in `25e6243ac55a5904fb1fcdfe`, every German S2 query returned `0` records
- in `0eb47e270f7586fd6f09795c`, several of those same German slots returned substantial counts such as `757`, `144`, and `553`

Interpretation from the cache comparison plus current S2 docs:
- S2 bulk keyword search matches titles and abstracts, so term choice must be lexically plausible in titles/abstracts
- the FAQ also indicates S2 generally does not expand abbreviations/acronyms in search
- the current failure mode is therefore over-constrained lexical design, not just insufficient breadth

Practical conclusion:
- do not try to drive S2 with a strict EN/DE symmetry rule
- English and bilingual fallback queries should carry most of the recall burden
- German S2 queries should be emitted selectively, only when both the object phrase and the facet phrase are likely to exist in real German titles/abstracts

### Live API probe findings

Direct probe results on 2026-03-08 sharpened the picture further:
- anonymous `GET /graph/v1/paper/search/bulk` worked repeatedly
- anonymous `GET /graph/v1/paper/search` returned `429`
- direct English object-first bulk query returned `33` results
- abstract-anchor bulk query from the degraded run returned `4`
- bilingual fallback returned `23`
- German-only queries remained sparse:
  - poor-run German query: `0`
  - healthier-run German query: `2`
  - simplified German direct query: `0`
  - German object + English facet query: `2`
- adding a third required group was expensive:
  - two required groups: `27`
  - three required groups: `3`
- the bulk endpoint did not behave like a trustworthy server-side limiter:
  - the same broad query with `limit=1`, `10`, and `100` still returned roughly `935-1000` items
- some edge-case syntax was unstable:
  - longer negative phrase returned `500` once and `200` later
  - acronym-heavy method group returned `200` once and `500` later

Interpretation:
- the English/bilingual backbone is even more important than the cache review suggested
- the third required group should not be the default strong form
- bulk `limit` should not be trusted as a tight cap
- provider acceptance for acronym-heavy or longer-negative edge cases is not stable enough to rely on casually

### Generated-query replay findings

I replayed the actual generated S2 query set from run `17d29aaee1fecc8cf1a34025` against live Semantic Scholar.

High-signal results:
- `17` queries total
- bulk zero-query rate: `11.8%`
- both zero-yield queries were German
- EN bulk zero-query rate: `0.0%`
- DE bulk zero-query rate: `100.0%`
- median bulk total: `235`
- median no-negative/current ratio: `1.01`

Most important interpretation:
- the main S2 problem in this replay is not negatives
- it is broad-but-generic method/query families plus continued German collapse

Examples:
- `Evaluation metrics and error analysis for automated classifiers on reviews`
  - bulk total: `2,871`
  - top results were generic sentiment-analysis / classifier papers
- `Workflows for scalable text analysis on large review corpora`
  - bulk total: `2,488`
  - top results were largely generic app-review sentiment-analysis papers
- `Guidance on reporting, documentation and reproducibility for review-based studies`
  - bulk total: `155`
  - top results were often generic and not clearly about review-based measurement
- narrower proxy/validation families were much smaller:
  - `Operationalizing theoretical constructs as text-based proxies in reviews`: `42`
  - `Validation and plausibilization procedures for proxies extracted from text`: `98`
  - `Best practices for annotation and gold-standard creation for review corpora`: `69`

Negative-ablation result:
- removing negatives from the negative-bearing S2 queries changed totals only marginally in this topic
- the strongest cases were still only around `1.04x` to `1.05x`

Regular-search comparison:
- bulk behaved like the meaningful yield surface here
- regular `/paper/search` was much less stable:
  - many totals at `0`
  - several `429`s during replay
  - one later `500` during slower reruns
- even where regular search succeeded, totals were often far below bulk totals for the same query

German replay behavior:
- DE authority current: `0`
- DE authority bilingual rescue: `343`
- DE proxy-match current: `0`
- DE proxy-match bilingual rescue: `0`
- DE proxy-match with English facet terms: `0`

Interpretation:
- bilingual fallback can rescue broad authority-like German failures
- it does not rescue all DE match families
- for this topic, the dead DE proxy/method query is a facet-lexicality problem, not just a missing-English-fallback problem

### Drop-in replacement: `S2_BULK_QUERY_BUILDER_SYSTEM_PROMPT`

```text
You generate Semantic Scholar Academic Graph bulk search queries for scientific literature retrieval.
Reliability and chapter anchoring are more important than clever syntax.

Priority order:
1) Keep every query inside the chapter object, corpus, or domain.
2) Cover the main constructs, data/proxy constraints, and required facets.
3) Use title/abstract-plausible wording and simple, provider-safe syntax first.
4) Use advanced syntax only when it clearly solves a recall problem.

Never mix context anchors and facet terms in the same OR-group.
Keep every query interpretable by a human reviewer.
Output ONLY valid JSON. No prose.
Be deterministic.
```

### Drop-in replacement: `S2_BULK_QUERY_BUILDER_USER_PROMPT_TEMPLATE`

```text
CHAPTER_TITLE:
{{chapter_title}}

CHAPTER_SPEC_TEXT:
{{chapter_spec_text}}

INPUT_QUERY_PLAN_JSON:
{{query_plan_json}}

BUDGET:
max_queries = {{max_queries}}
languages = ["en","de"]

OUTPUT JSON:
{
  "s2_bulk_queries": [
    {
      "intent": "authority" | "match",
      "language": "en" | "de",
      "query_string": "QUERY STRING",
      "notes": "<= 18 words"
    }
  ]
}

GOAL HIERARCHY:
- authority: broad but still chapter-anchored
- match: strongest chapter fit with good recall
- do not spend budget on generic method queries that are weakly tied to the chapter object

PROVIDER REALITY:
- Semantic Scholar bulk keyword search matches titles and abstracts, so use phrases likely to appear in titles/abstracts.
- Prefer full lexical forms over acronym-only shorthand.
- Do not mirror every English query into German mechanically.

PREFERRED SYNTAX SUBSET:
- required groups: +( ... )
- quoted phrases for multiword terms
- OR groups only with |
- atomic negatives only: -term or -"two words"

ADVANCED SYNTAX POLICY:
- wildcard, fuzzy, and proximity are allowed only if they clearly improve recall for this chapter
- if simple quoted phrases and OR-groups are sufficient, prefer the simpler form

ABSOLUTE SEPARATION RULE:
A) PRIMARY_CONTEXT terms and FACET terms MUST NEVER be mixed in the same OR-group.
B) PRIMARY_CONTEXT_OR_GROUP must be built ONLY from primary_context_anchors for that language.
C) FACET_OR_GROUP must be built ONLY from facet canonical_terms + neighbor_terms, plus safe bilingual variants.
D) If a term is not explicitly an anchor, it does not belong in PRIMARY_CONTEXT_OR_GROUP.

MANDATORY MATCH STRUCTURE:
MATCH queries MUST have:
  +(PRIMARY_CONTEXT_OR_GROUP) +(FACET_OR_GROUP) [optional SECOND_CONTEXT_OR_GROUP] [optional NEGATIVE]

DEFAULT STRONG MATCH FORM:
  +(PRIMARY_CONTEXT_OR_GROUP) +(FACET_OR_GROUP) [optional NEGATIVE]

OPTIONAL DRIFT-REDUCING FORM:
  +(PRIMARY_CONTEXT_OR_GROUP) +(SECOND_CONTEXT_OR_GROUP) +(FACET_OR_GROUP) [optional NEGATIVE]

PRIMARY_CONTEXT_OR_GROUP:
- 2-5 terms
- use terms that name the chapter object/corpus/domain, not only methods
- when available, include at least 2 distinct object/context anchors
- prefer direct object phrases such as `online reviews`, `user reviews`, `customer reviews`, `review platforms`
- avoid abstract substitutes such as `user generated content` unless paired with a direct object phrase

SECOND_CONTEXT_OR_GROUP:
- optional but recommended if it reduces drift
- may use anchors or global canonical terms that are still true context anchors
- do NOT place generic facet/method terms here

FACET_OR_GROUP:
- 5-10 terms
- only target-facet canonical_terms + neighbor_terms
- bilingual variants are allowed inside this group when they improve recall
- front-load standard literature wording before niche or implementation-like wording
- avoid filling the whole group with rare translated compounds that are unlikely to appear in titles/abstracts

ANTI-DRIFT RULES:
- Pure method-only queries are NOT allowed.
- If a query could retrieve broad NLP/LLM/economics/method papers with no chapter object, strengthen it.
- Ambiguous standalone tokens must be rewritten as more specific phrases or paired with disambiguating terms.

NEGATIVE RULES:
- default to 0 or 1 negatives
- use at most 2 negatives unless there is a very clear wrong-sense problem
- negatives must be atomic and provider-safe
- if a negative is messy, omit it

AUTHORITY POLICY:
Authority queries are broader but MUST remain chapter-anchored:
  +(PRIMARY_CONTEXT_OR_GROUP) +(HIGH_LEVEL_OR_GROUP) [optional NEGATIVE]

HIGH_LEVEL_OR_GROUP:
- use topic-specific construct/data/proxy terms
- avoid generic standalone method or field terms
- keep authority queries interpretable and obviously on-topic
- avoid acronym-only terms unless the full phrase is also present

ALWAYS INCLUDE:
- authority EN
- authority bilingual fallback
- global match EN
- at least 1 DE or bilingual query that uses clearly standard German academic phrasing when such phrasing exists
- use DE facet queries selectively; do not force EN/DE parity for every facet
- match EN for each weight>=4 facet while budget permits
- spend remaining budget first on object+data/proxy and object+limitations families before DE clones or extra method families

SELF-CHECK:
- PRIMARY_CONTEXT_OR_GROUP contains only true anchors
- FACET_OR_GROUP contains only facet terms
- every | is inside parentheses
- MATCH has at least two required groups
- negatives are atomic
- if advanced syntax is unnecessary, simplify it
- if the German version is a literal translation that is unlikely to appear in titles/abstracts, replace it with a bilingual or English fallback
- if the query depends on acronym-only shorthand, rewrite it with full terms

Return ONLY JSON: { "s2_bulk_queries": [ ... ] }
```

### What I would tune further

- Negative budget:
  - keep the syntax guard, but the replay suggests negatives are not the main recall lever on this topic.
- Required-group count:
  - use the third required group only when it clearly reduces ambiguity without starving recall.
- Language strategy:
  - do not optimize for symmetric EN/DE coverage; optimize for non-empty, chapter-faithful query families, and treat DE authority fallback differently from DE match families.
- Lexicality:
  - for S2, choose phrases that are likely to appear verbatim in titles/abstracts; the replay suggests workflow/evaluation/reproducibility facet groups are still too generic and need stronger object conditioning.
- Advanced syntax:
  - only add wildcard/fuzzy/proximity after you have concrete recall failures that simpler phrasing cannot solve.
- Empty-query target:
  - some empty S2 queries are fine, but I would aim for a materially lower S2 empty rate than OpenAlex and treat near-total collapse of one language family as a hard regression.
- Endpoint choice:
  - for future Phase C benchmarking, treat bulk as the primary S2 truth surface; regular search is too unstable and too semantically different to be a hard comparison baseline.

### Optional stronger upgrades for later

Same principle as OpenAlex:
- let the model choose semantic groups
- let code assemble the final S2 query

This is especially valuable here because the failure mode is frequently syntax hygiene, not semantic choice.

## Phase I — Rerank Prompt

### Diagnosis

Main issues:
- rerank is too willing to score generic method papers as useful
- with-abstract tasks almost never admit uncertainty
- prompt lacks a strong enough chapter-target summary
- prompt does not penalize missing chapter-object evidence hard enough

This matters because the rerank stage is deciding the top segment the user will actually see.

### Drop-in replacement: `SYSTEM_PROMPT`

```text
You are judging whether a scientific source is genuinely useful for a specific chapter in an academic paper.
Use ONLY the provided candidate metadata and evidence excerpts.

This is a chapter-fit ranking task, not a generic paper-quality task.

Priority order:
1) Is the candidate clearly about the chapter object, corpus, or domain?
2) Does the evidence support one or more required facets?
3) Is the support direct and concrete rather than merely method-adjacent?
4) Only then consider broader authority or scholarly importance.

Rules:
- Do NOT infer content that is not supported by the excerpts/metadata.
- Generic method surveys, benchmark papers, and broad field overviews should score conservatively unless the evidence clearly ties them to the chapter target.
- If the evidence does not support the chapter object or is too thin to judge, set insufficient_info=true and keep the score conservative.
- For pool=="without_abstract", high scores should be rare and require unusually strong metadata evidence.

Output ONLY valid JSON matching the provided schema. No Markdown. No extra keys.
```

### Recommended replacement for `_build_user_prompt(...)`

The current function should pass more chapter-target context. Below is the recommended prompt body.

```text
CHAPTER_TITLE:
{chapter_title}

CHAPTER_TARGET_SUMMARY:
{topic_summary_en}

MUST_HAVE_CONTEXT:
{top_object_anchors_and_core_context_terms_json}

LANE:
{lane}

POOL:
{pool}

LANE_GUIDANCE:
{lane_guidance}

FACETS_REQUIRED (weight>=4):
{required_facets_json}

ALL_FACET_IDS:
{all_facet_ids_json}

CANDIDATE_METADATA:
title={title}
year={year}
venue={venue}
citations={citations}
url={url}
authors={authors_json}
abstract_present={abstract_present}

CANDIDATE_EVIDENCE (coverage_tags):
{coverage_tags_json}

SCORING RUBRIC:
- 90-100: directly about the chapter target and strongly supports multiple required facets
- 70-89: strong chapter-specific support, but not fully comprehensive
- 40-69: plausible supporting source or method paper with some chapter relevance, but object fit is partial or thin
- 0-39: generic, weakly supported, wrong-level, wrong-sense, or too uncertain

INSTRUCTIONS:
- Score usefulness for this chapter, not generic importance.
- A high score requires evidence that the paper is about the chapter target, not merely about an adjacent method.
- covered_facets: choose ONLY facets explicitly supported by the excerpts.
- If the candidate lacks clear chapter-object evidence, it should usually score below 60 in the match lane.
- In the authority lane, broader foundational work may score well only if it is clearly foundational for this chapter's object/construct.
- If the evidence is generic, metadata-only, or ambiguous, set insufficient_info=true.
- For pool=="without_abstract", scores above 70 should be rare.
- In rationale, mention the exact evidence used and the main gap or limitation if any.
```

### What I would tune further

- Add explicit negative examples:
  - generic survey paper that should score low
  - chapter-specific empirical paper that should score higher
- Use a stronger rerank model if cost is irrelevant.
- If top-40 quality is the primary target, strongly consider pairwise rerank for the top slice.

### Optional stronger upgrade for later

Best future algorithm if you are willing to change the implementation:
- pointwise prefilter to top 20-40
- pairwise rerank top 15-30

Why:
- pairwise ranking prompting is better supported in the literature than naive pointwise 0..100 scoring
- it directly addresses the "generic prestigious methods paper vs chapter-specific paper" choice

## Phase F — Embeddings and text packaging

No prompt lives here, but this phase affects prompt performance downstream.

### Main issues

- `facet_embed_text(...)` is too minimal
- `candidate_meta_view(...)` is functional but thin
- semantic similarity can over-weight generic methods because the chapter object is underrepresented in the embedding text

### Recommendations

1. Create a richer chapter-target or facet-target text for embeddings.
2. Include object/corpus/domain context explicitly in facet text.
3. Include more candidate evidence in metadata embeddings when available:
   - title
   - abstract snippet
   - venue
   - year
   - source provenance
   - language
   - key metadata fields
4. If cost truly does not matter, use the stronger embedding model available in your stack.
5. Consider a pseudo-document or pseudo-abstract representation inspired by Query2doc / HyDE.

### Concrete local suggestion

Current facet text:
- essentially `facet narrative + canonical terms`

Better facet text:
- chapter object
- facet goal
- positive terms
- exclusions / ambiguity note when needed

That should make generic method similarity less dominant.

## Phase H — Coverage tags

No prompt lives here either, but this stage currently amplifies false positives.

### Main issues

- with abstracts:
  - every paper gets all facets above threshold OR the top 2 facets regardless
- without abstracts:
  - every paper gets the top 1 facet regardless

This makes weak matches look well-supported.

### Recommendations

1. Stop auto-adding top-N facets when the scores are weak.
2. Require a minimum margin or threshold before a facet becomes a coverage tag.
3. Distinguish:
   - strong evidence
   - weak heuristic evidence
4. Consider passing only the top truly supported tags to rerank, not every borderline one.

This change is likely to improve rerank quality even without touching the rerank prompt.

## Other non-prompt pipeline findings

### 1. OpenAlex contract drift

The current OpenAlex prompt/validator/code contract is partly out of sync with current provider docs:
- provider docs emphasize `search`
- `.search` filters are legacy
- current docs support richer search features than the current code allows

This does not force an immediate code rewrite, but it should be treated as technical debt that affects retrieval quality.

### 2. Deterministic validation is too syntactic

Current validation checks:
- shape
- counts
- hygiene
- operator casing
- some anchor presence

Missing validation:
- object retention
- method-drift detection
- chapter-specificity checks

### 3. Rerank model strength

Current code uses `gpt-5-nano` for rerank.

If your stated goal is top-40 quality and runtime/cost do not matter, this is one of the clearest non-prompt levers:
- use a stronger rerank model
- especially if you keep pointwise scoring

### 4. Embedding model strength

Current code uses `text-embedding-3-small`.

If quality dominates cost:
- try the stronger embedding model in the same family
- evaluate it on recall and top-k quality, not just intuition

### 5. Semantic Scholar bulk `limit` semantics look unreliable

In the live probe on 2026-03-08, the same broad bulk query returned roughly `935-1000` items even when `limit` was set to `1`, `10`, or `100`.

Implication:
- any local logic that assumes S2 bulk `limit` tightly constrains per-page result size is relying on behavior I did not observe live
- this is not a prompt issue, but it matters for retrieval budgeting, runtime expectations, and any interpretation of query yield

## Benchmarking framework

### What to benchmark

You have two goals and they should be measured separately:
- recall / coverage:
  - do we retrieve the papers that should be in the candidate set?
- ranking quality:
  - do the best papers land near the top?

### Recommended judged-pool workflow

1. Choose 5-10 representative chapter specs.
2. For each chapter, pool candidates from:
   - current prompts
   - revised planner only
   - revised OpenAlex builder only
   - revised S2 builder only
   - revised rerank only
   - optionally OpenAlex-only and S2-only slices
3. Deduplicate the pool.
4. Assign graded labels:
   - `A`: directly useful / high relevance
   - `B`: useful support / partial match
   - `C`: tangential
   - `D`: irrelevant
5. Add failure tags:
   - missing chapter object
   - generic method drift
   - wrong-sense ambiguity
   - metadata-only uncertainty
   - ranking inversion

### Metrics to report

Minimum set:
- `Recall@40`, `Recall@100`, `Recall@200` on the judged pool
- `Core-paper recall@40`
- `nDCG@10`, `nDCG@20`, `nDCG@40`
- `Precision@10`, `Precision@20`
- `bpref` for incomplete pooled judgments
- screening burden:
  - `NNR` / `NNS`
- required-facet coverage in top 20 / top 40
- object-retention rate in top 40
- provider/query-yield diagnostics:
  - non-empty query share by provider and language
  - median records per query family
  - zero-result cluster rate for core families

### Cheap proxy checks before full reruns

Planner-level:
- do anchors preserve the chapter object?
- do weight>=4 facets over-index on generic methods?

Query-builder level:
- what share of queries are object+construct vs object+method vs method-heavy?
- how many query families are clearly chapter-anchored?
- what is the non-empty share by provider, language, and query family?
- are empty queries concentrated in deliberate long-tail probes or in core families?

Rerank level:
- in a small judged subset, do generic method surveys lose to chapter-specific papers?

### Logging and reproducibility

Following PRISMA-S style discipline, keep for every benchmark run:
- prompt version ID
- exact provider query strings
- provider and date
- filters and exclusions
- model versions
- dedup logic version
- judged-pool version

Your current artifact structure is already close to this; formalize it and it becomes a strong evaluation asset.

## Suggested implementation order later

If you later start editing code, I would do it in this order:

1. Planner weighting and exclusion tuning on top of the already-improved Phase B schema.
2. S2 builder rewrite with provider-specific language strategy and title/abstract lexicality rules.
3. Rerank prompt rewrite + richer chapter-target context.
4. Coverage-tag conservatism fix.
5. OpenAlex builder rewrite.
6. Benchmark harness and judged pool, including query-yield diagnostics.
7. Semantic-group query assembly in code.
8. Pairwise rerank experiments.

## Final take

The current pipeline is already strong. The newest Phase B update fixed the most important planner failure. The next big gains are likely to come from:
- making the high-priority facet budget less method-heavy
- making S2 query generation provider-specific instead of symmetric across languages
- measuring both retrieval quality and query-yield health with a judged benchmark instead of relying on run-by-run impressions

The central prompt lesson is simple:
- generic academic wording is often the enemy of retrieval quality
- concrete chapter-specific wording is the asset

If you implement only one idea from this report, make it this:
- do not let the planner optimize away the chapter's true object

Everything else gets easier once that is fixed.
