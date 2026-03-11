# Phase C Query Replay Findings

Date: 2026-03-08

Purpose:
- replay the actual Phase C query outputs from run `17d29aaee1fecc8cf1a34025`
- measure live provider yield and top-result behavior for the generated queries themselves
- identify major implementation problems without overfitting too hard to one chapter

Inputs:
- `sources-v2/runs/17d29aaee1fecc8cf1a34025/openalex_queries.json`
- `sources-v2/runs/17d29aaee1fecc8cf1a34025/semanticscholar_queries.json`
- `sources-v2/runs/17d29aaee1fecc8cf1a34025/query_plan.json`

Scripts:
- `sources-v2/prompt_research/phase_c_query_replay_probe.py`
- `sources-v2/prompt_research/phase_c_query_replay_summary.py`

Outputs:
- `sources-v2/prompt_research/probe_outputs/phase_c_query_replay_17d29aaee1fecc8cf1a34025_20260308-192447.json`
- `sources-v2/prompt_research/probe_outputs/phase_c_query_replay_17d29aaee1fecc8cf1a34025_20260308-192447.summary.md`
- matching OpenAlex / S2 CSV exports

Method:
- OpenAlex:
  - replay every generated query on its current surface
  - replay the same logic on the alternate surface:
    - `search` -> `title_and_abstract.search`
    - `title_and_abstract.search` -> `search`
  - record `meta.count` and top sample titles
- Semantic Scholar:
  - replay every generated query on bulk search
  - replay every generated query on regular search as a secondary comparison signal
  - for queries with negatives, replay a no-negative ablation
  - record totals and top sample titles
- Top-title inspection:
  - compute lightweight sample anchor/core hit rates against `primary_context_anchors` and `core_object_terms`
  - use these only as rough drift signals, not as final truth

## Main findings

### 1. OpenAlex surface lift is real, but broad `search` is not automatically good

Replay summary:
- 26 OpenAlex queries
- current zero-query rate: `26.9%`
- EN zero-query rate: `0.0%`
- DE zero-query rate: `87.5%`
- median current count: `59.5`
- median alternate-surface/current ratio: `20.06`

Interpretation:
- the live `search` surface is often much broader than `title_and_abstract.search`
- but broadness alone is not quality
- some broad authority or method-heavy queries retrieved large result sets whose top titles were obviously generic

High-signal examples:
- authority query `Platform effects, bias, and validity in review data`
  - current `search` count: `21,410`
  - alternate `title_and_abstract.search` count: `1,245`
  - top titles were still generic enough to suggest drift
- match query `Reporting and reproducibility practices for studies using reviews`
  - current `title_and_abstract.search` count: `473`
  - alternate `search` count: `20,954`
  - top titles were mostly generic reproducibility / data-source papers, not review-specific methodology
- match query `Practical sampling and sample construction from raw reviews`
  - count: `55`
  - top titles were still weakly review-specific
- match query `Principles to design text-based proxies and lexicon/classifier approaches`
  - count: `64`
  - top titles were mostly generic lexicon / sentiment-analysis papers

Future-self note:
- this topic suggests a more conservative authority design than "authority defaults to broad `search`"
- a stronger staged pattern may be:
  - one tight authority core on `title_and_abstract.search`
  - at most one broad `search` booster when needed

### 2. German collapse is still the clearest language problem

OpenAlex replay:
- DE current counts: `[0, 13, 0, 0, 0, 0, 0, 0]`

Semantic Scholar replay:
- DE bulk totals: `[0, 0]`

Interpretation:
- selective DE is still correct
- the current generated DE families are too brittle for this topic
- the system should not treat "German coverage exists in principle" as "German query families should always be emitted"

Targeted rescue checks:
- OpenAlex DE authority current: `0`
- OpenAlex DE authority bilingual rescue: `1,384`
- OpenAlex DE proxy match current: `0`
- OpenAlex DE proxy match bilingual rescue: `0`
- S2 DE authority current: `0`
- S2 DE authority bilingual rescue: `343`
- S2 DE proxy match current: `0`
- S2 DE proxy match bilingual rescue: `0`

Interpretation:
- bilingual fallback can rescue broad authority-style German failures
- bilingual fallback does not rescue every method/proxy facet
- the hard problem is not just "German vs English"
- it is "are these facet terms actually literature-native for this object in that language"

Practical staged implication:
- later adaptation should favor:
  - bilingual authority fallback when DE-only authority dies
  - very selective DE match queries
  - skipping DE match families entirely when the object+facet wording is implausible

### 3. S2 negatives are not the main recall lever here

Replay summary:
- 7 S2 queries contained negatives
- median no-negative/current ratio: `1.01`

Examples:
- `current=235`, `no_negative=246`
- `current=120`, `no_negative=125`
- several negative-bearing queries changed by `<= 1%`

Interpretation:
- the new negative-budget guard is still good syntax hygiene
- but for this topic, negatives are not the major source of S2 starvation
- the bigger S2 levers are language choice and facet lexicality

### 4. S2 bulk is the right primary endpoint for this analysis

Replay summary:
- all 17 bulk requests returned `200`
- regular `/paper/search` returned:
  - many `0` totals
  - 7 initial `429` responses in the replay pass
  - one later `500` during slower reruns

Bulk/search contrast:
- query `Broad match for proxies, bias, representativeness, and data features in online reviews`
  - bulk: `402`
  - search: `0`
- query `Workflows for scalable text analysis on large review corpora`
  - bulk: `2,488`
  - search: `2`
- query `Evaluation metrics and error analysis for automated classifiers on reviews`
  - bulk: `2,871`
  - search: `0`

Interpretation:
- regular search is not a stable benchmarking companion for the bulk endpoint
- for future Phase C testing, treat bulk as the primary truth for S2 yield
- use regular search only as an exploratory side probe, not as a hard comparison baseline

### 5. The bigger risk now is broad-but-generic families, not just dead narrow queries

This is the most important replay result.

The obvious live drifters were:
- OpenAlex authority and reporting/workflow families
- S2 workflow / evaluation / reproducibility families

Examples:
- S2 `Evaluation metrics and error analysis for automated classifiers on reviews`
  - bulk total: `2,871`
  - sample titles were generic sentiment-analysis / classifier papers
- S2 `Workflows for scalable text analysis on large review corpora`
  - bulk total: `2,488`
  - sample titles were largely generic app-review sentiment-analysis papers
- S2 `Guidance on reporting, documentation and reproducibility for review-based studies`
  - bulk total: `155`
  - top titles were often generic and not clearly about review-based measurement

Interpretation:
- these are not "bad because they are empty"
- they are bad because they can contribute large volumes of weakly chapter-specific material
- this is exactly the kind of pollution that hurts top-40 quality later

## What this suggests to adapt later

### OpenAlex

- Do not assume every authority query should default to top-level `search`.
- Test a tighter authority pattern:
  - 1 core authority query on `title_and_abstract.search`
  - 1 optional broad `search` booster only when the core count is weak
- For high-risk generic families such as sampling, proxy design, and reproducibility:
  - require at least one direct review-specific object phrase
  - avoid letting the facet group dominate the object
- Keep bilingual fallback available for failed DE authority families.
- Do not interpret a large `search` lift as evidence of better retrieval quality by itself.

### Semantic Scholar

- Keep bulk search as the primary analysis target.
- Do not spend much design effort on negatives yet; the payoff looks small here.
- Put more pressure on facet lexicality:
  - workflow / evaluation / reproducibility families need stricter chapter-object conditioning
- Consider demoting or delaying method-heavy query families that showed high totals but generic top titles.
- Treat DE proxy/method queries as opt-in edge cases, not defaults.
- Bilingual fallback seems useful for authority-like recovery, but not for every match family.

## Guardrail against overfitting

This is still one chapter.

So the correct use of these findings is:
- not to hard-code chapter-specific terms
- but to identify reusable failure modes:
  - broad surface != relevant surface
  - DE viability is family-specific, not global
  - negatives may matter less than lexicality
  - broad method/evaluation families can pollute the pool even when counts look healthy

Future-self note:
- replay this same analysis on several chapters before turning these observations into hard global caps
- but the current evidence is already strong enough to justify report-level recommendations and targeted future tests
