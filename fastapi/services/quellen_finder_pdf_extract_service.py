from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Literal

import fitz  # PyMuPDF
from fastapi import HTTPException

from services.firebase_service import firebase_service
from services.quellen_finder_firestore_service import QuellenFinderFirestoreService
from services.quellen_finder_pdf_extract_pipeline import build_heading_index_strict, extract_section_by_hit
from services.quellen_finder_pdf_scan_job import _download_pdf_from_firebase_storage

logger = logging.getLogger(__name__)

PdfExtractStage = Literal["stage2", "stage3"]


def _as_opt_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        s = str(value).strip()
    except Exception:
        return None
    return s or None


def _as_str(value: Any) -> str:
    return _as_opt_str(value) or ""


def extract_quellen_finder_pdf_section(
    *,
    user_id: str,
    projekt_id: str,
    run_id: str,
    stage: PdfExtractStage,
    doc_id: str,
) -> dict:
    fs = QuellenFinderFirestoreService()

    run_ref = fs.run_ref(user_id, projekt_id, run_id)
    run_snap = run_ref.get()
    if not getattr(run_snap, "exists", False):
        raise HTTPException(status_code=404, detail="Research run not found.")
    run = run_snap.to_dict() or {}
    if str(run.get("kind") or "") != "pdf_scan":
        raise HTTPException(status_code=400, detail="Run is not a PDF scan run.")

    stage_col = "pdfStage2" if stage == "stage2" else "pdfStage3"
    stage_snap = run_ref.collection(stage_col).document(str(doc_id)).get()
    if not getattr(stage_snap, "exists", False):
        raise HTTPException(status_code=404, detail=f"{stage_col} doc not found.")
    stage_doc = stage_snap.to_dict() or {}

    pdf_id = _as_str(stage_doc.get("pdfId"))
    if not pdf_id:
        return {
            "pdf": None,
            "hit": {
                "anchor": _as_opt_str(stage_doc.get("anchor")),
                "anchor_alt": _as_opt_str(stage_doc.get("anchorAlt")),
                "locator_hint": _as_opt_str(stage_doc.get("locatorHint") if stage == "stage2" else stage_doc.get("heading")),
            },
            "extract": {"ok": False, "reason": "missing_pdf_id"},
            "meta": {"stage": stage, "stage_col": stage_col},
        }

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
    filename = _as_str(pdf_doc.get("filename")) or _as_str(stage_doc.get("pdfLabel")) or "document.pdf"
    expected_size = None
    try:
        size_raw = pdf_doc.get("size")
        if isinstance(size_raw, (int, float)) and int(size_raw) > 0:
            expected_size = int(size_raw)
    except Exception:
        expected_size = None

    hit = {
        "anchor": _as_str(stage_doc.get("anchor")),
        "anchor_alt": _as_str(stage_doc.get("anchorAlt")),
        "locator_hint": _as_opt_str(stage_doc.get("locatorHint") if stage == "stage2" else stage_doc.get("heading")),
    }

    logger.info(
        "QF pdf extract start | run_id=%s projekt_id=%s stage=%s doc_id=%s pdf_id=%s storage_path=%s",
        run_id,
        projekt_id,
        stage,
        doc_id,
        pdf_id,
        storage_path or "(missing)",
    )

    if not storage_path:
        return {
            "pdf": {"id": pdf_id, "filename": filename, "storage_path": None, "size": expected_size},
            "hit": hit,
            "extract": {"ok": False, "reason": "missing_storage_path"},
            "meta": {"stage": stage, "stage_col": stage_col},
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
                "hit": hit,
                "extract": {"ok": False, "reason": "download_failed", "detail": str(exc)[:500]},
                "meta": {"stage": stage, "stage_col": stage_col},
            }
        download_s = float(time.time() - t0)

        try:
            with fitz.open(str(dest_path)) as doc:
                headings, body_size = build_heading_index_strict(doc)

                t1 = time.time()
                result = extract_section_by_hit(doc, hit, headings)
                extract_s = float(time.time() - t1)

                text_len = len(str(result.get("text") or ""))
                result = dict(result)
                result.pop("text", None)

                pages = (result.get("highlights") or {}).get("pages") or []
                total_rects = 0
                try:
                    total_rects = int(sum(len(p.get("rects") or []) for p in pages))
                except Exception:
                    total_rects = 0

                logger.info(
                    "QF pdf extract done | run_id=%s pdf_id=%s ok=%s method=%s download_s=%.2f extract_s=%.2f headings=%s pages=%s rects=%s text_len=%s",
                    run_id,
                    pdf_id,
                    bool(result.get("ok")),
                    str(result.get("method") or ""),
                    download_s,
                    extract_s,
                    int(len(headings)),
                    int(len(pages)),
                    int(total_rects),
                    int(text_len),
                )

                return {
                    "pdf": {
                        "id": pdf_id,
                        "filename": filename,
                        "storage_path": storage_path,
                        "size": expected_size,
                    },
                    "hit": hit,
                    "extract": result,
                    "meta": {
                        "stage": stage,
                        "stage_col": stage_col,
                        "page_count": int(doc.page_count),
                        "body_font_size": float(body_size),
                        "strict_headings": int(len(headings)),
                        "download_s": float(download_s),
                        "extract_s": float(extract_s),
                    },
                }
        except Exception as exc:
            logger.exception("QF pdf extract failed | run_id=%s pdf_id=%s", run_id, pdf_id)
            return {
                "pdf": {"id": pdf_id, "filename": filename, "storage_path": storage_path, "size": expected_size},
                "hit": hit,
                "extract": {"ok": False, "reason": "extract_failed", "detail": str(exc)[:500]},
                "meta": {"stage": stage, "stage_col": stage_col, "download_s": float(download_s)},
            }

