#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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

    candidates = [path for path in runs_dir.iterdir() if path.is_dir() and (path / "phase_b_review" / "phase_b_review_summary.json").exists() and (path / "phase_c_review" / "phase_c_review_summary.json").exists()]
    if not candidates:
        raise FileNotFoundError(f"No Phase B/C review run found under {runs_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def classify_document(phase_b: Dict[str, Any], phase_c: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[str] = []
    strengths: List[str] = []

    page_count = int(phase_b.get("page_count") or phase_c.get("page_count") or 0)
    section_count = int(phase_c.get("section_count") or 0)
    sections_per_page = float(phase_c.get("sections_per_page") or 0.0)
    suppressed_count = int(phase_c.get("retrieval_suppressed_section_count") or 0)
    fallback_anchor_count = int(phase_c.get("fallback_anchor_count") or 0)
    eligible_tiny_count = int(phase_c.get("retrieval_eligible_tiny_section_count") or 0)
    docling_status = str(phase_b.get("docling_status") or "")
    fallback_activated = bool(phase_b.get("fallback_activated"))

    if docling_status == "failure":
        issues.append("docling_failure")
    if docling_status == "skipped_page_limit":
        issues.append("docling_skipped_page_limit")
    if fallback_activated:
        issues.append("fallback_parser_path")
    if fallback_anchor_count > 0:
        issues.append(f"fallback_anchors={fallback_anchor_count}")
    if eligible_tiny_count > 0:
        issues.append(f"retrieval_eligible_tiny_sections={eligible_tiny_count}")
    if sections_per_page > 2.0:
        issues.append(f"high_section_density={sections_per_page:.3f}")
    if section_count and (suppressed_count / max(1, section_count)) >= 0.25:
        issues.append(f"many_suppressed_wrappers={suppressed_count}/{section_count}")

    if docling_status == "success" and not fallback_activated:
        strengths.append("docling_success")
    if str(phase_b.get("docling_mode") or "") == "chunked":
        strengths.append("chunked_docling_recovery")
    if fallback_anchor_count == 0:
        strengths.append("no_fallback_anchors")
    if eligible_tiny_count == 0:
        strengths.append("no_retrieval_eligible_tiny_sections")
    if float(phase_c.get("section_coverage_pct") or 0.0) >= 99.5:
        strengths.append("high_section_coverage")

    if any(issue in issues for issue in ["docling_failure", "docling_skipped_page_limit", "fallback_parser_path"]) or fallback_anchor_count >= 3 or eligible_tiny_count > 0:
        category = "needs_follow_up"
    elif sections_per_page > 2.0 or fallback_anchor_count > 0 or (section_count and (suppressed_count / max(1, section_count)) >= 0.25):
        category = "acceptable_with_noise"
    else:
        category = "strong"

    return {
        "category": category,
        "issues": issues,
        "strengths": strengths,
        "page_count": page_count,
        "section_count": section_count,
        "passage_count": int(phase_c.get("passage_count") or 0),
        "section_coverage_pct": phase_c.get("section_coverage_pct"),
        "sections_per_page": sections_per_page,
    }


def build_review(run_dir: Path) -> Dict[str, Any]:
    phase_b_review = read_json(run_dir / "phase_b_review" / "phase_b_review_summary.json")
    phase_c_review = read_json(run_dir / "phase_c_review" / "phase_c_review_summary.json")
    phase_c_summary = read_json(run_dir / "normalized" / "phase_c_summary.json")

    phase_b_by_doc = {str(row.get("doc_id") or ""): row for row in (phase_b_review.get("documents") or [])}
    phase_c_by_doc = {str(row.get("doc_id") or ""): row for row in (phase_c_review.get("documents") or [])}
    phase_c_summary_by_doc = {str(row.get("doc_id") or ""): row for row in (phase_c_summary.get("documents") or [])}

    doc_rows: List[Dict[str, Any]] = []
    category_counts: Dict[str, int] = {"strong": 0, "acceptable_with_noise": 0, "needs_follow_up": 0}

    for doc_id, phase_b_doc in sorted(phase_b_by_doc.items()):
        phase_c_doc = dict(phase_c_by_doc.get(doc_id) or {})
        phase_c_doc.update(phase_c_summary_by_doc.get(doc_id) or {})
        classified = classify_document(phase_b_doc, phase_c_doc)
        category_counts[classified["category"]] = category_counts.get(classified["category"], 0) + 1
        doc_rows.append(
            {
                "doc_id": doc_id,
                "title": phase_c_doc.get("file_name") or phase_c_doc.get("title"),
                "category": classified["category"],
                "issues": classified["issues"],
                "strengths": classified["strengths"],
                "page_count": classified["page_count"],
                "docling_status": phase_b_doc.get("docling_status"),
                "docling_mode": phase_b_doc.get("docling_mode"),
                "fallback_activated": phase_b_doc.get("fallback_activated"),
                "outline_count": phase_b_doc.get("outline_count"),
                "section_count": classified["section_count"],
                "passage_count": classified["passage_count"],
                "section_coverage_pct": classified["section_coverage_pct"],
                "sections_per_page": classified["sections_per_page"],
                "fallback_anchor_count": phase_c_doc.get("fallback_anchor_count"),
                "retrieval_eligible_tiny_section_count": phase_c_doc.get("retrieval_eligible_tiny_section_count"),
                "retrieval_suppressed_section_count": phase_c_doc.get("retrieval_suppressed_section_count"),
                "strategy": phase_c_doc.get("strategy"),
            }
        )

    return {
        "run_dir": str(run_dir),
        "run_id": run_dir.name,
        "phase_b_status": phase_b_review.get("phase_b_status"),
        "phase_c_status": phase_c_review.get("phase_c_status"),
        "category_counts": category_counts,
        "documents": doc_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate review for a Phase B/C run.")
    parser.add_argument("--base-dir", default="pdf-scan")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    run_dir = find_run_dir(Path(args.base_dir).resolve(), args.run_id)
    review = build_review(run_dir)
    out_path = run_dir / "phase_bc_review" / "phase_bc_review_summary.json"
    write_json(out_path, review)

    print("Phase B/C review")
    print(f"run_dir: {review['run_dir']}")
    print(f"phase_b_status: {review['phase_b_status']}")
    print(f"phase_c_status: {review['phase_c_status']}")
    print(f"category_counts: {review['category_counts']}")
    print(f"saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
