# PDF Scan Deep Research Meta

Date: 2026-03-14
Workspace: `<projektverzeichnis>`
Scope: Section-first PDF scan pipeline for digital PDFs only.

Project target:
- For each PDF individually, decide whether it contains likely useful material for a chapter specification.
- If useful, return the relevant section(s) or subsection(s), explain why they are useful, and point to where they are in the PDF.
- If not useful, abstain explicitly for that PDF.

User constraints:
- No OCR. Digital PDFs only.
- Subsections are allowed and preferred when they are the true useful unit.
- Optimize primarily for quality and recall.
- Keep average API cost roughly in the low-cent range per PDF, with longer PDFs allowed to cost more.
- Favor per-PDF outputs over corpus-global domination by one document.
- Optimize for English first, but handle German inputs and occasional German PDFs.

Repository constraints:
- The implementation plan file in `pdf-scan` is allowed to be read.
- Do not inspect any other existing Markdown file inside `pdf-scan`.
- Iterative memory files are allowed and requested.

Working hypotheses after local review:
- Phase A-E exist in `pdf-scan-v2.ipynb`; later plan phases are not yet implemented.
- The current failure mode is not only parser quality. Query planning and support calibration are also too weak.
- Per-document abstention should be treated as a first-class output, not an afterthought.

Research streams:
1. Reliable digital PDF parsing and section recovery for short to very long PDFs.
2. Section and subsection normalization with page spans and parser provenance.
3. Per-document retrieval and reranking to avoid one-document domination.
4. Abstention and confidence calibration for "useful" vs "not useful".
5. Benchmarking and judgment design for section-level evaluation.

Files in this research set:
- `10_local_findings.md`
- `20_web_pdf_parsing.md`
- `30_web_retrieval_rerank.md`
- `40_web_benchmark_eval.md`
- `90_synthesis_draft.md`
