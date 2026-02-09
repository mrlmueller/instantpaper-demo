# Resource Ranking Improvements (Authority + Relevance)

This document is a **deliberately wide** backlog of experiments to improve the *quality* of papers returned by `source_final.ipynb` by ranking not only for **topical fit** but also for **authority** (citations, influential citations, reputable venues, well-known authors, etc.).

It’s written to be actionable against the current pipeline stages:

- **Stage B**: Chapter blueprint (LLM-generated rubric + queries)
- **Stage A**: Candidate acquisition (OpenAlex + Semantic Scholar)
- **Stage C**: Hybrid scoring (TF‑IDF + embeddings + small citation signal)
- **Stage C.3**: LLM shortlist rerank (include/maybe/exclude + score)
- **Stage D**: Diversity selection (MMR)

The notebook already has a citation signal (`score_cite_norm`) and a small fusion weight (`STAGEC_CITE_WEIGHT=0.08`). The core gap is that **“authority” is currently under-modeled** (only raw citations, per-chapter max-normalized) and **not used consistently across later stages** (Stage D relevance ignores it; Stage C.3 prompt ignores it).

---

## 0) Define “Authority” (what we actually want)

Authority is not one scalar. For your use-case (“best sources for a chapter”), it usually means a combination of:

1) **Scholarly impact**: citations, influential citations, citation velocity, field-normalized impact.
2) **Venue credibility**: reputable journal/conference vs. low‑signal venues (incl. predatory).
3) **Author credibility**: author-level impact (h‑index / citations), domain centrality.
4) **Publication status**: published version vs preprint; retracted/errata flags.
5) **Practical authority (optional)**: standards / government guidance (NIST, IETF RFCs), industry reference architectures.

Key principle: **Authority should be a tie-breaker among relevant papers**, not a substitute for relevance. Otherwise you’ll bias toward old, highly cited, but off-topic classics.

---

## 1) What others do (so we don’t reinvent the wheel)

### 1.1 Two-stage ranking + learning-to-rank is the norm

Academic search engines typically:

- retrieve a candidate set via lexical + semantic retrieval
- then **re-rank** with a supervised model (e.g., LambdaRank in LightGBM) combining:
  - relevance features (query-title/abstract term matches, BM25-like stats)
  - **citation-based features** (citations, citations/age, influential citations)
  - metadata features (year, doc type, etc.)

Semantic Scholar has publicly described using a **LightGBM LambdaRank** reranker with features including:

- n‑gram match counts and fractions between query and title/abstract
- query terms in title
- year
- citations, citations/age (“citations divided by oldness”)
- influential citations and influential citations/age

References:
- https://medium.com/ai2-blog/building-a-better-search-engine-for-semantic-scholar-ea23a0b661e7
- https://github.com/allenai/s2search

### 1.2 Better than raw citations: field- and time-normalized metrics

Raw citations are heavily confounded by:

- **age** (older papers accumulate citations)
- **field** (some subfields cite more)

OpenAlex exposes directly usable normalized metrics for Works, including:

- `citation_normalized_percentile` (field+year+type normalized)
- `cited_by_percentile_year`
- `fwci` (Field-Weighted Citation Impact)
- `counts_by_year` (enables citation velocity features)

References:
- https://docs.openalex.org/api-entities/works/work-object
- https://help.openalex.org/hc/en-us/articles/24300873176343-Field-Weighted-Citation-Impact-FWCI

### 1.3 “Authority” can also be graph-based (PageRank/CiteRank)

Citation networks support authority ranking via:

- PageRank / Eigenvector centrality
- time-aware variants like **CiteRank** (bias toward more recent activity)

This can outperform raw citation counts for “seminal in-topic” works when you can build a citation subgraph for your candidate set.

References:
- Maslov & Redner (2007): CiteRank — https://arxiv.org/abs/0707.0082

---

## 2) The current pipeline’s authority signal (as implemented)

### 2.1 Stage A

- Fetches `cited_by_count` (OpenAlex) and `citationCount` (Semantic Scholar).
- Merges cross-source and keeps `citation_count_max`.
- Sorts Stage A output by `citation_count_max` (but this is *not* the final ranking).

### 2.2 Stage C

- Builds `score_cite_norm` as `log1p(citation_count_max) / max(log1p(...))` **per chapter**.
- Fuses into `score_stageC_final` with `STAGEC_CITE_WEIGHT=0.08`.

Issues:

- Max-normalization is **outlier sensitive** (one mega-cited paper compresses all others).
- No age normalization → **older wins**.
- No venue/author signals.
- Citation is only 8% of Stage C, and **Stage D relevance ignores it**.

### 2.3 Stage C.3 + Stage D

- Stage C.3 prompt does not include citations/venue/author authority signals.
- Stage D uses `score_stageC3_signal_v1` (LLM relevance) and TF‑IDF similarity for diversity; authority is only a weak tie-breaker inside Stage C.3 sorting.

---

## 3) What to improve: experiment backlog (complexity × impact)

Legend:
- **Complexity**: Low (L), Medium (M), High (H)
- **Impact (expected)**: Low/Med/High (relative to current baseline)

### 3.1 Low complexity (tactical, mostly parameter/features you already have)

#### A) Replace `score_cite_norm` with robust normalization
- **Change**: replace `max` normalization with a robust transform:
  - percentile/rank normalization within chapter
  - or z-score on `log1p(cites)` with clipping
  - or `minmax(log1p(cites))` (still outlier-y, but better than divide-by-max if you clip)
- **Where**: Stage C (`score_cite_norm` computation)
- **Complexity**: L
- **Impact**: Med (reduces pathological compression)
- **Test**:
  - offline ndcg@20 vs baseline
  - new metric: `median_citations@20` (sanity), but keep ndcg primary

#### B) Add citation velocity (“citations per year”)
- **Change**: compute something like:
  - `age = max(1, current_year - year + 1)`
  - `cites_per_year = log1p(cites / age)`
- **Where**: Stage C (derive from `citation_count_max` + `year`)
- **Complexity**: L
- **Impact**: Med–High (often improves “recent but important” papers)
- **Test**:
  - ndcg@K
  - track `avg_year@20` and `avg_cites_per_year@20` to ensure you didn’t drift to pure recency

#### C) Use `source_count` as a weak reliability signal
- **Change**: small boost when a work appears in both OpenAlex and S2 (or more sources if you add them).
- **Where**: Stage C fusion features (Stage A already has `source_count`)
- **Complexity**: L
- **Impact**: Low–Med (helps prune weird one-off records)

#### D) Penalize “no abstract” early (or fetch more aggressively)
- **Change**: add a penalty if `has_abstract` is false; or increase effort to fetch abstracts for top candidates.
- **Where**: Stage C score; Stage A fetch policy
- **Complexity**: L–M
- **Impact**: Med (LLM and embedding scoring improve with abstracts)
- **Risk**: may drop relevant but older/metadata-poor records; consider only a mild penalty.

#### E) Tune `STAGEC_CITE_WEIGHT` and propagate authority into Stage D relevance
- **Change**:
  - sweep `STAGEC_CITE_WEIGHT` (e.g., 0.05 → 0.30) and evaluate LOCO
  - incorporate authority into `score_stageC3_signal_v1` (e.g., `1 + llm_n + gamma*authority_n`)
- **Where**: Stage C weights + Stage D relevance signal
- **Complexity**: L
- **Impact**: Med–High (if calibrated carefully)
- **Risk**: can over-bias to old/cited if you don’t add age normalization first.

#### F) Add “survey/review/standard” boosts (heuristics)
- **Change**: boost titles matching:
  - `survey`, `systematic review`, `taxonomy`, `reference architecture`, `standard`, `framework`
- **Where**: Stage C as a small additive feature
- **Complexity**: L
- **Impact**: Med (often surfaces the “right kind” of foundational docs early)
- **Risk**: topic-dependent; keep weight small and evaluate.

#### Additional low-complexity knobs worth testing (pipeline-wide)

These aren’t “authority signals” by themselves, but they often improve the *candidate set*, which makes authority ranking more meaningful.

- **Use blueprint negatives (`negative_query_terms`) as post-filters** (Complexity: L | Impact: Low–Med)  
  Filter out candidates whose titles/abstracts contain strong MUST_AVOID terms (soft filter with audit logs).

- **Increase recall knobs, then re-rank** (Complexity: L | Impact: Med)  
  Sweep: `FETCH_MAX_QUERIES_PER_CHAPTER`, `OA_MAX_WORKS_PER_QUERY`, `S2_MAX_PAGES_PER_QUERY`, `TOP_PER_QUERY`, `STAGEC3_TOPN_MAX`.  
  This is often a cheap way to “find the missing seminal paper”.

- **Tune lexical/embedding plumbing (cheap, sometimes surprisingly impactful)** (Complexity: L | Impact: Low–Med)  
  Sweeps to consider: `TFIDF_MIN_DF`, `TFIDF_NGRAM_RANGE`, `TFIDF_MAX_FEATURES`, stopword language, `MAX_CHARS_PER_EMBED`, `EMBED_BATCH_SIZE`.

- **Prefer peer-reviewed types (softly)** (Complexity: L | Impact: Med)  
  Add a small boost/penalty based on `type` (OpenAlex) / `publicationTypes` (S2) where available; avoid hard filters initially.

- **Downrank suspicious venues by string heuristics (temporary guardrail)** (Complexity: L | Impact: Low–Med)  
  Example: penalize venues matching patterns like `International Journal of ...` *only if* venue authority stats are missing/low.  
  (This is a stopgap until venue stats (Section I) are in place.)

#### Blueprint + acquisition improvements (authority-aware recall)

These target the **candidate pool quality** coming into Stage C; authority re-ranking can’t help if the right papers never enter the pool.

- **Use more of the blueprint output to generate queries** (Complexity: L | Impact: Med)  
  Stage A currently uses `main_query + facet_queries` only. Consider also generating additional queries from `keywords` + `key_concepts` (e.g., 10–30 extra queries, deduped), then rely on later ranking to filter noise.

- **Add an “authority pull” retrieval pass** (Complexity: L–M | Impact: Med–High)  
  For each chapter, run 1–3 broader queries and explicitly retrieve a few hundred works sorted by citation/impact (API-side sort when available, or post-sort). Union these into the pool, then let relevance stages filter.

- **Concept/topic filtering with OpenAlex** (Complexity: M | Impact: High)  
  Derive 3–10 OpenAlex concept/topic IDs from the blueprint (or from top seed papers), then filter subsequent OpenAlex work retrieval to those concepts to reduce off-topic high-citation “famous but irrelevant” results.

- **Venue/author-aware query variants (soft constraints)** (Complexity: M | Impact: Med)  
  Have Stage B output a short list of “likely top venues” and “canonical authors/organizations” *derived from the chapter*, then use them as *soft* boosts (not hard filters) in ranking or as additional targeted retrieval queries.

---

### 3.2 Medium complexity (new metadata fields + cached enrichment; big wins without redesign)

#### G) Pull OpenAlex normalized impact metrics (FWCI + percentiles) and use them as authority
- **Change**: in OpenAlex `select=...` add:
  - `fwci`
  - `citation_normalized_percentile`
  - `cited_by_percentile_year`
  - `counts_by_year`
  - `is_retracted`, `is_paratext`
  - `primary_location` / `locations` fields needed to capture venue ids + versions
- **Where**: Stage A OpenAlex fetch (`select=...`)
- **Complexity**: M (more fields + storage; minimal logic)
- **Impact**: High (you get *field- and time-normalized* authority “for free”)
- **Tests**:
  - ablations: raw cites vs `cited_by_percentile_year` vs `citation_normalized_percentile.value`
  - add an “authority sanity” metric: fraction of top‑20 with percentile ≥ 0.90
- **Notes**:
  - Prefer percentiles over raw citations when mixing across years/subfields.

#### H) Pull Semantic Scholar `influentialCitationCount` (and use influential/age)
- **Change**: extend S2 fields to include `influentialCitationCount` (and optionally `publicationDate`, `publicationTypes`, `fieldsOfStudy`, `isOpenAccess`).
- **Where**: Stage A S2 fetch (`SEARCH_FIELDS`, batch detail fields)
- **Complexity**: M
- **Impact**: Med–High (influential citations are a stronger “authority” proxy than raw count)
- **Tests**:
  - compare authority features: raw `citationCount` vs `influentialCitationCount` vs ratios per age

#### I) Venue authority via OpenAlex Sources (h-index, 2yr mean citedness)
- **Change**:
  - store venue/source IDs from OpenAlex (`primary_location.source.id`)
  - fetch OpenAlex Source objects for unique source IDs (cache results)
  - derive `venue_h_index`, `venue_2yr_mean_citedness`, `venue_works_count`
  - add a `venue_authority_score` (normalized per chapter)
- **Where**: Stage A (store ids) + new enrichment step (between A and C)
- **Complexity**: M
- **Impact**: High for filtering low-quality venues / predatory noise
- **Tests**:
  - measure drop in “obviously bad venues” inside top‑K (manual audit + heuristic thresholds)
  - ndcg@K shouldn’t regress

#### J) Author authority via OpenAlex Authors or S2 Author endpoints
- **Change**:
  - capture author IDs (OpenAlex authorships have ids; S2 can return authorIds)
  - fetch and cache author metrics (`h_index`, `cited_by_count`, works_count)
  - add features: `max_author_h`, `sum_top3_author_h`, `max_author_cites`, etc.
- **Where**: Stage A + enrichment
- **Complexity**: M (data joins + caching)
- **Impact**: Med–High (helps “well-known authors” requirement)
- **Risks**:
  - name disambiguation: only use stable IDs (ORCID/OpenAlex id/S2 authorId), avoid fuzzy name matching.

#### K) Version-aware de-dup (prefer published version over preprint)
- **Change**:
  - when multiple records exist for the same DOI/title cluster, prefer:
    1) publishedVersion (journal/conference) over submittedVersion (preprint)
    2) higher venue authority
    3) higher normalized impact
  - strengthen cross-source clustering (reduces duplicate noise and fixes split citation counts):
    - avoid relying on `title_norm + year` alone when DOI is missing (false merges)
    - incorporate first-author (or author ID) + venue signals into the merge key
    - use stable external IDs when available (DOI, arXiv ID, PubMed ID, S2 paperId, OpenAlex id)
- **Where**: Stage A merge + dedupe policy
- **Complexity**: M
- **Impact**: Med (reduces “arXiv vs journal duplicate” clutter; improves perceived quality)

#### L) Add an explicit `authority_score` column and treat it as a first-class signal
- **Change**:
  - compute a calibrated authority score from a small set of robust features:
    - OpenAlex `citation_normalized_percentile.value` (primary)
    - S2 `influentialCitationCount/age` (secondary)
    - venue h-index (tertiary)
    - author h-index (tertiary)
  - then fuse: `final = (1-α)*relevance + α*authority`, with α tuned
- **Where**: Stage C fusion; optionally as a post-processing rerank among “include”
- **Complexity**: M
- **Impact**: High (this directly addresses your request)
- **Testing**:
  - evaluate ndcg@K (relevance) + track authority metrics as secondary
  - run LOCO to avoid overfitting to one chapter type

#### M) Improve lexical scoring: replace TF‑IDF with BM25 (or add BM25 as another feature)
- **Change**:
  - TF‑IDF is okay, but BM25 is the standard baseline and handles term saturation better
  - add BM25 score and let fusion/LTR decide
- **Where**: Stage C lexical scoring
- **Complexity**: M
- **Impact**: Med (often helps recall/precision on technical terms)

#### N) Upgrade embeddings (or use scientific embeddings)
- **Change options**:
  1) switch OpenAI embedding model (better quality, higher cost)
  2) use S2’s SPECTER2 embedding field (precomputed) for S2 papers (field name appears as `embedding.specterv2` / `embedding.specter_v2`)
  3) use a local model (e.g., Sci-optimized embedding model) to reduce cost
- **Where**: Stage C embedding scoring
- **Complexity**: M
- **Impact**: Med–High (relevance lift; indirectly improves authority because you surface better candidates)

---

### 3.3 High complexity (major redesigns; only do after you exhaust the above)

#### O) Learning-to-Rank (LTR) for final ranking (LambdaRank / pairwise)
- **Change**:
  - build a feature table for each (chapter, paper) candidate
  - train a ranking model (LightGBM LambdaRank is a strong starting point)
  - features should include: lexical relevance, embedding relevance, authority signals, freshness, venue/author metrics
- **Where**: replaces hand-tuned fusion in Stage C; can also replace parts of Stage C.3 ordering
- **Complexity**: H (training pipeline + feature management + validation)
- **Impact**: Very High (this is what production search engines do)
- **References**:
  - Semantic Scholar’s described approach + open-source `s2search`
- **Testing**:
  - strict LOCO + repeated runs to ensure stability
  - calibrate for “top‑K quality” (ndcg@10/20)

#### P) Graph-based authority: PageRank/CiteRank on a topic subgraph
- **Change**:
  - for the candidate set (or expanded neighborhood), fetch references/citations
  - build a citation graph
  - compute PageRank / CiteRank and use it as authority (topic-sensitive if you restrict edges)
- **Where**: new authority module; fused with relevance in Stage C/D
- **Complexity**: H (extra API calls + graph compute + caching)
- **Impact**: High (especially for surfacing “seminal” works that are central to the topic)
- **Risks**:
  - API cost/limits; missing edges for some works; bias toward well-covered fields.

#### Q) Candidate expansion via recommendations (graph/embedding neighborhoods)
- **Change**:
  - after Stage C finds top seeds, call Semantic Scholar Recommendations API to expand candidates
  - then re-score/rerank expanded set
- **Where**: between Stage A and Stage C (or as Stage A2)
- **Complexity**: H
- **Impact**: High (recall + authority improves if seeds are good)
- **Risk**: topic drift if seed relevance is weak; guard with rubric checks.

#### R) Full-text retrieval + chunk-level ranking (OA PDFs)
- **Change**:
  - fetch open-access PDFs (OpenAlex + Unpaywall-style links)
  - run text extraction + chunk embeddings
  - rank by evidence coverage (not just abstract keywords)
- **Where**: entirely new retrieval layer
- **Complexity**: H
- **Impact**: Very High for nuanced/technical chapters (abstracts can be misleading)
- **Risk**: infra + latency + extraction quality; needs robust caching.

#### S) Build a local index (OpenAlex/S2 snapshots) for consistent retrieval + richer features
- **Change**:
  - ingest OpenAlex snapshot (and optionally S2 Open Research Corpus / S2AG subsets)
  - build a local BM25 + vector index
  - compute authority features offline (PageRank, venue stats, author stats)
- **Where**: replaces Stage A APIs for most retrieval
- **Complexity**: Very H
- **Impact**: High (control + speed + repeatability), but large engineering cost.

---

## 4) Concrete authority feature set (recommended starting point)

If you want a pragmatic “authority_v1” that is cheap and strong:

1) **OpenAlex** (preferred when available):
   - `citation_normalized_percentile.value` (0–1)
   - `fwci` (log-scaled + clipped)
   - recent citations from `counts_by_year` (e.g., last 2 years sum)
2) **Semantic Scholar**:
   - `influentialCitationCount`
   - `influentialCitationCount / age`
3) **Venue** (OpenAlex Source):
   - `summary_stats.h_index`
   - `summary_stats.2yr_mean_citedness`
4) **Authors** (OpenAlex Author or S2 Author):
   - `max_author_h_index` (or top‑3 mean)

Then normalize per chapter (rank/percentile) and fuse:

- `authority_score = w1*oa_percentile + w2*log1p(fwci) + w3*infl_cites_per_age + w4*venue_h + w5*author_h`

Important: keep weights interpretable and **clip** extreme values.

---

## 5) Where to plug authority into the pipeline (so it actually changes output)

You have three good insertion points:

1) **Stage C**: incorporate authority into `score_stageC_final` (and thus top‑N for Stage C.3)
2) **Stage C.3 ordering**: include authority as a secondary sort key among equally relevant “include” items
3) **Stage D relevance**: use authority-aware relevance for MMR selection so diversity doesn’t accidentally favor low-authority items

Recommended strategy:

- Use Stage C to get a *better shortlist*.
- Keep Stage C.3 as *relevance gatekeeper* (avoid hallucinated authority judgments).
- Use Stage D to diversify among **relevant** items while retaining authority.

---

## 6) Evaluation: what to test (and what to log)

You already have a solid evaluation loop (`eval_dataset_builder.ipynb` + `sources_test.ipynb` + `PIPELINE_EVALUATION.md`).

### 6.1 Primary metric (keep)
- `ndcg@10/20/50` (graded include/maybe/exclude)

### 6.2 Add authority secondary metrics (new)
These are *guardrails*, not primary objectives:

- `authority@K`: mean/median `authority_score` in top‑K
- `%topK_high_impact`: fraction with OpenAlex percentile ≥ 0.90 (when present)
- `avg_age@K`: avoid drifting to only very old papers
- `venue_quality@K`: fraction above venue h-index threshold (heuristic)

### 6.3 Ablation matrix (minimal set to run first)
Order from cheapest → more involved:

1) Robust cite normalization + cite/age feature
2) Sweep `STAGEC_CITE_WEIGHT` + Stage D authority injection
3) Add OpenAlex percentiles/FWCI (authority_v1)
4) Add S2 influential citations (authority_v2)
5) Add venue + author enrichment (authority_v3)
6) Optional: switch embeddings / add BM25

Each run:
- Evaluate across all chapters + LOCO.
- Keep a “manual audit” list: top‑20 for each chapter (spot-check for junk venues).

---

## 7) References (starting points)

- Semantic Scholar ranking & search:
  - *Building a Better Search Engine for Semantic Scholar* (LightGBM LambdaRank + citation/age/influential citations features): https://medium.com/ai2-blog/building-a-better-search-engine-for-semantic-scholar-ea23a0b661e7
  - `allenai/s2search` (GitHub): https://github.com/allenai/s2search
  - API tutorial (fields, examples, recommendations): https://www.semanticscholar.org/product/api/tutorial
  - Graph API docs: https://api.semanticscholar.org/api-docs/graph

- OpenAlex authority/impact metrics:
  - Work object (`citation_normalized_percentile`, `cited_by_percentile_year`, `fwci`, `counts_by_year`): https://docs.openalex.org/api-entities/works/work-object
  - FWCI definition: https://help.openalex.org/hc/en-us/articles/24300873176343-Field-Weighted-Citation-Impact-FWCI
  - Author object (`summary_stats` with h-index/i10/2yr_mean_citedness): https://docs.openalex.org/api-entities/authors/author-object
  - Source object (venue summary stats): https://docs.openalex.org/api-entities/sources/source-object

- Citation-network authority:
  - CiteRank (time-aware ranking on citation networks): https://arxiv.org/abs/0707.0082
  - PageRank/Eigenvector centrality literature (general)

- Scientific semantic embeddings:
  - SPECTER2 (Semantic Scholar / AI2; S2 Graph API exposes a SPECTER2 embedding field — the exact name varies in docs/posts as `embedding.specterv2` / `embedding.specter_v2`, so confirm against the current API schema)
  - https://www.semanticscholar.org/blog/specter2-paper-embeddings/

### Direct API/doc links (handy for implementation)

- Semantic Scholar API tutorial: https://www.semanticscholar.org/product/api/tutorial
- Semantic Scholar Graph API docs: https://api.semanticscholar.org/api-docs/graph
- OpenAlex Work object: https://docs.openalex.org/api-entities/works/work-object
- OpenAlex Author object: https://docs.openalex.org/api-entities/authors/author-object
- OpenAlex Source object: https://docs.openalex.org/api-entities/sources/source-object
- OpenAlex FWCI definition: https://help.openalex.org/hc/en-us/articles/24300873176343-Field-Weighted-Citation-Impact-FWCI
