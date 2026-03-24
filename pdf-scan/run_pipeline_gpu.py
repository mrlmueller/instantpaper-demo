#!/usr/bin/env python3
"""
GPU Pipeline Runner — Phases F and G.

This script runs the GPU-accelerated portion of the PDF scan pipeline.
It resumes from an existing run directory produced by run_pipeline_cpu.py.

The cross-encoder model (BAAI/bge-reranker-v2-m3) automatically uses CUDA
when available, providing ~80x speedup over CPU.

Usage:
    python run_pipeline_gpu.py --run-dir path/to/runs/{run_id}

    # With custom options:
    python run_pipeline_gpu.py --run-dir path/to/runs/{run_id} \
        --cross-encoder-batch-size 64 \
        --no-openai-judge

Prerequisites:
    - Phases A-E must have completed (run_pipeline_cpu.py)
    - PyTorch with CUDA support for GPU acceleration
    - OpenAI API key in environment for the LLM judge (Phase F)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PDF_SCAN_DIR = Path(__file__).resolve().parent
if str(PDF_SCAN_DIR) not in sys.path:
    sys.path.insert(0, str(PDF_SCAN_DIR))

from phase_a_lab import (
    RunArtifacts,
    RunContext,
    load_metrics,
    log_event,
    save_metrics,
    setup_run_logger,
    stable_hash,
    stage_timer,
)
from phase_f_lab import PhaseFOptions, run_phase_f
from phase_g_lab import PhaseGOptions, run_phase_g


def update_stage_metrics(
    run_ctx: Any, stage_name: str, metrics_update: dict[str, Any]
) -> None:
    metrics = load_metrics(run_ctx)
    metrics.setdefault("stages", {}).setdefault(stage_name, {}).update(metrics_update)
    save_metrics(run_ctx, metrics)


def reconstruct_run_ctx(run_dir: Path) -> RunContext:
    """Reconstruct a RunContext from an existing run directory.

    This allows the GPU runner to resume from where the CPU runner left off,
    without needing to re-run Phase A.
    """
    run_dir = run_dir.resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    # Verify required CPU phase outputs exist
    required_files = [
        run_dir / "config.json",
        run_dir / "normalized" / "sections.jsonl",
        run_dir / "retrieval" / "fused_candidates.jsonl",
        run_dir / "query_plan.json",
    ]
    missing = [str(f) for f in required_files if not f.exists()]
    if missing:
        raise FileNotFoundError(
            f"CPU phases incomplete. Missing files:\n"
            + "\n".join(f"  - {f}" for f in missing)
            + "\n\nRun run_pipeline_cpu.py first."
        )

    run_id = run_dir.name
    artifacts = RunArtifacts.from_run_dir(run_dir)

    # Determine repo_root and pdf_scan_dir from the run directory location
    # Runs are stored under pdf-scan/runs/ or a custom runs_root
    pdf_scan_dir = PDF_SCAN_DIR
    repo_root = pdf_scan_dir.parent

    return RunContext(
        repo_root=repo_root,
        pdf_scan_dir=pdf_scan_dir,
        run_id=run_id,
        run_dir=run_dir,
        artifacts=artifacts,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run GPU phases (F+G) of the PDF scan pipeline."
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Path to existing run directory from CPU pipeline.",
    )
    parser.add_argument("--force-rebuild-phase-f", action="store_true")
    parser.add_argument("--force-rebuild-phase-g", action="store_true")
    parser.add_argument("--no-openai-judge", action="store_true")
    parser.add_argument(
        "--cross-encoder-batch-size",
        type=int,
        default=8,
        help="Batch size for cross-encoder. Use 64+ on GPU.",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()

    # Check for GPU
    try:
        import torch

        has_cuda = torch.cuda.is_available()
        if has_cuda:
            gpu_name = torch.cuda.get_device_name(0)
            print(f"GPU: {gpu_name} (CUDA {torch.version.cuda})")
        else:
            print("WARNING: No CUDA GPU detected. Running on CPU (will be slow).")
    except ImportError:
        has_cuda = False
        print("WARNING: PyTorch not installed. Cross-encoder will fail.")

    # Reconstruct run context
    run_ctx = reconstruct_run_ctx(run_dir)
    print(f"Run ID: {run_ctx.run_id}")
    print(f"Run dir: {run_ctx.run_dir}")

    # Auto-tune batch size for GPU based on VRAM and sequence length
    batch_size = args.cross_encoder_batch_size
    if has_cuda and batch_size <= 8:
        import torch

        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        max_length = 1536  # cross_encoder_max_length default
        # FP32 XLM-RoBERTa attention: ~(batch * seq^2 * layers * heads * 4 bytes)
        # Empirical safe limits per VRAM tier at max_length=1536:
        #   10 GB (RTX 3080): batch_size=8
        #   16 GB (RTX 4080/A4000): batch_size=16
        #   24 GB (L4/RTX 3090/4090): batch_size=32
        if vram_gb >= 20:
            batch_size = 32
        elif vram_gb >= 14:
            batch_size = 16
        else:
            batch_size = 8
        print(
            f"Auto-tuned batch size to {batch_size} for GPU ({vram_gb:.0f} GB VRAM, max_length={max_length})"
        )

    t_start = time.perf_counter()

    # ── Phase F: Cross-encoder Reranking + LLM Judge ────────────────────
    if (
        bool(args.force_rebuild_phase_f)
        or not (run_ctx.run_dir / "rerank" / "phase_f_summary.json").exists()
    ):
        phase_f_logger = setup_run_logger(run_ctx)
        phase_f_options = PhaseFOptions(
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
        with stage_timer(run_ctx, "phase_f"):
            phase_f_result = run_phase_f(
                run_ctx,
                options=phase_f_options,
                stable_hash_fn=stable_hash,
                log_event_fn=log_event,
                run_logger=phase_f_logger,
            )
            update_stage_metrics(run_ctx, "phase_f", phase_f_result["metrics_update"])
        print(f"[Phase F] Reranking complete")
    else:
        print(f"[Phase F] Cached")

    # ── Phase G: Final Scoring ──────────────────────────────────────────
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
            log_event_fn=log_event,
            run_logger=phase_g_logger,
        )
        update_stage_metrics(run_ctx, "phase_g", phase_g_result["metrics_update"])
    print(f"[Phase G] Final scoring complete")

    elapsed = time.perf_counter() - t_start
    useful = len(
        [
            r
            for r in phase_g_result["doc_feature_rows"]
            if r.get("has_useful_information")
        ]
    )
    total = len(phase_g_result["doc_feature_rows"])

    print(f"\n{'='*60}")
    print(f"  GPU PIPELINE COMPLETE")
    print(f"  Elapsed: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print(f"  Useful PDFs: {useful}/{total}")
    print(f"  Output: {run_ctx.artifacts.final_dir / 'output.json'}")
    print(f"{'='*60}")

    payload = {
        "run_id": run_ctx.run_id,
        "run_dir": str(run_ctx.run_dir),
        "useful_pdfs": useful,
        "document_count": total,
        "output_json": str(run_ctx.artifacts.final_dir / "output.json"),
        "gpu_used": has_cuda,
        "elapsed_sec": round(elapsed, 1),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
