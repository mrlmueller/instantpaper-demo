from __future__ import annotations

import asyncio
import json
import os
import shutil
import statistics
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from services.user_key_service import user_key_service

from .phase_f import run_phase_f_embeddings_and_scoring
from .phase_g import run_phase_g_lane_fusion
from .phase_h import run_phase_h_coverage_tags
from .phase_i import run_phase_i_rerank
from .phase_k import run_phase_k_output
from .pipeline import (
    ChapterInput,
    PipelineConfig,
    RunArtifacts,
    RunContext,
    TwoLaneOpenAI,
    TwoLaneStageCost,
    build_candidates_from_raw,
    build_openalex_queries_llm,
    build_s2_bulk_queries_llm,
    fetch_openalex_to_cache,
    fetch_s2_to_cache,
    plan_queries_llm,
    read_json,
    rebuild_aggregate_jsonl,
    stage_timer,
)
from .telemetry import build_two_lane_telemetry
from utils.config import config as app_config


class TwoLaneRunCancelled(RuntimeError):
    pass


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _artifacts_root_local() -> Path:
    return _backend_root() / ".two_lane_artifacts" / "runs"


def _prune_old_runs(root: Path, *, keep: int = 10) -> None:
    try:
        if not root.exists():
            return
        dirs = [p for p in root.iterdir() if p.is_dir()]
        dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for p in dirs[int(keep) :]:
            try:
                shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass
    except Exception:
        return


def _build_run_ctx(*, run_dir: Path, run_id: str) -> RunContext:
    artifacts = RunArtifacts(
        query_plan_json=run_dir / "query_plan.json",
        openalex_queries_json=run_dir / "openalex_queries.json",
        semanticscholar_queries_json=run_dir / "s2_bulk_queries.json",
        openalex_raw_jsonl=run_dir / "openalex_raw.jsonl",
        semanticscholar_raw_jsonl=run_dir / "semanticscholar_raw.jsonl",
        semanticscholar_recommendations_jsonl=run_dir / "s2_recommendations.jsonl",
        candidates_normalized_jsonl=run_dir / "candidates_normalized.jsonl",
        candidates_normalized_csv=run_dir / "candidates_normalized.csv",
        embeddings_manifest_jsonl=run_dir / "embeddings_manifest.jsonl",
        embeddings_manifest_csv=run_dir / "embeddings_manifest.csv",
        embeddings_vectors_dir=run_dir / "embeddings_vectors",
        rerank_results_jsonl=run_dir / "rerank_results.jsonl",
        output_json=run_dir / "output.json",
        logs_jsonl=run_dir / "logs.jsonl",
        run_log=run_dir / "run.log",
        metrics_json=run_dir / "metrics.json",
    )
    return RunContext(repo_root=_repo_root(), run_id=str(run_id), run_dir=Path(run_dir), artifacts=artifacts)


def _derive_costs_from_metrics(
    *,
    metrics: Dict[str, Any],
    run_dir: Optional[Path] = None,
    key_source: str,
    budget_cap_usd: float,
) -> Dict[str, Any]:
    stage_costs: Dict[str, Dict[str, Any]] = {}

    stages = metrics.get("stages") if isinstance(metrics, dict) else None
    if not isinstance(stages, dict):
        stages = {}

    def _sum_openai_attempt_meta(glob_pat: str) -> Optional[Dict[str, Any]]:
        if run_dir is None:
            return None
        files = sorted(run_dir.glob(str(glob_pat)))
        if not files:
            return None
        cost = 0.0
        in_tok = 0
        cached_in_tok = 0
        out_tok = 0
        reqs = 0
        for p in files:
            try:
                meta = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(meta, dict):
                continue
            cost += float(meta.get("cost_usd") or 0.0)
            usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
            in_tok += int((usage or {}).get("input_tokens") or 0)
            cached_in_tok += int((usage or {}).get("cached_input_tokens") or 0)
            out_tok += int((usage or {}).get("output_tokens") or 0)
            reqs += 1
        if reqs <= 0:
            return None
        return {
            "cost_usd": float(cost),
            "input_tokens": int(in_tok),
            "cached_input_tokens": int(cached_in_tok),
            "output_tokens": int(out_tok),
            "requests": int(reqs),
        }

    attempt_meta_glob_by_stage = {
        "phase_b_query_planner": "query_plan_attempt*.openai_meta.json",
        "phase_c_openalex_query_builder": "openalex_queries_attempt*.openai_meta.json",
        "phase_c_s2_query_builder": "s2_bulk_queries_attempt*.openai_meta.json",
    }

    for stage, st_obj in stages.items():
        if not isinstance(st_obj, dict):
            continue

        summed = _sum_openai_attempt_meta(attempt_meta_glob_by_stage.get(str(stage), "")) if str(stage) in attempt_meta_glob_by_stage else None
        if isinstance(summed, dict):
            stage_costs[str(stage)] = summed
            continue

        # LLM json_schema_call stages
        openai_meta = st_obj.get("openai")
        if isinstance(openai_meta, dict):
            usage = openai_meta.get("usage") if isinstance(openai_meta.get("usage"), dict) else {}
            stage_costs[str(stage)] = {
                "cost_usd": float(openai_meta.get("cost_usd") or 0.0),
                "input_tokens": int((usage or {}).get("input_tokens") or 0),
                "cached_input_tokens": int((usage or {}).get("cached_input_tokens") or 0),
                "output_tokens": int((usage or {}).get("output_tokens") or 0),
                "requests": 1,
            }
            continue

        # Embeddings stages
        emb = st_obj.get("embeddings")
        if isinstance(emb, dict) and ("cost_usd" in emb or "prompt_tokens" in emb or "api_calls" in emb):
            stage_costs[str(stage)] = {
                "cost_usd": float(emb.get("cost_usd") or 0.0),
                "input_tokens": int(emb.get("prompt_tokens") or 0),
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "requests": int(emb.get("api_calls") or 0),
            }
            continue

        # Rerank stage (many calls) stores rollup in counts
        if str(stage) == "phase_i_rerank":
            counts = st_obj.get("counts")
            if isinstance(counts, dict):
                stage_costs[str(stage)] = {
                    "cost_usd": float(counts.get("cost_usd_total") or 0.0),
                    "input_tokens": int(counts.get("tokens_in_total") or 0),
                    "cached_input_tokens": int(counts.get("tokens_cached_in_total") or 0),
                    "output_tokens": int(counts.get("tokens_out_total") or 0),
                    "requests": int(counts.get("api_calls") or 0),
                }

    total_cost = float(sum(float(v.get("cost_usd") or 0.0) for v in stage_costs.values()))

    return {
        "total_cost_usd": float(total_cost),
        "stage_costs": stage_costs,
        "key_source": str(key_source),
        "budget_cap_usd": float(budget_cap_usd),
    }


def _derive_effective_settings(*, cfg: PipelineConfig, metrics: Dict[str, Any]) -> Dict[str, Any]:
    masked_settings = cfg.model_dump(mode="json")
    for k in ("openai_api_key", "openalex_api_key", "semanticscholar_api_key"):
        if k in masked_settings:
            masked_settings[k] = None

    stages = metrics.get("stages") if isinstance(metrics, dict) else None
    if not isinstance(stages, dict):
        return masked_settings

    def _model_used(stage: str) -> Optional[str]:
        st = stages.get(stage)
        if not isinstance(st, dict):
            return None
        oa = st.get("openai")
        if isinstance(oa, dict):
            m = str(oa.get("model_used") or oa.get("model_requested") or "").strip()
            return m or None
        if stage == "phase_i_rerank":
            counts = st.get("counts")
            if isinstance(counts, dict):
                m = str(counts.get("model_used") or counts.get("model") or "").strip()
                return m or None
        return None

    def _embedding_model_used() -> Optional[str]:
        # Any embeddings stage is fine; they should all use the same embedding model.
        for st_name in ("phase_f_chunk_embeddings", "phase_f_metadata_embeddings", "phase_f_facet_embeddings"):
            st = stages.get(st_name)
            emb = st.get("embeddings") if isinstance(st, dict) else None
            if isinstance(emb, dict):
                m = str(emb.get("model") or "").strip()
                if m:
                    return m
        return None

    # Override with what actually ran (more accurate for cached/resumed runs too)
    masked_settings["openai_model_planner"] = _model_used("phase_b_query_planner") or masked_settings.get("openai_model_planner")
    masked_settings["openai_model_openalex_query_builder"] = _model_used("phase_c_openalex_query_builder") or masked_settings.get(
        "openai_model_openalex_query_builder"
    )
    masked_settings["openai_model_s2_query_builder"] = _model_used("phase_c_s2_query_builder") or masked_settings.get("openai_model_s2_query_builder")
    masked_settings["openai_model_rerank"] = _model_used("phase_i_rerank") or masked_settings.get("openai_model_rerank")
    masked_settings["embedding_model"] = _embedding_model_used() or masked_settings.get("embedding_model")

    return masked_settings


async def run_two_lane_sources_pipeline(
    *,
    user_id: str,
    projekt_id: str,
    kapitel_id: str,
    run_id: str,
    chapter_title: str,
    chapter_spec_text: str,
    settings: Optional[Dict[str, Any]] = None,
    check_cancel: Optional[Callable[[], Any]] = None,
    on_progress: Optional[Callable[[str, str], Any]] = None,
    on_telemetry: Optional[Callable[[Dict[str, Dict[str, Any]]], Any]] = None,
) -> Dict[str, Any]:
    """
    End-to-end two-lane pipeline runner.

    Returns a dict with `output`, `metrics`, and `costs` suitable for persistence.
    """

    async def _call_maybe_await(fn, *args):
        if fn is None:
            return None
        res0 = fn(*args)
        if asyncio.iscoroutine(res0):
            return await res0
        return res0

    await _call_maybe_await(check_cancel)

    if app_config.IS_CLOUD_RUN:
        tmp_dir_cm = tempfile.TemporaryDirectory(prefix="two_lane_run_")
        run_dir = Path(tmp_dir_cm.name) / str(run_id)
        runs_root = Path(tmp_dir_cm.name)
        keep_artifacts = False
    else:
        runs_root = _artifacts_root_local()
        _prune_old_runs(runs_root, keep=10)
        run_dir = runs_root / str(run_id)
        keep_artifacts = True
        tmp_dir_cm = None

    try:
        run_ctx = _build_run_ctx(run_dir=run_dir, run_id=run_id)
        run_ctx.create_artifact_skeleton(overwrite=False)

        cfg = PipelineConfig.from_env(runs_root=runs_root, pipeline_version="two_lane_v1")
        if isinstance(settings, dict) and settings:
            blocked = {"openai_api_key", "openalex_api_key", "semanticscholar_api_key", "openalex_email", "pipeline_version", "runs_root"}
            cfg = cfg.model_copy(update={k: v for k, v in settings.items() if (k in cfg.model_fields and k not in blocked)})

        force_rebuild = bool(getattr(cfg, "force_rebuild", True))

        async def _check_cancel():
            await _call_maybe_await(check_cancel)

        async def _progress(stage: str, message: str) -> None:
            await _call_maybe_await(on_progress, str(stage), str(message))

        async def _telemetry(docs: Dict[str, Dict[str, Any]]) -> None:
            if not isinstance(docs, dict) or not docs:
                return
            await _call_maybe_await(on_telemetry, {str(k): (v if isinstance(v, dict) else {"value": v}) for k, v in docs.items()})

        chapter_input = ChapterInput(
            chapter_title=str(chapter_title or "").strip(),
            chapter_spec_text=str(chapter_spec_text or "").strip(),
            pipeline_version=str(cfg.pipeline_version or "two_lane_v1"),
        )
        records_openalex: int | None = None
        records_s2: int | None = None
        candidates_total: int | None = None

        # Resume shortcut (local dev): if we already have a valid output.json and force_rebuild=False,
        # skip the expensive pipeline and just reuse artifacts.
        output_path = Path(run_ctx.artifacts.output_json)
        metrics_path = Path(run_ctx.artifacts.metrics_json)
        if not force_rebuild and output_path.exists():
            try:
                output_cached = read_json(output_path)
                if isinstance(output_cached, dict) and str(output_cached.get("schema_version") or "") == "two_lane_output_v1":
                    await _progress("resume_cached_output", "Using cached output.json")

                    metrics_cached = read_json(metrics_path) if metrics_path.exists() else {}
                    costs_cached = _derive_costs_from_metrics(
                        metrics=metrics_cached,
                        run_dir=run_ctx.run_dir,
                        key_source="cached_artifacts",
                        budget_cap_usd=2.0,
                    )
                    effective_settings_cached = _derive_effective_settings(cfg=cfg, metrics=metrics_cached)

                    telemetry_cached = {}
                    try:
                        telemetry_cached = build_two_lane_telemetry(
                            run_ctx=run_ctx,
                            effective_settings=effective_settings_cached,
                            costs=costs_cached,
                            openalex_fetch=None,
                            s2_fetch=None,
                        )
                    except Exception:
                        telemetry_cached = {}

                    return {
                        "run_id": str(run_id),
                        "keep_artifacts": bool(keep_artifacts),
                        "artifacts_dir": str(run_ctx.run_dir) if keep_artifacts else None,
                        "output": output_cached,
                        "metrics": metrics_cached,
                        "costs": costs_cached,
                        "effective_settings": effective_settings_cached,
                        "telemetry": telemetry_cached,
                    }
            except Exception:
                pass

        api_key, key_source = await user_key_service.resolve_api_key_for_user(str(user_id))

        llm = TwoLaneOpenAI(
            user_id=str(user_id),
            projekt_id=str(projekt_id),
            kapitel_id=str(kapitel_id),
            run_id=str(run_id),
            api_key=str(api_key),
            key_source=str(key_source),
            max_total_cost_usd=2.0,
        )

        # Resume: seed live cost snapshot from existing metrics so budget cap + UI reflect prior work.
        if not force_rebuild and metrics_path.exists():
            try:
                metrics_seed = read_json(metrics_path)
                costs_seed = _derive_costs_from_metrics(
                    metrics=metrics_seed, run_dir=run_ctx.run_dir, key_source=str(key_source), budget_cap_usd=float(llm.max_total_cost_usd)
                )
                llm.total_cost_usd = float(costs_seed.get("total_cost_usd") or 0.0)
                llm.budget_exceeded = bool(float(llm.total_cost_usd) > float(llm.max_total_cost_usd))

                stage_costs_seed = costs_seed.get("stage_costs") if isinstance(costs_seed, dict) else None
                if isinstance(stage_costs_seed, dict):
                    llm.stage_costs = {}
                    for stage, rec in stage_costs_seed.items():
                        if not isinstance(rec, dict):
                            continue
                        st: TwoLaneStageCost = llm._stage(str(stage))  # pylint: disable=protected-access
                        st.cost_usd = float(rec.get("cost_usd") or 0.0)
                        st.input_tokens = int(rec.get("input_tokens") or 0)
                        st.cached_input_tokens = int(rec.get("cached_input_tokens") or 0)
                        st.output_tokens = int(rec.get("output_tokens") or 0)
                        st.requests = int(rec.get("requests") or 0)

                await llm._request_live_cost_emit(stage="resume")  # pylint: disable=protected-access
            except Exception:
                pass

        def _query_id(provider: str, i: int, intent: str, language: str) -> str:
            return f"{provider}:{int(i)}:{str(intent or 'unknown').strip() or 'unknown'}:{str(language or 'unknown').strip() or 'unknown'}"

        def _build_min_report(
            *,
            facets_count: int | None = None,
            queries_oa: int | None = None,
            queries_s2: int | None = None,
            records_openalex: int | None = None,
            records_s2: int | None = None,
            candidates_total: int | None = None,
        ) -> Dict[str, Any]:
            return {
                "telemetry_schema_version": 2,
                "kpis": {
                    "seconds_total": None,
                    "total_cost_usd": float(getattr(llm, "total_cost_usd", 0.0) or 0.0),
                    "budget_cap_usd": float(getattr(llm, "max_total_cost_usd", 2.0) or 2.0),
                    "records_total": (None if records_openalex is None or records_s2 is None else int(records_openalex) + int(records_s2)),
                    "records_openalex": (int(records_openalex) if records_openalex is not None else None),
                    "records_semanticscholar": (int(records_s2) if records_s2 is not None else None),
                    "candidates_total": (int(candidates_total) if candidates_total is not None else None),
                    "facets_count": (int(facets_count) if facets_count is not None else None),
                    "queries_total": (None if queries_oa is None or queries_s2 is None else int(queries_oa) + int(queries_s2)),
                    "queries_openalex": (int(queries_oa) if queries_oa is not None else None),
                    "queries_semanticscholar": (int(queries_s2) if queries_s2 is not None else None),
                },
                "stage_tables": {"durations": [], "costs": []},
                "models": {
                    "planner": str(getattr(cfg, "openai_model_planner", "") or "") or None,
                    "openalex_queries": str(getattr(cfg, "openai_model_openalex_query_builder", "") or "") or None,
                    "s2_queries": str(getattr(cfg, "openai_model_s2_query_builder", "") or "") or None,
                    "rerank": str(getattr(cfg, "openai_model_rerank", "") or "") or None,
                    "embedding": str(getattr(cfg, "embedding_model", "") or "") or None,
                },
                "plots": {
                    "publication_year": {"data": []},
                    "citations_log10": {"data": []},
                    "coverage_tags_count": {"data": []},
                    "llm_score_distribution": {"data": []},
                    "llm_score_vs_lane_score": {"data": []},
                    "match_lane_distribution": {"data": []},
                    "match_vs_authority_top500": {"data": []},
                    "lane_score_by_rank_top200": {
                        "match_with": [],
                        "match_without": [],
                        "authority_with": [],
                        "authority_without": [],
                    },
                    "coverage_tags_top": {"data": []},
                },
            }

        def _build_v2_b_plan(plan_obj: Any) -> Dict[str, Any]:
            p = plan_obj.model_dump(mode="json") if hasattr(plan_obj, "model_dump") else {}
            return {
                "telemetry_schema_version": 2,
                "topic_summary_de": str(p.get("topic_summary_de") or ""),
                "topic_summary_en": str(p.get("topic_summary_en") or ""),
                "primary_context_anchors": p.get("primary_context_anchors") or {"en": [], "de": []},
                "global_canonical_terms": p.get("global_canonical_terms") or {"en": [], "de": []},
                "global_exclusions": p.get("global_exclusions") or {"en": [], "de": []},
                "facets": list(p.get("facets") or []),
            }

        def _build_v2_c_queries(openalex_qs: list, s2_qs: list) -> Dict[str, Any]:
            oa_rows = []
            for i, q in enumerate(openalex_qs or [], start=1):
                try:
                    intent = str(getattr(q, "intent", "") or "").strip() or "unknown"
                    lang = str(getattr(q, "language", "") or "").strip() or "unknown"
                    oa_rows.append(
                        {
                            "query_id": _query_id("openalex", i, intent, lang),
                            "i": int(i),
                            "intent": intent,
                            "language": lang,
                            "query_string": str(getattr(q, "query_string", "") or ""),
                            "notes": str(getattr(q, "notes", "") or "") or None,
                            "search_field": str(getattr(q, "search_field", "") or "") or None,
                            "filters": str(getattr(q, "filters", "") or "") or None,
                            "sort": (str(getattr(q, "sort", "") or "") or None),
                            "per_page": int(getattr(q, "per_page", 200) or 200),
                        }
                    )
                except Exception:
                    continue

            s2_rows = []
            for i, q in enumerate(s2_qs or [], start=1):
                try:
                    intent = str(getattr(q, "intent", "") or "").strip() or "unknown"
                    lang = str(getattr(q, "language", "") or "").strip() or "unknown"
                    s2_rows.append(
                        {
                            "query_id": _query_id("semanticscholar", i, intent, lang),
                            "i": int(i),
                            "intent": intent,
                            "language": lang,
                            "query_string": str(getattr(q, "query_string", "") or ""),
                            "notes": str(getattr(q, "notes", "") or "") or None,
                        }
                    )
                except Exception:
                    continue

            oa_lens = [len(str(getattr(q, "query_string", "") or "")) for q in (openalex_qs or [])]
            s2_lens = [len(str(getattr(q, "query_string", "") or "")) for q in (s2_qs or [])]
            all_lens = [int(x) for x in (oa_lens + s2_lens) if isinstance(x, int) and x >= 0]
            median_len = (None if not all_lens else float(statistics.median(sorted(all_lens))))
            max_len = (None if not all_lens else int(max(all_lens)))

            def _bin_dist(xs: list[int], *, key: str, acc: dict[int, dict[str, int]]):
                for x in xs:
                    try:
                        n = int(x)
                    except Exception:
                        continue
                    if n < 0:
                        continue
                    lo = (n // 10) * 10
                    acc.setdefault(lo, {"openalex": 0, "semanticscholar": 0})[key] += 1

            bins: dict[int, dict[str, int]] = {}
            _bin_dist(oa_lens, key="openalex", acc=bins)
            _bin_dist(s2_lens, key="semanticscholar", acc=bins)
            max_edge = 0 if not bins else (max(bins.keys()) + 10)
            length_dist = []
            for lo in range(0, int(max_edge), 10):
                row = bins.get(lo) or {"openalex": 0, "semanticscholar": 0}
                length_dist.append({"bin_lo": int(lo), "bin_hi": int(lo + 10), "openalex": int(row["openalex"]), "semanticscholar": int(row["semanticscholar"])})

            match_total = int(sum(1 for q in (openalex_qs or []) if str(getattr(q, "intent", "") or "") == "match") + sum(1 for q in (s2_qs or []) if str(getattr(q, "intent", "") or "") == "match"))
            authority_total = int(sum(1 for q in (openalex_qs or []) if str(getattr(q, "intent", "") or "") == "authority") + sum(1 for q in (s2_qs or []) if str(getattr(q, "intent", "") or "") == "authority"))

            return {
                "telemetry_schema_version": 2,
                "counts": {
                    "openalex_total": int(len(openalex_qs or [])),
                    "s2_total": int(len(s2_qs or [])),
                    "match_total": int(match_total),
                    "authority_total": int(authority_total),
                    "median_length": (None if median_len is None else float(median_len)),
                    "max_length": (None if max_len is None else int(max_len)),
                },
                "length_distribution": {"bin_width_chars": 10, "data": length_dist},
                "openalex_queries": oa_rows,
                "s2_queries": s2_rows,
            }

        def _count_raw_intents(path: Path) -> Dict[str, int]:
            out = {"total": 0, "match": 0, "authority": 0}
            try:
                if not path.exists():
                    return out
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        s = line.strip()
                        if not s:
                            continue
                        try:
                            rec = json.loads(s)
                        except Exception:
                            continue
                        if not isinstance(rec, dict):
                            continue
                        intent = str(rec.get("intent") or "").strip()
                        out["total"] += 1
                        if intent == "match":
                            out["match"] += 1
                        elif intent == "authority":
                            out["authority"] += 1
            except Exception:
                return out
            return out

        def _build_v2_d_retrieval_min(*, openalex_fetch: Optional[Dict[str, Any]], s2_fetch: Optional[Dict[str, Any]]) -> Dict[str, Any]:
            oa_scan = _count_raw_intents(Path(run_ctx.artifacts.openalex_raw_jsonl))
            s2_scan = _count_raw_intents(Path(run_ctx.artifacts.semanticscholar_raw_jsonl))
            oa_total = int(oa_scan.get("total") or 0) or int((openalex_fetch or {}).get("records") or 0)
            s2_total = int(s2_scan.get("total") or 0) or int((s2_fetch or {}).get("records") or 0)
            return {
                "telemetry_schema_version": 2,
                "provider_totals": {
                    "openalex": {
                        "records_total": int(oa_total),
                        "authority": int(oa_scan.get("authority") or 0),
                        "match": int(oa_scan.get("match") or 0),
                    },
                    "semanticscholar": {
                        "records_total": int(s2_total),
                        "authority": int(s2_scan.get("authority") or 0),
                        "match": int(s2_scan.get("match") or 0),
                    },
                },
                "provider_summary": [],
                "records_by_intent_lang": {"openalex": [], "semanticscholar": []},
                "year_distribution": {"data": []},
                "top_queries": {"data": []},
                "bottom_queries_nonzero": {"data": []},
                "zero_result_queries": {"data": [], "truncated": False, "total": 0},
            }

        await _progress("phase_b_query_planner", "Planning facets & query strategy")
        plan, _meta_b = await plan_queries_llm(
            chapter_input,
            config=cfg,
            run_ctx=run_ctx,
            llm=llm,
            force_rebuild=force_rebuild,
        )
        facets_count = int(len(getattr(plan, "facets", []) or []))
        try:
            await _telemetry({"v2_b_plan": _build_v2_b_plan(plan), "v2_report": _build_min_report(facets_count=facets_count)})
        except Exception:
            pass
        await _check_cancel()

        await _progress("phase_c_openalex_query_builder", "Building OpenAlex queries")
        openalex_queries, _meta_c1 = await build_openalex_queries_llm(
            plan,
            chapter_title=chapter_input.chapter_title,
            chapter_spec_text=chapter_input.chapter_spec_text,
            config=cfg,
            run_ctx=run_ctx,
            llm=llm,
            force_rebuild=force_rebuild,
        )
        try:
            await _telemetry(
                {
                    "v2_c_queries": _build_v2_c_queries(openalex_queries, []),
                    "v2_report": _build_min_report(facets_count=facets_count, queries_oa=len(openalex_queries), queries_s2=0),
                }
            )
        except Exception:
            pass
        await _check_cancel()

        await _progress("phase_c_s2_query_builder", "Building Semantic Scholar queries")
        s2_bulk_queries, _meta_c2 = await build_s2_bulk_queries_llm(
            plan,
            chapter_title=chapter_input.chapter_title,
            chapter_spec_text=chapter_input.chapter_spec_text,
            config=cfg,
            run_ctx=run_ctx,
            llm=llm,
            force_rebuild=force_rebuild,
        )
        try:
            await _telemetry(
                {
                    "v2_c_queries": _build_v2_c_queries(openalex_queries, s2_bulk_queries),
                    "v2_report": _build_min_report(
                        facets_count=facets_count,
                        queries_oa=len(openalex_queries),
                        queries_s2=len(s2_bulk_queries),
                    ),
                }
            )
        except Exception:
            pass
        await _check_cancel()

        await _progress("phase_d_openalex_retrieval", "Fetching OpenAlex records")
        with stage_timer(run_ctx, "phase_d_openalex_retrieval"):
            openalex_fetch = await asyncio.to_thread(
                fetch_openalex_to_cache,
                cfg=cfg,
                run_ctx=run_ctx,
                queries=openalex_queries,
                force_rebuild=force_rebuild,
            )
        await _check_cancel()

        await _progress("phase_d_semanticscholar_retrieval", "Fetching Semantic Scholar records")
        with stage_timer(run_ctx, "phase_d_semanticscholar_retrieval"):
            s2_fetch = await asyncio.to_thread(
                fetch_s2_to_cache,
                cfg=cfg,
                run_ctx=run_ctx,
                queries=s2_bulk_queries,
                force_rebuild=force_rebuild,
            )
        await _check_cancel()

        rebuild_aggregate_jsonl(run_ctx.artifacts.openalex_raw_jsonl, list(openalex_fetch.get("used_cache_paths") or []))
        rebuild_aggregate_jsonl(run_ctx.artifacts.semanticscholar_raw_jsonl, list(s2_fetch.get("used_cache_paths") or []))
        try:
            v2_d_min = _build_v2_d_retrieval_min(openalex_fetch=openalex_fetch if isinstance(openalex_fetch, dict) else None, s2_fetch=s2_fetch if isinstance(s2_fetch, dict) else None)
            records_openalex = int(((v2_d_min.get("provider_totals") or {}).get("openalex") or {}).get("records_total") or 0)
            records_s2 = int(((v2_d_min.get("provider_totals") or {}).get("semanticscholar") or {}).get("records_total") or 0)
            await _telemetry(
                {
                    "v2_d_retrieval": v2_d_min,
                    "v2_report": _build_min_report(
                        facets_count=facets_count,
                        queries_oa=len(openalex_queries),
                        queries_s2=len(s2_bulk_queries),
                        records_openalex=records_openalex,
                        records_s2=records_s2,
                    ),
                }
            )
        except Exception:
            pass
        await _check_cancel()

        await _progress("phase_e_candidates", "Normalizing & deduplicating candidates")
        with stage_timer(run_ctx, "phase_e_candidates"):
            _cands, _meta_e = await asyncio.to_thread(build_candidates_from_raw, run_ctx=run_ctx, force_rebuild=force_rebuild)
        try:
            if isinstance(_meta_e, dict):
                candidates_total = int(_meta_e.get("deduped_candidates") or 0)
        except Exception:
            pass
        try:
            await _telemetry(
                {
                    "v2_report": _build_min_report(
                        facets_count=facets_count,
                        queries_oa=len(openalex_queries),
                        queries_s2=len(s2_bulk_queries),
                        records_openalex=records_openalex,
                        records_s2=records_s2,
                        candidates_total=candidates_total,
                    )
                }
            )
        except Exception:
            pass
        await _check_cancel()

        await _progress("phase_f", "Embedding & scoring candidates")
        _meta_f = await run_phase_f_embeddings_and_scoring(
            cfg=cfg,
            run_ctx=run_ctx,
            llm=llm,
            chapter_title=chapter_input.chapter_title,
            chapter_spec_text=chapter_input.chapter_spec_text,
            force_rebuild=force_rebuild,
            check_cancel=_check_cancel,
        )
        await _check_cancel()
        try:
            metrics_partial = read_json(Path(run_ctx.artifacts.metrics_json))
            effective_settings_partial = _derive_effective_settings(cfg=cfg, metrics=metrics_partial if isinstance(metrics_partial, dict) else {})
            costs_partial = _derive_costs_from_metrics(
                metrics=metrics_partial if isinstance(metrics_partial, dict) else {},
                run_dir=run_ctx.run_dir,
                key_source=str(key_source),
                budget_cap_usd=float(llm.max_total_cost_usd),
            )
            telemetry_partial = build_two_lane_telemetry(
                run_ctx=run_ctx,
                effective_settings=effective_settings_partial,
                costs=costs_partial,
                openalex_fetch=openalex_fetch if isinstance(openalex_fetch, dict) else None,
                s2_fetch=s2_fetch if isinstance(s2_fetch, dict) else None,
            )
            v2_f = telemetry_partial.get("v2_f_scoring")
            if isinstance(v2_f, dict):
                await _telemetry(
                    {
                        "v2_f_scoring": v2_f,
                        "v2_report": _build_min_report(
                            facets_count=facets_count,
                            queries_oa=len(openalex_queries),
                            queries_s2=len(s2_bulk_queries),
                            records_openalex=records_openalex,
                            records_s2=records_s2,
                            candidates_total=candidates_total,
                        ),
                    }
                )
        except Exception:
            pass

        await _progress("phase_g", "Final lane scoring (Phase G)")
        _meta_g = await run_phase_g_lane_fusion(cfg=cfg, run_ctx=run_ctx, check_cancel=_check_cancel)
        await _check_cancel()

        await _progress("phase_h", "Computing coverage tags (Phase H)")
        _meta_h = await run_phase_h_coverage_tags(cfg=cfg, run_ctx=run_ctx, check_cancel=_check_cancel)
        await _check_cancel()

        await _progress("phase_i", "LLM reranking (Phase I)")
        _meta_i = await run_phase_i_rerank(
            cfg=cfg,
            run_ctx=run_ctx,
            llm=llm,
            chapter_title=chapter_input.chapter_title,
            chapter_spec_text=chapter_input.chapter_spec_text,
            check_cancel=_check_cancel,
            force_rebuild=force_rebuild,
        )
        await _check_cancel()
        try:
            metrics_partial = read_json(Path(run_ctx.artifacts.metrics_json))
            effective_settings_partial = _derive_effective_settings(cfg=cfg, metrics=metrics_partial if isinstance(metrics_partial, dict) else {})
            costs_partial = _derive_costs_from_metrics(
                metrics=metrics_partial if isinstance(metrics_partial, dict) else {},
                run_dir=run_ctx.run_dir,
                key_source=str(key_source),
                budget_cap_usd=float(llm.max_total_cost_usd),
            )
            telemetry_partial = build_two_lane_telemetry(
                run_ctx=run_ctx,
                effective_settings=effective_settings_partial,
                costs=costs_partial,
                openalex_fetch=openalex_fetch if isinstance(openalex_fetch, dict) else None,
                s2_fetch=s2_fetch if isinstance(s2_fetch, dict) else None,
            )
            v2_i = telemetry_partial.get("v2_i_rerank")
            if isinstance(v2_i, dict):
                await _telemetry(
                    {
                        "v2_i_rerank": v2_i,
                        "v2_report": _build_min_report(
                            facets_count=facets_count,
                            queries_oa=len(openalex_queries),
                            queries_s2=len(s2_bulk_queries),
                            records_openalex=records_openalex,
                            records_s2=records_s2,
                            candidates_total=candidates_total,
                        ),
                    }
                )
        except Exception:
            pass

        await _progress("phase_k", "Building final output (Phase K)")
        with stage_timer(run_ctx, "phase_k_output"):
            _meta_k = await run_phase_k_output(
                cfg=cfg,
                run_ctx=run_ctx,
                chapter_title=chapter_input.chapter_title,
                chapter_spec_text=chapter_input.chapter_spec_text,
                top_n=40,
                check_cancel=_check_cancel,
                force_rebuild=force_rebuild,
            )
        await _check_cancel()

        output = read_json(Path(run_ctx.artifacts.output_json))
        metrics = read_json(Path(run_ctx.artifacts.metrics_json))

        effective_settings = _derive_effective_settings(cfg=cfg, metrics=metrics if isinstance(metrics, dict) else {})
        costs = _derive_costs_from_metrics(
            metrics=metrics if isinstance(metrics, dict) else {}, run_dir=run_ctx.run_dir, key_source=str(key_source), budget_cap_usd=float(llm.max_total_cost_usd)
        )

        telemetry = build_two_lane_telemetry(
            run_ctx=run_ctx,
            effective_settings=effective_settings,
            costs=costs,
            openalex_fetch=openalex_fetch if isinstance(openalex_fetch, dict) else None,
            s2_fetch=s2_fetch if isinstance(s2_fetch, dict) else None,
        )

        result = {
            "run_id": str(run_id),
            "keep_artifacts": bool(keep_artifacts),
            "artifacts_dir": str(run_ctx.run_dir) if keep_artifacts else None,
            "output": output,
            "metrics": metrics,
            "costs": costs,
            "effective_settings": effective_settings,
            "telemetry": telemetry,
        }

        return result
    finally:
        if tmp_dir_cm is not None:
            try:
                tmp_dir_cm.cleanup()
            except Exception:
                pass
