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

    candidates = [path for path in runs_dir.iterdir() if path.is_dir() and (path / "parser" / "phase_b_summary.json").exists()]
    if not candidates:
        raise FileNotFoundError(f"No Phase B run found under {runs_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def classify_docling_issue(docling_payload: Dict[str, Any]) -> str:
    combined = "\n".join(
        [
            str(docling_payload.get("error") or ""),
            str(docling_payload.get("stderr") or ""),
            json.dumps((docling_payload.get("result") or {}).get("errors") or [], ensure_ascii=False),
        ]
    ).lower()
    if "std::bad_alloc" in combined:
        return "memory"
    if "not valid, skipping conversion" in combined or "inconsistent number of pages" in combined:
        return "invalid_pdf"
    if "page_count=" in combined and "page limit" in combined:
        return "page_limit"
    if not combined.strip():
        return "none"
    return "other"


def resolve_path(run_dir: Path, rel_path: str | None) -> Path | None:
    if not rel_path:
        return None
    path = Path(rel_path)
    return path if path.is_absolute() else (run_dir / path)


def build_review(run_dir: Path) -> Dict[str, Any]:
    summary = read_json(run_dir / "parser" / "phase_b_summary.json")
    assessment = read_json(run_dir / "parser" / "phase_b_assessment.json")
    bundles = read_jsonl(run_dir / "parser" / "parsed_document_bundles.jsonl")
    metrics = read_json(run_dir / "metrics.json")

    doc_rows: List[Dict[str, Any]] = []
    error_categories: Dict[str, int] = {}

    for bundle in bundles:
        docling_path = resolve_path(run_dir, bundle.get("docling_json"))
        diagnostics_path = resolve_path(run_dir, bundle.get("diagnostics_json"))
        metadata_path = resolve_path(run_dir, bundle.get("metadata_json"))
        docling = read_json(docling_path) if docling_path and docling_path.exists() else {}
        diagnostics = read_json(diagnostics_path) if diagnostics_path and diagnostics_path.exists() else {}
        metadata = read_json(metadata_path) if metadata_path and metadata_path.exists() else {}
        doc_summary = docling.get("document_summary") or {}
        attempts = list(docling.get("attempts") or [])
        chunking = dict(docling.get("chunking") or {})
        header_count = int(doc_summary.get("section_header_count") or len(docling.get("section_headers") or []))
        issue_category = classify_docling_issue(docling)
        error_categories[issue_category] = int(error_categories.get(issue_category) or 0) + 1

        doc_rows.append(
            {
                "doc_id": bundle.get("doc_id"),
                "file_name": metadata.get("file_name"),
                "page_count": metadata.get("page_count"),
                "outline_count": max(
                    len(((metadata.get("fitz") or {}).get("outline") or [])),
                    len(((metadata.get("pypdf") or {}).get("outline") or [])),
                ),
                "docling_status": docling.get("status"),
                "docling_mode": docling.get("selected_mode"),
                "docling_section_header_count": header_count,
                "docling_attempt_count": len(attempts),
                "docling_chunk_count": int(chunking.get("chunk_count") or 0),
                "docling_confidence": docling.get("confidence_summary"),
                "fallback_activated": diagnostics.get("fallback_activated"),
                "pages_with_text_pct": ((metadata.get("fitz") or {}).get("text_coverage") or {}).get("percent_pages_with_text"),
                "issue_category": issue_category,
                "markdown_preview_available": bool(docling.get("markdown_preview")),
            }
        )

    header_counts = [int(row["docling_section_header_count"]) for row in doc_rows if row.get("docling_status") in {"success", "partial_success"}]
    chunked_docs = [row["doc_id"] for row in doc_rows if str(row.get("docling_mode") or "") == "chunked"]
    headerless_docs = [
        row["doc_id"]
        for row in doc_rows
        if row.get("docling_status") in {"success", "partial_success"} and int(row.get("docling_section_header_count") or 0) == 0
    ]
    fallback_docs = [row["doc_id"] for row in doc_rows if row.get("fallback_activated")]

    qc_rows = [
        {
            "check": "documents_match_bundle_count",
            "status": "OK" if len(doc_rows) == len(summary.get("documents") or []) else "FAIL",
            "value": len(doc_rows),
            "expected": len(summary.get("documents") or []),
        },
        {
            "check": "phase_b_metrics_present",
            "status": "OK" if bool(((metrics.get("stages") or {}).get("phase_b") or {})) else "FAIL",
            "value": bool(((metrics.get("stages") or {}).get("phase_b") or {})),
            "expected": True,
        },
        {
            "check": "chunked_docs_have_chunking_metadata",
            "status": "OK" if all(int(row.get("docling_chunk_count") or 0) > 0 for row in doc_rows if row.get("docling_mode") == "chunked") else "FAIL",
            "value": len(chunked_docs),
            "expected": "all chunked docs expose chunk_count > 0",
        },
        {
            "check": "success_like_docs_have_headers",
            "status": "OK" if not headerless_docs else "WARN",
            "value": "none" if not headerless_docs else ", ".join(headerless_docs[:4]),
            "expected": "none",
        },
        {
            "check": "phase_b_can_continue",
            "status": "OK" if bool(((assessment.get("assessment") or {}).get("can_continue_to_next_phase"))) else "FAIL",
            "value": bool(((assessment.get("assessment") or {}).get("can_continue_to_next_phase"))),
            "expected": True,
        },
    ]

    return {
        "run_dir": str(run_dir),
        "run_id": run_dir.name,
        "phase_b_status": ((assessment.get("assessment") or {}).get("status")),
        "phase_b_quality_band": ((assessment.get("assessment") or {}).get("quality_band")),
        "documents_processed": len(doc_rows),
        "docling_review": {
            "success_like_count": sum(1 for row in doc_rows if row.get("docling_status") in {"success", "partial_success"}),
            "chunked_selected_count": len(chunked_docs),
            "chunked_selected_docs": chunked_docs,
            "headerless_success_like_count": len(headerless_docs),
            "headerless_success_like_docs": headerless_docs,
            "fallback_doc_count": len(fallback_docs),
            "fallback_docs": fallback_docs,
            "section_header_count_min": min(header_counts) if header_counts else None,
            "section_header_count_median": statistics.median(header_counts) if header_counts else None,
            "section_header_count_max": max(header_counts) if header_counts else None,
            "issue_categories": error_categories,
        },
        "documents": doc_rows,
        "qc_rows": qc_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Review a Phase B parser run.")
    parser.add_argument("--base-dir", default="pdf-scan")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    run_dir = find_run_dir(Path(args.base_dir).resolve(), args.run_id)
    review = build_review(run_dir)
    out_path = run_dir / "phase_b_review" / "phase_b_review_summary.json"
    write_json(out_path, review)

    print("Phase B review")
    print(f"run_dir: {review['run_dir']}")
    print(f"status: {review['phase_b_status']} ({review['phase_b_quality_band']})")
    for row in review["qc_rows"]:
        print(f"- {row['check']}: {row['status']} | value={row['value']} | expected={row['expected']}")
    print(f"saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
