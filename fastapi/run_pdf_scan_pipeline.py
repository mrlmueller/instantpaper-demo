from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    write_json,
)
from phase_a_lab import run_phase_a  # noqa: E402
from phase_b_lab import PhaseBOptions, run_phase_b  # noqa: E402
from phase_c_lab import PhaseCOptions, run_phase_c  # noqa: E402
from phase_d_lab import PhaseDOptions, run_phase_d  # noqa: E402
from phase_e_lab import PhaseEOptions, prepare_phase_e_shared_dense_cache, run_phase_e  # noqa: E402

EVENT_PREFIX = "PDF_SCAN_EVENT\t"
PHASE_LABELS = {
    "phase_a": "Phase A",
    "phase_b": "Phase B",
    "phase_c": "Phase C",
    "phase_c5": "Phase C.5",
    "phase_d": "Phase D",
    "phase_e": "Phase E",
}


def default_local_runs_root() -> Path:
    return Path(tempfile.gettempdir()) / "instantpaper_pdf_scan_runs"


def emit(event: str, **payload: Any) -> None:
    print(EVENT_PREFIX + json.dumps({"event": str(event), **payload}, ensure_ascii=False), flush=True)


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


def update_stage_metrics(run_ctx: Any, stage_name: str, metrics_update: dict[str, Any]) -> None:
    metrics = load_metrics(run_ctx)
    metrics.setdefault("stages", {}).setdefault(stage_name, {}).update(metrics_update)
    save_metrics(run_ctx, metrics)


def update_chapter_stage_metrics(run_ctx: Any, chapter_id: str, stage_name: str, metrics_update: dict[str, Any]) -> None:
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
) -> dict[str, Any]:
    chapter_ctx = run_ctx.for_chapter(chapter.chapter_id)
    phase_d_summary_path = Path(chapter_ctx.artifacts.retrieval_dir) / "phase_d_summary.json"
    if not bool(options.force_rebuild) and phase_d_summary_path.exists():
        return {
            "chapter_id": chapter.chapter_id,
            "chapter_title": chapter.chapter_title,
            "status": "cached",
            "elapsed_sec": 0.0,
            "summary": json.loads(phase_d_summary_path.read_text(encoding="utf-8")),
        }

    started = time.perf_counter()
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
        return {
            "chapter_id": chapter.chapter_id,
            "chapter_title": chapter.chapter_title,
            "status": "success",
            "elapsed_sec": elapsed,
            "summary": result.get("summary") or {},
        }
    except Exception as exc:
        return {
            "chapter_id": chapter.chapter_id,
            "chapter_title": chapter.chapter_title,
            "status": "failed",
            "elapsed_sec": round(time.perf_counter() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _run_phase_e_for_chapter(
    run_ctx: Any,
    *,
    chapter: Any,
    options: PhaseEOptions,
    run_logger: Any,
) -> dict[str, Any]:
    chapter_ctx = run_ctx.for_chapter(chapter.chapter_id)
    phase_e_summary_path = Path(chapter_ctx.artifacts.retrieval_dir) / "phase_e_summary.json"
    if not bool(options.force_rebuild) and phase_e_summary_path.exists():
        return {
            "chapter_id": chapter.chapter_id,
            "chapter_title": chapter.chapter_title,
            "status": "cached",
            "elapsed_sec": 0.0,
            "summary": json.loads(phase_e_summary_path.read_text(encoding="utf-8")),
        }

    started = time.perf_counter()
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
        return {
            "chapter_id": chapter.chapter_id,
            "chapter_title": chapter.chapter_title,
            "status": "success",
            "elapsed_sec": elapsed,
            "summary": result.get("summary") or {},
        }
    except Exception as exc:
        return {
            "chapter_id": chapter.chapter_id,
            "chapter_title": chapter.chapter_title,
            "status": "failed",
            "elapsed_sec": round(time.perf_counter() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_parallel_chapter_stage(
    *,
    chapters: list[Any],
    max_workers: int,
    submit_fn,
) -> dict[str, dict[str, Any]]:
    if not chapters:
        return {}
    if len(chapters) == 1 or max_workers <= 1:
        result = submit_fn(chapters[0])
        return {chapters[0].chapter_id: result}
    out: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(submit_fn, chapter): chapter for chapter in chapters}
        for future in as_completed(futures):
            chapter = futures[future]
            out[chapter.chapter_id] = future.result()
    return out


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run CPU phases (A-E) of the standalone PDF scan pipeline.")
    chapter_group = parser.add_mutually_exclusive_group(required=True)
    chapter_group.add_argument("--theme-md", help="Path to a single topic markdown file.")
    chapter_group.add_argument("--chapters-dir", help="Directory containing one markdown file per chapter.")
    parser.add_argument("--pdf-dir", required=True, help="Directory containing the PDFs.")
    parser.add_argument(
        "--runs-root",
        default="",
        help="Optional root directory for pipeline run artifacts. Defaults to the system temp directory for local runs.",
    )
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv or sys.argv[1:]))
    theme_path = Path(args.theme_md).resolve() if args.theme_md else None
    chapters_dir = Path(args.chapters_dir).resolve() if args.chapters_dir else None
    pdf_dir = Path(args.pdf_dir).resolve()

    chapter_title = ""
    chapter_description = ""
    if theme_path is not None:
        chapter_title, chapter_description = parse_theme_markdown(theme_path)

    phase_a_args = Namespace(
        input_mode="manual",
        pipeline_version=str(args.pipeline_version or "pdf_scan_v3_parallel_topic"),
        force_rebuild=bool(args.force_rebuild_phase_a),
        runs_root=str(Path(args.runs_root).resolve()) if str(args.runs_root or "").strip() else str(default_local_runs_root().resolve()),
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

    t_start = time.perf_counter()
    phase_doc_totals: dict[str, int] = {}
    phase_doc_progress = {"phase_b": 0, "phase_c": 0}

    def bridged_log_event(run_ctx: Any, *, stage: str, event: str, **payload: Any) -> None:
        log_event(run_ctx, stage=stage, event=event, **payload)
        if stage == "phase_b" and event in {"document_parsed", "document_reused_from_cache", "document_failed"}:
            phase_doc_progress["phase_b"] += 1
            emit(
                "document_progress",
                scope="shared",
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
                scope="shared",
                stage=stage,
                label=PHASE_LABELS.get(stage, stage),
                current=phase_doc_progress["phase_c"],
                total=phase_doc_totals.get("phase_c"),
                doc_id=str(payload.get("doc_id") or ""),
            )

    try:
        emit("stage_start", scope="shared", stage="phase_a", label=PHASE_LABELS["phase_a"])
        phase_a_result = run_phase_a(phase_a_args)
        run_ctx = phase_a_result["run_ctx"]
        config = phase_a_result["config"]
        pdf_manifest = phase_a_result["manifest_rows"]
        run_logger = setup_run_logger(run_ctx)
        phase_doc_totals["phase_b"] = len(pdf_manifest)
        phase_doc_totals["phase_c"] = len(pdf_manifest)
        emit(
            "run_initialized",
            pipeline_run_id=str(run_ctx.run_id),
            run_dir=str(run_ctx.run_dir),
            document_count=len(pdf_manifest),
            chapter_count=len(config.chapters),
        )
        emit(
            "stage_complete",
            scope="shared",
            stage="phase_a",
            label=PHASE_LABELS["phase_a"],
            document_count=len(pdf_manifest),
            chapter_count=len(config.chapters),
        )

        if bool(args.force_rebuild_phase_b) or not (run_ctx.run_dir / "parser" / "phase_b_summary.json").exists():
            emit("stage_start", scope="shared", stage="phase_b", label=PHASE_LABELS["phase_b"], total=phase_doc_totals["phase_b"])
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
                    run_logger=run_logger,
                )
                update_stage_metrics(run_ctx, "phase_b", phase_b_result["metrics_update"])
            emit(
                "stage_complete",
                scope="shared",
                stage="phase_b",
                label=PHASE_LABELS["phase_b"],
                current=phase_doc_progress["phase_b"],
                total=phase_doc_totals["phase_b"],
            )

        if bool(args.force_rebuild_phase_c) or not (run_ctx.run_dir / "normalized" / "phase_c_summary.json").exists():
            emit("stage_start", scope="shared", stage="phase_c", label=PHASE_LABELS["phase_c"], total=phase_doc_totals["phase_c"])
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
                    run_logger=run_logger,
                )
                update_stage_metrics(run_ctx, "phase_c", phase_c_result["metrics_update"])
            emit(
                "stage_complete",
                scope="shared",
                stage="phase_c",
                label=PHASE_LABELS["phase_c"],
                current=phase_doc_progress["phase_c"],
                total=phase_doc_totals["phase_c"],
            )

        phase_d_options = build_phase_d_options(args)
        phase_e_options = build_phase_e_options(args)
        max_workers = max(1, min(int(args.max_cpu_chapter_concurrency), len(config.chapters)))
        chapter_lookup = {chapter.chapter_id: chapter for chapter in config.chapters}

        emit("stage_start", scope="chapter", stage="phase_d", label=PHASE_LABELS["phase_d"], total=len(config.chapters))
        with stage_timer(run_ctx, "phase_d_parallel"):
            phase_d_results = run_parallel_chapter_stage(
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
        for row in phase_d_results.values():
            emit(
                "chapter_stage_complete",
                scope="chapter",
                stage="phase_d",
                chapter_id=row.get("chapter_id"),
                chapter_title=row.get("chapter_title"),
                status=row.get("status"),
                elapsed_sec=row.get("elapsed_sec"),
                error=row.get("error"),
            )
        emit("stage_complete", scope="chapter", stage="phase_d", label=PHASE_LABELS["phase_d"], current=d_success, total=len(config.chapters))

        if phase_e_options.use_shared_dense_cache and phase_e_options.use_openai_dense and d_success:
            emit("stage_start", scope="shared", stage="phase_c5", label=PHASE_LABELS["phase_c5"])
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
            emit("stage_complete", scope="shared", stage="phase_c5", label=PHASE_LABELS["phase_c5"])

        chapters_for_e = [
            chapter_lookup[chapter_id]
            for chapter_id, row in phase_d_results.items()
            if row.get("status") in {"success", "cached"} and chapter_id in chapter_lookup
        ]
        emit("stage_start", scope="chapter", stage="phase_e", label=PHASE_LABELS["phase_e"], total=len(chapters_for_e))
        with stage_timer(run_ctx, "phase_e_parallel"):
            phase_e_results = run_parallel_chapter_stage(
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
        for row in phase_e_results.values():
            emit(
                "chapter_stage_complete",
                scope="chapter",
                stage="phase_e",
                chapter_id=row.get("chapter_id"),
                chapter_title=row.get("chapter_title"),
                status=row.get("status"),
                elapsed_sec=row.get("elapsed_sec"),
                error=row.get("error"),
            )
        emit("stage_complete", scope="chapter", stage="phase_e", label=PHASE_LABELS["phase_e"], current=e_success, total=len(chapters_for_e))

        cpu_summary = {
            "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "run_id": run_ctx.run_id,
            "status": "success" if e_success == len(config.chapters) else ("partial_success" if e_success else "failed"),
            "chapter_count": len(config.chapters),
            "phase_d_results": phase_d_results,
            "phase_e_results": phase_e_results,
        }
        write_json(run_ctx.artifacts.shared_dir / "cpu_pipeline_summary.json", cpu_summary)

        payload = {
            "run_id": run_ctx.run_id,
            "run_dir": str(run_ctx.run_dir),
            "chapter_count": len(config.chapters),
            "phase_d_success": d_success,
            "phase_e_success": e_success,
            "cpu_summary_json": str(run_ctx.artifacts.shared_dir / "cpu_pipeline_summary.json"),
            "last_completed_phase": "phase_e",
            "document_count": len(pdf_manifest),
        }
        emit("run_complete", pipeline_run_id=str(run_ctx.run_id), **payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
        return 0
    except Exception as exc:
        emit("run_error", error_type=type(exc).__name__, error_message=str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
