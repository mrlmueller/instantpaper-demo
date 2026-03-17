#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

PDF_SCAN_DIR = Path(__file__).resolve().parents[2]
if str(PDF_SCAN_DIR) not in sys.path:
    sys.path.insert(0, str(PDF_SCAN_DIR))

from tools.benchmark.evaluate_manual_benchmark import read_json, read_jsonl


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return text or "topic"


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def truncate_text(value: Any, limit: int = 1600) -> str:
    text = clean_text(value)
    if len(text) <= int(limit):
        return text
    return text[: max(1, int(limit) - 1)] + "…"


def parse_theme_markdown(path: Path) -> tuple[str, str]:
    raw = path.read_text(encoding="utf-8")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"Theme file is empty: {path}")
    title = lines[0]
    description = "\n\n".join(part.strip() for part in raw.split("\n\n") if part.strip())
    if description.startswith(title):
        description = description[len(title) :].strip()
    description = description or title
    return title, description


def doc_map(rows: Iterable[Dict[str, Any]], key: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        doc_id = str(row.get(key) or "")
        if doc_id:
            out[doc_id] = row
    return out


def rows_by_doc(rows: Iterable[Dict[str, Any]], key: str = "doc_id") -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        doc_id = str(row.get(key) or "")
        if not doc_id:
            continue
        out.setdefault(doc_id, []).append(row)
    return out


def build_chapter_payload(theme_md: Path) -> Dict[str, Any]:
    title, description = parse_theme_markdown(theme_md)
    chapter_id = f"chapter_001_{slugify(title)[:64]}"
    return {
        "chapter_id": chapter_id,
        "title": title,
        "description": description,
        "language_hints": ["de", "en"],
        "subpoints": [],
        "notes": (
            "Manual exhaustive benchmark scaffold. Section-level usefulness, gold sections, near misses, and structural misses "
            "must be filled by direct PDF/section review."
        ),
    }


def render_review_packet(
    *,
    doc_row: Dict[str, Any],
    parser_row: Dict[str, Any] | None,
    final_doc_row: Dict[str, Any] | None,
    section_rows: List[Dict[str, Any]],
    fused_rows: List[Dict[str, Any]],
    rerank_rows: List[Dict[str, Any]],
) -> str:
    lines: List[str] = [
        f"# {clean_text(doc_row.get('title') or doc_row.get('doc_id') or 'Document')}",
        "",
        f"- doc_id: `{doc_row.get('doc_id')}`",
        f"- source_path: `{doc_row.get('source_path')}`",
        f"- page_count: `{doc_row.get('page_count')}`",
        f"- parser_strategy: `{doc_row.get('normalization_strategy')}`",
        f"- fallback_anchor_count: `{doc_row.get('fallback_anchor_count')}`",
        f"- extracted_sections: `{doc_row.get('section_count')}`",
        f"- extracted_passages: `{doc_row.get('passage_count')}`",
    ]
    if parser_row:
        lines.extend(
            [
                f"- parser_page_count: `{parser_row.get('page_count')}`",
                f"- parser_outline_count: `{parser_row.get('outline_count')}`",
                f"- parser_status: `{parser_row.get('parser_mode')}`",
            ]
        )
    if final_doc_row:
        lines.extend(
            [
                f"- current_pipeline_has_useful_information: `{final_doc_row.get('has_useful_information')}`",
                f"- current_pipeline_doc_match_probability: `{final_doc_row.get('doc_match_probability')}`",
                f"- current_pipeline_top_section_title: `{final_doc_row.get('top_section_title')}`",
                f"- current_pipeline_top_section_score: `{final_doc_row.get('top_section_score')}`",
            ]
        )
    lines.extend(["", "## Top Current Pipeline Sections", ""])
    top_sections = list((final_doc_row or {}).get("top_sections") or [])
    if top_sections:
        for row in top_sections[:10]:
            lines.extend(
                [
                    f"### {clean_text(row.get('title') or 'Untitled')}",
                    "",
                    f"- pages: `{row.get('pages')}`",
                    f"- score_0_to_100: `{row.get('score_0_to_100')}`",
                    f"- score_band: `{row.get('score_band')}`",
                    f"- support_strength: `{row.get('support_strength')}`",
                    f"- evidence_preview: {clean_text(row.get('evidence_preview') or '')}",
                    "",
                ]
            )
    else:
        lines.extend(["No final top sections yet.", ""])

    lines.extend(["## Top Retrieval Candidates", ""])
    if fused_rows:
        for row in fused_rows[:10]:
            lines.extend(
                [
                    f"- rank `{row.get('fused_rank')}` | pages `{row.get('page_start')}-{row.get('page_end')}` | {clean_text(row.get('title') or '')}",
                    f"  - fused_score: `{row.get('fused_score')}` | support_count: `{row.get('supporting_passage_count')}` | trusted_subpoints: `{', '.join(row.get('trusted_subpoint_ids') or [])}`",
                ]
            )
        lines.append("")
    else:
        lines.extend(["No fused candidates.", ""])

    lines.extend(["## Top Reranked Sections", ""])
    if rerank_rows:
        for row in rerank_rows[:10]:
            lines.extend(
                [
                    f"- rank `{row.get('rerank_rank')}` | pages `{row.get('page_start')}-{row.get('page_end')}` | {clean_text(row.get('title') or '')}",
                    f"  - rerank_score: `{row.get('rerank_score')}` | cross_encoder_score: `{row.get('cross_encoder_score')}` | judge_score: `{row.get('judge_score')}`",
                ]
            )
        lines.append("")
    else:
        lines.extend(["No rerank rows.", ""])

    lines.extend(["## Extracted Sections", ""])
    for idx, row in enumerate(section_rows, 1):
        lines.extend(
            [
                f"### [{idx}] {clean_text(row.get('title') or 'Untitled')}",
                "",
                f"- section_id: `{row.get('section_id')}`",
                f"- pages: `{row.get('page_start')}-{row.get('page_end')}`",
                f"- level: `{row.get('level')}`",
                f"- section_type: `{row.get('section_type')}`",
                f"- retrieval_eligible: `{row.get('retrieval_eligible')}`",
                f"- parser_sources: `{', '.join(row.get('parser_sources') or [])}`",
                f"- quality_flags: `{', '.join(row.get('quality_flags') or [])}`",
                "",
                truncate_text(row.get("text") or "", limit=2400),
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a manual exhaustive benchmark suite scaffold from a run.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--theme-md", required=True)
    parser.add_argument("--suite-id", required=True)
    args = parser.parse_args()

    run_dir = (PDF_SCAN_DIR / "runs" / str(args.run_id)).resolve()
    suite_dir = (PDF_SCAN_DIR / "benchmark" / str(args.suite_id)).resolve()
    theme_md = Path(args.theme_md).resolve()

    chapter = build_chapter_payload(theme_md)
    chapter_id = str(chapter["chapter_id"])

    document_rows = read_jsonl(run_dir / "normalized" / "documents.jsonl")
    section_rows = read_jsonl(run_dir / "normalized" / "sections.jsonl")
    parser_documents = read_jsonl(run_dir / "parser" / "documents.jsonl")
    fused_rows = read_jsonl(run_dir / "retrieval" / "fused_candidates.jsonl")
    rerank_rows = read_jsonl(run_dir / "rerank" / "rerank_results.jsonl")
    final_output = read_json(run_dir / "final" / "output.json")
    final_docs = doc_map(final_output.get("documents") or [], "doc_id")

    docs_by_id = doc_map(document_rows, "doc_id")
    parser_by_id = doc_map(parser_documents, "doc_id")
    sections_by_doc = rows_by_doc(section_rows)
    fused_by_doc = rows_by_doc(fused_rows)
    rerank_by_doc = rows_by_doc(rerank_rows)

    judgments_refs: list[str] = []
    manifests_refs: list[str] = []
    review_packets_dir = suite_dir / "review_packets"
    review_packets_dir.mkdir(parents=True, exist_ok=True)

    for doc_id in sorted(docs_by_id):
        doc_row = docs_by_id[doc_id]
        doc_sections = sorted(
            sections_by_doc.get(doc_id, []),
            key=lambda row: (int(row.get("page_start") or 0), int(row.get("level") or 0), clean_text(row.get("title") or "")),
        )
        current_final = final_docs.get(doc_id, {})
        judgment_payload = {
            "chapter_id": chapter_id,
            "doc_id": doc_id,
            "doc_title": doc_row.get("title"),
            "has_useful_information": None,
            "document_label_0_to_3": None,
            "document_label_band": "",
            "document_notes": "",
            "manual_review_basis": [
                "direct PDF reading",
                f"run {args.run_id} normalized sections",
                "review packet with extracted section text and current pipeline trace",
            ],
            "gold_section_refs": [],
            "near_miss_sections": [],
            "structural_miss_sections": [],
            "section_judgments": [
                {
                    "section_ref": {
                        "section_id": row.get("section_id"),
                        "section_title": row.get("title"),
                        "page_start": row.get("page_start"),
                        "page_end": row.get("page_end"),
                        "section_type": row.get("section_type"),
                    },
                    "usefulness_0_to_10": None,
                    "label_0_to_3": None,
                    "label_band": "",
                    "judgment_role": "",
                    "supported_subpoints": [],
                    "benchmark_categories": [],
                    "retrieval_eligible": bool(row.get("retrieval_eligible")),
                    "quality_flags": list(row.get("quality_flags") or []),
                    "notes": "",
                    "section_text_excerpt": truncate_text(row.get("text") or "", limit=2200),
                    "pipeline_trace": {
                        "phase_e_doc_rank": next((item.get("fused_rank") for item in fused_by_doc.get(doc_id, []) if str(item.get("section_id") or "") == str(row.get("section_id") or "")), None),
                        "phase_f_doc_rank": next((item.get("rerank_rank") for item in rerank_by_doc.get(doc_id, []) if str(item.get("section_id") or "") == str(row.get("section_id") or "")), None),
                        "phase_g_doc_rank": next((idx for idx, item in enumerate(list(current_final.get("top_sections") or []), 1) if str(item.get("section_id") or "") == str(row.get("section_id") or "")), None),
                        "phase_g_score_0_to_100": next((item.get("score_0_to_100") for item in list(current_final.get("top_sections") or []) if str(item.get("section_id") or "") == str(row.get("section_id") or "")), None),
                        "doc_has_useful_information": current_final.get("has_useful_information"),
                        "doc_match_probability": current_final.get("doc_match_probability"),
                        "doc_abstention_reason": current_final.get("abstention_reason"),
                    },
                }
                for row in doc_sections
            ],
        }
        judgment_name = f"{chapter_id}__{doc_id}.json"
        write_json(suite_dir / "judgments" / judgment_name, judgment_payload)
        judgments_refs.append(f"judgments/{judgment_name}")

        manifest_payload = {
            "doc_id": doc_id,
            "label": doc_row.get("title"),
            "path": doc_row.get("source_path"),
            "role_in_suite": "manual_review_pending",
            "expected_difficulty": "unknown",
            "notes": "Manual benchmark labeling pending.",
        }
        manifest_name = f"{doc_id}.json"
        write_json(suite_dir / "manifests" / manifest_name, manifest_payload)
        manifests_refs.append(f"manifests/{manifest_name}")

        packet = render_review_packet(
            doc_row=doc_row,
            parser_row=parser_by_id.get(doc_id),
            final_doc_row=current_final,
            section_rows=doc_sections,
            fused_rows=sorted(fused_by_doc.get(doc_id, []), key=lambda row: int(row.get("fused_rank") or 100000)),
            rerank_rows=sorted(rerank_by_doc.get(doc_id, []), key=lambda row: int(row.get("rerank_rank") or 100000)),
        )
        (review_packets_dir / f"{doc_id}.md").write_text(packet, encoding="utf-8")

    suite_manifest = {
        "suite_id": str(args.suite_id),
        "suite_type": "manual_exhaustive_scaffold",
        "chapter_specs": [f"chapters/{chapter_id}.json"],
        "documents": manifests_refs,
        "judgments": judgments_refs,
        "notes": (
            "Initial scaffold for manual exhaustive labeling. Each judgment file contains every extracted section plus pipeline trace data. "
            "Fill document-level labels, section usefulness, gold sections, near misses, and structural misses after direct PDF review."
        ),
    }
    write_json(suite_dir / "manifests" / "suite_manifest.json", suite_manifest)
    write_json(suite_dir / "chapters" / f"{chapter_id}.json", chapter)
    write_json(
        suite_dir / "suite_summary.json",
        {
            "suite_id": str(args.suite_id),
            "chapter_id": chapter_id,
            "run_id": str(args.run_id),
            "document_count": len(docs_by_id),
            "section_count": len(section_rows),
            "judgment_status": "manual_review_pending",
            "label_distribution": {},
        },
    )
    readme_lines = [
        f"# {args.suite_id}",
        "",
        "This suite is a manual exhaustive benchmark scaffold.",
        "",
        "Files:",
        "- `chapters/`: topic spec from `Text Thema.md`",
        "- `judgments/`: one JSON per document with every extracted section",
        "- `review_packets/`: human-readable packets for manual review",
        "- `manifests/`: suite and document manifests",
        "",
        f"Source run: `{args.run_id}`",
        "",
        "Next step: fill the judgment files by direct PDF review, then run `finalize_manual_topic_suite.py`.",
    ]
    (suite_dir / "README.md").write_text("\n".join(readme_lines).strip() + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "suite_id": str(args.suite_id),
                "run_id": str(args.run_id),
                "suite_dir": str(suite_dir),
                "document_count": len(docs_by_id),
                "section_count": len(section_rows),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
