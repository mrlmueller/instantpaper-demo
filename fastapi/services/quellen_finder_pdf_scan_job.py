from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException
from firebase_admin import storage
from google.api_core.exceptions import DeadlineExceeded, GoogleAPICallError, NotFound, RetryError
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.cost_service import TokenUsage, get_cost_service
from services.credits_service import get_credits_service
from services.firebase_service import firebase_service
from services.openai_budget_service import get_openai_budget_service
from services.quellen_finder_firestore_service import QuellenFinderFirestoreService
from utils.runtime_paths import resolve_fastapi_root, resolve_pdf_scan_pipeline_script
from utils.config import config

logger = logging.getLogger(__name__)

FASTAPI_ROOT = resolve_fastapi_root(__file__)
PIPELINE_CHILD_SCRIPT = resolve_pdf_scan_pipeline_script(__file__)
PIPELINE_EVENT_PREFIX = "PDF_SCAN_EVENT\t"
VISIBLE_SCORE_THRESHOLD = 5.0
PDF_SCAN_MAX_PDF_BYTES = max(1, int(getattr(config, "PDF_SCAN_MAX_PDF_BYTES", 50 * 1024 * 1024) or 50 * 1024 * 1024))
PDF_SCAN_MAX_PDF_MB = max(1, (PDF_SCAN_MAX_PDF_BYTES + (1024 * 1024) - 1) // (1024 * 1024))
FINALIZATION_TRANSIENT_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
    DeadlineExceeded,
    RetryError,
    GoogleAPICallError,
)
PDF_SCAN_STAGE_LABELS = {
    "prepare_inputs": "Preparing run inputs",
    "download_pdfs": "Downloading selected PDFs",
    "phase_a": "Building pipeline manifest",
    "phase_b": "Parsing PDF structure",
    "phase_c": "Normalizing sections",
    "phase_d": "Planning retrieval",
    "phase_e": "Retrieving candidate sections",
    "phase_f": "Reranking candidate sections",
    "phase_g": "Scoring final sections",
    "persist_results": "Saving UI results",
}


class PdfScanRunCancelled(RuntimeError):
    """Raised when a PDF scan run is cancelled by the user."""


class PdfScanRunTerminated(RuntimeError):
    """Raised when a PDF scan worker is terminated externally."""


def _exception_message(exc: BaseException, *, fallback: str = "Unknown error") -> str:
    text = str(exc or "").strip()
    if text:
        return text
    if isinstance(exc, NotImplementedError):
        return "Local PDF scan subprocesses are not supported by the current Windows event loop."
    name = type(exc).__name__.strip()
    return name or fallback


def _as_str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    try:
        text = str(value).strip()
    except Exception:
        return None
    return text or None


def _as_int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _trim_text(value: Any, *, max_chars: int = 5000) -> str | None:
    text = _as_str_or_none(value)
    if not text:
        return None
    if len(text) <= int(max_chars):
        return text
    return text[: max(0, int(max_chars) - 1)].rstrip() + "..."


def _termination_message(message_getter: Callable[[], str | None] | None = None) -> str:
    text = None
    if callable(message_getter):
        with contextlib.suppress(Exception):
            text = message_getter()
    trimmed = _trim_text(text, max_chars=500)
    return trimmed or "PDF scan worker termination requested."


def _is_mupdf_noise_line(text: Any) -> bool:
    raw = _as_str_or_none(text) or ""
    normalized = raw.lstrip()
    return normalized.startswith("MuPDF error:") or normalized.startswith("MuPDF warning:")


def _remember_suppressed_child_line(state: dict[str, Any], text: str) -> None:
    suppressed = state.setdefault("suppressed_child_lines", {})
    key = _trim_text(text, max_chars=320) or "MuPDF parser message"
    suppressed[key] = int(suppressed.get(key) or 0) + 1


def _flush_suppressed_child_lines(state: dict[str, Any]) -> None:
    suppressed = state.get("suppressed_child_lines") or {}
    if not suppressed:
        return
    total = sum(int(count) for count in suppressed.values())
    samples = ", ".join(f"{count}x {sample}" for sample, count in list(suppressed.items())[:3])
    logger.info("PDF scan child suppressed %s MuPDF parser line(s)%s", total, f": {samples}" if samples else ".")
    suppressed.clear()


def _normalize_abs_path(value: Any) -> str:
    raw = _as_str_or_none(value)
    if not raw:
        return ""
    try:
        return str(Path(raw).resolve()).lower()
    except Exception:
        return str(raw).strip().lower()


def _slugify_filename(name: str) -> str:
    base = re.sub(r"[^\w.\- ]+", "_", str(name or "").strip(), flags=re.UNICODE).strip(" ._")
    return base or "document.pdf"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _read_pdf_scan_api_usage(run_dir: Path) -> dict[str, Any]:
    metrics_path = run_dir / "metrics.json"
    api_calls_path = run_dir / "api_calls.jsonl"

    totals = {
        "call_count": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }
    by_stage: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "call_count": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
        }
    )

    try:
        for row in _read_jsonl(api_calls_path):
            stage = _as_str_or_none(row.get("stage")) or "unknown"
            input_tokens = max(int(row.get("input_tokens") or 0), 0)
            cached_input_tokens = max(int(row.get("cached_input_tokens") or 0), 0)
            output_tokens = max(int(row.get("output_tokens") or 0), 0)
            total_tokens = max(int(row.get("total_tokens") or (input_tokens + output_tokens)), 0)
            cost_usd = max(_as_float(row.get("cost_usd"), 0.0), 0.0)

            totals["call_count"] += 1
            totals["input_tokens"] += input_tokens
            totals["cached_input_tokens"] += cached_input_tokens
            totals["output_tokens"] += output_tokens
            totals["total_tokens"] += total_tokens
            totals["cost_usd"] = round(float(totals["cost_usd"]) + float(cost_usd), 10)

            stage_totals = by_stage[stage]
            stage_totals["call_count"] += 1
            stage_totals["input_tokens"] += input_tokens
            stage_totals["cached_input_tokens"] += cached_input_tokens
            stage_totals["output_tokens"] += output_tokens
            stage_totals["total_tokens"] += total_tokens
            stage_totals["cost_usd"] = round(float(stage_totals["cost_usd"]) + float(cost_usd), 10)
    except Exception:
        pass

    if totals["call_count"] <= 0 and metrics_path.exists():
        try:
            metrics = _read_json(metrics_path)
            summary = metrics.get("api_usage_summary") if isinstance(metrics, dict) else {}
            if isinstance(summary, dict):
                totals = {
                    "call_count": max(int(summary.get("call_count") or 0), 0),
                    "input_tokens": max(int(summary.get("input_tokens") or 0), 0),
                    "cached_input_tokens": max(int(summary.get("cached_input_tokens") or 0), 0),
                    "output_tokens": max(int(summary.get("output_tokens") or 0), 0),
                    "total_tokens": max(int(summary.get("total_tokens") or 0), 0),
                    "cost_usd": round(max(_as_float(summary.get("cost_usd"), 0.0), 0.0), 10),
                }
        except Exception:
            pass

    return {
        **totals,
        "by_stage": {str(stage): dict(values) for stage, values in by_stage.items()},
    }


def _resolve_pipeline_run_dir(raw_run_dir: Any, *, expected_root: Path) -> Path:
    run_dir_text = _as_str_or_none(raw_run_dir)
    if not run_dir_text:
        raise RuntimeError("Standalone PDF scan pipeline did not report a run directory.")

    run_dir = Path(run_dir_text).resolve()
    expected_root_resolved = Path(expected_root).resolve()
    try:
        run_dir.relative_to(expected_root_resolved)
    except ValueError as exc:
        raise RuntimeError(
            f"Standalone PDF scan pipeline reported an unexpected run directory outside {expected_root_resolved}: {run_dir}"
        ) from exc

    if not run_dir.exists() or not run_dir.is_dir():
        raise RuntimeError(f"Standalone PDF scan pipeline run directory is missing: {run_dir}")

    return run_dir


async def _load_required_run_doc(
    *,
    fs: QuellenFinderFirestoreService,
    user_id: str,
    projekt_id: str,
    run_id: str,
    purpose: str,
) -> dict[str, Any]:
    try:
        data = await asyncio.to_thread(
            fs.get_run,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
        )
    except Exception as exc:
        logger.error(
            "Failed to load PDF scan run doc | purpose=%s user_id=%s projekt_id=%s run_id=%s",
            purpose,
            user_id,
            projekt_id,
            run_id,
            exc_info=True,
        )
        raise RuntimeError(
            f"Failed to load PDF scan run doc for {purpose} (user_id={user_id}, projekt_id={projekt_id}, run_id={run_id})."
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(
            f"PDF scan run doc for {purpose} is invalid (user_id={user_id}, projekt_id={projekt_id}, run_id={run_id})."
        )
    return data


def _candidate_bucket_names(project_id: str, configured: str) -> list[str]:
    names: list[str] = []
    configured = str(configured or "").strip()
    if configured:
        names.append(configured)

    project_id = str(project_id or "").strip()
    if project_id:
        names.extend([f"{project_id}.firebasestorage.app", f"{project_id}.appspot.com"])

    seen = set()
    out: list[str] = []
    for name in names:
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _verify_pdf_file(path: Path, *, expected_size: int | None = None) -> None:
    if not path.exists():
        raise RuntimeError(f"Downloaded file missing: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise RuntimeError(f"Downloaded file is empty: {path}")
    if expected_size is not None and int(expected_size) > 0 and abs(int(size) - int(expected_size)) > 64:
        raise RuntimeError(f"Downloaded file size mismatch (expected ~{expected_size}, got {size}): {path}")
    with path.open("rb") as handle:
        head = handle.read(5)
    if not head.startswith(b"%PDF"):
        raise RuntimeError(f"Downloaded file does not look like a PDF (header={head!r}): {path}")


def _download_pdf_from_firebase_storage(
    *,
    storage_path: str,
    dest_path: Path,
    expected_size: int | None,
    max_retries: int = 6,
    cancel_requested_sync: Callable[[], bool] | None = None,
    termination_requested_sync: Callable[[], bool] | None = None,
    termination_message_getter: Callable[[], str | None] | None = None,
) -> None:
    storage_path = str(storage_path or "").strip().lstrip("/")
    if not storage_path:
        raise ValueError("storage_path is required")
    if expected_size is not None and int(expected_size) > PDF_SCAN_MAX_PDF_BYTES:
        raise ValueError(f"PDF exceeds the {PDF_SCAN_MAX_PDF_MB} MB limit: {storage_path}")

    def raise_if_stop_requested() -> None:
        if callable(termination_requested_sync) and termination_requested_sync():
            raise PdfScanRunTerminated(_termination_message(termination_message_getter))
        if callable(cancel_requested_sync) and cancel_requested_sync():
            raise PdfScanRunCancelled("Cancellation requested.")

    total_timeout_sec = max(10, int(getattr(config, "PDF_SCAN_STORAGE_TOTAL_DOWNLOAD_TIMEOUT_SEC", 240) or 240))
    rpc_timeout_sec = max(10, int(getattr(config, "PDF_SCAN_STORAGE_RPC_TIMEOUT_SEC", 90) or 90))
    deadline = time.monotonic() + float(total_timeout_sec)
    last_exc: Exception | None = None
    for attempt in range(1, int(max_retries) + 1):
        raise_if_stop_requested()
        remaining_total = float(deadline - time.monotonic())
        if remaining_total <= 0:
            raise TimeoutError(f"Timed out downloading {storage_path} from Firebase Storage after {total_timeout_sec}s") from last_exc
        for bucket_name in _candidate_bucket_names(config.FIREBASE_PROJECT_ID, config.FIREBASE_STORAGE_BUCKET):
            raise_if_stop_requested()
            try:
                remaining_total = float(deadline - time.monotonic())
                if remaining_total <= 0:
                    raise TimeoutError(f"Timed out downloading {storage_path} from Firebase Storage after {total_timeout_sec}s")
                timeout_sec = max(10.0, min(float(rpc_timeout_sec), remaining_total))
                bucket = storage.bucket(bucket_name)
                blob = bucket.blob(storage_path)
                if not blob.exists(timeout=timeout_sec):
                    continue
                blob.download_to_filename(str(dest_path), timeout=timeout_sec)
                actual_size = int(dest_path.stat().st_size) if dest_path.exists() else 0
                if actual_size > PDF_SCAN_MAX_PDF_BYTES:
                    raise ValueError(f"PDF exceeds the {PDF_SCAN_MAX_PDF_MB} MB limit: {storage_path}")
                _verify_pdf_file(dest_path, expected_size=expected_size)
                return
            except NotFound as exc:
                last_exc = exc
                with contextlib.suppress(FileNotFoundError):
                    dest_path.unlink()
                continue
            except ValueError:
                with contextlib.suppress(FileNotFoundError):
                    dest_path.unlink()
                raise
            except (DeadlineExceeded, RetryError, TimeoutError) as exc:
                last_exc = exc
                with contextlib.suppress(FileNotFoundError):
                    dest_path.unlink()
                continue
            except Exception as exc:
                last_exc = exc
                with contextlib.suppress(FileNotFoundError):
                    dest_path.unlink()
                continue

        sleep_s = min(8.0, 0.8 * (2 ** (attempt - 1)))
        stop_sleep_at = time.monotonic() + float(sleep_s)
        while time.monotonic() < stop_sleep_at:
            raise_if_stop_requested()
            time.sleep(min(0.25, max(0.05, stop_sleep_at - time.monotonic())))

    raise RuntimeError(f"Failed to download {storage_path} from Firebase Storage") from last_exc


def _build_runtime_settings_from_run_doc(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
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

    pdf_snapshots = data.get("pdfSnapshots")
    pdf_snapshot_rows = [row for row in list(pdf_snapshots or []) if isinstance(row, dict)]
    if not pdf_snapshot_rows:
        raise RuntimeError("Run is missing pdfSnapshots.")

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
        "pdf_snapshots": pdf_snapshot_rows,
    }


def _build_theme_markdown(*, chapter_title: str, chapter_spec_text: str) -> str:
    parts = [str(chapter_title or "").strip(), "", str(chapter_spec_text or "").strip()]
    return "\n".join(parts).strip() + "\n"


def _download_selected_pdfs(
    *,
    pdf_snapshots: list[dict[str, Any]],
    pdf_root: Path,
    on_progress_sync: Any,
    cancel_requested_sync: Callable[[], bool] | None = None,
    termination_requested_sync: Callable[[], bool] | None = None,
    termination_message_getter: Callable[[], str | None] | None = None,
) -> dict[str, dict[str, Any]]:
    pdf_root.mkdir(parents=True, exist_ok=True)
    resolved: dict[str, dict[str, Any]] = {}
    total = len(pdf_snapshots)
    for index, snapshot in enumerate(pdf_snapshots, start=1):
        if callable(termination_requested_sync) and termination_requested_sync():
            raise PdfScanRunTerminated(_termination_message(termination_message_getter))
        if callable(cancel_requested_sync) and cancel_requested_sync():
            raise PdfScanRunCancelled("Cancellation requested.")
        pdf_id = _as_str_or_none(snapshot.get("id"))
        storage_path = _as_str_or_none(snapshot.get("storagePath"))
        filename = _slugify_filename(_as_str_or_none(snapshot.get("filename")) or f"{pdf_id or index}.pdf")
        expected_size = _as_int_or_none(snapshot.get("size"))
        if not pdf_id or not storage_path:
            raise RuntimeError("PDF snapshot is missing id or storagePath.")

        target_dir = pdf_root / pdf_id
        target_dir.mkdir(parents=True, exist_ok=True)
        dest_path = target_dir / filename

        on_progress_sync("download_pdfs", f"Downloading {filename}", current=index - 1, total=total)
        _download_pdf_from_firebase_storage(
            storage_path=storage_path,
            dest_path=dest_path,
            expected_size=expected_size,
            cancel_requested_sync=cancel_requested_sync,
            termination_requested_sync=termination_requested_sync,
            termination_message_getter=termination_message_getter,
        )
        resolved[pdf_id] = {
            **snapshot,
            "localPath": str(dest_path),
        }
        on_progress_sync("download_pdfs", f"Downloaded {filename}", current=index, total=total)
    return resolved


def _build_preview_sections(rows: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[: int(limit)]:
        out.append(
            {
                "sectionId": _as_str_or_none(row.get("section_id")),
                "title": _trim_text(row.get("title"), max_chars=220),
                "pageStart": _as_int_or_none(row.get("page_start")),
                "pageEnd": _as_int_or_none(row.get("page_end")),
                "score0To100": round(_as_float(row.get("score_0_to_100")), 1),
                "scoreBand": _as_str_or_none(row.get("score_band")),
            }
        )
    return out


def _build_persisted_view_docs(
    *,
    run_dir: Path,
    pdf_snapshot_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    manifest_payload = _read_json(run_dir / "pdf_manifest.json")
    phase_b_summary_payload = _read_json(run_dir / "parser" / "phase_b_summary.json") if (run_dir / "parser" / "phase_b_summary.json").exists() else {}
    document_rows = _read_jsonl(run_dir / "normalized" / "documents.jsonl")
    section_score_rows_all = _read_jsonl(run_dir / "final" / "section_scores.jsonl")
    doc_feature_rows = _read_jsonl(run_dir / "final" / "doc_features.jsonl")
    manifest_rows = list((manifest_payload or {}).get("pdfs") or [])
    manifest_by_source_path = {
        _normalize_abs_path(row.get("path")): row
        for row in manifest_rows
        if _normalize_abs_path(row.get("path"))
    }
    document_by_doc_id = {
        _as_str_or_none(row.get("doc_id")) or "": row
        for row in document_rows
        if _as_str_or_none(row.get("doc_id"))
    }
    doc_feature_by_doc_id = {
        _as_str_or_none(row.get("doc_id")) or "": row
        for row in doc_feature_rows
        if _as_str_or_none(row.get("doc_id"))
    }

    visible_section_rows = [
        row
        for row in section_score_rows_all
        if _as_float(row.get("score_0_to_100")) >= float(VISIBLE_SCORE_THRESHOLD)
    ]
    visible_by_doc_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in visible_section_rows:
        doc_id = _as_str_or_none(row.get("doc_id"))
        if doc_id:
            visible_by_doc_id[doc_id].append(row)

    doc_docs: list[tuple[str, dict[str, Any]]] = []
    section_docs: list[tuple[str, dict[str, Any]]] = []
    visible_doc_count = 0
    useful_pdf_count = 0
    phase_b_counts = (((phase_b_summary_payload or {}).get("assessment") or {}).get("counts") or {})
    had_partial_failures = bool(
        _as_int_or_none(phase_b_counts.get("bundle_failure_count"))
        or (
            (_as_int_or_none(phase_b_counts.get("documents_processed")) or 0)
            < (_as_int_or_none(phase_b_counts.get("selected_count")) or 0)
        )
    )

    for doc_id, visible_rows_unsorted in visible_by_doc_id.items():
        document_row = dict(document_by_doc_id.get(doc_id) or {})
        source_path = _normalize_abs_path(document_row.get("source_path"))
        manifest_row = dict(manifest_by_source_path.get(source_path) or {})

        pdf_snapshot = None
        manifest_path = _normalize_abs_path(manifest_row.get("path"))
        if manifest_path:
            for snapshot in pdf_snapshot_by_id.values():
                if _normalize_abs_path(snapshot.get("localPath")) == manifest_path:
                    pdf_snapshot = snapshot
                    break
        if pdf_snapshot is None:
            had_partial_failures = True
            logger.warning("PDF scan persistence could not map doc_id=%s back to a project PDF", doc_id)
            continue

        pdf_id = _as_str_or_none(pdf_snapshot.get("id"))
        if not pdf_id:
            had_partial_failures = True
            continue

        doc_dir = run_dir / "normalized" / doc_id
        all_sections = _read_jsonl(doc_dir / "sections.jsonl")
        section_locator_by_id = {
            _as_str_or_none(row.get("section_id")) or "": row
            for row in all_sections
            if _as_str_or_none(row.get("section_id"))
        }
        visible_rows = sorted(
            list(visible_rows_unsorted),
            key=lambda row: (_as_float(row.get("score_0_to_100")), -(_as_int_or_none(row.get("doc_rank")) or 10_000)),
            reverse=True,
        )
        doc_feature_row = dict(doc_feature_by_doc_id.get(doc_id) or {})

        if bool(doc_feature_row.get("has_useful_information")):
            useful_pdf_count += 1
        visible_doc_count += 1

        summary_payload = {
            "docId": doc_id,
            "pdfId": pdf_id,
            "pdfFilename": _as_str_or_none(pdf_snapshot.get("filename")),
            "pdfLabel": _as_str_or_none(manifest_row.get("label")) or _as_str_or_none(pdf_snapshot.get("filename")) or doc_id,
            "docTitle": _as_str_or_none(document_row.get("title")) or _as_str_or_none(manifest_row.get("label")) or doc_id,
            "pageCount": _as_int_or_none(document_row.get("page_count")),
            "sectionCount": _as_int_or_none(document_row.get("section_count")),
            "acceptedHeadingCount": _as_int_or_none(document_row.get("accepted_heading_count")),
            "strategy": _as_str_or_none(document_row.get("strategy")),
            "doclingStatus": _as_str_or_none(document_row.get("docling_status")),
            "hasOutline": bool(document_row.get("has_outline")),
            "outlineCount": _as_int_or_none(manifest_row.get("outline_count") or document_row.get("outline_count")),
            "qualityFlags": list(document_row.get("quality_flags") or [])[:12],
            "hasUsefulInformation": bool(doc_feature_row.get("has_useful_information")),
            "docMatchProbability": round(_as_float(doc_feature_row.get("doc_match_probability")), 3),
            "topSectionScore": round(_as_float(doc_feature_row.get("top_section_score")), 1),
            "topSectionTitle": _trim_text(doc_feature_row.get("top_section_title"), max_chars=220),
            "visibleSectionCount": int(len(visible_rows)),
            "previewSections": _build_preview_sections(visible_rows, limit=3),
            "createdAt": SERVER_TIMESTAMP,
        }
        doc_docs.append((doc_id, summary_payload))

        for row in visible_rows:
            section_id = _as_str_or_none(row.get("section_id"))
            if not section_id:
                had_partial_failures = True
                continue
            locator_row = dict(section_locator_by_id.get(section_id) or {})
            heading_anchor = locator_row.get("heading_anchor") if isinstance(locator_row.get("heading_anchor"), dict) else {}
            span = locator_row.get("span") if isinstance(locator_row.get("span"), dict) else {}
            evidence_preview_rows = []
            for item in list(row.get("evidence_preview") or [])[:3]:
                if not isinstance(item, dict):
                    continue
                evidence_preview_rows.append(
                    {
                        "pageStart": _as_int_or_none(item.get("page_start")),
                        "pageEnd": _as_int_or_none(item.get("page_end")),
                        "lanes": list(item.get("lanes") or [])[:4],
                        "text": _trim_text(item.get("text"), max_chars=340),
                    }
                )
            section_doc_id = f"{doc_id}__{section_id}"
            section_docs.append(
                (
                    section_doc_id,
                    {
                        "docId": doc_id,
                        "pdfId": pdf_id,
                        "pdfFilename": _as_str_or_none(pdf_snapshot.get("filename")),
                        "pdfLabel": summary_payload["pdfLabel"],
                        "docTitle": summary_payload["docTitle"],
                        "sectionId": section_id,
                        "title": _trim_text(row.get("title"), max_chars=260),
                        "sectionPath": list(row.get("section_path") or []),
                        "sectionPathText": _trim_text(" / ".join(list(row.get("section_path") or [])) or row.get("title"), max_chars=400),
                        "sectionType": _as_str_or_none(row.get("section_type")) or "body_other",
                        "pageStart": _as_int_or_none(row.get("page_start")),
                        "pageEnd": _as_int_or_none(row.get("page_end")),
                        "score0To100": round(_as_float(row.get("score_0_to_100")), 1),
                        "scoreBand": _as_str_or_none(row.get("score_band")),
                        "supportStrength": round(_as_float(row.get("support_strength")), 3),
                        "supportingPassageCount": _as_int_or_none(row.get("supporting_passage_count")),
                        "subpointCoverageIds": list(row.get("subpoint_coverage_ids") or [])[:12],
                        "qualityFlags": list(row.get("quality_flags") or [])[:12],
                        "globalRank": _as_int_or_none(row.get("global_rank")),
                        "docRank": _as_int_or_none(row.get("doc_rank")),
                        "headingAnchor": {
                            "page": _as_int_or_none(heading_anchor.get("page")),
                            "blockIndex": _as_int_or_none(heading_anchor.get("block_index")),
                            "absBlockIndex": _as_int_or_none(heading_anchor.get("abs_block_index")),
                            "method": _as_str_or_none(heading_anchor.get("method")),
                            "confidence": _as_float(heading_anchor.get("confidence"), 0.0),
                        },
                        "span": {
                            "startAbsBlockIndex": _as_int_or_none(span.get("start_abs_block_index")),
                            "endAbsBlockIndex": _as_int_or_none(span.get("end_abs_block_index")),
                            "blockCount": _as_int_or_none(span.get("block_count")),
                        },
                        "anchorPage": _as_int_or_none((heading_anchor or {}).get("page")),
                        "evidencePreview": evidence_preview_rows,
                        "createdAt": SERVER_TIMESTAMP,
                    },
                )
            )

    return {
        "doc_docs": doc_docs,
        "section_docs": section_docs,
        "visible_doc_count": int(visible_doc_count),
        "visible_section_count": int(len(section_docs)),
        "scanned_doc_count": int(len(document_rows)),
        "useful_pdf_count": int(useful_pdf_count),
        "had_partial_failures": bool(had_partial_failures),
    }


async def _run_pipeline_subprocess(
    *,
    theme_path: Path,
    pdf_root: Path,
    runs_root: Path,
    max_pdfs: int,
    on_progress: Any,
    cancel_requested_sync: Any,
    termination_requested_sync: Callable[[], bool] | None = None,
    termination_message_getter: Callable[[], str | None] | None = None,
) -> dict[str, Any]:
    args = [
        sys.executable,
        str(PIPELINE_CHILD_SCRIPT),
        f"--theme-md={str(theme_path)}",
        f"--pdf-dir={str(pdf_root)}",
        f"--runs-root={str(runs_root)}",
        f"--max-pdfs={int(max_pdfs)}",
        "--pdf-recursive",
        "--force-rebuild-phase-a",
        "--force-rebuild-phase-b",
        "--force-rebuild-phase-c",
        "--force-rebuild-phase-d",
        "--force-rebuild-phase-e",
        "--force-rebuild-phase-f",
        "--force-rebuild-phase-g",
    ]
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    loop = asyncio.get_running_loop()

    state: dict[str, Any] = {
        "pipeline_run_id": None,
        "run_dir": None,
        "output_json": None,
        "document_count": None,
        "useful_pdfs": None,
        "child_error_message": None,
        "stdout_tail": [],
        "stderr_tail": [],
        "suppressed_child_lines": {},
    }

    cancel_requested = False
    termination_requested = False

    async def handle_event(payload: dict[str, Any]) -> None:
        event = _as_str_or_none(payload.get("event")) or ""
        stage = _as_str_or_none(payload.get("stage"))
        label = _as_str_or_none(payload.get("label")) or (PDF_SCAN_STAGE_LABELS.get(stage or "", stage or "") if stage else "")
        if event == "run_initialized":
            state["pipeline_run_id"] = _as_str_or_none(payload.get("pipeline_run_id"))
            state["run_dir"] = _as_str_or_none(payload.get("run_dir"))
            await on_progress(
                "phase_a",
                f"{label or PDF_SCAN_STAGE_LABELS['phase_a']} ready",
                current=_as_int_or_none(payload.get("document_count")),
                total=_as_int_or_none(payload.get("document_count")),
            )
            return
        if event == "stage_start" and stage:
            await on_progress(stage, label or PDF_SCAN_STAGE_LABELS.get(stage, stage), current=_as_int_or_none(payload.get("current")), total=_as_int_or_none(payload.get("total")))
            return
        if event == "document_progress" and stage:
            doc_id = _as_str_or_none(payload.get("doc_id"))
            message = label or PDF_SCAN_STAGE_LABELS.get(stage, stage)
            if doc_id:
                message = f"{message} ({doc_id})"
            await on_progress(stage, message, current=_as_int_or_none(payload.get("current")), total=_as_int_or_none(payload.get("total")))
            return
        if event == "stage_complete" and stage:
            total = _as_int_or_none(payload.get("total"))
            current = _as_int_or_none(payload.get("current")) or total
            await on_progress(
                stage,
                f"{label or PDF_SCAN_STAGE_LABELS.get(stage, stage)} complete",
                current=current,
                total=total,
                stage_completed=True,
            )
            return
        if event == "run_complete":
            state["pipeline_run_id"] = _as_str_or_none(payload.get("pipeline_run_id"))
            state["run_dir"] = _as_str_or_none(payload.get("run_dir"))
            state["output_json"] = _as_str_or_none(payload.get("output_json"))
            state["document_count"] = _as_int_or_none(payload.get("document_count"))
            state["useful_pdfs"] = _as_int_or_none(payload.get("useful_pdfs"))
            return
        if event == "run_error":
            state["child_error_message"] = _as_str_or_none(payload.get("error_message")) or _as_str_or_none(payload.get("error_type"))

    def handle_event_sync(payload: dict[str, Any]) -> None:
        async def _forward() -> None:
            await handle_event(payload)

        fut = asyncio.run_coroutine_threadsafe(_forward(), loop)
        fut.result()

    def run_threaded_subprocess() -> dict[str, Any]:
        nonlocal cancel_requested, termination_requested
        proc = subprocess.Popen(
            args,
            cwd=str(FASTAPI_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,
        )

        event_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        eof_count = 0

        def pump_stream(stream: Any, channel: str) -> None:
            try:
                if stream is None:
                    return
                while True:
                    line = stream.readline()
                    if not line:
                        break
                    event_queue.put((channel, line.rstrip()))
            finally:
                event_queue.put((f"{channel}_eof", ""))
                with contextlib.suppress(Exception):
                    if stream is not None:
                        stream.close()

        stdout_thread = threading.Thread(target=pump_stream, args=(proc.stdout, "stdout"), daemon=True)
        stderr_thread = threading.Thread(target=pump_stream, args=(proc.stderr, "stderr"), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        while True:
            stop_requested = False
            if callable(termination_requested_sync) and termination_requested_sync() and proc.poll() is None:
                termination_requested = True
                stop_requested = True
            elif cancel_requested_sync() and proc.poll() is None:
                cancel_requested = True
                stop_requested = True

            if stop_requested:
                with contextlib.suppress(Exception):
                    proc.terminate()
                deadline = time.time() + 15.0
                while proc.poll() is None and time.time() < deadline:
                    time.sleep(0.2)
                if proc.poll() is None:
                    with contextlib.suppress(Exception):
                        proc.kill()

            try:
                channel, text = event_queue.get(timeout=0.25)
            except queue.Empty:
                if proc.poll() is not None and eof_count >= 2:
                    break
                continue

            if channel.endswith("_eof"):
                eof_count += 1
                if proc.poll() is not None and eof_count >= 2:
                    break
                continue

            if not text:
                continue

            if channel == "stdout" and text.startswith(PIPELINE_EVENT_PREFIX):
                try:
                    payload = json.loads(text[len(PIPELINE_EVENT_PREFIX) :])
                except Exception:
                    logger.warning("Failed to parse PDF scan child event: %s", text)
                    continue
                if isinstance(payload, dict):
                    handle_event_sync(payload)
                continue
            if _is_mupdf_noise_line(text):
                _remember_suppressed_child_line(state, text)
                continue

            tail_key = "stderr_tail" if channel == "stderr" else "stdout_tail"
            tail = state[tail_key]
            tail.append(text)
            if len(tail) > 80:
                del tail[:-80]

            logger.info("PDF scan child %s | %s", channel, text)

        stdout_thread.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)
        return_code = proc.wait(timeout=5)
        _flush_suppressed_child_lines(state)

        if termination_requested:
            raise PdfScanRunTerminated(_termination_message(termination_message_getter))
        if cancel_requested:
            raise PdfScanRunCancelled("Cancellation requested.")
        if return_code != 0:
            stderr_tail = "\n".join(state.get("stderr_tail") or [])
            stdout_tail = "\n".join(state.get("stdout_tail") or [])
            detail = _trim_text(
                _as_str_or_none(state.get("child_error_message"))
                or stderr_tail
                or stdout_tail
                or f"Exit code {return_code}",
                max_chars=4000,
            )
            raise RuntimeError(f"Standalone PDF scan pipeline failed. {detail or ''}".strip())
        return dict(state)

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(FASTAPI_ROOT),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except NotImplementedError:
        logger.warning("Falling back to threaded PDF scan subprocess runner on this event loop.")
        return await asyncio.to_thread(run_threaded_subprocess)

    async def read_stream(stream: asyncio.StreamReader | None, *, is_stderr: bool) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="ignore").rstrip()
            if not text:
                continue
            if not is_stderr and text.startswith(PIPELINE_EVENT_PREFIX):
                try:
                    payload = json.loads(text[len(PIPELINE_EVENT_PREFIX) :])
                except Exception:
                    logger.warning("Failed to parse PDF scan child event: %s", text)
                    continue
                if isinstance(payload, dict):
                    await handle_event(payload)
                continue
            if _is_mupdf_noise_line(text):
                _remember_suppressed_child_line(state, text)
                continue
            tail_key = "stderr_tail" if is_stderr else "stdout_tail"
            tail = state[tail_key]
            tail.append(text)
            if len(tail) > 80:
                del tail[:-80]
            logger.info("PDF scan child %s | %s", "stderr" if is_stderr else "stdout", text)

    async def watch_cancel() -> None:
        nonlocal cancel_requested, termination_requested
        while proc.returncode is None:
            stop_requested = False
            if callable(termination_requested_sync) and termination_requested_sync():
                termination_requested = True
                stop_requested = True
            elif cancel_requested_sync():
                cancel_requested = True
                stop_requested = True
            if stop_requested:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    return
                try:
                    await asyncio.wait_for(proc.wait(), timeout=15)
                except asyncio.TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        proc.kill()
                return
            await asyncio.sleep(3)

    stdout_task = asyncio.create_task(read_stream(proc.stdout, is_stderr=False))
    stderr_task = asyncio.create_task(read_stream(proc.stderr, is_stderr=True))
    cancel_task = asyncio.create_task(watch_cancel())

    try:
        return_code = await proc.wait()
        await asyncio.gather(stdout_task, stderr_task)
    finally:
        cancel_task.cancel()
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await cancel_task
        _flush_suppressed_child_lines(state)

    if termination_requested:
        raise PdfScanRunTerminated(_termination_message(termination_message_getter))
    if cancel_requested:
        raise PdfScanRunCancelled("Cancellation requested.")
    if return_code != 0:
        stderr_tail = "\n".join(state.get("stderr_tail") or [])
        stdout_tail = "\n".join(state.get("stdout_tail") or [])
        detail = _trim_text(
            _as_str_or_none(state.get("child_error_message")) or stderr_tail or stdout_tail or f"Exit code {return_code}",
            max_chars=4000,
        )
        raise RuntimeError(f"Standalone PDF scan pipeline failed. {detail or ''}".strip())
    return state


async def run_quellen_finder_pdf_scan_job_from_run_doc(
    *,
    user_id: str,
    projekt_id: str,
    run_id: str,
    external_termination_event: asyncio.Event | None = None,
    external_termination_message_getter: Callable[[], str | None] | None = None,
) -> None:
    fs = QuellenFinderFirestoreService()
    budget_service = get_openai_budget_service(firebase_service)

    def _reservation_operation_id_from_data(data: dict[str, Any]) -> str:
        billing_state = data.get("billing") if isinstance(data.get("billing"), dict) else {}
        return _as_str_or_none((billing_state or {}).get("reservationOperationId")) or f"{run_id}_pdf_scan_run"

    def _log_preflight_cleanup_warning(action: str, exc: BaseException) -> None:
        logger.warning(
            "PDF scan preflight cleanup transient failure | action=%s user_id=%s projekt_id=%s run_id=%s err=%s",
            action,
            user_id,
            projekt_id,
            run_id,
            exc,
        )

    async def _finalize_preflight_failure(*, message: str, cancelled: bool) -> None:
        normalized_message = _trim_text(message, max_chars=1000) or ("Cancellation requested." if cancelled else "Unknown error")
        data = await _load_required_run_doc(
            fs=fs,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            purpose="preflight_failure_cleanup",
        )
        reservation_operation_id = _reservation_operation_id_from_data(data)
        if cancelled:
            try:
                await budget_service.mark_status(
                    user_id=user_id,
                    operation_id=reservation_operation_id,
                    status="cancelled",
                    error_message=normalized_message,
                )
            except FINALIZATION_TRANSIENT_EXCEPTIONS as exc:
                _log_preflight_cleanup_warning("budget_mark_cancelled", exc)
            try:
                await budget_service.release_reservation(
                    user_id=user_id,
                    operation_id=reservation_operation_id,
                    reason="cancelled",
                )
            except FINALIZATION_TRANSIENT_EXCEPTIONS as exc:
                _log_preflight_cleanup_warning("budget_release_cancelled", exc)
            try:
                fs.mark_cancelled(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
            except FINALIZATION_TRANSIENT_EXCEPTIONS as exc:
                _log_preflight_cleanup_warning("firestore_mark_cancelled", exc)
            try:
                fs.run_ref(user_id, projekt_id, run_id).set(
                    {
                        "billing": {
                            "status": "cancelled",
                            "reservationOperationId": reservation_operation_id,
                        }
                    },
                    merge=True,
                )
            except FINALIZATION_TRANSIENT_EXCEPTIONS as exc:
                _log_preflight_cleanup_warning("firestore_set_cancelled_billing", exc)
            return

        try:
            await budget_service.mark_status(
                user_id=user_id,
                operation_id=reservation_operation_id,
                status="error",
                error_message=normalized_message,
            )
        except FINALIZATION_TRANSIENT_EXCEPTIONS as exc:
            _log_preflight_cleanup_warning("budget_mark_error", exc)
        try:
            await budget_service.release_reservation(
                user_id=user_id,
                operation_id=reservation_operation_id,
                reason="error",
            )
        except FINALIZATION_TRANSIENT_EXCEPTIONS as exc:
            _log_preflight_cleanup_warning("budget_release_error", exc)
        try:
            fs.mark_error(
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                error_message=normalized_message,
                had_partial_failures=False,
            )
        except FINALIZATION_TRANSIENT_EXCEPTIONS as exc:
            _log_preflight_cleanup_warning("firestore_mark_error", exc)
        try:
            fs.run_ref(user_id, projekt_id, run_id).set(
                {
                    "billing": {
                        "status": "error",
                        "reservationOperationId": reservation_operation_id,
                    }
                    },
                    merge=True,
                )
        except FINALIZATION_TRANSIENT_EXCEPTIONS as exc:
            _log_preflight_cleanup_warning("firestore_set_error_billing", exc)

    def _load() -> tuple[dict[str, Any], str | None]:
        data = fs.get_run(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        status_now = str((data or {}).get("status") or "").strip()
        if status_now in {"success", "error", "cancelled"}:
            return data, "terminal"
        if status_now == "running":
            return data, "already_running"
        if bool((data or {}).get("cancelRequestedAt")):
            fs.mark_cancelled(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
            return data, "cancelled_before_start"
        return data, None

    data, skip_reason = await asyncio.to_thread(_load)
    if skip_reason:
        logger.info(
            "QF pdf scan worker no-op | run_id=%s projekt_id=%s reason=%s",
            run_id,
            projekt_id,
            skip_reason,
        )
        return

    try:
        if external_termination_event is not None and external_termination_event.is_set():
            raise PdfScanRunTerminated(_termination_message(external_termination_message_getter))

        if str((data or {}).get("kind") or "") != "pdf_scan":
            raise RuntimeError("Run is not a pdf_scan run.")

        kapitel_id, settings = _build_runtime_settings_from_run_doc(data)
        if external_termination_event is not None and external_termination_event.is_set():
            raise PdfScanRunTerminated(_termination_message(external_termination_message_getter))

        await run_quellen_finder_pdf_scan_job(
            user_id=user_id,
            projekt_id=projekt_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            settings=settings,
            external_termination_event=external_termination_event,
            external_termination_message_getter=external_termination_message_getter,
        )
    except PdfScanRunCancelled as exc:
        logger.info("QF pdf scan preflight cancelled | run_id=%s err=%s", run_id, exc)
        await _finalize_preflight_failure(message=_exception_message(exc), cancelled=True)
        raise
    except Exception as exc:
        logger.error("QF pdf scan preflight failed | run_id=%s error=%s", run_id, exc, exc_info=True)
        await _finalize_preflight_failure(message=_exception_message(exc), cancelled=False)
        raise


async def run_quellen_finder_pdf_scan_job(
    *,
    user_id: str,
    projekt_id: str,
    kapitel_id: str,
    run_id: str,
    settings: dict[str, Any],
    external_termination_event: asyncio.Event | None = None,
    external_termination_message_getter: Callable[[], str | None] | None = None,
) -> None:
    fs = QuellenFinderFirestoreService()
    budget_service = get_openai_budget_service(firebase_service)
    credits_service = get_credits_service(firebase_service)
    cost_service = get_cost_service(firebase_service)
    run_doc = await _load_required_run_doc(
        fs=fs,
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        purpose="run_execution",
    )
    billing_state = run_doc.get("billing") if isinstance(run_doc.get("billing"), dict) else {}
    reservation_operation_id = _as_str_or_none((billing_state or {}).get("reservationOperationId")) or f"{run_id}_pdf_scan_run"
    kapitel_snapshots = run_doc.get("kapitelSnapshots") if isinstance(run_doc.get("kapitelSnapshots"), list) else []
    kapitel_snapshot = kapitel_snapshots[0] if kapitel_snapshots and isinstance(kapitel_snapshots[0], dict) else None
    model_name = _as_str_or_none(run_doc.get("model")) or "pdf_scan_v3_topic_best"
    t0 = time.perf_counter()
    heartbeat_stop = asyncio.Event()

    def user_cancel_requested_sync() -> bool:
        snap = fs.run_ref(user_id, projekt_id, run_id).get()
        data = snap.to_dict() if snap is not None else {}
        return bool((data or {}).get("cancelRequestedAt"))

    def termination_requested_sync() -> bool:
        return bool(external_termination_event is not None and external_termination_event.is_set())

    async def check_cancel() -> None:
        if termination_requested_sync():
            raise PdfScanRunTerminated(_termination_message(external_termination_message_getter))
        if await asyncio.to_thread(user_cancel_requested_sync):
            raise PdfScanRunCancelled("Cancellation requested.")

    last_stage: str | None = None
    last_progress: dict[str, Any] = {
        "stage": None,
        "message": None,
        "current": None,
        "total": None,
    }
    pipeline_stages: dict[str, dict[str, Any]] = {}

    def _snapshot_pipeline_stages() -> dict[str, dict[str, Any]]:
        return {str(key): dict(value) for key, value in pipeline_stages.items()}

    def _now_epoch_ms() -> int:
        return int(round(time.time() * 1000.0))

    def _update_pipeline_stages(
        *,
        stage: str,
        current: int | None,
        total: int | None,
        stage_started_at: bool,
        stage_completed: bool,
        terminal_status: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        now_ms = _now_epoch_ms()
        stage_s = str(stage or "")
        if stage_started_at:
            previous_stage = _as_str_or_none(last_progress.get("stage"))
            if previous_stage and previous_stage != stage_s:
                previous_entry = pipeline_stages.setdefault(previous_stage, {})
                if str(previous_entry.get("status") or "") == "running":
                    started_at_ms = _as_int_or_none(previous_entry.get("startedAtMs")) or now_ms
                    previous_entry["status"] = "completed"
                    previous_entry["completedAtMs"] = now_ms
                    previous_entry["elapsedMs"] = max(0, now_ms - started_at_ms)
        entry = pipeline_stages.setdefault(stage_s, {})
        if stage_started_at or not isinstance(entry.get("startedAtMs"), int):
            entry["startedAtMs"] = now_ms
            entry.pop("completedAtMs", None)
            entry.pop("elapsedMs", None)
        if isinstance(current, int):
            entry["current"] = int(current)
        if isinstance(total, int):
            entry["total"] = int(total)
        entry["status"] = terminal_status or ("completed" if stage_completed else "running")
        if stage_completed or terminal_status in {"error", "cancelled"}:
            started_at_ms = _as_int_or_none(entry.get("startedAtMs")) or now_ms
            entry["completedAtMs"] = now_ms
            entry["elapsedMs"] = max(0, now_ms - started_at_ms)
        return _snapshot_pipeline_stages()

    def _mark_current_stage_terminal(status: str) -> dict[str, dict[str, Any]] | None:
        stage_s = _as_str_or_none(last_progress.get("stage"))
        if not stage_s:
            return None
        return _update_pipeline_stages(
            stage=stage_s,
            current=_as_int_or_none(last_progress.get("current")),
            total=_as_int_or_none(last_progress.get("total")),
            stage_started_at=False,
            stage_completed=False,
            terminal_status=str(status or "").strip() or None,
        )

    async def on_progress(
        stage: str,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
        stage_completed: bool = False,
    ) -> None:
        nonlocal last_stage
        stage_s = str(stage or "")
        stage_started_at = stage_s != (last_stage or "")
        if stage_started_at:
            last_stage = stage_s
        pipeline_stage_snapshot = _update_pipeline_stages(
            stage=stage_s,
            current=current,
            total=total,
            stage_started_at=bool(stage_started_at),
            stage_completed=bool(stage_completed),
        )
        last_progress.update(
            {
                "stage": stage_s,
                "message": str(message),
                "current": current,
                "total": total,
            }
        )
        await asyncio.to_thread(
            fs.set_progress,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            stage=stage_s,
            message=str(message),
            current=current,
            total=total,
            stage_started_at=bool(stage_started_at),
            pipeline_stages=pipeline_stage_snapshot,
        )

    def on_progress_sync(
        stage: str,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
        stage_completed: bool = False,
    ) -> None:
        nonlocal last_stage
        stage_s = str(stage or "")
        stage_started_at = stage_s != (last_stage or "")
        if stage_started_at:
            last_stage = stage_s
        pipeline_stage_snapshot = _update_pipeline_stages(
            stage=stage_s,
            current=current,
            total=total,
            stage_started_at=bool(stage_started_at),
            stage_completed=bool(stage_completed),
        )
        last_progress.update(
            {
                "stage": stage_s,
                "message": str(message),
                "current": current,
                "total": total,
            }
        )
        fs.set_progress(
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            stage=stage_s,
            message=str(message),
            current=current,
            total=total,
            stage_started_at=bool(stage_started_at),
            pipeline_stages=pipeline_stage_snapshot,
        )

    async def progress_heartbeat() -> None:
        while not heartbeat_stop.is_set():
            try:
                await asyncio.wait_for(heartbeat_stop.wait(), timeout=20.0)
                return
            except asyncio.TimeoutError:
                pass
            stage = _as_str_or_none(last_progress.get("stage"))
            message = _as_str_or_none(last_progress.get("message"))
            if not stage or not message:
                continue
            await asyncio.to_thread(
                fs.set_progress,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                stage=stage,
                message=message,
                current=_as_int_or_none(last_progress.get("current")),
                total=_as_int_or_none(last_progress.get("total")),
                stage_started_at=False,
                pipeline_stages=_snapshot_pipeline_stages(),
            )

    heartbeat_task = asyncio.create_task(progress_heartbeat())

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
                }
            },
            merge=True,
        )
        await on_progress("prepare_inputs", "Preparing PDF scan inputs")
        await asyncio.to_thread(fs.clear_subcollection, user_id=user_id, projekt_id=projekt_id, run_id=run_id, name="pdfScanDocs")
        await asyncio.to_thread(fs.clear_subcollection, user_id=user_id, projekt_id=projekt_id, run_id=run_id, name="pdfScanSections")
        with tempfile.TemporaryDirectory(prefix="qf_pdf_scan_") as tmpdir:
            temp_root = Path(tmpdir)
            theme_path = temp_root / "Text Thema.md"
            pdf_root = temp_root / "pdfs"
            pipeline_runs_root = temp_root / "pipeline_runs"
            theme_path.write_text(
                _build_theme_markdown(
                    chapter_title=str((settings or {}).get("chapter_title") or "").strip(),
                    chapter_spec_text=str((settings or {}).get("chapter_spec_text") or "").strip(),
                ),
                encoding="utf-8",
            )

            pdf_snapshot_rows = list((settings or {}).get("pdf_snapshots") or [])
            pdf_snapshot_by_id = await asyncio.to_thread(
                _download_selected_pdfs,
                pdf_snapshots=pdf_snapshot_rows,
                pdf_root=pdf_root,
                on_progress_sync=on_progress_sync,
                cancel_requested_sync=user_cancel_requested_sync,
                termination_requested_sync=termination_requested_sync,
                termination_message_getter=external_termination_message_getter,
            )
            await check_cancel()

            pipeline_state = await _run_pipeline_subprocess(
                theme_path=theme_path,
                pdf_root=pdf_root,
                runs_root=pipeline_runs_root,
                max_pdfs=len(pdf_snapshot_rows),
                on_progress=on_progress,
                cancel_requested_sync=user_cancel_requested_sync,
                termination_requested_sync=termination_requested_sync,
                termination_message_getter=external_termination_message_getter,
            )
            await check_cancel()

            pipeline_run_dir = _resolve_pipeline_run_dir(
                pipeline_state.get("run_dir"),
                expected_root=pipeline_runs_root,
            )

            await on_progress("persist_results", "Preparing PDF result cards")
            persisted = await asyncio.to_thread(
                _build_persisted_view_docs,
                run_dir=pipeline_run_dir,
                pdf_snapshot_by_id=pdf_snapshot_by_id,
            )
            await check_cancel()

            total_docs = int(len(list(persisted.get("doc_docs") or [])))
            await on_progress("persist_results", "Saving PDF result cards", current=total_docs, total=total_docs)
            await asyncio.to_thread(
                fs.replace_pdf_scan_results,
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                doc_docs=list(persisted.get("doc_docs") or []),
                section_docs=list(persisted.get("section_docs") or []),
            )
            await on_progress(
                "persist_results",
                "Saving PDF result cards complete",
                current=total_docs,
                total=total_docs,
                stage_completed=True,
            )
            dt = float(time.perf_counter() - t0)
            api_usage = _read_pdf_scan_api_usage(pipeline_run_dir)
            compute_billing = await credits_service.calculate_pdf_scan_compute_cost(
                user_id=user_id,
                pdf_count=len(pdf_snapshot_rows),
                seconds_total=dt,
            )
            openai_cost_usd = float(max(_as_float(api_usage.get("cost_usd"), 0.0), 0.0))
            compute_cost_usd = float(max(_as_float(compute_billing.get("cost_usd"), 0.0), 0.0))
            total_cost_usd = float(round(openai_cost_usd + compute_cost_usd, 10))
            spend_rate_value = float(max(_as_float(compute_billing.get("spend_rate"), 0.0), 0.0))
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
                    "pdfCount": int(len(pdf_snapshot_rows)),
                    "pipelineVersion": model_name,
                    "visibleDocCount": int(persisted.get("visible_doc_count") or 0),
                    "visibleSectionCount": int(persisted.get("visible_section_count") or 0),
                    "hadPartialFailures": bool(persisted.get("had_partial_failures")),
                },
                model=model_name,
                usage=usage_payload,
                key_source="pdf_scan_pipeline",
                billing_components={
                    "openaiCostUsd": float(round(openai_cost_usd, 10)),
                    "computeCostUsd": float(round(compute_cost_usd, 10)),
                    "openaiCallCount": int(api_usage.get("call_count") or 0),
                    "secondsTotal": float(round(dt, 3)),
                    "openaiByStage": dict(api_usage.get("by_stage") or {}),
                    "computeBilling": dict(compute_billing or {}),
                },
                projekt_id=projekt_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                kapitel_snapshot=kapitel_snapshot,
                run_snapshot={"id": run_id, "kind": "pdf_scan"},
                status="success",
                spend_rate=spend_rate_value if spend_rate_value > 0 else None,
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
                extra={
                    "resultCount": int(persisted.get("visible_section_count") or 0),
                    "pdfScanDocCount": int(persisted.get("visible_doc_count") or 0),
                    "pdfScanSectionCount": int(persisted.get("visible_section_count") or 0),
                    "usefulPdfCount": int(persisted.get("useful_pdf_count") or 0),
                    "summary": {
                        "seconds_total": dt,
                        "scanned_doc_count": int(persisted.get("scanned_doc_count") or 0),
                        "visible_doc_count": int(persisted.get("visible_doc_count") or 0),
                        "visible_section_count": int(persisted.get("visible_section_count") or 0),
                        "useful_pdf_count": int(persisted.get("useful_pdf_count") or 0),
                        "openai_call_count": int(api_usage.get("call_count") or 0),
                        "openai_input_tokens": int(api_usage.get("input_tokens") or 0),
                        "openai_cached_input_tokens": int(api_usage.get("cached_input_tokens") or 0),
                        "openai_output_tokens": int(api_usage.get("output_tokens") or 0),
                        "openai_total_tokens": int(api_usage.get("total_tokens") or 0),
                        "openai_cost_usd": float(round(openai_cost_usd, 10)),
                        "compute_cost_usd": float(round(compute_cost_usd, 10)),
                        "total_cost_usd": float(round(total_cost_usd, 10)),
                    },
                    "billing": {
                        "status": "charged",
                        "reservationOperationId": reservation_operation_id,
                        "chargedOperationId": reservation_operation_id,
                        "spendRate": float(spend_rate_value),
                        "openaiCostUsd": float(round(openai_cost_usd, 10)),
                        "computeCostUsd": float(round(compute_cost_usd, 10)),
                        "totalCostUsd": float(round(total_cost_usd, 10)),
                        "creditsDebited": float(round(total_cost_usd * spend_rate_value, 8)),
                        "openaiCallCount": int(api_usage.get("call_count") or 0),
                        "chargedAt": SERVER_TIMESTAMP,
                    },
                },
            )
            logger.info(
                "QF pdf scan success | run_id=%s seconds=%.2f docs=%s sections=%s useful=%s partial=%s total_cost_usd=%.5f",
                run_id,
                dt,
                int(persisted.get("visible_doc_count") or 0),
                int(persisted.get("visible_section_count") or 0),
                int(persisted.get("useful_pdf_count") or 0),
                bool(persisted.get("had_partial_failures")),
                total_cost_usd,
            )
    except PdfScanRunCancelled:
        logger.info("QF pdf scan cancelled | run_id=%s kapitel_id=%s", run_id, kapitel_id)
        await budget_service.mark_status(
            user_id=user_id,
            operation_id=reservation_operation_id,
            status="cancelled",
            error_message="Cancellation requested.",
        )
        await budget_service.release_reservation(
            user_id=user_id,
            operation_id=reservation_operation_id,
            reason="cancelled",
        )
        fs.mark_cancelled(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        terminal_stages = _mark_current_stage_terminal("cancelled")
        payload: dict[str, Any] = {"billing": {"status": "cancelled", "reservationOperationId": reservation_operation_id}}
        if terminal_stages is not None:
            payload["pipelineStages"] = terminal_stages
        fs.run_ref(user_id, projekt_id, run_id).set(payload, merge=True)
    except PdfScanRunTerminated as exc:
        logger.error("QF pdf scan terminated | run_id=%s reason=%s", run_id, exc)
        msg = _exception_message(exc)[:1000]
        await budget_service.mark_status(
            user_id=user_id,
            operation_id=reservation_operation_id,
            status="error",
            error_message=msg,
        )
        await budget_service.release_reservation(
            user_id=user_id,
            operation_id=reservation_operation_id,
            reason="error",
        )
        fs.mark_error(user_id=user_id, projekt_id=projekt_id, run_id=run_id, error_message=msg, had_partial_failures=False)
        terminal_stages = _mark_current_stage_terminal("error")
        payload: dict[str, Any] = {"billing": {"status": "error", "reservationOperationId": reservation_operation_id}}
        if terminal_stages is not None:
            payload["pipelineStages"] = terminal_stages
        fs.run_ref(user_id, projekt_id, run_id).set(payload, merge=True)
    except HTTPException as exc:
        logger.error(
            "QF pdf scan HTTPException | run_id=%s status=%s detail=%s",
            run_id,
            getattr(exc, "status_code", None),
            getattr(exc, "detail", None),
            exc_info=True,
        )
        detail = getattr(exc, "detail", None)
        msg = _exception_message(exc if detail is None else Exception(str(detail)))[:1000]
        await budget_service.mark_status(
            user_id=user_id,
            operation_id=reservation_operation_id,
            status="error",
            error_message=msg,
        )
        await budget_service.release_reservation(
            user_id=user_id,
            operation_id=reservation_operation_id,
            reason="error",
        )
        fs.mark_error(user_id=user_id, projekt_id=projekt_id, run_id=run_id, error_message=msg, had_partial_failures=False)
        terminal_stages = _mark_current_stage_terminal("error")
        payload: dict[str, Any] = {"billing": {"status": "error", "reservationOperationId": reservation_operation_id}}
        if terminal_stages is not None:
            payload["pipelineStages"] = terminal_stages
        fs.run_ref(user_id, projekt_id, run_id).set(payload, merge=True)
    except Exception as exc:
        logger.error("QF pdf scan failed | run_id=%s error=%s", run_id, exc, exc_info=True)
        logger.debug("Traceback:\n%s", traceback.format_exc())
        msg = _exception_message(exc)[:1000]
        await budget_service.mark_status(
            user_id=user_id,
            operation_id=reservation_operation_id,
            status="error",
            error_message=msg,
        )
        await budget_service.release_reservation(
            user_id=user_id,
            operation_id=reservation_operation_id,
            reason="error",
        )
        fs.mark_error(user_id=user_id, projekt_id=projekt_id, run_id=run_id, error_message=msg, had_partial_failures=False)
        terminal_stages = _mark_current_stage_terminal("error")
        payload: dict[str, Any] = {"billing": {"status": "error", "reservationOperationId": reservation_operation_id}}
        if terminal_stages is not None:
            payload["pipelineStages"] = terminal_stages
        fs.run_ref(user_id, projekt_id, run_id).set(payload, merge=True)
    finally:
        heartbeat_stop.set()
        with contextlib.suppress(Exception):
            await heartbeat_task
