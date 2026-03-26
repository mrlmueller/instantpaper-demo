from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

FASTAPI_ROOT = Path(__file__).resolve().parents[1]
if str(FASTAPI_ROOT) not in sys.path:
    sys.path.insert(0, str(FASTAPI_ROOT))

from firebase_admin import storage  # noqa: E402

from services.firebase_service import firebase_service  # noqa: E402
from services.quellen_finder_firestore_service import QuellenFinderFirestoreService  # noqa: E402


def _as_str(value: Any) -> str:
    return str(value or "").strip()


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=_json_default)


def _dump_jsonl(rows: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(row, ensure_ascii=False, default=_json_default) for row in rows) + ("\n" if rows else "")


def _backup_run(
    *,
    user_id: str,
    projekt_id: str,
    run_id: str,
    run_data: dict[str, Any],
    flat_docs: list[dict[str, Any]],
    flat_sections: list[dict[str, Any]],
) -> list[str]:
    bucket_name = _as_str(os.getenv("FIREBASE_STORAGE_BUCKET")) or _as_str(os.getenv("PDF_SCAN_ARTIFACT_BUCKET"))
    if not bucket_name:
        raise RuntimeError("FIREBASE_STORAGE_BUCKET or PDF_SCAN_ARTIFACT_BUCKET must be configured for backups.")
    bucket = storage.bucket(bucket_name)
    prefix = f"pdf-scan-runs/{user_id}/{projekt_id}/{run_id}/migration-backup"
    uploads = {
        f"{prefix}/run_doc.json": _dump_json(run_data),
        f"{prefix}/pdfScanDocs.jsonl": _dump_jsonl(flat_docs),
        f"{prefix}/pdfScanSections.jsonl": _dump_jsonl(flat_sections),
    }
    uris: list[str] = []
    for object_name, payload in uploads.items():
        blob = bucket.blob(object_name)
        blob.upload_from_string(payload, content_type="application/json")
        uris.append(f"gs://{bucket_name}/{object_name}")
    return uris


def _list_docs(col_ref: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for snap in col_ref.stream():
        if snap is None or not getattr(snap, "exists", False):
            continue
        data = snap.to_dict() or {}
        if not isinstance(data, dict):
            data = {}
        rows.append({"id": str(snap.id), **data})
    return rows


def _build_v2_payload(
    *,
    run_data: dict[str, Any],
    flat_docs: list[dict[str, Any]],
    flat_sections: list[dict[str, Any]],
) -> dict[str, Any]:
    kapitel_ids = [_as_str(v) for v in list(run_data.get("kapitelIds") or []) if _as_str(v)]
    if len(kapitel_ids) != 1:
        raise RuntimeError("Only historical single-chapter PDF scan runs can be migrated.")
    chapter_id = kapitel_ids[0]

    kapitel_snapshots = [row for row in list(run_data.get("kapitelSnapshots") or []) if isinstance(row, dict)]
    chapter_snapshot = next((row for row in kapitel_snapshots if _as_str(row.get("id")) == chapter_id), {})
    chapter_title = _as_str(chapter_snapshot.get("title") or chapter_snapshot.get("ueberschrift"))

    chapter_doc_docs: list[tuple[str, dict[str, Any]]] = []
    chapter_section_docs: list[tuple[str, dict[str, Any]]] = []
    aggregate_doc_docs: list[tuple[str, dict[str, Any]]] = []

    useful_pdf_count_any_chapter = 0
    useful_chapter_pair_count = 0
    total_visible_section_count = len(flat_sections)

    for index, row in enumerate(flat_docs, start=1):
        doc_id = _as_str(row.get("id") or row.get("docId"))
        if not doc_id:
            raise RuntimeError("Flat pdfScanDocs row is missing id/docId.")
        payload = dict(row)
        payload.pop("id", None)
        payload.update(
            {
                "chapterId": chapter_id,
                "chapterOrder": 0,
                "chapterTitle": chapter_title or None,
                "chapterRank": index,
            }
        )
        chapter_doc_docs.append((doc_id, payload))

        has_useful = bool(row.get("hasUsefulInformation"))
        useful_for_chapters = [chapter_id] if has_useful else []
        if has_useful:
            useful_pdf_count_any_chapter += 1
            useful_chapter_pair_count += 1
        aggregate_doc_docs.append(
            (
                doc_id,
                {
                    "pdfId": row.get("pdfId"),
                    "docId": row.get("docId") or doc_id,
                    "pdfFilename": row.get("pdfFilename"),
                    "pdfLabel": row.get("pdfLabel"),
                    "docTitle": row.get("docTitle"),
                    "usefulForChapters": useful_for_chapters,
                    "usefulChapterCount": int(len(useful_for_chapters)),
                    "bestChapterMatch": {
                        "chapterId": chapter_id,
                        "docMatchProbability": row.get("docMatchProbability"),
                        "topSectionScore": row.get("topSectionScore"),
                        "topSectionTitle": row.get("topSectionTitle"),
                    }
                    if row.get("docId") or row.get("topSectionTitle")
                    else None,
                    "perChapter": {
                        chapter_id: {
                            "hasUsefulInformation": has_useful,
                            "docMatchProbability": row.get("docMatchProbability"),
                            "topSectionScore": row.get("topSectionScore"),
                            "topSectionTitle": row.get("topSectionTitle"),
                            "abstentionReason": None if has_useful else "migrated_legacy_single_chapter_run",
                        }
                    },
                },
            )
        )

    for row in flat_sections:
        section_doc_id = _as_str(row.get("id") or row.get("sectionId"))
        if not section_doc_id:
            raise RuntimeError("Flat pdfScanSections row is missing id/sectionId.")
        payload = dict(row)
        payload.pop("id", None)
        payload.update(
            {
                "chapterId": chapter_id,
                "chapterOrder": 0,
                "chapterTitle": chapter_title or None,
            }
        )
        chapter_section_docs.append((section_doc_id, payload))

    root_payload = {
        "pdfScanSchemaVersion": 2,
        "pdfScanMode": "chapter_matrix",
        "chapterInputMode": "single",
        "chapterInputSnapshots": [
            {
                "chapterId": chapter_id,
                "chapterOrder": 0,
                "chapterTitle": chapter_title or None,
                "chapterSpecText": _as_str(chapter_snapshot.get("thema")) or None,
            }
        ],
        "pdfScanSummary": {
            "chapterCount": 1,
            "completedChapterCount": 1 if _as_str(run_data.get("status")) == "success" else 0,
            "failedChapterCount": 0,
            "documentCount": int(len(flat_docs)),
            "usefulPdfCountAnyChapter": int(useful_pdf_count_any_chapter),
            "usefulChapterPairCount": int(useful_chapter_pair_count),
            "multiChapterSectionCount": 0,
            "totalVisibleSectionCount": int(total_visible_section_count),
            "aggregateStatus": "partial_success" if bool(run_data.get("hadPartialFailures")) else (_as_str(run_data.get("status")) or "success"),
        },
        "pdfScanCounts": {
            "aggregateDocCount": int(len(flat_docs)),
            "aggregateSectionCount": 0,
            "chapterDocCount": int(len(flat_docs)),
            "chapterSectionCount": int(len(flat_sections)),
        },
        "pdfScanDisplay": {
            "runLabel": f"1 Kapitel • {len(list(run_data.get('pdfIds') or []))} PDFs",
            "chapterPreview": [
                {
                    "chapterId": chapter_id,
                    "nummer": chapter_snapshot.get("nummer"),
                    "title": chapter_snapshot.get("title") or chapter_snapshot.get("ueberschrift"),
                }
            ],
            "chapterCountLabel": "1 Kapitel",
        },
        "pdfScanMigration": {
            "migratedFromSchemaVersion": 1,
            "migratedToSchemaVersion": 2,
            "migrationStatus": "migrated",
            "migrationScriptVersion": "2026-03-25-v1",
            "migratedAt": SERVER_TIMESTAMP,
            "migratedBy": _as_str(os.getenv("USERNAME") or os.getenv("USER")) or "migration_script",
            "sourceFlatDocCount": int(len(flat_docs)),
            "sourceFlatSectionCount": int(len(flat_sections)),
            "targetChapterDocCount": int(len(flat_docs)),
            "targetChapterSectionCount": int(len(flat_sections)),
            "targetAggregateDocCount": int(len(flat_docs)),
        },
    }
    chapter_doc = {
        "chapterId": chapter_id,
        "chapterOrder": 0,
        "kapitelSnapshot": chapter_snapshot,
        "status": "success" if _as_str(run_data.get("status")) == "success" else (_as_str(run_data.get("status")) or "success"),
        "errorMessage": run_data.get("errorMessage"),
        "progress": {"stage": "done", "message": "Migrated from legacy run"},
        "pipelineStages": run_data.get("pipelineStages"),
        "startedAt": run_data.get("startedAt"),
        "finishedAt": run_data.get("finishedAt"),
        "usefulPdfCount": int(useful_pdf_count_any_chapter),
        "documentCount": int(len(flat_docs)),
        "visibleSectionCount": int(total_visible_section_count),
        "topSectionCount": int(min(10, len(flat_sections))),
        "outputPath": None,
        "docFeaturesPath": None,
        "sectionScoresPath": None,
        "createdAt": run_data.get("createdAt") or SERVER_TIMESTAMP,
        "updatedAt": SERVER_TIMESTAMP,
    }

    return {
        "root_payload": root_payload,
        "chapter_docs": [(chapter_id, chapter_doc)],
        "chapter_doc_docs": {chapter_id: chapter_doc_docs},
        "chapter_section_docs": {chapter_id: chapter_section_docs},
        "aggregate_doc_docs": aggregate_doc_docs,
        "aggregate_section_docs": [],
        "chapter_id": chapter_id,
        "counts": {
            "sourceFlatDocCount": len(flat_docs),
            "sourceFlatSectionCount": len(flat_sections),
            "targetChapterDocCount": len(chapter_doc_docs),
            "targetChapterSectionCount": len(chapter_section_docs),
            "targetAggregateDocCount": len(aggregate_doc_docs),
        },
    }


def _verify_migration(
    *,
    fs: QuellenFinderFirestoreService,
    user_id: str,
    projekt_id: str,
    run_id: str,
    chapter_id: str,
    expected_counts: dict[str, int],
) -> None:
    run_ref = fs.run_ref(user_id, projekt_id, run_id)
    target_chapter_doc_count = sum(1 for _ in run_ref.collection("pdfScanChapters").document(chapter_id).collection("docs").stream())
    target_chapter_section_count = sum(1 for _ in run_ref.collection("pdfScanChapters").document(chapter_id).collection("sections").stream())
    target_aggregate_doc_count = sum(1 for _ in run_ref.collection("pdfScanAggregateDocs").stream())
    chapter_snap = run_ref.collection("pdfScanChapters").document(chapter_id).get()
    if not getattr(chapter_snap, "exists", False):
        raise RuntimeError("Verification failed: target chapter doc missing.")
    if int(expected_counts.get("sourceFlatDocCount") or 0) != int(target_chapter_doc_count):
        raise RuntimeError("Verification failed: source flat doc count != target chapter doc count.")
    if int(expected_counts.get("sourceFlatSectionCount") or 0) != int(target_chapter_section_count):
        raise RuntimeError("Verification failed: source flat section count != target chapter section count.")
    if int(expected_counts.get("sourceFlatDocCount") or 0) != int(target_aggregate_doc_count):
        raise RuntimeError("Verification failed: aggregate doc count != source flat doc count.")


def iter_candidate_runs(
    *,
    fs: QuellenFinderFirestoreService,
    user_id: str,
    projekt_id: str,
    run_id: str | None,
    limit: int | None,
    force: bool,
) -> list[tuple[str, dict[str, Any]]]:
    runs = []
    if run_id:
        data = fs.get_run(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        runs.append((run_id, data))
    else:
        for snap in fs.runs_col(user_id, projekt_id).stream():
            if snap is None or not getattr(snap, "exists", False):
                continue
            data = snap.to_dict() or {}
            if not isinstance(data, dict):
                data = {}
            runs.append((str(snap.id), data))
    candidates: list[tuple[str, dict[str, Any]]] = []
    for candidate_run_id, data in runs:
        if _as_str(data.get("kind")) != "pdf_scan":
            continue
        schema_version = int(data.get("pdfScanSchemaVersion") or 0)
        status = _as_str(data.get("status"))
        if not force and schema_version >= 2:
            continue
        if not force and status not in {"success", "error", "cancelled"}:
            continue
        candidates.append((candidate_run_id, data))
    candidates.sort(key=lambda item: _as_str(item[0]))
    if isinstance(limit, int) and limit > 0:
        candidates = candidates[:limit]
    return candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate legacy flat PDF-scan runs to schema v2.")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write-v2", action="store_true")
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--delete-legacy", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fs = QuellenFinderFirestoreService()
    user_id = _as_str(args.user_id)
    projekt_id = _as_str(args.project_id)
    run_id = _as_str(args.run_id) or None
    limit = int(args.limit) if int(args.limit or 0) > 0 else None

    candidates = iter_candidate_runs(
        fs=fs,
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        limit=limit,
        force=bool(args.force),
    )
    print(_dump_json({"candidateCount": len(candidates), "runIds": [run_id for run_id, _ in candidates]}))
    if args.dry_run and not args.write_v2:
        return 0

    for candidate_run_id, run_data in candidates:
        run_ref = fs.run_ref(user_id, projekt_id, candidate_run_id)
        flat_docs = _list_docs(run_ref.collection("pdfScanDocs"))
        flat_sections = _list_docs(run_ref.collection("pdfScanSections"))
        payload = _build_v2_payload(
            run_data=run_data,
            flat_docs=flat_docs,
            flat_sections=flat_sections,
        )

        backup_uris: list[str] = []
        if args.backup:
            backup_uris = _backup_run(
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=candidate_run_id,
                run_data=run_data,
                flat_docs=flat_docs,
                flat_sections=flat_sections,
            )

        if args.write_v2:
            fs.replace_pdf_scan_v2_results(
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=candidate_run_id,
                root_payload=dict(payload.get("root_payload") or {}),
                chapter_docs=list(payload.get("chapter_docs") or []),
                chapter_doc_docs=dict(payload.get("chapter_doc_docs") or {}),
                chapter_section_docs=dict(payload.get("chapter_section_docs") or {}),
                aggregate_doc_docs=list(payload.get("aggregate_doc_docs") or []),
                aggregate_section_docs=list(payload.get("aggregate_section_docs") or []),
            )
            if backup_uris:
                run_ref.set(
                    {
                        "pdfScanMigration": {
                            "backupUris": backup_uris,
                        }
                    },
                    merge=True,
                )
            _verify_migration(
                fs=fs,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=candidate_run_id,
                chapter_id=str(payload.get("chapter_id") or ""),
                expected_counts=dict(payload.get("counts") or {}),
            )
            if args.delete_legacy:
                fs.clear_subcollection(user_id=user_id, projekt_id=projekt_id, run_id=candidate_run_id, name="pdfScanDocs")
                fs.clear_subcollection(user_id=user_id, projekt_id=projekt_id, run_id=candidate_run_id, name="pdfScanSections")
                run_ref.set(
                    {
                        "chapterInputSnapshot": firestore.DELETE_FIELD,
                        "pdfScanDocCount": firestore.DELETE_FIELD,
                        "pdfScanSectionCount": firestore.DELETE_FIELD,
                        "usefulPdfCount": firestore.DELETE_FIELD,
                        "finalScoreCol": firestore.DELETE_FIELD,
                    },
                    merge=True,
                )

        print(
            _dump_json(
                {
                    "runId": candidate_run_id,
                    "chapterId": payload.get("chapter_id"),
                    "sourceFlatDocCount": len(flat_docs),
                    "sourceFlatSectionCount": len(flat_sections),
                    "backupUris": backup_uris,
                    "wroteV2": bool(args.write_v2),
                    "deletedLegacy": bool(args.delete_legacy and args.write_v2),
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
