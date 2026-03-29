"""
Replay the two-lane planner and query-builder stages for a real Firestore case.

Artifacts are written under:
    backend/.two_lane_artifacts/investigations/<label>/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from openai import AsyncOpenAI


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(REPO_ROOT / ".env", override=True)
load_dotenv(BACKEND_ROOT / ".env", override=True)

from services.firebase_service import firebase_service
from services.two_lane_sources.pipeline import (
    OPENALEX_QUERY_BUILDER_JSON_SCHEMA,
    OPENALEX_QUERY_BUILDER_SYSTEM_PROMPT,
    OPENALEX_QUERY_BUILDER_USER_PROMPT_TEMPLATE,
    OPENALEX_SELECT,
    PLANNER_SYSTEM_PROMPT,
    QUERY_PLAN_JSON_SCHEMA,
    S2_BATCH_FIELDS,
    S2_BULK_FIELDS,
    S2_BULK_QUERY_BUILDER_JSON_SCHEMA,
    S2_BULK_QUERY_BUILDER_SYSTEM_PROMPT,
    S2_BULK_QUERY_BUILDER_USER_PROMPT_TEMPLATE,
    ChapterInput,
    OpenAlexQuery,
    PipelineConfig,
    QueryPlan,
    S2BulkQuery,
    _count_s2_negative_components,
    _count_s2_required_components,
    _extract_text_from_response,
    _find_anchor_terms_in_text,
    _json_for_prompt,
    _normalize_openalex_query,
    _normalize_s2_query,
    _openalex_params,
    _plan_language_terms,
    _render_template,
    _repair_query_plan,
    _sanitize_plan_for_query_builders,
    _truncate_chars,
    _validate_intent_coverage,
    _validate_language_coverage,
    _validate_match_core_object_presence,
    _validate_openalex_anchor_presence,
    _validate_openalex_match_anchor_fingerprint_diversity,
    _validate_openalex_search_field_budget,
    _validate_s2_advanced_syntax_budget,
    _validate_s2_anchor_presence,
    _validate_s2_match_required_group_budget,
    build_candidates_from_raw,
    diagnose_query_plan,
    fetch_openalex_to_cache,
    fetch_s2_to_cache,
    planner_user_prompt,
    rebuild_aggregate_jsonl,
)
from services.two_lane_sources.runner import _build_run_ctx


INVESTIGATION_ROOT = BACKEND_ROOT / ".two_lane_artifacts" / "investigations"


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return repr(value)


def _write_json(path: Path, payload: Any) -> None:
    _ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8")


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(text or "").strip())
    cleaned = cleaned.strip("-")
    return cleaned or "case"


def _usage_to_dict(resp: Any) -> Dict[str, Any]:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return {}
    output_details = getattr(usage, "output_tokens_details", None)
    input_details = getattr(usage, "input_tokens_details", None)
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "cached_input_tokens": int(getattr(input_details, "cached_tokens", 0) or 0),
        "reasoning_tokens": int(getattr(output_details, "reasoning_tokens", 0) or 0),
    }


async def _responses_json_schema_call(
    *,
    client: AsyncOpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    schema_name: str,
    schema: Dict[str, Any],
    reasoning_effort: str,
    max_output_tokens: int,
    timeout_s: float,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    http_timeout_create_s = float(min(max(30.0, timeout_s), 600.0))
    http_timeout_poll_s = float(min(60.0, http_timeout_create_s))
    t0 = time.perf_counter()

    resp = await client.responses.create(
        model=model,
        service_tier="default",
        input=[
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": schema,
                "strict": True,
            }
        },
        reasoning={"effort": reasoning_effort},
        max_output_tokens=max(256, int(max_output_tokens or 0)),
        store=False,
        background=True,
        timeout=http_timeout_create_s,
    )

    response_id = getattr(resp, "id", None)
    terminal_statuses = {"completed", "incomplete", "failed", "cancelled", "canceled"}
    poll_sleep_s = 1.0
    while getattr(resp, "status", None) not in terminal_statuses:
        if (time.perf_counter() - t0) > float(timeout_s):
            raise TimeoutError(
                f"OpenAI background response timed out after {int(timeout_s)}s "
                f"(last_status={getattr(resp, 'status', None)!r}, response_id={response_id!r})"
            )
        await asyncio.sleep(poll_sleep_s)
        poll_sleep_s = min(poll_sleep_s * 1.5, 10.0)
        if not response_id:
            break
        resp = await client.responses.retrieve(response_id, timeout=http_timeout_poll_s)

    raw_text = _extract_text_from_response(resp)
    if not raw_text.strip():
        raise RuntimeError("OpenAI returned empty output_text")

    obj = json.loads(raw_text)
    meta = {
        "model_requested": model,
        "model_used": str(getattr(resp, "model", None) or model),
        "response_id": response_id,
        "status": getattr(resp, "status", None),
        "reasoning_effort": reasoning_effort,
        "usage": _usage_to_dict(resp),
        "elapsed_s": round(float(time.perf_counter() - t0), 3),
    }
    raw_response = resp.model_dump() if hasattr(resp, "model_dump") else {"raw_text": raw_text}
    return obj, meta, raw_response


def _find_project_owner(project_id: str) -> str:
    db = firebase_service.db
    for user_doc in db.collection("users").stream():
        if user_doc.reference.collection("projects").document(project_id).get().exists:
            return user_doc.id
    raise ValueError(f"Could not find owner for project_id={project_id}")


def _load_firestore_case(*, user_id: Optional[str], project_id: str, kapitel_id: str, run_id: Optional[str]) -> Dict[str, Any]:
    db = firebase_service.db
    owner_id = (user_id or "").strip() or _find_project_owner(project_id)

    project_ref = db.collection("users").document(owner_id).collection("projects").document(project_id)
    project_snap = project_ref.get()
    if not project_snap.exists:
        raise ValueError(f"Project not found for user_id={owner_id} project_id={project_id}")

    kapitel_ref = db.collection("users").document(owner_id).collection("kapitels").document(kapitel_id)
    kapitel_snap = kapitel_ref.get()
    if not kapitel_snap.exists:
        raise ValueError(f"Kapitel not found: {kapitel_id}")

    kapitel = kapitel_snap.to_dict() or {}
    title = str(kapitel.get("title") or kapitel.get("chapterTitle") or "").strip()
    thema = str(kapitel.get("thema") or kapitel.get("specText") or "").strip()
    if not title or not thema:
        raise ValueError(f"Kapitel is missing title/thema: {kapitel_id}")

    run_settings: Dict[str, Any] = {}
    run_payload: Dict[str, Any] = {}
    if run_id:
        run_ref = project_ref.collection("researchRuns").document(run_id)
        run_snap = run_ref.get()
        if not run_snap.exists:
            raise ValueError(f"Run not found: {run_id}")
        run_payload = run_snap.to_dict() or {}
        settings = run_payload.get("settings")
        if isinstance(settings, dict):
            run_settings = dict(settings)

    return {
        "user_id": owner_id,
        "project_id": project_id,
        "kapitel_id": kapitel_id,
        "run_id": run_id,
        "chapter_title": title,
        "chapter_spec_text": thema,
        "kapitel_payload": kapitel,
        "run_payload": run_payload,
        "run_settings": run_settings,
    }


def _build_direct_case(*, chapter_title: str, chapter_spec_text: str) -> Dict[str, Any]:
    title = str(chapter_title or "").strip()
    spec_text = str(chapter_spec_text or "").strip()
    if not title:
        raise ValueError("chapter_title is required when bypassing Firestore")
    if not spec_text:
        raise ValueError("chapter_spec_text is required when bypassing Firestore")

    direct_id = _slug(title)[:48]
    return {
        "user_id": None,
        "project_id": f"direct-{direct_id}",
        "kapitel_id": f"direct-{direct_id}",
        "run_id": None,
        "chapter_title": title,
        "chapter_spec_text": spec_text,
        "kapitel_payload": {},
        "run_payload": {},
        "run_settings": {},
        "case_source": "direct_input",
    }


def _effective_config(*, run_root: Path, run_settings: Dict[str, Any]) -> PipelineConfig:
    cfg = PipelineConfig.from_env(runs_root=run_root, pipeline_version="two_lane_v1")
    overrides = run_settings.get("pipeline_settings") if isinstance(run_settings.get("pipeline_settings"), dict) else {}
    for key, value in (run_settings | overrides).items():
        if hasattr(cfg, key):
            try:
                setattr(cfg, key, value)
            except Exception:
                pass
    cfg.force_rebuild = True
    return cfg


def _legacy_openalex_fingerprint_summary(queries: List[OpenAlexQuery], *, plan: QueryPlan, max_share: float = 0.60) -> Dict[str, Any]:
    report: Dict[str, Any] = {}
    for lang in ("en", "de"):
        anchors = getattr(plan.primary_context_anchors, lang, []) or []
        anchors = [str(t).strip() for t in anchors if str(t or "").strip()]
        match_qs = [q for q in queries if q.intent == "match" and q.language == lang]
        lang_report: Dict[str, Any] = {
            "anchor_count": len(anchors),
            "match_query_count": len(match_qs),
            "eligible_count": 0,
            "most_common_fingerprint": None,
            "most_common_share": None,
            "pass": True,
            "variable_anchors": [],
        }
        if len(match_qs) < 4 or not anchors:
            report[lang] = lang_report
            continue

        presence_counts: Dict[str, int] = {anchor: 0 for anchor in anchors}
        for q in match_qs:
            qs = str(q.query_string or "")
            for anchor in anchors:
                if anchor.casefold() in qs.casefold():
                    presence_counts[anchor] += 1

        variable_anchors = [anchor for anchor in anchors if (presence_counts.get(anchor, 0) / max(len(match_qs), 1)) < 0.90]
        lang_report["variable_anchors"] = variable_anchors
        if len(variable_anchors) < 2:
            report[lang] = lang_report
            continue

        fps: Counter[Tuple[str, str]] = Counter()
        for q in match_qs:
            hits = _find_anchor_terms_in_text(q.query_string, variable_anchors)
            top2 = tuple(h.lower() for h in hits[:2])
            if len(top2) < 2:
                continue
            fps[top2] += 1

        eligible = int(sum(fps.values()))
        lang_report["eligible_count"] = eligible
        if eligible < 4 or not fps:
            report[lang] = lang_report
            continue

        fp, count = fps.most_common(1)[0]
        share = count / max(eligible, 1)
        lang_report["most_common_fingerprint"] = list(fp)
        lang_report["most_common_share"] = round(share, 4)
        lang_report["pass"] = bool(share <= float(max_share))
        report[lang] = lang_report
    return report


def _active_openalex_fingerprint_summary(queries: List[OpenAlexQuery], *, plan: QueryPlan, max_share: float = 0.60) -> Dict[str, Any]:
    report: Dict[str, Any] = {}
    for lang in ("en", "de"):
        anchors = getattr(plan.primary_context_anchors, lang, []) or []
        anchors = [str(t).strip() for t in anchors if str(t or "").strip()]
        match_qs = [q for q in queries if q.intent == "match" and q.language == lang]
        fps: Counter[Tuple[str, str]] = Counter()
        eligible = 0
        for q in match_qs:
            hits = _find_anchor_terms_in_text(q.query_string, anchors)
            top2 = tuple(h.lower() for h in hits[:2])
            if len(top2) < 2:
                continue
            fps[top2] += 1
            eligible += 1
        most_fp: Optional[List[str]] = None
        most_share: Optional[float] = None
        passed = True
        if eligible >= 4 and fps:
            fp, count = fps.most_common(1)[0]
            most_fp = list(fp)
            most_share = round(count / max(eligible, 1), 4)
            passed = bool((count / max(eligible, 1)) <= float(max_share))
        report[lang] = {
            "anchor_count": len(anchors),
            "match_query_count": len(match_qs),
            "eligible_count": eligible,
            "most_common_fingerprint": most_fp,
            "most_common_share": most_share,
            "pass": passed,
        }
    return report


def _query_hit_summary(query_string: str, terms: Iterable[str]) -> List[str]:
    return _find_anchor_terms_in_text(query_string, list(terms))


def _openalex_query_rows(queries: List[OpenAlexQuery], *, plan: QueryPlan) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, q in enumerate(queries, start=1):
        rows.append(
            {
                "index": idx,
                "intent": q.intent,
                "language": q.language,
                "search_field": q.search_field,
                "anchor_hits": _query_hit_summary(q.query_string, getattr(plan.primary_context_anchors, q.language, []) or []),
                "core_object_hits": _query_hit_summary(q.query_string, _plan_language_terms(plan, "core_object_terms", q.language)),
                "query_string": q.query_string,
                "filters": q.filters,
                "sort": q.sort,
                "notes": q.notes,
            }
        )
    return rows


def _s2_query_rows(queries: List[S2BulkQuery], *, plan: QueryPlan) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, q in enumerate(queries, start=1):
        rows.append(
            {
                "index": idx,
                "intent": q.intent,
                "language": q.language,
                "anchor_hits": _query_hit_summary(q.query_string, getattr(plan.primary_context_anchors, q.language, []) or []),
                "core_object_hits": _query_hit_summary(q.query_string, _plan_language_terms(plan, "core_object_terms", q.language)),
                "required_components": _count_s2_required_components(q.query_string),
                "negative_components": _count_s2_negative_components(q.query_string),
                "query_string": q.query_string,
                "notes": q.notes,
            }
        )
    return rows


def _validate_openalex_queries(queries_obj: Dict[str, Any], *, plan: QueryPlan, cfg: PipelineConfig) -> Dict[str, Any]:
    items = queries_obj.get("openalex_queries")
    if not isinstance(items, list):
        raise ValueError("OpenAI output missing openalex_queries list")

    queries = [_normalize_openalex_query(OpenAlexQuery.model_validate(item)) for item in items]
    max_q = int(cfg.max_queries_per_provider or 0) or 50
    if len(queries) > max_q:
        queries = queries[:max_q]

    _validate_language_coverage(queries, provider="OpenAlex")
    _validate_intent_coverage(queries, provider="OpenAlex")
    _validate_openalex_anchor_presence(queries, plan=plan)
    _validate_match_core_object_presence(queries, plan=plan, provider="OpenAlex")
    _validate_openalex_match_anchor_fingerprint_diversity(queries, plan=plan)
    _validate_openalex_search_field_budget(queries)

    return {
        "queries": queries,
        "rows": _openalex_query_rows(queries, plan=plan),
        "active_fingerprint": _active_openalex_fingerprint_summary(queries, plan=plan),
        "legacy_fingerprint": _legacy_openalex_fingerprint_summary(queries, plan=plan),
    }


def _validate_s2_queries(queries_obj: Dict[str, Any], *, plan: QueryPlan, cfg: PipelineConfig) -> Dict[str, Any]:
    items = queries_obj.get("s2_bulk_queries")
    if not isinstance(items, list):
        raise ValueError("OpenAI output missing s2_bulk_queries list")

    queries = [_normalize_s2_query(S2BulkQuery.model_validate(item)) for item in items]
    max_q = int(cfg.max_queries_per_provider or 0) or 50
    if len(queries) > max_q:
        queries = queries[:max_q]

    _validate_language_coverage(queries, provider="S2")
    _validate_intent_coverage(queries, provider="S2")
    _validate_s2_anchor_presence(queries, plan=plan)
    _validate_match_core_object_presence(queries, plan=plan, provider="S2")
    _validate_s2_match_required_group_budget(queries)
    _validate_s2_advanced_syntax_budget(queries)

    return {
        "queries": queries,
        "rows": _s2_query_rows(queries, plan=plan),
    }


def _probe_openalex(cfg: PipelineConfig, q: OpenAlexQuery, *, top_k: int) -> Dict[str, Any]:
    session = requests.Session()
    session.headers.update({"User-Agent": "instantpaper-two-lane-investigation/1.0"})
    params = _openalex_params(cfg, q.model_copy(update={"per_page": min(max(top_k, 1), 25)}), cursor="*")
    url = cfg.openalex_base_url.rstrip("/") + "/works"
    resp = session.get(url, params=params, timeout=float(cfg.openalex_timeout_s))
    payload = resp.json()
    rows = []
    for item in (payload.get("results") or [])[:top_k]:
        rows.append(
            {
                "id": item.get("id"),
                "title": item.get("display_name"),
                "year": item.get("publication_year"),
                "type": item.get("type"),
                "cited_by_count": item.get("cited_by_count"),
            }
        )
    return {
        "status_code": int(resp.status_code),
        "result_count_reported": ((payload.get("meta") or {}).get("count")),
        "sample_results": rows,
        "request_params": {k: ("<redacted>" if k == "api_key" else v) for k, v in params.items()},
    }


def _probe_s2(cfg: PipelineConfig, q: S2BulkQuery, *, top_k: int) -> Dict[str, Any]:
    base = cfg.semanticscholar_base_url.rstrip("/")
    bulk_url = base + "/paper/search/bulk"
    batch_url = base + "/paper/batch"
    session = requests.Session()
    session.headers.update({"User-Agent": "instantpaper-two-lane-investigation/1.0"})
    if cfg.semanticscholar_api_key:
        session.headers.update({"x-api-key": cfg.semanticscholar_api_key})

    bulk_resp = session.get(
        bulk_url,
        params={"query": q.query_string, "fields": S2_BULK_FIELDS, "limit": int(min(max(top_k, 1), 25))},
        timeout=float(cfg.semanticscholar_timeout_s),
    )
    bulk_payload = bulk_resp.json()
    ids = [str(item.get("paperId")) for item in (bulk_payload.get("data") or []) if item.get("paperId")][:top_k]

    sample_results: List[Dict[str, Any]] = []
    if ids:
        batch_resp = session.post(
            batch_url,
            params={"fields": S2_BATCH_FIELDS},
            json={"ids": ids},
            timeout=float(cfg.semanticscholar_timeout_s),
        )
        batch_payload = batch_resp.json()
        batch_items = batch_payload if isinstance(batch_payload, list) else (batch_payload.get("data") or [])
        for item in batch_items[:top_k]:
            if not isinstance(item, dict):
                continue
            sample_results.append(
                {
                    "paperId": item.get("paperId"),
                    "title": item.get("title"),
                    "year": item.get("year"),
                    "venue": item.get("venue"),
                    "citationCount": item.get("citationCount"),
                }
            )

    return {
        "status_code": int(bulk_resp.status_code),
        "ids_seen": len(ids),
        "sample_results": sample_results,
        "request_query": q.query_string,
    }


async def _run_planner(
    *,
    client: AsyncOpenAI,
    chapter_input: ChapterInput,
    cfg: PipelineConfig,
    out_dir: Path,
    attempts: int,
) -> Tuple[QueryPlan, Dict[str, Any]]:
    user_prompt = planner_user_prompt(chapter_input)
    last_err: Optional[Exception] = None
    summary: Dict[str, Any] = {"attempts": []}

    for attempt in range(1, attempts + 1):
        attempt_prompt = user_prompt
        if last_err is not None:
            attempt_prompt = (
                user_prompt
                + "\n\nLINT_FEEDBACK:\n- Previous attempt failed deterministic validation. Fix and regenerate.\n"
                + f"- Error: {str(last_err)[:600]}\n"
            )

        obj, meta, raw_response = await _responses_json_schema_call(
            client=client,
            model=cfg.openai_model_planner,
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=attempt_prompt,
            schema_name="query_plan",
            schema=QUERY_PLAN_JSON_SCHEMA,
            reasoning_effort=cfg.openai_reasoning_effort,
            max_output_tokens=int(getattr(cfg, "openai_max_output_tokens_planner", 6000)),
            timeout_s=float(cfg.openai_timeout_s),
        )
        attempt_dir = _ensure_dir(out_dir / f"planner_attempt_{attempt}")
        _write_json(attempt_dir / "parsed_output.json", obj)
        _write_json(attempt_dir / "openai_meta.json", meta)
        _write_json(attempt_dir / "raw_response.json", raw_response)

        attempt_rec: Dict[str, Any] = {"attempt": attempt, "meta": meta}
        try:
            plan = QueryPlan.model_validate(obj)
            repaired_plan, repair_notes = _repair_query_plan(plan)
            diagnostics = diagnose_query_plan(repaired_plan)
            critical = diagnostics.get("critical_issues") or []
            if critical:
                raise ValueError("QueryPlan failed hygiene checks: " + "; ".join(str(item) for item in critical[:6]))
            _write_json(attempt_dir / "repaired_plan.json", repaired_plan.model_dump(mode="json"))
            _write_json(attempt_dir / "diagnostics.json", diagnostics)
            attempt_rec["status"] = "passed"
            attempt_rec["repair_notes"] = repair_notes
            attempt_rec["diagnostics"] = diagnostics
            summary["attempts"].append(attempt_rec)
            summary["selected_attempt"] = attempt
            summary["selected_meta"] = meta
            summary["repair_notes"] = repair_notes
            summary["diagnostics"] = diagnostics
            return repaired_plan, summary
        except Exception as exc:
            attempt_rec["status"] = "failed"
            attempt_rec["error"] = str(exc)
            summary["attempts"].append(attempt_rec)
            _write_json(attempt_dir / "lint_failure.json", {"error": str(exc)})
            last_err = exc

    raise RuntimeError(f"Planner replay failed after {attempts} attempts: {last_err}")


async def _run_openalex_builder(
    *,
    client: AsyncOpenAI,
    chapter_input: ChapterInput,
    plan: QueryPlan,
    cfg: PipelineConfig,
    out_dir: Path,
    attempts: int,
    probe_top_k: int,
) -> Tuple[Dict[str, Any], Optional[List[OpenAlexQuery]]]:
    user_prompt = _render_template(
        OPENALEX_QUERY_BUILDER_USER_PROMPT_TEMPLATE,
        chapter_title=str(chapter_input.chapter_title or "").strip(),
        chapter_spec_text=_truncate_chars(chapter_input.chapter_spec_text, 12000),
        query_plan_json=_json_for_prompt(_sanitize_plan_for_query_builders(plan)),
        max_queries=str(int(cfg.max_queries_per_provider or 50)),
    )
    last_err: Optional[Exception] = None
    summary: Dict[str, Any] = {"attempts": []}

    for attempt in range(1, attempts + 1):
        attempt_prompt = user_prompt
        if last_err is not None:
            attempt_prompt = (
                user_prompt
                + "\n\nLINT_FEEDBACK:\n- Previous attempt failed deterministic validation. Fix and regenerate.\n"
                + f"- Error: {str(last_err)[:400]}\n"
            )
        obj, meta, raw_response = await _responses_json_schema_call(
            client=client,
            model=cfg.openai_model_openalex_query_builder,
            system_prompt=OPENALEX_QUERY_BUILDER_SYSTEM_PROMPT,
            user_prompt=attempt_prompt,
            schema_name="openalex_queries",
            schema=OPENALEX_QUERY_BUILDER_JSON_SCHEMA,
            reasoning_effort=cfg.openai_reasoning_effort,
            max_output_tokens=50000,
            timeout_s=float(cfg.openai_timeout_s),
        )
        attempt_dir = _ensure_dir(out_dir / f"openalex_attempt_{attempt}")
        _write_json(attempt_dir / "parsed_output.json", obj)
        _write_json(attempt_dir / "openai_meta.json", meta)
        _write_json(attempt_dir / "raw_response.json", raw_response)

        attempt_rec: Dict[str, Any] = {"attempt": attempt, "meta": meta}
        try:
            validated = _validate_openalex_queries(obj, plan=plan, cfg=cfg)
            probes: List[Dict[str, Any]] = []
            for row, query in zip(validated["rows"][:probe_top_k], validated["queries"][:probe_top_k]):
                probes.append({"query_row": row, "provider_probe": _probe_openalex(cfg, query, top_k=3)})
            _write_json(attempt_dir / "validation.json", {k: v for k, v in validated.items() if k != "queries"})
            _write_json(attempt_dir / "provider_probes.json", probes)
            attempt_rec["status"] = "passed"
            attempt_rec["validation"] = {k: v for k, v in validated.items() if k != "queries"}
            summary["attempts"].append(attempt_rec)
            summary["selected_attempt"] = attempt
            summary["selected_meta"] = meta
            summary["selected_validation"] = {k: v for k, v in validated.items() if k != "queries"}
            return summary, list(validated["queries"])
        except Exception as exc:
            probe_payload: Dict[str, Any] = {}
            items = obj.get("openalex_queries") if isinstance(obj, dict) else None
            if isinstance(items, list):
                try:
                    normalized = []
                    for item in items[:probe_top_k]:
                        try:
                            normalized.append(_normalize_openalex_query(OpenAlexQuery.model_validate(item)))
                        except Exception:
                            continue
                    if normalized:
                        probe_payload["sample_provider_probes"] = [
                            _probe_openalex(cfg, query, top_k=3) for query in normalized[:probe_top_k]
                        ]
                        probe_payload["sample_rows"] = _openalex_query_rows(normalized[:probe_top_k], plan=plan)
                        probe_payload["active_fingerprint"] = _active_openalex_fingerprint_summary(normalized, plan=plan)
                        probe_payload["legacy_fingerprint"] = _legacy_openalex_fingerprint_summary(normalized, plan=plan)
                except Exception as probe_exc:
                    probe_payload["probe_error"] = str(probe_exc)
            _write_json(attempt_dir / "lint_failure.json", {"error": str(exc), **probe_payload})
            attempt_rec["status"] = "failed"
            attempt_rec["error"] = str(exc)
            if probe_payload:
                attempt_rec["probe_payload"] = probe_payload
            summary["attempts"].append(attempt_rec)
            last_err = exc

    return summary, None


async def _run_s2_builder(
    *,
    client: AsyncOpenAI,
    chapter_input: ChapterInput,
    plan: QueryPlan,
    cfg: PipelineConfig,
    out_dir: Path,
    attempts: int,
    probe_top_k: int,
) -> Tuple[Dict[str, Any], Optional[List[S2BulkQuery]]]:
    user_prompt = _render_template(
        S2_BULK_QUERY_BUILDER_USER_PROMPT_TEMPLATE,
        chapter_title=str(chapter_input.chapter_title or "").strip(),
        chapter_spec_text=_truncate_chars(chapter_input.chapter_spec_text, 12000),
        query_plan_json=_json_for_prompt(_sanitize_plan_for_query_builders(plan)),
        max_queries=str(int(cfg.max_queries_per_provider or 50)),
    )
    last_err: Optional[Exception] = None
    summary: Dict[str, Any] = {"attempts": []}

    for attempt in range(1, attempts + 1):
        attempt_prompt = user_prompt
        if last_err is not None:
            attempt_prompt = (
                user_prompt
                + "\n\nLINT_FEEDBACK:\n- Previous attempt failed deterministic validation. Fix and regenerate.\n"
                + f"- Error: {str(last_err)[:400]}\n"
            )
        obj, meta, raw_response = await _responses_json_schema_call(
            client=client,
            model=cfg.openai_model_s2_query_builder,
            system_prompt=S2_BULK_QUERY_BUILDER_SYSTEM_PROMPT,
            user_prompt=attempt_prompt,
            schema_name="s2_bulk_queries",
            schema=S2_BULK_QUERY_BUILDER_JSON_SCHEMA,
            reasoning_effort=cfg.openai_reasoning_effort,
            max_output_tokens=50000,
            timeout_s=float(cfg.openai_timeout_s),
        )
        attempt_dir = _ensure_dir(out_dir / f"s2_attempt_{attempt}")
        _write_json(attempt_dir / "parsed_output.json", obj)
        _write_json(attempt_dir / "openai_meta.json", meta)
        _write_json(attempt_dir / "raw_response.json", raw_response)

        attempt_rec: Dict[str, Any] = {"attempt": attempt, "meta": meta}
        try:
            validated = _validate_s2_queries(obj, plan=plan, cfg=cfg)
            probes: List[Dict[str, Any]] = []
            for row, query in zip(validated["rows"][:probe_top_k], validated["queries"][:probe_top_k]):
                probes.append({"query_row": row, "provider_probe": _probe_s2(cfg, query, top_k=3)})
            _write_json(attempt_dir / "validation.json", {k: v for k, v in validated.items() if k != "queries"})
            _write_json(attempt_dir / "provider_probes.json", probes)
            attempt_rec["status"] = "passed"
            attempt_rec["validation"] = {k: v for k, v in validated.items() if k != "queries"}
            summary["attempts"].append(attempt_rec)
            summary["selected_attempt"] = attempt
            summary["selected_meta"] = meta
            summary["selected_validation"] = {k: v for k, v in validated.items() if k != "queries"}
            return summary, list(validated["queries"])
        except Exception as exc:
            probe_payload: Dict[str, Any] = {}
            items = obj.get("s2_bulk_queries") if isinstance(obj, dict) else None
            if isinstance(items, list):
                try:
                    normalized = []
                    for item in items[:probe_top_k]:
                        try:
                            normalized.append(_normalize_s2_query(S2BulkQuery.model_validate(item)))
                        except Exception:
                            continue
                    if normalized:
                        probe_payload["sample_provider_probes"] = [_probe_s2(cfg, query, top_k=3) for query in normalized[:probe_top_k]]
                        probe_payload["sample_rows"] = _s2_query_rows(normalized[:probe_top_k], plan=plan)
                except Exception as probe_exc:
                    probe_payload["probe_error"] = str(probe_exc)
            _write_json(attempt_dir / "lint_failure.json", {"error": str(exc), **probe_payload})
            attempt_rec["status"] = "failed"
            attempt_rec["error"] = str(exc)
            if probe_payload:
                attempt_rec["probe_payload"] = probe_payload
            summary["attempts"].append(attempt_rec)
            last_err = exc

    return summary, None


def _run_fetch_and_candidates(
    *,
    cfg: PipelineConfig,
    run_ctx,
    openalex_queries: List[OpenAlexQuery],
    s2_queries: List[S2BulkQuery],
) -> Dict[str, Any]:
    openalex_fetch = fetch_openalex_to_cache(
        cfg=cfg,
        run_ctx=run_ctx,
        queries=openalex_queries,
        force_rebuild=True,
    )
    s2_fetch = fetch_s2_to_cache(
        cfg=cfg,
        run_ctx=run_ctx,
        queries=s2_queries,
        force_rebuild=True,
    )
    rebuild_aggregate_jsonl(run_ctx.artifacts.openalex_raw_jsonl, list(openalex_fetch.get("used_cache_paths") or []))
    rebuild_aggregate_jsonl(run_ctx.artifacts.semanticscholar_raw_jsonl, list(s2_fetch.get("used_cache_paths") or []))
    _candidates, candidate_meta = build_candidates_from_raw(run_ctx=run_ctx, force_rebuild=True)
    return {
        "openalex_fetch": openalex_fetch,
        "s2_fetch": s2_fetch,
        "candidate_meta": candidate_meta,
    }


async def _async_main(args: argparse.Namespace) -> int:
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise RuntimeError("OPENAI_API_KEY is not available after loading dotenv")

    if str(args.chapter_title or "").strip() or str(args.chapter_spec_text or "").strip():
        case = _build_direct_case(
            chapter_title=str(args.chapter_title or "").strip(),
            chapter_spec_text=str(args.chapter_spec_text or "").strip(),
        )
    else:
        if not str(args.project_id or "").strip() or not str(args.kapitel_id or "").strip():
            raise ValueError("Either --chapter-title/--chapter-spec-text or both --project-id and --kapitel-id are required")
        case = _load_firestore_case(
            user_id=args.user_id,
            project_id=str(args.project_id or "").strip(),
            kapitel_id=str(args.kapitel_id or "").strip(),
            run_id=args.run_id,
        )

    label_parts = [case["project_id"], case["kapitel_id"]]
    if case["run_id"]:
        label_parts.append(case["run_id"])
    out_dir = _ensure_dir(INVESTIGATION_ROOT / _slug("_".join(label_parts)))
    cfg = _effective_config(run_root=out_dir / "runs", run_settings=case["run_settings"])
    chapter_input = ChapterInput(
        chapter_title=case["chapter_title"],
        chapter_spec_text=case["chapter_spec_text"],
        pipeline_version=str(cfg.pipeline_version),
    )
    run_ctx = _build_run_ctx(run_dir=out_dir / "scratch_run", run_id=(case["run_id"] or "investigation"))
    run_ctx.create_artifact_skeleton(overwrite=False)

    _write_json(out_dir / "case.json", case)
    _write_json(out_dir / "effective_config.json", cfg.model_dump(mode="json"))
    _write_json(out_dir / "chapter_input.json", chapter_input.model_dump(mode="json"))
    _write_json(out_dir / "run_context.json", run_ctx.model_dump(mode="json"))

    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    planner_dir = _ensure_dir(out_dir / "planner")
    plan, planner_summary = await _run_planner(
        client=client,
        chapter_input=chapter_input,
        cfg=cfg,
        out_dir=planner_dir,
        attempts=int(args.planner_attempts),
    )
    _write_json(out_dir / "query_plan.json", plan.model_dump(mode="json"))
    _write_json(out_dir / "planner_summary.json", planner_summary)

    openalex_summary, openalex_queries = await _run_openalex_builder(
        client=client,
        chapter_input=chapter_input,
        plan=plan,
        cfg=cfg,
        out_dir=_ensure_dir(out_dir / "openalex"),
        attempts=int(args.openalex_attempts),
        probe_top_k=int(args.probe_top_k),
    )
    _write_json(out_dir / "openalex_summary.json", openalex_summary)

    s2_summary, s2_queries = await _run_s2_builder(
        client=client,
        chapter_input=chapter_input,
        plan=plan,
        cfg=cfg,
        out_dir=_ensure_dir(out_dir / "s2"),
        attempts=int(args.s2_attempts),
        probe_top_k=int(args.probe_top_k),
    )
    _write_json(out_dir / "s2_summary.json", s2_summary)

    pipeline_smoke: Dict[str, Any] = {}
    if args.run_fetch_and_candidates:
        if not openalex_queries or not s2_queries:
            raise RuntimeError("Cannot run fetch/candidate smoke test because one of the query builders did not produce a passing output.")
        pipeline_smoke = _run_fetch_and_candidates(
            cfg=cfg,
            run_ctx=run_ctx,
            openalex_queries=openalex_queries,
            s2_queries=s2_queries,
        )
        _write_json(out_dir / "pipeline_smoke.json", pipeline_smoke)

    combined_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cached_input_tokens": 0, "reasoning_tokens": 0}
    for summary in (planner_summary, openalex_summary, s2_summary):
        for attempt in summary.get("attempts", []):
            usage = (((attempt or {}).get("meta") or {}).get("usage") or {})
            for key in combined_usage:
                combined_usage[key] += int(usage.get(key) or 0)
    _write_json(out_dir / "usage_rollup.json", combined_usage)

    print(f"Investigation artifacts written to: {out_dir}")
    result_payload = {"out_dir": str(out_dir), "usage": combined_usage}
    if pipeline_smoke:
        result_payload["pipeline_smoke"] = {
            "openalex_records": int(((pipeline_smoke.get("openalex_fetch") or {}).get("records")) or 0),
            "s2_records": int(((pipeline_smoke.get("s2_fetch") or {}).get("records")) or 0),
            "deduped_candidates": int(((pipeline_smoke.get("candidate_meta") or {}).get("deduped_candidates")) or 0),
        }
    print(json.dumps(result_payload, indent=2))
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay the two-lane planner and query builders for a Firestore case.")
    parser.add_argument("--project-id", default=None, help="Firestore project document id")
    parser.add_argument("--kapitel-id", default=None, help="Kapitel document id")
    parser.add_argument("--run-id", default=None, help="Optional researchRun id to reuse effective settings")
    parser.add_argument("--user-id", default=None, help="Optional owner uid; if omitted the script searches for the project owner")
    parser.add_argument("--chapter-title", default=None, help="Direct chapter title input; bypasses Firestore when provided")
    parser.add_argument("--chapter-spec-text", default=None, help="Direct chapter spec text input; bypasses Firestore when provided")
    parser.add_argument("--planner-attempts", type=int, default=1, help="Number of planner attempts to run")
    parser.add_argument("--openalex-attempts", type=int, default=3, help="Number of OpenAlex builder attempts to run")
    parser.add_argument("--s2-attempts", type=int, default=3, help="Number of Semantic Scholar builder attempts to run")
    parser.add_argument("--probe-top-k", type=int, default=3, help="How many normalized queries to probe against providers per attempt")
    parser.add_argument("--run-fetch-and-candidates", action="store_true", help="After passing query generation, run provider fetches and candidate normalization (Phases D-E smoke test)")
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
