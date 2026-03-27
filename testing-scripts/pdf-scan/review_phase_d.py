#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional

from phase_d_lab import (
    clean_text,
    flatten_retrieval_views,
    read_json,
    read_jsonl_rows,
    text_contains_term,
    write_json,
)


def find_run_dir(base_dir: Path, run_id: Optional[str]) -> Path:
    runs_dir = base_dir / "runs"
    if run_id:
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")
        return run_dir
    candidates = [
        path
        for path in runs_dir.iterdir()
        if path.is_dir()
        and (path / "retrieval" / "phase_d_assessment.json").exists()
        and (path / "query_plan.json").exists()
    ]
    if not candidates:
        raise FileNotFoundError(f"No Phase D runs found under {runs_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def read_optional_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return read_json(path)


def gather_term_examples(plan: Dict[str, Any], sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for kind in ["must_terms", "should_terms"]:
        for term in plan.get(kind) or []:
            matching_titles = []
            matching_docs = set()
            title_hits = 0
            text_hits = 0
            for row in sections:
                title = clean_text(row.get("title") or "")
                text = clean_text(row.get("contextualized_text") or row.get("text") or "")
                matched_title = text_contains_term(title, term)
                matched_text = text_contains_term(text, term)
                if matched_title:
                    title_hits += 1
                if matched_text:
                    text_hits += 1
                if matched_title or matched_text:
                    matching_titles.append(title)
                    matching_docs.add(str(row.get("doc_id") or ""))
            rows.append(
                {
                    "kind": "must" if kind == "must_terms" else "should",
                    "term": term,
                    "title_hits": title_hits,
                    "text_hits": text_hits,
                    "doc_hits": len([doc for doc in matching_docs if doc]),
                    "example_titles": list(dict.fromkeys([title for title in matching_titles if title]))[:5],
                }
            )
    return rows


def gather_subpoint_examples(plan: Dict[str, Any], sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for subpoint in plan.get("subpoints") or []:
        terms = list(subpoint.get("source_anchors") or []) + list(subpoint.get("must_terms") or []) + list(subpoint.get("should_terms") or [])
        terms = [term for i, term in enumerate(terms) if term and term not in terms[:i]]
        titles = []
        docs = set()
        for row in sections:
            title = clean_text(row.get("title") or "")
            text = clean_text(row.get("contextualized_text") or row.get("text") or "")
            hit_count = sum(1 for term in terms if text_contains_term(title, term) or text_contains_term(text, term))
            if hit_count > 0:
                titles.append(title)
                docs.add(str(row.get("doc_id") or ""))
        rows.append(
            {
                "subpoint_id": subpoint.get("subpoint_id"),
                "label": subpoint.get("label"),
                "matched_docs": len([doc for doc in docs if doc]),
                "matched_sections": len(titles),
                "example_titles": list(dict.fromkeys([title for title in titles if title]))[:5],
            }
        )
    return rows


def categorize_review(assessment: Dict[str, Any], corpus_support: Dict[str, Any]) -> str:
    status = str(assessment.get("status") or "")
    warning_count = len(assessment.get("warnings") or [])
    unsupported_must = int((corpus_support.get("summary") or {}).get("must_term_unsupported_count") or 0)
    unsupported_subpoints = int((corpus_support.get("summary") or {}).get("subpoints_without_support") or 0)
    if status == "failed":
        return "needs_follow_up"
    if unsupported_must > 0 or unsupported_subpoints > 0 or warning_count >= 3:
        return "acceptable_with_noise"
    return "strong"


def build_review(run_dir: Path) -> Dict[str, Any]:
    query_plan_payload = read_optional_json(run_dir / "query_plan.json")
    query_views = read_optional_json(run_dir / "retrieval" / "query_views.json")
    planner_trace = read_optional_json(run_dir / "retrieval" / "planner_trace.json")
    phase_d_assessment = read_optional_json(run_dir / "retrieval" / "phase_d_assessment.json")
    corpus_support = read_optional_json(run_dir / "retrieval" / "phase_d_corpus_support.json")
    sections = read_jsonl_rows(run_dir / "normalized" / "sections.jsonl")

    plan = dict(query_plan_payload.get("query_plan") or {})
    assessment = dict(phase_d_assessment.get("assessment") or {})
    review_category = categorize_review(assessment, corpus_support)
    term_examples = gather_term_examples(plan, sections)
    subpoint_examples = gather_subpoint_examples(plan, sections)
    flattened_views = flatten_retrieval_views(query_views) if query_views else []

    unsupported_must_terms = [row for row in term_examples if row.get("kind") == "must" and int(row.get("title_hits") or 0) + int(row.get("text_hits") or 0) == 0]
    unsupported_subpoints = [row for row in subpoint_examples if int(row.get("matched_sections") or 0) == 0]
    long_views = [row for row in flattened_views if int(row.get("query_word_count") or 0) > 80]

    findings: List[str] = []
    if unsupported_must_terms:
        findings.append(f"{len(unsupported_must_terms)} must terms have zero lexical support in the current corpus")
    if unsupported_subpoints:
        findings.append(f"{len(unsupported_subpoints)} subpoints have zero lexical support in the current corpus")
    if long_views:
        findings.append(f"{len(long_views)} retrieval views are very long and may be noisy")
    if not findings:
        findings.append("no material review findings")

    summary = {
        "run_id": run_dir.name,
        "review_category": review_category,
        "planner_mode": planner_trace.get("planner_mode"),
        "api_mode": planner_trace.get("api_mode"),
        "model_used": planner_trace.get("model_used") or planner_trace.get("model_requested"),
        "estimated_cost_usd": (planner_trace.get("cost") or {}).get("estimated_cost_usd"),
        "source_alignment_ratio": assessment.get("source_alignment_ratio"),
        "warning_count": len(assessment.get("warnings") or []),
        "failure_count": len(assessment.get("failures") or []),
        "source_anchor_count": len(plan.get("source_anchors") or []),
        "must_term_count": len(plan.get("must_terms") or []),
        "should_term_count": len(plan.get("should_terms") or []),
        "subpoint_count": len(plan.get("subpoints") or []),
        "retrieval_view_count": len(flattened_views),
        "must_term_unsupported_count": len(unsupported_must_terms),
        "subpoints_without_support_count": len(unsupported_subpoints),
        "findings": findings,
    }
    return {
        "summary": summary,
        "query_plan": plan,
        "planner_trace": planner_trace,
        "assessment": assessment,
        "corpus_support": corpus_support,
        "term_examples": term_examples,
        "subpoint_examples": subpoint_examples,
        "view_rows": flattened_views,
        "unsupported_must_terms": unsupported_must_terms,
        "unsupported_subpoints": unsupported_subpoints,
        "long_views": long_views,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Review a Phase D planner run.")
    parser.add_argument("--base-dir", default="pdf-scan", help="Path to pdf-scan")
    parser.add_argument("--run-id", default=None, help="Run id under pdf-scan/runs")
    parser.add_argument("--output-dir", default=None, help="Optional explicit output directory")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    run_dir = find_run_dir(base_dir, args.run_id)
    review = build_review(run_dir)

    output_dir = Path(args.output_dir).resolve() if args.output_dir else run_dir / "phase_d_review"
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "phase_d_review_summary.json", review["summary"])
    write_json(output_dir / "term_examples.json", {"rows": review["term_examples"]})
    write_json(output_dir / "subpoint_examples.json", {"rows": review["subpoint_examples"]})
    write_json(output_dir / "view_rows.json", {"rows": review["view_rows"]})
    write_json(output_dir / "unsupported_must_terms.json", {"rows": review["unsupported_must_terms"]})
    write_json(output_dir / "unsupported_subpoints.json", {"rows": review["unsupported_subpoints"]})

    print("=" * 80)
    print("Phase D Review")
    print("=" * 80)
    for key, value in review["summary"].items():
        if isinstance(value, list):
            print(f"{key:28} {'; '.join(str(item) for item in value)}")
        else:
            print(f"{key:28} {value}")
    print("=" * 80)
    print("Unsupported Must Terms")
    print("=" * 80)
    for row in review["unsupported_must_terms"][:10]:
        print(f"- {row['term']} | title_hits={row['title_hits']} | text_hits={row['text_hits']} | docs={row['doc_hits']}")
    print("=" * 80)
    print("Subpoint Support")
    print("=" * 80)
    for row in review["subpoint_examples"][:10]:
        print(f"- {row['subpoint_id']} | matched_docs={row['matched_docs']} | matched_sections={row['matched_sections']} | {row['label']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
