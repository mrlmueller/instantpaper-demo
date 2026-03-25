#!/usr/bin/env python3
"""
GPU Pipeline Runner — chapter-aware Phases F, G, and aggregate H.

This resumes an existing run directory produced by run_pipeline_cpu.py.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

PDF_SCAN_DIR = Path(__file__).resolve().parent
if str(PDF_SCAN_DIR) not in sys.path:
    sys.path.insert(0, str(PDF_SCAN_DIR))

from phase_a_lab import (
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
from phase_f_lab import PhaseFOptions, run_phase_f
from phase_g_lab import PhaseGOptions, run_phase_g
from phase_h_lab import PhaseHOptions, run_phase_h


def update_stage_metrics(run_ctx: Any, stage_name: str, metrics_update: Dict[str, Any]) -> None:
    metrics = load_metrics(run_ctx)
    metrics.setdefault("stages", {}).setdefault(stage_name, {}).update(metrics_update)
    save_metrics(run_ctx, metrics)


def update_chapter_stage_metrics(run_ctx: Any, chapter_id: str, stage_name: str, metrics_update: Dict[str, Any]) -> None:
    metrics = load_metrics(run_ctx)
    chapter_metrics = metrics.setdefault("chapters", {}).setdefault(chapter_id, {})
    chapter_metrics.setdefault("stages", {}).setdefault(stage_name, {}).update(metrics_update)
    save_metrics(run_ctx, metrics)


def reconstruct_run_ctx(run_dir: Path) -> tuple[RunContext, Dict[str, Any]]:
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
            repo_root=PDF_SCAN_DIR.parent,
            pdf_scan_dir=PDF_SCAN_DIR,
            run_id=run_dir.name,
            run_dir=run_dir,
            artifacts=artifacts,
        ),
        config,
    )


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
    chapter: Dict[str, Any],
    phase_f_options: PhaseFOptions,
    phase_g_options: PhaseGOptions,
    run_logger: Any,
) -> Dict[str, Any]:
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
    log_event(run_ctx, stage="phase_fg", event="chapter_started", chapter_id=chapter_id, chapter_title=chapter_title)
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
        log_event(
            run_ctx,
            stage="phase_fg",
            event="chapter_finished",
            chapter_id=chapter_id,
            chapter_title=chapter_title,
            status="success",
            elapsed_sec=elapsed,
            useful_pdf_count=useful_docs,
        )
        return {
            "chapter_id": chapter_id,
            "chapter_title": chapter_title,
            "status": "success",
            "elapsed_sec": elapsed,
            "useful_pdf_count": useful_docs,
            "phase_f_metrics_update": phase_f_result.get("metrics_update") or {},
            "phase_g_metrics_update": phase_g_result.get("metrics_update") or {},
        }
    except Exception as exc:
        elapsed = round(time.perf_counter() - started, 3)
        log_event(
            run_ctx,
            stage="phase_fg",
            event="chapter_failed",
            chapter_id=chapter_id,
            chapter_title=chapter_title,
            status="failed",
            elapsed_sec=elapsed,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return {
            "chapter_id": chapter_id,
            "chapter_title": chapter_title,
            "status": "failed",
            "elapsed_sec": elapsed,
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run GPU phases (F+G+H) of the PDF scan pipeline.")
    parser.add_argument("--run-dir", required=True, help="Path to existing run directory from CPU pipeline.")
    parser.add_argument("--force-rebuild-phase-f", action="store_true")
    parser.add_argument("--force-rebuild-phase-g", action="store_true")
    parser.add_argument("--force-rebuild-phase-h", action="store_true")
    parser.add_argument("--no-openai-judge", action="store_true")
    parser.add_argument("--cross-encoder-batch-size", type=int, default=8, help="Batch size for cross-encoder. Use 32 on larger GPUs.")
    parser.add_argument("--max-gpu-chapter-concurrency", type=int, default=1)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    has_cuda = False
    try:
        import torch

        has_cuda = torch.cuda.is_available()
        if has_cuda:
            gpu_name = torch.cuda.get_device_name(0)
            print(f"GPU: {gpu_name} (CUDA {torch.version.cuda})")
        else:
            print("WARNING: No CUDA GPU detected. Running on CPU (slow).")
    except ImportError:
        print("WARNING: PyTorch not installed. Cross-encoder will fail.")

    run_ctx, config = reconstruct_run_ctx(run_dir)
    run_logger = setup_run_logger(run_ctx)
    print(f"Run ID: {run_ctx.run_id}")
    print(f"Run dir: {run_ctx.run_dir}")

    batch_size = args.cross_encoder_batch_size
    if has_cuda and batch_size <= 8:
        import torch

        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        if vram_gb >= 20:
            batch_size = 32
        elif vram_gb >= 14:
            batch_size = 16
        else:
            batch_size = 8
        print(f"Auto-tuned batch size to {batch_size} for GPU ({vram_gb:.0f} GB VRAM)")

    phase_f_options = build_phase_f_options(args, batch_size=batch_size)
    phase_g_options = build_phase_g_options(args)
    chapter_rows: List[Dict[str, Any]] = list(config.get("chapters") or [])
    t_start = time.perf_counter()

    if int(args.max_gpu_chapter_concurrency) > 1:
        print("WARNING: max-gpu-chapter-concurrency > 1 is experimental; current runner still executes chapters serially.")

    chapter_results: Dict[str, Dict[str, Any]] = {}
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

    elapsed = time.perf_counter() - t_start
    aggregate_output_path = run_ctx.artifacts.aggregate_dir / "output.json"
    aggregate_output = read_json(aggregate_output_path)

    print(f"\n{'=' * 60}")
    print("  GPU PIPELINE COMPLETE")
    print(f"  Elapsed: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print(f"  Aggregate status: {aggregate_output.get('status')}")
    print(f"  Output: {aggregate_output_path}")
    print(f"{'=' * 60}")

    payload = {
        "run_id": run_ctx.run_id,
        "run_dir": str(run_ctx.run_dir),
        "chapter_count": len(chapter_rows),
        "aggregate_status": aggregate_output.get("status"),
        "completed_chapters": aggregate_output.get("completed_chapters"),
        "failed_chapters": aggregate_output.get("failed_chapters"),
        "output_json": str(aggregate_output_path),
        "gpu_used": has_cuda,
        "elapsed_sec": round(elapsed, 1),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
