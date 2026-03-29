# Phase C/D Solution Research

## Scope

This note covers the specific failures found in the current `pdf-scan-v2.ipynb` run:

- back-matter leakage into the candidate pool, especially `Index`
- too many semantically meaningful section headings still typed as `body_other`
- temptation to fix low lexical alignment with aggressive expansion or pseudo-feedback

The local tests for this note were run with:

- `python pdf-scan\phase_cd_failure_lab.py --base-dir pdf-scan --run-id 67507862e53171c27bfb2ac9`
- `python pdf-scan\phase_cd_solution_search.py --base-dir pdf-scan --run-id 67507862e53171c27bfb2ac9`

## Local Findings

Current run artifacts show:

- `Index` is still structurally leaking unless explicitly typed and penalized.
- The best local candidate is a discourse-aware classifier, not more expansion.
- Aggressive corpus feedback and loose lexical growth add drift without adding reliable hits.

Key local result from `solution_search`:

- `discourse_patch`: `composite=85.40`
- `discourse_conservative_lexical`: `composite=85.40`
- `discourse_plus_phrase_feedback`: `composite=85.20`
- `baseline`: `composite=58.43`

Interpretation:

- section typing is the dominant fix
- conservative lexical variants are harmless but unnecessary
- feedback should stay optional and later-stage, not part of the main Phase D plan

## External Evidence

### 1. Section typing should use a curated heading taxonomy, not raw heading strings

Europe PMC's section-tagger work describes a rule-based tagger built around normalized heading variants and regular expressions for a fixed label set, then maps unmatched headings to `Other`. That is very close to the problem we have in Phase C.

Sources:

- Europe PMC section tagger: <https://pmc.ncbi.nlm.nih.gov/articles/PMC4359544/>
- Structured section headings / article organization context: <https://pmc.ncbi.nlm.nih.gov/articles/PMC4147923/>

Why this matters here:

- our pipeline already has the raw headings
- the main missing piece is a better normalization dictionary
- adding back-matter labels such as `index` and richer discourse labels is evidence-based, not ad hoc

### 2. Blind feedback and broad query expansion can drift

The Stanford IR book explicitly warns that pseudo relevance feedback can cause query drift when the assumed relevant top results are not actually relevant.

Sources:

- Pseudo relevance feedback: <https://nlp.stanford.edu/IR-book/html/htmledition/pseudo-relevance-feedback-1.html>
- Relevance feedback and query expansion: <https://nlp.stanford.edu/IR-book/html/htmledition/relevance-feedback-and-query-expansion-1.html>

Recent work also shows that generative expansion is not uniformly beneficial:

- Query2doc reports gains from LLM-generated pseudo-documents, but only as an added retrieval aid, not proof that expansion is always safe: <https://aclanthology.org/2023.emnlp-main.585/>
- "When do Generative Query and Document Expansions Fail?" reports a negative correlation between retriever strength and gains from generative expansions, and shows that expansions can hurt stronger retrievers: <https://aclanthology.org/2024.findings-eacl.134/>
- Corpus-Steered Query Expansion exists precisely because unconstrained expansion can hallucinate irrelevant content; the paper steers generation using corpus signals: <https://aclanthology.org/2024.eacl-short.34/>

Why this matters here:

- our local lab already shows drift from naive feedback
- the evidence supports keeping feedback gated and optional
- Phase D should stay conservative; richer expansion belongs in later retrieval experiments, not the default planner

### 3. The semantic gap should be handled in retrieval, not with brittle lexical inflation

Sentence Transformers' retrieve-and-rerank guidance uses a first-stage retriever for high recall and a stronger reranker for final ordering. That supports keeping Phase D clean and handling cross-lingual/topic-semantic mismatch in Phase E/F.

Source:

- Retrieve & Re-Rank: <https://www.sbert.net/examples/sparse_encoder/applications/retrieve_rerank/README.html>

For the multilingual gap specifically, multilingual E5 was trained on roughly one billion multilingual text pairs and uses explicit `query:` / `passage:` prefixes.

Sources:

- multilingual-e5 paper: <https://arxiv.org/abs/2402.05672>
- multilingual-e5-large model card: <https://huggingface.co/intfloat/multilingual-e5-large>

Why this matters here:

- our benchmark chapter is German-heavy while most PDFs are English
- forcing more lexical synonyms into Phase D is the wrong layer to solve that
- the better fix is to preserve precise query concepts and add a multilingual dense retrieval view later

### 4. Parser structure should stay multi-lane

GROBID's principles describe a cascade of sequence-labeling models where segmentation is an early explicit stage. That supports the current architecture direction: keep parser lanes separate, keep structure explicit, and do not collapse everything into one raw-text search path.

Source:

- GROBID principles: <https://grobid.readthedocs.io/en/latest/Principles/>

## Chosen Fix Direction

### Phase C

Add or strengthen these section types:

- `index`
- richer `table_of_contents` variants such as lists of figures/tables
- richer `background` variants:
  - `theory and hypotheses`
  - `conceptual background`
  - `conceptual framework`
  - `theoretical framework`
- richer `methods` variants:
  - `main measures`
  - `measures`
  - `measurement`
  - `measurement model`
  - `variables`
  - `sample and procedures`

### Phase D

Keep the planner conservative:

- preserve the current strict plan structure
- include `index` in the allowed and penalized section types
- do not add broad corpus-feedback expansion to the default plan
- keep dense multilingual support as a future retrieval-view capability, not as lexical inflation

## Why This Is Not Overfitting

The chosen fix is not "make the query match this one chapter better." It is:

- improving generic scholarly section taxonomy
- explicitly handling generic back matter
- testing paraphrased probes, not only the exact benchmark wording
- avoiding benchmark-specific topic synonyms unless they are structurally justified

That is exactly the safer direction for later scaling to the larger suite.
