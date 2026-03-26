from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from utils.runtime_paths import resolve_pdf_scan_runtime_dir

PDF_SCAN_RUNTIME_DIR = resolve_pdf_scan_runtime_dir(__file__)
if str(PDF_SCAN_RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(PDF_SCAN_RUNTIME_DIR))

from phase_a_lab import (  # noqa: E402
    RunArtifacts,
    RunContext,
    load_metrics,
    log_event,
    read_json,
    save_metrics,
    setup_run_logger,
    stable_hash,
    stage_timer,
    write_json,
)
from phase_f_lab import PhaseFOptions, run_phase_f  # noqa: E402
from phase_g_lab import PhaseGOptions, run_phase_g  # noqa: E402
from phase_h_lab import PhaseHOptions, run_phase_h  # noqa: E402

EVENT_PREFIX = "PDF_SCAN_EVENT\t"
PHASE_LABELS = {
    "phase_f": "Phase F",
    "phase_g": "Phase G",
    "phase_h": "Phase H",
}


def emit(event: str, **payload: Any) -> None:
    print(EVENT_PREFIX + json.dumps({"event": str(event), **payload}, ensure_ascii=False), flush=True)


def update_stage_metrics(run_ctx: Any, stage_name: str, metrics_update: dict[str, Any]) -> None:
    metrics = load_metrics(run_ctx)
    metrics.setdefault("stages", {}).setdefault(stage_name, {}).update(metrics_update)
    save_metrics(run_ctx, metrics)


def update_chapter_stage_metrics(run_ctx: Any, chapter_id: str, stage_name: str, metrics_update: dict[str, Any]) -> None:
    metrics = load_metrics(run_ctx)
    chapter_metrics = metrics.setdefault("chapters", {}).setdefault(chapter_id, {})
    chapter_metrics.setdefault("stages", {}).setdefault(stage_name, {}).update(metrics_update)
    save_metrics(run_ctx, metrics)


def reconstruct_run_ctx(run_dir: Path) -> tuple[RunContext, dict[str, Any]]:
    run_dir = run_dir.resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    config_path = run_dir / "config.json"
    normalized_sections = run_dir / "normalized" / "sections.jsonl"
    if not config_path.exists():
        raise FileNotFoundError(f"Missing config.json in run directory: {run_dir}")
    if not normalized_sections.exists():
        raise FileNotFoundError(f"Missing normalized/sections.jsonl in run directory: {run_dir}")
    config = read_json(config_path)
    artifacts = RunArtifacts.from_run_dir(run_dir)
    return (
        RunContext(
            repo_root=PDF_SCAN_RUNTIME_DIR.parent.parent,
            pdf_scan_dir=PDF_SCAN_RUNTIME_DIR,
            run_id=run_dir.name,
            run_dir=run_dir,
            artifacts=artifacts,
        ),
        config,
    )


def detect_gpu_batch_size(default_batch_size: int) -> tuple[bool, int, str | None]:
    try:
        import torch
    except Exception:
        return False, default_batch_size, None
    if not torch.cuda.is_available():
        return False, default_batch_size, None
    vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    if default_batch_size > 8:
        batch_size = default_batch_size
    elif vram_gb >= 20:
        batch_size = 32
    elif vram_gb >= 14:
        batch_size = 16
    else:
        batch_size = 8
    return True, batch_size, torch.cuda.get_device_name(0)


def build_phase_f_options(args: argparse.Namespace, *, batch_size: int) -> PhaseFOptions:
    return PhaseFOptions(
        force_rebuild=bool(args.force_rebuild_phase_f),
        rerank_top_k=140,
        inject_doc_top_candidates=True,
        cross_encoder_model="BAAI/bge-reranker-v2-m3",
        cross_encoder_batch_size=batch_size,
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


def build_phase_g_options(args: argparse.Namespace) -> PhaseGOptions:
    return PhaseGOptions(
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


def _run_chapter_gpu_pipeline(
    run_ctx: Any,
    *,
    chapter: dict[str, Any],
    phase_f_options: PhaseFOptions,
    phase_g_options: PhaseGOptions,
    run_logger: Any,
) -> dict[str, Any]:
    chapter_id = str(chapter.get("chapter_id") or "")
    chapter_title = str(chapter.get("chapter_title") or "")
    chapter_ctx = run_ctx.for_chapter(chapter_id)
    retrieval_dir = Path(chapter_ctx.artifacts.retrieval_dir)
    rerank_dir = Path(chapter_ctx.artifacts.rerank_dir)
    final_dir = Path(chapter_ctx.artifacts.final_dir)
    if not (retrieval_dir / "fused_candidates.jsonl").exists():
        return {
            "chapter_id": chapter_id,
            "chapter_title": chapter_title,
            "status": "skipped",
            "error": "missing_phase_e_output",
        }
    if (
        not bool(phase_f_options.force_rebuild)
        and not bool(phase_g_options.force_rebuild)
        and (rerank_dir / "phase_f_summary.json").exists()
        and (final_dir / "phase_g_summary.json").exists()
        and (final_dir / "output.json").exists()
    ):
        output = read_json(final_dir / "output.json")
        return {
            "chapter_id": chapter_id,
            "chapter_title": chapter_title,
            "status": "cached",
            "elapsed_sec": 0.0,
            "useful_pdf_count": int(output.get("useful_pdf_count") or 0),
        }

    started = time.perf_counter()
    try:
        phase_f_result = run_phase_f(
            chapter_ctx,
            options=phase_f_options,
            stable_hash_fn=stable_hash,
            log_event_fn=log_event,
            run_logger=run_logger,
        )
        update_chapter_stage_metrics(run_ctx, chapter_id, "phase_f", phase_f_result.get("metrics_update") or {})

        phase_g_result = run_phase_g(
            chapter_ctx,
            options=phase_g_options,
            stable_hash_fn=stable_hash,
            log_event_fn=log_event,
            run_logger=run_logger,
        )
        update_chapter_stage_metrics(run_ctx, chapter_id, "phase_g", phase_g_result.get("metrics_update") or {})

        elapsed = round(time.perf_counter() - started, 3)
        useful_docs = len([row for row in phase_g_result.get("doc_feature_rows") or [] if row.get("has_useful_information")])
        return {
            "chapter_id": chapter_id,
            "chapter_title": chapter_title,
            "status": "success",
            "elapsed_sec": elapsed,
            "useful_pdf_count": useful_docs,
        }
    except Exception as exc:
        return {
            "chapter_id": chapter_id,
            "chapter_title": chapter_title,
            "status": "failed",
            "elapsed_sec": round(time.perf_counter() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run GPU phases (F-G-H) of the standalone PDF scan pipeline.")
    parser.add_argument("--run-dir", required=True, help="Path to an existing run directory produced by CPU phases.")
    parser.add_argument("--force-rebuild-phase-f", action="store_true")
    parser.add_argument("--force-rebuild-phase-g", action="store_true")
    parser.add_argument("--force-rebuild-phase-h", action="store_true")
    parser.add_argument("--no-openai-judge", action="store_true")
    parser.add_argument("--cross-encoder-batch-size", type=int, default=8)
    parser.add_argument("--max-gpu-chapter-concurrency", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv or sys.argv[1:]))
    run_dir = Path(args.run_dir).resolve()
    run_ctx, config = reconstruct_run_ctx(run_dir)
    run_logger = setup_run_logger(run_ctx)
    chapter_rows = [row for row in list(config.get("chapters") or []) if isinstance(row, dict)]
    if not chapter_rows:
        raise RuntimeError(
            "Restored GPU handoff is missing chapter configuration. "
            "Expected config.json with a non-empty chapters[] list."
        )

    chapter_ids_with_phase_e = []
    for chapter in chapter_rows:
        chapter_id = str((chapter or {}).get("chapter_id") or "").strip()
        if not chapter_id:
            continue
        fused_candidates_path = run_ctx.artifacts.for_chapter(chapter_id).retrieval_dir / "fused_candidates.jsonl"
        if fused_candidates_path.exists():
            chapter_ids_with_phase_e.append(chapter_id)
    if not chapter_ids_with_phase_e:
        raise RuntimeError(
            "Restored GPU handoff is missing all chapter retrieval artifacts. "
            "Expected chapters/<chapter_id>/retrieval/fused_candidates.jsonl for at least one chapter."
        )

    has_cuda, batch_size, gpu_name = detect_gpu_batch_size(int(args.cross_encoder_batch_size))
    if gpu_name:
        print(f"GPU: {gpu_name} | batch_size={batch_size}", flush=True)

    t_start = time.perf_counter()
    try:
        emit("stage_start", scope="chapter", stage="phase_f", label=PHASE_LABELS["phase_f"], total=len(chapter_rows))
        phase_f_options = build_phase_f_options(args, batch_size=batch_size)
        phase_g_options = build_phase_g_options(args)
        chapter_results: dict[str, dict[str, Any]] = {}

        with stage_timer(run_ctx, "phase_fg_parallel"):
            for chapter in chapter_rows:
                result = _run_chapter_gpu_pipeline(
                    run_ctx,
                    chapter=chapter,
                    phase_f_options=phase_f_options,
                    phase_g_options=phase_g_options,
                    run_logger=run_logger,
                )
                chapter_results[str(chapter.get("chapter_id") or "")] = result
                emit(
                    "chapter_stage_complete",
                    scope="chapter",
                    stage="phase_fg",
                    chapter_id=result.get("chapter_id"),
                    chapter_title=result.get("chapter_title"),
                    status=result.get("status"),
                    elapsed_sec=result.get("elapsed_sec"),
                    useful_pdf_count=result.get("useful_pdf_count"),
                    error=result.get("error"),
                )

            success_count = sum(1 for row in chapter_results.values() if row.get("status") in {"success", "cached"})
            skipped_count = sum(1 for row in chapter_results.values() if row.get("status") == "skipped")
            failed_count = sum(1 for row in chapter_results.values() if row.get("status") == "failed")
            update_stage_metrics(
                run_ctx,
                "phase_fg_parallel",
                {
                    "chapter_count": len(chapter_rows),
                    "successful_chapters": success_count,
                    "skipped_chapters": skipped_count,
                    "failed_chapters": failed_count,
                    "gpu_used": has_cuda,
                    "cross_encoder_batch_size": batch_size,
                },
            )
        emit("stage_complete", scope="chapter", stage="phase_f", label=PHASE_LABELS["phase_f"], current=success_count, total=len(chapter_rows))
        emit("stage_complete", scope="chapter", stage="phase_g", label=PHASE_LABELS["phase_g"], current=success_count, total=len(chapter_rows))

        emit("stage_start", scope="aggregate", stage="phase_h", label=PHASE_LABELS["phase_h"])
        with stage_timer(run_ctx, "phase_h"):
            phase_h_result = run_phase_h(
                run_ctx,
                chapter_results=chapter_results,
                options=PhaseHOptions(force_rebuild=bool(args.force_rebuild_phase_h)),
                run_logger=run_logger,
            )
            update_stage_metrics(
                run_ctx,
                "phase_h",
                {
                    "status": phase_h_result.get("status"),
                    "completed_chapter_count": len(phase_h_result.get("output", {}).get("completed_chapters") or []),
                    "failed_chapter_count": len(phase_h_result.get("output", {}).get("failed_chapters") or []),
                    "document_count": len(phase_h_result.get("output", {}).get("document_matrix") or []),
                },
            )
        emit("stage_complete", scope="aggregate", stage="phase_h", label=PHASE_LABELS["phase_h"])

        aggregate_output_path = run_ctx.artifacts.aggregate_dir / "output.json"
        aggregate_output = read_json(aggregate_output_path)
        payload = {
            "run_id": run_ctx.run_id,
            "run_dir": str(run_ctx.run_dir),
            "chapter_count": len(chapter_rows),
            "aggregate_status": aggregate_output.get("status"),
            "completed_chapters": aggregate_output.get("completed_chapters"),
            "failed_chapters": aggregate_output.get("failed_chapters"),
            "output_json": str(aggregate_output_path),
            "gpu_used": has_cuda,
            "elapsed_sec": round(time.perf_counter() - t_start, 1),
            "last_completed_phase": "phase_h",
            "document_count": len(aggregate_output.get("document_matrix") or []),
            "useful_pdfs": sum(1 for row in list(aggregate_output.get("document_matrix") or []) if int(row.get("useful_chapter_count") or 0) > 0),
        }
        emit("run_complete", pipeline_run_id=str(run_ctx.run_id), **payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
        return 0
    except Exception as exc:
        emit("run_error", error_type=type(exc).__name__, error_message=str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
