#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


GENERIC_TITLES = {
    "abstract",
    "background",
    "conclusion",
    "discussion",
    "introduction",
    "method",
    "methods",
    "results",
}

ADMIN_TITLES = {
    "acmreference format",
    "author contributions",
    "conflict of interest",
    "conflict of interest statement",
    "contents",
    "copyright page",
    "data availability",
    "front matter",
    "index",
    "open access",
    "references",
    "table of contents",
    "title page",
}

NOISE_PATTERNS = [
    (r"@", "email"),
    (r"creative commons", "license"),
    (r"commons\.org/licenses", "license"),
    (r"frontiers in", "journal_header"),
    (r"citation:", "citation_block"),
    (r"downloaded from", "download_notice"),
    (r"\bvolume \d+\b", "journal_header"),
    (r"\barticle \d+\b", "journal_header"),
]


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_md(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def normalize_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def snippet(text: Any, limit: int = 360) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def is_generic_title(title: Any) -> bool:
    low = normalize_text(title)
    if low in GENERIC_TITLES:
        return True
    return bool(re.fullmatch(r"\d+\.?\s+(introduction|discussion|conclusion|results|methods?)", low))


def is_admin_title(title: Any) -> bool:
    low = normalize_text(title)
    return low in ADMIN_TITLES or "reference format" in low


def normalize_subpoint_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def is_reference_like_title(title: Any) -> bool:
    value = str(title or "").strip()
    if not value:
        return False
    if re.match(r"^[A-Z][A-Za-z'’.-]+,\s+(?:[A-Z]\.\s*){1,4}", value):
        return True
    if re.match(r"^[A-Z][A-Za-z'’.-]+,\s*[A-Z](?:\.)?,\s*(?:and|&)\s+[A-Z][A-Za-z'’.-]+,\s*[A-Z](?:\.)?\.?$", value):
        return True
    if re.search(r"\(\d{4}\)\.?$", value) and "," in value:
        return True
    if value[:1].islower():
        return True
    if re.match(r"^report no\.", normalize_text(value)):
        return True
    return False


def text_noise_flags(text: Any) -> List[str]:
    found: List[str] = []
    low = str(text or "")
    for pattern, label in NOISE_PATTERNS:
        if re.search(pattern, low, flags=re.IGNORECASE):
            found.append(label)
    return sorted(set(found))


def candidate_issues(candidate: Dict[str, Any], section: Dict[str, Any]) -> List[str]:
    issues: List[str] = []
    if not bool(section.get("retrieval_eligible", True)):
        issues.append("retrieval_suppressed_leak")
    if is_admin_title(candidate.get("title")):
        issues.append("admin_title")
    if is_reference_like_title(candidate.get("title")):
        issues.append("reference_like_title")
    if is_generic_title(candidate.get("title")) and int(candidate.get("supporting_passage_count") or 0) < 2:
        issues.append("weak_generic_title")
    issues.extend(text_noise_flags(section.get("text")))
    return sorted(set(issues))


def summarize_top(candidates: List[Dict[str, Any]], sections_by_id: Dict[str, Dict[str, Any]], *, top_k: int) -> Dict[str, Any]:
    top = candidates[:top_k]
    issue_counter = Counter()
    doc_counter = Counter()
    subpoint_counter = Counter()
    issue_rows = []
    for row in top:
        section = sections_by_id.get(str(row.get("section_id") or "")) or {}
        issues = candidate_issues(row, section)
        issue_counter.update(issues)
        doc_counter.update([str(row.get("doc_id") or "")])
        subpoint_counter.update(normalize_subpoint_list(row.get("trusted_subpoints")))
        issue_rows.append(
            {
                "fused_rank": row.get("fused_rank"),
                "doc_id": row.get("doc_id"),
                "title": row.get("title"),
                "section_type": row.get("section_type"),
                "issues": issues,
                "supporting_passage_count": row.get("supporting_passage_count"),
                "trusted_subpoints": normalize_subpoint_list(row.get("trusted_subpoints")),
                "text_snippet": snippet(section.get("text")),
            }
        )
    suspicious_rows = [row for row in issue_rows if row["issues"]]
    return {
        "top_k": top_k,
        "unique_doc_count": len([doc for doc in doc_counter if doc]),
        "doc_counts": dict(doc_counter),
        "subpoint_counts": dict(subpoint_counter),
        "issue_counts": dict(issue_counter),
        "suspicious_candidate_count": len(suspicious_rows),
        "suspicious_candidates": suspicious_rows[:20],
        "rows": issue_rows,
    }


def review_run(base_dir: Path, run_id: str) -> Dict[str, Any]:
    run_dir = base_dir / "runs" / run_id
    retrieval_dir = run_dir / "retrieval"
    normalized_dir = run_dir / "normalized"
    candidates = read_jsonl(retrieval_dir / "fused_candidates.jsonl")
    sections = read_jsonl(normalized_dir / "sections.jsonl")
    summary = read_json(retrieval_dir / "phase_e_summary.json")
    assessment = read_json(retrieval_dir / "phase_e_assessment.json")
    sections_by_id = {str(row.get("section_id") or ""): row for row in sections if str(row.get("section_id") or "")}

    top20 = summarize_top(candidates, sections_by_id, top_k=20)
    top50 = summarize_top(candidates, sections_by_id, top_k=50)

    review_category = "strong"
    if top20["issue_counts"].get("retrieval_suppressed_leak", 0) > 0:
        review_category = "needs_follow_up"
    elif top20["suspicious_candidate_count"] >= 8 or top20["issue_counts"].get("reference_like_title", 0) >= 3:
        review_category = "acceptable_with_noise"

    return {
        "run_id": run_id,
        "review_category": review_category,
        "phase_e_fused_candidate_count": len(candidates),
        "phase_e_supported_subpoints": list((summary.get("supported_subpoint_ids") or [])),
        "phase_e_dense_mode": ((summary.get("dense_trace") or {}).get("dense_mode")),
        "phase_e_embedding_cost_usd": (((summary.get("dense_trace") or {}).get("cost") or {}).get("estimated_cost_usd")),
        "assessment_status": ((assessment.get("assessment") or {}).get("status")),
        "top20": top20,
        "top50": top50,
    }


def render_markdown(review: Dict[str, Any]) -> str:
    top20 = review["top20"]
    lines = [
        f"# Pipeline A-E Review: `{review['run_id']}`",
        "",
        f"- Review category: `{review['review_category']}`",
        f"- Fused candidates: `{review['phase_e_fused_candidate_count']}`",
        f"- Supported subpoints: `{', '.join(review['phase_e_supported_subpoints']) or 'none'}`",
        f"- Dense mode: `{review['phase_e_dense_mode']}`",
        f"- Embedding cost USD: `{review['phase_e_embedding_cost_usd']}`",
        "",
        "## Top-20 summary",
        "",
        f"- Unique docs in top 20: `{top20['unique_doc_count']}`",
        f"- Suspicious candidates in top 20: `{top20['suspicious_candidate_count']}`",
        f"- Issue counts: `{json.dumps(top20['issue_counts'], ensure_ascii=False)}`",
        f"- Doc counts: `{json.dumps(top20['doc_counts'], ensure_ascii=False)}`",
        "",
        "## Suspicious top-20 candidates",
        "",
    ]
    if not top20["suspicious_candidates"]:
        lines.append("None.")
    else:
        for row in top20["suspicious_candidates"]:
            lines.extend(
                [
                    f"### Rank {row['fused_rank']}: {row['title']}",
                    f"- Doc: `{row['doc_id']}`",
                    f"- Issues: `{', '.join(row['issues'])}`",
                    f"- Trusted subpoints: `{', '.join(row['trusted_subpoints']) or 'none'}`",
                    f"- Supporting passages: `{row['supporting_passage_count']}`",
                    f"- Snippet: `{row['text_snippet']}`",
                    "",
                ]
            )
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit full pipeline A-E outputs for one run.")
    parser.add_argument("--base-dir", default="pdf-scan")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    review = review_run(base_dir, args.run_id)
    out_dir = base_dir / "runs" / args.run_id / "pipeline_ae_review"
    write_json(out_dir / "pipeline_ae_review_summary.json", review)
    write_md(out_dir / "pipeline_ae_review.md", render_markdown(review))
    print(json.dumps(review, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
