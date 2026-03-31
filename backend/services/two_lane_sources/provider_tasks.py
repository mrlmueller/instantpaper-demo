from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable

import requests
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.cloud_run_job_launcher import cloud_run_job_launcher
from services.quellen_finder_firestore_service import QuellenFinderFirestoreService
from services.two_lane_sources.pipeline import (
    OPENALEX_SELECT,
    S2_BATCH_FIELDS,
    S2_BULK_FIELDS,
    OpenAlexQuery,
    PipelineConfig,
    S2BulkQuery,
    _openalex_params,
    _query_hash,
    _s2_iter_batch_items,
    _chunked,
    request_json,
    stable_hash,
)
from services.two_lane_sources.provider_rate_limit import build_provider_rate_limiter
from services.two_lane_sources.storage import TwoLaneArtifactStore
from services.two_lane_sources.task_dispatch import build_two_lane_task_dispatcher
from utils.config import config

logger = logging.getLogger(__name__)

OPENALEX_STAGE = "openalex_fetch"
SEMANTICSCHOLAR_STAGE = "s2_fetch"


def _round_float(value: Any, digits: int = 3) -> float:
    return round(float(value or 0.0), int(digits))


def _request_stats_payload(stats: dict[str, Any]) -> dict[str, Any]:
    payload = dict(stats or {})
    if "rate_limit_wait_s" in payload:
        payload["rate_limit_wait_s"] = _round_float(payload.get("rate_limit_wait_s"))
    if "retry_backoff_wait_s" in payload:
        payload["retry_backoff_wait_s"] = _round_float(payload.get("retry_backoff_wait_s"))
    return payload


def _log_provider_task(event: str, **payload: Any) -> None:
    body = {"stage": "two_lane_provider_task", "event": str(event)}
    body.update(payload)
    logger.info(json.dumps(body, ensure_ascii=False, default=str))


def _run_is_terminal(run_doc: dict[str, Any] | None) -> bool:
    status_now = str(((run_doc or {}).get("status") if isinstance(run_doc, dict) else "") or "").strip().lower()
    if status_now in {"success", "error", "cancelled"}:
        return True
    return bool(((run_doc or {}).get("cancelRequestedAt")) if isinstance(run_doc, dict) else False)


def _provider_task_summary(*, page_index: int, records: int, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {"page_index": int(page_index), "records": int(records)}
    if isinstance(extra, dict) and extra:
        payload.update(extra)
    return payload


def _artifact_store_from_run_doc(run_doc: dict[str, Any] | None = None) -> TwoLaneArtifactStore:
    artifacts = (run_doc or {}).get("twoLaneArtifacts") if isinstance((run_doc or {}).get("twoLaneArtifacts"), dict) else {}
    bucket_name = (
        str((artifacts or {}).get("bucket") or config.TWO_LANE_ARTIFACT_BUCKET or "").strip()
        or str(config.FIREBASE_STORAGE_BUCKET or "").strip()
    )
    if not bucket_name:
        raise RuntimeError("TWO_LANE_ARTIFACT_BUCKET or FIREBASE_STORAGE_BUCKET must be configured.")
    return TwoLaneArtifactStore(
        bucket_name=bucket_name,
        base_prefix=str((artifacts or {}).get("basePrefix") or config.TWO_LANE_ARTIFACT_PREFIX or "").strip(),
        project_id=str(config.GOOGLE_CLOUD_PROJECT or config.FIREBASE_PROJECT_ID or "").strip(),
    )


def _provider_relative_prefix(*, artifact_store: TwoLaneArtifactStore, run_id: str, provider: str) -> str:
    return f"{artifact_store.run_prefix(run_id)}/provider/{str(provider).strip().lower()}/pages"


def _provider_meta_prefix(*, artifact_store: TwoLaneArtifactStore, run_id: str, provider: str) -> str:
    return f"{artifact_store.run_prefix(run_id)}/provider/{str(provider).strip().lower()}/meta"


def _openalex_task_key(*, query_hash: str, cursor: str, page_index: int) -> str:
    cursor_hash = stable_hash("openalex", str(query_hash), str(cursor or "*"), length=12)
    return f"oa-{str(query_hash)}-{int(page_index):06d}-{cursor_hash}"


def _s2_task_key(*, query_hash: str, token: str | None, page_index: int) -> str:
    token_hash = stable_hash("s2", str(query_hash), str(token or "start"), length=12)
    return f"s2-{str(query_hash)}-{int(page_index):06d}-{token_hash}"


def _openalex_query_task_key(*, query_hash: str, segment_index: int) -> str:
    return f"oaq-{str(query_hash)}-{int(segment_index):04d}"


def _s2_query_task_key(*, query_hash: str, segment_index: int) -> str:
    return f"s2q-{str(query_hash)}-{int(segment_index):04d}"


def _openalex_page_paths(
    *,
    artifact_store: TwoLaneArtifactStore,
    run_id: str,
    query_hash: str,
    page_index: int,
    cursor: str,
) -> tuple[str, str]:
    cursor_hash = stable_hash("oa-page", str(query_hash), str(cursor or "*"), length=12)
    base = _provider_relative_prefix(artifact_store=artifact_store, run_id=run_id, provider="openalex")
    meta = _provider_meta_prefix(artifact_store=artifact_store, run_id=run_id, provider="openalex")
    data_path = f"{base}/{query_hash}/{int(page_index):06d}_{cursor_hash}.jsonl"
    meta_path = f"{meta}/{query_hash}/{int(page_index):06d}_{cursor_hash}.json"
    return data_path, meta_path


def _s2_page_paths(
    *,
    artifact_store: TwoLaneArtifactStore,
    run_id: str,
    query_hash: str,
    page_index: int,
    token: str | None,
) -> tuple[str, str]:
    token_hash = stable_hash("s2-page", str(query_hash), str(token or "start"), length=12)
    base = _provider_relative_prefix(artifact_store=artifact_store, run_id=run_id, provider="semanticscholar")
    meta = _provider_meta_prefix(artifact_store=artifact_store, run_id=run_id, provider="semanticscholar")
    data_path = f"{base}/{query_hash}/{int(page_index):06d}_{token_hash}.jsonl"
    meta_path = f"{meta}/{query_hash}/{int(page_index):06d}_{token_hash}.json"
    return data_path, meta_path


def load_openalex_queries(*, run_dir: Path) -> list[OpenAlexQuery]:
    path = Path(run_dir).resolve() / "openalex_queries.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("openalex_queries") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("openalex_queries.json is missing openalex_queries")
    return [OpenAlexQuery.model_validate(item) for item in items]


def load_s2_queries(*, run_dir: Path) -> list[S2BulkQuery]:
    path = Path(run_dir).resolve() / "s2_bulk_queries.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("s2_bulk_queries") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("s2_bulk_queries.json is missing s2_bulk_queries")
    return [S2BulkQuery.model_validate(item) for item in items]


def seed_openalex_provider_tasks(
    *,
    user_id: str,
    projekt_id: str,
    run_id: str,
    queries: list[OpenAlexQuery],
    run_doc: dict[str, Any],
) -> dict[str, Any]:
    fs = QuellenFinderFirestoreService()
    dispatcher = build_two_lane_task_dispatcher()
    artifact_store = _artifact_store_from_run_doc(run_doc)
    results_prefix = _provider_relative_prefix(artifact_store=artifact_store, run_id=run_id, provider="openalex")
    seeded = 0

    for qi, query in enumerate(queries, start=1):
        query_hash = _query_hash("openalex", query)
        task_key = _openalex_query_task_key(query_hash=query_hash, segment_index=1)
        claimed = fs.enqueue_two_lane_provider_task(
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            provider="openalex",
            stage_name=OPENALEX_STAGE,
            queue_name=str(dispatcher.openalex_queue),
            task_key=task_key,
            results_prefix=results_prefix,
        )
        if not claimed:
            continue
        payload = {
            "kind": "openalex_query",
            "user_id": str(user_id),
            "projekt_id": str(projekt_id),
            "run_id": str(run_id),
            "provider": "openalex",
            "stage_name": OPENALEX_STAGE,
            "task_key": task_key,
            "query_i": int(qi),
            "query_hash": query_hash,
            "segment_index": 1,
            "start_page_index": 1,
            "start_cursor": "*",
            "query": query.model_dump(mode="json"),
        }
        dispatcher.enqueue(queue_key="openalex", task_name=task_key, payload=payload)
        seeded += 1

    fs.run_ref(user_id, projekt_id, run_id).set(
        {
            "updatedAt": SERVER_TIMESTAMP,
            "twoLaneArtifacts": {
                OPENALEX_STAGE: {
                    "resultsPrefix": results_prefix,
                    "seededTasks": int(seeded),
                    "taskMode": "query_chain",
                    "updatedAt": SERVER_TIMESTAMP,
                }
            },
        },
        merge=True,
    )
    return {"seeded_tasks": int(seeded), "results_prefix": results_prefix}


def seed_s2_provider_tasks(
    *,
    user_id: str,
    projekt_id: str,
    run_id: str,
    queries: list[S2BulkQuery],
    run_doc: dict[str, Any],
) -> dict[str, Any]:
    fs = QuellenFinderFirestoreService()
    dispatcher = build_two_lane_task_dispatcher()
    artifact_store = _artifact_store_from_run_doc(run_doc)
    results_prefix = _provider_relative_prefix(artifact_store=artifact_store, run_id=run_id, provider="semanticscholar")
    seeded = 0

    for qi, query in enumerate(queries, start=1):
        query_hash = _query_hash("semanticscholar", query)
        task_key = _s2_query_task_key(query_hash=query_hash, segment_index=1)
        claimed = fs.enqueue_two_lane_provider_task(
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            provider="semanticscholar",
            stage_name=SEMANTICSCHOLAR_STAGE,
            queue_name=str(dispatcher.semanticscholar_queue),
            task_key=task_key,
            results_prefix=results_prefix,
        )
        if not claimed:
            continue
        payload = {
            "kind": "s2_bulk_query",
            "user_id": str(user_id),
            "projekt_id": str(projekt_id),
            "run_id": str(run_id),
            "provider": "semanticscholar",
            "stage_name": SEMANTICSCHOLAR_STAGE,
            "task_key": task_key,
            "query_i": int(qi),
            "query_hash": query_hash,
            "segment_index": 1,
            "start_page_index": 1,
            "start_token": None,
            "query": query.model_dump(mode="json"),
            "bulk_limit": 100,
        }
        dispatcher.enqueue(queue_key="semanticscholar", task_name=task_key, payload=payload)
        seeded += 1

    fs.run_ref(user_id, projekt_id, run_id).set(
        {
            "updatedAt": SERVER_TIMESTAMP,
            "twoLaneArtifacts": {
                SEMANTICSCHOLAR_STAGE: {
                    "resultsPrefix": results_prefix,
                    "seededTasks": int(seeded),
                    "taskMode": "query_chain",
                    "updatedAt": SERVER_TIMESTAMP,
                }
            },
        },
        merge=True,
    )
    return {"seeded_tasks": int(seeded), "results_prefix": results_prefix}


def materialize_provider_results(
    *,
    artifact_store: TwoLaneArtifactStore,
    run_id: str,
    provider: str,
    destination: Path,
) -> dict[str, Any]:
    prefix = _provider_relative_prefix(artifact_store=artifact_store, run_id=run_id, provider=provider)
    objects = sorted(artifact_store.list_prefix(prefix=prefix), key=lambda item: item.object_name)
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    total_records = 0
    with destination.open("w", encoding="utf-8") as handle:
        for item in objects:
            if not str(item.object_name).endswith(".jsonl"):
                continue
            text = artifact_store.download_text(path_or_uri=item.uri)
            for line in str(text).splitlines():
                if not line.strip():
                    continue
                handle.write(line.rstrip() + "\n")
                total_records += 1
    return {"objects": int(len(objects)), "records": int(total_records), "prefix": prefix}


def _build_openalex_limiter(*, cfg: PipelineConfig, run_id: str):
    return build_provider_rate_limiter(
        provider="openalex",
        rps=cfg.openalex_rps,
        backend=cfg.provider_rate_limit_backend,
        collection_name=cfg.provider_rate_limit_collection,
        holder=f"task:{run_id}",
        run_id=run_id,
        stage="phase_d_openalex_retrieval",
        max_future_ms=cfg.provider_rate_limit_max_future_ms,
        dispatch_buffer_ms=cfg.provider_rate_limit_dispatch_buffer_ms,
    )


def _build_s2_limiter(*, cfg: PipelineConfig, run_id: str, stage: str):
    return build_provider_rate_limiter(
        provider="semanticscholar",
        rps=cfg.semanticscholar_rps,
        backend=cfg.provider_rate_limit_backend,
        collection_name=cfg.provider_rate_limit_collection,
        holder=f"task:{run_id}",
        run_id=run_id,
        stage=stage,
        max_future_ms=cfg.provider_rate_limit_max_future_ms,
        dispatch_buffer_ms=cfg.provider_rate_limit_dispatch_buffer_ms,
    )


async def _maybe_launch_candidates(*, user_id: str, projekt_id: str, run_id: str) -> bool:
    fs = QuellenFinderFirestoreService()
    claimed = await __import__("asyncio").to_thread(
        fs.try_queue_two_lane_stage,
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        target_stage="candidates",
        prerequisite_stages=[OPENALEX_STAGE, SEMANTICSCHOLAR_STAGE],
        allowed_current_statuses=["pending"],
        current_stage_value="candidates",
    )
    if not claimed:
        return False
    launch = await __import__("asyncio").to_thread(
        cloud_run_job_launcher.execute_two_lane_sources_job,
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        stage="candidates",
    )
    fs.run_ref(user_id, projekt_id, run_id).set(
        {
            "updatedAt": SERVER_TIMESTAMP,
            "splitExecution": {
                "candidates": {
                    "jobName": (launch or {}).get("job_name"),
                    "region": (launch or {}).get("region"),
                    "executionName": (launch or {}).get("execution_name"),
                    "operationName": (launch or {}).get("operation_name"),
                    "updatedAt": SERVER_TIMESTAMP,
                }
            },
        },
        merge=True,
    )
    return True


async def _skip_due_to_terminal_run(
    *,
    fs: QuellenFinderFirestoreService,
    user_id: str,
    projekt_id: str,
    run_id: str,
    provider: str,
    task_key: str,
    stage_name: str,
    reason: str,
    summary: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    result = await __import__("asyncio").to_thread(
        fs.skip_two_lane_provider_task,
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        provider=provider,
        task_key=task_key,
        stage_name=stage_name,
        reason=reason,
        summary=summary,
        error_message=error_message,
    )
    return result if isinstance(result, dict) else {"provider_done": False, "already_done": False}


async def _requeue_task_failure(
    *,
    fs: QuellenFinderFirestoreService,
    user_id: str,
    projekt_id: str,
    run_id: str,
    provider: str,
    task_key: str,
    stage_name: str,
    error_message: str,
) -> dict[str, Any]:
    result = await __import__("asyncio").to_thread(
        fs.retry_two_lane_provider_task,
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        provider=provider,
        task_key=task_key,
        stage_name=stage_name,
        error_message=error_message,
    )
    return result if isinstance(result, dict) else {"retry_queued": False, "already_done": False}


def _dispatcher_supports_local_retry(dispatcher) -> bool:
    backend = str(getattr(dispatcher, "backend", "") or "").strip().lower()
    return backend in {"local_background", "local_thread", "local", "local_inline", "inline"}


async def _schedule_local_retry_if_needed(
    *,
    queue_key: str,
    task_key: str,
    payload: dict[str, Any],
    delay_seconds: float = 15.0,
) -> bool:
    dispatcher = build_two_lane_task_dispatcher()
    if not _dispatcher_supports_local_retry(dispatcher):
        return False
    await __import__("asyncio").to_thread(
        dispatcher.enqueue,
        queue_key=queue_key,
        task_name=task_key,
        payload=dict(payload),
        schedule_delay_seconds=float(delay_seconds),
    )
    return True


def _segment_limit_reason(
    *,
    started_at_monotonic: float,
    pages_processed: int,
    max_pages_per_task: int,
    max_runtime_s: float,
) -> str | None:
    if int(max_pages_per_task) > 0 and int(pages_processed) >= int(max_pages_per_task):
        return "max_pages"
    if float(max_runtime_s) > 0 and (__import__("time").monotonic() - float(started_at_monotonic)) >= float(max_runtime_s):
        return "max_runtime"
    return None


async def process_openalex_query_task(payload: dict[str, Any]) -> dict[str, Any]:
    user_id = str(payload.get("user_id") or "").strip()
    projekt_id = str(payload.get("projekt_id") or "").strip()
    run_id = str(payload.get("run_id") or "").strip()
    task_key = str(payload.get("task_key") or "").strip()
    if not user_id or not projekt_id or not run_id or not task_key:
        raise ValueError("openalex query task payload is missing identifiers")

    fs = QuellenFinderFirestoreService()
    claimed = await __import__("asyncio").to_thread(
        fs.claim_two_lane_provider_task,
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        provider="openalex",
        task_key=task_key,
    )
    if not claimed:
        return {"claimed": False, "task_key": task_key}

    run_doc = await __import__("asyncio").to_thread(fs.get_run, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
    if _run_is_terminal(run_doc):
        await _skip_due_to_terminal_run(
            fs=fs,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            provider="openalex",
            task_key=task_key,
            stage_name=OPENALEX_STAGE,
            reason="terminal_before_fetch",
        )
        return {"claimed": True, "task_key": task_key, "skipped": True}

    artifact_store = _artifact_store_from_run_doc(run_doc)
    query = OpenAlexQuery.model_validate(payload.get("query") or {})
    query_hash = str(payload.get("query_hash") or _query_hash("openalex", query)).strip()
    segment_index = max(1, int(payload.get("segment_index") or 1))
    page_index = max(1, int(payload.get("start_page_index") or payload.get("page_index") or 1))
    cursor = str(payload.get("start_cursor") or payload.get("cursor") or "*")

    cfg = PipelineConfig.from_env(runs_root=Path("."), pipeline_version="two_lane_v1")
    session = requests.Session()
    session.headers.update({"User-Agent": "instantpaper-two-lane/1.0"})
    limiter = _build_openalex_limiter(cfg=cfg, run_id=run_id)
    started_at = __import__("time").monotonic()
    task_started_at = __import__("time").monotonic()
    pages_processed = 0
    total_records = 0
    final_page_index = max(0, int(page_index) - 1)
    continuation_task_key: str | None = None
    continuation_page_index: int | None = None
    continuation_cursor: str | None = None
    continuation_reason: str | None = None
    cache_hit_pages = 0
    cache_miss_pages = 0
    task_http_stats: dict[str, Any] = {"request_attempts": 0, "rate_limit_wait_s": 0.0, "retry_backoff_wait_s": 0.0}

    _log_provider_task(
        "start",
        provider="openalex",
        task_kind="openalex_query",
        stage_name=OPENALEX_STAGE,
        run_id=run_id,
        projekt_id=projekt_id,
        task_key=task_key,
        query_i=int(payload.get("query_i") or 0),
        query_hash=query_hash,
        segment_index=int(segment_index),
        start_page_index=int(page_index),
        max_pages_per_task=int(cfg.openalex_task_max_pages_per_task),
        max_runtime_s=float(cfg.provider_task_max_runtime_s),
    )

    try:
        while True:
            data_path, meta_path = _openalex_page_paths(
                artifact_store=artifact_store,
                run_id=run_id,
                query_hash=query_hash,
                page_index=page_index,
                cursor=cursor,
            )
            meta: dict[str, Any]
            if artifact_store.exists(path_or_uri=meta_path):
                cache_hit_pages += 1
                meta = artifact_store.download_json(path_or_uri=meta_path)
            else:
                cache_miss_pages += 1
                data = request_json(
                    run_ctx=None,
                    stage="phase_d_openalex_retrieval",
                    provider="openalex",
                    session=session,
                    method="GET",
                    url=cfg.openalex_base_url.rstrip("/") + "/works",
                    params=_openalex_params(cfg, query, cursor=cursor),
                    body=None,
                    timeout_s=float(cfg.openalex_timeout_s),
                    rate_limiter=limiter,
                    request_stats=task_http_stats,
                    max_attempts=8,
                    backoff_initial_s=1.0,
                    backoff_max_s=60.0,
                )
                results = (data or {}).get("results") or []
                lines = []
                for rank, work in enumerate(results, start=1):
                    lines.append(
                        json.dumps(
                            {
                                "run_id": run_id,
                                "provider": "openalex",
                                "query_hash": query_hash,
                                "query_i": int(payload.get("query_i") or 0),
                                "intent": query.intent,
                                "language": query.language,
                                "rank": int(((page_index - 1) * int(query.per_page or 200)) + rank),
                                "work": work,
                            },
                            ensure_ascii=False,
                        )
                    )
                artifact_store.upload_text(
                    text="\n".join(lines) + ("\n" if lines else ""),
                    path_or_uri=data_path,
                    content_type="application/x-ndjson; charset=utf-8",
                )
                meta = {
                    "query_hash": query_hash,
                    "page_index": int(page_index),
                    "cursor": cursor,
                    "next_cursor": ((data or {}).get("meta") or {}).get("next_cursor"),
                    "records": int(len(lines)),
                    "dataPath": data_path,
                }
                artifact_store.upload_json(payload=meta, path_or_uri=meta_path)

            pages_processed += 1
            total_records += int(meta.get("records") or 0)
            final_page_index = int(page_index)

            run_doc_after_page = await __import__("asyncio").to_thread(fs.get_run, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
            if _run_is_terminal(run_doc_after_page):
                await _skip_due_to_terminal_run(
                    fs=fs,
                    user_id=user_id,
                    projekt_id=projekt_id,
                    run_id=run_id,
                    provider="openalex",
                    task_key=task_key,
                    stage_name=OPENALEX_STAGE,
                    reason="terminal_after_fetch",
                    summary={
                        "start_page_index": int(payload.get("start_page_index") or 1),
                        "final_page_index": int(final_page_index),
                        "pages_processed": int(pages_processed),
                        "records": int(total_records),
                    },
                )
                return {"claimed": True, "task_key": task_key, "records": int(total_records), "skipped": True}

            next_cursor = str(meta.get("next_cursor") or "").strip() or None
            if not next_cursor:
                break

            continuation_reason = _segment_limit_reason(
                started_at_monotonic=started_at,
                pages_processed=pages_processed,
                max_pages_per_task=int(cfg.openalex_task_max_pages_per_task),
                max_runtime_s=float(cfg.provider_task_max_runtime_s),
            )
            if continuation_reason:
                next_segment_index = int(segment_index) + 1
                continuation_task_key = _openalex_query_task_key(query_hash=query_hash, segment_index=next_segment_index)
                continuation_page_index = int(page_index) + 1
                continuation_cursor = str(next_cursor)
                dispatcher = build_two_lane_task_dispatcher()
                queued = await __import__("asyncio").to_thread(
                    fs.enqueue_two_lane_provider_task,
                    user_id=user_id,
                    projekt_id=projekt_id,
                    run_id=run_id,
                    provider="openalex",
                    stage_name=OPENALEX_STAGE,
                    queue_name=str(dispatcher.openalex_queue),
                    task_key=continuation_task_key,
                    results_prefix=_provider_relative_prefix(artifact_store=artifact_store, run_id=run_id, provider="openalex"),
                )
                if queued:
                    dispatcher.enqueue(
                        queue_key="openalex",
                        task_name=continuation_task_key,
                        payload={
                            "kind": "openalex_query",
                            "user_id": user_id,
                            "projekt_id": projekt_id,
                            "run_id": run_id,
                            "provider": "openalex",
                            "stage_name": OPENALEX_STAGE,
                            "task_key": continuation_task_key,
                            "query_i": int(payload.get("query_i") or 0),
                            "query_hash": query_hash,
                            "segment_index": next_segment_index,
                            "start_page_index": continuation_page_index,
                            "start_cursor": continuation_cursor,
                            "query": query.model_dump(mode="json"),
                        },
                    )
                _log_provider_task(
                    "continuation_enqueued",
                    provider="openalex",
                    task_kind="openalex_query",
                    stage_name=OPENALEX_STAGE,
                    run_id=run_id,
                    task_key=task_key,
                    query_hash=query_hash,
                    segment_index=int(segment_index),
                    continuation_task_key=continuation_task_key,
                    continuation_page_index=int(continuation_page_index or 0),
                    continuation_reason=continuation_reason,
                    pages_processed=int(pages_processed),
                    request_stats=_request_stats_payload(task_http_stats),
                )
                break

            page_index += 1
            cursor = str(next_cursor)

        result = await __import__("asyncio").to_thread(
            fs.complete_two_lane_provider_task,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            provider="openalex",
            task_key=task_key,
            stage_name=OPENALEX_STAGE,
            summary={
                "segment_index": int(segment_index),
                "start_page_index": int(payload.get("start_page_index") or 1),
                "final_page_index": int(final_page_index),
                "pages_processed": int(pages_processed),
                "records": int(total_records),
                "continued": bool(continuation_task_key),
                "continuation_task_key": continuation_task_key,
                "continuation_page_index": continuation_page_index,
            },
        )
        if bool((result or {}).get("provider_done")):
            await _maybe_launch_candidates(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        wall_time_s = __import__("time").monotonic() - task_started_at
        _log_provider_task(
            "success",
            provider="openalex",
            task_kind="openalex_query",
            stage_name=OPENALEX_STAGE,
            run_id=run_id,
            task_key=task_key,
            query_hash=query_hash,
            segment_index=int(segment_index),
            start_page_index=int(payload.get("start_page_index") or 1),
            final_page_index=int(final_page_index),
            pages_processed=int(pages_processed),
            records=int(total_records),
            cache_hit_pages=int(cache_hit_pages),
            cache_miss_pages=int(cache_miss_pages),
            continued=bool(continuation_task_key),
            continuation_reason=continuation_reason,
            provider_done=bool((result or {}).get("provider_done")),
            wall_time_s=_round_float(wall_time_s),
            request_stats=_request_stats_payload(task_http_stats),
        )
        return {
            "claimed": True,
            "task_key": task_key,
            "records": int(total_records),
            "pages_processed": int(pages_processed),
            "continued": bool(continuation_task_key),
            "continuation_task_key": continuation_task_key,
        }
    except Exception as exc:
        wall_time_s = __import__("time").monotonic() - task_started_at
        _log_provider_task(
            "error",
            provider="openalex",
            task_kind="openalex_query",
            stage_name=OPENALEX_STAGE,
            run_id=run_id,
            task_key=task_key,
            query_hash=query_hash,
            segment_index=int(segment_index),
            start_page_index=int(payload.get("start_page_index") or 1),
            pages_processed=int(pages_processed),
            records=int(total_records),
            cache_hit_pages=int(cache_hit_pages),
            cache_miss_pages=int(cache_miss_pages),
            wall_time_s=_round_float(wall_time_s),
            error=str(exc),
            request_stats=_request_stats_payload(task_http_stats),
        )
        latest_run_doc = await __import__("asyncio").to_thread(fs.get_run, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        if _run_is_terminal(latest_run_doc):
            await _skip_due_to_terminal_run(
                fs=fs,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                provider="openalex",
                task_key=task_key,
                stage_name=OPENALEX_STAGE,
                reason="terminal_on_error",
                error_message=str(exc),
            )
        else:
            retry_state = await _requeue_task_failure(
                fs=fs,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                provider="openalex",
                task_key=task_key,
                stage_name=OPENALEX_STAGE,
                error_message=str(exc),
            )
            if bool((retry_state or {}).get("retry_queued")):
                _log_provider_task(
                    "retry_queued",
                    provider="openalex",
                    task_kind="openalex_query",
                    stage_name=OPENALEX_STAGE,
                    run_id=run_id,
                    task_key=task_key,
                    query_hash=query_hash,
                    segment_index=int(segment_index),
                    error=str(exc),
                )
                if await _schedule_local_retry_if_needed(
                    queue_key="openalex",
                    task_key=task_key,
                    payload=payload,
                ):
                    return {"claimed": True, "task_key": task_key, "retry_scheduled": True, "error": str(exc)}
        raise


async def process_s2_bulk_query_task(payload: dict[str, Any]) -> dict[str, Any]:
    user_id = str(payload.get("user_id") or "").strip()
    projekt_id = str(payload.get("projekt_id") or "").strip()
    run_id = str(payload.get("run_id") or "").strip()
    task_key = str(payload.get("task_key") or "").strip()
    if not user_id or not projekt_id or not run_id or not task_key:
        raise ValueError("s2 query task payload is missing identifiers")

    fs = QuellenFinderFirestoreService()
    claimed = await __import__("asyncio").to_thread(
        fs.claim_two_lane_provider_task,
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        provider="semanticscholar",
        task_key=task_key,
    )
    if not claimed:
        return {"claimed": False, "task_key": task_key}

    run_doc = await __import__("asyncio").to_thread(fs.get_run, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
    if _run_is_terminal(run_doc):
        await _skip_due_to_terminal_run(
            fs=fs,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            provider="semanticscholar",
            task_key=task_key,
            stage_name=SEMANTICSCHOLAR_STAGE,
            reason="terminal_before_fetch",
        )
        return {"claimed": True, "task_key": task_key, "skipped": True}

    artifact_store = _artifact_store_from_run_doc(run_doc)
    query = S2BulkQuery.model_validate(payload.get("query") or {})
    query_hash = str(payload.get("query_hash") or _query_hash("semanticscholar", query)).strip()
    segment_index = max(1, int(payload.get("segment_index") or 1))
    page_index = max(1, int(payload.get("start_page_index") or payload.get("page_index") or 1))
    token = payload.get("start_token", payload.get("token"))
    token_s = str(token).strip() if token is not None else None
    bulk_limit = max(1, int(payload.get("bulk_limit") or 100))

    cfg = PipelineConfig.from_env(runs_root=Path("."), pipeline_version="two_lane_v1")
    session = requests.Session()
    session.headers.update({"User-Agent": "instantpaper-two-lane/1.0"})
    if cfg.semanticscholar_api_key:
        session.headers.update({"x-api-key": cfg.semanticscholar_api_key})
    limiter = _build_s2_limiter(cfg=cfg, run_id=run_id, stage="phase_d_semanticscholar_retrieval")
    base = cfg.semanticscholar_base_url.rstrip("/")
    started_at = __import__("time").monotonic()
    task_started_at = __import__("time").monotonic()
    pages_processed = 0
    total_records = 0
    total_ids_seen = 0
    final_page_index = max(0, int(page_index) - 1)
    continuation_task_key: str | None = None
    continuation_page_index: int | None = None
    continuation_token: str | None = None
    continuation_reason: str | None = None
    cache_hit_pages = 0
    cache_miss_pages = 0
    task_http_stats: dict[str, Any] = {"request_attempts": 0, "rate_limit_wait_s": 0.0, "retry_backoff_wait_s": 0.0}

    _log_provider_task(
        "start",
        provider="semanticscholar",
        task_kind="s2_bulk_query",
        stage_name=SEMANTICSCHOLAR_STAGE,
        run_id=run_id,
        projekt_id=projekt_id,
        task_key=task_key,
        query_i=int(payload.get("query_i") or 0),
        query_hash=query_hash,
        segment_index=int(segment_index),
        start_page_index=int(page_index),
        max_pages_per_task=int(cfg.semanticscholar_task_max_pages_per_task),
        max_runtime_s=float(cfg.provider_task_max_runtime_s),
    )

    try:
        while True:
            data_path, meta_path = _s2_page_paths(
                artifact_store=artifact_store,
                run_id=run_id,
                query_hash=query_hash,
                page_index=page_index,
                token=token_s,
            )
            meta: dict[str, Any]
            if artifact_store.exists(path_or_uri=meta_path):
                cache_hit_pages += 1
                meta = artifact_store.download_json(path_or_uri=meta_path)
            else:
                cache_miss_pages += 1
                params: dict[str, Any] = {"query": query.query_string, "fields": S2_BULK_FIELDS, "limit": int(bulk_limit)}
                if token_s:
                    params["token"] = token_s
                page = request_json(
                    run_ctx=None,
                    stage="phase_d_semanticscholar_retrieval",
                    provider="semanticscholar",
                    session=session,
                    method="GET",
                    url=base + "/paper/search/bulk",
                    params=params,
                    body=None,
                    timeout_s=float(cfg.semanticscholar_timeout_s),
                    rate_limiter=limiter,
                    request_stats=task_http_stats,
                    max_attempts=10,
                    backoff_initial_s=2.0,
                    backoff_max_s=120.0,
                )

                items = (page or {}).get("data") or []
                ids: list[str] = []
                ranks: dict[str, int] = {}
                for rank, item in enumerate(items, start=1):
                    if not isinstance(item, dict):
                        continue
                    paper_id = item.get("paperId")
                    if not paper_id:
                        continue
                    paper_id_s = str(paper_id)
                    ids.append(paper_id_s)
                    ranks[paper_id_s] = int(((page_index - 1) * int(bulk_limit)) + rank)

                hydrated: list[dict[str, Any]] = []
                if ids:
                    for chunk in _chunked(ids, 500):
                        batch = request_json(
                            run_ctx=None,
                            stage="phase_d_semanticscholar_retrieval",
                            provider="semanticscholar",
                            session=session,
                            method="POST",
                            url=base + "/paper/batch",
                            params={"fields": S2_BATCH_FIELDS},
                            body={"ids": chunk},
                            timeout_s=float(cfg.semanticscholar_timeout_s),
                            rate_limiter=limiter,
                            request_stats=task_http_stats,
                            max_attempts=10,
                            backoff_initial_s=2.0,
                            backoff_max_s=120.0,
                        )
                        hydrated.extend(_s2_iter_batch_items(batch))

                lines = []
                for paper in hydrated:
                    paper_id = str(paper.get("paperId") or "").strip()
                    if not paper_id:
                        continue
                    lines.append(
                        json.dumps(
                            {
                                "run_id": run_id,
                                "provider": "semanticscholar",
                                "query_hash": query_hash,
                                "query_i": int(payload.get("query_i") or 0),
                                "intent": query.intent,
                                "language": query.language,
                                "rank": int(ranks.get(paper_id) or 0),
                                "paper": paper,
                            },
                            ensure_ascii=False,
                        )
                    )
                artifact_store.upload_text(
                    text="\n".join(lines) + ("\n" if lines else ""),
                    path_or_uri=data_path,
                    content_type="application/x-ndjson; charset=utf-8",
                )
                meta = {
                    "query_hash": query_hash,
                    "page_index": int(page_index),
                    "token": token_s,
                    "next_token": (page or {}).get("token") or (page or {}).get("next"),
                    "ids_seen": int(len(ids)),
                    "records": int(len(lines)),
                    "dataPath": data_path,
                }
                artifact_store.upload_json(payload=meta, path_or_uri=meta_path)

            pages_processed += 1
            total_records += int(meta.get("records") or 0)
            total_ids_seen += int(meta.get("ids_seen") or 0)
            final_page_index = int(page_index)

            run_doc_after_page = await __import__("asyncio").to_thread(fs.get_run, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
            if _run_is_terminal(run_doc_after_page):
                await _skip_due_to_terminal_run(
                    fs=fs,
                    user_id=user_id,
                    projekt_id=projekt_id,
                    run_id=run_id,
                    provider="semanticscholar",
                    task_key=task_key,
                    stage_name=SEMANTICSCHOLAR_STAGE,
                    reason="terminal_after_fetch",
                    summary={
                        "start_page_index": int(payload.get("start_page_index") or 1),
                        "final_page_index": int(final_page_index),
                        "pages_processed": int(pages_processed),
                        "records": int(total_records),
                        "ids_seen": int(total_ids_seen),
                    },
                )
                return {"claimed": True, "task_key": task_key, "records": int(total_records), "skipped": True}

            next_token = str(meta.get("next_token") or "").strip() or None
            if not next_token:
                break

            continuation_reason = _segment_limit_reason(
                started_at_monotonic=started_at,
                pages_processed=pages_processed,
                max_pages_per_task=int(cfg.semanticscholar_task_max_pages_per_task),
                max_runtime_s=float(cfg.provider_task_max_runtime_s),
            )
            if continuation_reason:
                next_segment_index = int(segment_index) + 1
                continuation_task_key = _s2_query_task_key(query_hash=query_hash, segment_index=next_segment_index)
                continuation_page_index = int(page_index) + 1
                continuation_token = str(next_token)
                dispatcher = build_two_lane_task_dispatcher()
                queued = await __import__("asyncio").to_thread(
                    fs.enqueue_two_lane_provider_task,
                    user_id=user_id,
                    projekt_id=projekt_id,
                    run_id=run_id,
                    provider="semanticscholar",
                    stage_name=SEMANTICSCHOLAR_STAGE,
                    queue_name=str(dispatcher.semanticscholar_queue),
                    task_key=continuation_task_key,
                    results_prefix=_provider_relative_prefix(artifact_store=artifact_store, run_id=run_id, provider="semanticscholar"),
                )
                if queued:
                    dispatcher.enqueue(
                        queue_key="semanticscholar",
                        task_name=continuation_task_key,
                        payload={
                            "kind": "s2_bulk_query",
                            "user_id": user_id,
                            "projekt_id": projekt_id,
                            "run_id": run_id,
                            "provider": "semanticscholar",
                            "stage_name": SEMANTICSCHOLAR_STAGE,
                            "task_key": continuation_task_key,
                            "query_i": int(payload.get("query_i") or 0),
                            "query_hash": query_hash,
                            "segment_index": next_segment_index,
                            "start_page_index": continuation_page_index,
                            "start_token": continuation_token,
                            "query": query.model_dump(mode="json"),
                            "bulk_limit": int(bulk_limit),
                        },
                    )
                _log_provider_task(
                    "continuation_enqueued",
                    provider="semanticscholar",
                    task_kind="s2_bulk_query",
                    stage_name=SEMANTICSCHOLAR_STAGE,
                    run_id=run_id,
                    task_key=task_key,
                    query_hash=query_hash,
                    segment_index=int(segment_index),
                    continuation_task_key=continuation_task_key,
                    continuation_page_index=int(continuation_page_index or 0),
                    continuation_reason=continuation_reason,
                    pages_processed=int(pages_processed),
                    ids_seen=int(total_ids_seen),
                    request_stats=_request_stats_payload(task_http_stats),
                )
                break

            page_index += 1
            token_s = str(next_token)

        result = await __import__("asyncio").to_thread(
            fs.complete_two_lane_provider_task,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            provider="semanticscholar",
            task_key=task_key,
            stage_name=SEMANTICSCHOLAR_STAGE,
            summary={
                "segment_index": int(segment_index),
                "start_page_index": int(payload.get("start_page_index") or 1),
                "final_page_index": int(final_page_index),
                "pages_processed": int(pages_processed),
                "records": int(total_records),
                "ids_seen": int(total_ids_seen),
                "continued": bool(continuation_task_key),
                "continuation_task_key": continuation_task_key,
                "continuation_page_index": continuation_page_index,
            },
        )
        if bool((result or {}).get("provider_done")):
            await _maybe_launch_candidates(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        wall_time_s = __import__("time").monotonic() - task_started_at
        _log_provider_task(
            "success",
            provider="semanticscholar",
            task_kind="s2_bulk_query",
            stage_name=SEMANTICSCHOLAR_STAGE,
            run_id=run_id,
            task_key=task_key,
            query_hash=query_hash,
            segment_index=int(segment_index),
            start_page_index=int(payload.get("start_page_index") or 1),
            final_page_index=int(final_page_index),
            pages_processed=int(pages_processed),
            records=int(total_records),
            ids_seen=int(total_ids_seen),
            cache_hit_pages=int(cache_hit_pages),
            cache_miss_pages=int(cache_miss_pages),
            continued=bool(continuation_task_key),
            continuation_reason=continuation_reason,
            provider_done=bool((result or {}).get("provider_done")),
            wall_time_s=_round_float(wall_time_s),
            request_stats=_request_stats_payload(task_http_stats),
        )
        return {
            "claimed": True,
            "task_key": task_key,
            "records": int(total_records),
            "pages_processed": int(pages_processed),
            "ids_seen": int(total_ids_seen),
            "continued": bool(continuation_task_key),
            "continuation_task_key": continuation_task_key,
        }
    except Exception as exc:
        wall_time_s = __import__("time").monotonic() - task_started_at
        _log_provider_task(
            "error",
            provider="semanticscholar",
            task_kind="s2_bulk_query",
            stage_name=SEMANTICSCHOLAR_STAGE,
            run_id=run_id,
            task_key=task_key,
            query_hash=query_hash,
            segment_index=int(segment_index),
            start_page_index=int(payload.get("start_page_index") or 1),
            pages_processed=int(pages_processed),
            records=int(total_records),
            ids_seen=int(total_ids_seen),
            cache_hit_pages=int(cache_hit_pages),
            cache_miss_pages=int(cache_miss_pages),
            wall_time_s=_round_float(wall_time_s),
            error=str(exc),
            request_stats=_request_stats_payload(task_http_stats),
        )
        latest_run_doc = await __import__("asyncio").to_thread(fs.get_run, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        if _run_is_terminal(latest_run_doc):
            await _skip_due_to_terminal_run(
                fs=fs,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                provider="semanticscholar",
                task_key=task_key,
                stage_name=SEMANTICSCHOLAR_STAGE,
                reason="terminal_on_error",
                error_message=str(exc),
            )
        else:
            retry_state = await _requeue_task_failure(
                fs=fs,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                provider="semanticscholar",
                task_key=task_key,
                stage_name=SEMANTICSCHOLAR_STAGE,
                error_message=str(exc),
            )
            if bool((retry_state or {}).get("retry_queued")):
                _log_provider_task(
                    "retry_queued",
                    provider="semanticscholar",
                    task_kind="s2_bulk_query",
                    stage_name=SEMANTICSCHOLAR_STAGE,
                    run_id=run_id,
                    task_key=task_key,
                    query_hash=query_hash,
                    segment_index=int(segment_index),
                    error=str(exc),
                )
                if await _schedule_local_retry_if_needed(
                    queue_key="semanticscholar",
                    task_key=task_key,
                    payload=payload,
                ):
                    return {"claimed": True, "task_key": task_key, "retry_scheduled": True, "error": str(exc)}
        raise


async def process_openalex_page_task(payload: dict[str, Any]) -> dict[str, Any]:
    user_id = str(payload.get("user_id") or "").strip()
    projekt_id = str(payload.get("projekt_id") or "").strip()
    run_id = str(payload.get("run_id") or "").strip()
    task_key = str(payload.get("task_key") or "").strip()
    if not user_id or not projekt_id or not run_id or not task_key:
        raise ValueError("openalex task payload is missing identifiers")

    fs = QuellenFinderFirestoreService()
    claimed = await __import__("asyncio").to_thread(
        fs.claim_two_lane_provider_task,
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        provider="openalex",
        task_key=task_key,
    )
    if not claimed:
        return {"claimed": False, "task_key": task_key}

    run_doc = await __import__("asyncio").to_thread(fs.get_run, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
    if _run_is_terminal(run_doc):
        await _skip_due_to_terminal_run(
            fs=fs,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            provider="openalex",
            task_key=task_key,
            stage_name=OPENALEX_STAGE,
            reason="terminal_before_fetch",
        )
        return {"claimed": True, "task_key": task_key, "skipped": True}
    artifact_store = _artifact_store_from_run_doc(run_doc)
    query = OpenAlexQuery.model_validate(payload.get("query") or {})
    query_hash = str(payload.get("query_hash") or _query_hash("openalex", query)).strip()
    page_index = int(payload.get("page_index") or 1)
    cursor = str(payload.get("cursor") or "*")
    data_path, meta_path = _openalex_page_paths(
        artifact_store=artifact_store,
        run_id=run_id,
        query_hash=query_hash,
        page_index=page_index,
        cursor=cursor,
    )

    try:
        meta: dict[str, Any]
        if artifact_store.exists(path_or_uri=meta_path):
            meta = artifact_store.download_json(path_or_uri=meta_path)
        else:
            cfg = PipelineConfig.from_env(runs_root=Path("."), pipeline_version="two_lane_v1")
            session = requests.Session()
            session.headers.update({"User-Agent": "instantpaper-two-lane/1.0"})
            limiter = _build_openalex_limiter(cfg=cfg, run_id=run_id)
            data = request_json(
                run_ctx=None,
                stage="phase_d_openalex_retrieval",
                provider="openalex",
                session=session,
                method="GET",
                url=cfg.openalex_base_url.rstrip("/") + "/works",
                params=_openalex_params(cfg, query, cursor=cursor),
                body=None,
                timeout_s=float(cfg.openalex_timeout_s),
                rate_limiter=limiter,
                max_attempts=8,
                backoff_initial_s=1.0,
                backoff_max_s=60.0,
            )
            results = (data or {}).get("results") or []
            lines = []
            for rank, work in enumerate(results, start=1):
                lines.append(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "provider": "openalex",
                            "query_hash": query_hash,
                            "query_i": int(payload.get("query_i") or 0),
                            "intent": query.intent,
                            "language": query.language,
                            "rank": int(((page_index - 1) * int(query.per_page or 200)) + rank),
                            "work": work,
                        },
                        ensure_ascii=False,
                    )
                )
            artifact_store.upload_text(
                text="\n".join(lines) + ("\n" if lines else ""),
                path_or_uri=data_path,
                content_type="application/x-ndjson; charset=utf-8",
            )
            meta = {
                "query_hash": query_hash,
                "page_index": int(page_index),
                "cursor": cursor,
                "next_cursor": ((data or {}).get("meta") or {}).get("next_cursor"),
                "records": int(len(lines)),
                "dataPath": data_path,
            }
            artifact_store.upload_json(payload=meta, path_or_uri=meta_path)

        run_doc_after_fetch = await __import__("asyncio").to_thread(fs.get_run, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        if _run_is_terminal(run_doc_after_fetch):
            await _skip_due_to_terminal_run(
                fs=fs,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                provider="openalex",
                task_key=task_key,
                stage_name=OPENALEX_STAGE,
                reason="terminal_after_fetch",
                summary=_provider_task_summary(page_index=page_index, records=int(meta.get("records") or 0)),
            )
            return {"claimed": True, "task_key": task_key, "records": int(meta.get("records") or 0), "skipped": True}

        next_cursor = str(meta.get("next_cursor") or "").strip() or None
        if next_cursor:
            next_page_index = int(page_index) + 1
            next_task_key = _openalex_task_key(query_hash=query_hash, cursor=next_cursor, page_index=next_page_index)
            dispatcher = build_two_lane_task_dispatcher()
            queued = await __import__("asyncio").to_thread(
                fs.enqueue_two_lane_provider_task,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                provider="openalex",
                stage_name=OPENALEX_STAGE,
                queue_name=str(dispatcher.openalex_queue),
                task_key=next_task_key,
                results_prefix=_provider_relative_prefix(artifact_store=artifact_store, run_id=run_id, provider="openalex"),
            )
            if queued:
                dispatcher.enqueue(
                    queue_key="openalex",
                    task_name=next_task_key,
                    payload={
                        "kind": "openalex_page",
                        "user_id": user_id,
                        "projekt_id": projekt_id,
                        "run_id": run_id,
                        "provider": "openalex",
                        "stage_name": OPENALEX_STAGE,
                        "task_key": next_task_key,
                        "query_i": int(payload.get("query_i") or 0),
                        "query_hash": query_hash,
                        "page_index": next_page_index,
                        "cursor": next_cursor,
                        "query": query.model_dump(mode="json"),
                    },
                )

        result = await __import__("asyncio").to_thread(
            fs.complete_two_lane_provider_task,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            provider="openalex",
            task_key=task_key,
            stage_name=OPENALEX_STAGE,
            summary=_provider_task_summary(page_index=page_index, records=int(meta.get("records") or 0)),
        )
        if bool((result or {}).get("provider_done")):
            await _maybe_launch_candidates(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        return {"claimed": True, "task_key": task_key, "records": int(meta.get("records") or 0)}
    except Exception as exc:
        latest_run_doc = await __import__("asyncio").to_thread(fs.get_run, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        if _run_is_terminal(latest_run_doc):
            await _skip_due_to_terminal_run(
                fs=fs,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                provider="openalex",
                task_key=task_key,
                stage_name=OPENALEX_STAGE,
                reason="terminal_on_error",
                error_message=str(exc),
            )
        else:
            retry_state = await _requeue_task_failure(
                fs=fs,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                provider="openalex",
                task_key=task_key,
                stage_name=OPENALEX_STAGE,
                error_message=str(exc),
            )
            if bool((retry_state or {}).get("retry_queued")):
                if await _schedule_local_retry_if_needed(
                    queue_key="openalex",
                    task_key=task_key,
                    payload=payload,
                ):
                    return {"claimed": True, "task_key": task_key, "retry_scheduled": True, "error": str(exc)}
        raise


async def process_s2_bulk_page_task(payload: dict[str, Any]) -> dict[str, Any]:
    user_id = str(payload.get("user_id") or "").strip()
    projekt_id = str(payload.get("projekt_id") or "").strip()
    run_id = str(payload.get("run_id") or "").strip()
    task_key = str(payload.get("task_key") or "").strip()
    if not user_id or not projekt_id or not run_id or not task_key:
        raise ValueError("s2 task payload is missing identifiers")

    fs = QuellenFinderFirestoreService()
    claimed = await __import__("asyncio").to_thread(
        fs.claim_two_lane_provider_task,
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        provider="semanticscholar",
        task_key=task_key,
    )
    if not claimed:
        return {"claimed": False, "task_key": task_key}

    run_doc = await __import__("asyncio").to_thread(fs.get_run, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
    if _run_is_terminal(run_doc):
        await _skip_due_to_terminal_run(
            fs=fs,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            provider="semanticscholar",
            task_key=task_key,
            stage_name=SEMANTICSCHOLAR_STAGE,
            reason="terminal_before_fetch",
        )
        return {"claimed": True, "task_key": task_key, "skipped": True}
    artifact_store = _artifact_store_from_run_doc(run_doc)
    query = S2BulkQuery.model_validate(payload.get("query") or {})
    query_hash = str(payload.get("query_hash") or _query_hash("semanticscholar", query)).strip()
    page_index = int(payload.get("page_index") or 1)
    token = payload.get("token")
    token_s = str(token).strip() if token is not None else None
    bulk_limit = max(1, int(payload.get("bulk_limit") or 100))
    data_path, meta_path = _s2_page_paths(
        artifact_store=artifact_store,
        run_id=run_id,
        query_hash=query_hash,
        page_index=page_index,
        token=token_s,
    )

    try:
        meta: dict[str, Any]
        if artifact_store.exists(path_or_uri=meta_path):
            meta = artifact_store.download_json(path_or_uri=meta_path)
        else:
            cfg = PipelineConfig.from_env(runs_root=Path("."), pipeline_version="two_lane_v1")
            session = requests.Session()
            session.headers.update({"User-Agent": "instantpaper-two-lane/1.0"})
            if cfg.semanticscholar_api_key:
                session.headers.update({"x-api-key": cfg.semanticscholar_api_key})
            limiter = _build_s2_limiter(cfg=cfg, run_id=run_id, stage="phase_d_semanticscholar_retrieval")
            base = cfg.semanticscholar_base_url.rstrip("/")
            params: dict[str, Any] = {"query": query.query_string, "fields": S2_BULK_FIELDS, "limit": int(bulk_limit)}
            if token_s:
                params["token"] = token_s
            page = request_json(
                run_ctx=None,
                stage="phase_d_semanticscholar_retrieval",
                provider="semanticscholar",
                session=session,
                method="GET",
                url=base + "/paper/search/bulk",
                params=params,
                body=None,
                timeout_s=float(cfg.semanticscholar_timeout_s),
                rate_limiter=limiter,
                max_attempts=10,
                backoff_initial_s=2.0,
                backoff_max_s=120.0,
            )

            items = (page or {}).get("data") or []
            ids: list[str] = []
            ranks: dict[str, int] = {}
            for rank, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    continue
                paper_id = item.get("paperId")
                if not paper_id:
                    continue
                paper_id_s = str(paper_id)
                ids.append(paper_id_s)
                ranks[paper_id_s] = int(((page_index - 1) * int(bulk_limit)) + rank)

            hydrated: list[dict[str, Any]] = []
            if ids:
                for chunk in _chunked(ids, 500):
                    batch = request_json(
                        run_ctx=None,
                        stage="phase_d_semanticscholar_retrieval",
                        provider="semanticscholar",
                        session=session,
                        method="POST",
                        url=base + "/paper/batch",
                        params={"fields": S2_BATCH_FIELDS},
                        body={"ids": chunk},
                        timeout_s=float(cfg.semanticscholar_timeout_s),
                        rate_limiter=limiter,
                        max_attempts=10,
                        backoff_initial_s=2.0,
                        backoff_max_s=120.0,
                    )
                    hydrated.extend(_s2_iter_batch_items(batch))

            lines = []
            for paper in hydrated:
                paper_id = str(paper.get("paperId") or "").strip()
                if not paper_id:
                    continue
                lines.append(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "provider": "semanticscholar",
                            "query_hash": query_hash,
                            "query_i": int(payload.get("query_i") or 0),
                            "intent": query.intent,
                            "language": query.language,
                            "rank": int(ranks.get(paper_id) or 0),
                            "paper": paper,
                        },
                        ensure_ascii=False,
                    )
                )
            artifact_store.upload_text(
                text="\n".join(lines) + ("\n" if lines else ""),
                path_or_uri=data_path,
                content_type="application/x-ndjson; charset=utf-8",
            )
            meta = {
                "query_hash": query_hash,
                "page_index": int(page_index),
                "token": token_s,
                "next_token": (page or {}).get("token") or (page or {}).get("next"),
                "ids_seen": int(len(ids)),
                "records": int(len(lines)),
                "dataPath": data_path,
            }
            artifact_store.upload_json(payload=meta, path_or_uri=meta_path)

        run_doc_after_fetch = await __import__("asyncio").to_thread(fs.get_run, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        if _run_is_terminal(run_doc_after_fetch):
            await _skip_due_to_terminal_run(
                fs=fs,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                provider="semanticscholar",
                task_key=task_key,
                stage_name=SEMANTICSCHOLAR_STAGE,
                reason="terminal_after_fetch",
                summary=_provider_task_summary(
                    page_index=page_index,
                    records=int(meta.get("records") or 0),
                    extra={"ids_seen": int(meta.get("ids_seen") or 0)},
                ),
            )
            return {"claimed": True, "task_key": task_key, "records": int(meta.get("records") or 0), "skipped": True}

        next_token = str(meta.get("next_token") or "").strip() or None
        if next_token:
            next_page_index = int(page_index) + 1
            next_task_key = _s2_task_key(query_hash=query_hash, token=next_token, page_index=next_page_index)
            dispatcher = build_two_lane_task_dispatcher()
            queued = await __import__("asyncio").to_thread(
                fs.enqueue_two_lane_provider_task,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                provider="semanticscholar",
                stage_name=SEMANTICSCHOLAR_STAGE,
                queue_name=str(dispatcher.semanticscholar_queue),
                task_key=next_task_key,
                results_prefix=_provider_relative_prefix(artifact_store=artifact_store, run_id=run_id, provider="semanticscholar"),
            )
            if queued:
                dispatcher.enqueue(
                    queue_key="semanticscholar",
                    task_name=next_task_key,
                    payload={
                        "kind": "s2_bulk_page",
                        "user_id": user_id,
                        "projekt_id": projekt_id,
                        "run_id": run_id,
                        "provider": "semanticscholar",
                        "stage_name": SEMANTICSCHOLAR_STAGE,
                        "task_key": next_task_key,
                        "query_i": int(payload.get("query_i") or 0),
                        "query_hash": query_hash,
                        "page_index": next_page_index,
                        "token": next_token,
                        "query": query.model_dump(mode="json"),
                        "bulk_limit": int(bulk_limit),
                    },
                )

        result = await __import__("asyncio").to_thread(
            fs.complete_two_lane_provider_task,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            provider="semanticscholar",
            task_key=task_key,
            stage_name=SEMANTICSCHOLAR_STAGE,
            summary=_provider_task_summary(
                page_index=page_index,
                records=int(meta.get("records") or 0),
                extra={"ids_seen": int(meta.get("ids_seen") or 0)},
            ),
        )
        if bool((result or {}).get("provider_done")):
            await _maybe_launch_candidates(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        return {"claimed": True, "task_key": task_key, "records": int(meta.get("records") or 0)}
    except Exception as exc:
        latest_run_doc = await __import__("asyncio").to_thread(fs.get_run, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        if _run_is_terminal(latest_run_doc):
            await _skip_due_to_terminal_run(
                fs=fs,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                provider="semanticscholar",
                task_key=task_key,
                stage_name=SEMANTICSCHOLAR_STAGE,
                reason="terminal_on_error",
                error_message=str(exc),
            )
        else:
            retry_state = await _requeue_task_failure(
                fs=fs,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                provider="semanticscholar",
                task_key=task_key,
                stage_name=SEMANTICSCHOLAR_STAGE,
                error_message=str(exc),
            )
            if bool((retry_state or {}).get("retry_queued")):
                if await _schedule_local_retry_if_needed(
                    queue_key="semanticscholar",
                    task_key=task_key,
                    payload=payload,
                ):
                    return {"claimed": True, "task_key": task_key, "retry_scheduled": True, "error": str(exc)}
        raise
