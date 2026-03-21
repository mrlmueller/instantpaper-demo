from __future__ import annotations

import argparse
import json
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

from utils.runtime_paths import resolve_pdf_scan_runtime_dir

PDF_SCAN_RUNTIME_DIR = resolve_pdf_scan_runtime_dir(__file__)
if str(PDF_SCAN_RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(PDF_SCAN_RUNTIME_DIR))

from phase_a_lab import (  # noqa: E402
    load_metrics,
    log_event,
    save_metrics,
    setup_run_logger,
    stable_hash,
    stage_timer,
)
from phase_a_lab import run_phase_a  # noqa: E402
from phase_b_lab import PhaseBOptions, run_phase_b  # noqa: E402
from phase_c_lab import PhaseCOptions, run_phase_c  # noqa: E402
from phase_d_lab import PhaseDOptions, run_phase_d  # noqa: E402
from phase_e_lab import PhaseEOptions, run_phase_e  # noqa: E402
from phase_f_lab import PhaseFOptions, run_phase_f  # noqa: E402
from phase_g_lab import PhaseGOptions, run_phase_g  # noqa: E402

EVENT_PREFIX = "PDF_SCAN_EVENT\t"
PHASE_LABELS = {
    "phase_a": "Phase A",
    "phase_b": "Phase B",
    "phase_c": "Phase C",
    "phase_d": "Phase D",
    "phase_e": "Phase E",
    "phase_f": "Phase F",
    "phase_g": "Phase G",
}


def emit(event: str, **payload: Any) -> None:
    print(
        EVENT_PREFIX + json.dumps({"event": str(event), **payload}, ensure_ascii=False),
        flush=True,
    )


def parse_theme_markdown(path: Path) -> tuple[str, str]:
    raw = path.read_text(encoding="utf-8")
    lines = [line.strip() for line in raw.splitlines()]
    non_empty = [line for line in lines if line]
    if not non_empty:
        raise ValueError(f"Theme file is empty: {path}")
    title = non_empty[0]
    description = "\n\n".join(part.strip() for part in raw.split("\n\n") if part.strip())
    if description.startswith(title):
        description = description[len(title) :].strip()
    description = description or title
    return title, description


def update_stage_metrics(run_ctx: Any, stage_name: str, metrics_update: dict[str, Any]) -> None:
    metrics = load_metrics(run_ctx)
    metrics.setdefault("stages", {}).setdefault(stage_name, {}).update(metrics_update)
    save_metrics(run_ctx, metrics)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the standalone PDF scan pipeline and emit structured progress events.")
    parser.add_argument("--theme-md", required=True, help="Path to the topic Text Thema.md file.")
    parser.add_argument("--pdf-dir", required=True, help="Directory containing the PDFs for the topic.")
    parser.add_argument("--runs-root", default="", help="Optional root directory for pipeline run artifacts.")
    parser.add_argument("--pipeline-version", default="pdf_scan_v3_topic_best")
    parser.add_argument("--pdf-glob", default="*.pdf")
    parser.add_argument("--pdf-recursive", action="store_true")
    parser.add_argument("--max-pdfs", type=int, default=100)
    parser.add_argument("--grobid-base-url", default="")
    parser.add_argument("--no-openai-planner", action="store_true")
    parser.add_argument("--no-openai-dense", action="store_true")
    parser.add_argument("--no-openai-judge", action="store_true")
    parser.add_argument("--force-rebuild-phase-a", action="store_true")
    parser.add_argument("--force-rebuild-phase-b", action="store_true")
    parser.add_argument("--force-rebuild-phase-c", action="store_true")
    parser.add_argument("--force-rebuild-phase-d", action="store_true")
    parser.add_argument("--force-rebuild-phase-e", action="store_true")
    parser.add_argument("--force-rebuild-phase-f", action="store_true")
    parser.add_argument("--force-rebuild-phase-g", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv or sys.argv[1:]))
    theme_path = Path(args.theme_md).resolve()
    pdf_dir = Path(args.pdf_dir).resolve()
    chapter_title, chapter_description = parse_theme_markdown(theme_path)

    phase_a_args = Namespace(
        input_mode="manual",
        pipeline_version=str(args.pipeline_version or "pdf_scan_v3_topic_best"),
        force_rebuild=bool(args.force_rebuild_phase_a),
        runs_root=str(args.runs_root or ""),
        suite_manifest="",
        chapter_index=0,
        doc_limit=None,
        include_doc_id=[],
        exclude_doc_id=[],
        chapter_title=chapter_title,
        chapter_description=chapter_description,
        pdf=[],
        pdf_dir=str(pdf_dir),
        pdf_glob=str(args.pdf_glob or "*.pdf"),
        pdf_recursive=bool(args.pdf_recursive),
        max_pdfs=int(args.max_pdfs),
    )

    phase_doc_totals: dict[str, int] = {}
    phase_doc_progress = {"phase_b": 0, "phase_c": 0}

    def bridged_log_event(run_ctx: Any, *, stage: str, event: str, **payload: Any) -> None:
        log_event(run_ctx, stage=stage, event=event, **payload)
        if stage == "phase_b" and event in {"document_parsed", "document_reused_from_cache", "document_failed"}:
            phase_doc_progress["phase_b"] += 1
            emit(
                "document_progress",
                stage=stage,
                label=PHASE_LABELS.get(stage, stage),
                current=phase_doc_progress["phase_b"],
                total=phase_doc_totals.get("phase_b"),
                doc_id=str(payload.get("doc_id") or ""),
            )
        elif stage == "phase_c" and event in {"doc_normalized", "doc_failed"}:
            phase_doc_progress["phase_c"] += 1
            emit(
                "document_progress",
                stage=stage,
                label=PHASE_LABELS.get(stage, stage),
                current=phase_doc_progress["phase_c"],
                total=phase_doc_totals.get("phase_c"),
                doc_id=str(payload.get("doc_id") or ""),
            )

    try:
        emit("stage_start", stage="phase_a", label=PHASE_LABELS["phase_a"])
        phase_a_result = run_phase_a(phase_a_args)
        run_ctx = phase_a_result["run_ctx"]
        pdf_manifest = phase_a_result["manifest_rows"]
        phase_doc_totals["phase_b"] = len(pdf_manifest)
        phase_doc_totals["phase_c"] = len(pdf_manifest)
        emit(
            "run_initialized",
            pipeline_run_id=str(run_ctx.run_id),
            run_dir=str(run_ctx.run_dir),
            document_count=len(pdf_manifest),
        )
        emit(
            "stage_complete",
            stage="phase_a",
            label=PHASE_LABELS["phase_a"],
            document_count=len(pdf_manifest),
        )

        if bool(args.force_rebuild_phase_b) or not (run_ctx.run_dir / "parser" / "phase_b_summary.json").exists():
            emit("stage_start", stage="phase_b", label=PHASE_LABELS["phase_b"], total=phase_doc_totals["phase_b"])
            phase_b_logger = setup_run_logger(run_ctx)
            phase_b_options = PhaseBOptions(
                force_rebuild=bool(args.force_rebuild_phase_b),
                doc_limit=None,
                include_doc_ids=[],
                exclude_doc_ids=[],
                min_page_words=20,
                min_doc_chars=200,
                try_docling=True,
                docling_page_limit=400,
                docling_max_file_size_bytes=50 * 1024 * 1024,
                docling_do_ocr=False,
                docling_do_table_structure=False,
                docling_document_timeout_sec=180,
                docling_num_threads=4,
                docling_enable_chunking=True,
                docling_chunk_size=20,
                docling_chunk_max_pages=400,
                docling_chunk_num_threads=1,
                try_grobid=True,
                grobid_page_limit=400,
                grobid_base_url=str(args.grobid_base_url or "").strip(),
                grobid_process_path="/api/processFulltextDocument",
                grobid_timeout_sec=120,
                grobid_consolidate_header=0,
                grobid_consolidate_citations=0,
                grobid_include_raw_citations=0,
            )
            with stage_timer(run_ctx, "phase_b"):
                phase_b_result = run_phase_b(
                    run_ctx,
                    pdf_manifest,
                    phase_b_options,
                    stable_hash_fn=stable_hash,
                    log_event_fn=bridged_log_event,
                    run_logger=phase_b_logger,
                )
                update_stage_metrics(run_ctx, "phase_b", phase_b_result["metrics_update"])
            emit(
                "stage_complete",
                stage="phase_b",
                label=PHASE_LABELS["phase_b"],
                current=phase_doc_progress["phase_b"],
                total=phase_doc_totals["phase_b"],
            )

        if bool(args.force_rebuild_phase_c) or not (run_ctx.run_dir / "normalized" / "phase_c_summary.json").exists():
            emit("stage_start", stage="phase_c", label=PHASE_LABELS["phase_c"], total=phase_doc_totals["phase_c"])
            phase_c_logger = setup_run_logger(run_ctx)
            phase_c_options = PhaseCOptions(
                force_rebuild=bool(args.force_rebuild_phase_c),
                min_section_words=20,
                passage_target_words=180,
                passage_max_words=260,
                passage_min_words=70,
                use_heuristic_recovery=True,
                repair_titles_from_anchor_blocks=True,
                heuristic_recovery_disable_when_strong_outline=True,
                heuristic_recovery_disable_when_docling_rich=True,
                enable_numbered_gap_fill_when_docling_noisy=True,
                docling_noise_ratio_for_gap_fill=0.22,
                docling_numbered_gap_fill_max_words=18,
                docling_supplement_strong_outline_numbering_depth=2,
            )
            with stage_timer(run_ctx, "phase_c"):
                phase_c_result = run_phase_c(
                    run_ctx,
                    phase_c_options,
                    stable_hash_fn=stable_hash,
                    log_event_fn=bridged_log_event,
                    run_logger=phase_c_logger,
                )
                update_stage_metrics(run_ctx, "phase_c", phase_c_result["metrics_update"])
            emit(
                "stage_complete",
                stage="phase_c",
                label=PHASE_LABELS["phase_c"],
                current=phase_doc_progress["phase_c"],
                total=phase_doc_totals["phase_c"],
            )

        if bool(args.force_rebuild_phase_d) or not (run_ctx.run_dir / "retrieval" / "phase_d_summary.json").exists():
            emit("stage_start", stage="phase_d", label=PHASE_LABELS["phase_d"])
            phase_d_logger = setup_run_logger(run_ctx)
            phase_d_options = PhaseDOptions(
                force_rebuild=bool(args.force_rebuild_phase_d),
                use_openai_planner=not bool(args.no_openai_planner),
                allow_heuristic_fallback=True,
                openai_model="gpt-5-mini",
                reasoning_effort="low",
                temperature=0.0,
                max_completion_tokens=1400,
                bridge_max_completion_tokens=1800,
                must_term_limit=8,
                should_term_limit=20,
                exclusion_limit=8,
                subpoint_limit=7,
                drift_risk_limit=8,
                source_anchor_limit=24,
                subpoint_source_anchor_limit=3,
                max_summary_chars=480,
                max_subpoint_summary_chars=320,
                min_anchor_token_overlap=0.67,
                planner_prompt_mode="coverage",
                include_should_terms_view=True,
                include_support_context_view=True,
                include_subpoint_lexical_views=True,
                bridge_term_limit=14,
            )
            with stage_timer(run_ctx, "phase_d"):
                phase_d_result = run_phase_d(
                    run_ctx,
                    chapter_title=phase_a_result["config"].chapter_title,
                    chapter_spec_text=phase_a_result["config"].chapter_spec_text,
                    options=phase_d_options,
                    stable_hash_fn=stable_hash,
                    log_event_fn=bridged_log_event,
                    run_logger=phase_d_logger,
                )
                update_stage_metrics(run_ctx, "phase_d", phase_d_result["metrics_update"])
            emit("stage_complete", stage="phase_d", label=PHASE_LABELS["phase_d"])

        if bool(args.force_rebuild_phase_e) or not (run_ctx.run_dir / "retrieval" / "phase_e_summary.json").exists():
            emit("stage_start", stage="phase_e", label=PHASE_LABELS["phase_e"])
            phase_e_logger = setup_run_logger(run_ctx)
            phase_e_options = PhaseEOptions(
                force_rebuild=bool(args.force_rebuild_phase_e),
                candidate_limit_per_lane=160,
                fused_candidate_limit=260,
                per_view_limit_multiplier=4,
                rrf_k=60,
                lexical_k1=1.2,
                lexical_b=0.75,
                use_openai_dense=not bool(args.no_openai_dense),
                allow_lexical_only_fallback=True,
                openai_embedding_model="text-embedding-3-small",
                openai_timeout_sec=300,
                dense_batch_size=64,
                dense_section_max_chars=4200,
                dense_passage_max_chars=2400,
                dense_query_max_chars=1600,
                dense_dimensions=None,
                dense_min_similarity=0.05,
                top_candidate_preview_count=20,
                selection_strategy="round_robin",
                use_supported_subpoint_selection=False,
                abstain_when_no_supported_subpoints=False,
                generic_evidence_bonus=0.01,
                generic_anchor_score_threshold=1.0,
                single_support_penalty=0.003,
                zero_support_penalty=0.008,
                generic_low_support_penalty=0.004,
                subpoint_min_supported_candidates=1,
                subpoint_max_preview_rows=10,
                diversity_lambda=0.2,
                enable_doc_title_rescue=True,
                doc_rescue_doc_limit=10,
                doc_rescue_sections_per_doc=3,
                doc_rescue_score_scale=0.06,
            )
            with stage_timer(run_ctx, "phase_e"):
                phase_e_result = run_phase_e(
                    run_ctx,
                    options=phase_e_options,
                    stable_hash_fn=stable_hash,
                    log_event_fn=bridged_log_event,
                    run_logger=phase_e_logger,
                )
                update_stage_metrics(run_ctx, "phase_e", phase_e_result["metrics_update"])
            emit("stage_complete", stage="phase_e", label=PHASE_LABELS["phase_e"])

        if bool(args.force_rebuild_phase_f) or not (run_ctx.run_dir / "rerank" / "phase_f_summary.json").exists():
            emit("stage_start", stage="phase_f", label=PHASE_LABELS["phase_f"])
            phase_f_logger = setup_run_logger(run_ctx)
            phase_f_options = PhaseFOptions(
                force_rebuild=bool(args.force_rebuild_phase_f),
                rerank_top_k=140,
                inject_doc_top_candidates=True,
                cross_encoder_model="BAAI/bge-reranker-v2-m3",
                cross_encoder_batch_size=8,
                cross_encoder_max_length=1536,
                cross_encoder_subpoint_limit=2,
                section_excerpt_max_chars=2200,
                supporting_passage_count=3,
                passage_excerpt_max_chars=520,
                use_openai_judge=not bool(args.no_openai_judge),
                judge_model="gpt-5-mini",
                judge_reasoning_effort="low",
                judge_candidate_limit=24,
                judge_max_per_doc=3,
                judge_max_output_tokens=550,
                top_candidate_preview_count=20,
                cross_encoder_weight=0.72,
                fused_prior_weight=0.16,
                evidence_weight=0.12,
                llm_judge_blend=0.20,
                generic_title_penalty=0.035,
                weak_evidence_penalty=0.05,
                single_passage_penalty=0.02,
            )
            with stage_timer(run_ctx, "phase_f"):
                phase_f_result = run_phase_f(
                    run_ctx,
                    options=phase_f_options,
                    stable_hash_fn=stable_hash,
                    log_event_fn=bridged_log_event,
                    run_logger=phase_f_logger,
                )
                update_stage_metrics(run_ctx, "phase_f", phase_f_result["metrics_update"])
            emit("stage_complete", stage="phase_f", label=PHASE_LABELS["phase_f"])

        emit("stage_start", stage="phase_g", label=PHASE_LABELS["phase_g"])
        phase_g_logger = setup_run_logger(run_ctx)
        phase_g_options = PhaseGOptions(
            force_rebuild=bool(args.force_rebuild_phase_g),
            top_sections_per_doc=5,
            top_global_sections=25,
            section_useful_threshold=34,
            section_partial_threshold=22,
            doc_probability_threshold=0.16,
            top_section_floor=18,
            strong_top_section_floor=38,
            min_doc_sections_for_useful=1,
            min_doc_partial_sections=1,
            min_top_supporting_passages=1,
            top_k_for_doc_features=5,
            support_preview_count=2,
            support_preview_max_chars=260,
            generic_only_penalty=0.07,
            generic_high_penalty=0.02,
            penalized_type_penalty=0.08,
            calibration_mode="auto",
            broad_support_min_sections=1,
            broad_support_top1_floor=18,
            broad_support_probability_bonus=0.18,
        )
        with stage_timer(run_ctx, "phase_g"):
            phase_g_result = run_phase_g(
                run_ctx,
                options=phase_g_options,
                stable_hash_fn=stable_hash,
                log_event_fn=bridged_log_event,
                run_logger=phase_g_logger,
            )
            update_stage_metrics(run_ctx, "phase_g", phase_g_result["metrics_update"])
        emit("stage_complete", stage="phase_g", label=PHASE_LABELS["phase_g"])

        payload = {
            "pipeline_run_id": str(run_ctx.run_id),
            "run_dir": str(run_ctx.run_dir),
            "theme_md": str(theme_path),
            "pdf_dir": str(pdf_dir),
            "chapter_title": chapter_title,
            "chapter_description": chapter_description,
            "useful_pdfs": len([row for row in phase_g_result["doc_feature_rows"] if row.get("has_useful_information")]),
            "document_count": len(phase_g_result["doc_feature_rows"]),
            "output_json": str(run_ctx.artifacts.final_dir / "output.json"),
        }
        emit("run_complete", **payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
        return 0
    except Exception as exc:
        emit("run_error", error_type=type(exc).__name__, error_message=str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
