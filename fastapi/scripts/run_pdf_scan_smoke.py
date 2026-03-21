from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
FASTAPI_DIR = SCRIPT_DIR.parent
REPO_ROOT = FASTAPI_DIR.parent
if str(FASTAPI_DIR) not in sys.path:
    sys.path.insert(0, str(FASTAPI_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.firebase_service import firebase_service
from services.quellen_finder_firestore_service import QuellenFinderFirestoreService
from services.quellen_finder_pdf_scan_job import run_quellen_finder_pdf_scan_job_from_run_doc


def _load_project_pdf(user_id: str, project_id: str, pdf_id: str) -> dict:
    snap = (
        firebase_service.db.collection("users")
        .document(str(user_id))
        .collection("projects")
        .document(str(project_id))
        .collection("pdfs")
        .document(str(pdf_id))
        .get()
    )
    if snap is None or not getattr(snap, "exists", False):
        raise ValueError(f"Project PDF not found: {pdf_id}")
    data = snap.to_dict()
    if not isinstance(data, dict):
        raise ValueError(f"Project PDF payload is invalid: {pdf_id}")
    return data


async def _build_run_payload(user_id: str, project_id: str, kapitel_id: str, pdf_ids: list[str]) -> tuple[str, dict]:
    project = await firebase_service.get_project(user_id, project_id)
    if not isinstance(project, dict):
        raise ValueError(f"Project not found: {project_id}")

    kapitel = await firebase_service.get_kapitel(user_id, kapitel_id)
    if not isinstance(kapitel, dict):
        raise ValueError(f"Kapitel not found: {kapitel_id}")

    kapitel_snapshot = {
        "id": str(kapitel_id),
        "nummer": str((kapitel or {}).get("nummer") or "").strip() or None,
        "title": str((kapitel or {}).get("title") or "").strip() or None,
        "ueberschrift": str((kapitel or {}).get("title") or "").strip() or None,
        "thema": str((kapitel or {}).get("thema") or "").strip() or None,
    }

    pdf_snapshots = []
    for pdf_id in pdf_ids:
        pdf_doc = _load_project_pdf(user_id, project_id, pdf_id)
        pdf_snapshots.append(
            {
                "id": str(pdf_id),
                "filename": str((pdf_doc or {}).get("filename") or "").strip() or None,
                "storagePath": str((pdf_doc or {}).get("storagePath") or "").strip() or None,
                "size": int((pdf_doc or {}).get("size") or 0) or None,
                "contentType": str((pdf_doc or {}).get("contentType") or "").strip() or None,
            }
        )

    fs = QuellenFinderFirestoreService()
    run_id = fs.create_run(
        user_id=user_id,
        projekt_id=project_id,
        kind="pdf_scan",
        kapitel_ids=[kapitel_id],
        kapitel_snapshots=[kapitel_snapshot],
        model="pdf_scan_v3_topic_best",
        pdf_ids=pdf_ids,
        extra={
            "chapterInputSnapshot": {
                "chapterTitle": str((kapitel or {}).get("title") or "").strip() or None,
                "chapterSpecText": str((kapitel or {}).get("thema") or "").strip() or None,
            },
            "pdfSnapshots": pdf_snapshots,
            "job": {
                "provider": "local_background_task",
                "jobName": None,
                "region": None,
                "operationName": None,
                "executionName": None,
                "launchedAt": None,
                "launchError": None,
            },
        },
    )
    return run_id, {"project": project, "kapitel": kapitel, "pdfSnapshots": pdf_snapshots}


async def _main_async(args: argparse.Namespace) -> int:
    user_id = str(args.user_id or "").strip()
    project_id = str(args.project_id or "").strip()
    kapitel_id = str(args.kapitel_id or "").strip()
    pdf_ids = [str(pdf_id or "").strip() for pdf_id in (args.pdf_id or []) if str(pdf_id or "").strip()]
    if not user_id or not project_id or not kapitel_id or not pdf_ids:
        raise ValueError("user-id, project-id, kapitel-id, and at least one --pdf-id are required")

    run_id, snapshots = await _build_run_payload(user_id, project_id, kapitel_id, pdf_ids)
    print(
        json.dumps(
            {
                "runId": run_id,
                "userId": user_id,
                "projectId": project_id,
                "kapitelId": kapitel_id,
                "pdfIds": pdf_ids,
                "pdfFilenames": [row.get("filename") for row in snapshots.get("pdfSnapshots") or []],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    await run_quellen_finder_pdf_scan_job_from_run_doc(user_id=user_id, projekt_id=project_id, run_id=run_id)
    data = QuellenFinderFirestoreService().get_run(user_id=user_id, projekt_id=project_id, run_id=run_id)
    print(
        json.dumps(
            {
                "runId": run_id,
                "status": data.get("status"),
                "errorMessage": data.get("errorMessage"),
                "hadPartialFailures": data.get("hadPartialFailures"),
                "resultCount": data.get("resultCount"),
                "summary": data.get("summary"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and execute a local PDF-scan smoke run against an existing project.")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--kapitel-id", required=True)
    parser.add_argument("--pdf-id", action="append", default=[], help="Repeat for each selected PDF id.")
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
