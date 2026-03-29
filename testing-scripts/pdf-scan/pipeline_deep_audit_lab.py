#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import fitz  # PyMuPDF
except Exception as e:  # pragma: no cover
    fitz = None
    FITZ_IMPORT_ERROR = f"{type(e).__name__}: {e}"
else:
    FITZ_IMPORT_ERROR = ""

from phase_b_lab import ensure_dir, write_json_atomic as write_json


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def page_html_path(doc_dir: Path, page_number: int) -> Path:
    return doc_dir / "pages" / f"page_{int(page_number):04d}.html"


def write_page_html(doc: Any, page_number: int, out_path: Path) -> None:
    page = doc[int(page_number) - 1]
    ensure_dir(out_path.parent)
    out_path.write_text(page.get_text("html"), encoding="utf-8")


def rel(path: Path, base: Path) -> str:
    return str(path.relative_to(base)).replace("\\", "/")


def choose_pages(phase_c: Dict[str, Any], phase_e: Dict[str, Any], phase_g: Dict[str, Any]) -> List[int]:
    pages = set()
    for row in (phase_c.get("accepted_headings") or [])[:25]:
        page = int(row.get("page") or row.get("anchor_page") or 0)
        if page > 0:
            pages.add(page)
    for row in (phase_e.get("fused_candidates") or [])[:12]:
        page_start = int(row.get("page_start") or 0)
        page_end = int(row.get("page_end") or 0)
        for page in range(page_start, min(page_end, page_start + 1) + 1):
            if page > 0:
                pages.add(page)
    output_document = phase_g.get("output_document") or {}
    for row in (output_document.get("top_sections") or [])[:8]:
        page_start = int(row.get("page_start") or 0)
        page_end = int(row.get("page_end") or 0)
        for page in range(page_start, min(page_end, page_start + 1) + 1):
            if page > 0:
                pages.add(page)
    return sorted(page for page in pages if page > 0)


def top_rows(rows: Iterable[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        out.append(row)
        if len(out) >= limit:
            break
    return out


def render_doc_markdown(
    *,
    doc_id: str,
    report: Dict[str, Any],
    phase_b: Dict[str, Any],
    phase_c: Dict[str, Any],
    phase_e: Dict[str, Any],
    phase_f: Dict[str, Any],
    phase_g: Dict[str, Any],
    selected_pages: List[int],
) -> str:
    lines: List[str] = []
    overview = report
    final_doc = (phase_g.get("output_document") or {})
    lines.append(f"# {overview.get('doc_title') or doc_id}")
    lines.append("")
    lines.append(f"- `doc_id`: `{doc_id}`")
    lines.append(f"- source pdf: `{overview.get('source_pdf') or ''}`")
    lines.append(f"- useful: `{final_doc.get('has_useful_information')}`")
    lines.append(f"- doc match probability: `{final_doc.get('doc_match_probability')}`")
    lines.append(f"- abstention reason: `{final_doc.get('abstention_reason')}`")
    lines.append(f"- selected pages exported: `{', '.join(str(x) for x in selected_pages) or 'none'}`")
    lines.append("")

    lines.append("## Phase B")
    diagnostics = phase_b.get("diagnostics") or {}
    lines.append(f"- docling status: `{((diagnostics.get('docling') or {}).get('status'))}`")
    toc = phase_b.get("table_of_contents") or {}
    lines.append(f"- fitz outline rows: `{len(toc.get('fitz_outline') or [])}`")
    lines.append(f"- docling section headers: `{len(toc.get('docling_section_headers') or [])}`")
    lines.append("")
    lines.append("### TOC preview")
    for row in top_rows(toc.get("fitz_outline") or [], 18):
        lines.append(f"- p{row.get('page')}: {row.get('title')}")
    lines.append("")

    lines.append("## Phase C")
    lines.append(f"- accepted headings: `{len(phase_c.get('accepted_headings') or [])}`")
    lines.append(f"- sections: `{len(phase_c.get('sections') or [])}`")
    lines.append(f"- passages: `{len(phase_c.get('passages') or [])}`")
    lines.append("")
    lines.append("### Accepted headings")
    for row in top_rows(phase_c.get("accepted_headings") or [], 40):
        lines.append(f"- p{row.get('page') or row.get('anchor_page')}: `{row.get('source')}` :: {row.get('title')}")
    lines.append("")
    suspicious = [
        row
        for row in (phase_c.get("accepted_headings") or [])
        if str(row.get("source") or "").startswith("heuristic")
        or str(row.get("source") or "") == "docling"
    ]
    lines.append("### Suspicious accepted headings")
    for row in top_rows(suspicious, 25):
        lines.append(f"- p{row.get('page') or row.get('anchor_page')}: `{row.get('source')}` :: {row.get('title')}")
    if not suspicious:
        lines.append("- none")
    lines.append("")

    lines.append("## Phase E")
    for row in top_rows(phase_e.get("fused_candidates") or [], 15):
        lines.append(
            f"- rank {row.get('fused_rank')}: p{row.get('page_start')}-{row.get('page_end')} :: "
            f"{row.get('title')} :: fused={row.get('fused_score')} :: subpoints={row.get('trusted_subpoint_ids')}"
        )
    lines.append("")

    lines.append("## Phase F")
    for row in top_rows(phase_f.get("rerank_results") or [], 12):
        lines.append(
            f"- rank {row.get('rerank_rank')}: p{row.get('page_start')}-{row.get('page_end')} :: "
            f"{row.get('title')} :: rerank={row.get('rerank_score')} :: cross={row.get('cross_encoder_score')} :: judge={row.get('judge_score')}"
        )
    lines.append("")

    lines.append("## Phase G")
    for row in top_rows(final_doc.get("top_sections") or [], 8):
        lines.append(
            f"- score {row.get('score_0_to_100')}: p{row.get('page_start')}-{row.get('page_end')} :: "
            f"{row.get('title')} :: band={row.get('score_band')} :: support={row.get('support_strength')}"
        )
        preview = str(row.get("evidence_preview") or "").strip()
        if preview:
            lines.append(f"  - evidence: {preview[:700]}")
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_doc_index_html(doc_dir: Path, title: str, markdown_path: Path, selected_pages: List[int]) -> None:
    page_links = "\n".join(
        f"<li><a href='pages/page_{page:04d}.html'>Page {page}</a></li>"
        for page in selected_pages
    ) or "<li>(none)</li>"
    html_text = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; line-height: 1.45; }}
    a {{ color: #0b5ed7; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <p><a href="{html.escape(markdown_path.name)}">inspection.md</a></p>
  <h2>Exported pages</h2>
  <ul>{page_links}</ul>
</body>
</html>
"""
    (doc_dir / "index.html").write_text(html_text, encoding="utf-8")


def audit_run(run_dir: Path, *, output_subdir: str, include_doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    if fitz is None:
        raise RuntimeError(f"PyMuPDF unavailable: {FITZ_IMPORT_ERROR}")
    pdf_reports_dir = run_dir / "pdf_reports"
    output_dir = ensure_dir(run_dir / output_subdir)
    doc_dirs = [path for path in pdf_reports_dir.iterdir() if path.is_dir()]
    if include_doc_ids:
        include = set(include_doc_ids)
        doc_dirs = [path for path in doc_dirs if path.name in include]
    summary_rows: List[Dict[str, Any]] = []
    for doc_dir in sorted(doc_dirs):
        report = read_json(doc_dir / "report.json")
        phase_b = read_json(doc_dir / "phase_b_parser.json") if (doc_dir / "phase_b_parser.json").exists() else {}
        phase_c = read_json(doc_dir / "phase_c_normalized.json") if (doc_dir / "phase_c_normalized.json").exists() else {}
        phase_e = read_json(doc_dir / "phase_e_retrieval.json") if (doc_dir / "phase_e_retrieval.json").exists() else {}
        phase_f = read_json(doc_dir / "phase_f_rerank.json") if (doc_dir / "phase_f_rerank.json").exists() else {}
        phase_g = read_json(doc_dir / "phase_g_final.json") if (doc_dir / "phase_g_final.json").exists() else {}
        source_pdf_value = (
            report.get("source_pdf")
            or ((phase_c.get("document") or {}).get("source_path"))
            or (((phase_b.get("metadata") or {}).get("source_path")))
            or ""
        )
        source_pdf = Path(str(source_pdf_value or "")).resolve() if source_pdf_value else Path()
        out_doc_dir = ensure_dir(output_dir / doc_dir.name)
        selected_pages = choose_pages(phase_c, phase_e, phase_g)
        if source_pdf and source_pdf.exists():
            pdf = fitz.open(source_pdf)
            for page_number in selected_pages:
                write_page_html(pdf, page_number, page_html_path(out_doc_dir, page_number))
        markdown = render_doc_markdown(
            doc_id=doc_dir.name,
            report=report,
            phase_b=phase_b,
            phase_c=phase_c,
            phase_e=phase_e,
            phase_f=phase_f,
            phase_g=phase_g,
            selected_pages=selected_pages,
        )
        markdown_path = out_doc_dir / "inspection.md"
        markdown_path.write_text(markdown, encoding="utf-8")
        render_doc_index_html(out_doc_dir, str(report.get("doc_title") or doc_dir.name), markdown_path, selected_pages)
        summary_rows.append(
            {
                "doc_id": doc_dir.name,
                "doc_title": report.get("doc_title"),
                "source_pdf": str(source_pdf),
                "useful": ((phase_g.get("output_document") or {}).get("has_useful_information")),
                "doc_match_probability": ((phase_g.get("output_document") or {}).get("doc_match_probability")),
                "top_section_title": ((((phase_g.get("output_document") or {}).get("top_sections") or [{}])[0]).get("title")),
                "selected_page_count": len(selected_pages),
                "inspection_markdown": rel(markdown_path, run_dir),
                "inspection_index_html": rel(out_doc_dir / "index.html", run_dir),
            }
        )
    write_json(output_dir / "summary.json", {"run_id": run_dir.name, "doc_count": len(summary_rows), "rows": summary_rows})
    return {"output_dir": output_dir, "summary_rows": summary_rows}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deep audit helper for PDF scan runs.")
    parser.add_argument("--base-dir", default="pdf-scan", help="Path to pdf-scan.")
    parser.add_argument("--run-id", required=True, help="Run id to audit.")
    parser.add_argument("--output-subdir", default="pipeline_deep_audit", help="Output subdirectory under the run.")
    parser.add_argument("--include-doc-id", action="append", default=[], help="Optional doc ids to inspect.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    base_dir = Path(args.base_dir).resolve()
    run_dir = (base_dir / "runs" / str(args.run_id)).resolve()
    result = audit_run(run_dir, output_subdir=str(args.output_subdir), include_doc_ids=list(args.include_doc_id or []))
    print(f"run_id       {run_dir.name}")
    print(f"output_dir   {result['output_dir']}")
    print(f"docs_audited {len(result['summary_rows'])}")
    for row in result["summary_rows"][:20]:
        print(
            f"{row.get('doc_id')} :: useful={row.get('useful')} :: prob={row.get('doc_match_probability')} :: "
            f"top={row.get('top_section_title')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
