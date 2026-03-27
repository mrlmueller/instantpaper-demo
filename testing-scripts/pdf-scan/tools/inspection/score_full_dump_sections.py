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


if BaseModel is not None:

    class SectionAssessment(BaseModel):
        section_id: str = Field(min_length=1)
        usefulness_0_to_10: int = Field(ge=0, le=10)
        primary_category: str = Field(min_length=1)
        secondary_categories: List[str] = Field(default_factory=list, max_length=3)
        short_rationale: str = Field(min_length=1, max_length=240)


    class SectionAssessmentBatch(BaseModel):
        items: List[SectionAssessment] = Field(default_factory=list)

else:
    SectionAssessmentBatch = None


CATEGORY_QUERIES = {
    "decision_psychology_theory": "heuristics biases dual-process decision confidence judgment under uncertainty representativeness framing availability",
    "nudging_choice_architecture": "choice architecture digital nudging nudging mechanisms defaults salience framing transparency user autonomy ethical boundaries manipulation",
    "trust_risk_uncertainty": "perceived risk uncertainty trust trustworthiness information asymmetry online purchase decision social commerce reviewer credibility",
    "review_quality_authenticity": "review helpfulness fake reviews review authenticity verified purchase quality signals reviewer quality manipulation trustworthiness",
    "information_presentation_filtering_comparison": "information overload comparison explainability information presentation filtering summarization ranking top reviews review analysis management",
    "consumer_electronics_or_product_examples": "consumer electronics smartphones laptops earbuds complex products product features reliability battery design comparisons",
    "supporting_background_context": "background overview introduction conceptual framing literature context",
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def truncate_text(value: Any, limit: int = 1800) -> str:
    text = clean_text(value)
    if len(text) <= int(limit):
        return text
    return text[: max(1, int(limit) - 1)] + "…"


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_messages(chapter_title: str, chapter_description: str, rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    system = (
        "You are rating extracted PDF sections for how useful they are for writing one target chapter. "
        "Usefulness is broad: a section can be valuable because it gives core theory, a mechanism, a trust/risk angle, "
        "information-quality evidence, product-specific examples, or a scientifically grounding perspective. "
        "Do NOT only reward direct lexical overlap with the chapter wording. "
        "Score 0 if the section is essentially useless for the chapter. "
        "Score 10 if it is extremely useful and should very likely be surfaced. "
        "Choose one primary category from the allowed list and up to three secondary categories. "
        "Be strict with front matter, pure methods, references, and generic low-information sections."
    )
    allowed = ", ".join(SECTION_CATEGORIES)
    user_lines = [
        f"Chapter title:\n{chapter_title}",
        "",
        f"Chapter description:\n{chapter_description}",
        "",
        f"Allowed categories:\n{allowed}",
        "",
        "Assess these sections:",
        "",
    ]
    for row in rows:
        user_lines.extend(
            [
                f"SECTION_ID: {row['section_id']}",
                f"DOC_TITLE: {clean_text(row.get('doc_title') or row.get('doc_id') or '')}",
                f"SECTION_TITLE: {clean_text(row.get('title') or '')}",
                f"PAGES: {row.get('page_start')}-{row.get('page_end')}",
                f"SECTION_TYPE: {clean_text(row.get('section_type') or '')}",
                f"TEXT:\n{truncate_text(row.get('text') or row.get('text_excerpt') or '', limit=1800)}",
                "",
            ]
        )
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(user_lines)}]


def local_section_score(rows: List[Dict[str, Any]], chapter_title: str, chapter_description: str) -> List[Dict[str, Any]]:
    pairs = []
    queries = {
        "global": f"{chapter_title} || {chapter_description}",
        **CATEGORY_QUERIES,
    }
    for row in rows:
        candidate_text = truncate_text(row.get("text") or row.get("text_excerpt") or "", limit=2000)
        for key, query in queries.items():
            pairs.append(
                {
                    "section_id": str(row.get("section_id") or ""),
                    "query_key": key,
                    "query": query,
                    "candidate_text": candidate_text,
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
    by_section: Dict[str, Dict[str, float]] = {}
    for item in payload["rows"]:
        by_section.setdefault(str(item.get("section_id") or ""), {})[str(item.get("query_key") or "")] = float(item.get("score_prob") or 0.0)

    scored_rows = []
    for row in rows:
        section_id = str(row.get("section_id") or "")
        scores = dict(by_section.get(section_id) or {})
        category_scores = {key: float(scores.get(key) or 0.0) for key in CATEGORY_QUERIES}
        primary_category = max(category_scores, key=category_scores.get) if category_scores else "methods_or_low_value"
        primary_score = float(category_scores.get(primary_category) or 0.0)
        secondary_categories = [
            key
            for key, value in sorted(category_scores.items(), key=lambda item: item[1], reverse=True)
            if key != primary_category and float(value) >= max(0.48, primary_score - 0.07)
        ][:3]
        usefulness = min(
            10.0,
            (float(scores.get("global") or 0.0) * 5.5)
            + (primary_score * 3.5)
            + (0.5 * len(secondary_categories)),
        )
        if str(row.get("section_type") or "") in {"references", "acknowledgements", "table_of_contents", "index", "front_matter"}:
            usefulness = min(usefulness, 1.0)
            primary_category = "methods_or_low_value"
            secondary_categories = []
        if not bool(row.get("retrieval_eligible", True)):
            usefulness = max(0.0, usefulness - 1.0)
        usefulness_0_to_10 = int(round(usefulness))
        scored_rows.append(
            {
                **row,
                "usefulness_0_to_10": usefulness_0_to_10,
                "primary_category": primary_category,
                "secondary_categories": secondary_categories,
                "short_rationale": f"local cross-encoder score; strongest facet={primary_category.replace('_', ' ')}",
                "local_query_scores": {k: round(v, 6) for k, v in {"global": float(scores.get("global") or 0.0), **category_scores}.items()},
            }
        )
    return scored_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Score all extracted sections for broad usefulness to the target chapter.")
    parser.add_argument("--run-id", default="386e04657c41c805f8c1b974")
    parser.add_argument("--suite-manifest", default="benchmark/full_dump_webshop_manual_v1/manifests/suite_manifest.json")
    parser.add_argument("--input-jsonl", default="")
    parser.add_argument("--output-subdir", default="section_inspection")
    parser.add_argument("--model", default="gpt-5-mini")
    parser.add_argument("--batch-size", type=int, default=6)
    args = parser.parse_args()

    suite = load_suite((PDF_SCAN_DIR / args.suite_manifest).resolve())
    chapter = suite["chapter"]
    run_dir = (PDF_SCAN_DIR / "runs" / args.run_id).resolve()
    input_path = Path(args.input_jsonl).resolve() if args.input_jsonl else (run_dir / args.output_subdir / "all_sections.jsonl")
    output_dir = run_dir / args.output_subdir
    output_path = output_dir / "section_scores_openai.jsonl"
    summary_path = output_dir / "section_scores_openai_summary.json"

    section_rows = load_jsonl(input_path)
    if OPENAI_API_KEY and OpenAI is not None and SectionAssessmentBatch is not None:
        client = OpenAI(api_key=OPENAI_API_KEY)
        scored_rows = []
        total_input_tokens = 0
        total_output_tokens = 0
        scoring_mode = "openai"
        for start in range(0, len(section_rows), max(1, int(args.batch_size))):
            batch = section_rows[start : start + max(1, int(args.batch_size))]
            messages = build_messages(chapter["title"], chapter["description"], batch)
            response = client.responses.parse(
                model=str(args.model or "gpt-5-mini"),
                reasoning={"effort": "low"},
                input=messages,
                max_output_tokens=2200,
                text_format=SectionAssessmentBatch,
            )
            parsed = response.output_parsed
            usage = getattr(response, "usage", None)
            total_input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
            total_output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
            scored_by_id = {item.section_id: item.model_dump() for item in (parsed.items or [])}
            for row in batch:
                section_id = str(row.get("section_id") or "")
                assessment = dict(scored_by_id.get(section_id) or {})
                scored_rows.append(
                    {
                        **row,
                        "usefulness_0_to_10": assessment.get("usefulness_0_to_10"),
                        "primary_category": assessment.get("primary_category"),
                        "secondary_categories": assessment.get("secondary_categories") or [],
                        "short_rationale": assessment.get("short_rationale"),
                    }
                )
    else:
        scoring_mode = "local_cross_encoder"
        total_input_tokens = 0
        total_output_tokens = 0
        scored_rows = local_section_score(section_rows, chapter["title"], chapter["description"])

    write_jsonl(output_path, scored_rows)
    write_json(
        summary_path,
        {
            "run_id": args.run_id,
            "section_count": len(scored_rows),
            "model": args.model,
            "scoring_mode": scoring_mode,
            "batch_size": args.batch_size,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "output_path": str(output_path),
        },
    )
    print(json.dumps({"run_id": args.run_id, "section_count": len(scored_rows), "output_path": str(output_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
