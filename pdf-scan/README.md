# PDF Scan

This folder is organized by role so the core pipeline stays visible and the support tooling stays out of the way.

## Core

- `phase_a_lab.py` to `phase_g_lab.py`
  - the main staged pipeline
- `pdf_reporting.py`
  - run and per-PDF reporting
- `pdf-scan-v3.ipynb`
  - current notebook entrypoint

## Notebooks

- `pdf-scan-test.ipynb`
- `pdf-scan-v2.ipynb`
- `pdf-scan-v3.ipynb`
- `text-extract-test.ipynb`

## Benchmark

- `benchmark/`
  - benchmark schemas, manifests, judgments, and curated suites

## Research

- `research/`
  - design notes, audit reports, and iterative findings

## Local Data

- `runs/`
  - generated pipeline runs and cached artifacts
- `paper-dump/`
  - local PDF dump for testing

Both are ignored locally by `pdf-scan/.gitignore`.

## Tooling

- `tools/benchmark/`
  - benchmark builders and evaluators
- `tools/inspection/`
  - section-inspection and benchmark-review helpers

## Root-Level Support Scripts

These remain at the top level because they are still part of active pipeline development rather than general tooling:

- `phase_c_truth_lab.py`
- `phase_cd_failure_lab.py`
- `phase_cd_solution_search.py`
- `phase_e_failure_lab.py`
- `phase_e_solution_search.py`
- `phase_def_benchmark_search.py`
- `pipeline_deep_audit_lab.py`
- `review_phase_*.py`
- `review_pipeline_ae.py`
- `review_run_outputs.py`

If more cleanup is wanted later, these can be moved into `tools/` as a second pass.
