from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from fastapi import HTTPException

from services.firebase_service import firebase_service
from services.quellen_finder_firestore_service import QuellenFinderFirestoreService
from services.quellen_finder_pdf_extract_pipeline import (
    extract_section_by_locator,
    rebuild_phase_c_block_index,
)
from services.quellen_finder_pdf_scan_job import _download_pdf_from_firebase_storage

logger = logging.getLogger(__name__)


def _as_opt_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        text = str(value).strip()
    except Exception:
        return None
    return text or None


def _as_str(value: Any) -> str:
    return _as_opt_str(value) or ""


def extract_quellen_finder_pdf_section(
    *,
    user_id: str,
    projekt_id: str,
    run_id: str,
    pdf_doc_id: str,
    section_doc_id: str,
) -> dict:
    fs = QuellenFinderFirestoreService()

    run_ref = fs.run_ref(user_id, projekt_id, run_id)
    run_snap = run_ref.get()
    if not getattr(run_snap, "exists", False):
        raise HTTPException(status_code=404, detail="Research run not found.")
    run = run_snap.to_dict() or {}
    if str(run.get("kind") or "") != "pdf_scan":
        raise HTTPException(status_code=400, detail="Run is not a PDF scan run.")

    pdf_doc_snap = run_ref.collection("pdfScanDocs").document(str(pdf_doc_id)).get()
    if not getattr(pdf_doc_snap, "exists", False):
        raise HTTPException(status_code=404, detail="PDF summary doc not found.")
    pdf_summary_doc = pdf_doc_snap.to_dict() or {}

    section_snap = run_ref.collection("pdfScanSections").document(str(section_doc_id)).get()
    if not getattr(section_snap, "exists", False):
        raise HTTPException(status_code=404, detail="PDF section doc not found.")
    section_doc = section_snap.to_dict() or {}

    if str(section_doc.get("docId") or "") != str(pdf_doc_id):
        raise HTTPException(status_code=400, detail="Section does not belong to the requested PDF doc.")

    pdf_id = _as_str(section_doc.get("pdfId"))
    if not pdf_id:
        raise HTTPException(status_code=400, detail="Section is missing pdfId.")

    pdf_snap = (
        firebase_service.db.collection("users")
        .document(str(user_id))
        .collection("projects")
        .document(str(projekt_id))
        .collection("pdfs")
        .document(str(pdf_id))
        .get()
    )
    if not getattr(pdf_snap, "exists", False):
        raise HTTPException(status_code=404, detail="PDF not found in project library.")
    pdf_doc = pdf_snap.to_dict() or {}

    storage_path = _as_str(pdf_doc.get("storagePath"))
    filename = _as_str(pdf_doc.get("filename")) or _as_str(section_doc.get("pdfFilename")) or "document.pdf"
    expected_size = None
    size_raw = pdf_doc.get("size")
    if isinstance(size_raw, (int, float)) and int(size_raw) > 0:
        expected_size = int(size_raw)

    locator = {
        "headingAnchor": section_doc.get("headingAnchor") if isinstance(section_doc.get("headingAnchor"), dict) else {},
        "span": section_doc.get("span") if isinstance(section_doc.get("span"), dict) else {},
    }
    section_title = _as_opt_str(section_doc.get("title")) or _as_opt_str(pdf_summary_doc.get("topSectionTitle"))

    logger.info(
        "QF pdf extract start | run_id=%s projekt_id=%s pdf_doc_id=%s section_doc_id=%s pdf_id=%s storage_path=%s",
        run_id,
        projekt_id,
        pdf_doc_id,
        section_doc_id,
        pdf_id,
        storage_path or "(missing)",
    )

    if not storage_path:
        return {
            "pdf": {"id": pdf_id, "filename": filename, "storage_path": None, "size": expected_size},
            "hit": {"locator_hint": section_title},
            "extract": {"ok": False, "reason": "missing_storage_path"},
            "meta": {"pdf_doc_id": pdf_doc_id, "section_doc_id": section_doc_id},
        }

    with tempfile.TemporaryDirectory(prefix="qf_pdf_extract_") as tmpdir:
        dest_path = Path(tmpdir) / "document.pdf"
        t0 = time.time()
        try:
            _download_pdf_from_firebase_storage(
                storage_path=storage_path,
                dest_path=dest_path,
                expected_size=expected_size,
            )
        except Exception as exc:
            logger.warning(
                "QF pdf extract download failed | run_id=%s pdf_id=%s storage_path=%s err=%s",
                run_id,
                pdf_id,
                storage_path,
                exc,
            )
            return {
                "pdf": {"id": pdf_id, "filename": filename, "storage_path": storage_path, "size": expected_size},
                "hit": {"locator_hint": section_title},
                "extract": {"ok": False, "reason": "download_failed", "detail": str(exc)[:500]},
                "meta": {"pdf_doc_id": pdf_doc_id, "section_doc_id": section_doc_id},
            }
        download_s = float(time.time() - t0)

        try:
            block_index = rebuild_phase_c_block_index(dest_path)
            with fitz.open(str(dest_path)) as doc:
                t1 = time.time()
                result = extract_section_by_locator(
                    doc,
                    locator=locator,
                    block_index=block_index,
                    section_title=section_title,
                )
                extract_s = float(time.time() - t1)

                pages = (result.get("highlights") or {}).get("pages") or []
                total_rects = int(sum(len(page.get("rects") or []) for page in pages))
                logger.info(
                    "QF pdf extract done | run_id=%s pdf_id=%s ok=%s method=%s download_s=%.2f extract_s=%.2f pages=%s rects=%s",
                    run_id,
                    pdf_id,
                    bool(result.get("ok")),
                    str(result.get("method") or ""),
                    download_s,
                    extract_s,
                    int(len(pages)),
                    total_rects,
                )
                return {
                    "pdf": {
                        "id": pdf_id,
                        "filename": filename,
                        "storage_path": storage_path,
                        "size": expected_size,
                    },
                    "hit": {"locator_hint": section_title},
                    "extract": result,
                    "meta": {
                        "pdf_doc_id": pdf_doc_id,
                        "section_doc_id": section_doc_id,
                        "page_count": int(doc.page_count),
                        "download_s": float(download_s),
                        "extract_s": float(extract_s),
                    },
                }
        except Exception as exc:
            logger.exception("QF pdf extract failed | run_id=%s pdf_id=%s", run_id, pdf_id)
            return {
                "pdf": {"id": pdf_id, "filename": filename, "storage_path": storage_path, "size": expected_size},
                "hit": {"locator_hint": section_title},
                "extract": {"ok": False, "reason": "extract_failed", "detail": str(exc)[:500]},
                "meta": {
                    "pdf_doc_id": pdf_doc_id,
                    "section_doc_id": section_doc_id,
                    "download_s": float(download_s),
                },
            }
