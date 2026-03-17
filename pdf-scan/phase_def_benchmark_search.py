#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List

PDF_SCAN_DIR = Path(__file__).resolve().parent
if str(PDF_SCAN_DIR) not in sys.path:
    sys.path.insert(0, str(PDF_SCAN_DIR))

from tools.benchmark.evaluate_manual_benchmark import build_run_view, build_summary, evaluate_judgment, load_suite
from phase_a_lab import (
    REPO_ROOT,
    RunArtifacts,
    RunContext,
    load_metrics,
    log_event,
    save_metrics,
    setup_run_logger,
    stable_hash,
    stage_timer,
)
from phase_d_lab import PhaseDOptions, run_phase_d
from phase_e_lab import PhaseEOptions, run_phase_e
from phase_f_lab import PhaseFOptions, run_phase_f
from phase_g_lab import PhaseGOptions, run_phase_g


@dataclass
class VariantSpec:
    name: str
    notes: str
    phase_d: Dict[str, Any] = field(default_factory=dict)
    phase_e: Dict[str, Any] = field(default_factory=dict)
    phase_f: Dict[str, Any] = field(default_factory=dict)
    phase_g: Dict[str, Any] = field(default_factory=dict)


BASE_PHASE_D = dict(
    force_rebuild=True,
    use_openai_planner=True,
    allow_heuristic_fallback=True,
    openai_model="gpt-5-mini",
    reasoning_effort="low",
    temperature=0.0,
    max_completion_tokens=1400,
    bridge_max_completion_tokens=1800,
    must_term_limit=8,
    should_term_limit=14,
    exclusion_limit=8,
    subpoint_limit=6,
    drift_risk_limit=8,
    source_anchor_limit=24,
    subpoint_source_anchor_limit=3,
    max_summary_chars=480,
    max_subpoint_summary_chars=320,
    min_anchor_token_overlap=0.67,
)

BASE_PHASE_E = dict(
    force_rebuild=True,
    candidate_limit_per_lane=80,
    fused_candidate_limit=120,
    per_view_limit_multiplier=2,
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
    selection_strategy="xquad",
    use_supported_subpoint_selection=True,
    abstain_when_no_supported_subpoints=True,
    generic_evidence_bonus=0.01,
    generic_anchor_score_threshold=1.0,
    single_support_penalty=0.008,
    zero_support_penalty=0.025,
    generic_low_support_penalty=0.01,
    subpoint_min_supported_candidates=1,
    subpoint_max_preview_rows=10,
    diversity_lambda=0.45,
    enable_doc_title_rescue=False,
)

BASE_PHASE_F = dict(
    force_rebuild=True,
    rerank_top_k=60,
    inject_doc_top_candidates=True,
    cross_encoder_model="BAAI/bge-reranker-v2-m3",
    cross_encoder_batch_size=8,
    cross_encoder_max_length=1536,
    cross_encoder_subpoint_limit=2,
    section_excerpt_max_chars=2200,
    supporting_passage_count=3,
    passage_excerpt_max_chars=520,
    use_openai_judge=True,
    judge_model="gpt-5-mini",
    judge_reasoning_effort="low",
    judge_candidate_limit=12,
    judge_max_per_doc=2,
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

BASE_PHASE_G = dict(
    force_rebuild=True,
    top_sections_per_doc=5,
    top_global_sections=25,
    section_useful_threshold=70,
    section_partial_threshold=55,
    doc_probability_threshold=0.63,
    top_section_floor=62,
    strong_top_section_floor=78,
    min_doc_sections_for_useful=1,
    min_doc_partial_sections=1,
    min_top_supporting_passages=1,
    top_k_for_doc_features=5,
    support_preview_count=2,
    support_preview_max_chars=260,
    generic_only_penalty=0.18,
    generic_high_penalty=0.08,
    penalized_type_penalty=0.20,
    calibration_mode="auto",
)


VARIANTS: List[VariantSpec] = [
    VariantSpec(
        name="baseline_current",
        notes="Current tuned D/E/F/G defaults from the full-dump false-negative audit baseline.",
    ),
    VariantSpec(
        name="recall_relaxed_calibration",
        notes="Keep retrieval the same but widen rerank judging and relax final usefulness thresholds.",
        phase_f={
            "rerank_top_k": 90,
            "judge_candidate_limit": 24,
            "judge_max_per_doc": 3,
            "llm_judge_blend": 0.28,
        },
        phase_g={
            "section_useful_threshold": 65,
            "section_partial_threshold": 50,
            "doc_probability_threshold": 0.52,
            "top_section_floor": 55,
            "strong_top_section_floor": 72,
        },
    ),
    VariantSpec(
        name="recall_broader_retrieval",
        notes="Broaden Phase E candidate generation and disable supported-subpoint gating.",
        phase_e={
            "candidate_limit_per_lane": 120,
            "fused_candidate_limit": 180,
            "per_view_limit_multiplier": 3,
            "use_supported_subpoint_selection": False,
            "abstain_when_no_supported_subpoints": False,
            "selection_strategy": "round_robin",
            "diversity_lambda": 0.25,
            "single_support_penalty": 0.004,
            "zero_support_penalty": 0.012,
            "generic_low_support_penalty": 0.006,
        },
        phase_f={
            "rerank_top_k": 100,
            "judge_candidate_limit": 24,
            "judge_max_per_doc": 3,
            "llm_judge_blend": 0.25,
        },
        phase_g={
            "section_useful_threshold": 65,
            "section_partial_threshold": 50,
            "doc_probability_threshold": 0.50,
            "top_section_floor": 54,
            "strong_top_section_floor": 72,
        },
    ),
    VariantSpec(
        name="summary_doc_rescue_high_recall",
        notes="Broader retrieval plus low-scale document-summary rescue and a wider rerank pool.",
        phase_e={
            "candidate_limit_per_lane": 120,
            "fused_candidate_limit": 180,
            "per_view_limit_multiplier": 3,
            "use_supported_subpoint_selection": False,
            "abstain_when_no_supported_subpoints": False,
            "selection_strategy": "round_robin",
            "diversity_lambda": 0.25,
            "single_support_penalty": 0.004,
            "zero_support_penalty": 0.012,
            "generic_low_support_penalty": 0.006,
            "enable_doc_title_rescue": True,
            "doc_rescue_doc_limit": 5,
            "doc_rescue_sections_per_doc": 2,
            "doc_rescue_score_scale": 0.02,
        },
        phase_f={
            "rerank_top_k": 140,
            "judge_candidate_limit": 28,
            "judge_max_per_doc": 3,
            "llm_judge_blend": 0.24,
        },
        phase_g={
            "section_useful_threshold": 62,
            "section_partial_threshold": 48,
            "doc_probability_threshold": 0.48,
            "top_section_floor": 52,
            "strong_top_section_floor": 70,
        },
    ),
    VariantSpec(
        name="summary_doc_rescue_max_rerank",
        notes="Same recall stack but let Phase F see nearly the full fused pool before judging.",
        phase_e={
            "candidate_limit_per_lane": 140,
            "fused_candidate_limit": 220,
            "per_view_limit_multiplier": 3,
            "use_supported_subpoint_selection": False,
            "abstain_when_no_supported_subpoints": False,
            "selection_strategy": "round_robin",
            "diversity_lambda": 0.22,
            "single_support_penalty": 0.004,
            "zero_support_penalty": 0.01,
            "generic_low_support_penalty": 0.005,
            "enable_doc_title_rescue": True,
            "doc_rescue_doc_limit": 6,
            "doc_rescue_sections_per_doc": 2,
            "doc_rescue_score_scale": 0.018,
        },
        phase_f={
            "rerank_top_k": 180,
            "judge_candidate_limit": 32,
            "judge_max_per_doc": 3,
            "llm_judge_blend": 0.22,
        },
        phase_g={
            "section_useful_threshold": 60,
            "section_partial_threshold": 46,
            "doc_probability_threshold": 0.46,
            "top_section_floor": 50,
            "strong_top_section_floor": 68,
        },
    ),
    VariantSpec(
        name="summary_doc_rescue_max_rerank_relaxed_calibration",
        notes="Best observed end-to-end stack so far: max-rerank recall plus relaxed document calibration.",
        phase_e={
            "candidate_limit_per_lane": 140,
            "fused_candidate_limit": 220,
            "per_view_limit_multiplier": 3,
            "use_supported_subpoint_selection": False,
            "abstain_when_no_supported_subpoints": False,
            "selection_strategy": "round_robin",
            "diversity_lambda": 0.22,
            "single_support_penalty": 0.004,
            "zero_support_penalty": 0.01,
            "generic_low_support_penalty": 0.005,
            "enable_doc_title_rescue": True,
            "doc_rescue_doc_limit": 6,
            "doc_rescue_sections_per_doc": 2,
            "doc_rescue_score_scale": 0.018,
        },
        phase_f={
            "rerank_top_k": 180,
            "judge_candidate_limit": 32,
            "judge_max_per_doc": 3,
            "llm_judge_blend": 0.22,
        },
        phase_g={
            "section_useful_threshold": 48,
            "section_partial_threshold": 36,
            "doc_probability_threshold": 0.34,
            "top_section_floor": 38,
            "strong_top_section_floor": 56,
            "generic_only_penalty": 0.14,
            "generic_high_penalty": 0.06,
            "penalized_type_penalty": 0.16,
        },
    ),
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_run_ctx(run_id: str) -> RunContext:
    run_dir = (PDF_SCAN_DIR / "runs" / run_id).resolve()
    return RunContext(
        repo_root=REPO_ROOT,
        pdf_scan_dir=PDF_SCAN_DIR,
        run_id=run_id,
        run_dir=run_dir,
        artifacts=RunArtifacts.from_run_dir(run_dir),
    )


def merged(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    out.update(override or {})
    return out


def evaluate_suite(run_dir: Path, suite_manifest: Path, *, phase_e_doc_topk: int = 10, phase_f_doc_topk: int = 10, phase_g_topk: int = 5) -> Dict[str, Any]:
    suite_view = load_suite(suite_manifest)
    run_view = build_run_view(run_dir)
    rows = [
        evaluate_judgment(
            judgment,
            run_view,
            phase_e_doc_topk=phase_e_doc_topk,
            phase_f_doc_topk=phase_f_doc_topk,
            phase_g_topk=phase_g_topk,
        )
        for judgment in suite_view["judgments"]
    ]
    summary = build_summary(
        rows,
        phase_e_doc_topk=phase_e_doc_topk,
        phase_f_doc_topk=phase_f_doc_topk,
        phase_g_topk=phase_g_topk,
    )
    return {
        "suite_id": suite_view["suite"]["suite_id"],
        "rows": rows,
        "summary": summary,
    }


def run_variant(run_ctx: RunContext, chapter_title: str, chapter_description: str, variant: VariantSpec, suite_manifest: Path) -> Dict[str, Any]:
    d_opt = PhaseDOptions(**merged(BASE_PHASE_D, variant.phase_d))
    e_opt = PhaseEOptions(**merged(BASE_PHASE_E, variant.phase_e))
    f_opt = PhaseFOptions(**merged(BASE_PHASE_F, variant.phase_f))
    g_opt = PhaseGOptions(**merged(BASE_PHASE_G, variant.phase_g))

    stage_logger = setup_run_logger(run_ctx)

    with stage_timer(run_ctx, f"phase_d::{variant.name}"):
        phase_d_result = run_phase_d(
            run_ctx,
            chapter_title=chapter_title,
            chapter_spec_text=chapter_description,
            options=d_opt,
            stable_hash_fn=stable_hash,
            log_event_fn=log_event,
            run_logger=stage_logger,
        )
        metrics = load_metrics(run_ctx)
        metrics.setdefault("stages", {}).setdefault("phase_d", {}).update(phase_d_result["metrics_update"])
        save_metrics(run_ctx, metrics)

    with stage_timer(run_ctx, f"phase_e::{variant.name}"):
        phase_e_result = run_phase_e(
            run_ctx,
            options=e_opt,
            stable_hash_fn=stable_hash,
            log_event_fn=log_event,
            run_logger=stage_logger,
        )
        metrics = load_metrics(run_ctx)
        metrics.setdefault("stages", {}).setdefault("phase_e", {}).update(phase_e_result["metrics_update"])
        save_metrics(run_ctx, metrics)

    with stage_timer(run_ctx, f"phase_f::{variant.name}"):
        phase_f_result = run_phase_f(
            run_ctx,
            options=f_opt,
            stable_hash_fn=stable_hash,
            log_event_fn=log_event,
            run_logger=stage_logger,
        )
        metrics = load_metrics(run_ctx)
        metrics.setdefault("stages", {}).setdefault("phase_f", {}).update(phase_f_result["metrics_update"])
        save_metrics(run_ctx, metrics)

    with stage_timer(run_ctx, f"phase_g::{variant.name}"):
        phase_g_result = run_phase_g(
            run_ctx,
            options=g_opt,
            stable_hash_fn=stable_hash,
            log_event_fn=log_event,
            run_logger=stage_logger,
        )
        metrics = load_metrics(run_ctx)
        metrics.setdefault("stages", {}).setdefault("phase_g", {}).update(phase_g_result["metrics_update"])
        save_metrics(run_ctx, metrics)

    benchmark = evaluate_suite(run_ctx.run_dir, suite_manifest)
    return {
        "variant": variant.name,
        "notes": variant.notes,
        "phase_d": merged(BASE_PHASE_D, variant.phase_d),
        "phase_e": merged(BASE_PHASE_E, variant.phase_e),
        "phase_f": merged(BASE_PHASE_F, variant.phase_f),
        "phase_g": merged(BASE_PHASE_G, variant.phase_g),
        "benchmark_summary": benchmark["summary"],
        "false_negative_docs": benchmark["summary"]["false_negative_docs"],
        "docs_with_missed_anchors": benchmark["summary"]["docs_with_missed_anchors"],
        "phase_g_useful_docs": [row["doc_id"] for row in read_json(run_ctx.run_dir / "final" / "output.json").get("documents") or [] if row.get("has_useful_information")],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Search D/E/F/G variants against the manual full-dump benchmark.")
    parser.add_argument("--run-id", default="386e04657c41c805f8c1b974")
    parser.add_argument("--suite-manifest", default="benchmark/full_dump_webshop_manual_v1/manifests/suite_manifest.json")
    parser.add_argument("--variants", nargs="*", default=[spec.name for spec in VARIANTS])
    args = parser.parse_args()

    run_ctx = build_run_ctx(args.run_id)
    config = read_json(run_ctx.artifacts.config_json)
    chapter_title = str(config.get("chapter_title") or "")
    chapter_description = str(config.get("chapter_spec_text") or "")
    suite_manifest = (PDF_SCAN_DIR / args.suite_manifest).resolve() if not Path(args.suite_manifest).is_absolute() else Path(args.suite_manifest).resolve()

    selected = [spec for spec in VARIANTS if spec.name in set(args.variants)]
    if not selected:
        raise SystemExit("No matching variants selected.")

    out_dir = run_ctx.run_dir / "phase_def_benchmark_search"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for spec in selected:
        result = run_variant(run_ctx, chapter_title, chapter_description, spec, suite_manifest)
        rows.append(result)
        write_json(out_dir / f"{spec.name}.json", result)

    leaderboard = []
    for row in rows:
        doc_metrics = row["benchmark_summary"]["document_metrics"]
        anchor_metrics = row["benchmark_summary"]["section_anchor_metrics"]
        leaderboard.append(
            {
                "variant": row["variant"],
                "doc_recall": doc_metrics["doc_recall"],
                "doc_precision": doc_metrics["doc_precision"],
                "anchor_structure_recall": anchor_metrics["structure_presence_recall"],
                "phase_e_anchor_hit": anchor_metrics.get("phase_e_hit_at_doc_top10"),
                "phase_f_anchor_hit": anchor_metrics.get("phase_f_hit_at_doc_top10"),
                "phase_g_anchor_hit": anchor_metrics.get("phase_g_hit_at_doc_top5"),
                "false_negative_count": doc_metrics["false_negative"],
                "useful_doc_count": doc_metrics["true_positive"] + doc_metrics["false_positive"],
            }
        )
    leaderboard.sort(key=lambda row: (row["doc_recall"], row["phase_f_anchor_hit"], row["phase_e_anchor_hit"]), reverse=True)
    write_json(out_dir / "leaderboard.json", {"rows": leaderboard})

    print(json.dumps({"run_id": args.run_id, "leaderboard": leaderboard}, ensure_ascii=False, indent=2))
    print(f"\nWrote benchmark search artifacts to {out_dir}")


if __name__ == "__main__":
    main()
