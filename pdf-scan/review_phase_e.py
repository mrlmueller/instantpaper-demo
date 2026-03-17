import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


GENERIC_TITLES = {
    "introduction",
    "conclusion",
    "research design",
    "discussion",
    "results",
    "method",
    "methods",
    "abstract",
}


CONCEPT_PATTERNS = {
    "heuristics_biases": [
        r"\bheuristic",
        r"\bbias",
        r"\bavailability\b",
        r"\banchoring\b",
        r"\bdebias",
        r"\bframing\b",
    ],
    "dual_process": [
        r"dual[\s-]?process",
        r"\bsystem\s*1\b",
        r"\bsystem\s*2\b",
        r"\bfast and slow\b",
    ],
    "decision_confidence": [
        r"decision confidence",
        r"entscheidungssicherheit",
        r"\bconfidence\b",
        r"\bcertainty\b",
        r"\bdeliberation\b",
    ],
    "risk_trust_uncertainty": [
        r"perceived risk",
        r"\brisk\b",
        r"\btrust\b",
        r"uncertaint",
        r"unsicher",
    ],
    "nudging_choice_architecture": [
        r"\bnudg",
        r"choice architecture",
        r"\bdefault\b",
        r"choice set",
    ],
    "ethics_transparency_autonomy": [
        r"transparen",
        r"autonom",
        r"\bethic",
        r"consent",
        r"manipulat",
        r"dark pattern",
    ],
    "uncertainty_reduction_interventions": [
        r"information",
        r"compar",
        r"explain",
        r"quality signal",
        r"\breview",
        r"certificate",
        r"recommend",
        r"\brating",
        r"spec",
    ],
    "ecommerce_context": [
        r"webshop",
        r"e-?commerce",
        r"online purch",
        r"online shopping",
        r"social commerce",
        r"recommender",
        r"consumer",
    ],
    "complex_products": [
        r"consumer electronics",
        r"complex product",
        r"product heterogeneity",
        r"product category",
    ],
}


SUBPOINT_CONCEPTS = {
    "SP1": ["heuristics_biases", "decision_confidence", "ecommerce_context"],
    "SP2": ["dual_process", "decision_confidence", "heuristics_biases"],
    "SP3": ["nudging_choice_architecture", "ecommerce_context"],
    "SP4": ["nudging_choice_architecture", "ethics_transparency_autonomy"],
    "SP5": ["risk_trust_uncertainty", "ecommerce_context", "complex_products"],
    "SP6": ["uncertainty_reduction_interventions", "risk_trust_uncertainty", "ecommerce_context"],
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_run(base_dir: Path, run_id: str):
    run_dir = base_dir / "runs" / run_id
    data = {
        "run_dir": run_dir,
        "retrieval_dir": run_dir / "retrieval",
        "normalized_dir": run_dir / "normalized",
        "query_plan": read_json(run_dir / "query_plan.json"),
        "phase_e_summary": read_json(run_dir / "retrieval" / "phase_e_summary.json"),
        "phase_e_assessment": read_json(run_dir / "retrieval" / "phase_e_assessment.json"),
        "sections": read_jsonl(run_dir / "normalized" / "sections.jsonl"),
        "passages": read_jsonl(run_dir / "normalized" / "passages.jsonl"),
        "fused_candidates": read_jsonl(run_dir / "retrieval" / "fused_candidates.jsonl"),
    }
    lanes_dir = run_dir / "retrieval" / "lanes"
    data["lanes"] = {
        "section_title_lexical": read_jsonl(lanes_dir / "section_title_lexical.jsonl"),
        "section_body_lexical": read_jsonl(lanes_dir / "section_body_lexical.jsonl"),
        "section_dense": read_jsonl(lanes_dir / "section_dense.jsonl"),
        "passage_lexical": read_jsonl(lanes_dir / "passage_lexical.jsonl"),
        "passage_dense": read_jsonl(lanes_dir / "passage_dense.jsonl"),
    }
    return data


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def match_concepts(text: str):
    low = normalize_text(text)
    hits = {}
    for concept, patterns in CONCEPT_PATTERNS.items():
        matched = []
        for pattern in patterns:
            m = re.search(pattern, low)
            if m:
                matched.append(m.group(0))
        if matched:
            hits[concept] = sorted(set(matched))
    return hits


def snippet(text: str, limit: int = 700) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()[:limit]


def is_generic_title(title: str) -> bool:
    low = normalize_text(title)
    return low in GENERIC_TITLES or bool(re.fullmatch(r"\d+\.?\s+(introduction|discussion|conclusion|results|methods?)", low))


def candidate_review_row(candidate, section_by_id, passage_by_id):
    section = section_by_id[candidate["section_id"]]
    text = f"{section.get('title', '')}\n{section.get('text', '')}"
    concept_hits = match_concepts(text)
    supporting = []
    for item in candidate.get("supporting_passages", [])[:3]:
        passage = passage_by_id.get(item["passage_id"])
        if not passage:
            continue
        supporting.append(
            {
                "passage_id": item["passage_id"],
                "page_start": passage["page_span"]["page_start"],
                "page_end": passage["page_span"]["page_end"],
                "lanes": item.get("lanes", []),
                "text_snippet": snippet(passage.get("text", ""), 360),
                "concept_hits": match_concepts(passage.get("text", "")),
            }
        )

    subpoint_scores = {}
    for subpoint_id, required_concepts in SUBPOINT_CONCEPTS.items():
        subpoint_scores[subpoint_id] = sum(1 for name in required_concepts if name in concept_hits)

    max_subpoint_id = max(subpoint_scores, key=subpoint_scores.get)
    max_subpoint_score = subpoint_scores[max_subpoint_id]
    core_concepts = {
        name
        for name in concept_hits
        if name not in {"ecommerce_context", "uncertainty_reduction_interventions", "complex_products"}
    }

    verdict = "weak"
    if max_subpoint_score >= 2 and len(core_concepts) >= 1:
        verdict = "strong"
    elif max_subpoint_score >= 1 or len(core_concepts) >= 1:
        verdict = "partial"

    if is_generic_title(section.get("title", "")) and verdict == "strong":
        verdict = "partial"
    if is_generic_title(section.get("title", "")) and max_subpoint_score == 0:
        verdict = "weak"

    return {
        "doc_id": candidate["doc_id"],
        "section_id": candidate["section_id"],
        "title": candidate["title"],
        "section_type": candidate["section_type"],
        "page_start": candidate["page_start"],
        "page_end": candidate["page_end"],
        "fused_rank": candidate.get("fused_rank"),
        "fused_score": candidate.get("fused_score"),
        "lane_count": candidate.get("lane_count"),
        "best_views_by_lane": candidate.get("best_views_by_lane", {}),
        "component_lane_ranks": candidate.get("component_lane_ranks", {}),
        "concept_hits": concept_hits,
        "subpoint_scores": subpoint_scores,
        "best_subpoint": {"subpoint_id": max_subpoint_id, "score": max_subpoint_score},
        "generic_title": is_generic_title(section.get("title", "")),
        "title_path": section.get("title_path", []),
        "section_text_snippet": snippet(section.get("text", "")),
        "supporting_passages": supporting,
        "verdict": verdict,
    }


def compute_dense_value(fused_candidates):
    only_dense = 0
    dense_helped = 0
    dense_top10 = 0
    for row in fused_candidates:
        has_dense = any(k.endswith("dense") and v is not None for k, v in row.get("component_lane_ranks", {}).items())
        has_lexical = any("lexical" in k and v is not None for k, v in row.get("component_lane_ranks", {}).items())
        if has_dense:
            dense_helped += 1
        if has_dense and not has_lexical:
            only_dense += 1
        if row.get("fused_rank", 10_000) <= 10 and has_dense:
            dense_top10 += 1
    return {
        "candidates_with_dense_support": dense_helped,
        "dense_only_candidates": only_dense,
        "top10_with_dense_support": dense_top10,
    }


def lane_overlap(lane_rows):
    ids = {name: {row["section_id"] for row in rows} for name, rows in lane_rows.items()}
    overlap = {}
    for left, left_ids in ids.items():
        overlap[left] = {}
        for right, right_ids in ids.items():
            union = len(left_ids | right_ids) or 1
            overlap[left][right] = round(len(left_ids & right_ids) / union, 4)
    return overlap


def summarize_top_distribution(rows, top_k):
    top = rows[:top_k]
    doc_counts = Counter(row["doc_id"] for row in top)
    section_type_counts = Counter(row["section_type"] for row in top)
    verdict_counts = Counter(row["verdict"] for row in top)
    best_subpoints = Counter(row["best_subpoint"]["subpoint_id"] for row in top)
    return {
        "top_k": top_k,
        "doc_counts": doc_counts,
        "section_type_counts": section_type_counts,
        "verdict_counts": verdict_counts,
        "best_subpoints": best_subpoints,
        "generic_title_count": sum(1 for row in top if row["generic_title"]),
    }


def candidate_focus_metrics(rows, top_k):
    top = rows[:top_k]
    concept_counts = Counter()
    for row in top:
        concept_counts.update(row["concept_hits"].keys())
    return {
        "top_k": top_k,
        "concept_counts": concept_counts,
        "average_lane_count": round(sum(row["lane_count"] or 0 for row in top) / max(len(top), 1), 3),
        "average_subpoint_score": round(
            sum(row["best_subpoint"]["score"] for row in top) / max(len(top), 1), 3
        ),
    }


def subpoint_probe_summary(fused_candidates):
    probes = {}
    for subpoint_id in SUBPOINT_CONCEPTS:
        matches = []
        for row in fused_candidates:
            lane_views = set((row.get("best_views_by_lane") or {}).values())
            if f"subpoint::{subpoint_id}" in lane_views:
                matches.append(
                    {
                        "fused_rank": row.get("fused_rank"),
                        "title": row.get("title"),
                        "doc_id": row.get("doc_id"),
                        "section_type": row.get("section_type"),
                        "fused_score": row.get("fused_score"),
                    }
                )
        probes[subpoint_id] = matches[:5]
    return probes


def to_plain(obj):
    if isinstance(obj, Counter):
        return dict(obj)
    if isinstance(obj, defaultdict):
        return dict(obj)
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_plain(v) for v in obj]
    return obj


def write_report(out_dir: Path, summary: dict, top_rows: list):
    lines = []
    lines.append("# Phase E Review")
    lines.append("")
    lines.append(f"- Run ID: `{summary['run_id']}`")
    lines.append(f"- Status: `{summary['phase_e_status']}`")
    lines.append(f"- Dense mode: `{summary['dense_mode']}`")
    lines.append(f"- Embedding cost USD: `{summary['embedding_cost_usd']}`")
    lines.append(f"- Fused candidates: `{summary['fused_candidate_count']}`")
    lines.append("")
    lines.append("## Headline Metrics")
    lines.append("")
    lines.append(f"- Top 10 verdicts: `{summary['top10_distribution']['verdict_counts']}`")
    lines.append(f"- Top 20 verdicts: `{summary['top20_distribution']['verdict_counts']}`")
    lines.append(f"- Top 20 document spread: `{summary['top20_distribution']['doc_counts']}`")
    lines.append(f"- Top 20 section types: `{summary['top20_distribution']['section_type_counts']}`")
    lines.append(f"- Top 20 best-subpoint focus: `{summary['top20_distribution']['best_subpoints']}`")
    lines.append(f"- Top 20 generic titles: `{summary['top20_distribution']['generic_title_count']}`")
    lines.append("")
    lines.append("## Dense Value")
    lines.append("")
    lines.append(f"- Dense support: `{summary['dense_value']}`")
    lines.append("")
    lines.append("## Top Candidate Audit")
    lines.append("")
    for row in top_rows:
        lines.append(
            f"### Rank {row['fused_rank']} | {row['title']} | {row['verdict']}"
        )
        lines.append("")
        lines.append(f"- Doc: `{row['doc_id']}`")
        lines.append(f"- Section type: `{row['section_type']}`")
        lines.append(f"- Pages: `{row['page_start']}-{row['page_end']}`")
        lines.append(f"- Fused score: `{row['fused_score']}`")
        lines.append(f"- Lane count: `{row['lane_count']}`")
        lines.append(f"- Best subpoint: `{row['best_subpoint']}`")
        lines.append(f"- Concept hits: `{list(row['concept_hits'].keys())}`")
        lines.append(f"- Generic title: `{row['generic_title']}`")
        lines.append(f"- Best views by lane: `{row['best_views_by_lane']}`")
        lines.append("")
        lines.append(row["section_text_snippet"])
        lines.append("")
        for idx, passage in enumerate(row["supporting_passages"], 1):
            lines.append(
                f"- Support {idx}: pages {passage['page_start']}-{passage['page_end']} | lanes={passage['lanes']} | concepts={list(passage['concept_hits'].keys())}"
            )
            lines.append(f"  {passage['text_snippet']}")
        lines.append("")
    (out_dir / "phase_e_review_report.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--top-k", type=int, default=20)
    args = parser.parse_args()

    data = load_run(args.base_dir, args.run_id)
    out_dir = data["run_dir"] / "phase_e_review"
    out_dir.mkdir(parents=True, exist_ok=True)

    section_by_id = {row["section_id"]: row for row in data["sections"]}
    passage_by_id = {row["passage_id"]: row for row in data["passages"]}
    fused_candidates = sorted(
        data["fused_candidates"], key=lambda row: (row.get("fused_rank") or 10_000, -row.get("fused_score", 0.0))
    )

    reviewed = [candidate_review_row(row, section_by_id, passage_by_id) for row in fused_candidates]

    summary = {
        "run_id": args.run_id,
        "phase_e_status": data["phase_e_assessment"]["assessment"]["status"],
        "dense_mode": data["phase_e_summary"]["dense_trace"].get("dense_mode"),
        "embedding_cost_usd": data["phase_e_summary"]["dense_trace"].get("cost", {}).get("estimated_cost_usd"),
        "embedding_input_tokens": data["phase_e_summary"]["dense_trace"].get("usage", {}).get("input_tokens"),
        "fused_candidate_count": data["phase_e_summary"]["fused_candidate_count"],
        "top10_distribution": summarize_top_distribution(reviewed, 10),
        "top20_distribution": summarize_top_distribution(reviewed, 20),
        "focus_top10": candidate_focus_metrics(reviewed, 10),
        "focus_top20": candidate_focus_metrics(reviewed, 20),
        "dense_value": compute_dense_value(fused_candidates),
        "lane_overlap": lane_overlap(data["lanes"]),
        "subpoint_probes": subpoint_probe_summary(fused_candidates),
        "warnings": [],
    }

    if summary["top20_distribution"]["verdict_counts"].get("weak", 0) >= 4:
        summary["warnings"].append("Top-20 contains too many weak candidates.")
    if summary["top20_distribution"]["generic_title_count"] >= 3:
        summary["warnings"].append("Top-20 still contains several generic section titles.")
    if summary["top20_distribution"]["best_subpoints"].get("SP3", 0) == 0:
        summary["warnings"].append("No top-20 candidates align to SP3 (choice architecture / digital nudging).")
    if summary["top20_distribution"]["best_subpoints"].get("SP4", 0) == 0:
        summary["warnings"].append("No top-20 candidates align to SP4 (ethics / autonomy / transparency).")

    (out_dir / "phase_e_review_summary.json").write_text(
        json.dumps(to_plain(summary), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out_dir / "phase_e_top_candidates.json").write_text(
        json.dumps(to_plain(reviewed[: args.top_k]), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_report(out_dir, to_plain(summary), to_plain(reviewed[: args.top_k]))

    print(json.dumps(to_plain(summary), indent=2, ensure_ascii=False))
    print(f"\nWrote review artifacts to {out_dir}")


if __name__ == "__main__":
    main()
