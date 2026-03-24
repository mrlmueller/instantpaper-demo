#!/usr/bin/env python3
"""
A/B pipeline test runner for comparing baseline vs optimized Phase F.

Runs the full pipeline with either:
  --mode baseline   PyTorch cross-encoder, batch_size=8 (original settings)
  --mode optimized  ONNX INT8 cross-encoder, batch_size=32, judge_concurrency=8

Phases A-E are shared (reused from cache). Only Phase F and G are force-rebuilt.
This ensures identical inputs for the reranking comparison.

EXPECTED RUNTIME:
  - Phase B (PDF parsing): 15-90 min depending on PDF count/size
  - Phase E (embeddings): 2-5 min (OpenAI API)
  - Phase F baseline: 15-40 min (cross-encoder + judge)
  - Phase F optimized: ~half of baseline
  - Total for first run (all phases): 30-120 min
  - Total for A/B re-run (F+G only): 15-40 min

Usage:
  python tools/run_ab_test.py --mode baseline --max-pdfs 5
  python tools/run_ab_test.py --mode optimized --max-pdfs 5  (reuses A-E from first run)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

PDF_SCAN_DIR = Path(__file__).resolve().parents[1]
if str(PDF_SCAN_DIR) not in sys.path:
    sys.path.insert(0, str(PDF_SCAN_DIR))

# Load OpenAI API key from fastapi/.env if not already set
FASTAPI_ENV = PDF_SCAN_DIR.parent / "fastapi" / ".env"
if not os.environ.get("OPENAI_API_KEY") and FASTAPI_ENV.exists():
    for line in FASTAPI_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("OPENAI_API_KEY="):
            os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
            break

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


def parse_theme_markdown(path: Path) -> tuple[str, str]:
    raw = path.read_text(encoding="utf-8")
    lines = [line.strip() for line in raw.splitlines()]
    non_empty = [line for line in lines if line]
    if not non_empty:
        raise ValueError(f"Theme file is empty: {path}")
    title = non_empty[0]
    description = "\n\n".join(
        part.strip() for part in raw.split("\n\n") if part.strip()
    )
    if description.startswith(title):
        description = description[len(title) :].strip()
    description = description or title
    return title, description


def update_stage_metrics(run_ctx, stage_name: str, metrics_update: dict) -> None:
    metrics = load_metrics(run_ctx)
    metrics.setdefault("stages", {}).setdefault(stage_name, {}).update(metrics_update)
    save_metrics(run_ctx, metrics)


def fmt_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}min"
    else:
        return f"{seconds / 3600:.1f}h"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="A/B pipeline test: baseline vs optimized Phase F"
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["baseline", "optimized"],
        help="baseline=PyTorch/batch8, optimized=ONNX-INT8/batch32",
    )
    parser.add_argument(
        "--theme-md", default=str(PDF_SCAN_DIR / "tools" / "test_theme_nudging.md")
    )
    parser.add_argument(
        "--pdf-dir", default=str(PDF_SCAN_DIR / "paper-dump" / "Nudging")
    )
    parser.add_argument("--max-pdfs", type=int, default=5)
    parser.add_argument(
        "--reuse-run-id",
        default="",
        help="Re-use phases A-E from this run directory (skip parsing/embedding)",
    )
    parser.add_argument(
        "--skip-to-phase-f",
        action="store_true",
        help="Skip phases A-E, go straight to F+G (requires --reuse-run-id)",
    )
    args = parser.parse_args()

    mode = args.mode
    theme_path = Path(args.theme_md).resolve()
    pdf_dir = Path(args.pdf_dir).resolve()
    chapter_title, chapter_description = parse_theme_markdown(theme_path)

    print(f"\n{'='*70}")
    print(f"  A/B TEST — Mode: {mode.upper()}")
    print(f"  Theme: {chapter_title[:60]}...")
    print(f"  PDFs: {pdf_dir} (max {args.max_pdfs})")
    print(f"{'='*70}\n")

    timings = {}
    total_start = time.time()

    # ─── Phase A ───
    from argparse import Namespace

    phase_a_args = Namespace(
        input_mode="manual",
        pipeline_version="pdf_scan_v3_topic_best",
        force_rebuild=False,
        runs_root="",
        suite_manifest="",
        chapter_index=0,
        doc_limit=None,
        include_doc_id=[],
        exclude_doc_id=[],
        chapter_title=chapter_title,
        chapter_description=chapter_description,
        pdf=[],
        pdf_dir=str(pdf_dir),
        pdf_glob="*.pdf",
        pdf_recursive=False,
        max_pdfs=int(args.max_pdfs),
    )

    t0 = time.time()
    phase_a_result = run_phase_a(phase_a_args)
    run_ctx = phase_a_result["run_ctx"]
    pdf_manifest = phase_a_result["manifest_rows"]
    timings["phase_a"] = time.time() - t0
    print(
        f"[Phase A] {fmt_time(timings['phase_a'])} — {len(pdf_manifest)} PDFs discovered"
    )
    print(f"  Run dir: {run_ctx.run_dir}")

    # If reusing a run, copy phases B-E artifacts
    if args.reuse_run_id:
        source_run = PDF_SCAN_DIR / "runs" / args.reuse_run_id
        if source_run.exists():
            for subdir in ["parser", "normalized", "retrieval"]:
                src = source_run / subdir
                dst = run_ctx.run_dir / subdir
                if src.exists() and not dst.exists():
                    shutil.copytree(str(src), str(dst))
                    print(f"  Reused {subdir}/ from {args.reuse_run_id}")

    if args.skip_to_phase_f:
        if not args.reuse_run_id:
            print("ERROR: --skip-to-phase-f requires --reuse-run-id")
            return 1
        print("  Skipping phases B-E (reusing cached data)")
    else:
        # ─── Phase B ───
        if not (run_ctx.run_dir / "parser" / "phase_b_summary.json").exists():
            print(f"\n[Phase B] Starting PDF parsing ({len(pdf_manifest)} docs)...")
            print(f"  ⚠  EXPECTED: 15-90 min for large PDFs (500+ pages)")
            phase_b_logger = setup_run_logger(run_ctx)
            phase_b_options = PhaseBOptions(
                force_rebuild=False,
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
                grobid_base_url="",
                grobid_process_path="/api/processFulltextDocument",
                grobid_timeout_sec=120,
                grobid_consolidate_header=0,
                grobid_consolidate_citations=0,
                grobid_include_raw_citations=0,
            )
            t0 = time.time()
            with stage_timer(run_ctx, "phase_b"):
                phase_b_result = run_phase_b(
                    run_ctx,
                    pdf_manifest,
                    phase_b_options,
                    stable_hash_fn=stable_hash,
                    log_event_fn=log_event,
                    run_logger=phase_b_logger,
                )
                update_stage_metrics(
                    run_ctx, "phase_b", phase_b_result["metrics_update"]
                )
            timings["phase_b"] = time.time() - t0
            print(f"[Phase B] Done — {fmt_time(timings['phase_b'])}")
        else:
            print("[Phase B] Cached — skipping")

        # ─── Phase C ───
        if not (run_ctx.run_dir / "normalized" / "phase_c_summary.json").exists():
            print("\n[Phase C] Normalizing sections...")
            phase_c_logger = setup_run_logger(run_ctx)
            phase_c_options = PhaseCOptions(
                force_rebuild=False,
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
            t0 = time.time()
            with stage_timer(run_ctx, "phase_c"):
                phase_c_result = run_phase_c(
                    run_ctx,
                    phase_c_options,
                    stable_hash_fn=stable_hash,
                    log_event_fn=log_event,
                    run_logger=phase_c_logger,
                )
                update_stage_metrics(
                    run_ctx, "phase_c", phase_c_result["metrics_update"]
                )
            timings["phase_c"] = time.time() - t0
            print(f"[Phase C] Done — {fmt_time(timings['phase_c'])}")
        else:
            print("[Phase C] Cached — skipping")

        # ─── Phase D ───
        if not (run_ctx.run_dir / "retrieval" / "phase_d_summary.json").exists():
            print("\n[Phase D] Query planning (OpenAI)...")
            phase_d_logger = setup_run_logger(run_ctx)
            phase_d_options = PhaseDOptions(
                force_rebuild=False,
                use_openai_planner=True,
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
            t0 = time.time()
            with stage_timer(run_ctx, "phase_d"):
                phase_d_result = run_phase_d(
                    run_ctx,
                    chapter_title=phase_a_result["config"].chapter_title,
                    chapter_spec_text=phase_a_result["config"].chapter_spec_text,
                    options=phase_d_options,
                    stable_hash_fn=stable_hash,
                    log_event_fn=log_event,
                    run_logger=phase_d_logger,
                )
                update_stage_metrics(
                    run_ctx, "phase_d", phase_d_result["metrics_update"]
                )
            timings["phase_d"] = time.time() - t0
            print(f"[Phase D] Done — {fmt_time(timings['phase_d'])}")
        else:
            print("[Phase D] Cached — skipping")

        # ─── Phase E ───
        if not (run_ctx.run_dir / "retrieval" / "phase_e_summary.json").exists():
            print("\n[Phase E] Dense retrieval (OpenAI embeddings)...")
            phase_e_logger = setup_run_logger(run_ctx)
            phase_e_options = PhaseEOptions(
                force_rebuild=False,
                candidate_limit_per_lane=160,
                fused_candidate_limit=260,
                per_view_limit_multiplier=4,
                rrf_k=60,
                lexical_k1=1.2,
                lexical_b=0.75,
                use_openai_dense=True,
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
            t0 = time.time()
            with stage_timer(run_ctx, "phase_e"):
                phase_e_result = run_phase_e(
                    run_ctx,
                    options=phase_e_options,
                    stable_hash_fn=stable_hash,
                    log_event_fn=log_event,
                    run_logger=phase_e_logger,
                )
                update_stage_metrics(
                    run_ctx, "phase_e", phase_e_result["metrics_update"]
                )
            timings["phase_e"] = time.time() - t0
            print(f"[Phase E] Done — {fmt_time(timings['phase_e'])}")
        else:
            print("[Phase E] Cached — skipping")

    # ─── Phase F (the A/B comparison target) ───
    print(f"\n[Phase F] Reranking — mode={mode.upper()}")
    phase_f_logger = setup_run_logger(run_ctx)

    if mode == "baseline":
        phase_f_options = PhaseFOptions(
            force_rebuild=True,
            rerank_top_k=140,
            inject_doc_top_candidates=True,
            cross_encoder_model="BAAI/bge-reranker-v2-m3",
            cross_encoder_batch_size=8,
            cross_encoder_max_length=1536,
            cross_encoder_prefer_onnx=False,  # PyTorch only
            cross_encoder_subpoint_limit=2,
            section_excerpt_max_chars=2200,
            supporting_passage_count=3,
            passage_excerpt_max_chars=520,
            use_openai_judge=True,
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
            judge_max_concurrency=4,  # Original default
        )
    else:  # optimized
        phase_f_options = PhaseFOptions(
            force_rebuild=True,
            rerank_top_k=140,
            inject_doc_top_candidates=True,
            cross_encoder_model="BAAI/bge-reranker-v2-m3",
            cross_encoder_batch_size=32,  # ← increased
            cross_encoder_max_length=1536,
            cross_encoder_prefer_onnx=True,  # ← ONNX INT8
            cross_encoder_subpoint_limit=2,
            section_excerpt_max_chars=2200,  # ← SAME as baseline
            supporting_passage_count=3,
            passage_excerpt_max_chars=520,  # ← SAME as baseline
            use_openai_judge=True,
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
            judge_max_concurrency=8,  # ← increased
        )

    t0 = time.time()
    with stage_timer(run_ctx, "phase_f"):
        phase_f_result = run_phase_f(
            run_ctx,
            options=phase_f_options,
            stable_hash_fn=stable_hash,
            log_event_fn=log_event,
            run_logger=phase_f_logger,
        )
        update_stage_metrics(run_ctx, "phase_f", phase_f_result["metrics_update"])
    timings["phase_f"] = time.time() - t0
    print(f"[Phase F] Done — {fmt_time(timings['phase_f'])}")

    # ─── Phase G ───
    print("\n[Phase G] Final scoring...")
    phase_g_logger = setup_run_logger(run_ctx)
    phase_g_options = PhaseGOptions(
        force_rebuild=True,
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
    t0 = time.time()
    with stage_timer(run_ctx, "phase_g"):
        phase_g_result = run_phase_g(
            run_ctx,
            options=phase_g_options,
            stable_hash_fn=stable_hash,
            log_event_fn=log_event,
            run_logger=phase_g_logger,
        )
        update_stage_metrics(run_ctx, "phase_g", phase_g_result["metrics_update"])
    timings["phase_g"] = time.time() - t0
    print(f"[Phase G] Done — {fmt_time(timings['phase_g'])}")

    total_time = time.time() - total_start

    # ─── Summary ───
    print(f"\n{'='*70}")
    print(f"  RUN COMPLETE — Mode: {mode.upper()}")
    print(f"  Run ID: {run_ctx.run_id}")
    print(f"  Run dir: {run_ctx.run_dir}")
    print(f"  Total: {fmt_time(total_time)}")
    print(f"{'='*70}")
    print("\n  Phase timings:")
    for phase, t in sorted(timings.items()):
        print(f"    {phase}: {fmt_time(t)}")

    # Save summary for later comparison
    summary = {
        "mode": mode,
        "run_id": run_ctx.run_id,
        "run_dir": str(run_ctx.run_dir),
        "total_seconds": total_time,
        "timings": timings,
        "pdf_count": len(pdf_manifest),
        "pdf_dir": str(pdf_dir),
        "chapter_title": chapter_title,
    }
    out_file = PDF_SCAN_DIR / "tools" / f"ab_test_{mode}.json"
    out_file.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n  Summary saved: {out_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
