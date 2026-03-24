#!/usr/bin/env python3
"""
CPU Pipeline Runner — Phases A through E.

This script runs the CPU-only portion of the PDF scan pipeline.
It produces all artifacts needed by the GPU pipeline (phases F+G).

Usage:
    python run_pipeline_cpu.py \
        --theme-md path/to/theme.md \
        --pdf-dir path/to/pdfs/ \
        [--max-pdfs 100] \
        [--grobid-base-url http://localhost:8070]

Output:
    Creates a run directory under pdf-scan/runs/{run_id}/ with:
      - config.json, pdf_manifest.json
      - parser/          (Phase B output)
      - normalized/      (Phase C output)
      - retrieval/       (Phases D+E output)
    Prints the run_dir path on completion for the GPU runner to pick up.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from argparse import Namespace
from pathlib import Path
from typing import Any

PDF_SCAN_DIR = Path(__file__).resolve().parents[1]
if str(PDF_SCAN_DIR) not in sys.path:
    sys.path.insert(0, str(PDF_SCAN_DIR))

from phase_a_lab import (
    load_metrics,
    log_event,
    save_metrics,
    setup_run_logger,
    stable_hash,
    stage_timer,
)
from phase_a_lab import run_phase_a
from phase_b_lab import PhaseBOptions, run_phase_b
from phase_c_lab import PhaseCOptions, run_phase_c
from phase_d_lab import PhaseDOptions, run_phase_d
from phase_e_lab import PhaseEOptions, run_phase_e


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


def update_stage_metrics(
    run_ctx: Any, stage_name: str, metrics_update: dict[str, Any]
) -> None:
    metrics = load_metrics(run_ctx)
    metrics.setdefault("stages", {}).setdefault(stage_name, {}).update(metrics_update)
    save_metrics(run_ctx, metrics)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run CPU phases (A-E) of the PDF scan pipeline."
    )
    parser.add_argument(
        "--theme-md", required=True, help="Path to the topic Text Thema.md file."
    )
    parser.add_argument(
        "--pdf-dir", required=True, help="Directory containing the PDFs."
    )
    parser.add_argument("--pipeline-version", default="pdf_scan_v3_topic_best")
    parser.add_argument("--pdf-glob", default="*.pdf")
    parser.add_argument("--pdf-recursive", action="store_true")
    parser.add_argument("--max-pdfs", type=int, default=100)
    parser.add_argument("--grobid-base-url", default="")
    parser.add_argument("--no-openai-planner", action="store_true")
    parser.add_argument("--no-openai-dense", action="store_true")
    parser.add_argument("--force-rebuild-phase-a", action="store_true")
    parser.add_argument("--force-rebuild-phase-b", action="store_true")
    parser.add_argument("--force-rebuild-phase-c", action="store_true")
    parser.add_argument("--force-rebuild-phase-d", action="store_true")
    parser.add_argument("--force-rebuild-phase-e", action="store_true")
    args = parser.parse_args()

    theme_path = Path(args.theme_md).resolve()
    pdf_dir = Path(args.pdf_dir).resolve()
    chapter_title, chapter_description = parse_theme_markdown(theme_path)

    t_start = time.perf_counter()

    # ── Phase A: Discovery ──────────────────────────────────────────────
    phase_a_args = Namespace(
        input_mode="manual",
        pipeline_version=str(args.pipeline_version or "pdf_scan_v3_topic_best"),
        force_rebuild=bool(args.force_rebuild_phase_a),
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
        pdf_glob=str(args.pdf_glob or "*.pdf"),
        pdf_recursive=bool(args.pdf_recursive),
        max_pdfs=int(args.max_pdfs),
    )
    phase_a_result = run_phase_a(phase_a_args)
    run_ctx = phase_a_result["run_ctx"]
    pdf_manifest = phase_a_result["manifest_rows"]
    print(f"[Phase A] {len(pdf_manifest)} PDFs — run_id={run_ctx.run_id}")
    print(f"  run_dir: {run_ctx.run_dir}")

    # ── Phase B: PDF Parsing ────────────────────────────────────────────
    if (
        bool(args.force_rebuild_phase_b)
        or not (run_ctx.run_dir / "parser" / "phase_b_summary.json").exists()
    ):
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
                log_event_fn=log_event,
                run_logger=phase_b_logger,
            )
            update_stage_metrics(run_ctx, "phase_b", phase_b_result["metrics_update"])
        print(f"[Phase B] PDF parsing complete")
    else:
        print(f"[Phase B] Cached")

    # ── Phase C: Normalization ──────────────────────────────────────────
    if (
        bool(args.force_rebuild_phase_c)
        or not (run_ctx.run_dir / "normalized" / "phase_c_summary.json").exists()
    ):
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
                log_event_fn=log_event,
                run_logger=phase_c_logger,
            )
            update_stage_metrics(run_ctx, "phase_c", phase_c_result["metrics_update"])
        print(f"[Phase C] Normalization complete")
    else:
        print(f"[Phase C] Cached")

    # ── Phase D: Query Planning ─────────────────────────────────────────
    if (
        bool(args.force_rebuild_phase_d)
        or not (run_ctx.run_dir / "retrieval" / "phase_d_summary.json").exists()
    ):
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
                log_event_fn=log_event,
                run_logger=phase_d_logger,
            )
            update_stage_metrics(run_ctx, "phase_d", phase_d_result["metrics_update"])
        print(f"[Phase D] Query planning complete")
    else:
        print(f"[Phase D] Cached")

    # ── Phase E: Retrieval ──────────────────────────────────────────────
    if (
        bool(args.force_rebuild_phase_e)
        or not (run_ctx.run_dir / "retrieval" / "phase_e_summary.json").exists()
    ):
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
                log_event_fn=log_event,
                run_logger=phase_e_logger,
            )
            update_stage_metrics(run_ctx, "phase_e", phase_e_result["metrics_update"])
        print(f"[Phase E] Retrieval complete")
    else:
        print(f"[Phase E] Cached")

    elapsed = time.perf_counter() - t_start
    print(f"\n{'='*60}")
    print(f"  CPU PIPELINE COMPLETE")
    print(f"  Elapsed: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print(f"  Run dir: {run_ctx.run_dir}")
    print(f"{'='*60}")
    print(f"\nTo run GPU phases (F+G):")
    print(f'  python run_pipeline_gpu.py --run-dir "{run_ctx.run_dir}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
