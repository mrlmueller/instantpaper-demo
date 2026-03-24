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

from phase_a_lab import RunArtifacts, RunContext, load_metrics, log_event, save_metrics, setup_run_logger, stable_hash, stage_timer  # noqa: E402
from phase_f_lab import PhaseFOptions, run_phase_f  # noqa: E402
from phase_g_lab import PhaseGOptions, run_phase_g  # noqa: E402

EVENT_PREFIX = "PDF_SCAN_EVENT\t"
PHASE_LABELS = {
    "phase_f": "Phase F",
    "phase_g": "Phase G",
}


def emit(event: str, **payload: Any) -> None:
    print(EVENT_PREFIX + json.dumps({"event": str(event), **payload}, ensure_ascii=False), flush=True)


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def update_stage_metrics(run_ctx: Any, stage_name: str, metrics_update: dict[str, Any]) -> None:
    metrics = load_metrics(run_ctx)
    metrics.setdefault("stages", {}).setdefault(stage_name, {}).update(metrics_update)
    save_metrics(run_ctx, metrics)


def reconstruct_run_ctx(run_dir: Path) -> RunContext:
    run_dir = run_dir.resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    required_files = [
        run_dir / "config.json",
        run_dir / "normalized" / "sections.jsonl",
        run_dir / "retrieval" / "fused_candidates.jsonl",
        run_dir / "query_plan.json",
    ]
    missing = [str(path) for path in required_files if not path.exists()]
    if missing:
        raise FileNotFoundError("CPU phases incomplete. Missing files:\n" + "\n".join(f"  - {item}" for item in missing))
    return RunContext(
        repo_root=PDF_SCAN_RUNTIME_DIR.parent.parent,
        pdf_scan_dir=PDF_SCAN_RUNTIME_DIR,
        run_id=run_dir.name,
        run_dir=run_dir,
        artifacts=RunArtifacts.from_run_dir(run_dir),
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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the GPU phases (F+G) of the standalone PDF scan pipeline.")
    parser.add_argument("--run-dir", required=True, help="Path to an existing run directory produced by CPU phases.")
    parser.add_argument("--force-rebuild-phase-f", action="store_true")
    parser.add_argument("--force-rebuild-phase-g", action="store_true")
    parser.add_argument("--no-openai-judge", action="store_true")
    parser.add_argument("--cross-encoder-batch-size", type=int, default=8)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv or sys.argv[1:]))
    run_dir = Path(args.run_dir).resolve()
    run_ctx = reconstruct_run_ctx(run_dir)
    document_count = len(_read_jsonl_rows(run_ctx.run_dir / "normalized" / "documents.jsonl"))

    has_cuda, batch_size, gpu_name = detect_gpu_batch_size(int(args.cross_encoder_batch_size))
    if gpu_name:
        print(f"GPU: {gpu_name} | batch_size={batch_size}", flush=True)

    t_start = time.perf_counter()
    phase_g_result = None

    try:
        if bool(args.force_rebuild_phase_f) or not (run_ctx.run_dir / "rerank" / "phase_f_summary.json").exists():
            emit("stage_start", stage="phase_f", label=PHASE_LABELS["phase_f"])
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
                log_event_fn=log_event,
                run_logger=phase_g_logger,
            )
            update_stage_metrics(run_ctx, "phase_g", phase_g_result["metrics_update"])
        emit("stage_complete", stage="phase_g", label=PHASE_LABELS["phase_g"])

        useful = len([row for row in phase_g_result["doc_feature_rows"] if row.get("has_useful_information")])
        payload = {
            "pipeline_run_id": str(run_ctx.run_id),
            "run_dir": str(run_ctx.run_dir),
            "last_completed_phase": "phase_g",
            "useful_pdfs": useful,
            "document_count": len(phase_g_result["doc_feature_rows"]),
            "output_json": str(run_ctx.artifacts.final_dir / "output.json"),
            "gpu_used": has_cuda,
            "elapsed_sec": round(time.perf_counter() - t_start, 1),
        }
        emit("run_complete", **payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
        return 0
    except Exception as exc:
        emit("run_error", error_type=type(exc).__name__, error_message=str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
