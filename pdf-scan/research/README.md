# PDF Scan Research Notes

This folder is the persistent memory for the `pdf-scan/pdf-scan-test.ipynb` research pass.

Rules for these notes:
- Focus on the notebook in `pdf-scan/pdf-scan-test.ipynb`, not the FastAPI runtime.
- No notebook code changes are part of this pass.
- Prefer primary sources: official docs, official repos, and original papers.
- Capture both findings and implications for the current pipeline.
- Keep rough notes here first; synthesize later into the final report.

Files:
- `00_pipeline_audit.md`: current notebook design, assumptions, and likely failure modes.
- `10_pdf_extraction_notes.md`: digital PDF extraction, structure recovery, and large-PDF handling.
- `20_retrieval_ranking_notes.md`: section retrieval and ranking methods for scientific literature.
- `30_api_package_notes.md`: current docs for the APIs/packages the notebook relies on.
- `40_benchmark_notes.md`: benchmark and evaluation design ideas.
- `50_stage_blueprint_notes.md`: second-pass stage map and cross-stage interface notes.
- `60_parsing_section_design_notes.md`: stage-specific notes for parsing and section candidate construction.
- `70_retrieval_rerank_design_notes.md`: stage-specific notes for retrieval and reranking design.
- `80_scoring_observability_notes.md`: scoring, no-match detection, logging, and stage summaries.
- `99_final_report_draft.md`: synthesis area before final polishing.
