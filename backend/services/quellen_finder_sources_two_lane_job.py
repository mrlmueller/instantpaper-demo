from __future__ import annotations

import asyncio
import logging
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from fastapi import HTTPException
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.cloud_run_job_launcher import cloud_run_job_launcher
from services.quellen_finder_firestore_service import QuellenFinderFirestoreService
from services.two_lane_sources.handoff import restore_handoff_bundle, upload_handoff_bundle
from services.two_lane_sources.runner import (
    TwoLaneRunCancelled,
    run_two_lane_sources_pipeline,
    run_two_lane_sources_pipeline_stage,
)
from services.two_lane_sources.storage import TwoLaneArtifactStore
from utils.config import config

logger = logging.getLogger(__name__)

_SPLIT_STAGES = ("preprocess", "fetch", "finalize")


def _as_str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    try:
        s = str(value).strip()
    except Exception:
        return None
    return s or None


def _as_int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _trim_text(value: Any, *, max_chars: int = 5000) -> str | None:
    s = _as_str_or_none(value)
    if not s:
        return None
    if len(s) <= int(max_chars):
        return s
    return s[: max(0, int(max_chars) - 1)].rstrip() + "…"


def _build_two_lane_results_docs(*, output: Dict[str, Any]) -> List[Tuple[str, dict]]:
    top = output.get("top") or {}

    docs: List[Tuple[str, dict]] = []
    for lane in ["match", "authority"]:
        for pool in ["with_abstract", "without_abstract"]:
            cards = list(((top.get(lane) or {}).get(pool) or []))
            for rank, card in enumerate(cards[:40], start=1):
                cid = _as_str_or_none(card.get("id")) or ""

                rerank = card.get("rerank")
                if not isinstance(rerank, dict):
                    rerank = None
                else:
                    rerank = {
                        "llm_score_0_100": _as_int_or_none(rerank.get("llm_score_0_100")),
                        "covered_facets": list(rerank.get("covered_facets") or []),
                        "rationale": _trim_text(rerank.get("rationale"), max_chars=5000),
                        "insufficient_info": bool(rerank.get("insufficient_info")) if rerank.get("insufficient_info") is not None else None,
                    }

                coverage_tags_in = card.get("coverage_tags")
                coverage_tags = None
                if isinstance(coverage_tags_in, list):
                    ct = []
                    for t in coverage_tags_in:
                        if not isinstance(t, dict):
                            continue
                        fid = _as_str_or_none(t.get("facet_id"))
                        if not fid:
                            continue
                        ct.append(
                            {
                                "facet_id": fid,
                                "score": float(t.get("score") or 0.0),
                                "excerpt": _trim_text(t.get("excerpt"), max_chars=240) or "",
                            }
                        )
                    coverage_tags = ct

                authors_in = card.get("authors")
                authors: List[str] = []
                if isinstance(authors_in, list):
                    for a in authors_in:
                        s = _as_str_or_none(a)
                        if s:
                            authors.append(s)

                scores = card.get("scores") if isinstance(card.get("scores"), dict) else {}

                payload = {
                    "lane": lane,
                    "pool": pool,
                    "rank": int(rank),
                    "id": cid,
                    "doi": _as_str_or_none(card.get("doi")),
                    "title": _as_str_or_none(card.get("title")),
                    "authors": authors,
                    "year": _as_int_or_none(card.get("year")),
                    "venue": _as_str_or_none(card.get("venue")),
                    "url": _as_str_or_none(card.get("url")),
                    "language": _as_str_or_none(card.get("language")),
                    "abstract": _trim_text(card.get("abstract"), max_chars=5000),
                    "citations": _as_int_or_none(card.get("citations")),
                    "influential_citations": _as_int_or_none(card.get("influential_citations")),
                    "provider": _as_str_or_none(card.get("provider")),
                    "provider_ids": (card.get("provider_ids") if isinstance(card.get("provider_ids"), dict) else None),
                    "external_ids": (card.get("external_ids") if isinstance(card.get("external_ids"), dict) else None),
                    "sources": (card.get("sources") if isinstance(card.get("sources"), list) else None),
                    "scores": scores,
                    "coverage_tags": coverage_tags,
                    "rerank": rerank,
                    "createdAt": SERVER_TIMESTAMP,
                }

                doc_id = f"{lane}_{pool}_{rank:03d}"
                docs.append((doc_id, payload))

    return docs


def _build_two_lane_telemetry_docs(*, telemetry: Dict[str, Any]) -> List[Tuple[str, dict]]:
    docs: List[Tuple[str, dict]] = []
    for doc_id, payload in (telemetry or {}).items():
        if not isinstance(doc_id, str) or not doc_id.strip():
            continue
        if not isinstance(payload, dict):
            payload = {"value": payload}
        docs.append(
            (
                doc_id.strip(),
                {
                    **payload,
                    "createdAt": SERVER_TIMESTAMP,
                },
            )
        )
    return docs


def _build_runtime_settings_from_run_doc(data: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    chapter_input = data.get("chapterInputSnapshot")
    if not isinstance(chapter_input, dict):
        chapter_input = {}

    kapitel_snapshots = data.get("kapitelSnapshots")
    kapitel_snapshot = (
        kapitel_snapshots[0]
        if isinstance(kapitel_snapshots, list) and kapitel_snapshots and isinstance(kapitel_snapshots[0], dict)
        else {}
    )

    chapter_title = str(
        (chapter_input or {}).get("chapterTitle")
        or (kapitel_snapshot or {}).get("title")
        or (kapitel_snapshot or {}).get("ueberschrift")
        or ""
    ).strip()
    chapter_spec_text = str(
        (chapter_input or {}).get("chapterSpecText")
        or (kapitel_snapshot or {}).get("thema")
        or ""
    ).strip()

    if not chapter_title:
        raise RuntimeError("Run is missing chapter title snapshot.")
    if not chapter_spec_text:
        raise RuntimeError("Run is missing chapter spec snapshot.")

    pipeline_settings = data.get("twoLaneSettingsRequested")
    if not isinstance(pipeline_settings, dict):
        pipeline_settings = {}

    kapitel_ids = data.get("kapitelIds")
    kapitel_id = (
        str(kapitel_ids[0]).strip()
        if isinstance(kapitel_ids, list) and kapitel_ids and str(kapitel_ids[0]).strip()
        else ""
    )
    if not kapitel_id:
        raise RuntimeError("Run is missing kapitelIds[0].")

    return kapitel_id, {
        "chapter_title": chapter_title,
        "chapter_spec_text": chapter_spec_text,
        "pipeline_settings": pipeline_settings,
    }


def _two_lane_job_provider(split: bool) -> str:
    if split:
        return "cloud_run_split_jobs" if config.IS_CLOUD_RUN else "local_split_jobs"
    return "cloud_run_jobs" if config.IS_CLOUD_RUN else "local_background_task"


def _default_two_lane_job_name() -> str | None:
    if not config.IS_CLOUD_RUN:
        return "local:run_two_lane_job.py"
    return str(config.TWO_LANE_CLOUD_RUN_JOB_NAME or "").strip() or None


def _default_two_lane_job_region() -> str | None:
    if not config.IS_CLOUD_RUN:
        return "local"
    return str(config.TWO_LANE_CLOUD_RUN_JOB_REGION or "").strip() or None


def _artifact_store_from_config(run_doc: Dict[str, Any] | None = None) -> TwoLaneArtifactStore:
    artifacts = (run_doc or {}).get("twoLaneArtifacts") if isinstance((run_doc or {}).get("twoLaneArtifacts"), dict) else {}
    bucket_name = str((artifacts or {}).get("bucket") or config.TWO_LANE_ARTIFACT_BUCKET or "").strip() or str(config.FIREBASE_STORAGE_BUCKET or "").strip()
    if not bucket_name:
        raise RuntimeError("TWO_LANE_ARTIFACT_BUCKET or FIREBASE_STORAGE_BUCKET must be configured.")
    return TwoLaneArtifactStore(
        bucket_name=bucket_name,
        base_prefix=str((artifacts or {}).get("basePrefix") or config.TWO_LANE_ARTIFACT_PREFIX or "").strip(),
        project_id=str(config.GOOGLE_CLOUD_PROJECT or config.FIREBASE_PROJECT_ID or "").strip(),
    )


def _split_stage_state(data: Dict[str, Any], stage_name: str) -> Dict[str, Any]:
    split_execution = data.get("splitExecution") if isinstance(data.get("splitExecution"), dict) else {}
    stage_state = split_execution.get(str(stage_name)) if isinstance(split_execution.get(str(stage_name)), dict) else {}
    return dict(stage_state)


def _next_split_stage(stage_name: str) -> str | None:
    stage_norm = str(stage_name or "").strip().lower()
    try:
        idx = _SPLIT_STAGES.index(stage_norm)
    except ValueError:
        return None
    next_idx = idx + 1
    if next_idx >= len(_SPLIT_STAGES):
        return None
    return _SPLIT_STAGES[next_idx]


def _stage_progress_label(stage_name: str) -> str:
    labels = {
        "preprocess": "Preparing query plan and provider queries",
        "fetch": "Fetching provider records and normalizing candidates",
        "finalize": "Finalizing ranking and output",
    }
    return str(labels.get(str(stage_name or "").strip().lower()) or stage_name or "Running split stage")


def _mark_split_stage(
    fs: QuellenFinderFirestoreService,
    *,
    user_id: str,
    projekt_id: str,
    run_id: str,
    stage_name: str,
    status: str,
    extra: Dict[str, Any] | None = None,
) -> None:
    stage_norm = str(stage_name or "").strip().lower()
    payload: Dict[str, Any] = {
        "updatedAt": SERVER_TIMESTAMP,
        "splitExecution": {
            "backend": _two_lane_job_provider(split=True),
            "version": 1,
            "currentStage": stage_norm,
            stage_norm: {
                "status": str(status or "").strip().lower(),
                "updatedAt": SERVER_TIMESTAMP,
            },
        },
    }
    stage_payload = payload["splitExecution"][stage_norm]
    if status == "running":
        stage_payload["startedAt"] = SERVER_TIMESTAMP
    if status in {"success", "error", "cancelled"}:
        stage_payload["finishedAt"] = SERVER_TIMESTAMP
    if isinstance(extra, dict) and extra:
        stage_payload.update(extra)
    fs.run_ref(user_id, projekt_id, run_id).set(payload, merge=True)


def _record_split_artifact_manifest(
    fs: QuellenFinderFirestoreService,
    *,
    user_id: str,
    projekt_id: str,
    run_id: str,
    stage_name: str,
    artifact_store: TwoLaneArtifactStore,
    manifest: Dict[str, Any],
) -> None:
    prefix = artifact_store.run_prefix(run_id)
    fs.run_ref(user_id, projekt_id, run_id).set(
        {
            "updatedAt": SERVER_TIMESTAMP,
            "twoLaneArtifacts": {
                "bucket": artifact_store.bucket_name,
                "basePrefix": artifact_store.base_prefix,
                "prefixUri": f"gs://{artifact_store.bucket_name}/{prefix}",
                "cleanupStatus": "pending",
                "latestStage": str(stage_name or "").strip().lower(),
                "latestManifestUri": str((manifest or {}).get("manifest_uri") or "").strip() or None,
                str(stage_name or "").strip().lower(): {
                    "manifestUri": str((manifest or {}).get("manifest_uri") or "").strip() or None,
                    "bundleUri": str((manifest or {}).get("bundle_uri") or "").strip() or None,
                    "bundleSha256": str((manifest or {}).get("bundle_sha256") or "").strip() or None,
                    "bundleSizeBytes": int((manifest or {}).get("bundle_size_bytes") or 0),
                    "fileCount": int((manifest or {}).get("file_count") or 0),
                    "updatedAt": SERVER_TIMESTAMP,
                },
            },
        },
        merge=True,
    )


def _cleanup_split_artifacts(
    fs: QuellenFinderFirestoreService,
    *,
    user_id: str,
    projekt_id: str,
    run_id: str,
) -> None:
    try:
        run_doc = fs.get_run(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        artifact_store = _artifact_store_from_config(run_doc)
        deleted = int(artifact_store.delete_run_prefix(run_id))
        fs.run_ref(user_id, projekt_id, run_id).set(
            {
                "updatedAt": SERVER_TIMESTAMP,
                "twoLaneArtifacts": {
                    "cleanupStatus": "done",
                    "cleanupDeletedObjects": int(deleted),
                    "cleanupFinishedAt": SERVER_TIMESTAMP,
                },
            },
            merge=True,
        )
    except Exception as exc:
        fs.run_ref(user_id, projekt_id, run_id).set(
            {
                "updatedAt": SERVER_TIMESTAMP,
                "twoLaneArtifacts": {
                    "cleanupStatus": "error",
                    "cleanupError": str(exc or "")[:1000] or "artifact cleanup failed",
                    "cleanupFinishedAt": SERVER_TIMESTAMP,
                },
            },
            merge=True,
        )
        logger.warning("QF split artifact cleanup failed | run_id=%s error=%s", run_id, exc)


async def _launch_split_stage(
    *,
    user_id: str,
    projekt_id: str,
    run_id: str,
    stage_name: str,
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        cloud_run_job_launcher.execute_two_lane_sources_job,
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        stage=stage_name,
    )


def _build_stage_settings(settings: Dict[str, Any], *, stage_name: str) -> Dict[str, Any]:
    out = dict(settings or {})
    pipeline_settings = out.get("pipeline_settings") if isinstance(out.get("pipeline_settings"), dict) else {}
    pipeline_settings = dict(pipeline_settings)
    if str(stage_name or "").strip().lower() in {"fetch", "finalize"}:
        pipeline_settings["force_rebuild"] = False
    out["pipeline_settings"] = pipeline_settings
    return out


def _load_split_manifest(data: Dict[str, Any], *, stage_name: str) -> Dict[str, Any]:
    artifacts = data.get("twoLaneArtifacts") if isinstance(data.get("twoLaneArtifacts"), dict) else {}
    stage_artifacts = artifacts.get(str(stage_name)) if isinstance(artifacts.get(str(stage_name)), dict) else {}
    manifest_uri = str((stage_artifacts or {}).get("manifestUri") or "").strip()
    if not manifest_uri:
        raise RuntimeError(f"Run is missing twoLaneArtifacts.{stage_name}.manifestUri.")
    artifact_store = _artifact_store_from_config(data)
    manifest = artifact_store.download_json(path_or_uri=manifest_uri)
    if not isinstance(manifest, dict):
        raise RuntimeError(f"Invalid two-lane handoff manifest for stage {stage_name}.")
    return manifest


def _persist_two_lane_pipeline_success(
    *,
    fs: QuellenFinderFirestoreService,
    user_id: str,
    projekt_id: str,
    run_id: str,
    result: Dict[str, Any],
    elapsed_seconds: float,
) -> None:
    output = result.get("output") if isinstance(result, dict) else None
    telemetry = (result.get("telemetry") if isinstance(result, dict) else None) or {}
    costs = (result.get("costs") if isinstance(result, dict) else None) or {}
    effective_settings = (result.get("effective_settings") if isinstance(result, dict) else None) or {}

    if not isinstance(output, dict):
        raise RuntimeError("Pipeline produced no output.")

    docs_results = _build_two_lane_results_docs(output=output)
    docs_telemetry = _build_two_lane_telemetry_docs(telemetry=telemetry)

    fs.write_two_lane_results(user_id=user_id, projekt_id=projekt_id, run_id=run_id, docs=docs_results)

    telemetry_ok = True
    telemetry_error: str | None = None
    try:
        fs.write_two_lane_telemetry(user_id=user_id, projekt_id=projekt_id, run_id=run_id, docs=docs_telemetry)
    except Exception as exc:
        telemetry_ok = False
        telemetry_error = str(exc)[:800] if exc is not None else "unknown"
        logger.warning("QF two-lane telemetry write failed (ignored) | run_id=%s error=%s", run_id, telemetry_error)

    fs.mark_success(
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        had_partial_failures=not telemetry_ok,
        extra={
            "resultCount": int(len(docs_results)),
            "twoLaneSettings": effective_settings,
            "summary": {
                "total_cost_usd": float(costs.get("total_cost_usd") or 0.0),
                "budget_cap_usd": float(costs.get("budget_cap_usd") or 2.0),
                "seconds_total": float(elapsed_seconds),
                "telemetry_docs": int(len(docs_telemetry)),
                "telemetry_write_ok": bool(telemetry_ok),
                "telemetry_write_error": telemetry_error,
            },
        },
    )


async def run_quellen_finder_sources_two_lane_job_from_run_doc(
    *,
    user_id: str,
    projekt_id: str,
    run_id: str,
    stage: str | None = None,
) -> None:
    fs = QuellenFinderFirestoreService()
    stage_norm = str(stage or "").strip().lower() or None

    def _load() -> tuple[dict[str, Any], str | None]:
        data = fs.get_run(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        status_now = str((data or {}).get("status") or "").strip()
        if status_now in {"success", "error", "cancelled"}:
            return data, "terminal"
        if bool((data or {}).get("cancelRequestedAt")):
            fs.mark_cancelled(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
            return data, "cancelled_before_start"

        if stage_norm in _SPLIT_STAGES:
            stage_state = _split_stage_state(data, stage_norm)
            stage_status = str((stage_state or {}).get("status") or "").strip().lower()
            if stage_status in {"running", "success"}:
                return data, f"stage_{stage_status}"
            return data, None

        if status_now == "running":
            return data, "already_running"
        return data, None

    data, skip_reason = await asyncio.to_thread(_load)
    if skip_reason:
        logger.info(
            "QF two-lane worker no-op | run_id=%s projekt_id=%s reason=%s",
            run_id,
            projekt_id,
            skip_reason,
        )
        return

    if str((data or {}).get("kind") or "") != "sources_two_lane":
        raise RuntimeError("Run is not a two-lane sources run.")

    kapitel_id, settings = _build_runtime_settings_from_run_doc(data)
    execution_backend = str((data or {}).get("executionBackend") or config.TWO_LANE_SOURCES_EXECUTION_BACKEND or "").strip().lower()
    if stage_norm in _SPLIT_STAGES or execution_backend in {"cloud_run_split_jobs", "local_split_jobs"}:
        if stage_norm not in _SPLIT_STAGES:
            stage_norm = str(((data.get("splitExecution") if isinstance(data.get("splitExecution"), dict) else {}).get("currentStage") or "preprocess")).strip().lower()
        await run_quellen_finder_sources_two_lane_split_stage_job(
            user_id=user_id,
            projekt_id=projekt_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            stage_name=stage_norm,
            settings=settings,
        )
        return

    await run_quellen_finder_sources_two_lane_job(
        user_id=user_id,
        projekt_id=projekt_id,
        kapitel_id=kapitel_id,
        run_id=run_id,
        settings=settings,
    )


async def run_quellen_finder_sources_two_lane_job(
    *,
    user_id: str,
    projekt_id: str,
    kapitel_id: str,
    run_id: str,
    settings: Dict[str, Any],
) -> None:
    fs = QuellenFinderFirestoreService()

    t0 = time.perf_counter()
    logger.info(
        "QF two-lane job start | run_id=%s projekt_id=%s kapitel_id=%s settings_keys=%s",
        run_id,
        projekt_id,
        kapitel_id,
        sorted(list((settings or {}).keys())),
    )

    def _cancel_requested_sync() -> bool:
        snap = fs.run_ref(user_id, projekt_id, run_id).get()
        data = snap.to_dict() if snap is not None else {}
        return bool((data or {}).get("cancelRequestedAt"))

    async def check_cancel() -> None:
        if await asyncio.to_thread(_cancel_requested_sync):
            raise TwoLaneRunCancelled("Cancellation requested.")

    last_stage: str | None = None

    async def on_progress(stage: str, message: str) -> None:
        nonlocal last_stage
        stage_s = str(stage)
        stage_started_at = stage_s != (last_stage or "")
        if stage_started_at:
            last_stage = stage_s
        await asyncio.to_thread(
            fs.set_progress,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            stage=stage_s,
            message=str(message),
            stage_started_at=bool(stage_started_at),
        )

    async def on_telemetry(docs: Dict[str, Dict[str, Any]]) -> None:
        if not isinstance(docs, dict) or not docs:
            return
        try:
            docs_telemetry = _build_two_lane_telemetry_docs(telemetry=docs)
            await asyncio.to_thread(fs.write_two_lane_telemetry, user_id=user_id, projekt_id=projekt_id, run_id=run_id, docs=docs_telemetry)
        except Exception:
            return

    try:
        await check_cancel()
        fs.mark_running(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        await on_progress("starting", "Starting two-lane pipeline")
        await asyncio.to_thread(fs.clear_subcollection, user_id=user_id, projekt_id=projekt_id, run_id=run_id, name="twoLaneResults")
        await asyncio.to_thread(fs.clear_subcollection, user_id=user_id, projekt_id=projekt_id, run_id=run_id, name="twoLaneTelemetry")

        result = await run_two_lane_sources_pipeline(
            user_id=user_id,
            projekt_id=projekt_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            chapter_title=str((settings or {}).get("chapter_title") or "").strip(),
            chapter_spec_text=str((settings or {}).get("chapter_spec_text") or "").strip(),
            settings=(settings or {}).get("pipeline_settings") if isinstance((settings or {}).get("pipeline_settings"), dict) else {},
            check_cancel=check_cancel,
            on_progress=on_progress,
            on_telemetry=on_telemetry,
        )

        await on_progress("write_results", "Saving results")

        output = result.get("output") if isinstance(result, dict) else None
        costs = (result.get("costs") if isinstance(result, dict) else None) or {}

        if not isinstance(output, dict):
            raise RuntimeError("Pipeline produced no output.")
        dt = time.perf_counter() - t0
        _persist_two_lane_pipeline_success(
            fs=fs,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            result=result,
            elapsed_seconds=dt,
        )
        logger.info(
            "QF two-lane job success | run_id=%s seconds=%.2f cost_usd=%.4f",
            run_id,
            dt,
            float(costs.get("total_cost_usd") or 0.0),
        )
    except TwoLaneRunCancelled:
        logger.info("QF two-lane job cancelled | run_id=%s", run_id)
        fs.mark_cancelled(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
    except HTTPException as exc:
        logger.error(
            "QF two-lane job HTTPException | run_id=%s status=%s detail=%s",
            run_id,
            getattr(exc, "status_code", None),
            getattr(exc, "detail", None),
            exc_info=True,
        )
        detail = getattr(exc, "detail", None)
        msg = str(detail or exc)[:1000]
        fs.mark_error(user_id=user_id, projekt_id=projekt_id, run_id=run_id, error_message=msg, had_partial_failures=False)
    except Exception as exc:
        logger.error("QF two-lane job failed | run_id=%s error=%s", run_id, exc, exc_info=True)
        logger.debug("Traceback:\n%s", traceback.format_exc())
        fs.mark_error(user_id=user_id, projekt_id=projekt_id, run_id=run_id, error_message=str(exc), had_partial_failures=False)


async def run_quellen_finder_sources_two_lane_split_stage_job(
    *,
    user_id: str,
    projekt_id: str,
    kapitel_id: str,
    run_id: str,
    stage_name: str,
    settings: Dict[str, Any],
) -> None:
    fs = QuellenFinderFirestoreService()
    stage_norm = str(stage_name or "").strip().lower()
    if stage_norm not in _SPLIT_STAGES:
        raise RuntimeError(f"Unsupported split stage: {stage_name}")

    t0 = time.perf_counter()
    logger.info(
        "QF two-lane split stage start | run_id=%s projekt_id=%s kapitel_id=%s stage=%s",
        run_id,
        projekt_id,
        kapitel_id,
        stage_norm,
    )

    def _cancel_requested_sync() -> bool:
        snap = fs.run_ref(user_id, projekt_id, run_id).get()
        data = snap.to_dict() if snap is not None else {}
        return bool((data or {}).get("cancelRequestedAt"))

    async def check_cancel() -> None:
        if await asyncio.to_thread(_cancel_requested_sync):
            raise TwoLaneRunCancelled("Cancellation requested.")

    last_stage: str | None = None

    async def on_progress(stage: str, message: str) -> None:
        nonlocal last_stage
        stage_s = str(stage)
        stage_started_at = stage_s != (last_stage or "")
        if stage_started_at:
            last_stage = stage_s
        await asyncio.to_thread(
            fs.set_progress,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            stage=stage_s,
            message=str(message),
            stage_started_at=bool(stage_started_at),
        )

    try:
        await check_cancel()
        if stage_norm == "preprocess":
            fs.mark_running(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        else:
            fs.run_ref(user_id, projekt_id, run_id).set(
                {
                    "status": "running",
                    "errorMessage": None,
                    "hadPartialFailures": False,
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )
        await asyncio.to_thread(
            _mark_split_stage,
            fs,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            stage_name=stage_norm,
            status="running",
            extra={"jobName": _default_two_lane_job_name(), "region": _default_two_lane_job_region()},
        )
        await on_progress(f"split_{stage_norm}", _stage_progress_label(stage_norm))

        if stage_norm == "preprocess":
            await asyncio.to_thread(fs.clear_subcollection, user_id=user_id, projekt_id=projekt_id, run_id=run_id, name="twoLaneResults")
            await asyncio.to_thread(fs.clear_subcollection, user_id=user_id, projekt_id=projekt_id, run_id=run_id, name="twoLaneTelemetry")
            with tempfile.TemporaryDirectory(prefix="qf_two_lane_preprocess_") as tmpdir:
                work_root = Path(tmpdir)
                stage_run_dir = work_root / "pipeline_runs" / str(run_id)
                result = await run_two_lane_sources_pipeline_stage(
                    stage_name="preprocess",
                    user_id=user_id,
                    projekt_id=projekt_id,
                    kapitel_id=kapitel_id,
                    run_id=run_id,
                    chapter_title=str((settings or {}).get("chapter_title") or "").strip(),
                    chapter_spec_text=str((settings or {}).get("chapter_spec_text") or "").strip(),
                    settings=_build_stage_settings(settings, stage_name="preprocess").get("pipeline_settings"),
                    run_dir=stage_run_dir,
                    check_cancel=check_cancel,
                    on_progress=on_progress,
                )
                artifact_store = _artifact_store_from_config()
                manifest = await asyncio.to_thread(
                    upload_handoff_bundle,
                    run_dir=Path(result.get("artifacts_dir") or stage_run_dir),
                    artifact_store=artifact_store,
                    run_id=run_id,
                    pipeline_version="two_lane_v1",
                    stage_name="preprocess",
                )
                await asyncio.to_thread(
                    _record_split_artifact_manifest,
                    fs,
                    user_id=user_id,
                    projekt_id=projekt_id,
                    run_id=run_id,
                    stage_name="preprocess",
                    artifact_store=artifact_store,
                    manifest=manifest,
                )

            launch = await _launch_split_stage(user_id=user_id, projekt_id=projekt_id, run_id=run_id, stage_name="fetch")
            fs.run_ref(user_id, projekt_id, run_id).set(
                {
                    "updatedAt": SERVER_TIMESTAMP,
                    "splitExecution": {
                        "currentStage": "fetch",
                        "preprocess": {"status": "success", "finishedAt": SERVER_TIMESTAMP},
                        "fetch": {
                            "status": "queued",
                            "queuedAt": SERVER_TIMESTAMP,
                            "jobName": str((launch or {}).get("job_name") or _default_two_lane_job_name() or "").strip() or None,
                            "region": str((launch or {}).get("region") or _default_two_lane_job_region() or "").strip() or None,
                            "executionName": (launch or {}).get("execution_name"),
                            "operationName": (launch or {}).get("operation_name"),
                        },
                    },
                },
                merge=True,
            )
            logger.info("QF two-lane split preprocess success | run_id=%s seconds=%.2f", run_id, time.perf_counter() - t0)
            return

        if stage_norm == "fetch":
            data = await asyncio.to_thread(fs.get_run, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
            manifest = await asyncio.to_thread(_load_split_manifest, data, stage_name="preprocess")
            artifact_store = _artifact_store_from_config(data)
            with tempfile.TemporaryDirectory(prefix="qf_two_lane_fetch_") as tmpdir:
                work_root = Path(tmpdir)
                stage_run_dir = await asyncio.to_thread(
                    restore_handoff_bundle,
                    artifact_store=artifact_store,
                    manifest=manifest,
                    work_root=work_root,
                )
                result = await run_two_lane_sources_pipeline_stage(
                    stage_name="fetch",
                    user_id=user_id,
                    projekt_id=projekt_id,
                    kapitel_id=kapitel_id,
                    run_id=run_id,
                    chapter_title=str((settings or {}).get("chapter_title") or "").strip(),
                    chapter_spec_text=str((settings or {}).get("chapter_spec_text") or "").strip(),
                    settings=_build_stage_settings(settings, stage_name="fetch").get("pipeline_settings"),
                    run_dir=stage_run_dir,
                    check_cancel=check_cancel,
                    on_progress=on_progress,
                )
                manifest_out = await asyncio.to_thread(
                    upload_handoff_bundle,
                    run_dir=Path(result.get("artifacts_dir") or stage_run_dir),
                    artifact_store=artifact_store,
                    run_id=run_id,
                    pipeline_version="two_lane_v1",
                    stage_name="fetch",
                )
                await asyncio.to_thread(
                    _record_split_artifact_manifest,
                    fs,
                    user_id=user_id,
                    projekt_id=projekt_id,
                    run_id=run_id,
                    stage_name="fetch",
                    artifact_store=artifact_store,
                    manifest=manifest_out,
                )

            launch = await _launch_split_stage(user_id=user_id, projekt_id=projekt_id, run_id=run_id, stage_name="finalize")
            fs.run_ref(user_id, projekt_id, run_id).set(
                {
                    "updatedAt": SERVER_TIMESTAMP,
                    "splitExecution": {
                        "currentStage": "finalize",
                        "fetch": {"status": "success", "finishedAt": SERVER_TIMESTAMP},
                        "finalize": {
                            "status": "queued",
                            "queuedAt": SERVER_TIMESTAMP,
                            "jobName": str((launch or {}).get("job_name") or _default_two_lane_job_name() or "").strip() or None,
                            "region": str((launch or {}).get("region") or _default_two_lane_job_region() or "").strip() or None,
                            "executionName": (launch or {}).get("execution_name"),
                            "operationName": (launch or {}).get("operation_name"),
                        },
                    },
                },
                merge=True,
            )
            logger.info("QF two-lane split fetch success | run_id=%s seconds=%.2f", run_id, time.perf_counter() - t0)
            return

        data = await asyncio.to_thread(fs.get_run, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        manifest = await asyncio.to_thread(_load_split_manifest, data, stage_name="fetch")
        artifact_store = _artifact_store_from_config(data)
        with tempfile.TemporaryDirectory(prefix="qf_two_lane_finalize_") as tmpdir:
            work_root = Path(tmpdir)
            stage_run_dir = await asyncio.to_thread(
                restore_handoff_bundle,
                artifact_store=artifact_store,
                manifest=manifest,
                work_root=work_root,
            )
            result = await run_two_lane_sources_pipeline_stage(
                stage_name="finalize",
                user_id=user_id,
                projekt_id=projekt_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                chapter_title=str((settings or {}).get("chapter_title") or "").strip(),
                chapter_spec_text=str((settings or {}).get("chapter_spec_text") or "").strip(),
                settings=_build_stage_settings(settings, stage_name="finalize").get("pipeline_settings"),
                run_dir=stage_run_dir,
                check_cancel=check_cancel,
                on_progress=on_progress,
            )
            await on_progress("write_results", "Saving results")
            await asyncio.to_thread(
                _persist_two_lane_pipeline_success,
                fs=fs,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                result=result,
                elapsed_seconds=(time.perf_counter() - t0),
            )

        fs.run_ref(user_id, projekt_id, run_id).set(
            {
                "updatedAt": SERVER_TIMESTAMP,
                "splitExecution": {
                    "currentStage": "done",
                    "finalize": {"status": "success", "finishedAt": SERVER_TIMESTAMP},
                },
            },
            merge=True,
        )
        await asyncio.to_thread(_cleanup_split_artifacts, fs, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        logger.info("QF two-lane split finalize success | run_id=%s seconds=%.2f", run_id, time.perf_counter() - t0)
    except TwoLaneRunCancelled:
        logger.info("QF two-lane split stage cancelled | run_id=%s stage=%s", run_id, stage_norm)
        await asyncio.to_thread(_mark_split_stage, fs, user_id=user_id, projekt_id=projekt_id, run_id=run_id, stage_name=stage_norm, status="cancelled")
        fs.mark_cancelled(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        await asyncio.to_thread(_cleanup_split_artifacts, fs, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
    except HTTPException as exc:
        logger.error(
            "QF two-lane split stage HTTPException | run_id=%s stage=%s status=%s detail=%s",
            run_id,
            stage_norm,
            getattr(exc, "status_code", None),
            getattr(exc, "detail", None),
            exc_info=True,
        )
        detail = getattr(exc, "detail", None)
        msg = str(detail or exc)[:1000]
        await asyncio.to_thread(
            _mark_split_stage,
            fs,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            stage_name=stage_norm,
            status="error",
            extra={"errorMessage": msg},
        )
        fs.mark_error(user_id=user_id, projekt_id=projekt_id, run_id=run_id, error_message=msg, had_partial_failures=False)
        await asyncio.to_thread(_cleanup_split_artifacts, fs, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
    except Exception as exc:
        logger.error("QF two-lane split stage failed | run_id=%s stage=%s error=%s", run_id, stage_norm, exc, exc_info=True)
        logger.debug("Traceback:\n%s", traceback.format_exc())
        await asyncio.to_thread(
            _mark_split_stage,
            fs,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            stage_name=stage_norm,
            status="error",
            extra={"errorMessage": str(exc)[:1000]},
        )
        fs.mark_error(user_id=user_id, projekt_id=projekt_id, run_id=run_id, error_message=str(exc), had_partial_failures=False)
        await asyncio.to_thread(_cleanup_split_artifacts, fs, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
