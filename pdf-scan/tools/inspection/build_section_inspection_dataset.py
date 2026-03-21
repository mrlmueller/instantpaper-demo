#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import fitz

PDF_SCAN_DIR = Path(__file__).resolve().parents[2]
if str(PDF_SCAN_DIR) not in sys.path:
    sys.path.insert(0, str(PDF_SCAN_DIR))

from tools.benchmark.evaluate_manual_benchmark import (
    build_run_view,
    load_suite,
    read_json,
    read_jsonl,
    strong_match,
)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def truncate_text(value: Any, limit: int = 800) -> str:
    text = clean_text(value)
    if len(text) <= int(limit):
        return text
    return text[: max(1, int(limit) - 1)] + "…"


def load_sections(run_dir: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    rows = read_jsonl(run_dir / "normalized" / "sections.jsonl")
    by_id = {}
    by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        section_id = str(row.get("section_id") or "")
        doc_id = str(row.get("doc_id") or "")
        if section_id:
            by_id[section_id] = row
        if doc_id:
            by_doc[doc_id].append(row)
    for values in by_doc.values():
        values.sort(key=lambda item: (int(item.get("page_start") or 0), int(item.get("level") or 0), str(item.get("title") or "")))
    return rows, by_id, by_doc


def load_documents(run_dir: Path) -> Dict[str, Dict[str, Any]]:
    rows = read_jsonl(run_dir / "normalized" / "documents.jsonl")
    return {str(row.get("doc_id") or ""): row for row in rows if str(row.get("doc_id") or "")}


def load_fused_by_doc(run_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
    rows = read_jsonl(run_dir / "retrieval" / "fused_candidates.jsonl")
    by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        doc_id = str(row.get("doc_id") or "")
        if doc_id:
            by_doc[doc_id].append(row)
    for values in by_doc.values():
        values.sort(key=lambda item: int(item.get("fused_rank") or 100000))
    return by_doc


def load_rerank_by_doc(run_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
    rows = read_jsonl(run_dir / "rerank" / "rerank_results.jsonl")
    by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        doc_id = str(row.get("doc_id") or "")
        if doc_id:
            by_doc[doc_id].append(row)
    for values in by_doc.values():
        values.sort(key=lambda item: int(item.get("rerank_rank") or 100000))
    return by_doc


def load_final_docs(run_dir: Path) -> Dict[str, Dict[str, Any]]:
    payload = read_json(run_dir / "final" / "output.json")
    return {str(row.get("doc_id") or ""): row for row in (payload.get("documents") or []) if str(row.get("doc_id") or "")}


def page_text_excerpt(pdf_path: Path, page_start: int, page_end: int, *, max_chars: int = 2400) -> str:
    if not pdf_path.exists():
        return ""
    excerpts: List[str] = []
    with fitz.open(pdf_path) as doc:
        for page_no in range(max(1, int(page_start)), min(len(doc), int(page_end)) + 1):
            try:
                text = doc[page_no - 1].get_text("text")
            except Exception:
                text = ""
            if clean_text(text):
                excerpts.append(f"[Page {page_no}] {clean_text(text)}")
    return truncate_text("\n\n".join(excerpts), limit=max_chars)


def build_section_rank_maps(rows: List[Dict[str, Any]], rank_key: str) -> Dict[str, int]:
    out = {}
    for row in rows:
        section_id = str(row.get("section_id") or "")
        if section_id and section_id not in out:
            out[section_id] = int(row.get(rank_key) or 0)
    return out


def section_pipeline_view(
    section: Dict[str, Any],
    document: Dict[str, Any],
    fused_rank_map: Dict[str, int],
    rerank_rank_map: Dict[str, int],
    final_rank_map: Dict[str, int],
) -> Dict[str, Any]:
    section_id = str(section.get("section_id") or "")
    top_sections = list((document.get("top_sections") or []))
    final_row = next((row for row in top_sections if str(row.get("section_id") or "") == section_id), None)
    return {
        "phase_e_doc_rank": fused_rank_map.get(section_id),
        "phase_f_doc_rank": rerank_rank_map.get(section_id),
        "phase_g_doc_rank": final_rank_map.get(section_id),
        "phase_g_score_0_to_100": final_row.get("score_0_to_100") if final_row else None,
        "phase_g_score_band": final_row.get("score_band") if final_row else None,
        "doc_has_useful_information": bool(document.get("has_useful_information")),
        "doc_match_probability": document.get("doc_match_probability"),
        "doc_abstention_reason": document.get("abstention_reason"),
        "doc_top_section_title": document.get("top_section_title"),
        "doc_top_section_score": document.get("top_section_score"),
    }


def match_expected_to_section(
    expected: Dict[str, Any],
    sections: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[float]]:
    best_row = None
    best_score = None
    for row in sections:
        ok, score = strong_match(
            expected,
            str(row.get("title") or ""),
            int(row.get("page_start") or 0),
            int(row.get("page_end") or 0),
        )
        if not ok:
            continue
        if best_score is None or float(score) > float(best_score):
            best_row = row
            best_score = score
    return best_row, best_score


def benchmark_status_reason(
    matched_section: Optional[Dict[str, Any]],
    fused_rows: List[Dict[str, Any]],
    rerank_rows: List[Dict[str, Any]],
    final_top_rows: List[Dict[str, Any]],
    expected: Dict[str, Any],
    final_doc: Dict[str, Any],
) -> str:
    if matched_section is None:
        return "phase_c_structure_miss"
    section_id = str(matched_section.get("section_id") or "")
    if not any(str(row.get("section_id") or "") == section_id for row in fused_rows[:10]):
        return "phase_e_retrieval_miss"
    if not any(str(row.get("section_id") or "") == section_id for row in rerank_rows[:10]):
        return "phase_f_rerank_miss"
    if not any(str(row.get("section_id") or "") == section_id for row in final_top_rows[:5]):
        reason = clean_text(final_doc.get("abstention_reason") or "")
        return f"phase_g_final_miss::{reason or 'not_in_top_sections'}"
    return "surfaced_to_phase_g"


def render_doc_markdown(
    doc_id: str,
    document_row: Dict[str, Any],
    sections: List[Dict[str, Any]],
    section_rows: List[Dict[str, Any]],
    benchmark_rows: List[Dict[str, Any]],
) -> str:
    lines = [
        f"# {clean_text(document_row.get('title') or doc_id)}",
        "",
        f"- doc_id: `{doc_id}`",
        f"- source_path: `{document_row.get('source_path')}`",
        f"- page_count: `{document_row.get('page_count')}`",
        f"- has_useful_information: `{document_row.get('has_useful_information')}`",
        f"- doc_match_probability: `{document_row.get('doc_match_probability')}`",
        f"- top_section_title: `{document_row.get('top_section_title')}`",
        f"- top_section_score: `{document_row.get('top_section_score')}`",
        "",
        "## Benchmark Sections",
        "",
    ]
    if benchmark_rows:
        for row in benchmark_rows:
            lines.extend(
                [
                    f"### {clean_text(row.get('expected_section_title') or 'Untitled')}",
                    "",
                    f"- pages: `{row.get('expected_page_start')}-{row.get('expected_page_end')}`",
                    f"- benchmark_label_0_to_3: `{row.get('benchmark_label_0_to_3')}`",
                    f"- benchmark_notes: {clean_text(row.get('benchmark_notes') or '')}",
                    f"- pipeline_reason: `{row.get('pipeline_reason')}`",
                    f"- matched_section_title: `{clean_text(row.get('matched_section_title') or '')}`",
                    f"- phase_e_doc_rank: `{row.get('phase_e_doc_rank')}`",
                    f"- phase_f_doc_rank: `{row.get('phase_f_doc_rank')}`",
                    f"- phase_g_doc_rank: `{row.get('phase_g_doc_rank')}`",
                    "",
                    truncate_text(row.get("inspection_text") or "", limit=2200),
                    "",
                ]
            )
    else:
        lines.extend(["No benchmark target sections for this PDF.", ""])

    lines.extend(["## Extracted Sections", ""])
    for row in section_rows:
        lines.extend(
            [
                f"### {clean_text(row.get('title') or 'Untitled')}",
                "",
                f"- pages: `{row.get('page_start')}-{row.get('page_end')}`",
                f"- section_type: `{row.get('section_type')}`",
                f"- retrieval_eligible: `{row.get('retrieval_eligible')}`",
                f"- phase_e_doc_rank: `{row.get('phase_e_doc_rank')}`",
                f"- phase_f_doc_rank: `{row.get('phase_f_doc_rank')}`",
                f"- phase_g_doc_rank: `{row.get('phase_g_doc_rank')}`",
                f"- benchmark_targets: `{', '.join(row.get('benchmark_target_titles') or [])}`",
                "",
                truncate_text(row.get("text") or "", limit=1800),
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a full inspection dataset for one run and the manual benchmark.")
    parser.add_argument("--run-id", default="386e04657c41c805f8c1b974")
    parser.add_argument("--suite-manifest", default="benchmark/full_dump_webshop_manual_v1/manifests/suite_manifest.json")
    parser.add_argument("--output-subdir", default="section_inspection")
    args = parser.parse_args()

    run_dir = (PDF_SCAN_DIR / "runs" / args.run_id).resolve()
    suite_manifest = (PDF_SCAN_DIR / args.suite_manifest).resolve()
    suite = load_suite(suite_manifest)
    out_dir = run_dir / args.output_subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    per_doc_dir = out_dir / "per_doc"
    per_doc_dir.mkdir(parents=True, exist_ok=True)

    sections, sections_by_id, sections_by_doc = load_sections(run_dir)
    documents = load_documents(run_dir)
    fused_by_doc = load_fused_by_doc(run_dir)
    rerank_by_doc = load_rerank_by_doc(run_dir)
    final_docs = load_final_docs(run_dir)

    benchmark_by_doc = {row["doc_id"]: row for row in suite["judgments"]}

    all_section_rows: List[Dict[str, Any]] = []
    benchmark_rows: List[Dict[str, Any]] = []
    doc_section_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    doc_benchmark_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for doc_id, doc_sections in sections_by_doc.items():
        document_row = documents.get(doc_id, {})
        final_doc = final_docs.get(doc_id, {})
        fused_rank_map = build_section_rank_maps(fused_by_doc.get(doc_id, []), "fused_rank")
        rerank_rank_map = build_section_rank_maps(rerank_by_doc.get(doc_id, []), "rerank_rank")
        final_rank_map = {str(row.get("section_id") or ""): idx for idx, row in enumerate(list(final_doc.get("top_sections") or []), 1) if str(row.get("section_id") or "")}

        benchmark_targets = list((benchmark_by_doc.get(doc_id, {}) or {}).get("section_judgments") or [])
        benchmark_matches: Dict[str, List[str]] = defaultdict(list)
        for expected in benchmark_targets:
            matched_row, _ = match_expected_to_section(expected, doc_sections)
            if matched_row is not None:
                benchmark_matches[str(matched_row.get("section_id") or "")].append(expected["section_ref"]["section_title"])

        for section in doc_sections:
            row = {
                "run_id": args.run_id,
                "doc_id": doc_id,
                "doc_title": clean_text(document_row.get("title") or ""),
                "source_path": document_row.get("source_path"),
                "section_id": section.get("section_id"),
                "title": clean_text(section.get("title") or ""),
                "page_start": section.get("page_start"),
                "page_end": section.get("page_end"),
                "section_type": section.get("section_type"),
                "retrieval_eligible": bool(section.get("retrieval_eligible")),
                "quality_flags": list(section.get("quality_flags") or []),
                "parser_sources": list(section.get("parser_sources") or []),
                "benchmark_target_titles": list(benchmark_matches.get(str(section.get("section_id") or ""), [])),
                "title_path": list(section.get("title_path") or []),
                "text": clean_text(section.get("text") or ""),
                "text_excerpt": truncate_text(section.get("text") or "", limit=1600),
                **section_pipeline_view(section, final_doc, fused_rank_map, rerank_rank_map, final_rank_map),
            }
            all_section_rows.append(row)
            doc_section_rows[doc_id].append(row)

        for expected in benchmark_targets:
            matched_row, match_score = match_expected_to_section(expected, doc_sections)
            matched_section_id = str(matched_row.get("section_id") or "") if matched_row else None
            fused_rows = fused_by_doc.get(doc_id, [])
            rerank_rows = rerank_by_doc.get(doc_id, [])
            final_top_rows = list((final_doc.get("top_sections") or []))
            pipeline_reason = benchmark_status_reason(matched_row, fused_rows, rerank_rows, final_top_rows, expected, final_doc)
            if matched_row is not None:
                inspection_text = clean_text(matched_row.get("text") or "")
            else:
                source_path = Path(str(document_row.get("source_path") or ""))
                section_ref = expected["section_ref"]
                inspection_text = page_text_excerpt(source_path, int(section_ref["page_start"]), int(section_ref["page_end"]))
            row = {
                "run_id": args.run_id,
                "doc_id": doc_id,
                "doc_title": clean_text(document_row.get("title") or ""),
                "source_path": document_row.get("source_path"),
                "expected_section_title": expected["section_ref"]["section_title"],
                "expected_page_start": expected["section_ref"]["page_start"],
                "expected_page_end": expected["section_ref"]["page_end"],
                "benchmark_label_0_to_3": expected.get("label_0_to_3"),
                "benchmark_supported_subpoints": list(expected.get("supported_subpoints") or []),
                "benchmark_notes": expected.get("notes"),
                "matched_section_id": matched_section_id,
                "matched_section_title": clean_text(matched_row.get("title") or "") if matched_row else None,
                "matched_page_start": matched_row.get("page_start") if matched_row else None,
                "matched_page_end": matched_row.get("page_end") if matched_row else None,
                "match_score": round(float(match_score), 4) if match_score is not None else None,
                "phase_e_doc_rank": fused_rank_map.get(matched_section_id) if matched_section_id else None,
                "phase_f_doc_rank": rerank_rank_map.get(matched_section_id) if matched_section_id else None,
                "phase_g_doc_rank": final_rank_map.get(matched_section_id) if matched_section_id else None,
                "doc_has_useful_information": bool(final_doc.get("has_useful_information")),
                "doc_match_probability": final_doc.get("doc_match_probability"),
                "doc_abstention_reason": final_doc.get("abstention_reason"),
                "pipeline_reason": pipeline_reason,
                "inspection_text": inspection_text,
                "inspection_excerpt": truncate_text(inspection_text, limit=1800),
            }
            benchmark_rows.append(row)
            doc_benchmark_rows[doc_id].append(row)

    for doc_id, section_rows in doc_section_rows.items():
        payload = render_doc_markdown(
            doc_id,
            final_docs.get(doc_id, {}) | documents.get(doc_id, {}),
            sections_by_doc.get(doc_id, []),
            section_rows,
            doc_benchmark_rows.get(doc_id, []),
        )
        (per_doc_dir / f"{doc_id}.md").write_text(payload, encoding="utf-8")

    write_jsonl(out_dir / "all_sections.jsonl", all_section_rows)
    write_jsonl(out_dir / "benchmark_targets.jsonl", benchmark_rows)
    write_json(
        out_dir / "summary.json",
        {
            "run_id": args.run_id,
            "suite_id": suite["suite"]["suite_id"],
            "doc_count": len(doc_section_rows),
            "section_count": len(all_section_rows),
            "benchmark_target_count": len(benchmark_rows),
            "output_subdir": args.output_subdir,
        },
    )
    print(json.dumps({"run_id": args.run_id, "output_dir": str(out_dir), "section_count": len(all_section_rows), "benchmark_target_count": len(benchmark_rows)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
