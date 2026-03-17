# Synthesis Draft

Purpose:
- Hold the emerging target architecture, implementation recommendations, parameter notes, and final-report structure as research progresses.

Status:
- In progress.

Planned sections:
- Target behavior
- Proposed pipeline architecture
- Phase-by-phase implementation changes
- Parser stack recommendations
- Retrieval and reranking recommendations
- Abstention and calibration
- Benchmark suite and labeling
- Parameter tuning opportunities
- Additional observations outside the main pipeline

## Early Synthesis

### Non-negotiable output contract

The pipeline should output a result for each PDF independently:
- `doc_id`
- `useful`: `yes` / `no` / `uncertain`
- `reason`
- `confidence`
- `ranked_sections`

Each returned section should include:
- section / subsection title
- page span
- why it is useful for the chapter
- which chapter subpoints it supports
- top supporting passages

### Answer to the user’s open design point on per-document no-match

Per-document abstention must be a first-class outcome.

Reason:
- it matches the user’s real decision task
- it prevents one useful PDF from masking failures in others
- it creates a benchmarkable, calibratable acceptance / rejection problem

### Likely target architecture

1. Phase A-B:
- strong run context
- parser bundle with PyMuPDF, pypdf, Docling, optional GROBID

2. Phase C:
- canonical section graph
- subsection-preserving where possible
- evidence passages built from sections, not the other way around

3. Phase D:
- chapter decomposition into grounded query plan plus controlled expansion
- no over-literal pruning of valid bilingual / synonymous terms

4. Phase E:
- per-document candidate generation
- hybrid lexical + dense retrieval
- top-K section candidates plus evidence passages

5. Phase F:
- real reranking phase
- section-level judge / reranker
- evidence agreement checks

6. Phase G:
- per-document usefulness decision
- abstention thresholding
- confidence calibration

7. Phase H-I:
- final reporting
- benchmark harness
