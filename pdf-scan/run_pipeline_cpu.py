#!/usr/bin/env python3
"""
CPU Pipeline Runner — shared Phases A-C plus chapter-parallel D/E.

This runner supports:
- single chapter via --theme-md
- multi chapter via --chapters-dir

Artifacts are written into the chapter-aware run layout under runs/<run_id>/.
The GPU runner resumes the same run for chapter-local F/G and aggregate H.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

PDF_SCAN_DIR = Path(__file__).resolve().parent
if str(PDF_SCAN_DIR) not in sys.path:
    sys.path.insert(0, str(PDF_SCAN_DIR))

from phase_a_lab import (
    load_metrics,
    log_event,
    read_json,
    save_metrics,
    setup_run_logger,
    stable_hash,
    stage_timer,
    write_json,
)
from phase_a_lab import run_phase_a
from phase_b_lab import PhaseBOptions, run_phase_b
from phase_c_lab import PhaseCOptions, run_phase_c
from phase_d_lab import PhaseDOptions, run_phase_d
from phase_e_lab import PhaseEOptions, prepare_phase_e_shared_dense_cache, run_phase_e


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
    return title, description or title


def update_stage_metrics(run_ctx: Any, stage_name: str, metrics_update: Dict[str, Any]) -> None:
    metrics = load_metrics(run_ctx)
    metrics.setdefault("stages", {}).setdefault(stage_name, {}).update(metrics_update)
    save_metrics(run_ctx, metrics)


def update_chapter_stage_metrics(run_ctx: Any, chapter_id: str, stage_name: str, metrics_update: Dict[str, Any]) -> None:
    metrics = load_metrics(run_ctx)
    chapter_metrics = metrics.setdefault("chapters", {}).setdefault(chapter_id, {})
    chapter_metrics.setdefault("stages", {}).setdefault(stage_name, {}).update(metrics_update)
    save_metrics(run_ctx, metrics)


def build_phase_d_options(args: argparse.Namespace) -> PhaseDOptions:
    return PhaseDOptions(
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


def build_phase_e_options(args: argparse.Namespace) -> PhaseEOptions:
    return PhaseEOptions(
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
        use_shared_dense_cache=True,
    )


def _run_phase_d_for_chapter(
    run_ctx: Any,
    *,
    chapter: Any,
    options: PhaseDOptions,
    run_logger: Any,
) -> Dict[str, Any]:
    chapter_ctx = run_ctx.for_chapter(chapter.chapter_id)
    phase_d_summary_path = Path(chapter_ctx.artifacts.retrieval_dir) / "phase_d_summary.json"
    if not bool(options.force_rebuild) and phase_d_summary_path.exists():
        return {
            "chapter_id": chapter.chapter_id,
            "chapter_title": chapter.chapter_title,
            "status": "cached",
            "elapsed_sec": 0.0,
            "metrics_update": dict((read_json(phase_d_summary_path).get("metrics_update") or {})),
            "summary": read_json(phase_d_summary_path),
        }

    started = time.perf_counter()
    log_event(
        run_ctx,
        stage="phase_d",
        event="chapter_started",
        chapter_id=chapter.chapter_id,
        chapter_title=chapter.chapter_title,
    )
    try:
        result = run_phase_d(
            chapter_ctx,
            chapter_title=chapter.chapter_title,
            chapter_spec_text=chapter.chapter_spec_text,
            options=options,
            stable_hash_fn=stable_hash,
            log_event_fn=log_event,
            run_logger=run_logger,
        )
        elapsed = round(time.perf_counter() - started, 3)
        update_chapter_stage_metrics(run_ctx, chapter.chapter_id, "phase_d", result.get("metrics_update") or {})
        log_event(
            run_ctx,
            stage="phase_d",
            event="chapter_finished",
            chapter_id=chapter.chapter_id,
            chapter_title=chapter.chapter_title,
            elapsed_sec=elapsed,
            status="success",
        )
        return {
            "chapter_id": chapter.chapter_id,
            "chapter_title": chapter.chapter_title,
            "status": "success",
            "elapsed_sec": elapsed,
            "metrics_update": result.get("metrics_update") or {},
            "summary": result.get("summary") or {},
        }
    except Exception as exc:
        elapsed = round(time.perf_counter() - started, 3)
        log_event(
            run_ctx,
            stage="phase_d",
            event="chapter_failed",
            chapter_id=chapter.chapter_id,
            chapter_title=chapter.chapter_title,
            elapsed_sec=elapsed,
            status="failed",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return {
            "chapter_id": chapter.chapter_id,
            "chapter_title": chapter.chapter_title,
            "status": "failed",
            "elapsed_sec": elapsed,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _run_phase_e_for_chapter(
    run_ctx: Any,
    *,
    chapter: Any,
    options: PhaseEOptions,
    run_logger: Any,
) -> Dict[str, Any]:
    chapter_ctx = run_ctx.for_chapter(chapter.chapter_id)
    phase_e_summary_path = Path(chapter_ctx.artifacts.retrieval_dir) / "phase_e_summary.json"
    if not bool(options.force_rebuild) and phase_e_summary_path.exists():
        return {
            "chapter_id": chapter.chapter_id,
            "chapter_title": chapter.chapter_title,
            "status": "cached",
            "elapsed_sec": 0.0,
            "metrics_update": dict((read_json(phase_e_summary_path).get("metrics_update") or {})),
            "summary": read_json(phase_e_summary_path),
        }

    started = time.perf_counter()
    log_event(
        run_ctx,
        stage="phase_e",
        event="chapter_started",
        chapter_id=chapter.chapter_id,
        chapter_title=chapter.chapter_title,
    )
    try:
        result = run_phase_e(
            chapter_ctx,
            options=options,
            stable_hash_fn=stable_hash,
            log_event_fn=log_event,
            run_logger=run_logger,
        )
        elapsed = round(time.perf_counter() - started, 3)
        update_chapter_stage_metrics(run_ctx, chapter.chapter_id, "phase_e", result.get("metrics_update") or {})
        log_event(
            run_ctx,
            stage="phase_e",
            event="chapter_finished",
            chapter_id=chapter.chapter_id,
            chapter_title=chapter.chapter_title,
            elapsed_sec=elapsed,
            status="success",
        )
        return {
            "chapter_id": chapter.chapter_id,
            "chapter_title": chapter.chapter_title,
            "status": "success",
            "elapsed_sec": elapsed,
            "metrics_update": result.get("metrics_update") or {},
            "summary": result.get("summary") or {},
        }
    except Exception as exc:
        elapsed = round(time.perf_counter() - started, 3)
        log_event(
            run_ctx,
            stage="phase_e",
            event="chapter_failed",
            chapter_id=chapter.chapter_id,
            chapter_title=chapter.chapter_title,
            elapsed_sec=elapsed,
            status="failed",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return {
            "chapter_id": chapter.chapter_id,
            "chapter_title": chapter.chapter_title,
            "status": "failed",
            "elapsed_sec": elapsed,
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_parallel_chapter_stage(
    run_ctx: Any,
    *,
    chapters: List[Any],
    max_workers: int,
    submit_fn,
) -> Dict[str, Dict[str, Any]]:
    if not chapters:
        return {}
    if len(chapters) == 1 or max_workers <= 1:
        result = submit_fn(chapters[0])
        return {chapters[0].chapter_id: result}

    out: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(submit_fn, chapter): chapter for chapter in chapters}
        for future in as_completed(futures):
            chapter = futures[future]
            out[chapter.chapter_id] = future.result()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CPU phases (A-E) of the PDF scan pipeline.")
    chapter_group = parser.add_mutually_exclusive_group(required=True)
    chapter_group.add_argument("--theme-md", help="Path to a single topic markdown file.")
    chapter_group.add_argument("--chapters-dir", help="Directory containing one markdown file per chapter.")
    parser.add_argument("--pdf-dir", required=True, help="Directory containing the PDFs.")
    parser.add_argument("--pipeline-version", default="pdf_scan_v3_parallel_topic")
    parser.add_argument("--pdf-glob", default="*.pdf")
    parser.add_argument("--pdf-recursive", action="store_true")
    parser.add_argument("--max-pdfs", type=int, default=100)
    parser.add_argument("--grobid-base-url", default="")
    parser.add_argument("--no-openai-planner", action="store_true")
    parser.add_argument("--no-openai-dense", action="store_true")
    parser.add_argument("--max-cpu-chapter-concurrency", type=int, default=3)
    parser.add_argument("--force-rebuild-phase-a", action="store_true")
    parser.add_argument("--force-rebuild-phase-b", action="store_true")
    parser.add_argument("--force-rebuild-phase-c", action="store_true")
    parser.add_argument("--force-rebuild-phase-d", action="store_true")
    parser.add_argument("--force-rebuild-phase-e", action="store_true")
    args = parser.parse_args()

    theme_path = Path(args.theme_md).resolve() if args.theme_md else None
    chapters_dir = Path(args.chapters_dir).resolve() if args.chapters_dir else None
    pdf_dir = Path(args.pdf_dir).resolve()

    chapter_title = ""
    chapter_description = ""
    if theme_path is not None:
        chapter_title, chapter_description = parse_theme_markdown(theme_path)

    t_start = time.perf_counter()
    phase_a_args = Namespace(
        input_mode="manual",
        pipeline_version=str(args.pipeline_version or "pdf_scan_v3_parallel_topic"),
        force_rebuild=bool(args.force_rebuild_phase_a),
        runs_root="",
        suite_manifest="",
        chapter_index=0,
        doc_limit=None,
        include_doc_id=[],
        exclude_doc_id=[],
        chapter_title=chapter_title,
        chapter_description=chapter_description,
        chapters_dir=str(chapters_dir) if chapters_dir else "",
        pdf=[],
        pdf_dir=str(pdf_dir),
        pdf_glob=str(args.pdf_glob or "*.pdf"),
        pdf_recursive=bool(args.pdf_recursive),
        max_pdfs=int(args.max_pdfs),
    )
    phase_a_result = run_phase_a(phase_a_args)
    run_ctx = phase_a_result["run_ctx"]
    config = phase_a_result["config"]
    pdf_manifest = phase_a_result["manifest_rows"]
    run_logger = setup_run_logger(run_ctx)

    print(f"[Phase A] {len(pdf_manifest)} PDFs — run_id={run_ctx.run_id}")
    print(f"  run_dir: {run_ctx.run_dir}")
    print(f"  chapters: {len(config.chapters)}")

    if bool(args.force_rebuild_phase_b) or not (run_ctx.run_dir / "parser" / "phase_b_summary.json").exists():
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
                run_logger=run_logger,
            )
            update_stage_metrics(run_ctx, "phase_b", phase_b_result["metrics_update"])
        print("[Phase B] PDF parsing complete")
    else:
        print("[Phase B] Cached")

    if bool(args.force_rebuild_phase_c) or not (run_ctx.run_dir / "normalized" / "phase_c_summary.json").exists():
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
                run_logger=run_logger,
            )
            update_stage_metrics(run_ctx, "phase_c", phase_c_result["metrics_update"])
        print("[Phase C] Normalization complete")
    else:
        print("[Phase C] Cached")

    phase_d_options = build_phase_d_options(args)
    phase_e_options = build_phase_e_options(args)
    max_workers = max(1, min(int(args.max_cpu_chapter_concurrency), len(config.chapters)))
    chapter_lookup = {chapter.chapter_id: chapter for chapter in config.chapters}

    with stage_timer(run_ctx, "phase_d_parallel"):
        phase_d_results = run_parallel_chapter_stage(
            run_ctx,
            chapters=config.chapters,
            max_workers=max_workers,
            submit_fn=lambda chapter: _run_phase_d_for_chapter(
                run_ctx,
                chapter=chapter,
                options=phase_d_options,
                run_logger=run_logger,
            ),
        )
        d_success = sum(1 for row in phase_d_results.values() if row.get("status") in {"success", "cached"})
        d_failed = len(phase_d_results) - d_success
        update_stage_metrics(
            run_ctx,
            "phase_d_parallel",
            {
                "chapter_count": len(config.chapters),
                "successful_chapters": d_success,
                "failed_chapters": d_failed,
                "max_workers": max_workers,
            },
        )
    print(f"[Phase D] complete — success={d_success} failed={d_failed}")

    if phase_e_options.use_shared_dense_cache and phase_e_options.use_openai_dense and d_success:
        with stage_timer(run_ctx, "phase_c5_shared_dense_cache"):
            shared_cache_summary = prepare_phase_e_shared_dense_cache(
                run_ctx,
                options=phase_e_options,
                force_rebuild=bool(args.force_rebuild_phase_e),
            )
            update_stage_metrics(
                run_ctx,
                "phase_c5_shared_dense_cache",
                {
                    "status": "success",
                    "embedding_model": shared_cache_summary.get("model_used"),
                    "section_count": shared_cache_summary.get("section_count"),
                    "passage_count": shared_cache_summary.get("passage_count"),
                    "embedding_cost_usd": ((shared_cache_summary.get("cost") or {}).get("estimated_cost_usd")),
                },
            )
        print("[Phase C.5] Shared dense cache ready")

    chapters_for_e = [
        chapter_lookup[chapter_id]
        for chapter_id, row in phase_d_results.items()
        if row.get("status") in {"success", "cached"} and chapter_id in chapter_lookup
    ]
    with stage_timer(run_ctx, "phase_e_parallel"):
        phase_e_results = run_parallel_chapter_stage(
            run_ctx,
            chapters=chapters_for_e,
            max_workers=max_workers,
            submit_fn=lambda chapter: _run_phase_e_for_chapter(
                run_ctx,
                chapter=chapter,
                options=phase_e_options,
                run_logger=run_logger,
            ),
        )
        e_success = sum(1 for row in phase_e_results.values() if row.get("status") in {"success", "cached"})
        e_failed = len(chapters_for_e) - e_success
        update_stage_metrics(
            run_ctx,
            "phase_e_parallel",
            {
                "chapter_count": len(chapters_for_e),
                "successful_chapters": e_success,
                "failed_chapters": e_failed,
                "max_workers": max_workers,
            },
        )
    print(f"[Phase E] complete — success={e_success} failed={e_failed}")

    cpu_summary = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_id": run_ctx.run_id,
        "status": "success" if e_success == len(config.chapters) else ("partial_success" if e_success else "failed"),
        "chapter_count": len(config.chapters),
        "phase_d_results": phase_d_results,
        "phase_e_results": phase_e_results,
    }
    write_json(run_ctx.artifacts.shared_dir / "cpu_pipeline_summary.json", cpu_summary)

    elapsed = time.perf_counter() - t_start
    print(f"\n{'=' * 60}")
    print("  CPU PIPELINE COMPLETE")
    print(f"  Elapsed: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print(f"  Run dir: {run_ctx.run_dir}")
    print(f"  Chapter D success: {d_success}/{len(config.chapters)}")
    print(f"  Chapter E success: {e_success}/{len(config.chapters)}")
    print(f"{'=' * 60}")
    print(f'\nTo run GPU phases (F+G+H):\n  python run_pipeline_gpu.py --run-dir "{run_ctx.run_dir}"')
    payload = {
        "run_id": run_ctx.run_id,
        "run_dir": str(run_ctx.run_dir),
        "chapter_count": len(config.chapters),
        "phase_d_success": d_success,
        "phase_e_success": e_success,
        "cpu_summary_json": str(run_ctx.artifacts.shared_dir / "cpu_pipeline_summary.json"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
