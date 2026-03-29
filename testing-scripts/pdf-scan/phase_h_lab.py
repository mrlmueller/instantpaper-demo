#!/usr/bin/env python3
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict

from phase_a_lab import ensure_dir, read_json, utc_now_iso, write_json
from phase_b_lab import json_safe, rel_to_run
from phase_c_lab import read_jsonl_rows


@dataclass
class PhaseHOptions:
    force_rebuild: bool = False

    def normalized(self) -> "PhaseHOptions":
        return PhaseHOptions(force_rebuild=bool(self.force_rebuild))


def _chapter_output_payload(run_ctx: Any, chapter_id: str) -> Dict[str, Any]:
    chapter_artifacts = (run_ctx.artifacts.chapter_artifacts or {}).get(chapter_id)
    if chapter_artifacts is None:
        return {"status": "missing_artifacts", "chapter_id": chapter_id}

    final_dir = Path(chapter_artifacts.final_dir)
    output_path = final_dir / "output.json"
    doc_features_path = final_dir / "doc_features.jsonl"
    section_scores_path = final_dir / "section_scores.jsonl"
    if not output_path.exists():
        return {"status": "missing_output", "chapter_id": chapter_id}

    output = read_json(output_path)
    doc_features = read_jsonl_rows(doc_features_path) if doc_features_path.exists() else []
    section_scores = read_jsonl_rows(section_scores_path) if section_scores_path.exists() else []
    return {
        "status": "complete",
        "chapter_id": chapter_id,
        "output": output,
        "doc_features": doc_features,
        "section_scores": section_scores,
        "paths": {
            "output_path": rel_to_run(Path(run_ctx.run_dir), output_path),
            "doc_features_path": rel_to_run(Path(run_ctx.run_dir), doc_features_path) if doc_features_path.exists() else None,
            "section_scores_path": rel_to_run(Path(run_ctx.run_dir), section_scores_path) if section_scores_path.exists() else None,
        },
    }


def run_phase_h(
    run_ctx: Any,
    *,
    chapter_results: Dict[str, Dict[str, Any]],
    options: PhaseHOptions,
    run_logger=None,
) -> Dict[str, Any]:
    opt = options.normalized()
    aggregate_dir = ensure_dir(Path(run_ctx.artifacts.aggregate_dir))
    config_path = aggregate_dir / "phase_h_config.json"
    summary_path = aggregate_dir / "phase_h_summary.json"
    output_path = aggregate_dir / "output.json"
    matrix_path = aggregate_dir / "cross_chapter_matrix.json"

    if not bool(opt.force_rebuild) and summary_path.exists() and output_path.exists():
        return {
            "status": "cached",
            "summary": read_json(summary_path),
            "output": read_json(output_path),
        }

    write_json(
        config_path,
        {
            "generated_at_utc": utc_now_iso(),
            "phase": "phase_h",
            "options": json_safe(asdict(opt)),
        },
    )

    started = time.perf_counter()
    chapter_payloads: Dict[str, Dict[str, Any]] = {}
    doc_chapter_matrix: Dict[str, Dict[str, Any]] = defaultdict(dict)
    section_overlap: Dict[str, set[str]] = defaultdict(set)
    chapter_overview_rows = []

    for chapter_id, chapter_result in sorted((chapter_results or {}).items()):
        phase_payload = _chapter_output_payload(run_ctx, chapter_id)
        result_status = str(chapter_result.get("status") or "")
        phase_payload["orchestration_status"] = result_status or "unknown"
        phase_payload["error"] = chapter_result.get("error")
        phase_payload["elapsed_sec"] = chapter_result.get("elapsed_sec")
        chapter_payloads[chapter_id] = phase_payload

        if phase_payload.get("status") != "complete":
            chapter_overview_rows.append(
                {
                    "chapter_id": chapter_id,
                    "status": "failed",
                    "error": phase_payload.get("error") or f"phase_h_{phase_payload.get('status')}",
                    "useful_pdf_count": 0,
                    "document_count": 0,
                    "global_top_sections": [],
                }
            )
            continue

        output = dict(phase_payload.get("output") or {})
        doc_features = list(phase_payload.get("doc_features") or [])
        section_scores = list(phase_payload.get("section_scores") or [])

        useful_docs = [row for row in doc_features if bool(row.get("has_useful_information"))]
        chapter_overview_rows.append(
            {
                "chapter_id": chapter_id,
                "chapter_title": output.get("chapter_title"),
                "status": "success",
                "useful_pdf_count": len(useful_docs),
                "document_count": len(doc_features),
                "global_top_sections": list(output.get("global_top_sections") or [])[:10],
                "paths": phase_payload.get("paths") or {},
            }
        )

        for doc_row in doc_features:
            doc_id = str(doc_row.get("doc_id") or "")
            if not doc_id:
                continue
            doc_chapter_matrix[doc_id][chapter_id] = {
                "has_useful_information": bool(doc_row.get("has_useful_information")),
                "doc_match_probability": float(doc_row.get("doc_match_probability") or 0.0),
                "top_section_score": float(doc_row.get("top_section_score") or 0.0),
                "top_section_title": doc_row.get("top_section_title"),
                "abstention_reason": doc_row.get("abstention_reason"),
            }

        for section_row in section_scores:
            section_id = str(section_row.get("section_id") or "")
            if section_id and float(section_row.get("score_0_to_100") or 0.0) >= 34.0:
                section_overlap[section_id].add(chapter_id)

    document_rows = []
    for doc_id, per_chapter in sorted(doc_chapter_matrix.items()):
        useful_for = sorted(
            [
                chapter_id
                for chapter_id, payload in per_chapter.items()
                if bool(payload.get("has_useful_information"))
            ]
        )
        best = sorted(
            [
                {
                    "chapter_id": chapter_id,
                    "doc_match_probability": payload.get("doc_match_probability"),
                    "top_section_score": payload.get("top_section_score"),
                    "top_section_title": payload.get("top_section_title"),
                }
                for chapter_id, payload in per_chapter.items()
            ],
            key=lambda row: (
                float(row.get("doc_match_probability") or 0.0),
                float(row.get("top_section_score") or 0.0),
            ),
            reverse=True,
        )
        document_rows.append(
            {
                "doc_id": doc_id,
                "useful_for_chapters": useful_for,
                "useful_chapter_count": len(useful_for),
                "per_chapter": per_chapter,
                "best_chapter_match": best[0] if best else None,
            }
        )
    document_rows.sort(key=lambda row: (int(row.get("useful_chapter_count") or 0), row.get("doc_id") or ""), reverse=True)

    multi_chapter_sections = {
        section_id: sorted(list(chapters))
        for section_id, chapters in sorted(section_overlap.items())
        if len(chapters) > 1
    }

    completed = sorted(
        [
            chapter_id
            for chapter_id, row in chapter_results.items()
            if str(row.get("status") or "") in {"success", "cached"}
        ]
    )
    failed = sorted(
        [
            chapter_id
            for chapter_id, row in chapter_results.items()
            if str(row.get("status") or "") not in {"success", "cached"}
        ]
    )
    aggregate_status = "success" if not failed else ("partial_success" if completed else "failed")
    elapsed_sec = round(time.perf_counter() - started, 3)

    output = {
        "generated_at_utc": utc_now_iso(),
        "run_id": run_ctx.run_id,
        "phase": "phase_h",
        "status": aggregate_status,
        "chapter_count": len(chapter_results or {}),
        "completed_chapters": completed,
        "failed_chapters": failed,
        "chapter_results": chapter_overview_rows,
        "document_matrix": document_rows,
        "multi_chapter_sections": {
            "count": len(multi_chapter_sections),
            "sections": multi_chapter_sections,
        },
    }
    write_json(output_path, output)
    write_json(matrix_path, {"generated_at_utc": utc_now_iso(), "run_id": run_ctx.run_id, "rows": document_rows})

    summary = {
        "generated_at_utc": utc_now_iso(),
        "run_id": run_ctx.run_id,
        "phase": "phase_h",
        "status": aggregate_status,
        "chapter_count": len(chapter_results or {}),
        "completed_chapter_count": len(completed),
        "failed_chapter_count": len(failed),
        "document_count": len(document_rows),
        "multi_chapter_section_count": len(multi_chapter_sections),
        "elapsed_sec": elapsed_sec,
        "output_path": rel_to_run(Path(run_ctx.run_dir), output_path),
        "matrix_path": rel_to_run(Path(run_ctx.run_dir), matrix_path),
    }
    write_json(summary_path, summary)

    if run_logger is not None:
        run_logger.info(
            "Phase H finished | status=%s | chapters=%s/%s | docs=%s | shared_sections=%s | elapsed_sec=%s",
            aggregate_status,
            len(completed),
            len(chapter_results or {}),
            len(document_rows),
            len(multi_chapter_sections),
            elapsed_sec,
        )

    return {
        "status": aggregate_status,
        "summary": summary,
        "output": output,
    }
