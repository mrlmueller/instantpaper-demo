from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.cloud_run_job_launcher import cloud_run_job_launcher
from services.firebase_service import firebase_service
from services.openai_budget_service import get_openai_budget_service
from services.pdf_scan.common import (
    FASTAPI_ROOT,
    PdfScanRunCancelled,
    PdfScanRunTerminated,
    RunProgressTracker,
    build_runtime_settings_from_run_doc,
    build_theme_markdown,
    download_selected_pdfs,
    load_required_run_doc,
    resolve_pipeline_run_dir,
    run_pipeline_subprocess,
)
from services.pdf_scan.handoff import upload_handoff_bundle
from services.pdf_scan.storage import PdfScanArtifactStore
from services.quellen_finder_firestore_service import QuellenFinderFirestoreService
from utils.config import config

logger = logging.getLogger(__name__)


def _artifact_store_from_config() -> PdfScanArtifactStore:
    bucket_name = str(config.PDF_SCAN_ARTIFACT_BUCKET or "").strip() or str(config.FIREBASE_STORAGE_BUCKET or "").strip()
    if not bucket_name:
        raise RuntimeError("PDF_SCAN_ARTIFACT_BUCKET or FIREBASE_STORAGE_BUCKET must be configured.")
    return PdfScanArtifactStore(
        bucket_name=bucket_name,
        base_prefix=str(config.PDF_SCAN_ARTIFACT_PREFIX or "").strip(),
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
                "cpu": {
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
            "cpu": {
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


async def run_pdf_scan_cpu_job(
    *,
    user_id: str,
    projekt_id: str,
    run_id: str,
    settings: dict[str, Any],
    external_termination_event: asyncio.Event | None = None,
    external_termination_message_getter: Callable[[], str | None] | None = None,
) -> None:
    fs = QuellenFinderFirestoreService()
    budget_service = get_openai_budget_service(firebase_service)
    run_doc = await load_required_run_doc(
        fs=fs,
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        purpose="cpu_run_execution",
    )
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
        return str(text or "PDF scan CPU worker termination requested.").strip()

    async def check_cancel() -> None:
        if termination_requested_sync():
            raise PdfScanRunTerminated(termination_message())
        if await asyncio.to_thread(user_cancel_requested_sync):
            raise PdfScanRunCancelled("Cancellation requested.")

    try:
        await check_cancel()
        await budget_service.mark_running(user_id=user_id, operation_id=reservation_operation_id)
        fs.mark_running(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        fs.run_ref(user_id, projekt_id, run_id).set(
            {
                "billing": {
                    "status": "running",
                    "reservationOperationId": reservation_operation_id,
                    "startedAt": SERVER_TIMESTAMP,
                },
                "job": {
                    "provider": "cloud_run_split_jobs",
                },
                "splitExecution": {
                    "cpu": {
                        "status": "running",
                        "startedAt": SERVER_TIMESTAMP,
                    },
                    "gpu": {
                        "status": "pending",
                    },
                },
            },
            merge=True,
        )
        await progress.on_progress("prepare_inputs", "Preparing PDF scan inputs")
        await asyncio.to_thread(fs.clear_subcollection, user_id=user_id, projekt_id=projekt_id, run_id=run_id, name="pdfScanDocs")
        await asyncio.to_thread(fs.clear_subcollection, user_id=user_id, projekt_id=projekt_id, run_id=run_id, name="pdfScanSections")

        with tempfile.TemporaryDirectory(prefix="qf_pdf_scan_cpu_") as tmpdir:
            temp_root = Path(tmpdir)
            theme_path = temp_root / "Text Thema.md"
            pdf_root = temp_root / "pdfs"
            pipeline_runs_root = temp_root / "pipeline_runs"
            theme_path.write_text(
                build_theme_markdown(
                    chapter_title=str((settings or {}).get("chapter_title") or "").strip(),
                    chapter_spec_text=str((settings or {}).get("chapter_spec_text") or "").strip(),
                ),
                encoding="utf-8",
            )

            pdf_snapshot_rows = list((settings or {}).get("pdf_snapshots") or [])
            pdf_snapshot_by_id = await asyncio.to_thread(
                download_selected_pdfs,
                pdf_snapshots=pdf_snapshot_rows,
                pdf_root=pdf_root,
                on_progress_sync=progress.on_progress_sync,
                cancel_requested_sync=user_cancel_requested_sync,
                termination_requested_sync=termination_requested_sync,
                termination_message_getter=termination_message,
            )
            await check_cancel()

            pipeline_state = await run_pipeline_subprocess(
                script_path=FASTAPI_ROOT / "run_pdf_scan_pipeline.py",
                script_args=[
                    f"--theme-md={theme_path}",
                    f"--pdf-dir={pdf_root}",
                    f"--runs-root={pipeline_runs_root}",
                    f"--max-pdfs={len(pdf_snapshot_rows)}",
                    "--pdf-recursive",
                    "--force-rebuild-phase-a",
                    "--force-rebuild-phase-b",
                    "--force-rebuild-phase-c",
                    "--force-rebuild-phase-d",
                    "--force-rebuild-phase-e",
                    "--end-phase=phase_e",
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
                expected_root=pipeline_runs_root,
            )
            await progress.on_progress("gpu_handoff", "Uploading CPU-to-GPU handoff")
            artifact_store = _artifact_store_from_config()
            handoff_manifest = await asyncio.to_thread(
                upload_handoff_bundle,
                run_dir=pipeline_run_dir,
                artifact_store=artifact_store,
                run_id=run_id,
                pipeline_version=str((run_doc.get("model") or "").strip() or "pdf_scan_v3_topic_best"),
            )
            await progress.on_progress("gpu_handoff", "Uploading CPU-to-GPU handoff complete", stage_completed=True)

            await progress.on_progress("gpu_queue", "Queueing GPU worker")
            try:
                gpu_launch = await asyncio.to_thread(
                    cloud_run_job_launcher.execute_pdf_scan_gpu_job,
                    user_id=user_id,
                    projekt_id=projekt_id,
                    run_id=run_id,
                )
            except Exception as exc:
                fs.run_ref(user_id, projekt_id, run_id).set(
                    {
                        "job": {
                            "gpu": {
                                "jobName": str(config.PDF_SCAN_GPU_CLOUD_RUN_JOB_NAME or "").strip() or None,
                                "region": str(config.PDF_SCAN_GPU_CLOUD_RUN_JOB_REGION or "").strip() or None,
                                "launchError": str(exc or "")[:1000] or "Failed to launch GPU job.",
                            }
                        }
                    },
                    merge=True,
                )
                raise

            elapsed_seconds = round(float(time.perf_counter() - t0), 3)
            fs.run_ref(user_id, projekt_id, run_id).set(
                {
                    "job": {
                        "provider": "cloud_run_split_jobs",
                        "jobName": str((gpu_launch or {}).get("job_name") or config.PDF_SCAN_GPU_CLOUD_RUN_JOB_NAME or "").strip() or None,
                        "region": str((gpu_launch or {}).get("region") or config.PDF_SCAN_GPU_CLOUD_RUN_JOB_REGION or "").strip() or None,
                        "operationName": (gpu_launch or {}).get("operation_name"),
                        "executionName": (gpu_launch or {}).get("execution_name"),
                        "launchedAt": SERVER_TIMESTAMP,
                        "launchError": None,
                        "cpu": {
                            "jobName": str(config.PDF_SCAN_CPU_CLOUD_RUN_JOB_NAME or "").strip() or None,
                            "region": str(config.PDF_SCAN_CPU_CLOUD_RUN_JOB_REGION or "").strip() or None,
                        },
                        "gpu": {
                            "jobName": str((gpu_launch or {}).get("job_name") or config.PDF_SCAN_GPU_CLOUD_RUN_JOB_NAME or "").strip() or None,
                            "region": str((gpu_launch or {}).get("region") or config.PDF_SCAN_GPU_CLOUD_RUN_JOB_REGION or "").strip() or None,
                            "operationName": (gpu_launch or {}).get("operation_name"),
                            "executionName": (gpu_launch or {}).get("execution_name"),
                            "launchedAt": SERVER_TIMESTAMP,
                            "launchError": None,
                        },
                    },
                    "pdfScanArtifacts": {
                        "bucket": artifact_store.bucket_name,
                        "basePrefix": artifact_store.base_prefix,
                        "handoffManifestUri": handoff_manifest.get("manifest_uri"),
                        "handoffBundleUri": handoff_manifest.get("bundle_uri"),
                        "handoffBundleSha256": handoff_manifest.get("bundle_sha256"),
                        "handoffBundleSizeBytes": handoff_manifest.get("bundle_size_bytes"),
                        "handoffLastCompletedPhase": handoff_manifest.get("last_completed_phase"),
                        "cpuPipelineRunId": pipeline_state.get("pipeline_run_id"),
                        "resolvedPdfSnapshots": list(pdf_snapshot_by_id.values()),
                    },
                    "splitExecution": {
                        "cpu": {
                            "status": "success",
                            "finishedAt": SERVER_TIMESTAMP,
                            "elapsedSeconds": elapsed_seconds,
                            "lastCompletedPhase": "phase_e",
                            "pipelineRunId": pipeline_state.get("pipeline_run_id"),
                            "runDirName": pipeline_run_dir.name,
                        },
                        "gpu": {
                            "status": "queued",
                            "queuedAt": SERVER_TIMESTAMP,
                        },
                    },
                },
                merge=True,
            )
            await progress.on_progress("gpu_queue", "GPU worker queued", stage_completed=True)
    except PdfScanRunCancelled as exc:
        logger.info("PDF scan CPU worker cancelled | run_id=%s err=%s", run_id, exc)
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
        logger.error("PDF scan CPU worker failed | run_id=%s error=%s", run_id, exc, exc_info=True)
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


async def run_pdf_scan_cpu_job_from_run_doc(
    *,
    user_id: str,
    projekt_id: str,
    run_id: str,
    external_termination_event: asyncio.Event | None = None,
    external_termination_message_getter: Callable[[], str | None] | None = None,
) -> None:
    fs = QuellenFinderFirestoreService()
    budget_service = get_openai_budget_service(firebase_service)

    def _load() -> tuple[dict[str, Any], str | None]:
        data = fs.get_run(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        status_now = str((data or {}).get("status") or "").strip()
        if status_now in {"success", "error", "cancelled"}:
            return data, "terminal"
        if status_now == "running":
            split_execution = data.get("splitExecution") if isinstance(data.get("splitExecution"), dict) else {}
            cpu_state = split_execution.get("cpu") if isinstance(split_execution.get("cpu"), dict) else {}
            if str((cpu_state or {}).get("status") or "").strip() in {"running", "success"}:
                return data, "already_running"
        if bool((data or {}).get("cancelRequestedAt")):
            fs.mark_cancelled(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
            return data, "cancelled_before_start"
        return data, None

    data, skip_reason = await asyncio.to_thread(_load)
    if skip_reason:
        logger.info(
            "PDF scan CPU worker no-op | run_id=%s projekt_id=%s reason=%s",
            run_id,
            projekt_id,
            skip_reason,
        )
        return

    try:
        if str((data or {}).get("kind") or "") != "pdf_scan":
            raise RuntimeError("Run is not a pdf_scan run.")
        _kapitel_id, settings = build_runtime_settings_from_run_doc(data)
    except Exception as exc:
        await _finalize_failure(
            fs=fs,
            budget_service=budget_service,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            reservation_operation_id=_reservation_operation_id_from_data(data, run_id),
            message=str(exc),
            cancelled=isinstance(exc, PdfScanRunCancelled),
            progress=None,
        )
        raise
    await run_pdf_scan_cpu_job(
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        settings=settings,
        external_termination_event=external_termination_event,
        external_termination_message_getter=external_termination_message_getter,
    )
