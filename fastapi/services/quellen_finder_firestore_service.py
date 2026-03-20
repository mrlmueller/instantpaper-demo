from __future__ import annotations

import math
import logging
from typing import Any, Iterable, Optional

from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.firebase_service import firebase_service

logger = logging.getLogger(__name__)


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        s = str(value).strip()
    except Exception:
        return None
    return s or None


def _sanitize_firestore_value(value: Any) -> tuple[Any, bool]:
    """
    Firestore does not allow nested arrays (arrays containing arrays).

    We sanitize payloads defensively so that debug/telemetry writes don't fail an otherwise successful job.
    """

    if isinstance(value, float) and not math.isfinite(value):
        return None, True

    if isinstance(value, dict):
        changed = False
        out: dict[str, Any] = {}
        for k, v in value.items():
            vv, ch = _sanitize_firestore_value(v)
            changed = changed or ch
            out[str(k)] = vv
        return out, changed

    if isinstance(value, (list, tuple)):
        changed = False
        out_list: list[Any] = []
        for v in value:
            if isinstance(v, (list, tuple)):
                inner, _ = _sanitize_firestore_value(list(v))
                out_list.append({"values": inner})
                changed = True
                continue
            vv, ch = _sanitize_firestore_value(v)
            changed = changed or ch
            out_list.append(vv)
        return out_list, changed

    return value, False


class QuellenFinderFirestoreService:
    def __init__(self):
        self.firebase = firebase_service

    def _project_ref(self, user_id: str, projekt_id: str):
        return (
            self.firebase.db.collection("users")
            .document(str(user_id))
            .collection("projects")
            .document(str(projekt_id))
        )

    def runs_col(self, user_id: str, projekt_id: str):
        return self._project_ref(user_id, projekt_id).collection("researchRuns")

    def run_ref(self, user_id: str, projekt_id: str, run_id: str):
        return self.runs_col(user_id, projekt_id).document(str(run_id))

    def create_run(
        self,
        *,
        user_id: str,
        projekt_id: str,
        run_id: str | None = None,
        kind: str,
        kapitel_ids: list[str],
        kapitel_snapshots: Optional[list[dict]] = None,
        model: str | None = None,
        pdf_ids: Optional[list[str]] = None,
        extra: Optional[dict] = None,
    ) -> str:
        run_id_norm = _as_str(run_id)
        doc_ref = self.runs_col(user_id, projekt_id).document(run_id_norm) if run_id_norm else self.runs_col(user_id, projekt_id).document()

        payload: dict[str, Any] = {
            "kind": str(kind),
            "status": "queued",
            "projektId": str(projekt_id),
            "kapitelIds": list(kapitel_ids or []),
            "kapitelSnapshots": list(kapitel_snapshots or []),
            "model": _as_str(model),
            "hadPartialFailures": False,
            "errorMessage": None,
            "progress": {"stage": "queued", "message": "Queued"},
            "createdAt": SERVER_TIMESTAMP,
            "updatedAt": SERVER_TIMESTAMP,
            "startedAt": None,
            "finishedAt": None,
        }
        if pdf_ids is not None:
            payload["pdfIds"] = list(pdf_ids or [])
        if isinstance(extra, dict) and extra:
            payload.update(extra)

        doc_ref.set(payload)
        return str(doc_ref.id)

    def get_run(self, *, user_id: str, projekt_id: str, run_id: str) -> dict[str, Any]:
        snap = self.run_ref(user_id, projekt_id, run_id).get()
        if snap is None or not getattr(snap, "exists", False):
            raise ValueError("Run not found.")
        data = snap.to_dict()
        return data if isinstance(data, dict) else {}

    def find_active_two_lane_run_for_kapitel(
        self,
        *,
        user_id: str,
        projekt_id: str,
        kapitel_id: str,
    ) -> dict[str, Any] | None:
        kapitel_id_norm = _as_str(kapitel_id)
        if not kapitel_id_norm:
            return None

        q = self.runs_col(user_id, projekt_id).where("kind", "==", "sources_two_lane")
        found: dict[str, Any] | None = None
        found_created = None

        for snap in q.stream():
            if snap is None or not getattr(snap, "exists", False):
                continue
            data = snap.to_dict() if snap is not None else {}
            if not isinstance(data, dict):
                continue

            kapitel_ids = data.get("kapitelIds")
            if not isinstance(kapitel_ids, list) or kapitel_id_norm not in [str(x) for x in kapitel_ids]:
                continue

            status_now = str((data or {}).get("status") or "").strip()
            if status_now not in {"queued", "running"}:
                continue

            created_at = (data or {}).get("createdAt")
            if found is None or (created_at is not None and (found_created is None or created_at > found_created)):
                found = {"run_id": str(snap.id), "data": data}
                found_created = created_at

        return found

    def attach_job_execution(
        self,
        *,
        user_id: str,
        projekt_id: str,
        run_id: str,
        job_name: str,
        region: str,
        operation_name: str | None = None,
        execution_name: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "updatedAt": SERVER_TIMESTAMP,
            "job": {
                "provider": "cloud_run_jobs",
                "jobName": _as_str(job_name),
                "region": _as_str(region),
                "operationName": _as_str(operation_name),
                "executionName": _as_str(execution_name),
                "launchedAt": SERVER_TIMESTAMP,
                "launchError": None,
            },
        }
        self.run_ref(user_id, projekt_id, run_id).set(payload, merge=True)

    def mark_launch_failed(
        self,
        *,
        user_id: str,
        projekt_id: str,
        run_id: str,
        error_message: str,
        job_name: str | None = None,
        region: str | None = None,
        operation_name: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "status": "error",
            "errorMessage": str(error_message or "")[:1000] or "Failed to launch Cloud Run Job.",
            "hadPartialFailures": False,
            "finishedAt": SERVER_TIMESTAMP,
            "updatedAt": SERVER_TIMESTAMP,
            "progress": {"stage": "error", "message": "Error"},
            "job": {
                "provider": "cloud_run_jobs",
                "jobName": _as_str(job_name),
                "region": _as_str(region),
                "operationName": _as_str(operation_name),
                "launchError": str(error_message or "")[:1000] or "Failed to launch Cloud Run Job.",
            },
        }
        self.run_ref(user_id, projekt_id, run_id).set(payload, merge=True)

    def set_progress(
        self,
        *,
        user_id: str,
        projekt_id: str,
        run_id: str,
        stage: str,
        message: str | None = None,
        current: int | None = None,
        total: int | None = None,
        stage_started_at: bool = False,
    ) -> None:
        progress: dict[str, Any] = {
            "stage": str(stage),
            "message": _as_str(message),
            "current": int(current) if isinstance(current, int) else None,
            "total": int(total) if isinstance(total, int) else None,
        }
        if bool(stage_started_at):
            progress["stageStartedAt"] = SERVER_TIMESTAMP

        payload: dict[str, Any] = {
            "updatedAt": SERVER_TIMESTAMP,
            "progress": progress,
        }
        self.run_ref(user_id, projekt_id, run_id).set(payload, merge=True)

    def mark_running(self, *, user_id: str, projekt_id: str, run_id: str) -> None:
        self.run_ref(user_id, projekt_id, run_id).set(
            {
                "status": "running",
                "errorMessage": None,
                "hadPartialFailures": False,
                "startedAt": SERVER_TIMESTAMP,
                "updatedAt": SERVER_TIMESTAMP,
            },
            merge=True,
        )

    def mark_success(
        self,
        *,
        user_id: str,
        projekt_id: str,
        run_id: str,
        had_partial_failures: bool = False,
        extra: dict | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "status": "success",
            "errorMessage": None,
            "hadPartialFailures": bool(had_partial_failures),
            "finishedAt": SERVER_TIMESTAMP,
            "updatedAt": SERVER_TIMESTAMP,
            "progress": {"stage": "done", "message": "Done"},
        }
        if isinstance(extra, dict) and extra:
            payload.update(extra)
        self.run_ref(user_id, projekt_id, run_id).set(payload, merge=True)

    def mark_error(
        self,
        *,
        user_id: str,
        projekt_id: str,
        run_id: str,
        error_message: str,
        had_partial_failures: bool = False,
    ) -> None:
        self.run_ref(user_id, projekt_id, run_id).set(
            {
                "status": "error",
                "errorMessage": str(error_message or "")[:1000] or "Unknown error",
                "hadPartialFailures": bool(had_partial_failures),
                "finishedAt": SERVER_TIMESTAMP,
                "updatedAt": SERVER_TIMESTAMP,
                "progress": {"stage": "error", "message": "Error"},
            },
            merge=True,
        )

    def request_cancel(self, *, user_id: str, projekt_id: str, run_id: str) -> None:
        self.run_ref(user_id, projekt_id, run_id).set(
            {
                "cancelRequestedAt": SERVER_TIMESTAMP,
                "updatedAt": SERVER_TIMESTAMP,
                "progress": {"stage": "cancel_requested", "message": "Cancellation requested"},
            },
            merge=True,
        )

    def mark_cancelled(self, *, user_id: str, projekt_id: str, run_id: str) -> None:
        self.run_ref(user_id, projekt_id, run_id).set(
            {
                "status": "cancelled",
                "errorMessage": None,
                "hadPartialFailures": False,
                "cancelledAt": SERVER_TIMESTAMP,
                "finishedAt": SERVER_TIMESTAMP,
                "updatedAt": SERVER_TIMESTAMP,
                "progress": {"stage": "cancelled", "message": "Cancelled"},
            },
            merge=True,
        )

    def clear_subcollection(self, *, user_id: str, projekt_id: str, run_id: str, name: str) -> None:
        col = self.run_ref(user_id, projekt_id, run_id).collection(str(name))
        snaps = list(col.stream())
        if not snaps:
            return
        for start in range(0, len(snaps), 400):
            batch = self.firebase.db.batch()
            for snap in snaps[start : start + 400]:
                batch.delete(snap.reference)
            batch.commit()

    def write_two_lane_results(
        self,
        *,
        user_id: str,
        projekt_id: str,
        run_id: str,
        docs: Iterable[tuple[str, dict]],
    ) -> None:
        self.write_subcollection_docs(
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            name="twoLaneResults",
            docs=docs,
        )

    def write_two_lane_telemetry(
        self,
        *,
        user_id: str,
        projekt_id: str,
        run_id: str,
        docs: Iterable[tuple[str, dict]],
    ) -> None:
        self.write_subcollection_docs(
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            name="twoLaneTelemetry",
            docs=docs,
        )

    def write_subcollection_docs(
        self,
        *,
        user_id: str,
        projekt_id: str,
        run_id: str,
        name: str,
        docs: Iterable[tuple[str, dict]],
    ) -> None:
        col = self.run_ref(user_id, projekt_id, run_id).collection(str(name))
        docs_list = list(docs)
        count = 0
        sanitized_any = False
        for start in range(0, len(docs_list), 400):
            batch = self.firebase.db.batch()
            chunk = docs_list[start : start + 400]
            for doc_id, payload in chunk:
                payload2, changed = _sanitize_firestore_value(payload)
                sanitized_any = sanitized_any or changed
                batch.set(col.document(str(doc_id)), payload2)
                count += 1
            if chunk:
                batch.commit()
        if count:
            if sanitized_any:
                logger.warning(
                    "Firestore payload sanitized (nested arrays / non-finite numbers) | subcollection=%s run_id=%s docs=%s",
                    str(name),
                    str(run_id),
                    int(count),
                )
