#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


GENERIC_TITLES = {
    "introduction",
    "conclusion",
    "discussion",
    "results",
    "research design",
    "methods",
    "method",
    "abstract",
    "background",
}


SUBPOINT_PATTERNS: Dict[str, Dict[str, List[str]]] = {
    "SP1": {
        "label": "Heuristics / biases / decision confidence",
        "patterns": [
            r"\bheuristic",
            r"\bbias",
            r"\bavailability\b",
            r"\banchoring\b",
            r"\bdebias",
            r"judgment under uncertainty",
            r"decision confidence",
            r"entscheidungssicherheit",
            r"\boverconfidence\b",
        ],
    },
    "SP2": {
        "label": "Dual-process models and cognitive mechanisms",
        "patterns": [
            r"dual[\s-]?process",
            r"\bsystem\s*1\b",
            r"\bsystem\s*2\b",
            r"fast and slow",
            r"deliberation",
            r"automatic processing",
        ],
    },
    "SP3": {
        "label": "Choice architecture / digital nudging",
        "patterns": [
            r"choice architecture",
            r"\bnudg",
            r"default option",
            r"default effect",
            r"choice set",
            r"choice environment",
            r"nudging",
        ],
    },
    "SP4": {
        "label": "Transparency / autonomy / ethics / manipulation",
        "patterns": [
            r"transparen",
            r"autonom",
            r"\bethical\b",
            r"\bethics\b",
            r"informed consent",
            r"manipulative pattern",
            r"manipulative design",
            r"dark pattern",
            r"user autonomy",
        ],
    },
    "SP5": {
        "label": "Perceived risk / uncertainty / trust / complex products",
        "patterns": [
            r"perceived risk",
            r"\brisk\b",
            r"\btrust\b",
            r"uncertaint",
            r"unsicher",
            r"consumer electronics",
            r"complex product",
            r"purchase intention",
        ],
    },
    "SP6": {
        "label": "Uncertainty reduction interventions / signals / comparisons",
        "patterns": [
            r"information",
            r"compar",
            r"explain",
            r"quality signal",
            r"\breview",
            r"\brating",
            r"certificate",
            r"recommender",
            r"signal",
        ],
    },
}


PENALIZED_SECTION_TYPES = {
    "front_matter",
    "table_of_contents",
    "references",
    "appendix",
    "index",
    "acknowledgements",
}


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


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def is_generic_title(title: str) -> bool:
    low = normalize_text(title)
    if low in GENERIC_TITLES:
        return True
    return bool(re.fullmatch(r"\d+\.?\s+(introduction|discussion|conclusion|results|methods?)", low))


def match_subpoints(text: str) -> Dict[str, List[str]]:
    low = normalize_text(text)
    hits: Dict[str, List[str]] = {}
    for subpoint_id, spec in SUBPOINT_PATTERNS.items():
        matched = []
        for pattern in spec["patterns"]:
            found = re.search(pattern, low)
            if found:
                matched.append(found.group(0))
        if matched:
            hits[subpoint_id] = sorted(set(matched))
    return hits


def load_run(base_dir: Path, run_id: str) -> Dict[str, Any]:
    run_dir = base_dir / "runs" / run_id
    retrieval_dir = run_dir / "retrieval"
    normalized_dir = run_dir / "normalized"
    return {
        "run_dir": run_dir,
        "query_plan": read_json(run_dir / "query_plan.json"),
        "phase_e_summary": read_json(retrieval_dir / "phase_e_summary.json"),
        "phase_e_assessment": read_json(retrieval_dir / "phase_e_assessment.json"),
        "fused_candidates": read_jsonl(retrieval_dir / "fused_candidates.jsonl"),
        "sections": read_jsonl(normalized_dir / "sections.jsonl"),
        "passages": read_jsonl(normalized_dir / "passages.jsonl"),
        "lane_rows": {
            "section_title_lexical": read_jsonl(retrieval_dir / "lanes" / "section_title_lexical.jsonl"),
            "section_body_lexical": read_jsonl(retrieval_dir / "lanes" / "section_body_lexical.jsonl"),
            "section_dense": read_jsonl(retrieval_dir / "lanes" / "section_dense.jsonl"),
            "passage_lexical": read_jsonl(retrieval_dir / "lanes" / "passage_lexical.jsonl"),
            "passage_dense": read_jsonl(retrieval_dir / "lanes" / "passage_dense.jsonl"),
        },
    }


def build_candidate_view_map(lane_rows: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Dict[str, float]]]:
    per_section: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for lane_name, rows in lane_rows.items():
        for row in rows:
            section_id = str(row.get("section_id") or "")
            if not section_id:
                continue
            for vm in row.get("view_matches", []):
                view_id = str(vm.get("view_id") or "")
                if not view_id:
                    continue
                current = per_section[section_id][lane_name].get(view_id, float("-inf"))
                score = float(vm.get("score") or 0.0)
                if score > current:
                    per_section[section_id][lane_name][view_id] = score
    return per_section


def summarize_corpus_support(sections: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    by_subpoint: Dict[str, Dict[str, Any]] = {}
    for subpoint_id, spec in SUBPOINT_PATTERNS.items():
        raw_sections = []
        trusted_sections = []
        for row in sections:
            text = f"{row.get('title', '')}\n{row.get('text', '')}"
            hits = match_subpoints(text).get(subpoint_id, [])
            if hits:
                entry = {
                    "doc_id": row.get("doc_id"),
                    "section_id": row.get("section_id"),
                    "title": row.get("title"),
                    "section_type": row.get("section_type"),
                    "page_start": row.get("page_start"),
                    "page_end": row.get("page_end"),
                    "match_count": len(hits),
                    "matched_terms": hits,
                    "generic_title": is_generic_title(str(row.get("title") or "")),
                }
                raw_sections.append(entry)
                trusted_threshold = 2 if subpoint_id in {"SP2", "SP3", "SP4"} else 1
                if str(row.get("section_type") or "") not in PENALIZED_SECTION_TYPES and len(hits) >= trusted_threshold:
                    trusted_sections.append(entry)
        raw_sections.sort(key=lambda item: (-item["match_count"], str(item["title"])))
        trusted_sections.sort(key=lambda item: (-item["match_count"], str(item["title"])))
        raw_docs = sorted({row["doc_id"] for row in raw_sections})
        trusted_docs = sorted({row["doc_id"] for row in trusted_sections})
        by_subpoint[subpoint_id] = {
            "subpoint_id": subpoint_id,
            "label": spec["label"],
            "raw_matching_section_count": len(raw_sections),
            "raw_matching_doc_count": len(raw_docs),
            "raw_matching_doc_ids": raw_docs,
            "trusted_matching_section_count": len(trusted_sections),
            "trusted_matching_doc_count": len(trusted_docs),
            "trusted_matching_doc_ids": trusted_docs,
            "top_raw_sections": raw_sections[:10],
            "top_trusted_sections": trusted_sections[:10],
        }
        rows.append(
            {
                "subpoint_id": subpoint_id,
                "label": spec["label"],
                "raw_matching_section_count": len(raw_sections),
                "raw_matching_doc_count": len(raw_docs),
                "trusted_matching_section_count": len(trusted_sections),
                "trusted_matching_doc_count": len(trusted_docs),
            }
        )
    return {"rows": rows, "by_subpoint": by_subpoint}


def analyze_top_candidates(
    fused_candidates: List[Dict[str, Any]],
    section_by_id: Dict[str, Dict[str, Any]],
    candidate_view_map: Dict[str, Dict[str, Dict[str, float]]],
    top_k: int = 20,
) -> Dict[str, Any]:
    top = sorted(
        fused_candidates,
        key=lambda row: (int(row.get("fused_rank") or 10_000), -float(row.get("fused_score") or 0.0)),
    )[:top_k]
    detailed = []
    dominant_subpoints = Counter()
    generic_count = 0
    generic_high_evidence = 0
    dense_only = []

    for row in top:
        section = section_by_id[row["section_id"]]
        text = f"{section.get('title', '')}\n{section.get('text', '')}"
        hit_map = match_subpoints(text)
        subpoint_support: Dict[str, float] = defaultdict(float)
        for lane_name, view_scores in candidate_view_map.get(row["section_id"], {}).items():
            for view_id, score in view_scores.items():
                if view_id.startswith("subpoint::"):
                    subpoint_id = view_id.split("::", 1)[1]
                    subpoint_support[subpoint_id] = max(subpoint_support[subpoint_id], score)
        for subpoint_id, hits in hit_map.items():
            subpoint_support[subpoint_id] = max(subpoint_support[subpoint_id], float(len(hits)))

        best_subpoint = None
        best_score = -1.0
        if subpoint_support:
            best_subpoint, best_score = max(subpoint_support.items(), key=lambda item: item[1])
            dominant_subpoints[best_subpoint] += 1

        generic = is_generic_title(str(section.get("title") or ""))
        if generic:
            generic_count += 1
            if len(hit_map) >= 2 or sum(len(v) for v in hit_map.values()) >= 3:
                generic_high_evidence += 1

        lane_ranks = row.get("component_lane_ranks", {}) or {}
        has_dense = any(name.endswith("dense") and value is not None for name, value in lane_ranks.items())
        has_lexical = any("lexical" in name and value is not None for name, value in lane_ranks.items())
        if has_dense and not has_lexical:
            dense_only.append(
                {
                    "fused_rank": row.get("fused_rank"),
                    "title": row.get("title"),
                    "doc_id": row.get("doc_id"),
                    "section_type": row.get("section_type"),
                    "fused_score": row.get("fused_score"),
                    "matched_subpoints": sorted(hit_map.keys()),
                }
            )

        detailed.append(
            {
                "fused_rank": row.get("fused_rank"),
                "title": row.get("title"),
                "doc_id": row.get("doc_id"),
                "section_type": row.get("section_type"),
                "generic_title": generic,
                "fused_score": row.get("fused_score"),
                "matched_subpoints": {k: v for k, v in sorted(hit_map.items())},
                "best_subpoint": best_subpoint,
                "best_subpoint_score": best_score if best_subpoint is not None else None,
                "best_views_by_lane": row.get("best_views_by_lane", {}),
            }
        )

    return {
        "top_k": top_k,
        "dominant_subpoints": dict(dominant_subpoints),
        "generic_title_count": generic_count,
        "generic_high_evidence_count": generic_high_evidence,
        "generic_low_evidence_count": generic_count - generic_high_evidence,
        "dense_only_top_candidates": dense_only,
        "rows": detailed,
    }


def analyze_generic_sections(sections: List[Dict[str, Any]]) -> Dict[str, Any]:
    generic_sections = []
    non_generic_sections = []
    for row in sections:
        text = f"{row.get('title', '')}\n{row.get('text', '')}"
        hit_map = match_subpoints(text)
        entry = {
            "doc_id": row.get("doc_id"),
            "section_id": row.get("section_id"),
            "title": row.get("title"),
            "section_type": row.get("section_type"),
            "page_start": row.get("page_start"),
            "page_end": row.get("page_end"),
            "matched_subpoint_count": len(hit_map),
            "match_term_count": sum(len(v) for v in hit_map.values()),
        }
        if is_generic_title(str(row.get("title") or "")):
            generic_sections.append(entry)
        else:
            non_generic_sections.append(entry)

    def summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        term_counts = [row["match_term_count"] for row in rows]
        subpoint_counts = [row["matched_subpoint_count"] for row in rows]
        return {
            "count": len(rows),
            "avg_match_term_count": round(statistics.mean(term_counts), 3) if term_counts else 0.0,
            "avg_matched_subpoint_count": round(statistics.mean(subpoint_counts), 3) if subpoint_counts else 0.0,
            "high_evidence_count": sum(1 for row in rows if row["match_term_count"] >= 3 or row["matched_subpoint_count"] >= 2),
        }

    generic_sections.sort(key=lambda item: (-item["match_term_count"], -item["matched_subpoint_count"], str(item["title"])))
    return {
        "generic": summary(generic_sections),
        "non_generic": summary(non_generic_sections),
        "top_generic_sections": generic_sections[:20],
    }


def analyze_dense_drift(
    fused_candidates: List[Dict[str, Any]],
    section_by_id: Dict[str, Dict[str, Any]],
    top_k: int = 40,
) -> Dict[str, Any]:
    ranked = sorted(
        fused_candidates,
        key=lambda row: (int(row.get("fused_rank") or 10_000), -float(row.get("fused_score") or 0.0)),
    )[:top_k]
    dense_only = []
    dense_without_anchors = []
    for row in ranked:
        lane_ranks = row.get("component_lane_ranks", {}) or {}
        has_dense = any(name.endswith("dense") and value is not None for name, value in lane_ranks.items())
        has_lexical = any("lexical" in name and value is not None for name, value in lane_ranks.items())
        if not has_dense:
            continue
        section = section_by_id[row["section_id"]]
        matches = match_subpoints(f"{section.get('title', '')}\n{section.get('text', '')}")
        entry = {
            "fused_rank": row.get("fused_rank"),
            "doc_id": row.get("doc_id"),
            "title": row.get("title"),
            "section_type": row.get("section_type"),
            "dense_only": bool(has_dense and not has_lexical),
            "matched_subpoints": sorted(matches.keys()),
            "match_term_count": sum(len(v) for v in matches.values()),
        }
        if has_dense and not has_lexical:
            dense_only.append(entry)
        if entry["match_term_count"] == 0:
            dense_without_anchors.append(entry)

    return {
        "top_k": top_k,
        "dense_only_count": len(dense_only),
        "dense_without_anchor_count": len(dense_without_anchors),
        "dense_only_rows": dense_only[:20],
        "dense_without_anchor_rows": dense_without_anchors[:20],
    }


def build_report(summary: Dict[str, Any]) -> str:
    lines = []
    lines.append("# Phase E Failure Lab")
    lines.append("")
    lines.append(f"- Run ID: `{summary['run_id']}`")
    lines.append(f"- Phase E status: `{summary['phase_e_status']}`")
    lines.append(f"- Dense mode: `{summary['dense_mode']}`")
    lines.append("")
    lines.append("## Root Cause Signals")
    lines.append("")
    for item in summary["root_causes"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Corpus Support By Subpoint")
    lines.append("")
    for row in summary["corpus_support"]["rows"]:
        lines.append(
            f"- `{row['subpoint_id']}` {row['label']}: raw_sections={row['raw_matching_section_count']}, trusted_sections={row['trusted_matching_section_count']}, raw_docs={row['raw_matching_doc_count']}, trusted_docs={row['trusted_matching_doc_count']}"
        )
    lines.append("")
    lines.append("## Top-20 Behavior")
    lines.append("")
    lines.append(f"- Dominant subpoints: `{summary['top20']['dominant_subpoints']}`")
    lines.append(f"- Generic titles in top 20: `{summary['top20']['generic_title_count']}`")
    lines.append(f"- High-evidence generic titles in top 20: `{summary['top20']['generic_high_evidence_count']}`")
    lines.append(f"- Low-evidence generic titles in top 20: `{summary['top20']['generic_low_evidence_count']}`")
    lines.append("")
    lines.append("## Generic Section Usefulness")
    lines.append("")
    lines.append(f"- Generic summary: `{summary['generic_analysis']['generic']}`")
    lines.append(f"- Non-generic summary: `{summary['generic_analysis']['non_generic']}`")
    lines.append("")
    lines.append("## Dense Drift")
    lines.append("")
    lines.append(f"- Dense-only in top 40: `{summary['dense_drift']['dense_only_count']}`")
    lines.append(f"- Dense-supported without lexical anchors in top 40: `{summary['dense_drift']['dense_without_anchor_count']}`")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    data = load_run(args.base_dir, args.run_id)
    out_dir = data["run_dir"] / "phase_e_failure_lab"
    out_dir.mkdir(parents=True, exist_ok=True)

    section_by_id = {row["section_id"]: row for row in data["sections"]}
    candidate_view_map = build_candidate_view_map(data["lane_rows"])
    corpus_support = summarize_corpus_support(data["sections"])
    top20 = analyze_top_candidates(data["fused_candidates"], section_by_id, candidate_view_map, top_k=20)
    generic_analysis = analyze_generic_sections(data["sections"])
    dense_drift = analyze_dense_drift(data["fused_candidates"], section_by_id, top_k=40)

    root_causes: List[str] = []
    for subpoint_id in ("SP2", "SP3", "SP4"):
        support = corpus_support["by_subpoint"][subpoint_id]
        if support["trusted_matching_section_count"] <= 1:
            root_causes.append(
                f"{subpoint_id} has almost no anchored evidence in the corpus, so retrieval should support abstention instead of forcing coverage."
            )
    if len(top20["dominant_subpoints"]) <= 3:
        root_causes.append("Global fusion collapses multiple views into a small set of dominant subpoints instead of preserving aspect coverage.")
    if top20["generic_high_evidence_count"] >= top20["generic_low_evidence_count"]:
        root_causes.append("Generic section titles are not intrinsically bad; many generic sections carry strong evidence and should be judged by passage evidence, not title alone.")
    if dense_drift["dense_without_anchor_count"] > 0:
        root_causes.append("Dense retrieval contributes candidates with weak or absent lexical anchors, so dense support needs a confidence or anchoring gate for unsupported facets.")

    summary = {
        "run_id": args.run_id,
        "phase_e_status": data["phase_e_assessment"]["assessment"]["status"],
        "dense_mode": data["phase_e_summary"]["dense_trace"].get("dense_mode"),
        "corpus_support": corpus_support,
        "top20": top20,
        "generic_analysis": generic_analysis,
        "dense_drift": dense_drift,
        "root_causes": root_causes,
    }

    write_json(out_dir / "diagnosis.json", summary)
    write_md(out_dir / "diagnosis.md", build_report(summary))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nWrote failure lab artifacts to {out_dir}")


if __name__ == "__main__":
    main()
