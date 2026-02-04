from __future__ import annotations

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
        kind: str,
        kapitel_ids: list[str],
        kapitel_snapshots: Optional[list[dict]] = None,
        model: str | None = None,
        pdf_ids: Optional[list[str]] = None,
    ) -> str:
        doc_ref = self.runs_col(user_id, projekt_id).document()

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

        doc_ref.set(payload)
        return str(doc_ref.id)

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
    ) -> None:
        payload: dict[str, Any] = {
            "updatedAt": SERVER_TIMESTAMP,
            "progress": {
                "stage": str(stage),
                "message": _as_str(message),
                "current": int(current) if isinstance(current, int) else None,
                "total": int(total) if isinstance(total, int) else None,
            },
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

    def clear_subcollection(self, *, user_id: str, projekt_id: str, run_id: str, name: str) -> None:
        col = self.run_ref(user_id, projekt_id, run_id).collection(str(name))
        snaps = list(col.stream())
        if not snaps:
            return
        batch = self.firebase.db.batch()
        for snap in snaps:
            batch.delete(snap.reference)
        batch.commit()

    def write_sources_results(
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
            name="sourcesResults",
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
        batch = self.firebase.db.batch()
        count = 0
        for doc_id, payload in docs:
            batch.set(col.document(str(doc_id)), payload)
            count += 1
        if count:
            batch.commit()
