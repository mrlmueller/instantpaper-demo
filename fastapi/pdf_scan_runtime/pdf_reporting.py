#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional


PDF_REPORTS_DIRNAME = "pdf_reports"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_jsonl_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    bad_lines = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            bad_lines += 1
            continue
    if bad_lines:
        print(f"[pdf_reporting] skipped {bad_lines} malformed JSONL row(s) in {path}")
    return rows


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def clean_text(text: Any) -> str:
    if text is None:
        s = ""
    else:
        s = str(text)
    s = s.replace("\xad", "")
    s = s.replace("\u00a0", " ")
    s = s.replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def truncate_text(text: Any, max_len: int = 400) -> str:
    s = clean_text(text)
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def href_path(path: Any) -> str:
    return str(path or "").replace("\\", "/")


def to_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def fmt_bool(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "-"


def fmt_num(value: Any, digits: int = 2) -> str:
    if value is None or value == "":
        return "-"
    number = safe_float(value, default=float("nan"))
    if number != number:
        return str(value)
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.{int(digits)}f}"


def fmt_pages(page_start: Any, page_end: Any) -> str:
    if page_start in (None, "") and page_end in (None, ""):
        return "-"
    if page_start == page_end or page_end in (None, ""):
        return str(page_start)
    if page_start in (None, ""):
        return str(page_end)
    return f"{page_start}-{page_end}"


def fmt_list(values: Any, limit: int = 6) -> str:
    items = [clean_text(item) for item in to_list(values) if clean_text(item)]
    if not items:
        return "-"
    if len(items) <= int(limit):
        return ", ".join(items)
    return ", ".join(items[: int(limit)]) + f", +{len(items) - int(limit)} more"


def fmt_score_percent(value: Any) -> str:
    return fmt_num(value, digits=2)


def html_text(text: Any) -> str:
    if text is None:
        return ""
    return html.escape(str(text))


def markdown_text(text: Any) -> str:
    s = clean_text(text)
    s = s.replace("|", "\\|")
    return s or "-"


def render_markdown_table(rows: List[Dict[str, Any]], columns: List[str], labels: Optional[Dict[str, str]] = None) -> str:
    if not rows:
        return "_No data._"
    labels = labels or {}
    header = "| " + " | ".join(labels.get(col, col) for col in columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(markdown_text(row.get(col)) for col in columns) + " |")
    return "\n".join([header, sep] + body)


def render_html_table(rows: List[Dict[str, Any]], columns: List[str], labels: Optional[Dict[str, str]] = None) -> str:
    if not rows:
        return "<p class=\"muted\">No data.</p>"
    labels = labels or {}
    head = "".join(f"<th>{html_text(labels.get(col, col))}</th>" for col in columns)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{html_text(row.get(col))}</td>" for col in columns)
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        "<div class=\"table-wrap\"><table>"
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table></div>"
    )


def render_details_html(title: str, inner_html: str, *, count: Optional[int] = None, open_by_default: bool = False) -> str:
    count_html = f" <span class=\"count-pill\">{html_text(count)}</span>" if count is not None else ""
    open_attr = " open" if open_by_default else ""
    return (
        f"<details class=\"details-card\"{open_attr}>"
        f"<summary>{html_text(title)}{count_html}</summary>"
        f"<div class=\"details-body\">{inner_html}</div>"
        "</details>"
    )


def toc_preview_rows(payload: Dict[str, Any], *, limit: int = 18) -> List[Dict[str, Any]]:
    table_of_contents = dict(payload.get("table_of_contents") or {})
    rows: List[Dict[str, Any]] = []
    for item in list(table_of_contents.get("fitz_outline") or []):
        if len(rows) >= int(limit):
            break
        if isinstance(item, dict):
            rows.append({"source": "fitz", "page": item.get("page") or item.get("page_no") or "-", "title": truncate_text(item.get("title"), 100)})
    for item in list(table_of_contents.get("pypdf_outline") or []):
        if len(rows) >= int(limit):
            break
        if isinstance(item, dict):
            rows.append({"source": "pypdf", "page": item.get("page") or item.get("page_no") or "-", "title": truncate_text(item.get("title"), 100)})
    for item in list(table_of_contents.get("docling_section_headers") or []):
        if len(rows) >= int(limit):
            break
        page = "-"
        prov = list((item.get("prov") or [])) if isinstance(item, dict) else []
        if prov:
            page = (prov[0] or {}).get("page_no") or "-"
        title = ""
        if isinstance(item, dict):
            title = item.get("text") or item.get("orig") or item.get("title") or ""
        if clean_text(title):
            rows.append({"source": "docling", "page": page, "title": truncate_text(title, 100)})
    return rows


def accepted_heading_preview_rows(payload: Dict[str, Any], *, limit: int = 14) -> List[Dict[str, Any]]:
    rows = []
    for item in list(payload.get("accepted_headings") or [])[: int(limit)]:
        rows.append(
            {
                "page": item.get("anchor_page") or item.get("page") or "-",
                "source": item.get("source") or "-",
                "title": truncate_text(item.get("title"), 110),
                "anchor": item.get("anchor_method") or "-",
            }
        )
    return rows


def section_preview_rows(payload: Dict[str, Any], *, limit: int = 18) -> List[Dict[str, Any]]:
    rows = []
    for item in list(payload.get("sections") or [])[: int(limit)]:
        rows.append(
            {
                "pages": fmt_pages(item.get("page_start"), item.get("page_end")),
                "type": item.get("section_type") or "-",
                "eligible": fmt_bool(item.get("retrieval_eligible")),
                "title": truncate_text(item.get("title"), 110),
                "flags": fmt_list(item.get("quality_flags") or [], limit=4),
            }
        )
    return rows


def subpoint_preview_rows(payload: Dict[str, Any], *, limit: int = 10) -> List[Dict[str, Any]]:
    query_plan = dict((payload.get("query_plan") or {}).get("query_plan") or payload.get("query_plan") or {})
    rows = []
    for item in list(query_plan.get("subpoints") or [])[: int(limit)]:
        rows.append(
            {
                "id": item.get("subpoint_id") or "-",
                "label": truncate_text(item.get("label"), 60),
                "must_terms": fmt_list(item.get("must_terms") or [], limit=4),
                "preferred_types": fmt_list(item.get("preferred_section_types") or [], limit=4),
            }
        )
    return rows


def fused_candidate_preview_rows(payload: Dict[str, Any], *, limit: int = 12) -> List[Dict[str, Any]]:
    rows = []
    for item in list(payload.get("fused_candidates") or [])[: int(limit)]:
        rows.append(
            {
                "rank": item.get("fused_rank") or "-",
                "pages": fmt_pages(item.get("page_start"), item.get("page_end")),
                "type": item.get("section_type") or "-",
                "title": truncate_text(item.get("title"), 80),
                "fused_score": fmt_num(item.get("fused_score"), 4),
                "select_score": fmt_num(item.get("selection_score"), 4),
                "support": item.get("supporting_passage_count") or 0,
                "subpoints": fmt_list(item.get("trusted_subpoint_ids") or [], limit=4),
            }
        )
    return rows


def rerank_preview_rows(payload: Dict[str, Any], *, limit: int = 12) -> List[Dict[str, Any]]:
    rows = []
    for item in list(payload.get("rerank_results") or [])[: int(limit)]:
        rows.append(
            {
                "rank": item.get("rerank_rank") or "-",
                "pages": fmt_pages(item.get("page_start"), item.get("page_end")),
                "title": truncate_text(item.get("title"), 80),
                "rerank": fmt_num(item.get("rerank_score"), 4),
                "cross": fmt_num(item.get("cross_encoder_score"), 4),
                "judge": fmt_num(item.get("judge_score"), 2),
                "generic": fmt_bool(item.get("generic_title")),
            }
        )
    return rows


def top_section_preview_rows(payload: Dict[str, Any], *, limit: int = 8) -> List[Dict[str, Any]]:
    ranking = dict(payload.get("per_pdf_ranking") or {})
    top_sections = list(ranking.get("top_sections") or [])
    rows = []
    for item in top_sections[: int(limit)]:
        rows.append(
            {
                "score": fmt_num(item.get("score_0_to_100"), 2),
                "band": item.get("score_band") or "-",
                "support": item.get("support_strength") or "-",
                "pages": fmt_pages(item.get("page_start"), item.get("page_end")),
                "title": truncate_text(item.get("title"), 80),
                "coverage": fmt_list(item.get("subpoint_coverage_ids") or [], limit=4),
            }
        )
    return rows


def proposal_preview_rows(payload: Dict[str, Any], *, limit: int = 30) -> List[Dict[str, Any]]:
    rows = []
    for item in list(payload.get("section_proposals") or [])[: int(limit)]:
        rows.append(
            {
                "page": item.get("anchor_page") or item.get("page") or "-",
                "source": item.get("source") or "-",
                "title": truncate_text(item.get("title"), 90),
                "accepted": fmt_bool(item.get("accepted")),
                "reason": truncate_text(item.get("rejection_reason"), 48),
            }
        )
    return rows


def lane_summary_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for lane_name, lane_rows in sorted(dict(payload.get("lane_candidates") or {}).items()):
        top_title = "-"
        top_score = "-"
        if lane_rows:
            top = lane_rows[0]
            top_title = truncate_text(top.get("title"), 72)
            top_score = fmt_num(top.get("score") or top.get("best_lane_score"), 4)
        rows.append(
            {
                "lane": lane_name,
                "count": len(list(lane_rows or [])),
                "top_score": top_score,
                "top_title": top_title,
            }
        )
    return rows


def judge_preview_rows(payload: Dict[str, Any], *, limit: int = 20) -> List[Dict[str, Any]]:
    rows = []
    for item in list(payload.get("llm_judge_rows") or [])[: int(limit)]:
        rows.append(
            {
                "title": truncate_text(item.get("title"), 72),
                "judge": fmt_num(item.get("judge_score"), 2),
                "useful": item.get("judge_usefulness_raw") if item.get("judge_usefulness_raw") is not None else "-",
                "topic": item.get("judge_topic_match_raw") if item.get("judge_topic_match_raw") is not None else "-",
                "coverage": item.get("judge_coverage_raw") if item.get("judge_coverage_raw") is not None else "-",
                "violations": fmt_list(item.get("judge_exclusion_violations") or [], limit=4),
            }
        )
    return rows


def full_section_score_rows(payload: Dict[str, Any], *, limit: int = 40) -> List[Dict[str, Any]]:
    rows = []
    for item in list(payload.get("section_scores") or [])[: int(limit)]:
        rows.append(
            {
                "rank": item.get("global_rank") or "-",
                "score": fmt_num(item.get("score_0_to_100"), 2),
                "band": item.get("score_band") or "-",
                "support": item.get("support_strength") or "-",
                "pages": fmt_pages(item.get("page_start"), item.get("page_end")),
                "title": truncate_text(item.get("title"), 80),
                "coverage": fmt_list(item.get("subpoint_coverage_ids") or [], limit=4),
            }
        )
    return rows


def source_anchor_rows(payload: Dict[str, Any], *, limit: int = 30) -> List[Dict[str, Any]]:
    query_plan = dict((payload.get("query_plan") or {}).get("query_plan") or payload.get("query_plan") or {})
    rows = []
    for idx, item in enumerate(list(query_plan.get("source_anchors") or [])[: int(limit)], 1):
        rows.append({"n": idx, "anchor": truncate_text(item, 120)})
    return rows


def artifact_file_rows(payload: Dict[str, Any], *, limit: int = 80) -> List[Dict[str, Any]]:
    rows = []
    for idx, item in enumerate(list(payload.get("artifact_files") or [])[: int(limit)], 1):
        rows.append({"n": idx, "file": item})
    return rows


def evidence_preview_blocks(payload: Dict[str, Any], *, limit_sections: int = 3, limit_passages: int = 2) -> List[Dict[str, str]]:
    ranking = dict(payload.get("per_pdf_ranking") or {})
    blocks: List[Dict[str, str]] = []
    for section in list(ranking.get("top_sections") or [])[: int(limit_sections)]:
        title = clean_text(section.get("title") or "")
        snippets = []
        for passage in list(section.get("evidence_preview") or [])[: int(limit_passages)]:
            pages = clean_text(passage.get("pages") or "")
            text = truncate_text(passage.get("text"), 260)
            snippets.append(f"pp. {pages}: {text}")
        if title and snippets:
            blocks.append({"title": title, "snippets": "\n".join(snippets)})
    return blocks


def phase_b_summary(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    metadata = dict(payload.get("metadata") or {})
    coverage = dict(metadata.get("text_coverage") or {})
    docling = dict(metadata.get("docling") or {})
    return [
        {"metric": "Page count", "value": metadata.get("page_count") or "-"},
        {"metric": "Readable without OCR", "value": fmt_bool(coverage.get("readable_without_ocr"))},
        {"metric": "Pages with text %", "value": fmt_num(coverage.get("percent_pages_with_text"), 2)},
        {"metric": "Docling status", "value": docling.get("status") or "-"},
        {"metric": "Docling section headers", "value": ((docling.get("document_summary") or {}).get("section_header_count") or 0)},
        {"metric": "Outline count", "value": safe_int(((metadata.get("outline_counts") or {}).get("fitz") or 0)) + safe_int(((metadata.get("outline_counts") or {}).get("pypdf") or 0))},
    ]


def phase_c_summary(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    document = dict(payload.get("document") or {})
    return [
        {"metric": "Strategy", "value": document.get("strategy") or "-"},
        {"metric": "Section coverage %", "value": fmt_num(document.get("section_coverage_pct"), 2)},
        {"metric": "Accepted headings", "value": document.get("accepted_heading_count") or 0},
        {"metric": "Sections", "value": document.get("section_count") or 0},
        {"metric": "Passages", "value": (payload.get("document") or {}).get("passage_count") or len(list(payload.get("passages") or []))},
        {"metric": "Fallback anchors", "value": document.get("fallback_anchor_count") or 0},
        {"metric": "Retrieval-suppressed sections", "value": document.get("retrieval_suppressed_section_count") or 0},
        {"metric": "Metadata-stripped sections", "value": document.get("metadata_stripped_section_count") or 0},
    ]


def phase_d_summary(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    query_plan = dict((payload.get("query_plan") or {}).get("query_plan") or payload.get("query_plan") or {})
    return [
        {"metric": "Chapter summary", "value": truncate_text(query_plan.get("chapter_summary"), 160)},
        {"metric": "Must terms", "value": fmt_list(query_plan.get("must_terms") or [], limit=8)},
        {"metric": "Should terms", "value": fmt_list(query_plan.get("should_terms") or [], limit=8)},
        {"metric": "Subpoints", "value": len(list(query_plan.get("subpoints") or []))},
        {"metric": "Preferred section types", "value": fmt_list(query_plan.get("preferred_section_types") or [], limit=6)},
        {"metric": "Penalized section types", "value": fmt_list(query_plan.get("penalized_section_types") or [], limit=6)},
    ]


def phase_e_summary(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    support = dict(payload.get("phase_e_subpoint_support") or {})
    return [
        {"metric": "Fused candidates", "value": len(list(payload.get("fused_candidates") or []))},
        {"metric": "Lane count", "value": len(dict(payload.get("lane_candidates") or {}))},
        {"metric": "Active subpoints in doc", "value": fmt_list(payload.get("doc_active_subpoints") or [], limit=6)},
        {"metric": "Supported subpoints", "value": fmt_list(support.get("active_subpoint_ids") or [], limit=6)},
    ]


def phase_f_summary(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    judged = [row for row in list(payload.get("rerank_results") or []) if row.get("judge_score") is not None]
    return [
        {"metric": "Reranked candidates", "value": len(list(payload.get("rerank_results") or []))},
        {"metric": "Cross-encoder rows", "value": len(list(payload.get("cross_encoder_rows") or []))},
        {"metric": "Judge rows", "value": len(list(payload.get("llm_judge_rows") or []))},
        {"metric": "Used judge scores", "value": len(judged)},
    ]


def phase_g_summary(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    features = dict(payload.get("doc_features") or {})
    return [
        {"metric": "Useful PDF", "value": fmt_bool(features.get("has_useful_information"))},
        {"metric": "Doc match probability", "value": fmt_num(features.get("doc_match_probability"), 2)},
        {"metric": "Top section", "value": truncate_text(features.get("top_section_title"), 90)},
        {"metric": "Top section score", "value": fmt_num(features.get("top_section_score"), 2)},
        {"metric": "Top-3 mean score", "value": fmt_num(features.get("top3_mean_score"), 2)},
        {"metric": "Covered subpoints", "value": fmt_list(features.get("covered_subpoint_ids") or [], limit=6)},
        {"metric": "Abstention reason", "value": features.get("abstention_reason") or "-"},
    ]


DOC_REPORT_CSS = """
body { font-family: "Segoe UI", Tahoma, sans-serif; margin: 0; background: #f4f6f8; color: #18212b; }
.page { max-width: 1400px; margin: 0 auto; padding: 24px; }
h1, h2, h3 { margin: 0 0 12px; line-height: 1.2; }
h1 { font-size: 30px; }
h2 { font-size: 22px; margin-top: 28px; }
h3 { font-size: 17px; margin-top: 20px; }
.muted { color: #5f6b7a; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 18px; }
.chip { display: inline-block; padding: 4px 10px; border-radius: 999px; background: #dce9f5; color: #17324d; font-size: 12px; font-weight: 600; }
.chip.yes { background: #d8f0df; color: #17582d; }
.chip.no { background: #f6dbdb; color: #7a1f1f; }
.chip.warn { background: #f8e9c9; color: #69480d; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }
.card { background: #fff; border: 1px solid #d8e0e8; border-radius: 14px; padding: 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
.metric-label { font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: #6a7887; margin-bottom: 6px; }
.metric-value { font-size: 22px; font-weight: 700; color: #142435; }
.section { margin-top: 22px; }
.table-wrap { overflow-x: auto; border: 1px solid #d8e0e8; border-radius: 12px; background: #fff; }
table { width: 100%; border-collapse: collapse; min-width: 720px; }
th, td { padding: 10px 12px; border-bottom: 1px solid #e7edf3; text-align: left; vertical-align: top; }
th { background: #f8fafc; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: #5d6a79; }
tr:last-child td { border-bottom: none; }
code, pre { font-family: "Cascadia Code", Consolas, monospace; }
pre { white-space: pre-wrap; word-break: break-word; background: #fff; border: 1px solid #d8e0e8; border-radius: 12px; padding: 14px; }
.links a { color: #0b63b6; text-decoration: none; margin-right: 12px; }
.links a:hover { text-decoration: underline; }
.two-col { display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 18px; }
.note { background: #fff8df; border: 1px solid #ecdba1; border-radius: 12px; padding: 12px 14px; }
.evidence { background: #fff; border: 1px solid #d8e0e8; border-radius: 12px; padding: 12px 14px; margin-bottom: 12px; }
.details-card { margin-top: 12px; border: 1px solid #d8e0e8; border-radius: 12px; background: #ffffff; overflow: hidden; }
.details-card summary { cursor: pointer; list-style: none; padding: 12px 14px; font-weight: 600; color: #17324d; background: #f8fafc; display: flex; align-items: center; gap: 10px; }
.details-card summary::-webkit-details-marker { display: none; }
.details-card summary::before { content: "▸"; color: #4a6076; font-size: 14px; }
.details-card[open] summary::before { content: "▾"; }
.details-body { padding: 12px; border-top: 1px solid #e7edf3; }
.count-pill { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #dce9f5; color: #17324d; font-size: 12px; font-weight: 700; }
@media (max-width: 1000px) { .two-col { grid-template-columns: 1fr; } .page { padding: 16px; } h1 { font-size: 24px; } }
"""


def slugify(text: Any, max_len: int = 64) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(text or "").strip().lower()).strip("_")
    s = re.sub(r"_+", "_", s)
    return (s or "doc")[: int(max_len)]


def compute_doc_id_from_manifest_row(manifest_row: Dict[str, Any]) -> str:
    stem = slugify(Path(str(manifest_row.get("file_name") or "document.pdf")).stem, max_len=48)
    digest = str(manifest_row.get("sha256") or "")[:12] or "docbundle0000"
    return f"{stem}-{digest}"


def maybe_read_json(path: Path) -> Optional[Any]:
    try:
        return read_json(path)
    except Exception:
        return None


def rel_to_run(run_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(run_dir))
    except Exception:
        return str(path)


def list_relative_files(root: Path, run_dir: Path) -> List[str]:
    if not root.exists():
        return []
    return sorted(rel_to_run(run_dir, path) for path in root.iterdir() if path.is_file())


def summarize_phase_availability(run_dir: Path) -> Dict[str, bool]:
    return {
        "phase_a": (run_dir / "phase_a" / "phase_a_summary.json").exists(),
        "phase_b": (run_dir / "parser" / "phase_b_summary.json").exists(),
        "phase_c": (run_dir / "normalized" / "phase_c_summary.json").exists(),
        "phase_d": (run_dir / "retrieval" / "phase_d_summary.json").exists(),
        "phase_e": (run_dir / "retrieval" / "phase_e_summary.json").exists(),
        "phase_f": (run_dir / "rerank" / "phase_f_summary.json").exists(),
        "phase_g": (run_dir / "final" / "phase_g_summary.json").exists(),
    }


def build_run_ctx_from_dir(run_dir: Path) -> Any:
    run_dir = run_dir.resolve()
    return SimpleNamespace(
        run_id=run_dir.name,
        run_dir=run_dir,
        artifacts=SimpleNamespace(
            parser_dir=run_dir / "parser",
            normalized_dir=run_dir / "normalized",
            retrieval_dir=run_dir / "retrieval",
            rerank_dir=run_dir / "rerank",
            final_dir=run_dir / "final",
        ),
    )


def load_global_state(run_ctx: Any) -> Dict[str, Any]:
    run_dir = Path(run_ctx.run_dir)
    parser_dir = Path(run_ctx.artifacts.parser_dir)
    normalized_dir = Path(run_ctx.artifacts.normalized_dir)
    retrieval_dir = Path(run_ctx.artifacts.retrieval_dir)
    rerank_dir = Path(run_ctx.artifacts.rerank_dir)
    final_dir = Path(run_ctx.artifacts.final_dir)

    phase_a_config = maybe_read_json(run_dir / "config.json") or {}
    pdf_manifest = maybe_read_json(run_dir / "pdf_manifest.json") or {}
    manifest_rows = list(pdf_manifest.get("pdfs") or [])
    manifest_by_doc_id = {compute_doc_id_from_manifest_row(row): dict(row) for row in manifest_rows}

    parser_index_rows = read_jsonl_rows(parser_dir / "parsed_document_bundles.jsonl")
    parser_index_by_doc_id = {str(row.get("doc_id") or ""): row for row in parser_index_rows if str(row.get("doc_id") or "")}

    normalized_index_rows = read_jsonl_rows(normalized_dir / "normalized_document_bundles.jsonl")
    normalized_index_by_doc_id = {str(row.get("doc_id") or ""): row for row in normalized_index_rows if str(row.get("doc_id") or "")}

    document_rows = read_jsonl_rows(normalized_dir / "documents.jsonl")
    document_by_doc_id = {str(row.get("doc_id") or ""): row for row in document_rows if str(row.get("doc_id") or "")}

    fused_rows = read_jsonl_rows(retrieval_dir / "fused_candidates.jsonl")
    rerank_rows = read_jsonl_rows(rerank_dir / "rerank_results.jsonl")
    cross_encoder_rows = read_jsonl_rows(rerank_dir / "cross_encoder.jsonl")
    llm_judge_rows = read_jsonl_rows(rerank_dir / "llm_judge.jsonl")
    section_score_rows = read_jsonl_rows(final_dir / "section_scores.jsonl")
    doc_feature_rows = read_jsonl_rows(final_dir / "doc_features.jsonl")

    grouped = {
        "fused_rows_by_doc": group_rows_by_doc(fused_rows),
        "rerank_rows_by_doc": group_rows_by_doc(rerank_rows),
        "cross_encoder_by_doc": group_rows_by_doc(cross_encoder_rows),
        "llm_judge_by_doc": group_rows_by_doc(llm_judge_rows),
        "section_scores_by_doc": group_rows_by_doc(section_score_rows),
    }

    lane_rows_by_doc: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(dict)
    lanes_dir = retrieval_dir / "lanes"
    if lanes_dir.exists():
        for lane_path in sorted(lanes_dir.glob("*.jsonl")):
            lane_name = lane_path.stem
            for row in read_jsonl_rows(lane_path):
                doc_id = str(row.get("doc_id") or "")
                if not doc_id:
                    continue
                lane_rows_by_doc[doc_id].setdefault(lane_name, []).append(row)

    doc_features_by_doc_id = {str(row.get("doc_id") or ""): row for row in doc_feature_rows if str(row.get("doc_id") or "")}

    per_pdf_rankings = maybe_read_json(final_dir / "per_pdf_rankings.json") or {}
    per_pdf_docs_by_doc_id = {
        str(row.get("doc_id") or ""): row
        for row in list(per_pdf_rankings.get("documents") or [])
        if str(row.get("doc_id") or "")
    }

    global_rankings = maybe_read_json(final_dir / "global_rankings.json") or {}
    global_rows_by_doc = group_rows_by_doc(list(global_rankings.get("rows") or []))

    return {
        "run_dir": run_dir,
        "phase_a_config": phase_a_config,
        "pdf_manifest": pdf_manifest,
        "manifest_rows": manifest_rows,
        "manifest_by_doc_id": manifest_by_doc_id,
        "parser_index_by_doc_id": parser_index_by_doc_id,
        "normalized_index_by_doc_id": normalized_index_by_doc_id,
        "document_by_doc_id": document_by_doc_id,
        "grouped": grouped,
        "lane_rows_by_doc": lane_rows_by_doc,
        "doc_features_by_doc_id": doc_features_by_doc_id,
        "per_pdf_docs_by_doc_id": per_pdf_docs_by_doc_id,
        "global_rows_by_doc": global_rows_by_doc,
        "query_plan": maybe_read_json(run_dir / "query_plan.json") or {},
        "query_views": maybe_read_json(retrieval_dir / "query_views.json") or {},
        "planner_prompt": maybe_read_json(retrieval_dir / "planner_prompt.json") or {},
        "planner_response": maybe_read_json(retrieval_dir / "planner_response.json") or {},
        "source_anchor_inventory": maybe_read_json(retrieval_dir / "source_anchor_inventory.json") or {},
        "phase_d_corpus_support": maybe_read_json(retrieval_dir / "phase_d_corpus_support.json") or {},
        "phase_e_subpoint_support": maybe_read_json(retrieval_dir / "phase_e_subpoint_support.json") or {},
        "final_output": maybe_read_json(final_dir / "output.json") or {},
        "phase_availability": summarize_phase_availability(run_dir),
    }


def group_rows_by_doc(rows: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        doc_id = str(row.get("doc_id") or "")
        if not doc_id:
            continue
        grouped[doc_id].append(row)
    return grouped


def collect_doc_ids(state: Dict[str, Any]) -> List[str]:
    doc_ids = set(state["manifest_by_doc_id"].keys())
    doc_ids.update(state["parser_index_by_doc_id"].keys())
    doc_ids.update(state["normalized_index_by_doc_id"].keys())
    doc_ids.update(state["document_by_doc_id"].keys())
    doc_ids.update(state["grouped"]["fused_rows_by_doc"].keys())
    doc_ids.update(state["grouped"]["rerank_rows_by_doc"].keys())
    doc_ids.update(state["doc_features_by_doc_id"].keys())
    return sorted(doc_id for doc_id in doc_ids if doc_id)


def build_phase_a_payload(doc_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    config = dict(state.get("phase_a_config") or {})
    manifest_row = dict(state["manifest_by_doc_id"].get(doc_id) or {})
    return {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_a",
        "doc_id": doc_id,
        "chapter_title": clean_text(config.get("chapter_title")),
        "chapter_spec_text": clean_text(config.get("chapter_spec_text")),
        "pipeline_version": config.get("pipeline_version"),
        "input_mode": config.get("input_mode"),
        "manifest_row": manifest_row,
    }


def build_phase_b_payload(doc_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    run_dir = state["run_dir"]
    bundle_row = dict(state["parser_index_by_doc_id"].get(doc_id) or {})
    doc_dir = run_dir / "parser" / doc_id
    metadata = maybe_read_json(doc_dir / "metadata.json") or {}
    diagnostics = maybe_read_json(doc_dir / "diagnostics.json") or {}
    return {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_b",
        "doc_id": doc_id,
        "bundle_row": bundle_row,
        "metadata": metadata,
        "diagnostics": diagnostics,
        "table_of_contents": {
            "fitz_outline": ((metadata.get("fitz") or {}).get("outline") or []),
            "pypdf_outline": ((metadata.get("pypdf") or {}).get("outline") or []),
            "docling_section_headers": ((metadata.get("docling") or {}).get("section_headers") or []),
        },
        "artifact_files": list_relative_files(doc_dir, run_dir),
    }


def build_phase_c_payload(doc_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    run_dir = state["run_dir"]
    bundle_row = dict(state["normalized_index_by_doc_id"].get(doc_id) or {})
    doc_dir = run_dir / "normalized" / doc_id
    document = maybe_read_json(doc_dir / "document.json") or dict(state["document_by_doc_id"].get(doc_id) or {})
    diagnostics = maybe_read_json(doc_dir / "phase_c_diagnostics.json") or {}
    section_proposals = read_jsonl_rows(doc_dir / "section_proposals.jsonl")
    accepted_headings = read_jsonl_rows(doc_dir / "accepted_headings.jsonl")
    sections = read_jsonl_rows(doc_dir / "sections.jsonl")
    passages = read_jsonl_rows(doc_dir / "passages.jsonl")
    return {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_c",
        "doc_id": doc_id,
        "bundle_row": bundle_row,
        "document": document,
        "diagnostics": diagnostics,
        "section_proposals": section_proposals,
        "accepted_headings": accepted_headings,
        "sections": sections,
        "passages": passages,
        "artifact_files": list_relative_files(doc_dir, run_dir),
    }


def build_phase_d_payload(doc_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    run_dir = state["run_dir"]
    retrieval_dir = run_dir / "retrieval"
    return {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_d",
        "doc_id": doc_id,
        "query_plan": state.get("query_plan") or {},
        "query_views": state.get("query_views") or {},
        "planner_prompt": state.get("planner_prompt") or {},
        "planner_response": state.get("planner_response") or {},
        "source_anchor_inventory": state.get("source_anchor_inventory") or {},
        "phase_d_corpus_support": state.get("phase_d_corpus_support") or {},
        "artifact_files": list_relative_files(retrieval_dir, run_dir),
    }


def build_phase_e_payload(doc_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    run_dir = state["run_dir"]
    fused_rows = sorted(
        list(state["grouped"]["fused_rows_by_doc"].get(doc_id) or []),
        key=lambda row: int(row.get("fused_rank") or 10_000),
    )
    lane_rows = {
        lane: sorted(rows, key=lambda row: float(row.get("score") or row.get("best_lane_score") or 0.0), reverse=True)
        for lane, rows in dict(state["lane_rows_by_doc"].get(doc_id) or {}).items()
    }
    supported = dict(state.get("phase_e_subpoint_support") or {})
    return {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_e",
        "doc_id": doc_id,
        "fused_candidates": fused_rows,
        "lane_candidates": lane_rows,
        "phase_e_subpoint_support": supported,
        "doc_active_subpoints": sorted(
            {
                str(subpoint_id)
                for row in fused_rows
                for subpoint_id in list(row.get("trusted_subpoint_ids") or [])
                if str(subpoint_id)
            }
        ),
        "artifact_files": list_relative_files(run_dir / "retrieval", run_dir),
    }


def build_phase_f_payload(doc_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    run_dir = state["run_dir"]
    rerank_rows = sorted(
        list(state["grouped"]["rerank_rows_by_doc"].get(doc_id) or []),
        key=lambda row: int(row.get("rerank_rank") or 10_000),
    )
    cross_encoder_rows = sorted(
        list(state["grouped"]["cross_encoder_by_doc"].get(doc_id) or []),
        key=lambda row: float(row.get("cross_encoder_score") or 0.0),
        reverse=True,
    )
    llm_judge_rows = list(state["grouped"]["llm_judge_by_doc"].get(doc_id) or [])
    return {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_f",
        "doc_id": doc_id,
        "rerank_results": rerank_rows,
        "cross_encoder_rows": cross_encoder_rows,
        "llm_judge_rows": llm_judge_rows,
        "artifact_files": list_relative_files(run_dir / "rerank", run_dir),
    }


def build_phase_g_payload(doc_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    run_dir = state["run_dir"]
    return {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_g",
        "doc_id": doc_id,
        "doc_features": dict(state["doc_features_by_doc_id"].get(doc_id) or {}),
        "per_pdf_ranking": dict(state["per_pdf_docs_by_doc_id"].get(doc_id) or {}),
        "section_scores": sorted(
            list(state["grouped"]["section_scores_by_doc"].get(doc_id) or []),
            key=lambda row: int(row.get("global_rank") or 10_000),
        ),
        "global_rankings": sorted(
            list(state["global_rows_by_doc"].get(doc_id) or []),
            key=lambda row: int(row.get("global_rank") or 10_000),
        ),
        "output_document": next(
            (
                row
                for row in list((state.get("final_output") or {}).get("documents") or [])
                if str(row.get("doc_id") or "") == doc_id
            ),
            {},
        ),
        "artifact_files": list_relative_files(run_dir / "final", run_dir),
    }


def write_doc_report_files(doc_dir: Path, overview: Dict[str, Any], phase_payloads: Dict[str, Dict[str, Any]]) -> None:
    write_json(doc_dir / "report.json", overview)
    write_text(doc_dir / "report.md", build_doc_markdown(overview, phase_payloads))
    write_text(doc_dir / "report.html", build_doc_html(overview, phase_payloads))
    for phase_name, payload in phase_payloads.items():
        write_json(doc_dir / f"{phase_name}.json", payload)


def build_doc_markdown(overview: Dict[str, Any], phase_payloads: Dict[str, Dict[str, Any]]) -> str:
    phase_b = phase_payloads["phase_b_parser"]
    phase_c = phase_payloads["phase_c_normalized"]
    phase_d = phase_payloads["phase_d_query_context"]
    phase_e = phase_payloads["phase_e_retrieval"]
    phase_f = phase_payloads["phase_f_rerank"]
    phase_g = phase_payloads["phase_g_final"]

    lines = [
        f"# PDF Review - {clean_text(overview.get('doc_title') or overview.get('doc_id') or 'Untitled PDF')}",
        "",
        f"- Run ID: `{overview.get('run_id')}`",
        f"- Doc ID: `{overview.get('doc_id')}`",
        f"- Source PDF: `{overview.get('source_pdf')}`",
        f"- Last Updated Phase: `{overview.get('last_updated_phase')}`",
        "",
        "## At A Glance",
        render_markdown_table(
            [
                {"metric": "Useful PDF", "value": fmt_bool(overview.get("has_useful_information"))},
                {"metric": "Doc match probability", "value": fmt_num(overview.get("doc_match_probability"), 2)},
                {"metric": "Page count", "value": overview.get("page_count")},
                {"metric": "Section count", "value": overview.get("section_count")},
                {"metric": "Passage count", "value": overview.get("passage_count")},
                {"metric": "Top section", "value": clean_text(overview.get("top_section_title")) or "-"},
                {"metric": "Top section score", "value": fmt_num(overview.get("top_section_score"), 2)},
            ],
            ["metric", "value"],
            {"metric": "Metric", "value": "Value"},
        ),
        "",
        "## Quick Links",
        "- `report.html`",
    ]
    for file_name in list(overview.get("report_files") or []):
        if file_name != "report.html":
            lines.append(f"- `{file_name}`")

    lines.extend(
        [
            "",
            "## Phase B - Parsing",
            render_markdown_table(phase_b_summary(phase_b), ["metric", "value"], {"metric": "Metric", "value": "Value"}),
            "",
            "### TOC / Heading Preview",
            render_markdown_table(toc_preview_rows(phase_b), ["source", "page", "title"], {"source": "Source", "page": "Page", "title": "Title"}),
            "",
            "## Phase C - Normalization",
            render_markdown_table(phase_c_summary(phase_c), ["metric", "value"], {"metric": "Metric", "value": "Value"}),
            "",
            "### Accepted Headings",
            render_markdown_table(accepted_heading_preview_rows(phase_c), ["page", "source", "title", "anchor"], {"page": "Page", "source": "Source", "title": "Title", "anchor": "Anchor"}),
            "",
            "### Final Sections",
            render_markdown_table(section_preview_rows(phase_c), ["pages", "type", "eligible", "title", "flags"], {"pages": "Pages", "type": "Type", "eligible": "Eligible", "title": "Title", "flags": "Flags"}),
            "",
            "## Phase D - Query Plan",
            render_markdown_table(phase_d_summary(phase_d), ["metric", "value"], {"metric": "Metric", "value": "Value"}),
            "",
            "### Subpoints",
            render_markdown_table(subpoint_preview_rows(phase_d), ["id", "label", "must_terms", "preferred_types"], {"id": "ID", "label": "Label", "must_terms": "Must Terms", "preferred_types": "Preferred Types"}),
            "",
            "## Phase E - Retrieval",
            render_markdown_table(phase_e_summary(phase_e), ["metric", "value"], {"metric": "Metric", "value": "Value"}),
            "",
            "### Top Fused Candidates",
            render_markdown_table(fused_candidate_preview_rows(phase_e), ["rank", "pages", "type", "title", "fused_score", "select_score", "support", "subpoints"], {"rank": "Rank", "pages": "Pages", "type": "Type", "title": "Title", "fused_score": "Fused", "select_score": "Select", "support": "Support", "subpoints": "Subpoints"}),
            "",
            "## Phase F - Rerank",
            render_markdown_table(phase_f_summary(phase_f), ["metric", "value"], {"metric": "Metric", "value": "Value"}),
            "",
            "### Top Reranked Sections",
            render_markdown_table(rerank_preview_rows(phase_f), ["rank", "pages", "title", "rerank", "cross", "judge", "generic"], {"rank": "Rank", "pages": "Pages", "title": "Title", "rerank": "Rerank", "cross": "Cross", "judge": "Judge", "generic": "Generic"}),
            "",
            "## Phase G - Final Decision",
            render_markdown_table(phase_g_summary(phase_g), ["metric", "value"], {"metric": "Metric", "value": "Value"}),
            "",
            "### Top Final Sections",
            render_markdown_table(top_section_preview_rows(phase_g), ["score", "band", "support", "pages", "title", "coverage"], {"score": "Score", "band": "Band", "support": "Support", "pages": "Pages", "title": "Title", "coverage": "Coverage"}),
            "",
            "### Evidence Preview",
        ]
    )
    for block in evidence_preview_blocks(phase_g):
        lines.extend([f"#### {markdown_text(block['title'])}", "", block["snippets"], ""])
    if not evidence_preview_blocks(phase_g):
        lines.append("_No evidence preview._")
    return "\n".join(lines).rstrip() + "\n"


def build_doc_html(overview: Dict[str, Any], phase_payloads: Dict[str, Dict[str, Any]]) -> str:
    phase_b = phase_payloads["phase_b_parser"]
    phase_c = phase_payloads["phase_c_normalized"]
    phase_d = phase_payloads["phase_d_query_context"]
    phase_e = phase_payloads["phase_e_retrieval"]
    phase_f = phase_payloads["phase_f_rerank"]
    phase_g = phase_payloads["phase_g_final"]
    quick_links = ["report.json", "report.md"] + [f for f in list(overview.get("report_files") or []) if f not in {"report.json", "report.md", "report.html"}]
    toc_rows_preview = toc_preview_rows(phase_b)
    toc_rows_all = toc_preview_rows(phase_b, limit=5000)
    accepted_rows_preview = accepted_heading_preview_rows(phase_c)
    accepted_rows_all = accepted_heading_preview_rows(phase_c, limit=5000)
    section_rows_preview = section_preview_rows(phase_c)
    section_rows_all = section_preview_rows(phase_c, limit=5000)
    proposal_rows_all = proposal_preview_rows(phase_c, limit=5000)
    subpoint_rows_preview = subpoint_preview_rows(phase_d)
    source_anchor_all = source_anchor_rows(phase_d, limit=5000)
    fused_rows_preview = fused_candidate_preview_rows(phase_e)
    fused_rows_all = fused_candidate_preview_rows(phase_e, limit=5000)
    lane_rows_all = lane_summary_rows(phase_e)
    rerank_rows_preview = rerank_preview_rows(phase_f)
    rerank_rows_all = rerank_preview_rows(phase_f, limit=5000)
    judge_rows_all = judge_preview_rows(phase_f, limit=5000)
    final_rows_preview = top_section_preview_rows(phase_g)
    final_rows_all = full_section_score_rows(phase_g, limit=5000)
    phase_b_artifacts = artifact_file_rows(phase_b, limit=5000)
    phase_c_artifacts = artifact_file_rows(phase_c, limit=5000)
    phase_e_artifacts = artifact_file_rows(phase_e, limit=5000)
    phase_f_artifacts = artifact_file_rows(phase_f, limit=5000)
    phase_g_artifacts = artifact_file_rows(phase_g, limit=5000)
    chips = []
    chips.append(f"<span class=\"chip {'yes' if overview.get('has_useful_information') else 'no'}\">useful: {html_text(fmt_bool(overview.get('has_useful_information')))}</span>")
    for phase_name, available in dict(overview.get("available_phases") or {}).items():
        chips.append(f"<span class=\"chip {'yes' if available else 'warn'}\">{html_text(phase_name)}: {html_text(fmt_bool(available))}</span>")
    overview_cards = [
        ("Useful PDF", fmt_bool(overview.get("has_useful_information"))),
        ("Doc match probability", fmt_num(overview.get("doc_match_probability"), 2)),
        ("Page count", overview.get("page_count")),
        ("Section count", overview.get("section_count")),
        ("Passage count", overview.get("passage_count")),
        ("Top section score", fmt_num(overview.get("top_section_score"), 2)),
    ]
    card_html = "".join(
        f"<div class=\"card\"><div class=\"metric-label\">{html_text(label)}</div><div class=\"metric-value\">{html_text(value)}</div></div>"
        for label, value in overview_cards
    )
    evidence_blocks = []
    for block in evidence_preview_blocks(phase_g):
        evidence_blocks.append(
            "<div class=\"evidence\">"
            f"<h3>{html_text(block['title'])}</h3>"
            f"<pre>{html_text(block['snippets'])}</pre>"
            "</div>"
        )
    if not evidence_blocks:
        evidence_blocks.append("<p class=\"muted\">No evidence preview.</p>")
    phase_b_block = (
        "<div class=\"section\"><h2>Phase B - Parsing</h2>"
        + render_html_table(phase_b_summary(phase_b), ["metric", "value"], {"metric": "Metric", "value": "Value"})
        + "<h3>TOC / Heading Preview</h3>"
        + render_html_table(toc_rows_preview, ["source", "page", "title"], {"source": "Source", "page": "Page", "title": "Title"})
        + render_details_html(
            "Show all TOC / heading rows",
            render_html_table(toc_rows_all, ["source", "page", "title"], {"source": "Source", "page": "Page", "title": "Title"}),
            count=len(toc_rows_all),
        )
        + render_details_html(
            "Show parser artifact files",
            render_html_table(phase_b_artifacts, ["n", "file"], {"n": "#", "file": "Artifact"}),
            count=len(phase_b_artifacts),
        )
        + "</div>"
    )
    phase_c_block = (
        "<div class=\"section\"><h2>Phase C - Normalization</h2>"
        + render_html_table(phase_c_summary(phase_c), ["metric", "value"], {"metric": "Metric", "value": "Value"})
        + "<h3>Accepted Headings</h3>"
        + render_html_table(accepted_rows_preview, ["page", "source", "title", "anchor"], {"page": "Page", "source": "Source", "title": "Title", "anchor": "Anchor"})
        + render_details_html(
            "Show all accepted headings",
            render_html_table(accepted_rows_all, ["page", "source", "title", "anchor"], {"page": "Page", "source": "Source", "title": "Title", "anchor": "Anchor"}),
            count=len(accepted_rows_all),
        )
        + "<h3>Final Sections</h3>"
        + render_html_table(section_rows_preview, ["pages", "type", "eligible", "title", "flags"], {"pages": "Pages", "type": "Type", "eligible": "Eligible", "title": "Title", "flags": "Flags"})
        + render_details_html(
            "Show all final sections",
            render_html_table(section_rows_all, ["pages", "type", "eligible", "title", "flags"], {"pages": "Pages", "type": "Type", "eligible": "Eligible", "title": "Title", "flags": "Flags"}),
            count=len(section_rows_all),
        )
        + render_details_html(
            "Show section proposals",
            render_html_table(proposal_rows_all, ["page", "source", "title", "accepted", "reason"], {"page": "Page", "source": "Source", "title": "Title", "accepted": "Accepted", "reason": "Rejection Reason"}),
            count=len(proposal_rows_all),
        )
        + render_details_html(
            "Show normalization artifact files",
            render_html_table(phase_c_artifacts, ["n", "file"], {"n": "#", "file": "Artifact"}),
            count=len(phase_c_artifacts),
        )
        + "</div>"
    )
    phase_d_block = (
        "<div class=\"section\"><h2>Phase D - Query Plan</h2>"
        + render_html_table(phase_d_summary(phase_d), ["metric", "value"], {"metric": "Metric", "value": "Value"})
        + "<h3>Subpoints</h3>"
        + render_html_table(subpoint_rows_preview, ["id", "label", "must_terms", "preferred_types"], {"id": "ID", "label": "Label", "must_terms": "Must Terms", "preferred_types": "Preferred Types"})
        + render_details_html(
            "Show all source anchors",
            render_html_table(source_anchor_all, ["n", "anchor"], {"n": "#", "anchor": "Source Anchor"}),
            count=len(source_anchor_all),
        )
        + "</div>"
    )
    phase_e_block = (
        "<div class=\"section\"><h2>Phase E - Retrieval</h2>"
        + render_html_table(phase_e_summary(phase_e), ["metric", "value"], {"metric": "Metric", "value": "Value"})
        + "<h3>Top Fused Candidates</h3>"
        + render_html_table(fused_rows_preview, ["rank", "pages", "type", "title", "fused_score", "select_score", "support", "subpoints"], {"rank": "Rank", "pages": "Pages", "type": "Type", "title": "Title", "fused_score": "Fused", "select_score": "Select", "support": "Support", "subpoints": "Subpoints"})
        + render_details_html(
            "Show all fused candidates",
            render_html_table(fused_rows_all, ["rank", "pages", "type", "title", "fused_score", "select_score", "support", "subpoints"], {"rank": "Rank", "pages": "Pages", "type": "Type", "title": "Title", "fused_score": "Fused", "select_score": "Select", "support": "Support", "subpoints": "Subpoints"}),
            count=len(fused_rows_all),
        )
        + render_details_html(
            "Show retrieval lane breakdown",
            render_html_table(lane_rows_all, ["lane", "count", "top_score", "top_title"], {"lane": "Lane", "count": "Rows", "top_score": "Top Score", "top_title": "Top Title"}),
            count=len(lane_rows_all),
        )
        + render_details_html(
            "Show retrieval artifact files",
            render_html_table(phase_e_artifacts, ["n", "file"], {"n": "#", "file": "Artifact"}),
            count=len(phase_e_artifacts),
        )
        + "</div>"
    )
    phase_f_block = (
        "<div class=\"section\"><h2>Phase F - Rerank</h2>"
        + render_html_table(phase_f_summary(phase_f), ["metric", "value"], {"metric": "Metric", "value": "Value"})
        + "<h3>Top Reranked Sections</h3>"
        + render_html_table(rerank_rows_preview, ["rank", "pages", "title", "rerank", "cross", "judge", "generic"], {"rank": "Rank", "pages": "Pages", "title": "Title", "rerank": "Rerank", "cross": "Cross", "judge": "Judge", "generic": "Generic"})
        + render_details_html(
            "Show all reranked sections",
            render_html_table(rerank_rows_all, ["rank", "pages", "title", "rerank", "cross", "judge", "generic"], {"rank": "Rank", "pages": "Pages", "title": "Title", "rerank": "Rerank", "cross": "Cross", "judge": "Judge", "generic": "Generic"}),
            count=len(rerank_rows_all),
        )
        + render_details_html(
            "Show LLM judge rows",
            render_html_table(judge_rows_all, ["title", "judge", "useful", "topic", "coverage", "violations"], {"title": "Title", "judge": "Judge", "useful": "Useful", "topic": "Topic", "coverage": "Coverage", "violations": "Violations"}),
            count=len(judge_rows_all),
        )
        + render_details_html(
            "Show rerank artifact files",
            render_html_table(phase_f_artifacts, ["n", "file"], {"n": "#", "file": "Artifact"}),
            count=len(phase_f_artifacts),
        )
        + "</div>"
    )
    phase_g_block = (
        "<div class=\"section\"><h2>Phase G - Final Decision</h2>"
        + render_html_table(phase_g_summary(phase_g), ["metric", "value"], {"metric": "Metric", "value": "Value"})
        + "<h3>Top Final Sections</h3>"
        + render_html_table(final_rows_preview, ["score", "band", "support", "pages", "title", "coverage"], {"score": "Score", "band": "Band", "support": "Support", "pages": "Pages", "title": "Title", "coverage": "Coverage"})
        + render_details_html(
            "Show all final section scores",
            render_html_table(final_rows_all, ["rank", "score", "band", "support", "pages", "title", "coverage"], {"rank": "Global Rank", "score": "Score", "band": "Band", "support": "Support", "pages": "Pages", "title": "Title", "coverage": "Coverage"}),
            count=len(final_rows_all),
        )
        + render_details_html(
            "Show final artifact files",
            render_html_table(phase_g_artifacts, ["n", "file"], {"n": "#", "file": "Artifact"}),
            count=len(phase_g_artifacts),
        )
        + "</div>"
    )
    html_parts = [
        "<!doctype html>",
        "<html><head><meta charset=\"utf-8\">",
        f"<title>{html_text(overview.get('doc_title') or overview.get('doc_id'))}</title>",
        f"<style>{DOC_REPORT_CSS}</style>",
        "</head><body><div class=\"page\">",
        f"<div class=\"muted\">Run {html_text(overview.get('run_id'))} / {html_text(overview.get('doc_id'))}</div>",
        f"<h1>{html_text(overview.get('doc_title') or overview.get('doc_id'))}</h1>",
        f"<p class=\"muted\">Source PDF: {html_text(overview.get('source_pdf'))}</p>",
        f"<div class=\"chips\">{''.join(chips)}</div>",
        f"<div class=\"grid\">{card_html}</div>",
        "<div class=\"section links\"><strong>Quick links:</strong> <a href=\"../index.html\">run index</a> "
        + " ".join(f"<a href=\"{href_path(name)}\">{html_text(name)}</a>" for name in quick_links)
        + "</div>",
        phase_b_block,
        phase_c_block,
        phase_d_block,
        phase_e_block,
        phase_f_block,
        phase_g_block,
        "<div class=\"section\"><h2>Evidence Preview</h2>" + "".join(evidence_blocks) + "</div>",
        "</div></body></html>",
    ]
    return "".join(html_parts)


def build_index_markdown(index_payload: Dict[str, Any]) -> str:
    useful_count = sum(1 for row in list(index_payload.get("documents") or []) if row.get("has_useful_information") is True)
    lines = [
        "# Per-PDF Run Reports",
        "",
        f"- Run ID: `{index_payload.get('run_id')}`",
        f"- Generated At UTC: `{index_payload.get('generated_at_utc')}`",
        f"- Last Updated Phase: `{index_payload.get('last_updated_phase')}`",
        f"- Document count: `{len(list(index_payload.get('documents') or []))}`",
        f"- Useful PDFs: `{useful_count}`",
        "",
        "## Review Order",
        "1. Open `index.html` for the clean dashboard view.",
        "2. Open a PDF's `report.html` or `report.md`.",
        "3. Drill into the raw `phase_*.json` files only when something looks off.",
        "",
        "## Documents",
        render_markdown_table(
            list(index_payload.get("documents") or []),
            ["doc_title", "has_useful_information", "top_section_score", "top_section_title", "report_html_path"],
            {
                "doc_title": "Document",
                "has_useful_information": "Useful",
                "top_section_score": "Top Score",
                "top_section_title": "Top Section",
                "report_html_path": "HTML Report",
            },
        ),
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_index_html(index_payload: Dict[str, Any]) -> str:
    docs = list(index_payload.get("documents") or [])
    useful_count = sum(1 for row in docs if row.get("has_useful_information") is True)
    card_html = "".join(
        [
            f"<div class=\"card\"><div class=\"metric-label\">Run ID</div><div class=\"metric-value\">{html_text(index_payload.get('run_id'))}</div></div>",
            f"<div class=\"card\"><div class=\"metric-label\">Documents</div><div class=\"metric-value\">{len(docs)}</div></div>",
            f"<div class=\"card\"><div class=\"metric-label\">Useful PDFs</div><div class=\"metric-value\">{useful_count}</div></div>",
            f"<div class=\"card\"><div class=\"metric-label\">Last Updated Phase</div><div class=\"metric-value\">{html_text(index_payload.get('last_updated_phase') or '-')}</div></div>",
        ]
    )
    rows = []
    for row in docs:
        status = "yes" if row.get("has_useful_information") is True else "no" if row.get("has_useful_information") is False else "-"
        rows.append(
            {
                "document": row.get("doc_title") or row.get("doc_id") or "-",
                "useful": status,
                "top_score": fmt_num(row.get("top_section_score"), 2),
                "top_section": truncate_text(row.get("top_section_title"), 70),
                "pages": row.get("page_count") or "-",
                "sections": row.get("section_count") or "-",
                "report": row.get("report_html_local_path") or "-",
            }
        )
    table_html = render_html_table(rows, ["document", "useful", "top_score", "top_section", "pages", "sections", "report"], {"document": "Document", "useful": "Useful", "top_score": "Top Score", "top_section": "Top Section", "pages": "Pages", "sections": "Sections", "report": "HTML Report"})
    table_html = table_html.replace(
        "<td>",
        "<td>",
    )
    for row in rows:
        report = row["report"]
        table_html = table_html.replace(
            f">{html_text(report)}</td>",
            f"><a href=\"{href_path(report)}\">{html_text(report)}</a></td>",
            1,
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>Run {html_text(index_payload.get('run_id'))} reports</title>"
        f"<style>{DOC_REPORT_CSS}</style>"
        "</head><body><div class=\"page\">"
        f"<div class=\"muted\">Generated {html_text(index_payload.get('generated_at_utc'))}</div>"
        f"<h1>Per-PDF Run Reports</h1>"
        "<p class=\"note\">Start here. Open a per-document HTML report for the clean review view. Use the raw JSON files only when you need the full trace.</p>"
        f"<div class=\"grid\">{card_html}</div>"
        "<div class=\"section links\"><strong>Also available:</strong> <a href=\"index.json\">index.json</a> <a href=\"README.md\">README.md</a></div>"
        f"<div class=\"section\">{table_html}</div>"
        "</div></body></html>"
    )


def update_run_pdf_reports(run_ctx: Any, *, phase_name: str = "") -> Dict[str, Any]:
    state = load_global_state(run_ctx)
    run_dir = state["run_dir"]
    report_root = ensure_dir(run_dir / PDF_REPORTS_DIRNAME)
    doc_index_rows = []

    for doc_id in collect_doc_ids(state):
        manifest_row = dict(state["manifest_by_doc_id"].get(doc_id) or {})
        parser_dir = run_dir / "parser" / doc_id
        normalized_dir = run_dir / "normalized" / doc_id
        doc_dir = ensure_dir(report_root / doc_id)

        phase_payloads = {
            "phase_a_input": build_phase_a_payload(doc_id, state),
            "phase_b_parser": build_phase_b_payload(doc_id, state),
            "phase_c_normalized": build_phase_c_payload(doc_id, state),
            "phase_d_query_context": build_phase_d_payload(doc_id, state),
            "phase_e_retrieval": build_phase_e_payload(doc_id, state),
            "phase_f_rerank": build_phase_f_payload(doc_id, state),
            "phase_g_final": build_phase_g_payload(doc_id, state),
        }
        available_phases = {
            "phase_a": bool(phase_payloads["phase_a_input"].get("manifest_row")),
            "phase_b": bool(phase_payloads["phase_b_parser"].get("metadata")),
            "phase_c": bool(phase_payloads["phase_c_normalized"].get("document")),
            "phase_d": bool((phase_payloads["phase_d_query_context"].get("query_plan") or {}).get("query_plan") or phase_payloads["phase_d_query_context"].get("query_plan")),
            "phase_e": bool(phase_payloads["phase_e_retrieval"].get("fused_candidates")),
            "phase_f": bool(phase_payloads["phase_f_rerank"].get("rerank_results")),
            "phase_g": bool(phase_payloads["phase_g_final"].get("doc_features")),
        }
        document = dict(phase_payloads["phase_c_normalized"].get("document") or {})
        doc_features = dict(phase_payloads["phase_g_final"].get("doc_features") or {})
        overview = {
            "generated_at_utc": utc_now_iso(),
            "run_id": str(run_ctx.run_id),
            "doc_id": doc_id,
            "doc_title": clean_text(document.get("title") or manifest_row.get("label") or Path(str(manifest_row.get("path") or doc_id)).stem),
            "source_pdf": str(manifest_row.get("path") or phase_payloads["phase_b_parser"].get("metadata", {}).get("source_path") or ""),
            "page_count": document.get("page_count") or phase_payloads["phase_b_parser"].get("metadata", {}).get("page_count") or manifest_row.get("page_count"),
            "section_count": document.get("section_count") or len(list(phase_payloads["phase_c_normalized"].get("sections") or [])),
            "passage_count": len(list(phase_payloads["phase_c_normalized"].get("passages") or [])),
            "available_phases": available_phases,
            "last_updated_phase": phase_name or max((name for name, present in available_phases.items() if present), default="phase_a"),
            "has_useful_information": doc_features.get("has_useful_information"),
            "top_section_title": doc_features.get("top_section_title"),
            "top_section_score": doc_features.get("top_section_score"),
            "doc_match_probability": doc_features.get("doc_match_probability"),
            "parser_doc_dir": rel_to_run(run_dir, parser_dir),
            "normalized_doc_dir": rel_to_run(run_dir, normalized_dir),
            "report_files": sorted([f"{name}.json" for name in phase_payloads.keys()] + ["report.html", "report.json", "report.md"]),
        }
        write_doc_report_files(doc_dir, overview, phase_payloads)
        doc_index_rows.append(
            {
                "doc_id": doc_id,
                "doc_title": overview["doc_title"],
                "has_useful_information": overview.get("has_useful_information"),
                "doc_match_probability": overview.get("doc_match_probability"),
                "page_count": overview.get("page_count"),
                "section_count": overview.get("section_count"),
                "top_section_score": overview.get("top_section_score"),
                "top_section_title": overview.get("top_section_title"),
                "report_path": rel_to_run(run_dir, doc_dir / "report.json"),
                "markdown_path": rel_to_run(run_dir, doc_dir / "report.md"),
                "report_html_path": rel_to_run(run_dir, doc_dir / "report.html"),
                "report_html_local_path": rel_to_run(report_root, doc_dir / "report.html"),
            }
        )

    doc_index_rows.sort(key=lambda row: (row.get("has_useful_information") is True, float(row.get("top_section_score") or 0.0), row.get("doc_id") or ""), reverse=True)
    index_payload = {
        "generated_at_utc": utc_now_iso(),
        "run_id": str(run_ctx.run_id),
        "last_updated_phase": phase_name or "",
        "report_root": rel_to_run(run_dir, report_root),
        "documents": doc_index_rows,
        "phase_availability": state["phase_availability"],
    }
    write_json(report_root / "index.json", index_payload)
    write_text(report_root / "README.md", build_index_markdown(index_payload))
    write_text(report_root / "index.html", build_index_html(index_payload))
    return {
        "report_root": report_root,
        "index_path": report_root / "index.json",
        "readme_path": report_root / "README.md",
        "html_path": report_root / "index.html",
        "document_count": len(doc_index_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate per-PDF run reports.")
    parser.add_argument("run_dir")
    parser.add_argument("--phase-name", default="")
    args = parser.parse_args()
    run_ctx = build_run_ctx_from_dir(Path(args.run_dir))
    result = update_run_pdf_reports(run_ctx, phase_name=str(args.phase_name or ""))
    print(
        json.dumps(
            {
                "report_root": str(result["report_root"]),
                "index_path": str(result["index_path"]),
                "html_path": str(result["html_path"]),
                "document_count": result["document_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
