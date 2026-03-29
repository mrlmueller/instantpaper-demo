#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

PDF_SCAN_DIR = Path(__file__).resolve().parents[2]
if str(PDF_SCAN_DIR) not in sys.path:
    sys.path.insert(0, str(PDF_SCAN_DIR))

from tools.benchmark.evaluate_manual_benchmark import load_suite
from phase_f_lab import PhaseFOptions, score_cross_encoder_pairs

try:
    from openai import OpenAI
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover
    OpenAI = None
    BaseModel = None
    Field = None

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()

SECTION_CATEGORIES = [
    "decision_psychology_theory",
    "nudging_choice_architecture",
    "trust_risk_uncertainty",
    "review_quality_authenticity",
    "information_presentation_filtering_comparison",
    "consumer_electronics_or_product_examples",
    "supporting_background_context",
    "methods_or_low_value",
]

MISS_REASONS = [
    "phase_c_structure_issue",
    "phase_d_query_scope_too_narrow",
    "phase_e_retrieval_recall_gap",
    "phase_f_rerank_downranked",
    "phase_g_threshold_or_doc_calibration",
    "benchmark_anchor_not_actually_strong",
]


if BaseModel is not None:

    class BenchmarkAssessment(BaseModel):
        expected_section_title: str = Field(min_length=1)
        usefulness_0_to_10: int = Field(ge=0, le=10)
        primary_category: str = Field(min_length=1)
        secondary_categories: List[str] = Field(default_factory=list, max_length=3)
        benchmark_anchor_validity: str = Field(min_length=1, max_length=24)
        miss_reason: str = Field(min_length=1)
        why_not_surfaced: str = Field(min_length=1, max_length=320)
        suggested_pipeline_change: str = Field(min_length=1, max_length=320)


    class BenchmarkAssessmentBatch(BaseModel):
        items: List[BenchmarkAssessment] = Field(default_factory=list)

else:
    BenchmarkAssessmentBatch = None


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def truncate_text(value: Any, limit: int = 2200) -> str:
    text = clean_text(value)
    if len(text) <= int(limit):
        return text
    return text[: max(1, int(limit) - 1)] + "…"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_messages(chapter_title: str, chapter_description: str, rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    system = (
        "You are reviewing benchmark target sections and diagnosing why a retrieval pipeline did or did not surface them. "
        "Rate the section's actual usefulness broadly for writing the chapter, not just literal match quality. "
        "Use the provided pipeline ranks and reason as clues, but judge the section text itself. "
        "If the benchmark anchor itself seems weak, say so. "
        "When suggesting a pipeline change, prefer general fixes over benchmark-specific hacks."
    )
    user_lines = [
        f"Chapter title:\n{chapter_title}",
        "",
        f"Chapter description:\n{chapter_description}",
        "",
        f"Allowed categories:\n{', '.join(SECTION_CATEGORIES)}",
        "",
        f"Allowed miss_reason labels:\n{', '.join(MISS_REASONS)}",
        "",
        "Review these benchmark targets:",
        "",
    ]
    for row in rows:
        user_lines.extend(
            [
                f"EXPECTED_SECTION_TITLE: {row['expected_section_title']}",
                f"DOC_TITLE: {clean_text(row.get('doc_title') or row.get('doc_id') or '')}",
                f"PAGES: {row.get('expected_page_start')}-{row.get('expected_page_end')}",
                f"BENCHMARK_LABEL_0_TO_3: {row.get('benchmark_label_0_to_3')}",
                f"BENCHMARK_NOTES: {clean_text(row.get('benchmark_notes') or '')}",
                f"PIPELINE_REASON: {clean_text(row.get('pipeline_reason') or '')}",
                f"PIPELINE_PHASE_E_DOC_RANK: {row.get('phase_e_doc_rank')}",
                f"PIPELINE_PHASE_F_DOC_RANK: {row.get('phase_f_doc_rank')}",
                f"PIPELINE_PHASE_G_DOC_RANK: {row.get('phase_g_doc_rank')}",
                f"PIPELINE_DOC_ABORT_REASON: {clean_text(row.get('doc_abstention_reason') or '')}",
                f"TEXT:\n{truncate_text(row.get('inspection_text') or row.get('inspection_excerpt') or '', limit=2200)}",
                "",
            ]
        )
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(user_lines)}]


def render_markdown(rows: List[Dict[str, Any]]) -> str:
    lines = ["# Benchmark Target Review", ""]
    for row in rows:
        lines.extend(
            [
                f"## {clean_text(row.get('doc_title') or row.get('doc_id') or '')} :: {clean_text(row.get('expected_section_title') or '')}",
                "",
                f"- usefulness_0_to_10: `{row.get('usefulness_0_to_10')}`",
                f"- primary_category: `{row.get('primary_category')}`",
                f"- secondary_categories: `{', '.join(row.get('secondary_categories') or [])}`",
                f"- benchmark_anchor_validity: `{row.get('benchmark_anchor_validity')}`",
                f"- miss_reason: `{row.get('miss_reason')}`",
                f"- pipeline_reason: `{row.get('pipeline_reason')}`",
                f"- why_not_surfaced: {clean_text(row.get('why_not_surfaced') or '')}",
                f"- suggested_pipeline_change: {clean_text(row.get('suggested_pipeline_change') or '')}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def local_benchmark_review(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    query_map = {
        "decision_psychology_theory": "heuristics biases dual-process decision confidence judgment under uncertainty",
        "nudging_choice_architecture": "choice architecture digital nudging transparency autonomy ethics manipulation",
        "trust_risk_uncertainty": "perceived risk uncertainty trust trustworthiness information asymmetry online purchase",
        "review_quality_authenticity": "review helpfulness fake reviews reviewer quality authenticity verified purchase",
        "information_presentation_filtering_comparison": "information overload comparison explainability summarization filtering top reviews",
        "consumer_electronics_or_product_examples": "consumer electronics smartphones laptops earbuds reliability product features",
        "supporting_background_context": "background introduction conceptual framing overview",
    }
    pairs = []
    for row in rows:
        for key, query in query_map.items():
            pairs.append(
                {
                    "expected_section_title": row["expected_section_title"],
                    "query_key": key,
                    "query": query,
                    "candidate_text": truncate_text(row.get("inspection_text") or row.get("inspection_excerpt") or "", limit=2200),
                }
            )
    payload = score_cross_encoder_pairs(
        pairs,
        PhaseFOptions(
            cross_encoder_model="BAAI/bge-reranker-v2-m3",
            cross_encoder_batch_size=8,
            cross_encoder_max_length=1536,
        ),
    )
    by_title: Dict[str, Dict[str, float]] = {}
    for item in payload["rows"]:
        by_title.setdefault(str(item.get("expected_section_title") or ""), {})[str(item.get("query_key") or "")] = float(item.get("score_prob") or 0.0)

    reviewed = []
    for row in rows:
        scores = dict(by_title.get(row["expected_section_title"]) or {})
        primary_category = max(scores, key=scores.get) if scores else "methods_or_low_value"
        primary_score = float(scores.get(primary_category) or 0.0)
        usefulness = min(10.0, (primary_score * 7.5) + (0.8 if str(row.get("benchmark_label_0_to_3") or "") == "3" else 0.0))
        pipeline_reason = str(row.get("pipeline_reason") or "")
        if pipeline_reason.startswith("phase_c"):
            miss_reason = "phase_c_structure_issue"
            suggested = "Improve section recovery or heading anchoring so the section exists structurally before retrieval."
        elif pipeline_reason.startswith("phase_e"):
            miss_reason = "phase_e_retrieval_recall_gap"
            suggested = "Broaden retrieval with better bridge terms, doc-level rescue, or wider first-stage candidate pools."
        elif pipeline_reason.startswith("phase_f"):
            miss_reason = "phase_f_rerank_downranked"
            suggested = "Let reranking see a larger candidate pool and use broader query facets instead of a narrow global query."
        elif pipeline_reason.startswith("phase_g"):
            miss_reason = "phase_g_threshold_or_doc_calibration"
            suggested = "Relax doc-level calibration or treat strong partial sections as sufficient for a useful-doc decision."
        else:
            miss_reason = "benchmark_anchor_not_actually_strong"
            suggested = "Re-check whether this benchmark anchor is truly strong or just loosely related."
        reviewed.append(
            {
                **row,
                "usefulness_0_to_10": int(round(usefulness)),
                "primary_category": primary_category,
                "secondary_categories": [key for key, value in sorted(scores.items(), key=lambda item: item[1], reverse=True) if key != primary_category and float(value) >= max(0.45, primary_score - 0.08)][:3],
                "benchmark_anchor_validity": "strong" if usefulness >= 7 else ("mixed" if usefulness >= 4 else "weak"),
                "miss_reason": miss_reason,
                "why_not_surfaced": f"Pipeline status was {pipeline_reason}; the section reads mainly as {primary_category.replace('_', ' ')}.",
                "suggested_pipeline_change": suggested,
            }
        )
    return reviewed


def main() -> None:
    parser = argparse.ArgumentParser(description="Review benchmark target sections and diagnose misses.")
    parser.add_argument("--run-id", default="386e04657c41c805f8c1b974")
    parser.add_argument("--suite-manifest", default="benchmark/full_dump_webshop_manual_v1/manifests/suite_manifest.json")
    parser.add_argument("--input-jsonl", default="")
    parser.add_argument("--output-subdir", default="section_inspection")
    parser.add_argument("--model", default="gpt-5-mini")
    parser.add_argument("--batch-size", type=int, default=4)
    args = parser.parse_args()

    suite = load_suite((PDF_SCAN_DIR / args.suite_manifest).resolve())
    chapter = suite["chapter"]
    run_dir = (PDF_SCAN_DIR / "runs" / args.run_id).resolve()
    input_path = Path(args.input_jsonl).resolve() if args.input_jsonl else (run_dir / args.output_subdir / "benchmark_targets.jsonl")
    output_dir = run_dir / args.output_subdir
    output_path = output_dir / "benchmark_target_reviews.jsonl"
    markdown_path = output_dir / "benchmark_target_reviews.md"
    summary_path = output_dir / "benchmark_target_reviews_summary.json"

    rows = load_jsonl(input_path)
    if OPENAI_API_KEY and OpenAI is not None and BenchmarkAssessmentBatch is not None:
        client = OpenAI(api_key=OPENAI_API_KEY)
        reviewed_rows = []
        total_input_tokens = 0
        total_output_tokens = 0
        review_mode = "openai"
        for start in range(0, len(rows), max(1, int(args.batch_size))):
            batch = rows[start : start + max(1, int(args.batch_size))]
            messages = build_messages(chapter["title"], chapter["description"], batch)
            response = client.responses.parse(
                model=str(args.model or "gpt-5-mini"),
                reasoning={"effort": "low"},
                input=messages,
                max_output_tokens=2200,
                text_format=BenchmarkAssessmentBatch,
            )
            parsed = response.output_parsed
            usage = getattr(response, "usage", None)
            total_input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
            total_output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
            by_title = {item.expected_section_title: item.model_dump() for item in (parsed.items or [])}
            for row in batch:
                assessment = dict(by_title.get(row["expected_section_title"]) or {})
                reviewed_rows.append(
                    {
                        **row,
                        "usefulness_0_to_10": assessment.get("usefulness_0_to_10"),
                        "primary_category": assessment.get("primary_category"),
                        "secondary_categories": assessment.get("secondary_categories") or [],
                        "benchmark_anchor_validity": assessment.get("benchmark_anchor_validity"),
                        "miss_reason": assessment.get("miss_reason"),
                        "why_not_surfaced": assessment.get("why_not_surfaced"),
                        "suggested_pipeline_change": assessment.get("suggested_pipeline_change"),
                    }
                )
    else:
        review_mode = "local_cross_encoder"
        total_input_tokens = 0
        total_output_tokens = 0
        reviewed_rows = local_benchmark_review(rows)

    write_jsonl(output_path, reviewed_rows)
    markdown_path.write_text(render_markdown(reviewed_rows), encoding="utf-8")
    write_json(
        summary_path,
        {
            "run_id": args.run_id,
            "benchmark_target_count": len(reviewed_rows),
            "model": args.model,
            "review_mode": review_mode,
            "batch_size": args.batch_size,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "output_path": str(output_path),
            "markdown_path": str(markdown_path),
        },
    )
    print(json.dumps({"run_id": args.run_id, "benchmark_target_count": len(reviewed_rows), "output_path": str(output_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
