# Phase A Report

Date: 2026-03-14
Phase: A - Config, run context, artifact skeleton, and phase-level observability

## Goal Of Phase A

Phase A exists to make every later phase safe to iterate on.

Inputs:
- chapter title
- chapter description
- pipeline version
- PDF inputs
- environment variables

Outputs:
- stable run id
- run directory
- root artifacts
- phase-specific artifacts
- metrics and event logs
- validation / QC summary

Why this matters:
- Every later phase writes derived artifacts that depend on the exact inputs and file set.
- If Phase A is weak, all later debugging becomes noisy because run identity, config state, and artifact ownership are ambiguous.

## What I Changed

### 1. Created an executable Phase A lab

Added:
- `pdf-scan/phase_a_lab.py`

Purpose:
- run Phase A outside the notebook
- iterate faster
- avoid notebook-only debugging

This is the executable copy of the phase requested by the user workflow.

### 2. Strengthened the config surface

The new lab uses `pydantic` models instead of loose dataclasses for the Phase A config contract.

What this enables:
- non-empty validation for required fields
- stronger path normalization
- guaranteed presence of resolved PDF sources
- cleaner serialized config snapshots

### 3. Fixed reproducibility gaps

The previous notebook snapshot only stored chapter text length, not the full chapter text.

The new Phase A snapshot stores:
- full `chapter_spec_text`
- `chapter_spec_sha256`
- resolved source counts
- discovery counts

Why this matters:
- run ids can now be recomputed from artifacts alone
- later review scripts can verify that the run directory actually matches the saved config

### 4. Added Phase A-specific artifacts

New artifacts:
- `phase_a/phase_a_config.json`
- `phase_a/phase_a_runtime.json`
- `phase_a/phase_a_summary.json`
- `phase_a/phase_a_assessment.json`

Why this matters:
- Phase A now looks like the later phases operationally
- each phase can be reviewed in isolation
- later reports can point to one structured phase bundle instead of mixing root artifacts and logs

### 5. Added a unified API-usage ledger

New artifact:
- `api_calls.jsonl`

Why this matters:
- the user explicitly asked that all OpenAI/API costs always be tracked
- later phases can append to one run-level ledger
- total API usage can be aggregated from one place instead of scattered summaries

### 6. Improved stage timing and status semantics

The new `stage_timer`:
- writes `stage_started`
- records `in_progress`
- clears stale failure fields on success
- records clean `success` / `failed` state

Why this matters:
- the old run metrics showed stale failure state mixed with later success
- this makes phase status trustworthy for later automation and review

### 7. Added a review script

Added:
- `pdf-scan/review_phase_a.py`

Purpose:
- recompute run id from saved artifacts
- confirm phase events exist
- confirm the API ledger exists
- analyze the manifest at a deeper aggregate level

This matches the requested workflow of using additional Python analysis instead of trusting the direct output alone.

## Phase A Run Used For Validation

Lab run id:
- `00d6b807151f752b2a096a1d`

Run directory:
- `pdf-scan/runs/00d6b807151f752b2a096a1d`

Validation artifacts:
- `phase_a/phase_a_summary.json`
- `phase_a/phase_a_assessment.json`
- `phase_a_review/phase_a_review_summary.json`

## What The Run Showed

Document inventory in the validation run:
- 5 PDFs
- page counts from 7 to 598
- 3 documents with outlines
- 1 document with zero extracted text on page 1

Interpretation:
- Phase A now captures enough metadata to identify high-risk documents before parsing starts
- the 598-page book already surfaces a useful signal: first-page text can be empty while the PDF is still valid
- this means page-1 text alone must never be used as a hard readability check

## Iteration Loop And Issues Found

### First iteration

Result:
- the lab ran successfully
- but `phase_a_summary.json` reported itself as missing in its own artifact table

Cause:
- artifact existence was captured before the summary file had been written

Fix:
- write the summary once
- recompute artifact rows after the summary exists
- rewrite the summary with final artifact state

### Second iteration

Result:
- artifact table became internally consistent
- review script confirmed the run id recomputed from saved config and manifest
- metrics, logs, and ledger all matched the expected contract

Decision:
- Phase A is good enough to move forward

## Why These Changes Enable Later Phases

### Later parsing work

Phase B will rely on:
- stable run directories
- consistent config snapshots
- reliable page counts and outline presence

Without this, parser disagreements are much harder to analyze.

### Later retrieval and reranking work

Phases D-F will rely on:
- chapter text provenance
- API usage accounting
- metrics that do not mix stale failures with current success

Without this, later quality and cost analysis will be untrustworthy.

### Later benchmark work

Phase I will rely on:
- reproducible run identity
- a consistent artifact contract
- per-phase summaries and reviews that can be compared across runs

## Is The Data Enough?

For Phase A specifically: yes.

Why:
- we are not trying to judge retrieval quality yet
- we only need enough data to validate the Phase A contract
- the current artifacts now cover:
  - input config
  - input manifest
  - runtime environment
  - QC
  - metrics
  - event log
  - API cost ledger
  - independent review

That is enough to move to Phase B without blind spots at the run-context layer.

## Remaining Known Limits

- The notebook itself has not been synced to this new lab implementation yet.
- This turn hardened Phase A in executable lab form first to avoid damaging the user’s current notebook state while iterating.
- The next implementation step should either:
  - port the stabilized Phase A back into `pdf-scan-v2.ipynb`, or
  - factor shared phase code into a module used by both the notebook and lab scripts

## Sources Used For The Phase A Refactor

- Pydantic model concepts:
  - `https://docs.pydantic.dev/latest/concepts/models/`
- Pydantic validators:
  - `https://docs.pydantic.dev/latest/concepts/validators/`
- Pydantic serialization:
  - `https://docs.pydantic.dev/latest/concepts/serialization/`
- Pydantic settings:
  - `https://docs.pydantic.dev/latest/concepts/pydantic_settings/`
