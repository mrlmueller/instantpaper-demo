from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.cost_service import TokenUsage, get_cost_service
from services.credits_service import get_credits_service
from services.firebase_service import firebase_service
from services.openai_budget_service import get_openai_budget_service
from services.pdf_scan.common import (
    FASTAPI_ROOT,
    PdfScanRunCancelled,
    PdfScanRunTerminated,
    RunProgressTracker,
    load_required_run_doc,
    read_pdf_scan_api_usage,
    resolve_pipeline_run_dir,
    run_pipeline_subprocess,
)
from services.pdf_scan.handoff import restore_handoff_bundle, upload_final_outputs
from services.pdf_scan.persistence_v2 import build_persisted_pdf_scan_v2_view
from services.pdf_scan.storage import PdfScanArtifactStore
from services.quellen_finder_firestore_service import QuellenFinderFirestoreService
from utils.config import config

logger = logging.getLogger(__name__)


def _merge_persisted_root_update(extra: dict[str, Any], persisted: dict[str, Any]) -> dict[str, Any]:
    merged = dict(extra or {})
    root_update = dict((persisted or {}).get("root_update") or {})
    for key in ["pdfScanSchemaVersion", "pdfScanMode", "chapterInputMode", "pdfScanSummary", "pdfScanCounts", "pdfScanDisplay"]:
        if key in root_update:
            merged[key] = root_update.get(key)
    return merged


def _artifact_store_from_run_doc(run_doc: dict[str, Any]) -> PdfScanArtifactStore:
    artifacts = run_doc.get("pdfScanArtifacts") if isinstance(run_doc.get("pdfScanArtifacts"), dict) else {}
    bucket_name = str((artifacts or {}).get("bucket") or config.PDF_SCAN_ARTIFACT_BUCKET or config.FIREBASE_STORAGE_BUCKET or "").strip()
    if not bucket_name:
        raise RuntimeError("PDF scan artifact bucket is not configured.")
    return PdfScanArtifactStore(
        bucket_name=bucket_name,
        base_prefix=str((artifacts or {}).get("basePrefix") or config.PDF_SCAN_ARTIFACT_PREFIX or "").strip(),
        project_id=str(config.GOOGLE_CLOUD_PROJECT or config.FIREBASE_PROJECT_ID or "").strip(),
    )


def _reservation_operation_id_from_data(data: dict[str, Any], run_id: str) -> str:
    billing_state = data.get("billing") if isinstance(data.get("billing"), dict) else {}
    return str((billing_state or {}).get("reservationOperationId") or "").strip() or f"{run_id}_pdf_scan_run"


async def _finalize_failure(
    *,
    fs: QuellenFinderFirestoreService,
    budget_service: Any,
    user_id: str,
    projekt_id: str,
    run_id: str,
    reservation_operation_id: str,
    message: str,
    cancelled: bool,
    progress: RunProgressTracker | None = None,
) -> None:
    terminal_pipeline_stages = None
    if progress is not None:
        terminal_pipeline_stages = progress.mark_current_stage_terminal("cancelled" if cancelled else "error")
    if cancelled:
        payload = {
            "billing": {
                "status": "cancelled",
                "reservationOperationId": reservation_operation_id,
            },
            "splitExecution": {
                "gpu": {
                    "status": "cancelled",
                    "errorMessage": str(message or "")[:1000] or None,
                    "finishedAt": SERVER_TIMESTAMP,
                }
            },
        }
        if terminal_pipeline_stages is not None:
            payload["pipelineStages"] = terminal_pipeline_stages
        await budget_service.mark_status(
            user_id=user_id,
            operation_id=reservation_operation_id,
            status="cancelled",
            error_message=message,
        )
        await budget_service.release_reservation(
            user_id=user_id,
            operation_id=reservation_operation_id,
            reason="cancelled",
        )
        fs.mark_cancelled(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        fs.run_ref(user_id, projekt_id, run_id).set(payload, merge=True)
        return

    payload = {
        "billing": {
            "status": "error",
            "reservationOperationId": reservation_operation_id,
        },
        "splitExecution": {
            "gpu": {
                "status": "error",
                "errorMessage": str(message or "")[:1000] or None,
                "finishedAt": SERVER_TIMESTAMP,
            }
        },
    }
    if terminal_pipeline_stages is not None:
        payload["pipelineStages"] = terminal_pipeline_stages
    await budget_service.mark_status(
        user_id=user_id,
        operation_id=reservation_operation_id,
        status="error",
        error_message=message,
    )
    await budget_service.release_reservation(
        user_id=user_id,
        operation_id=reservation_operation_id,
        reason="error",
    )
    fs.mark_error(
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        error_message=message,
        had_partial_failures=False,
    )
    fs.run_ref(user_id, projekt_id, run_id).set(payload, merge=True)


async def run_pdf_scan_gpu_job(
    *,
    user_id: str,
    projekt_id: str,
    run_id: str,
    run_doc: dict[str, Any],
    external_termination_event: asyncio.Event | None = None,
    external_termination_message_getter: Callable[[], str | None] | None = None,
) -> None:
    fs = QuellenFinderFirestoreService()
    budget_service = get_openai_budget_service(firebase_service)
    credits_service = get_credits_service(firebase_service)
    cost_service = get_cost_service(firebase_service)
    reservation_operation_id = _reservation_operation_id_from_data(run_doc, run_id)
    progress = RunProgressTracker(fs=fs, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
    heartbeat_stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(progress.heartbeat(heartbeat_stop))
    t0 = time.perf_counter()

    def user_cancel_requested_sync() -> bool:
        snap = fs.run_ref(user_id, projekt_id, run_id).get()
        data = snap.to_dict() if snap is not None else {}
        return bool((data or {}).get("cancelRequestedAt"))

    def termination_requested_sync() -> bool:
        return bool(external_termination_event is not None and external_termination_event.is_set())

    def termination_message() -> str:
        text = None
        if callable(external_termination_message_getter):
            try:
                text = external_termination_message_getter()
            except Exception:
                text = None
        return str(text or "PDF scan GPU worker termination requested.").strip()

    async def check_cancel() -> None:
        if termination_requested_sync():
            raise PdfScanRunTerminated(termination_message())
        if await asyncio.to_thread(user_cancel_requested_sync):
            raise PdfScanRunCancelled("Cancellation requested.")

    try:
        await check_cancel()
        await budget_service.mark_running(user_id=user_id, operation_id=reservation_operation_id)
        fs.run_ref(user_id, projekt_id, run_id).set(
            {
                "status": "running",
                "billing": {
                    "status": "running",
                    "reservationOperationId": reservation_operation_id,
                },
                "splitExecution": {
                    "gpu": {
                        "status": "running",
                        "startedAt": SERVER_TIMESTAMP,
                    }
                },
            },
            merge=True,
        )

        artifacts = run_doc.get("pdfScanArtifacts") if isinstance(run_doc.get("pdfScanArtifacts"), dict) else {}
        handoff_manifest_uri = str((artifacts or {}).get("handoffManifestUri") or "").strip()
        if not handoff_manifest_uri:
            raise RuntimeError("Run is missing pdfScanArtifacts.handoffManifestUri.")
        resolved_pdf_snapshots = [
            row for row in list((artifacts or {}).get("resolvedPdfSnapshots") or []) if isinstance(row, dict)
        ]
        if not resolved_pdf_snapshots:
            raise RuntimeError("Run is missing resolved PDF snapshots for final result persistence.")

        artifact_store = _artifact_store_from_run_doc(run_doc)
        await progress.on_progress("gpu_download", "Downloading CPU-to-GPU handoff")
        with tempfile.TemporaryDirectory(prefix="qf_pdf_scan_gpu_") as tmpdir:
            temp_root = Path(tmpdir)
            manifest = await asyncio.to_thread(artifact_store.download_json, path_or_uri=handoff_manifest_uri)
            restored_run_dir = await asyncio.to_thread(
                restore_handoff_bundle,
                artifact_store=artifact_store,
                manifest=manifest,
                work_root=temp_root,
            )
            await progress.on_progress("gpu_download", "Downloading CPU-to-GPU handoff complete", stage_completed=True)
            await check_cancel()

            pipeline_state = await run_pipeline_subprocess(
                script_path=FASTAPI_ROOT / "run_pdf_scan_gpu_pipeline.py",
                script_args=[
                    f"--run-dir={restored_run_dir}",
                    "--force-rebuild-phase-f",
                    "--force-rebuild-phase-g",
                    "--force-rebuild-phase-h",
                ],
                working_dir=FASTAPI_ROOT,
                on_progress=progress.on_progress,
                cancel_requested_sync=user_cancel_requested_sync,
                termination_requested_sync=termination_requested_sync,
                termination_message_getter=termination_message,
            )
            await check_cancel()

            pipeline_run_dir = resolve_pipeline_run_dir(
                pipeline_state.get("run_dir"),
                expected_root=temp_root / "pipeline_runs",
            )

            await progress.on_progress("persist_results", "Preparing PDF result cards")
            pdf_snapshot_by_id = {
                str(row.get("id") or "").strip(): row
                for row in resolved_pdf_snapshots
                if str(row.get("id") or "").strip()
            }
            persisted = await asyncio.to_thread(
                build_persisted_pdf_scan_v2_view,
                run_dir=pipeline_run_dir,
                pdf_snapshot_by_id=pdf_snapshot_by_id,
                kapitel_snapshots=list((run_doc.get("kapitelSnapshots") or [])),
            )
            await check_cancel()

            total_docs = int(
                sum(len(rows) for rows in list((persisted.get("chapter_doc_docs") or {}).values()))
                + len(list(persisted.get("aggregate_doc_docs") or []))
            )
            await progress.on_progress("persist_results", "Saving PDF result cards", current=total_docs, total=total_docs)
            await asyncio.to_thread(
                fs.replace_pdf_scan_v2_results,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                root_payload=dict(persisted.get("root_update") or {}),
                chapter_docs=list(persisted.get("chapter_docs") or []),
                chapter_doc_docs=dict(persisted.get("chapter_doc_docs") or {}),
                chapter_section_docs=dict(persisted.get("chapter_section_docs") or {}),
                aggregate_doc_docs=list(persisted.get("aggregate_doc_docs") or []),
                aggregate_section_docs=list(persisted.get("aggregate_section_docs") or []),
            )
            verification = await asyncio.to_thread(
                fs.verify_pdf_scan_v2_results,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                chapter_docs=list(persisted.get("chapter_docs") or []),
                chapter_doc_docs=dict(persisted.get("chapter_doc_docs") or {}),
                chapter_section_docs=dict(persisted.get("chapter_section_docs") or {}),
                aggregate_doc_docs=list(persisted.get("aggregate_doc_docs") or []),
                aggregate_section_docs=list(persisted.get("aggregate_section_docs") or []),
            )
            if not bool((verification or {}).get("ok")):
                logger.warning(
                    "PDF scan v2 persistence verification failed after first write; retrying once | run_id=%s verification=%s",
                    run_id,
                    verification,
                )
                await asyncio.to_thread(
                    fs.replace_pdf_scan_v2_results,
                    user_id=user_id,
                    projekt_id=projekt_id,
                    run_id=run_id,
                    root_payload=dict(persisted.get("root_update") or {}),
                    chapter_docs=list(persisted.get("chapter_docs") or []),
                    chapter_doc_docs=dict(persisted.get("chapter_doc_docs") or {}),
                    chapter_section_docs=dict(persisted.get("chapter_section_docs") or {}),
                    aggregate_doc_docs=list(persisted.get("aggregate_doc_docs") or []),
                    aggregate_section_docs=list(persisted.get("aggregate_section_docs") or []),
                )
                verification = await asyncio.to_thread(
                    fs.verify_pdf_scan_v2_results,
                    user_id=user_id,
                    projekt_id=projekt_id,
                    run_id=run_id,
                    chapter_docs=list(persisted.get("chapter_docs") or []),
                    chapter_doc_docs=dict(persisted.get("chapter_doc_docs") or {}),
                    chapter_section_docs=dict(persisted.get("chapter_section_docs") or {}),
                    aggregate_doc_docs=list(persisted.get("aggregate_doc_docs") or []),
                    aggregate_section_docs=list(persisted.get("aggregate_section_docs") or []),
                )
            if not bool((verification or {}).get("ok")):
                raise RuntimeError(f"PDF scan v2 persistence verification failed: {verification}")
            await progress.on_progress(
                "persist_results",
                "Saving PDF result cards complete",
                current=total_docs,
                total=total_docs,
                stage_completed=True,
            )

            final_upload = await asyncio.to_thread(
                upload_final_outputs,
                run_dir=pipeline_run_dir,
                artifact_store=artifact_store,
                run_id=run_id,
            )

            dt_gpu = float(time.perf_counter() - t0)
            cpu_elapsed_seconds = float(
                (((run_doc.get("splitExecution") or {}).get("cpu") or {}).get("elapsedSeconds") or 0.0)
            )
            total_elapsed_seconds = float(round(max(cpu_elapsed_seconds, 0.0) + max(dt_gpu, 0.0), 3))
            api_usage = read_pdf_scan_api_usage(pipeline_run_dir)
            compute_billing = await credits_service.calculate_pdf_scan_compute_cost(
                user_id=user_id,
                pdf_count=len(resolved_pdf_snapshots),
                seconds_total=total_elapsed_seconds,
            )
            openai_cost_usd = float(max(float(api_usage.get("cost_usd") or 0.0), 0.0))
            compute_cost_usd = float(max(float(compute_billing.get("cost_usd") or 0.0), 0.0))
            total_cost_usd = float(round(openai_cost_usd + compute_cost_usd, 10))
            spend_rate_value = float(max(float(compute_billing.get("spend_rate") or 0.0), 0.0))
            usage_payload = TokenUsage.from_any(
                api_usage.get("input_tokens"),
                api_usage.get("cached_input_tokens"),
                api_usage.get("output_tokens"),
            )
            await cost_service.log_billed_operation(
                operation_id=reservation_operation_id,
                operation_type="pdf_scan_run",
                user_id=user_id,
                user_action_id=run_id,
                cost_usd=total_cost_usd,
                credits_source="pdf_scan",
                operation_details={
                    "pdfCount": int(len(resolved_pdf_snapshots)),
                    "pipelineVersion": str(run_doc.get("model") or "pdf_scan_v3_topic_best"),
                    "visibleDocCount": int((persisted.get("root_update") or {}).get("pdfScanCounts", {}).get("aggregateDocCount") or 0),
                    "visibleSectionCount": int(persisted.get("total_visible_section_count") or 0),
                    "hadPartialFailures": bool(persisted.get("had_partial_failures")),
                },
                model=str(run_doc.get("model") or "pdf_scan_v3_topic_best"),
                usage=usage_payload,
                key_source="pdf_scan_pipeline",
                billing_components={
                    "openaiCostUsd": float(round(openai_cost_usd, 10)),
                    "computeCostUsd": float(round(compute_cost_usd, 10)),
                    "totalCostUsd": float(round(total_cost_usd, 10)),
                    "secondsTotal": float(round(total_elapsed_seconds, 3)),
                    "secondsCpu": float(round(cpu_elapsed_seconds, 3)),
                    "secondsGpu": float(round(dt_gpu, 3)),
                    "spendRate": float(round(spend_rate_value, 8)),
                },
                projekt_id=projekt_id,
                run_id=run_id,
                spend_rate=spend_rate_value or None,
            )
            await budget_service.mark_status(
                user_id=user_id,
                operation_id=reservation_operation_id,
                status="success",
            )
            await budget_service.release_reservation(
                user_id=user_id,
                operation_id=reservation_operation_id,
                reason="success",
            )
            fs.mark_success(
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                had_partial_failures=bool(persisted.get("had_partial_failures")),
                extra=_merge_persisted_root_update({
                    "billing": {
                        "status": "success",
                        "reservationOperationId": reservation_operation_id,
                        "finishedAt": SERVER_TIMESTAMP,
                        "openaiCostUsd": float(round(openai_cost_usd, 10)),
                        "computeCostUsd": float(round(compute_cost_usd, 10)),
                        "totalCostUsd": float(round(total_cost_usd, 10)),
                        "credits": float(round(total_cost_usd * max(spend_rate_value, 0.0), 8)),
                        "secondsTotal": float(round(total_elapsed_seconds, 3)),
                        "secondsCpu": float(round(cpu_elapsed_seconds, 3)),
                        "secondsGpu": float(round(dt_gpu, 3)),
                        "spendRate": float(round(spend_rate_value, 8)),
                    },
                    "pdfScanArtifacts": {
                        "finalArtifactsPrefixUri": final_upload.get("prefix_uri"),
                        "finalArtifactCount": final_upload.get("uploaded_count"),
                        "finalArtifactPreview": final_upload.get("uploaded_uris_preview"),
                    },
                    "splitExecution": {
                        "gpu": {
                            "status": "success",
                            "finishedAt": SERVER_TIMESTAMP,
                            "elapsedSeconds": float(round(dt_gpu, 3)),
                            "lastCompletedPhase": str(pipeline_state.get("last_completed_phase") or "phase_h"),
                            "pipelineRunId": pipeline_state.get("pipeline_run_id"),
                        }
                    },
                    "resultSummary": {
                        "visibleDocCount": int((persisted.get("root_update") or {}).get("pdfScanCounts", {}).get("aggregateDocCount") or 0),
                        "visibleSectionCount": int(persisted.get("total_visible_section_count") or 0),
                        "usefulPdfCount": int(persisted.get("useful_pdf_count_any_chapter") or 0),
                    },
                }, persisted),
            )
    except PdfScanRunCancelled as exc:
        logger.info("PDF scan GPU worker cancelled | run_id=%s err=%s", run_id, exc)
        await _finalize_failure(
            fs=fs,
            budget_service=budget_service,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            reservation_operation_id=reservation_operation_id,
            message=str(exc),
            cancelled=True,
            progress=progress,
        )
        raise
    except Exception as exc:
        logger.error("PDF scan GPU worker failed | run_id=%s error=%s", run_id, exc, exc_info=True)
        await _finalize_failure(
            fs=fs,
            budget_service=budget_service,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            reservation_operation_id=reservation_operation_id,
            message=str(exc),
            cancelled=False,
            progress=progress,
        )
        raise
    finally:
        heartbeat_stop.set()
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except BaseException:
            pass


async def run_pdf_scan_gpu_job_from_run_doc(
    *,
    user_id: str,
    projekt_id: str,
    run_id: str,
    external_termination_event: asyncio.Event | None = None,
    external_termination_message_getter: Callable[[], str | None] | None = None,
) -> None:
    fs = QuellenFinderFirestoreService()
    budget_service = get_openai_budget_service(firebase_service)
    data = await load_required_run_doc(
        fs=fs,
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        purpose="gpu_run_execution",
    )
    status_now = str((data or {}).get("status") or "").strip()
    if status_now in {"success", "error", "cancelled"}:
        logger.info("PDF scan GPU worker no-op | run_id=%s status=%s", run_id, status_now)
        return
    if bool((data or {}).get("cancelRequestedAt")):
        await _finalize_failure(
            fs=fs,
            budget_service=budget_service,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            reservation_operation_id=_reservation_operation_id_from_data(data, run_id),
            message="Cancellation requested.",
            cancelled=True,
            progress=None,
        )
        return
    split_execution = data.get("splitExecution") if isinstance(data.get("splitExecution"), dict) else {}
    gpu_state = split_execution.get("gpu") if isinstance(split_execution.get("gpu"), dict) else {}
    if str((gpu_state or {}).get("status") or "").strip() in {"running", "success"}:
        logger.info("PDF scan GPU worker no-op | run_id=%s gpu_status=%s", run_id, str((gpu_state or {}).get("status") or "").strip())
        return
    if str((data or {}).get("kind") or "") != "pdf_scan":
        exc = RuntimeError("Run is not a pdf_scan run.")
        await _finalize_failure(
            fs=fs,
            budget_service=budget_service,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            reservation_operation_id=_reservation_operation_id_from_data(data, run_id),
            message=str(exc),
            cancelled=False,
            progress=None,
        )
        raise exc
    await run_pdf_scan_gpu_job(
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        run_doc=data,
        external_termination_event=external_termination_event,
        external_termination_message_getter=external_termination_message_getter,
    )
