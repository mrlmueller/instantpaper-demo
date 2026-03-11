# Research Notes — Retrieval And Ranking

Status: active working notes.

## Provider-doc findings

### OpenAlex

From the current OpenAlex docs:
- the top-level `search` parameter is the preferred free-text search surface
- `.search` filters are documented as deprecated / legacy
- OpenAlex search supports more than plain boolean:
  - exact search
  - wildcard
  - fuzziness
  - proximity
  - stemming / stop-word aware behavior

Why this matters locally:
- current code still normalizes query objects into `default.search` or `title_and_abstract.search`
- current OpenAlex prompt explicitly forbids `* ? ~`
- current validator also rejects `* ? ~`

Interpretation:
- part of the OpenAlex stage is now coupled to outdated assumptions about provider behavior
- even if we keep the current code for now, the report should call out the mismatch clearly

Practical recommendation:
- near term:
  - improve prompts inside the current code constraints
- medium term:
  - move from filter-based legacy search fields to the current provider contract
  - allow selected advanced syntax only after deterministic validation is updated

### Semantic Scholar bulk search

Official Semantic Scholar material shows an important distinction:
- the public website search is limited and does not support boolean logic in the same way
- the Academic Graph bulk search tutorial supports structured keyword syntax:
  - `+` required terms
  - quoted phrases
  - `|` inside parentheses for OR groups
  - `-` negatives
  - wildcard support in the API search context
- the tutorial states that keyword search terms are matched against title and abstract
- the FAQ indicates search generally does not expand abbreviations/acronyms

Why this matters locally:
- the pipeline is correctly targeting bulk API search, not the website search
- however, the current builder prompt encourages complex syntax that the model occasionally formats badly
- title/abstract matching means term choice must be lexically plausible, not merely conceptually related
- acronym-heavy or shorthand-heavy queries are riskier than they look

Practical recommendation:
- keep the S2 prompt syntax surface simpler than the API maximum
- use advanced operators only when they solve a real recall problem
- move as much syntax assembly as possible into deterministic code
- do not mirror every English query into German mechanically
- use English and bilingual fallback queries as the main recall backbone, and spend German-query budget only on phrases likely to appear in real titles/abstracts

## Local yield audit

See also:
- `PHASE_C_API_PROBE_FINDINGS.md` for live-provider probe results from 2026-03-08
- `PHASE_C_QUERY_REPLAY_FINDINGS.md` for live replay results on the actual generated Phase C queries

### Empty-query rates across recent runs

Cross-run cache counts:
- `25e6243ac55a5904fb1fcdfe`: OpenAlex `15/40` empty, S2 `14/33` empty
- `0eb47e270f7586fd6f09795c`: OpenAlex `19/40` empty, S2 `7/33` empty
- `4af2666be828e5054ccf4d31`: OpenAlex `21/42` empty, S2 `5/35` empty

Interpretation:
- a non-trivial empty-query rate is normal for recall-oriented search
- the more important diagnostic is whether empties are distributed across deliberate long-tail probes or concentrated in core families

### S2 language-family collapse is the practical failure mode

Strongest local pattern:
- in `25e6243ac55a5904fb1fcdfe`, every German S2 query returned `0`
- in `0eb47e270f7586fd6f09795c`, the same German slots were often viable:
  - `query_i=5`: `757`
  - `query_i=9`: `144`
  - `query_i=13`: `553`
  - `query_i=25`: `4`
  - `query_i=31`: `31`
  - `query_i=33`: `1`

Interpretation:
- S2 is not just randomly sparse on this domain
- the current prompt/query design can either starve or unlock an entire language slice
- better object anchors correlate with healthier German S2 yields

### Query-design implications from the yield audit

Practical recommendations:
- do not force EN/DE parity for every S2 facet query
- keep one broad object-preserving English authority query and one bilingual fallback alive even when narrow facet queries fail
- prefer direct object phrases such as `online reviews`, `user reviews`, `customer reviews` over abstract substitutes such as `user generated content`
- avoid title/abstract-unlikely phrases, implementation jargon, and literal translated compounds in S2 query groups
- avoid acronym-only anchors in S2 unless the full lexical form is also present
- use the third required group only when it clearly reduces ambiguity without starving recall

### Live provider probe implications

Additional findings from the direct Phase C API probe:
- OpenAlex top-level `search` is far broader than `title_and_abstract.search` for the same direct object phrase
- OpenAlex wildcard, fuzzy, and proximity syntax worked live
- S2 bulk works anonymously, while S2 standard search returned `429` anonymously
- S2 bulk `limit` did not behave like a trustworthy page-size cap in repeated tests

Future-self note:
- keep the report's prompt advice aligned with both the docs and the live probe, not just one or the other

### Generated-query replay implications

The replay of run `17d29aaee1fecc8cf1a34025` changes the practical diagnosis in an important way.

High-signal findings:
- OpenAlex current zero-query rate on the generated set was `26.9%`, but the stronger problem was not just zeros:
  - some broad authority/method families had large counts and generic top titles
- OpenAlex EN looked healthy on raw yield:
  - zero-rate `0.0%`
  - median count `536`
- OpenAlex DE still largely collapsed:
  - zero-rate `87.5%`
- OpenAlex alternate-surface lift was often enormous:
  - median alternate/current ratio `20.06`
  - but large lift did not automatically mean better chapter fit
- S2 bulk zero-rate was only `11.8%`
  - both zero-yield queries were German
- S2 negatives barely moved totals in this topic:
  - median no-negative/current ratio `1.01`
- S2 regular `/paper/search` was not a stable comparison surface:
  - many totals at `0`
  - several `429`s
  - one later `500`
  - often far below bulk totals for the same query

Interpretation:
- the next Phase C problem to solve is not simply "too many empty queries"
- it is "some query families are alive but too generic"

Concrete family-level risks from the replay:
- OpenAlex:
  - authority queries on broad `search` can drift badly
  - reporting / reproducibility / proxy-design families can still drift even on `title_and_abstract.search`
- S2:
  - workflow / evaluation / reproducibility families can return large totals with weakly chapter-specific top titles

Practical recommendation:
- OpenAlex:
  - test a tighter authority pattern later:
    - one core `title_and_abstract.search` authority query
    - at most one broad `search` booster when justified
- S2:
  - spend more adaptation effort on facet lexicality and family prioritization than on negatives
  - use bulk search as the primary benchmark surface
- German:
  - use bilingual fallback mainly for authority-style recovery
  - keep DE match families highly selective, and skip them when object+facet phrasing is implausible

## Retrieval and query-expansion research

### Query2doc

Core idea:
- use an LLM to generate a pseudo-document from the query
- append or derive expansion terms from that richer text
- retrieval improves because the query becomes semantically denser

Pipeline implication:
- the planner should not only emit short anchors and term lists
- it should also preserve enough object-conditioned detail that later stages can generate richer expansions
- a chapter-level pseudo-abstract could be useful for:
  - embedding text for the chapter target
  - query-builder term selection
  - later evaluation against chapter fit

### HyDE

Core idea:
- generate a hypothetical relevant document
- embed that hypothetical text
- use it as a retrieval representation

Pipeline implication:
- current facet embedding text is very lean
- a richer hypothetical relevant-paper summary per chapter or per high-weight facet may improve semantic retrieval and chunk matching

Future-self note:
- this is especially relevant for Phase F
- if you stay with embeddings, richer facet text is likely a higher-value change than endless synonym tweaking

## Phase F empirical probe

Probe date:
- 2026-03-09

Runs tested:
- `ed2e3d3304d5ed9587592f4d` (online reviews / proxy-operationalization chapter)
- `ca79147de41f8edbfb47c9e5` (late-antique / Western Roman Empire hard-topic chapter)

Cost:
- full known probe spend stayed under the `$1` cap at about `$0.85`

Main empirical findings:
- `text-embedding-3-large` did not materially outperform `text-embedding-3-small`
- metadata-only candidate embeddings are too weak as a main scorer
- richer chapter-target query text outperformed pure facet-only matching
- a staged shortlist + abstract-chunk rerank was the best cross-topic compromise
- light diversity control helped reduce redundancy in the final top 20

Cross-run averages from the probe:
- `summary_doc_small`:
  - `top20_title_core_hit_rate = 0.525`
  - `top20_abstract_core_hit_rate = 0.825`
  - but it still drifted toward broad contextual literature on the hard historical chapter
- `staged_small`:
  - `top20_title_core_hit_rate = 0.525`
  - `top20_abstract_core_hit_rate = 0.825`
  - `top20_mean_pairwise_similarity = 0.515`
  - best overall balance after qualitative inspection
- `hybrid_small`:
  - `top20_title_core_hit_rate = 0.475`
  - `top20_abstract_core_hit_rate = 0.750`
- `hybrid_large`:
  - `top20_title_core_hit_rate = 0.350`
  - `top20_abstract_core_hit_rate = 0.625`

Interpretation:
- packaging and staging matter more than switching from `small` to `large`
- Phase F should focus on:
  - richer chapter-target text
  - good candidate text packaging
  - chunk rerank
  - dedup / hygiene

Future-self note:
- this materially weakens the earlier speculative recommendation to “just try the stronger embedding model”
- the stronger model is not the first lever to pull here

## Phase F design probe

Second-pass probe date:
- 2026-03-09

What changed from the first probe:
- tested implementation-level design choices rather than only model choice
- focused on:
  - deterministic chapter-target query text
  - candidate text length
  - richer vs leaner candidate packaging
  - HyDE-style query expansion
  - staged rerank plus hygiene

Key findings:
- deterministic `chapter_target_doc` is the right new default query representation
- `abstract[:800]` is the best current default candidate text budget
- HyDE is interesting for sparse chapters but not stable enough for default use
- hygiene should be mandatory
- staged rerank remains the strongest overall design

Implementation note:
- a concrete build plan now exists in `PHASE_F_IMPLEMENTATION_PLAN.md`

### Promptagator

Core idea:
- LLMs can create retrieval-oriented synthetic query data that improves retrievers

Pipeline implication:
- the planner/query-builder should be treated as retrieval-training-style components, not just generic text generation
- prompts should be optimized for:
  - diversity of useful query formulations
  - preservation of relevance constraints
  - avoiding collapse into generic academic wording

## Reranking research

### RankGPT

Main relevance for this project:
- LLMs can rerank effectively when the comparison task is phrased well
- rank quality depends heavily on the prompt format and comparison setup

Pipeline implication:
- the current pointwise 0..100 scoring prompt is a reasonable baseline
- but it likely leaves performance on the table, especially for top-40 ordering

### Pairwise ranking prompting

Important result direction:
- pairwise prompting tends to outperform naive pointwise scoring
- it provides a more stable way to compare two plausible candidates

Pipeline implication:
- if top-40 quality matters most and runtime does not matter, pairwise or small-list reranking should be seriously considered
- even without changing the algorithm yet, the prompt should borrow pairwise ideas:
  - compare chapter fit before generic prestige
  - state explicit tie-break priorities
  - punish chapter-object mismatch hard

### Pointwise-vs-pairwise interpretation for this pipeline

Current local symptom:
- many with-abstract rerank scores are high
- `insufficient_info` is rarely true
- generic method surveys can still float into top ranks

Likely cause:
- pointwise prompts often over-score individually plausible papers
- they do not force the model to make difficult relative choices between a chapter-specific paper and a generic high-prestige methods paper

## Phase I empirical probe

Probe date:
- 2026-03-10

Runs tested:
- `ca79147de41f8edbfb47c9e5`
- `25e6243ac55a5904fb1fcdfe`

Primary result:
- the best overall design was a compact pointwise rubric with `gpt-5-nano`, `reasoning_effort="low"`, followed by a small pairwise refinement on the top `with_abstract` slice

Best variant:
- `rubric_low_pairwise_top6`

Main metrics from the final pass:
- `baseline_current`
  - `mean_ndcg20 = 0.889`
  - `mean_p10 = 0.762`
- `rubric_low`
  - `mean_ndcg20 = 0.904`
  - `mean_p10 = 0.787`
- `rubric_low_pairwise_top6`
  - `mean_ndcg20 = 0.919`
  - `mean_p10 = 0.787`
- `rubric_medium`
  - `mean_ndcg20 = 0.847`
  - `mean_p10 = 0.750`
  - `call_failed_rate = 0.031`

Interpretation:
- a compact rubric is better than the current long single-score prompt
- pairwise refinement on the top slice adds real ranking value
- medium reasoning on nano is a bad default: worse quality, higher cost, and worse operational stability

### Nano operational lesson

Most important implementation finding:
- nano can spend the full output budget on hidden reasoning and emit no JSON at all

This happened repeatedly when:
- prompts were long
- output-token ceilings were too small
- reasoning effort was `medium`

Practical implication:
- keep Phase I prompts compact
- use `reasoning_effort="low"` by default
- use explicit retries and conservative fallback behavior

### Cost profile

Main pointwise pass only:
- `baseline_current`
  - mean output tokens: `1868.4`
  - mean cost per call: `$0.000811`
- `rubric_low`
  - mean output tokens: `586.3`
  - mean cost per call: `$0.000293`
- `rubric_medium`
  - mean output tokens: `2287.8`
  - mean cost per call: `$0.000982`

Interpretation:
- `rubric_low` is both better and much cheaper than the baseline
- `rubric_medium` is more expensive than the baseline and still worse

### Pairwise refinement result

Pairwise top-6 refinement:
- improved the best variant from `0.904` to `0.919` mean `nDCG@20`
- cost per pairwise call stayed low, about `$0.000249`
- no pairwise failures in the final winning variant

Practical implication:
- if runtime does not matter, pairwise top-6 on `with_abstract` is worth keeping
- do not pairwise-rerank `without_abstract`

### Object-gate follow-up

I also tested a stronger prompt-level object gate.

Result:
- it did not beat the compact rubric design
- it introduced new ranking mistakes

Interpretation:
- do not try to solve the remaining authority noise by prompt-only overcorrection
- the remaining authority problem is partly upstream pool quality, not only rerank prompt wording

## Systematic-review search guidance

### PRESS guideline

Useful checklist dimensions:
- translation of the research question
- correct boolean / proximity usage
- subject headings and text words
- spelling, syntax, and line structure
- limits / filters

Pipeline implication:
- deterministic validators should check more than syntax hygiene
- they should also check whether the query set still expresses the chapter question faithfully

Concrete extension for this project:
- add chapter-object retention checks
- add ambiguity checks
- add "method-only drift" checks

### PRISMA-S

Why it matters:
- it is a reporting guideline, but it is also a design discipline
- it pushes exact query logging, database provenance, limits, dates, and dedup transparency

Pipeline implication:
- your run artifacts are already close to a strong search log
- the benchmark/reporting layer should preserve:
  - exact prompt version
  - exact provider queries
  - provider/date
  - filters and exclusions
  - dedup behavior

This will make prompt iteration defensible instead of anecdotal.

## Benchmarking and evaluation

### What to measure separately

Do not collapse everything into one score.

Track at least these:
- recall / coverage:
  - did the pipeline retrieve the papers that should be in consideration?
- ranking quality:
  - are the best papers near the top?
- screening burden:
  - how much junk must be screened to find the useful items?
- chapter-fit faithfulness:
  - does the top set stay inside the chapter object, not merely the method area?

### Metrics that fit this project

Recommended:
- `Recall@K` over a judged pool
- `Core-paper recall@K`
- `nDCG@10`, `nDCG@20`, `nDCG@40` with graded relevance labels
- `Precision@10` / `Precision@20`
- `bpref` when judgments are incomplete
- `NNR` or `NNS` style screening burden
- required-facet coverage in top 20 / top 40
- object-retention rate in top 40
- provider/query-yield diagnostics:
  - non-empty query share by provider and language
  - median records per query family
  - zero-result cluster rate for core families

Avoid using a single blended score as the only gate.

### Judged-pool design

Best practical setup for this repo:

1. Pick 5 to 10 representative chapter specs.
2. Pool candidates from several variants:
   - current prompts
   - revised planner only
   - revised query builders only
   - revised rerank only
   - OpenAlex-only and S2-only slices when useful
3. Deduplicate the pool.
4. Label each paper:
   - `A`: directly useful / highly relevant
   - `B`: useful support / partial match
   - `C`: tangential
   - `D`: irrelevant
5. Also annotate failure type:
   - missed core object
   - generic method paper
   - wrong-sense ambiguity
   - too broad
   - metadata-only uncertainty

Why this matters:
- incomplete judgments are unavoidable
- pooling plus `bpref` is the realistic path

### Fast proxy evals before full runs

The best prompt changes should be filtered early with cheap checks:
- planner:
  - does it preserve the chapter object?
  - do top anchors include the real corpus/object?
  - are high-weight facets dominated by generic methods?
- OpenAlex/S2 query sets:
  - how many queries are object-preserving?
  - how many are method-drift risks?
  - how diverse are anchor fingerprints?
- rerank:
  - on a small judged set, do generic method surveys lose to chapter-specific papers?

## Concrete retrieval ideas suggested by the research

### 1. Add pseudo-document style expansions

Not necessarily as live provider query strings first.
Possible uses:
- richer chapter-target embedding text
- richer high-weight facet embedding text
- generation of secondary canonical terms with better context

### 2. Introduce deterministic query families

Instead of letting the model decide everything freely, force families like:
- object-only core
- object + construct
- object + data/proxy
- object + method
- object + limitations / bias / validity

Future-self note:
- for S2, these families should not be symmetric across languages
- the healthier shape is usually EN core + bilingual fallback + selective DE, not EN/DE duplication for every facet
- object + exclusion-disambiguated

This matches retrieval best practices better than a flat pile of facet-led queries.

### 3. Prefer semantic generation plus deterministic syntax assembly

This is the single most important design lesson for Phase C.

Model should choose:
- anchors
- support terms
- exclusions
- language
- intent

Code should assemble:
- boolean structure
- parentheses
- quoting
- field placement
- provider-safe filters

### 4. Treat rerank as a relative-comparison problem

If later changes are allowed:
- pairwise rerank the top slice
- or do pointwise prefilter then pairwise rerank top 15 to 30

Because:
- top-k quality is where users feel quality most
- pairwise prompting is well supported by the reranking literature

## Notes to future self

- OpenAlex search behavior is a moving target. Re-check docs before changing validators.
- Do not confuse the public Semantic Scholar search limitations with the bulk API syntax surface.
- Benchmarking should reward both recall and ranking. If you only optimize precision at 20, you will miss too many good papers.
- The judged pool is the long-term asset. Build it once and keep prompt iteration honest with it.
