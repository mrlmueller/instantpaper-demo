#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def ascii_fold(value: Any) -> str:
    text = str(value or "")
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii")


def norm_text(value: Any) -> str:
    text = ascii_fold(value).lower()
    text = re.sub(r"[^a-z0-9*]+", " ", text)
    return " ".join(text.split())


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def find_run_dir(base_dir: Path, run_id: str | None) -> Path:
    runs_dir = base_dir / "runs"
    if run_id:
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")
        return run_dir

    candidates = [path for path in runs_dir.iterdir() if path.is_dir() and (path / "query_plan.json").exists()]
    if not candidates:
        raise FileNotFoundError(f"No run with query_plan.json found under {runs_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def contains_term(haystack: str, term: str) -> bool:
    needle_tokens = norm_text(term).split()
    haystack_tokens = norm_text(haystack).split()
    if not needle_tokens or not haystack_tokens or len(needle_tokens) > len(haystack_tokens):
        return False
    limit = len(haystack_tokens) - len(needle_tokens) + 1
    for start in range(limit):
        ok = True
        for offset, needle in enumerate(needle_tokens):
            candidate = haystack_tokens[start + offset]
            if needle.endswith("*"):
                prefix = needle[:-1]
                if not prefix or not candidate.startswith(prefix):
                    ok = False
                    break
            elif candidate != needle:
                ok = False
                break
        if ok:
            return True
    return False


def summarize_counter(counter: Counter, top_n: int | None = None) -> List[Dict[str, Any]]:
    items = counter.most_common(top_n)
    return [{"label": key, "count": value} for key, value in items]


def build_term_coverage(
    sections: List[Dict[str, Any]],
    must_terms: List[str],
    penalized_types: set[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    doc_ids = sorted({str(row.get("doc_id") or "") for row in sections})
    non_penalized_sections = [row for row in sections if str(row.get("section_type") or "") not in penalized_types]
    coverage_rows: List[Dict[str, Any]] = []
    hit_terms = 0

    for term in must_terms:
        title_hits = 0
        text_hits = 0
        docs_hit = set()
        for row in non_penalized_sections:
            title_norm = norm_text(row.get("title"))
            text_norm = norm_text(row.get("contextualized_text") or row.get("text"))
            if contains_term(title_norm, term):
                title_hits += 1
                docs_hit.add(str(row.get("doc_id") or ""))
            elif contains_term(text_norm, term):
                text_hits += 1
                docs_hit.add(str(row.get("doc_id") or ""))

        if title_hits or text_hits:
            hit_terms += 1

        coverage_rows.append(
            {
                "term": term,
                "docs_hit": len(docs_hit),
                "doc_coverage_ratio": round(len(docs_hit) / max(1, len(doc_ids)), 3),
                "title_hits": title_hits,
                "text_hits": text_hits,
                "total_section_hits": title_hits + text_hits,
            }
        )

    summary = {
        "must_term_count": len(must_terms),
        "terms_hit_anywhere": hit_terms,
        "term_hit_ratio": round(hit_terms / max(1, len(must_terms)), 3),
        "mean_docs_hit": round(statistics.mean([row["docs_hit"] for row in coverage_rows]), 3) if coverage_rows else 0.0,
        "median_docs_hit": statistics.median([row["docs_hit"] for row in coverage_rows]) if coverage_rows else 0,
    }
    return coverage_rows, summary


def score_section(
    section: Dict[str, Any],
    query_plan: Dict[str, Any],
    penalized_types: set[str],
    preferred_types: set[str],
) -> Dict[str, Any]:
    section_type = str(section.get("section_type") or "")
    title_norm = norm_text(section.get("title"))
    text_norm = norm_text(section.get("contextualized_text") or section.get("text"))
    score = 0.0
    matched_must_terms: List[str] = []
    matched_should_terms: List[str] = []
    matched_subpoints: List[str] = []

    for term in query_plan.get("must_terms") or []:
        title_hit = contains_term(title_norm, term)
        text_hit = contains_term(text_norm, term)
        if title_hit:
            score += 5.0
            matched_must_terms.append(term)
        elif text_hit:
            score += 2.0
            matched_must_terms.append(term)

    for term in query_plan.get("should_terms") or []:
        title_hit = contains_term(title_norm, term)
        text_hit = contains_term(text_norm, term)
        if title_hit:
            score += 2.0
            matched_should_terms.append(term)
        elif text_hit:
            score += 0.75
            matched_should_terms.append(term)

    for subpoint in query_plan.get("subpoints") or []:
        label = str(subpoint.get("label") or subpoint.get("subpoint_id") or "subpoint")
        subpoint_hit = False
        for term in subpoint.get("must_terms") or []:
            if contains_term(title_norm, term):
                score += 2.0
                subpoint_hit = True
            elif contains_term(text_norm, term):
                score += 0.9
                subpoint_hit = True
        if subpoint_hit:
            matched_subpoints.append(label)

    if section_type in preferred_types:
        score += 1.0
    if section_type in penalized_types:
        score -= 8.0
    if "tiny_section" in set(section.get("quality_flags") or []):
        score -= 1.5
    if "synthetic" in set(section.get("quality_flags") or []):
        score -= 0.5

    return {
        "score": round(score, 3),
        "matched_must_terms": sorted(set(matched_must_terms)),
        "matched_should_terms": sorted(set(matched_should_terms)),
        "matched_subpoints": sorted(set(matched_subpoints)),
    }


def build_candidate_rows(
    sections: List[Dict[str, Any]],
    query_plan: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    penalized_types = set(query_plan.get("penalized_section_types") or [])
    preferred_types = set(query_plan.get("preferred_section_types") or [])
    rows: List[Dict[str, Any]] = []

    for section in sections:
        score_row = score_section(section, query_plan, penalized_types, preferred_types)
        preview = " ".join(str(section.get("text") or "").split())[:220]
        rows.append(
            {
                "doc_id": str(section.get("doc_id") or ""),
                "section_id": str(section.get("section_id") or ""),
                "title": str(section.get("title") or ""),
                "section_type": str(section.get("section_type") or ""),
                "page_start": section.get("page_start"),
                "page_end": section.get("page_end"),
                "score": score_row["score"],
                "matched_must_terms": "; ".join(score_row["matched_must_terms"]),
                "matched_should_terms": "; ".join(score_row["matched_should_terms"]),
                "matched_subpoints": "; ".join(score_row["matched_subpoints"]),
                "penalized": str(section.get("section_type") or "") in penalized_types,
                "quality_flags": "; ".join(section.get("quality_flags") or []),
                "parser_sources": "; ".join(section.get("parser_sources") or []),
                "preview": preview,
            }
        )

    rows.sort(
        key=lambda row: (
            float(row.get("score") or 0.0),
            not bool(row.get("penalized")),
            -len(str(row.get("matched_must_terms") or "")),
            str(row.get("doc_id") or ""),
        ),
        reverse=True,
    )

    top20 = rows[:20]
    top20_penalized = sum(1 for row in top20 if row["penalized"])
    unique_docs_top20 = sorted({row["doc_id"] for row in top20})
    summary = {
        "top20_penalized_count": top20_penalized,
        "top20_penalized_ratio": round(top20_penalized / max(1, len(top20)), 3),
        "top20_unique_docs": len(unique_docs_top20),
        "top20_doc_ids": unique_docs_top20,
        "top_score": float(top20[0]["score"]) if top20 else 0.0,
    }
    return rows, summary


def build_doc_rows(
    sections: List[Dict[str, Any]],
    passages: List[Dict[str, Any]],
    candidate_rows: List[Dict[str, Any]],
    query_plan: Dict[str, Any],
) -> List[Dict[str, Any]]:
    penalized_types = set(query_plan.get("penalized_section_types") or [])
    passages_by_doc = Counter(str(row.get("doc_id") or "") for row in passages)
    candidates_by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in candidate_rows:
        candidates_by_doc[row["doc_id"]].append(row)

    sections_by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for section in sections:
        sections_by_doc[str(section.get("doc_id") or "")].append(section)

    doc_rows: List[Dict[str, Any]] = []
    for doc_id, doc_sections in sorted(sections_by_doc.items()):
        type_counter = Counter(str(section.get("section_type") or "") for section in doc_sections)
        top_rows = candidates_by_doc.get(doc_id, [])[:5]
        doc_rows.append(
            {
                "doc_id": doc_id,
                "section_count": len(doc_sections),
                "passage_count": passages_by_doc.get(doc_id, 0),
                "penalized_section_count": sum(1 for row in doc_sections if str(row.get("section_type") or "") in penalized_types),
                "body_other_count": type_counter.get("body_other", 0),
                "front_matter_count": type_counter.get("front_matter", 0),
                "reference_count": type_counter.get("references", 0),
                "appendix_count": type_counter.get("appendix", 0),
                "tiny_section_count": sum(1 for row in doc_sections if "tiny_section" in set(row.get("quality_flags") or [])),
                "synthetic_section_count": sum(1 for row in doc_sections if "synthetic" in set(row.get("quality_flags") or [])),
                "top_candidate_score": top_rows[0]["score"] if top_rows else 0.0,
                "top_candidate_title": top_rows[0]["title"] if top_rows else "",
                "top5_mean_score": round(statistics.mean([float(row["score"]) for row in top_rows]), 3) if top_rows else 0.0,
            }
        )
    return doc_rows


def build_review_flags(
    sections: List[Dict[str, Any]],
    query_plan: Dict[str, Any],
    phase_c_assessment: Dict[str, Any],
    phase_d_assessment: Dict[str, Any],
    term_summary: Dict[str, Any],
    candidate_summary: Dict[str, Any],
    candidate_rows: List[Dict[str, Any]],
) -> List[str]:
    flags: List[str] = []
    penalized_types = set(query_plan.get("penalized_section_types") or [])
    phase_d_ratio = (
        (phase_d_assessment.get("assessment") or {}).get("source_alignment_ratio")
        if isinstance(phase_d_assessment, dict)
        else None
    )
    if isinstance(phase_d_ratio, (int, float)) and phase_d_ratio < 0.35:
        flags.append(f"Phase D source alignment is low ({phase_d_ratio:.3f})")

    if float(candidate_summary.get("top20_penalized_ratio") or 0.0) > 0.0:
        flags.append(
            f"Penalized sections still appear in the lexical top-20 ({candidate_summary['top20_penalized_count']} of 20)"
        )

    if float(term_summary.get("term_hit_ratio") or 0.0) < 0.75:
        flags.append(
            f"Only {term_summary['terms_hit_anywhere']} of {term_summary['must_term_count']} must-terms appear in non-penalized sections"
        )

    front_matter_leaks = [
        row
        for row in sections
        if "front matter" in norm_text(row.get("title")) and str(row.get("section_type") or "") != "front_matter"
    ]
    if front_matter_leaks:
        flags.append(f"{len(front_matter_leaks)} front-matter-like sections are still misclassified")

    index_leaks = [
        row
        for row in sections
        if norm_text(row.get("title")) == "index" and str(row.get("section_type") or "") not in penalized_types
    ]
    if index_leaks:
        flags.append(f"{len(index_leaks)} index sections are still non-penalized")

    top20_index_leaks = [
        row for row in candidate_rows[:20] if norm_text(row.get("title")) == "index" and not bool(row.get("penalized"))
    ]
    if top20_index_leaks:
        flags.append(f"Index appears in the lexical top-20 ({len(top20_index_leaks)} hit)")

    phase_c_warnings = ((phase_c_assessment.get("assessment") or {}).get("warnings") or [])
    if phase_c_warnings:
        flags.extend(str(item) for item in phase_c_warnings)

    return flags


def build_report_markdown(
    run_id: str,
    phase_c_assessment: Dict[str, Any],
    phase_d_assessment: Dict[str, Any],
    query_plan: Dict[str, Any],
    doc_rows: List[Dict[str, Any]],
    term_rows: List[Dict[str, Any]],
    candidate_rows: List[Dict[str, Any]],
    flags: List[str],
) -> str:
    lines: List[str] = []
    lines.append(f"# Run Review: {run_id}")
    lines.append("")
    lines.append("## Stage Status")
    lines.append("")
    lines.append(
        f"- Phase C: {((phase_c_assessment.get('assessment') or {}).get('status') or 'unknown')} / "
        f"{((phase_c_assessment.get('assessment') or {}).get('quality_band') or 'unknown')}"
    )
    lines.append(
        f"- Phase D: {((phase_d_assessment.get('assessment') or {}).get('status') or 'unknown')} / "
        f"{((phase_d_assessment.get('assessment') or {}).get('quality_band') or 'unknown')}"
    )
    lines.append(f"- Must terms: {len(query_plan.get('must_terms') or [])}")
    lines.append(f"- Subpoints: {len(query_plan.get('subpoints') or [])}")
    lines.append("")

    lines.append("## Review Flags")
    lines.append("")
    if flags:
        for flag in flags:
            lines.append(f"- {flag}")
    else:
        lines.append("- No review flags")
    lines.append("")

    lines.append("## Per-Document Snapshot")
    lines.append("")
    lines.append("| doc_id | sections | passages | penalized | top candidate score | top candidate title |")
    lines.append("| --- | ---: | ---: | ---: | ---: | --- |")
    for row in doc_rows:
        lines.append(
            f"| {row['doc_id']} | {row['section_count']} | {row['passage_count']} | {row['penalized_section_count']} | "
            f"{row['top_candidate_score']} | {row['top_candidate_title']} |"
        )
    lines.append("")

    lines.append("## Must-Term Coverage")
    lines.append("")
    lines.append("| term | docs hit | title hits | text hits |")
    lines.append("| --- | ---: | ---: | ---: |")
    for row in term_rows:
        lines.append(f"| {row['term']} | {row['docs_hit']} | {row['title_hits']} | {row['text_hits']} |")
    lines.append("")

    lines.append("## Top Lexical Section Candidates")
    lines.append("")
    lines.append("| score | doc_id | type | title | matched must-terms |")
    lines.append("| ---: | --- | --- | --- | --- |")
    for row in candidate_rows[:20]:
        lines.append(
            f"| {row['score']} | {row['doc_id']} | {row['section_type']} | {row['title']} | {row['matched_must_terms']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Review Phase C / Phase D run outputs.")
    parser.add_argument("--base-dir", default=".", help="Path to the pdf-scan directory")
    parser.add_argument("--run-id", default=None, help="Run id under runs/. If omitted, uses the newest run with query_plan.json")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    run_dir = find_run_dir(base_dir, args.run_id)
    run_id = run_dir.name

    phase_c_assessment = read_json(run_dir / "normalized" / "phase_c_assessment.json")
    phase_d_assessment = read_json(run_dir / "retrieval" / "phase_d_assessment.json")
    query_plan = read_json(run_dir / "query_plan.json").get("query_plan") or {}
    sections = read_jsonl(run_dir / "normalized" / "sections.jsonl")
    passages = read_jsonl(run_dir / "normalized" / "passages.jsonl")

    penalized_types = set(query_plan.get("penalized_section_types") or [])
    section_type_counts = Counter(str(row.get("section_type") or "") for row in sections)
    quality_flag_counts = Counter(flag for row in sections for flag in (row.get("quality_flags") or []))
    parser_source_counts = Counter(source for row in sections for source in (row.get("parser_sources") or []))

    term_rows, term_summary = build_term_coverage(sections, query_plan.get("must_terms") or [], penalized_types)
    candidate_rows, candidate_summary = build_candidate_rows(sections, query_plan)
    doc_rows = build_doc_rows(sections, passages, candidate_rows, query_plan)
    flags = build_review_flags(
        sections=sections,
        query_plan=query_plan,
        phase_c_assessment=phase_c_assessment,
        phase_d_assessment=phase_d_assessment,
        term_summary=term_summary,
        candidate_summary=candidate_summary,
        candidate_rows=candidate_rows,
    )

    summary_payload = {
        "run_id": run_id,
        "paths": {
            "run_dir": str(run_dir),
            "phase_c_assessment": str(run_dir / "normalized" / "phase_c_assessment.json"),
            "phase_d_assessment": str(run_dir / "retrieval" / "phase_d_assessment.json"),
            "query_plan": str(run_dir / "query_plan.json"),
        },
        "phase_c": phase_c_assessment.get("assessment") or {},
        "phase_d": phase_d_assessment.get("assessment") or {},
        "section_type_counts": summarize_counter(section_type_counts),
        "quality_flag_counts": summarize_counter(quality_flag_counts),
        "parser_source_counts": summarize_counter(parser_source_counts),
        "must_term_coverage_summary": term_summary,
        "candidate_summary": candidate_summary,
        "review_flags": flags,
    }

    review_dir = run_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    write_json(review_dir / "review_summary.json", summary_payload)
    write_json(review_dir / "must_term_coverage.json", {"rows": term_rows, "summary": term_summary})
    write_json(
        review_dir / "top_section_candidates.json",
        {"summary": candidate_summary, "rows": candidate_rows[:100]},
    )
    write_json(review_dir / "doc_metrics.json", {"rows": doc_rows})
    write_csv(
        review_dir / "doc_metrics.csv",
        doc_rows,
        [
            "doc_id",
            "section_count",
            "passage_count",
            "penalized_section_count",
            "body_other_count",
            "front_matter_count",
            "reference_count",
            "appendix_count",
            "tiny_section_count",
            "synthetic_section_count",
            "top_candidate_score",
            "top_candidate_title",
            "top5_mean_score",
        ],
    )
    write_csv(
        review_dir / "top_section_candidates.csv",
        candidate_rows[:100],
        [
            "doc_id",
            "section_id",
            "title",
            "section_type",
            "page_start",
            "page_end",
            "score",
            "matched_must_terms",
            "matched_should_terms",
            "matched_subpoints",
            "penalized",
            "quality_flags",
            "parser_sources",
            "preview",
        ],
    )
    report_md = build_report_markdown(
        run_id=run_id,
        phase_c_assessment=phase_c_assessment,
        phase_d_assessment=phase_d_assessment,
        query_plan=query_plan,
        doc_rows=doc_rows,
        term_rows=term_rows,
        candidate_rows=candidate_rows,
        flags=flags,
    )
    (review_dir / "review_report.md").write_text(report_md, encoding="utf-8")

    print("=" * 80)
    print("Run Review Summary")
    print("=" * 80)
    print(f"run_id                   {run_id}")
    print(f"phase_c_status           {summary_payload['phase_c'].get('status')}")
    print(f"phase_d_status           {summary_payload['phase_d'].get('status')}")
    print(f"must_term_hit_ratio      {term_summary['term_hit_ratio']}")
    print(f"top20_penalized_ratio    {candidate_summary['top20_penalized_ratio']}")
    print(f"top20_unique_docs        {candidate_summary['top20_unique_docs']}")
    print(f"review_dir               {review_dir}")
    print("=" * 80)
    print("Top Section Candidates")
    print("=" * 80)
    for row in candidate_rows[:10]:
        print(
            f"{row['score']:>6} | {row['doc_id'][:42]:42} | {row['section_type'][:16]:16} | "
            f"{row['title'][:80]}"
        )
    print("=" * 80)
    print("Review Flags")
    print("=" * 80)
    if flags:
        for flag in flags:
            print(f"- {flag}")
    else:
        print("none")


if __name__ == "__main__":
    main()
