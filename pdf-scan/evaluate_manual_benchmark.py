#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


PDF_SCAN_DIR = Path(__file__).resolve().parent


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    bad_lines = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            bad_lines += 1
            continue
    if bad_lines:
        print(f"[evaluate_manual_benchmark] skipped {bad_lines} malformed JSONL row(s) in {path}")
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (value or "").lower())).strip()


def token_set(value: str) -> set[str]:
    return {token for token in normalize_text(value).split() if token}


def title_similarity(left: str, right: str) -> float:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if left_norm in right_norm or right_norm in left_norm:
        shorter = min(len(left_norm), len(right_norm))
        longer = max(len(left_norm), len(right_norm))
        return max(0.7, shorter / max(1, longer))
    left_tokens = token_set(left_norm)
    right_tokens = token_set(right_norm)
    if not left_tokens or not right_tokens:
        return 0.0
    inter = len(left_tokens & right_tokens)
    if inter == 0:
        return 0.0
    return inter / max(1, len(left_tokens | right_tokens))


def page_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return max(a_start, b_start) <= min(a_end, b_end)


def strong_match(expected: Dict[str, Any], actual_title: str, actual_page_start: int, actual_page_end: int) -> Tuple[bool, float]:
    title_score = title_similarity(expected["section_ref"]["section_title"], actual_title)
    expected_start = int(expected["section_ref"]["page_start"])
    expected_end = int(expected["section_ref"]["page_end"])
    overlap = page_overlap(expected_start, expected_end, int(actual_page_start), int(actual_page_end))
    if title_score >= 0.92:
        return True, title_score
    if overlap and title_score >= 0.58:
        return True, title_score
    if overlap and title_score >= 0.42 and len(token_set(expected["section_ref"]["section_title"])) >= 4:
        return True, title_score
    return False, title_score


def load_suite(suite_manifest: Path) -> Dict[str, Any]:
    suite = read_json(suite_manifest)
    suite_root = suite_manifest.parent.parent
    chapter_path = suite_root / suite["chapter_specs"][0]
    chapter = read_json(chapter_path)
    judgments = []
    for rel_path in suite.get("judgments") or []:
        judgments.append(read_json(suite_root / rel_path))
    manifests = []
    for rel_path in suite.get("documents") or []:
        manifests.append(read_json(suite_root / rel_path))
    return {
        "suite_root": suite_root,
        "suite": suite,
        "chapter": chapter,
        "judgments": judgments,
        "manifests": manifests,
    }


def build_run_view(run_dir: Path) -> Dict[str, Any]:
    final_output = read_json(run_dir / "final" / "output.json")
    final_docs = {row["doc_id"]: row for row in final_output.get("documents") or []}
    sections = read_jsonl(run_dir / "normalized" / "sections.jsonl")
    sections_by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in sections:
        sections_by_doc[str(row.get("doc_id") or "")].append(row)

    fused = read_jsonl(run_dir / "retrieval" / "fused_candidates.jsonl")
    fused_by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in fused:
        fused_by_doc[str(row.get("doc_id") or "")].append(row)
    for rows in fused_by_doc.values():
        rows.sort(key=lambda row: (int(row.get("fused_rank") or 10000), -float(row.get("fused_score") or 0.0)))

    rerank = read_jsonl(run_dir / "rerank" / "rerank_results.jsonl")
    rerank_by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rerank:
        rerank_by_doc[str(row.get("doc_id") or "")].append(row)
    for rows in rerank_by_doc.values():
        rows.sort(key=lambda row: int(row.get("rerank_rank") or 10000))

    return {
        "run_dir": run_dir,
        "final_docs": final_docs,
        "sections_by_doc": sections_by_doc,
        "fused_by_doc": fused_by_doc,
        "rerank_by_doc": rerank_by_doc,
    }


def find_matches(expected: Dict[str, Any], rows: Iterable[Dict[str, Any]], *, title_key: str = "title") -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    for row in rows:
        ok, score = strong_match(
            expected,
            str(row.get(title_key) or ""),
            int(row.get("page_start") or 0),
            int(row.get("page_end") or 0),
        )
        if ok:
            matches.append(
                {
                    "title": row.get(title_key),
                    "page_start": row.get("page_start"),
                    "page_end": row.get("page_end"),
                    "score": round(score, 4),
                }
            )
    matches.sort(key=lambda item: (-float(item["score"]), int(item["page_start"] or 0)))
    return matches


def evaluate_judgment(
    judgment: Dict[str, Any],
    run_view: Dict[str, Any],
    *,
    phase_e_doc_topk: int,
    phase_f_doc_topk: int,
    phase_g_topk: int,
) -> Dict[str, Any]:
    doc_id = judgment["doc_id"]
    final_doc = run_view["final_docs"].get(doc_id, {})
    actual_useful = bool(final_doc.get("has_useful_information"))
    expected_useful = bool(judgment.get("has_useful_information"))

    sections = run_view["sections_by_doc"].get(doc_id, [])
    fused_rows = run_view["fused_by_doc"].get(doc_id, [])
    rerank_rows = run_view["rerank_by_doc"].get(doc_id, [])
    final_top_sections = list(final_doc.get("top_sections") or [])[:phase_g_topk]

    anchor_rows = []
    for expected in judgment.get("section_judgments") or []:
        structure_matches = find_matches(expected, sections)
        e_matches = find_matches(expected, fused_rows[:phase_e_doc_topk])
        f_matches = find_matches(expected, rerank_rows[:phase_f_doc_topk])
        g_matches = find_matches(expected, final_top_sections)
        anchor_rows.append(
            {
                "expected_section_title": expected["section_ref"]["section_title"],
                "expected_pages": f"{expected['section_ref']['page_start']}-{expected['section_ref']['page_end']}",
                "supported_subpoints": expected.get("supported_subpoints") or [],
                "label_0_to_3": expected.get("label_0_to_3"),
                "structure_present": bool(structure_matches),
                "phase_e_hit_at_doc_topk": bool(e_matches),
                "phase_f_hit_at_doc_topk": bool(f_matches),
                "phase_g_hit_at_doc_topk": bool(g_matches),
                "best_structure_match": structure_matches[0] if structure_matches else None,
                "best_phase_e_match": e_matches[0] if e_matches else None,
                "best_phase_f_match": f_matches[0] if f_matches else None,
                "best_phase_g_match": g_matches[0] if g_matches else None,
            }
        )

    if expected_useful and actual_useful:
        doc_verdict = "true_positive"
    elif expected_useful and not actual_useful:
        doc_verdict = "false_negative"
    elif not expected_useful and actual_useful:
        doc_verdict = "false_positive"
    else:
        doc_verdict = "true_negative"

    return {
        "doc_id": doc_id,
        "expected_has_useful_information": expected_useful,
        "actual_has_useful_information": actual_useful,
        "doc_verdict": doc_verdict,
        "actual_doc_match_probability": final_doc.get("doc_match_probability"),
        "actual_top_section_title": final_doc.get("top_section_title"),
        "actual_top_section_score": final_doc.get("top_section_score"),
        "actual_abstention_reason": final_doc.get("abstention_reason"),
        "section_anchor_rows": anchor_rows,
        "document_notes": judgment.get("document_notes"),
    }


def build_summary(rows: List[Dict[str, Any]], *, phase_e_doc_topk: int, phase_f_doc_topk: int, phase_g_topk: int) -> Dict[str, Any]:
    positive_rows = [row for row in rows if row["expected_has_useful_information"]]
    negative_rows = [row for row in rows if not row["expected_has_useful_information"]]
    true_positive = sum(1 for row in positive_rows if row["doc_verdict"] == "true_positive")
    false_negative = sum(1 for row in positive_rows if row["doc_verdict"] == "false_negative")
    false_positive = sum(1 for row in negative_rows if row["doc_verdict"] == "false_positive")
    true_negative = sum(1 for row in negative_rows if row["doc_verdict"] == "true_negative")

    all_anchors = [anchor for row in rows for anchor in row["section_anchor_rows"]]
    structure_hits = sum(1 for row in all_anchors if row["structure_present"])
    e_hits = sum(1 for row in all_anchors if row["phase_e_hit_at_doc_topk"])
    f_hits = sum(1 for row in all_anchors if row["phase_f_hit_at_doc_topk"])
    g_hits = sum(1 for row in all_anchors if row["phase_g_hit_at_doc_topk"])

    false_negative_docs = [
        {
            "doc_id": row["doc_id"],
            "actual_top_section_title": row["actual_top_section_title"],
            "actual_top_section_score": row["actual_top_section_score"],
            "actual_abstention_reason": row["actual_abstention_reason"],
        }
        for row in rows
        if row["doc_verdict"] == "false_negative"
    ]

    missed_anchor_docs = defaultdict(list)
    for row in rows:
        for anchor in row["section_anchor_rows"]:
            if not anchor["phase_f_hit_at_doc_topk"]:
                missed_anchor_docs[row["doc_id"]].append(anchor["expected_section_title"])

    return {
        "document_metrics": {
            "judged_doc_count": len(rows),
            "positive_doc_count": len(positive_rows),
            "negative_doc_count": len(negative_rows),
            "true_positive": true_positive,
            "false_negative": false_negative,
            "true_negative": true_negative,
            "false_positive": false_positive,
            "doc_recall": round(true_positive / max(1, len(positive_rows)), 4),
            "doc_precision": round(true_positive / max(1, true_positive + false_positive), 4),
        },
        "section_anchor_metrics": {
            "anchor_count": len(all_anchors),
            "structure_presence_recall": round(structure_hits / max(1, len(all_anchors)), 4),
            f"phase_e_hit_at_doc_top{phase_e_doc_topk}": round(e_hits / max(1, len(all_anchors)), 4),
            f"phase_f_hit_at_doc_top{phase_f_doc_topk}": round(f_hits / max(1, len(all_anchors)), 4),
            f"phase_g_hit_at_doc_top{phase_g_topk}": round(g_hits / max(1, len(all_anchors)), 4),
        },
        "false_negative_docs": false_negative_docs,
        "docs_with_missed_anchors": {doc_id: titles for doc_id, titles in missed_anchor_docs.items()},
        "doc_verdict_distribution": dict(Counter(row["doc_verdict"] for row in rows)),
    }


def write_markdown(path: Path, suite_id: str, run_id: str, summary: Dict[str, Any], rows: List[Dict[str, Any]]) -> None:
    lines: List[str] = []
    lines.append("# Manual Benchmark Evaluation")
    lines.append("")
    lines.append(f"- Suite: `{suite_id}`")
    lines.append(f"- Run ID: `{run_id}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for key, value in summary["document_metrics"].items():
        lines.append(f"- {key}: `{value}`")
    for key, value in summary["section_anchor_metrics"].items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    lines.append("## False Negative Docs")
    lines.append("")
    for row in summary["false_negative_docs"]:
        lines.append(
            f"- `{row['doc_id']}`: top=`{row['actual_top_section_title']}`, "
            f"score=`{row['actual_top_section_score']}`, abstention=`{row['actual_abstention_reason']}`"
        )
    lines.append("")
    lines.append("## Per-Document Detail")
    lines.append("")
    for row in rows:
        lines.append(f"### {row['doc_id']} | {row['doc_verdict']}")
        lines.append("")
        lines.append(f"- expected_has_useful_information: `{row['expected_has_useful_information']}`")
        lines.append(f"- actual_has_useful_information: `{row['actual_has_useful_information']}`")
        lines.append(f"- actual_top_section_title: `{row['actual_top_section_title']}`")
        lines.append(f"- actual_top_section_score: `{row['actual_top_section_score']}`")
        lines.append(f"- actual_abstention_reason: `{row['actual_abstention_reason']}`")
        if row["document_notes"]:
            lines.append(f"- notes: {row['document_notes']}")
        for anchor in row["section_anchor_rows"]:
            lines.append(
                f"- anchor `{anchor['expected_section_title']}` ({anchor['expected_pages']}): "
                f"structure={anchor['structure_present']}, e={anchor['phase_e_hit_at_doc_topk']}, "
                f"f={anchor['phase_f_hit_at_doc_topk']}, g={anchor['phase_g_hit_at_doc_topk']}"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a run against the manual full-dump benchmark.")
    parser.add_argument("--suite-manifest", default="benchmark/full_dump_webshop_manual_v1/manifests/suite_manifest.json")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--phase-e-doc-topk", type=int, default=10)
    parser.add_argument("--phase-f-doc-topk", type=int, default=10)
    parser.add_argument("--phase-g-topk", type=int, default=5)
    args = parser.parse_args()

    suite_manifest = (PDF_SCAN_DIR / args.suite_manifest).resolve() if not Path(args.suite_manifest).is_absolute() else Path(args.suite_manifest).resolve()
    run_dir = (PDF_SCAN_DIR / "runs" / args.run_id).resolve()

    suite_view = load_suite(suite_manifest)
    run_view = build_run_view(run_dir)
    rows = [
        evaluate_judgment(
            judgment,
            run_view,
            phase_e_doc_topk=args.phase_e_doc_topk,
            phase_f_doc_topk=args.phase_f_doc_topk,
            phase_g_topk=args.phase_g_topk,
        )
        for judgment in suite_view["judgments"]
    ]
    rows.sort(key=lambda row: (row["doc_verdict"], row["doc_id"]))
    summary = build_summary(
        rows,
        phase_e_doc_topk=args.phase_e_doc_topk,
        phase_f_doc_topk=args.phase_f_doc_topk,
        phase_g_topk=args.phase_g_topk,
    )

    out_dir = run_dir / "manual_benchmark_eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        out_dir / "manual_benchmark_summary.json",
        {
            "suite_id": suite_view["suite"]["suite_id"],
            "run_id": args.run_id,
            **summary,
        },
    )
    write_json(out_dir / "manual_benchmark_rows.json", {"rows": rows})
    write_markdown(out_dir / "manual_benchmark_report.md", suite_view["suite"]["suite_id"], args.run_id, summary, rows)

    print(json.dumps({"suite_id": suite_view["suite"]["suite_id"], "run_id": args.run_id, **summary}, ensure_ascii=False, indent=2))
    print(f"\nWrote manual benchmark evaluation to {out_dir}")


if __name__ == "__main__":
    main()
