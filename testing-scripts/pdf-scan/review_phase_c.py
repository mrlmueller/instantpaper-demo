#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Dict, List


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_run_dir(base_dir: Path, run_id: str | None) -> Path:
    runs_dir = base_dir / "runs"
    if run_id:
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")
        return run_dir

    candidates = [path for path in runs_dir.iterdir() if path.is_dir() and (path / "normalized" / "phase_c_summary.json").exists()]
    if not candidates:
        raise FileNotFoundError(f"No Phase C run found under {runs_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def build_review(run_dir: Path) -> Dict[str, Any]:
    normalized_dir = run_dir / "normalized"
    summary = read_json(normalized_dir / "phase_c_summary.json")
    assessment = read_json(normalized_dir / "phase_c_assessment.json")
    documents = read_jsonl(normalized_dir / "documents.jsonl")
    sections = read_jsonl(normalized_dir / "sections.jsonl")
    passages = read_jsonl(normalized_dir / "passages.jsonl")
    bundles = read_jsonl(normalized_dir / "normalized_document_bundles.jsonl")
    metrics = read_json(run_dir / "metrics.json")

    section_counts_by_doc: Dict[str, int] = {}
    passage_counts_by_doc: Dict[str, int] = {}
    tiny_counts_by_doc: Dict[str, int] = {}
    eligible_tiny_counts_by_doc: Dict[str, int] = {}
    suppressed_counts_by_doc: Dict[str, int] = {}
    wrapper_titles_by_doc: Dict[str, List[str]] = {}
    for row in sections:
        doc_id = str(row.get("doc_id") or "")
        section_counts_by_doc[doc_id] = section_counts_by_doc.get(doc_id, 0) + 1
        flags = list(row.get("quality_flags") or [])
        if "tiny_section" in flags:
            tiny_counts_by_doc[doc_id] = tiny_counts_by_doc.get(doc_id, 0) + 1
            if bool(row.get("retrieval_eligible", True)):
                eligible_tiny_counts_by_doc[doc_id] = eligible_tiny_counts_by_doc.get(doc_id, 0) + 1
        if not bool(row.get("retrieval_eligible", True)):
            suppressed_counts_by_doc[doc_id] = suppressed_counts_by_doc.get(doc_id, 0) + 1
        if "structural_wrapper" in flags:
            wrapper_titles_by_doc.setdefault(doc_id, []).append(str(row.get("title") or ""))
    for row in passages:
        doc_id = str(row.get("doc_id") or "")
        passage_counts_by_doc[doc_id] = passage_counts_by_doc.get(doc_id, 0) + 1

    doc_rows: List[Dict[str, Any]] = []
    high_tiny_ratio_docs: List[str] = []
    fallback_docs: List[str] = []
    suppressed_docs: List[str] = []
    sections_per_page_values: List[float] = []

    for row in documents:
        doc_id = str(row.get("doc_id") or "")
        page_count = int(row.get("page_count") or 0)
        section_count = int(section_counts_by_doc.get(doc_id, 0))
        passage_count = int(passage_counts_by_doc.get(doc_id, 0))
        tiny_count = int(tiny_counts_by_doc.get(doc_id, 0))
        retrieval_eligible_tiny_count = int(eligible_tiny_counts_by_doc.get(doc_id, 0))
        suppressed_count = int(suppressed_counts_by_doc.get(doc_id, 0))
        tiny_ratio = round((tiny_count / max(1, section_count)), 4) if section_count else 0.0
        retrieval_eligible_tiny_ratio = round((retrieval_eligible_tiny_count / max(1, section_count)), 4) if section_count else 0.0
        sections_per_page = round((section_count / max(1, page_count)), 4) if page_count else None
        if sections_per_page is not None:
            sections_per_page_values.append(sections_per_page)
        if page_count >= 20 and retrieval_eligible_tiny_ratio >= 0.25:
            high_tiny_ratio_docs.append(doc_id)
        if int(row.get("fallback_anchor_count") or 0) > 0:
            fallback_docs.append(doc_id)
        if suppressed_count > 0:
            suppressed_docs.append(doc_id)

        doc_rows.append(
            {
                "doc_id": doc_id,
                "title": row.get("title"),
                "page_count": page_count,
                "section_count": section_count,
                "passage_count": passage_count,
                "section_coverage_pct": row.get("section_coverage_pct"),
                "fallback_anchor_count": row.get("fallback_anchor_count"),
                "tiny_section_count": tiny_count,
                "tiny_section_ratio": tiny_ratio,
                "retrieval_eligible_tiny_section_count": retrieval_eligible_tiny_count,
                "retrieval_eligible_tiny_ratio": retrieval_eligible_tiny_ratio,
                "retrieval_suppressed_section_count": suppressed_count,
                "structural_wrapper_count": int(row.get("structural_wrapper_count") or 0),
                "sections_per_page": sections_per_page,
                "strategy": row.get("strategy"),
                "heading_sources": row.get("heading_sources"),
                "quality_flags": list(row.get("quality_flags") or []),
                "wrapper_title_preview": wrapper_titles_by_doc.get(doc_id, [])[:10],
            }
        )

    summary_docs = list(summary.get("documents") or [])
    summary_doc_ids = {str(row.get("doc_id") or "") for row in summary_docs}
    document_doc_ids = {str(row.get("doc_id") or "") for row in documents}
    passage_section_ids = {str(row.get("section_id") or "") for row in passages}
    section_ids = {str(row.get("section_id") or "") for row in sections}
    ineligible_passage_count = sum(1 for row in passages if not bool(row.get("retrieval_eligible", True)))

    qc_rows = [
        {
            "check": "documents_match_summary",
            "status": "OK" if document_doc_ids == summary_doc_ids else "FAIL",
            "value": len(document_doc_ids),
            "expected": len(summary_doc_ids),
        },
        {
            "check": "sections_match_documents",
            "status": "OK" if all(int(row.get("section_count") or 0) == section_counts_by_doc.get(str(row.get("doc_id") or ""), 0) for row in documents) else "FAIL",
            "value": len(sections),
            "expected": "documents.jsonl section_count matches sections.jsonl",
        },
        {
            "check": "passages_match_documents",
            "status": "OK" if all(passage_counts_by_doc.get(str(row.get("doc_id") or ""), 0) > 0 for row in documents) else "FAIL",
            "value": len(passages),
            "expected": "every document has passages",
        },
        {
            "check": "passages_reference_known_sections",
            "status": "OK" if passage_section_ids.issubset(section_ids) else "FAIL",
            "value": len(passage_section_ids - section_ids),
            "expected": 0,
        },
        {
            "check": "phase_c_metrics_present",
            "status": "OK" if bool(((metrics.get("stages") or {}).get("phase_c") or {})) else "FAIL",
            "value": bool(((metrics.get("stages") or {}).get("phase_c") or {})),
            "expected": True,
        },
        {
            "check": "high_tiny_ratio_docs",
            "status": "OK" if not high_tiny_ratio_docs else "WARN",
            "value": "none" if not high_tiny_ratio_docs else ", ".join(high_tiny_ratio_docs),
            "expected": "none (for retrieval-eligible tiny sections)",
        },
        {
            "check": "fallback_anchor_docs",
            "status": "OK" if not fallback_docs else "WARN",
            "value": "none" if not fallback_docs else ", ".join(fallback_docs),
            "expected": "none preferred",
        },
    ]

    return {
        "run_dir": str(run_dir),
        "run_id": run_dir.name,
        "phase_c_status": ((assessment.get("assessment") or {}).get("status")),
        "phase_c_quality_band": ((assessment.get("assessment") or {}).get("quality_band")),
        "documents_processed": len(documents),
        "review_summary": {
            "bundle_count": len(bundles),
            "section_count": len(sections),
            "passage_count": len(passages),
            "sections_per_page_min": min(sections_per_page_values) if sections_per_page_values else None,
            "sections_per_page_median": statistics.median(sections_per_page_values) if sections_per_page_values else None,
            "sections_per_page_max": max(sections_per_page_values) if sections_per_page_values else None,
            "high_tiny_ratio_doc_count": len(high_tiny_ratio_docs),
            "high_tiny_ratio_docs": high_tiny_ratio_docs,
            "fallback_anchor_doc_count": len(fallback_docs),
            "fallback_anchor_docs": fallback_docs,
            "retrieval_suppressed_doc_count": len(suppressed_docs),
            "retrieval_suppressed_docs": suppressed_docs,
            "retrieval_suppressed_passage_count": ineligible_passage_count,
        },
        "documents": doc_rows,
        "qc_rows": qc_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Review a Phase C normalization run.")
    parser.add_argument("--base-dir", default="pdf-scan")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    run_dir = find_run_dir(Path(args.base_dir).resolve(), args.run_id)
    review = build_review(run_dir)
    out_path = run_dir / "phase_c_review" / "phase_c_review_summary.json"
    write_json(out_path, review)

    print("Phase C review")
    print(f"run_dir: {review['run_dir']}")
    print(f"status: {review['phase_c_status']} ({review['phase_c_quality_band']})")
    for row in review["qc_rows"]:
        print(f"- {row['check']}: {row['status']} | value={row['value']} | expected={row['expected']}")
    print(f"saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
