#!/usr/bin/env python3
from __future__ import annotations

import argparse
import statistics
from argparse import Namespace
from collections import defaultdict

from phase_f_lab import *  # noqa: F401,F403


try:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression
except Exception as e:
    CalibratedClassifierCV = None
    LogisticRegression = None
    PHASE_G_SKLEARN_IMPORT_ERROR = f"{type(e).__name__}: {e}"
else:
    PHASE_G_SKLEARN_IMPORT_ERROR = None


PHASE_G_PENALIZED_SECTION_TYPES = {
    "front_matter",
    "table_of_contents",
    "references",
    "appendix",
    "acknowledgements",
}

PHASE_G_GENERIC_SECTION_TYPES = {
    "abstract",
    "introduction",
    "conclusion",
    "background",
    "related_work",
}


@dataclass
class PhaseGOptions:
    force_rebuild: bool = False
    top_sections_per_doc: int = 5
    top_global_sections: int = 25
    section_useful_threshold: int = 70
    section_partial_threshold: int = 55
    doc_probability_threshold: float = 0.63
    top_section_floor: int = 62
    strong_top_section_floor: int = 78
    min_doc_sections_for_useful: int = 1
    min_doc_partial_sections: int = 1
    min_top_supporting_passages: int = 1
    top_k_for_doc_features: int = 5
    support_preview_count: int = 2
    support_preview_max_chars: int = 260
    generic_only_penalty: float = 0.18
    generic_high_penalty: float = 0.08
    penalized_type_penalty: float = 0.20
    calibration_mode: str = "auto"

    def normalized(self) -> "PhaseGOptions":
        mode = str(self.calibration_mode or "auto").strip().lower() or "auto"
        if mode not in {"auto", "provisional_rules", "disabled"}:
            mode = "auto"
        return PhaseGOptions(
            force_rebuild=bool(self.force_rebuild),
            top_sections_per_doc=max(1, int(self.top_sections_per_doc)),
            top_global_sections=max(5, int(self.top_global_sections)),
            section_useful_threshold=max(1, min(100, int(self.section_useful_threshold))),
            section_partial_threshold=max(1, min(100, int(self.section_partial_threshold))),
            doc_probability_threshold=max(0.0, min(1.0, float(self.doc_probability_threshold))),
            top_section_floor=max(1, min(100, int(self.top_section_floor))),
            strong_top_section_floor=max(1, min(100, int(self.strong_top_section_floor))),
            min_doc_sections_for_useful=max(1, int(self.min_doc_sections_for_useful)),
            min_doc_partial_sections=max(0, int(self.min_doc_partial_sections)),
            min_top_supporting_passages=max(0, int(self.min_top_supporting_passages)),
            top_k_for_doc_features=max(1, int(self.top_k_for_doc_features)),
            support_preview_count=max(1, int(self.support_preview_count)),
            support_preview_max_chars=max(80, int(self.support_preview_max_chars)),
            generic_only_penalty=max(0.0, min(0.4, float(self.generic_only_penalty))),
            generic_high_penalty=max(0.0, min(0.3, float(self.generic_high_penalty))),
            penalized_type_penalty=max(0.0, min(0.4, float(self.penalized_type_penalty))),
            calibration_mode=mode,
        )


def phase_g_capabilities() -> Dict[str, Any]:
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "sklearn_available": bool(CalibratedClassifierCV is not None and LogisticRegression is not None),
        "optional_import_errors": {"sklearn": PHASE_G_SKLEARN_IMPORT_ERROR},
    }


def build_phase_g_cache_result(run_ctx: Any) -> Dict[str, Any]:
    final_dir = Path(run_ctx.artifacts.final_dir)
    config_path = final_dir / "phase_g_config.json"
    runtime_path = final_dir / "phase_g_runtime.json"
    summary_path = final_dir / "phase_g_summary.json"
    assessment_path = final_dir / "phase_g_assessment.json"
    per_pdf_rankings_path = final_dir / "per_pdf_rankings.json"
    global_rankings_path = final_dir / "global_rankings.json"
    output_path = final_dir / "output.json"
    section_scores_path = final_dir / "section_scores.jsonl"
    doc_features_path = final_dir / "doc_features.jsonl"
    calibration_trace_path = final_dir / "calibration_trace.json"
    required = [
        config_path,
        runtime_path,
        summary_path,
        assessment_path,
        per_pdf_rankings_path,
        global_rankings_path,
        output_path,
        section_scores_path,
        doc_features_path,
        calibration_trace_path,
    ]
    if not all(path.exists() for path in required):
        raise FileNotFoundError("Phase G cache is incomplete.")
    summary = read_json(summary_path)
    assessment_json = read_json(assessment_path)
    return {
        "config_path": config_path,
        "runtime_path": runtime_path,
        "summary_path": summary_path,
        "assessment_path": assessment_path,
        "per_pdf_rankings_path": per_pdf_rankings_path,
        "global_rankings_path": global_rankings_path,
        "output_path": output_path,
        "section_scores_path": section_scores_path,
        "doc_features_path": doc_features_path,
        "calibration_trace_path": calibration_trace_path,
        "section_score_rows": read_jsonl_rows(section_scores_path),
        "doc_feature_rows": read_jsonl_rows(doc_features_path),
        "per_pdf_rankings": read_json(per_pdf_rankings_path),
        "global_rankings": read_json(global_rankings_path),
        "output_payload": read_json(output_path),
        "summary": summary,
        "assessment": assessment_json.get("assessment") or {},
        "qc_rows": assessment_json.get("qc_rows") or [],
        "metrics_update": summary.get("metrics_update") or {},
        "cache_hit": True,
    }


def section_band(score_0_to_100: Any) -> str:
    score = float(score_0_to_100 or 0.0)
    if score >= 85.0:
        return "highly_useful"
    if score >= 70.0:
        return "useful"
    if score >= 55.0:
        return "partially_useful"
    if score >= 40.0:
        return "weak_signal"
    return "not_useful"


def support_strength_label(score: Any) -> str:
    value = clamp01(score)
    if value >= 0.78:
        return "strong"
    if value >= 0.55:
        return "moderate"
    return "limited"


def safe_div(num: Any, den: Any) -> float:
    try:
        den_value = float(den)
        if den_value == 0.0:
            return 0.0
        return float(num) / den_value
    except Exception:
        return 0.0


def unique_nonempty(values: Iterable[Any]) -> List[str]:
    seen = set()
    out = []
    for value in values:
        item = clean_text(value)
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def is_penalized_section_type(section_type: Any, penalized_types: Iterable[str]) -> bool:
    return clean_text(section_type).lower() in {clean_text(item).lower() for item in penalized_types if clean_text(item)}


def is_generic_high_level_section(row: Dict[str, Any]) -> bool:
    if bool(row.get("generic_title")):
        return True
    return clean_text(row.get("section_type")).lower() in PHASE_G_GENERIC_SECTION_TYPES


def evidence_preview_rows(row: Dict[str, Any], *, max_rows: int, max_chars: int) -> List[Dict[str, Any]]:
    preview = []
    for item in list(row.get("evidence_rows") or [])[: max(1, int(max_rows))]:
        preview.append(
            {
                "passage_id": item.get("passage_id"),
                "pages": f"{item.get('page_start')}-{item.get('page_end')}",
                "best_lane_score": item.get("best_lane_score"),
                "lanes": list(item.get("lanes") or []),
                "text": truncate_text(clean_text(item.get("text") or ""), max_len=max_chars),
            }
        )
    return preview


def top_n_mean(values: Iterable[Any], n: int) -> float:
    seq = sorted([float(v) for v in values if v is not None], reverse=True)[: max(1, int(n))]
    if not seq:
        return 0.0
    return float(sum(seq) / len(seq))


def feature_support_score(row: Dict[str, Any]) -> float:
    supporting_count = min(1.0, safe_div(int(row.get("supporting_passage_count") or 0), 4.0))
    evidence_density = clamp01(row.get("evidence_density"))
    best_subpoint = clamp01(row.get("best_subpoint_score_prob"))
    judge_score = row.get("judge_score")
    judge_component = clamp01(judge_score) if judge_score is not None else None
    components = [0.38 * evidence_density, 0.32 * supporting_count, 0.22 * best_subpoint]
    if judge_component is not None:
        components.append(0.08 * judge_component)
    return round(sum(components), 8)


def feature_subpoint_coverage_ratio(row: Dict[str, Any], active_subpoint_ids: Iterable[str]) -> float:
    active = {str(value) for value in active_subpoint_ids if str(value)}
    if not active:
        return 0.0
    row_ids = {str(value) for value in list(row.get("trusted_subpoint_ids") or row.get("chosen_subpoint_ids") or []) if str(value)}
    return round(safe_div(len(active & row_ids), len(active)), 8)


def provisional_section_probability(
    row: Dict[str, Any],
    *,
    active_subpoint_ids: Iterable[str],
    penalized_types: Iterable[str],
    options: PhaseGOptions,
) -> Dict[str, Any]:
    rerank_score = clamp01(row.get("rerank_score"))
    cross_encoder = clamp01(row.get("cross_encoder_score"))
    support_score = feature_support_score(row)
    support_count_norm = min(1.0, safe_div(int(row.get("supporting_passage_count") or 0), 4.0))
    coverage_ratio = feature_subpoint_coverage_ratio(row, active_subpoint_ids)
    judge_score = row.get("judge_score")
    judge_norm = clamp01(judge_score) if judge_score is not None else None
    probability = (
        (0.52 * rerank_score)
        + (0.18 * cross_encoder)
        + (0.10 * support_score)
        + (0.08 * support_count_norm)
        + (0.07 * coverage_ratio)
        + (0.05 * judge_norm if judge_norm is not None else 0.0)
    )
    penalties = 0.0
    generic_high = is_generic_high_level_section(row)
    penalized_type = is_penalized_section_type(row.get("section_type"), penalized_types)
    if generic_high:
        penalties += 0.05 if support_score >= 0.72 else 0.09
    if penalized_type:
        penalties += float(options.penalized_type_penalty)
    if int(row.get("supporting_passage_count") or 0) <= 1:
        penalties += 0.05
    penalties += min(0.18, 0.05 * len(list(row.get("judge_exclusion_violations") or [])))
    probability = round(clamp01(probability - penalties), 8)
    score = round(probability * 100.0, 2)
    coverage_ids = [
        str(value)
        for value in list(row.get("trusted_subpoint_ids") or row.get("chosen_subpoint_ids") or [])
        if str(value)
    ]
    return {
        "section_probability": probability,
        "score_0_to_100": score,
        "score_band": section_band(score),
        "support_strength_score": round(support_score, 8),
        "support_strength": support_strength_label(support_score),
        "subpoint_coverage_ratio": coverage_ratio,
        "subpoint_coverage_ids": coverage_ids,
        "generic_title": bool(row.get("generic_title")),
        "generic_high_level": generic_high,
        "penalized_section_type": penalized_type,
    }


def build_doc_decision(
    doc_rows: List[Dict[str, Any]],
    *,
    active_subpoint_ids: Iterable[str],
    penalized_types: Iterable[str],
    options: PhaseGOptions,
) -> Dict[str, Any]:
    sorted_rows = sorted(doc_rows, key=lambda row: (float(row.get("score_0_to_100") or 0.0), float(row.get("section_probability") or 0.0)), reverse=True)
    if not sorted_rows:
        return {
            "has_useful_information": False,
            "doc_match_probability": 0.0,
            "abstention_reason": "no_ranked_sections",
            "top_section_id": None,
            "top_section_title": None,
            "top_section_score": 0.0,
            "top3_mean_score": 0.0,
            "top1_top2_margin": 0.0,
            "num_sections_above_useful": 0,
            "num_sections_above_partial": 0,
            "covered_subpoint_ids": [],
            "covered_subpoint_ratio": 0.0,
            "support_mean_score": 0.0,
            "judge_mean_score": 0.0,
            "only_generic_high_sections": False,
            "only_penalized_high_sections": False,
        }
    top1 = sorted_rows[0]
    top2 = sorted_rows[1] if len(sorted_rows) >= 2 else {}
    useful_rows = [row for row in sorted_rows if float(row.get("score_0_to_100") or 0.0) >= float(options.section_useful_threshold)]
    partial_rows = [row for row in sorted_rows if float(row.get("score_0_to_100") or 0.0) >= float(options.section_partial_threshold)]
    high_rows = partial_rows[: max(1, int(options.top_k_for_doc_features))]
    covered_subpoint_ids = unique_nonempty(
        value
        for row in high_rows
        for value in list(row.get("subpoint_coverage_ids") or [])
    )
    active = {str(value) for value in active_subpoint_ids if str(value)}
    coverage_ratio = round(safe_div(len(set(covered_subpoint_ids) & active), len(active)), 8) if active else 0.0
    support_mean = safe_mean(float(row.get("support_strength_score") or 0.0) for row in high_rows)
    judge_mean = safe_mean(clamp01(row.get("judge_score")) for row in high_rows if row.get("judge_score") is not None)
    top1_prob = clamp01(top1.get("section_probability"))
    top3_mean_prob = top_n_mean((row.get("section_probability") for row in sorted_rows), 3)
    margin = max(0.0, float(top1.get("section_probability") or 0.0) - float(top2.get("section_probability") or 0.0))
    useful_count_norm = min(1.0, safe_div(len(useful_rows), 3.0))
    partial_count_norm = min(1.0, safe_div(len(partial_rows), 4.0))
    only_generic_high = bool(high_rows) and all(bool(row.get("generic_high_level")) for row in high_rows)
    only_penalized_high = bool(high_rows) and all(bool(row.get("penalized_section_type")) for row in high_rows)
    probability = (
        (0.42 * top1_prob)
        + (0.18 * top3_mean_prob)
        + (0.10 * min(1.0, margin / 0.15))
        + (0.10 * useful_count_norm)
        + (0.08 * partial_count_norm)
        + (0.07 * coverage_ratio)
        + (0.03 * clamp01(support_mean))
        + (0.02 * clamp01(judge_mean))
    )
    if float(top1.get("score_0_to_100") or 0.0) >= float(options.strong_top_section_floor) and float(top1.get("support_strength_score") or 0.0) >= 0.72:
        probability += 0.04
    if only_generic_high:
        probability -= float(options.generic_only_penalty)
    elif any(bool(row.get("generic_high_level")) for row in high_rows):
        probability -= float(options.generic_high_penalty)
    if only_penalized_high:
        probability -= float(options.penalized_type_penalty)
    if len(partial_rows) <= 0:
        probability -= 0.25
    if len(useful_rows) <= 0 and float(top1.get("score_0_to_100") or 0.0) < float(options.strong_top_section_floor):
        probability -= 0.08
    probability = round(clamp01(probability), 8)

    strong_partial_case = (
        float(top1.get("score_0_to_100") or 0.0) >= max(float(options.section_partial_threshold) + 6.0, float(options.top_section_floor) - 1.0)
        and float(top_n_mean((row.get("score_0_to_100") for row in sorted_rows), 3)) >= float(options.section_partial_threshold) + 3.0
        and coverage_ratio >= (2.0 / 3.0)
        and clamp01(support_mean) >= 0.72
        and not only_generic_high
        and not only_penalized_high
        and int(top1.get("supporting_passage_count") or 0) >= 1
    )
    if strong_partial_case:
        probability = round(max(probability, float(options.doc_probability_threshold) + 0.02), 8)

    has_useful_information = (
        probability >= float(options.doc_probability_threshold)
        and float(top1.get("score_0_to_100") or 0.0) >= float(options.top_section_floor)
        and len(useful_rows) >= int(options.min_doc_sections_for_useful)
        and len(partial_rows) >= int(options.min_doc_partial_sections)
        and not only_penalized_high
        and int(top1.get("supporting_passage_count") or 0) >= int(options.min_top_supporting_passages)
    )
    if float(top1.get("score_0_to_100") or 0.0) >= float(options.strong_top_section_floor) and float(top1.get("support_strength_score") or 0.0) >= 0.78 and not only_penalized_high:
        has_useful_information = True
    if strong_partial_case:
        has_useful_information = True
    if float(top1.get("score_0_to_100") or 0.0) < float(options.top_section_floor) and not strong_partial_case:
        has_useful_information = False

    abstention_reason = None
    if not has_useful_information:
        if float(top1.get("score_0_to_100") or 0.0) < float(options.top_section_floor):
            abstention_reason = "top_section_below_threshold"
        elif only_penalized_high:
            abstention_reason = "only_penalized_sections_ranked_high"
        elif only_generic_high:
            abstention_reason = "only_generic_sections_ranked_high"
        elif len(partial_rows) < int(options.min_doc_partial_sections):
            abstention_reason = "insufficient_supported_sections"
        elif int(top1.get("supporting_passage_count") or 0) < int(options.min_top_supporting_passages):
            abstention_reason = "insufficient_support_strength"
        else:
            abstention_reason = "low_document_match_probability"

    return {
        "has_useful_information": bool(has_useful_information),
        "doc_match_probability": probability,
        "abstention_reason": abstention_reason,
        "top_section_id": top1.get("section_id"),
        "top_section_title": top1.get("title"),
        "top_section_score": round(float(top1.get("score_0_to_100") or 0.0), 2),
        "top3_mean_score": round(top_n_mean((row.get("score_0_to_100") for row in sorted_rows), 3), 2),
        "top1_top2_margin": round(max(0.0, float(top1.get("score_0_to_100") or 0.0) - float(top2.get("score_0_to_100") or 0.0)), 2),
        "num_sections_above_useful": len(useful_rows),
        "num_sections_above_partial": len(partial_rows),
        "covered_subpoint_ids": covered_subpoint_ids,
        "covered_subpoint_ratio": coverage_ratio,
        "support_mean_score": round(clamp01(support_mean), 8),
        "judge_mean_score": round(clamp01(judge_mean), 8),
        "only_generic_high_sections": only_generic_high,
        "only_penalized_high_sections": only_penalized_high,
    }


def calibration_trace_payload(options: PhaseGOptions, labels_available: bool) -> Dict[str, Any]:
    sklearn_available = bool(CalibratedClassifierCV is not None and LogisticRegression is not None)
    requested_mode = str(options.calibration_mode or "auto")
    effective_mode = "provisional_rules"
    reason = "labels unavailable"
    if requested_mode == "disabled":
        effective_mode = "disabled"
        reason = "calibration explicitly disabled"
    elif requested_mode == "provisional_rules":
        effective_mode = "provisional_rules"
        reason = "provisional rules requested"
    elif requested_mode == "auto":
        if labels_available and sklearn_available:
            effective_mode = "learned_calibration"
            reason = "labels and sklearn available"
        else:
            effective_mode = "provisional_rules"
            reason = "labels unavailable" if not labels_available else "sklearn unavailable"
    return {
        "generated_at_utc": utc_now_iso(),
        "requested_mode": requested_mode,
        "effective_mode": effective_mode,
        "labels_available": bool(labels_available),
        "sklearn_available": sklearn_available,
        "status": "not_used" if effective_mode != "learned_calibration" else "ready_but_not_implemented",
        "reason": reason,
        "recommended_tool": "CalibratedClassifierCV",
        "import_error": PHASE_G_SKLEARN_IMPORT_ERROR,
    }


def build_phase_g_preview(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    preview = []
    for row in rows[: max(1, int(limit))]:
        preview.append(
            {
                "global_rank": row.get("global_rank"),
                "doc_id": row.get("doc_id"),
                "title": row.get("title"),
                "section_type": row.get("section_type"),
                "pages": f"{row.get('page_start')}-{row.get('page_end')}",
                "score_0_to_100": row.get("score_0_to_100"),
                "score_band": row.get("score_band"),
                "support_strength": row.get("support_strength"),
                "doc_match_probability": row.get("doc_match_probability"),
                "has_useful_information": row.get("has_useful_information"),
            }
        )
    return preview


def run_phase_g(run_ctx: Any, *, options: PhaseGOptions, stable_hash_fn=None, log_event_fn=None, run_logger=None) -> Dict[str, Any]:
    opt = options.normalized()
    final_dir = ensure_dir(Path(run_ctx.artifacts.final_dir))
    config_path = final_dir / "phase_g_config.json"
    runtime_path = final_dir / "phase_g_runtime.json"
    summary_path = final_dir / "phase_g_summary.json"
    assessment_path = final_dir / "phase_g_assessment.json"
    per_pdf_rankings_path = final_dir / "per_pdf_rankings.json"
    global_rankings_path = final_dir / "global_rankings.json"
    output_path = final_dir / "output.json"
    section_scores_path = final_dir / "section_scores.jsonl"
    doc_features_path = final_dir / "doc_features.jsonl"
    calibration_trace_path = final_dir / "calibration_trace.json"

    if not bool(opt.force_rebuild):
        try:
            cached_result = build_phase_g_cache_result(run_ctx)
            from pdf_reporting import update_run_pdf_reports

            update_run_pdf_reports(run_ctx, phase_name="phase_g")
            return cached_result
        except Exception:
            pass

    write_json(runtime_path, {"generated_at_utc": utc_now_iso(), "phase": "phase_g", "options": json_safe(asdict(opt)), "capabilities": phase_g_capabilities()})
    write_json(config_path, {"generated_at_utc": utc_now_iso(), "phase": "phase_g", "options": json_safe(asdict(opt))})

    normalized_dir = Path(run_ctx.artifacts.normalized_dir)
    rerank_dir = Path(run_ctx.artifacts.rerank_dir)
    rerank_results_path = rerank_dir / "rerank_results.jsonl"
    documents_path = normalized_dir / "documents.jsonl"
    query_plan_path = Path(run_ctx.artifacts.query_plan_json)
    phase_e_support_path = Path(run_ctx.artifacts.retrieval_dir) / "phase_e_subpoint_support.json"
    required = [rerank_results_path, documents_path, query_plan_path, phase_e_support_path]
    if not all(path.exists() for path in required):
        raise FileNotFoundError("Phase G requires Phase C, Phase D, Phase E, and Phase F artifacts.")

    rerank_rows = read_jsonl_rows(rerank_results_path)
    documents = read_jsonl_rows(documents_path)
    query_plan = dict((read_json(query_plan_path).get("query_plan") or {}))
    phase_e_support = read_json(phase_e_support_path)
    labels_available = False
    calibration_trace = calibration_trace_payload(opt, labels_available=labels_available)
    write_json(calibration_trace_path, calibration_trace)

    active_subpoint_ids = list(phase_e_support.get("active_subpoint_ids") or [])
    if not active_subpoint_ids:
        active_subpoint_ids = [str(item.get("subpoint_id") or "") for item in list(query_plan.get("subpoints") or []) if str(item.get("subpoint_id") or "")]
    penalized_types = unique_nonempty(list(query_plan.get("penalized_section_types") or [])) or sorted(PHASE_G_PENALIZED_SECTION_TYPES)

    section_score_rows = []
    for row in rerank_rows:
        scored = provisional_section_probability(row, active_subpoint_ids=active_subpoint_ids, penalized_types=penalized_types, options=opt)
        section_score_rows.append(
            {
                **row,
                **scored,
                "evidence_preview": evidence_preview_rows(row, max_rows=opt.support_preview_count, max_chars=opt.support_preview_max_chars),
            }
        )
    section_score_rows.sort(
        key=lambda row: (
            float(row.get("score_0_to_100") or 0.0),
            float(row.get("section_probability") or 0.0),
            -int(row.get("rerank_rank") or 10_000),
        ),
        reverse=True,
    )
    for idx, row in enumerate(section_score_rows, 1):
        row["global_rank"] = idx
    write_jsonl_rows(section_scores_path, section_score_rows)

    rows_by_doc = defaultdict(list)
    for row in section_score_rows:
        rows_by_doc[str(row.get("doc_id") or "")].append(row)

    doc_feature_rows = []
    per_pdf_documents = []
    documents_by_id = {str(row.get("doc_id") or ""): row for row in documents}
    for document in documents:
        doc_id = str(document.get("doc_id") or "")
        doc_rows = sorted(rows_by_doc.get(doc_id) or [], key=lambda row: float(row.get("score_0_to_100") or 0.0), reverse=True)
        decision = build_doc_decision(doc_rows, active_subpoint_ids=active_subpoint_ids, penalized_types=penalized_types, options=opt)
        feature_row = {
            "doc_id": doc_id,
            "doc_title": document.get("title"),
            "page_count": document.get("page_count"),
            **decision,
        }
        doc_feature_rows.append(feature_row)
        per_pdf_documents.append(
            {
                "doc_id": doc_id,
                "doc_title": document.get("title"),
                "page_count": document.get("page_count"),
                **decision,
                "top_sections": [
                    {
                        "section_id": row.get("section_id"),
                        "title": row.get("title"),
                        "section_type": row.get("section_type"),
                        "page_start": row.get("page_start"),
                        "page_end": row.get("page_end"),
                        "score_0_to_100": row.get("score_0_to_100"),
                        "score_band": row.get("score_band"),
                        "support_strength": row.get("support_strength"),
                        "subpoint_coverage_ids": row.get("subpoint_coverage_ids"),
                        "evidence_preview": row.get("evidence_preview"),
                    }
                    for row in doc_rows[: int(opt.top_sections_per_doc)]
                ],
            }
        )
    doc_feature_rows.sort(key=lambda row: (bool(row.get("has_useful_information")), float(row.get("doc_match_probability") or 0.0), float(row.get("top_section_score") or 0.0)), reverse=True)
    per_pdf_documents.sort(key=lambda row: (bool(row.get("has_useful_information")), float(row.get("doc_match_probability") or 0.0), float(row.get("top_section_score") or 0.0)), reverse=True)
    write_jsonl_rows(doc_features_path, doc_feature_rows)

    doc_decision_by_id = {str(row.get("doc_id") or ""): row for row in doc_feature_rows}
    global_rows = []
    for row in section_score_rows:
        decision = dict(doc_decision_by_id.get(str(row.get("doc_id") or "")) or {})
        global_rows.append(
            {
                "global_rank": row.get("global_rank"),
                "doc_id": row.get("doc_id"),
                "doc_title": row.get("doc_title") or (documents_by_id.get(str(row.get("doc_id") or ""), {}) or {}).get("title"),
                "section_id": row.get("section_id"),
                "title": row.get("title"),
                "section_type": row.get("section_type"),
                "page_start": row.get("page_start"),
                "page_end": row.get("page_end"),
                "score_0_to_100": row.get("score_0_to_100"),
                "score_band": row.get("score_band"),
                "support_strength": row.get("support_strength"),
                "subpoint_coverage_ids": row.get("subpoint_coverage_ids"),
                "has_useful_information": decision.get("has_useful_information"),
                "doc_match_probability": decision.get("doc_match_probability"),
            }
        )
    global_rankings = {
        "generated_at_utc": utc_now_iso(),
        "run_id": run_ctx.run_id,
        "phase": "phase_g",
        "rows": global_rows[: int(opt.top_global_sections)],
    }
    per_pdf_rankings = {
        "generated_at_utc": utc_now_iso(),
        "run_id": run_ctx.run_id,
        "phase": "phase_g",
        "documents": per_pdf_documents,
    }
    write_json(global_rankings_path, global_rankings)
    write_json(per_pdf_rankings_path, per_pdf_rankings)

    useful_docs = [row for row in doc_feature_rows if bool(row.get("has_useful_information"))]
    no_match_docs = [row for row in doc_feature_rows if not bool(row.get("has_useful_information"))]
    threshold_window_rows = [
        {
            "doc_id": row.get("doc_id"),
            "doc_title": row.get("doc_title"),
            "doc_match_probability": row.get("doc_match_probability"),
            "top_section_score": row.get("top_section_score"),
            "abstention_reason": row.get("abstention_reason"),
        }
        for row in sorted(doc_feature_rows, key=lambda item: abs(float(item.get("doc_match_probability") or 0.0) - float(opt.doc_probability_threshold)))
    ][:10]

    output_payload = {
        "generated_at_utc": utc_now_iso(),
        "run_id": run_ctx.run_id,
        "phase": "phase_g",
        "status": "success",
        "chapter_title": clean_text(query_plan.get("chapter_title") or getattr(getattr(run_ctx, "config", None), "chapter_title", "") or ""),
        "has_any_useful_information": bool(useful_docs),
        "useful_pdf_count": len(useful_docs),
        "no_match_pdf_count": len(no_match_docs),
        "documents": per_pdf_documents,
        "global_top_sections": global_rankings["rows"],
    }
    write_json(output_path, output_payload)

    warnings = []
    failures = []
    if not doc_feature_rows:
        failures.append("Phase G did not produce any per-document decisions.")
    if useful_docs and not any(float(row.get("top_section_score") or 0.0) >= float(opt.strong_top_section_floor) for row in useful_docs):
        warnings.append("No useful PDF has a top section above the strong threshold.")
    if useful_docs and all(bool(row.get("only_generic_high_sections")) for row in useful_docs):
        warnings.append("All useful PDFs are carried only by generic high-level sections.")
    if not useful_docs:
        warnings.append("Phase G classified every PDF as no-match.")

    qc_rows = [
        qc_row(check="section_scores", status="OK" if section_score_rows else "FAIL", value=len(section_score_rows), expected=">= 1", why="Phase G needs section-level calibrated scores.", fix="inspect rerank_results.jsonl and section_scores.jsonl"),
        qc_row(check="useful_pdf_count", status="OK" if useful_docs else "WARN", value=len(useful_docs), expected=">= 1 preferred", why="The pipeline should surface useful PDFs when relevant material exists.", fix="inspect document thresholds and rerank evidence"),
        qc_row(check="no_match_pdf_count", status="OK" if no_match_docs else "WARN", value=len(no_match_docs), expected=">= 0", why="Phase G must support explicit abstention for non-matching PDFs.", fix="inspect calibration rules and doc-level penalties"),
        qc_row(check="threshold_window_rows", status="OK" if threshold_window_rows else "WARN", value=len(threshold_window_rows), expected=">= 1", why="Near-threshold documents are the main audit target for calibration.", fix="inspect doc_features.jsonl and output.json"),
        qc_row(check="calibration_mode", status="OK", value=calibration_trace.get('effective_mode'), expected="provisional_rules before labels exist", why="Phase G should be explicit about whether scores are learned or rule-based.", fix="inspect calibration_trace.json"),
    ]

    status = "failed" if failures else ("success_with_warnings" if warnings else "success")
    quality_band = "insufficient" if failures else ("acceptable_with_issues" if warnings else "high")
    assessment = {
        "status": status,
        "quality_band": quality_band,
        "can_continue_to_next_phase": not failures,
        "failures": failures,
        "warnings": warnings,
        "counts": {
            "section_scores": len(section_score_rows),
            "useful_pdf_count": len(useful_docs),
            "no_match_pdf_count": len(no_match_docs),
            "threshold_window_rows": len(threshold_window_rows),
        },
        "calibration_trace": calibration_trace,
        "qc_rows": qc_rows,
    }
    metrics_update = {
        "status": status,
        "quality_band": quality_band,
        "useful_pdf_count": len(useful_docs),
        "no_match_pdf_count": len(no_match_docs),
        "phase_g_summary_path": rel_to_run(Path(run_ctx.run_dir), summary_path),
        "phase_g_assessment_path": rel_to_run(Path(run_ctx.run_dir), assessment_path),
        "output_path": rel_to_run(Path(run_ctx.run_dir), output_path),
    }
    summary = {
        "generated_at_utc": utc_now_iso(),
        "run_id": run_ctx.run_id,
        "phase": "phase_g",
        "options": json_safe(asdict(opt)),
        "capabilities": phase_g_capabilities(),
        "calibration_trace": calibration_trace,
        "per_pdf_rankings_path": rel_to_run(Path(run_ctx.run_dir), per_pdf_rankings_path),
        "global_rankings_path": rel_to_run(Path(run_ctx.run_dir), global_rankings_path),
        "output_path": rel_to_run(Path(run_ctx.run_dir), output_path),
        "preview_rows": build_phase_g_preview(global_rows, 20),
        "threshold_window_rows": threshold_window_rows,
        "assessment": {k: v for k, v in assessment.items() if k != "qc_rows"},
        "qc_rows": qc_rows,
        "metrics_update": metrics_update,
    }
    write_json(summary_path, summary)
    write_json(
        assessment_path,
        {
            "generated_at_utc": utc_now_iso(),
            "run_id": run_ctx.run_id,
            "phase": "phase_g",
            "assessment": {k: v for k, v in assessment.items() if k != "qc_rows"},
            "qc_rows": qc_rows,
            "output_path": rel_to_run(Path(run_ctx.run_dir), output_path),
        },
    )

    if log_event_fn is not None:
        log_event_fn(
            run_ctx,
            stage="phase_g",
            event="phase_finished",
            status=status,
            useful_pdf_count=len(useful_docs),
            no_match_pdf_count=len(no_match_docs),
            calibration_mode=calibration_trace.get("effective_mode"),
        )
    if run_logger is not None:
        run_logger.info(
            "Phase G finished | status=%s | useful_pdfs=%s | no_match_pdfs=%s | calibration_mode=%s",
            status,
            len(useful_docs),
            len(no_match_docs),
            calibration_trace.get("effective_mode"),
        )

    from pdf_reporting import update_run_pdf_reports

    update_run_pdf_reports(run_ctx, phase_name="phase_g")

    return {
        "config_path": config_path,
        "runtime_path": runtime_path,
        "summary_path": summary_path,
        "assessment_path": assessment_path,
        "per_pdf_rankings_path": per_pdf_rankings_path,
        "global_rankings_path": global_rankings_path,
        "output_path": output_path,
        "section_scores_path": section_scores_path,
        "doc_features_path": doc_features_path,
        "calibration_trace_path": calibration_trace_path,
        "section_score_rows": section_score_rows,
        "doc_feature_rows": doc_feature_rows,
        "per_pdf_rankings": per_pdf_rankings,
        "global_rankings": global_rankings,
        "output_payload": output_payload,
        "summary": summary,
        "assessment": assessment,
        "qc_rows": qc_rows,
        "metrics_update": metrics_update,
        "cache_hit": False,
    }


def phase_summary_exists(run_ctx: Any, phase_name: str) -> bool:
    mapping = {
        "phase_b": Path(run_ctx.artifacts.parser_dir) / "phase_b_summary.json",
        "phase_c": Path(run_ctx.artifacts.normalized_dir) / "phase_c_summary.json",
        "phase_d": Path(run_ctx.artifacts.retrieval_dir) / "phase_d_summary.json",
        "phase_e": Path(run_ctx.artifacts.retrieval_dir) / "phase_e_summary.json",
        "phase_f": Path(run_ctx.artifacts.rerank_dir) / "phase_f_summary.json",
        "phase_g": Path(run_ctx.artifacts.final_dir) / "phase_g_summary.json",
    }
    path = mapping.get(phase_name)
    return bool(path and path.exists())


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase G lab for the PDF scan pipeline.")
    parser.add_argument("--input-mode", choices=["small_gold", "manual"], default="small_gold")
    parser.add_argument("--pipeline-version", default="pdf_scan_v3_phase_g_lab")
    parser.add_argument("--force-rebuild-phase-a", action="store_true")
    parser.add_argument("--force-rebuild-phase-b", action="store_true")
    parser.add_argument("--force-rebuild-phase-c", action="store_true")
    parser.add_argument("--force-rebuild-phase-d", action="store_true")
    parser.add_argument("--force-rebuild-phase-e", action="store_true")
    parser.add_argument("--force-rebuild-phase-f", action="store_true")
    parser.add_argument("--force-rebuild-phase-g", action="store_true")
    parser.add_argument("--suite-manifest", default="benchmark/small_gold/manifests/suite_manifest.json")
    parser.add_argument("--chapter-index", type=int, default=0)
    parser.add_argument("--doc-limit", type=int, default=None)
    parser.add_argument("--include-doc-id", action="append", default=[])
    parser.add_argument("--exclude-doc-id", action="append", default=[])
    parser.add_argument("--chapter-title", default="")
    parser.add_argument("--chapter-description", default="")
    parser.add_argument("--pdf", action="append", default=[])
    parser.add_argument("--pdf-dir", default="")
    parser.add_argument("--pdf-glob", default="*.pdf")
    parser.add_argument("--pdf-recursive", action="store_true")
    parser.add_argument("--max-pdfs", type=int, default=20)
    parser.add_argument("--grobid-base-url", default=(os.getenv("GROBID_URL") or os.getenv("GROBID_BASE_URL") or "").strip())
    parser.add_argument("--planner-model", default=(os.getenv("OPENAI_PDF_SCAN_PLANNER_MODEL") or os.getenv("OPENAI_PDF_SCAN_MODEL") or "gpt-5-mini").strip() or "gpt-5-mini")
    parser.add_argument("--planner-reasoning-effort", default="low")
    parser.add_argument("--no-openai-planner", action="store_true")
    parser.add_argument("--embed-model", default=(os.getenv("OPENAI_PDF_SCAN_EMBED_MODEL") or "text-embedding-3-small").strip() or "text-embedding-3-small")
    parser.add_argument("--no-openai-dense", action="store_true")
    parser.add_argument("--rerank-model", default=PHASE_F_DEFAULT_RERANK_MODEL)
    parser.add_argument("--rerank-top-k", type=int, default=60)
    parser.add_argument("--rerank-batch-size", type=int, default=8)
    parser.add_argument("--rerank-max-length", type=int, default=1536)
    parser.add_argument("--judge-model", default=PHASE_F_DEFAULT_JUDGE_MODEL)
    parser.add_argument("--no-openai-judge", action="store_true")
    parser.add_argument("--judge-candidate-limit", type=int, default=12)
    parser.add_argument("--judge-max-per-doc", type=int, default=2)
    parser.add_argument("--calibration-mode", default="auto")
    parser.add_argument("--top-sections-per-doc", type=int, default=5)
    parser.add_argument("--top-global-sections", type=int, default=25)
    parser.add_argument("--section-useful-threshold", type=int, default=70)
    parser.add_argument("--section-partial-threshold", type=int, default=55)
    parser.add_argument("--doc-probability-threshold", type=float, default=0.63)
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    phase_a_args = Namespace(
        input_mode=args.input_mode,
        pipeline_version=args.pipeline_version,
        force_rebuild=bool(args.force_rebuild_phase_a),
        runs_root="",
        suite_manifest=args.suite_manifest,
        chapter_index=int(args.chapter_index),
        doc_limit=args.doc_limit,
        include_doc_id=list(args.include_doc_id or []),
        exclude_doc_id=list(args.exclude_doc_id or []),
        chapter_title=str(args.chapter_title or ""),
        chapter_description=str(args.chapter_description or ""),
        pdf=list(args.pdf or []),
        pdf_dir=str(args.pdf_dir or ""),
        pdf_glob=str(args.pdf_glob or "*.pdf"),
        pdf_recursive=bool(args.pdf_recursive),
        max_pdfs=int(args.max_pdfs),
    )
    phase_a_result = run_phase_a(phase_a_args)
    run_ctx = phase_a_result["run_ctx"]
    pdf_manifest = phase_a_result["manifest_rows"]

    from phase_b_lab import PhaseBOptions, run_phase_b
    from phase_c_lab import PhaseCOptions, run_phase_c
    from phase_d_lab import PhaseDOptions, run_phase_d
    from phase_e_lab import PhaseEOptions, run_phase_e
    from phase_f_lab import PhaseFOptions, run_phase_f

    if bool(args.force_rebuild_phase_b) or not phase_summary_exists(run_ctx, "phase_b"):
        phase_b_logger = setup_run_logger(run_ctx)
        phase_b_options = PhaseBOptions(
            force_rebuild=bool(args.force_rebuild_phase_b),
            doc_limit=args.doc_limit,
            include_doc_ids=list(args.include_doc_id or []),
            exclude_doc_ids=list(args.exclude_doc_id or []),
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
            phase_b_result = run_phase_b(run_ctx, pdf_manifest, phase_b_options, stable_hash_fn=stable_hash, log_event_fn=log_event, run_logger=phase_b_logger)
            metrics = load_metrics(run_ctx)
            metrics.setdefault("stages", {}).setdefault("phase_b", {}).update(phase_b_result["metrics_update"])
            save_metrics(run_ctx, metrics)

    if bool(args.force_rebuild_phase_c) or not phase_summary_exists(run_ctx, "phase_c"):
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
            phase_c_result = run_phase_c(run_ctx, phase_c_options, stable_hash_fn=stable_hash, log_event_fn=log_event, run_logger=phase_c_logger)
            metrics = load_metrics(run_ctx)
            metrics.setdefault("stages", {}).setdefault("phase_c", {}).update(phase_c_result["metrics_update"])
            save_metrics(run_ctx, metrics)

    if bool(args.force_rebuild_phase_d) or not phase_summary_exists(run_ctx, "phase_d"):
        phase_d_logger = setup_run_logger(run_ctx)
        phase_d_options = PhaseDOptions(
            force_rebuild=bool(args.force_rebuild_phase_d),
            use_openai_planner=not bool(args.no_openai_planner),
            allow_heuristic_fallback=True,
            openai_model=str(args.planner_model or "gpt-5-mini").strip() or "gpt-5-mini",
            reasoning_effort=str(args.planner_reasoning_effort or "low").strip() or "low",
            max_completion_tokens=1400,
            temperature=0.0,
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
            metrics = load_metrics(run_ctx)
            metrics.setdefault("stages", {}).setdefault("phase_d", {}).update(phase_d_result["metrics_update"])
            save_metrics(run_ctx, metrics)

    if bool(args.force_rebuild_phase_e) or not phase_summary_exists(run_ctx, "phase_e"):
        phase_e_logger = setup_run_logger(run_ctx)
        phase_e_options = PhaseEOptions(
            force_rebuild=bool(args.force_rebuild_phase_e),
            candidate_limit_per_lane=80,
            fused_candidate_limit=120,
            per_view_limit_multiplier=2,
            rrf_k=60,
            lexical_k1=1.2,
            lexical_b=0.75,
            use_openai_dense=not bool(args.no_openai_dense),
            allow_lexical_only_fallback=True,
            openai_embedding_model=str(args.embed_model or "text-embedding-3-small").strip() or "text-embedding-3-small",
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
            subpoint_min_supported_candidates=1,
            subpoint_max_preview_rows=10,
            diversity_lambda=0.45,
        )
        with stage_timer(run_ctx, "phase_e"):
            phase_e_result = run_phase_e(run_ctx, options=phase_e_options, stable_hash_fn=stable_hash, log_event_fn=log_event, run_logger=phase_e_logger)
            metrics = load_metrics(run_ctx)
            metrics.setdefault("stages", {}).setdefault("phase_e", {}).update(phase_e_result["metrics_update"])
            save_metrics(run_ctx, metrics)

    if bool(args.force_rebuild_phase_f) or not phase_summary_exists(run_ctx, "phase_f"):
        phase_f_logger = setup_run_logger(run_ctx)
        phase_f_options = PhaseFOptions(
            force_rebuild=bool(args.force_rebuild_phase_f),
            rerank_top_k=int(args.rerank_top_k),
            inject_doc_top_candidates=True,
            cross_encoder_model=str(args.rerank_model or PHASE_F_DEFAULT_RERANK_MODEL).strip() or PHASE_F_DEFAULT_RERANK_MODEL,
            cross_encoder_batch_size=int(args.rerank_batch_size),
            cross_encoder_max_length=int(args.rerank_max_length),
            cross_encoder_subpoint_limit=2,
            section_excerpt_max_chars=2200,
            supporting_passage_count=3,
            passage_excerpt_max_chars=520,
            use_openai_judge=not bool(args.no_openai_judge),
            judge_model=str(args.judge_model or PHASE_F_DEFAULT_JUDGE_MODEL).strip() or PHASE_F_DEFAULT_JUDGE_MODEL,
            judge_reasoning_effort="low",
            judge_candidate_limit=int(args.judge_candidate_limit),
            judge_max_per_doc=int(args.judge_max_per_doc),
            judge_max_output_tokens=550,
            top_candidate_preview_count=20,
        )
        with stage_timer(run_ctx, "phase_f"):
            phase_f_result = run_phase_f(run_ctx, options=phase_f_options, stable_hash_fn=stable_hash, log_event_fn=log_event, run_logger=phase_f_logger)
            metrics = load_metrics(run_ctx)
            metrics.setdefault("stages", {}).setdefault("phase_f", {}).update(phase_f_result["metrics_update"])
            save_metrics(run_ctx, metrics)

    phase_g_logger = setup_run_logger(run_ctx)
    phase_g_options = PhaseGOptions(
        force_rebuild=bool(args.force_rebuild_phase_g),
        top_sections_per_doc=int(args.top_sections_per_doc),
        top_global_sections=int(args.top_global_sections),
        section_useful_threshold=int(args.section_useful_threshold),
        section_partial_threshold=int(args.section_partial_threshold),
        doc_probability_threshold=float(args.doc_probability_threshold),
        calibration_mode=str(args.calibration_mode or "auto"),
    )
    with stage_timer(run_ctx, "phase_g"):
        phase_g_result = run_phase_g(run_ctx, options=phase_g_options, stable_hash_fn=stable_hash, log_event_fn=log_event, run_logger=phase_g_logger)
        metrics = load_metrics(run_ctx)
        metrics.setdefault("stages", {}).setdefault("phase_g", {}).update(phase_g_result["metrics_update"])
        save_metrics(run_ctx, metrics)

    rel = lambda path: rel_to_run(Path(run_ctx.run_dir), Path(path))
    print_section("Phase G Lab - Capabilities")
    print_kv({
        "sklearn_available": phase_g_capabilities().get("sklearn_available"),
        "calibration_mode": (phase_g_result.get("summary") or {}).get("calibration_trace", {}).get("effective_mode"),
        "cache_hit": phase_g_result.get("cache_hit"),
    })
    print_section("Phase G Lab - What Happened")
    print_kv({
        "run_id": run_ctx.run_id,
        "section_scores_jsonl": rel(phase_g_result["section_scores_path"]),
        "doc_features_jsonl": rel(phase_g_result["doc_features_path"]),
        "per_pdf_rankings_json": rel(phase_g_result["per_pdf_rankings_path"]),
        "global_rankings_json": rel(phase_g_result["global_rankings_path"]),
        "output_json": rel(phase_g_result["output_path"]),
        "phase_g_summary_json": rel(phase_g_result["summary_path"]),
        "phase_g_assessment_json": rel(phase_g_result["assessment_path"]),
        "section_scores": len(phase_g_result["section_score_rows"]),
        "doc_decisions": len(phase_g_result["doc_feature_rows"]),
        "useful_pdfs": len([row for row in phase_g_result["doc_feature_rows"] if row.get("has_useful_information")]),
        "phase_status": phase_g_result["assessment"].get("status"),
    })
    print_section("Phase G Lab - Per-PDF Decisions")
    print_table(phase_g_result["doc_feature_rows"], columns=["doc_id", "doc_title", "has_useful_information", "doc_match_probability", "top_section_title", "top_section_score", "num_sections_above_useful", "covered_subpoint_ratio", "abstention_reason"], max_rows=30, max_col_width=54)
    print_section("Phase G Lab - Global Preview")
    print_table((phase_g_result.get("summary") or {}).get("preview_rows") or [], columns=["global_rank", "doc_id", "title", "section_type", "pages", "score_0_to_100", "score_band", "support_strength", "doc_match_probability", "has_useful_information"], max_rows=25, max_col_width=54)
    print_section("Phase G Lab - Threshold Window")
    print_table((phase_g_result.get("summary") or {}).get("threshold_window_rows") or [], columns=["doc_id", "doc_title", "doc_match_probability", "top_section_score", "abstention_reason"], max_rows=15, max_col_width=54)
    print_section("Phase G Lab - QC")
    print_table(phase_g_result["qc_rows"], columns=["check", "status", "value", "expected", "why", "fix"], max_rows=20, max_col_width=50)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
