#!/usr/bin/env python3
from __future__ import annotations

import argparse
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path

from phase_a_lab import (
    load_metrics,
    log_event,
    print_kv,
    print_section,
    print_table,
    save_metrics,
    setup_run_logger,
    stable_hash,
    stage_timer,
    run_phase_a,
)

# Phase B.0 - Parser bundle helpers and artifact writers

import importlib.metadata as importlib_metadata
import io
import json
import math
import re
import site
import sys
import time
import traceback
import threading
import warnings
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

OPTIONAL_IMPORT_ERRORS = {}
_MUPDF_DISPLAY_LOCK = threading.Lock()
_MUPDF_DISPLAY_DEPTH = 0
_MUPDF_PREVIOUS_ERRORS = None
_MUPDF_PREVIOUS_WARNINGS = None

try:
    import fitz  # PyMuPDF
except Exception as e:
    fitz = None
    OPTIONAL_IMPORT_ERRORS["fitz"] = f"{type(e).__name__}: {e}"

try:
    from pypdf import PdfReader
except Exception as e:
    PdfReader = None
    OPTIONAL_IMPORT_ERRORS["pypdf"] = f"{type(e).__name__}: {e}"

InputFormat = None
PdfPipelineOptions = None
PdfFormatOption = None
DocumentConverter = None
_DOCLING_IMPORT_ATTEMPTED = False


def _ensure_docling_imported() -> bool:
    global InputFormat, PdfPipelineOptions, PdfFormatOption, DocumentConverter, _DOCLING_IMPORT_ATTEMPTED
    if DocumentConverter is not None:
        return True
    if _DOCLING_IMPORT_ATTEMPTED:
        return False
    _DOCLING_IMPORT_ATTEMPTED = True
    try:
        from docling.datamodel.base_models import InputFormat as _InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions as _PdfPipelineOptions
        from docling.document_converter import DocumentConverter as _DocumentConverter, PdfFormatOption as _PdfFormatOption
    except Exception as e:
        OPTIONAL_IMPORT_ERRORS["docling"] = f"{type(e).__name__}: {e}"
        InputFormat = None
        PdfPipelineOptions = None
        PdfFormatOption = None
        DocumentConverter = None
        return False
    OPTIONAL_IMPORT_ERRORS.pop("docling", None)
    InputFormat = _InputFormat
    PdfPipelineOptions = _PdfPipelineOptions
    PdfFormatOption = _PdfFormatOption
    DocumentConverter = _DocumentConverter
    return True

try:
    import requests
except Exception as e:
    requests = None
    OPTIONAL_IMPORT_ERRORS["requests"] = f"{type(e).__name__}: {e}"

try:
    from bs4 import BeautifulSoup
except Exception as e:
    BeautifulSoup = None
    OPTIONAL_IMPORT_ERRORS["bs4"] = f"{type(e).__name__}: {e}"


@dataclass
class PhaseBOptions:
    force_rebuild: bool = False
    doc_limit: Optional[int] = None
    include_doc_ids: Optional[List[str]] = None
    exclude_doc_ids: Optional[List[str]] = None
    max_concurrent_docs: Optional[int] = None
    min_page_words: int = 20
    min_doc_chars: int = 200
    try_docling: bool = True
    docling_page_limit: int = 400
    docling_max_file_size_bytes: int = 50 * 1024 * 1024
    docling_do_ocr: bool = False
    docling_do_table_structure: bool = False
    docling_document_timeout_sec: Optional[int] = 180
    docling_num_threads: int = 4
    docling_enable_chunking: bool = True
    docling_chunk_size: int = 20
    docling_chunk_max_pages: int = 400
    docling_chunk_num_threads: int = 1
    try_grobid: bool = True
    grobid_page_limit: int = 400
    grobid_base_url: str = ""
    grobid_process_path: str = "/api/processFulltextDocument"
    grobid_timeout_sec: int = 120
    grobid_consolidate_header: int = 0
    grobid_consolidate_citations: int = 0
    grobid_include_raw_citations: int = 0

    def normalized(self) -> "PhaseBOptions":
        return PhaseBOptions(
            force_rebuild=bool(self.force_rebuild),
            doc_limit=None if self.doc_limit is None else int(self.doc_limit),
            include_doc_ids=[str(x).strip() for x in (self.include_doc_ids or []) if str(x).strip()],
            exclude_doc_ids=[str(x).strip() for x in (self.exclude_doc_ids or []) if str(x).strip()],
            max_concurrent_docs=None if self.max_concurrent_docs is None else max(1, int(self.max_concurrent_docs)),
            min_page_words=int(self.min_page_words),
            min_doc_chars=int(self.min_doc_chars),
            try_docling=bool(self.try_docling),
            docling_page_limit=int(self.docling_page_limit),
            docling_max_file_size_bytes=int(self.docling_max_file_size_bytes),
            docling_do_ocr=bool(self.docling_do_ocr),
            docling_do_table_structure=bool(self.docling_do_table_structure),
            docling_document_timeout_sec=None if self.docling_document_timeout_sec is None else int(self.docling_document_timeout_sec),
            docling_num_threads=max(1, int(self.docling_num_threads)),
            docling_enable_chunking=bool(self.docling_enable_chunking),
            docling_chunk_size=max(2, int(self.docling_chunk_size)),
            docling_chunk_max_pages=max(2, int(self.docling_chunk_max_pages)),
            docling_chunk_num_threads=max(1, int(self.docling_chunk_num_threads)),
            try_grobid=bool(self.try_grobid),
            grobid_page_limit=int(self.grobid_page_limit),
            grobid_base_url=str(self.grobid_base_url or "").strip(),
            grobid_process_path=str(self.grobid_process_path or "/api/processFulltextDocument").strip() or "/api/processFulltextDocument",
            grobid_timeout_sec=int(self.grobid_timeout_sec),
            grobid_consolidate_header=int(self.grobid_consolidate_header),
            grobid_consolidate_citations=int(self.grobid_consolidate_citations),
            grobid_include_raw_citations=int(self.grobid_include_raw_citations),
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def available_cpu_count() -> int:
    try:
        return max(1, int(os.cpu_count() or 1))
    except Exception:
        return 1


def pkg_version(name: str) -> Optional[str]:
    try:
        return importlib_metadata.version(name)
    except Exception:
        return None


def json_safe(obj: Any) -> Any:
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [json_safe(v) for v in obj]
    return obj


def write_json_atomic(path: Path, obj: Any, retries: int = 6, sleep_sec: float = 0.25) -> None:
    ensure_dir(path.parent)
    payload = json.dumps(json_safe(obj), ensure_ascii=False, indent=2) + "\n"
    last_error = None
    for attempt in range(max(1, int(retries))):
        tmp = path.with_suffix(path.suffix + f".{attempt}.tmp")
        try:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)
            return
        except PermissionError as e:
            last_error = e
            time.sleep(float(sleep_sec) * float(attempt + 1))
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to write JSON atomically: {path}")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_jsonl_rows(path: Path, rows: List[Dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    payload = "".join(json.dumps(json_safe(row), ensure_ascii=False) + "\n" for row in rows)
    last_error = None
    for attempt in range(6):
        tmp = path.with_suffix(path.suffix + f".{attempt}.tmp")
        try:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)
            return
        except PermissionError as e:
            last_error = e
            time.sleep(0.25 * float(attempt + 1))
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to write JSONL atomically: {path}")


def clean_text(text: Any) -> str:
    s = str(text or "")
    s = s.replace("\xad", "")
    s = s.replace("\u00a0", " ")
    s = s.replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def count_words(text: Any) -> int:
    return len(re.findall(r"\w+", str(text or ""), flags=re.UNICODE))


def slugify(text: str, max_len: int = 64) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(text or "").strip().lower()).strip("_")
    s = re.sub(r"_+", "_", s)
    return (s or "doc")[: int(max_len)]


def rel_to_run(run_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(run_dir))
    except Exception:
        return str(path)


def short_blob(text: str, max_len: int = 12000) -> str:
    s = str(text or "")
    return s if len(s) <= max_len else (s[: max_len - 1] + "...")


def runtime_env_snapshot() -> Dict[str, Any]:
    try:
        user_site = site.getusersitepackages()
    except Exception:
        user_site = None
    try:
        site_packages = [str(p) for p in site.getsitepackages()]
    except Exception:
        site_packages = []
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "python_prefix": sys.prefix,
        "python_base_prefix": getattr(sys, "base_prefix", sys.prefix),
        "cwd": str(Path.cwd()),
        "user_site": user_site,
        "site_packages": site_packages,
        "sys_path_preview": [str(x) for x in sys.path[:15]],
    }


def capture_python_noise(fn: Callable[[], Any]) -> Dict[str, Any]:
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = fn()
    return {
        "result": result,
        "stdout": short_blob(stdout_buf.getvalue()),
        "stderr": short_blob(stderr_buf.getvalue()),
        "warnings": [short_blob(str(w.message), max_len=2000) for w in caught],
    }


def unique_nonempty_texts(values: Any, *, max_len: int = 2000) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in list(values or []):
        text = str(value or "").strip()
        if not text:
            continue
        text = short_blob(text, max_len=max_len)
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def consume_mupdf_messages(*, max_len: int = 2000) -> List[str]:
    if fitz is None:
        return []
    try:
        raw = fitz.TOOLS.mupdf_warnings(reset=1)
    except Exception:
        return []
    if isinstance(raw, (list, tuple)):
        values = raw
    else:
        values = str(raw or "").splitlines()
    return unique_nonempty_texts(values, max_len=max_len)


@contextmanager
def muted_mupdf_messages() -> Any:
    global _MUPDF_DISPLAY_DEPTH, _MUPDF_PREVIOUS_ERRORS, _MUPDF_PREVIOUS_WARNINGS
    if fitz is None:
        yield
        return

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with _MUPDF_DISPLAY_LOCK:
            if _MUPDF_DISPLAY_DEPTH == 0:
                try:
                    _MUPDF_PREVIOUS_ERRORS = fitz.TOOLS.mupdf_display_errors()
                except Exception:
                    _MUPDF_PREVIOUS_ERRORS = None
                try:
                    _MUPDF_PREVIOUS_WARNINGS = fitz.TOOLS.mupdf_display_warnings()
                except Exception:
                    _MUPDF_PREVIOUS_WARNINGS = None
                try:
                    fitz.TOOLS.reset_mupdf_warnings()
                except Exception:
                    pass
                try:
                    fitz.TOOLS.mupdf_display_errors(False)
                except Exception:
                    pass
                try:
                    fitz.TOOLS.mupdf_display_warnings(False)
                except Exception:
                    pass
            _MUPDF_DISPLAY_DEPTH += 1
        try:
            yield
        finally:
            with _MUPDF_DISPLAY_LOCK:
                _MUPDF_DISPLAY_DEPTH = max(0, int(_MUPDF_DISPLAY_DEPTH) - 1)
                if _MUPDF_DISPLAY_DEPTH == 0:
                    try:
                        fitz.TOOLS.mupdf_display_errors(_MUPDF_PREVIOUS_ERRORS)
                    except Exception:
                        pass
                    try:
                        fitz.TOOLS.mupdf_display_warnings(_MUPDF_PREVIOUS_WARNINGS)
                    except Exception:
                        pass


def ping_grobid(base_url: str) -> Dict[str, Any]:
    out = {
        "configured": bool(base_url),
        "reachable": False,
        "status": "not_configured",
        "url": base_url,
        "error": None,
    }
    if not base_url:
        return out
    if requests is None:
        out["status"] = "requests_unavailable"
        return out
    try:
        resp = requests.get(base_url.rstrip("/") + "/api/isalive", timeout=10)
        out["reachable"] = bool(resp.ok)
        out["status"] = "alive" if resp.ok else f"http_{resp.status_code}"
    except Exception as e:
        out["status"] = f"error:{type(e).__name__}"
        out["error"] = str(e)
    return out


def detect_capabilities(grobid_base_url: str) -> Dict[str, Any]:
    docling_available = _ensure_docling_imported()
    return {
        "generated_at_utc": utc_now_iso(),
        "runtime": runtime_env_snapshot(),
        "fitz_available": bool(fitz is not None),
        "fitz_version": pkg_version("PyMuPDF"),
        "pypdf_available": bool(PdfReader is not None),
        "pypdf_version": pkg_version("pypdf"),
        "docling_available": bool(docling_available),
        "docling_version": pkg_version("docling"),
        "requests_available": bool(requests is not None),
        "requests_version": pkg_version("requests"),
        "bs4_available": bool(BeautifulSoup is not None),
        "bs4_version": pkg_version("beautifulsoup4"),
        "optional_import_errors": dict(OPTIONAL_IMPORT_ERRORS),
        "grobid": ping_grobid(grobid_base_url),
    }


def required_phase_b_kernel_packages(options: PhaseBOptions) -> List[str]:
    packages = ["PyMuPDF", "pypdf"]
    if bool(options.try_docling):
        packages.append("docling")
    if bool(options.try_grobid):
        packages.extend(["requests", "beautifulsoup4"])
    return packages


def missing_phase_b_kernel_packages(capabilities: Dict[str, Any], options: PhaseBOptions) -> List[str]:
    missing: List[str] = []
    if not bool(capabilities.get("fitz_available")):
        missing.append("PyMuPDF")
    if not bool(capabilities.get("pypdf_available")):
        missing.append("pypdf")
    if bool(options.try_docling) and not bool(capabilities.get("docling_available")):
        missing.append("docling")
    if bool(options.try_grobid) and not bool(capabilities.get("requests_available")):
        missing.append("requests")
    if bool(options.try_grobid) and not bool(capabilities.get("bs4_available")):
        missing.append("beautifulsoup4")
    return missing


def compute_doc_id(manifest_row: Dict[str, Any], stable_hash_fn: Optional[Callable[..., str]] = None) -> str:
    stem = slugify(Path(manifest_row.get("file_name") or "document.pdf").stem, max_len=48)
    digest = str(manifest_row.get("sha256") or "")[:12]
    if not digest and stable_hash_fn is not None:
        digest = stable_hash_fn(stem, str(manifest_row.get("path") or ""), length=12)
    digest = digest or "docbundle0000"
    return f"{stem}-{digest}"


def flatten_pypdf_outline(reader: Any, outline: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    def walk(nodes: Any, level: int) -> None:
        for node in nodes or []:
            if isinstance(node, list):
                walk(node, level + 1)
                continue
            title = clean_text(getattr(node, "title", None) or str(node))
            page_num = None
            try:
                page_num = int(reader.get_destination_page_number(node)) + 1
            except Exception:
                page_num = None
            rows.append({"level": int(level), "title": title, "page": page_num})

    if isinstance(outline, list):
        walk(outline, 1)
    return rows


def extract_pypdf_bundle(path: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "available": bool(PdfReader is not None),
        "status": "unavailable",
        "page_count": None,
        "metadata": {},
        "outline": [],
        "error": None,
    }
    if PdfReader is None:
        return out
    try:
        reader = PdfReader(str(path))
        out["page_count"] = int(len(reader.pages))
        out["metadata"] = {str(k): str(v) for k, v in dict(reader.metadata or {}).items()}
        out["outline"] = flatten_pypdf_outline(reader, getattr(reader, "outline", []))
        out["status"] = "ok"
    except Exception as e:
        out["status"] = f"error:{type(e).__name__}"
        out["error"] = str(e)
    return out


def normalize_fitz_block(block: Any, page_num: int, block_idx: int) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "page": int(page_num),
        "block_index": int(block_idx),
        "x0": None,
        "y0": None,
        "x1": None,
        "y1": None,
        "text": "",
        "block_no": None,
        "block_type": None,
        "char_len": 0,
        "word_count": 0,
    }
    if isinstance(block, (list, tuple)):
        vals = list(block)
        if len(vals) >= 4:
            row["x0"], row["y0"], row["x1"], row["y1"] = [float(v) if v is not None else None for v in vals[:4]]
        if len(vals) >= 5:
            row["text"] = clean_text(vals[4])
        if len(vals) >= 6:
            row["block_no"] = vals[5]
        if len(vals) >= 7:
            row["block_type"] = vals[6]
    row["char_len"] = len(row["text"])
    row["word_count"] = count_words(row["text"])
    return row


def extract_fitz_bundle(path: Path, min_page_words: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "available": bool(fitz is not None),
        "status": "unavailable",
        "page_count": None,
        "metadata": {},
        "outline": [],
        "pages": [],
        "blocks": [],
        "warnings": [],
        "error": None,
    }
    if fitz is None:
        return out
    native_warnings: List[str] = []
    try:
        with muted_mupdf_messages():
            with fitz.open(path) as doc:
                out["page_count"] = int(doc.page_count)
                out["metadata"] = {str(k): str(v) for k, v in dict(doc.metadata or {}).items()}
                try:
                    toc = doc.get_toc(simple=True) or []
                except Exception:
                    toc = []
                out["outline"] = [
                    {
                        "level": int(item[0]),
                        "title": clean_text(item[1]),
                        "page": int(item[2]) if len(item) > 2 and item[2] is not None else None,
                    }
                    for item in toc
                ]
                for page_index in range(doc.page_count):
                    page = doc[page_index]
                    try:
                        page_text = clean_text(page.get_text("text", sort=True))
                    except TypeError:
                        page_text = clean_text(page.get_text("text"))
                    page_word_count = count_words(page_text)
                    try:
                        raw_blocks = page.get_text("blocks", sort=True)
                    except TypeError:
                        raw_blocks = page.get_text("blocks")

                    block_rows = []
                    for block_idx, block in enumerate(raw_blocks or []):
                        row = normalize_fitz_block(block, page_index + 1, block_idx)
                        if row["text"]:
                            block_rows.append(row)
                    out["blocks"].extend(block_rows)
                    out["pages"].append(
                        {
                            "page": int(page_index + 1),
                            "text": page_text,
                            "char_len": len(page_text),
                            "word_count": page_word_count,
                            "has_text": bool(page_word_count > 0),
                            "has_substantive_text": bool(page_word_count >= int(min_page_words)),
                        }
                    )
            native_warnings = consume_mupdf_messages()
        out["status"] = "ok"
    except Exception as e:
        native_warnings = consume_mupdf_messages()
        out["status"] = f"error:{type(e).__name__}"
        out["error"] = str(e)
    out["warnings"] = unique_nonempty_texts(native_warnings)
    return out


_DOCLING_CONVERTER_CACHE: Dict[Any, Any] = {}


def _docling_converter_cache_key(options: PhaseBOptions, *, num_threads: Optional[int] = None) -> tuple[Any, ...]:
    return (
        bool(options.docling_do_ocr),
        bool(options.docling_do_table_structure),
        None if options.docling_document_timeout_sec is None else int(options.docling_document_timeout_sec),
        int(num_threads if num_threads is not None else options.docling_num_threads),
        int(threading.get_ident()),
    )


def get_docling_converter(options: PhaseBOptions, *, num_threads: Optional[int] = None) -> Any:
    if not _ensure_docling_imported():
        return None
    if DocumentConverter is None or PdfPipelineOptions is None or PdfFormatOption is None or InputFormat is None:
        return None
    key = _docling_converter_cache_key(options, num_threads=num_threads)
    cached = _DOCLING_CONVERTER_CACHE.get(key)
    if cached is not None:
        return cached

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = bool(options.docling_do_ocr)
    pipeline_options.do_table_structure = bool(options.docling_do_table_structure)
    pipeline_options.generate_page_images = False
    pipeline_options.generate_picture_images = False
    pipeline_options.generate_table_images = False
    pipeline_options.enable_remote_services = False
    pipeline_options.allow_external_plugins = False
    pipeline_options.document_timeout = None if options.docling_document_timeout_sec is None else int(options.docling_document_timeout_sec)
    try:
        pipeline_options.accelerator_options.num_threads = int(num_threads if num_threads is not None else options.docling_num_threads)
    except Exception:
        pass

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
            )
        }
    )
    _DOCLING_CONVERTER_CACHE[key] = converter
    return converter


def summarize_docling_confidence(confidence_payload: Any) -> Dict[str, Any]:
    payload = confidence_payload if isinstance(confidence_payload, dict) else {}
    return {
        "mean_grade": payload.get("mean_grade"),
        "low_grade": payload.get("low_grade"),
        "very_low_grade": payload.get("very_low_grade"),
    }


DOCLING_SUCCESS_STATUSES = {"success", "partial_success"}
DOCLING_GRADE_RANK = {
    "very_low": 0,
    "poor": 1,
    "fair": 2,
    "good": 3,
    "excellent": 4,
    "unspecified": -1,
    None: -1,
}


def normalize_docling_status_value(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "." in text:
        text = text.split(".")[-1]
    return text


def should_export_docling_document(status: Any) -> bool:
    return normalize_docling_status_value(status) in DOCLING_SUCCESS_STATUSES


def simplify_docling_text_item(item: Dict[str, Any], *, self_ref: Optional[str] = None) -> Dict[str, Any]:
    return {
        "self_ref": self_ref if self_ref is not None else item.get("self_ref"),
        "label": item.get("label"),
        "text": item.get("text"),
        "orig": item.get("orig"),
        "prov": json_safe(item.get("prov") or []),
    }


def extract_docling_section_headers(document_payload: Any) -> List[Dict[str, Any]]:
    doc = document_payload if isinstance(document_payload, dict) else {}
    texts = doc.get("texts") or []
    headers: List[Dict[str, Any]] = []
    for idx, item in enumerate(texts):
        if str(item.get("label") or "") != "section_header":
            continue
        headers.append(simplify_docling_text_item(item, self_ref=f"#/texts/{idx}"))
    return headers


def build_docling_document_summary(document_payload: Any) -> Dict[str, Any]:
    doc = document_payload if isinstance(document_payload, dict) else {}
    texts = doc.get("texts") or []
    pages = doc.get("pages") or {}
    label_counts: Dict[str, int] = {}
    for item in texts:
        label = str(item.get("label") or "unspecified")
        label_counts[label] = int(label_counts.get(label) or 0) + 1
    section_headers = label_counts.get("section_header") or 0
    return {
        "page_count": len(pages),
        "text_item_count": len(texts),
        "section_header_count": int(section_headers),
        "label_counts": label_counts,
    }


def docling_grade_rank(value: Any) -> int:
    return int(DOCLING_GRADE_RANK.get(str(value).strip().lower() if value is not None else None, -1))


def combine_docling_grade(values: List[Any]) -> Optional[str]:
    normalized = [str(v).strip().lower() for v in values if docling_grade_rank(v) >= 0]
    if not normalized:
        return None
    return min(normalized, key=docling_grade_rank)


def chunk_docling_page_ranges(page_count: int, chunk_size: int) -> List[tuple[int, int]]:
    ranges: List[tuple[int, int]] = []
    start = 1
    while start <= int(page_count):
        end = min(int(page_count), start + int(chunk_size) - 1)
        ranges.append((int(start), int(end)))
        start = end + 1
    return ranges


def summarize_docling_attempt(bundle: Dict[str, Any], *, page_range: Optional[tuple[int, int]] = None, mode: str = "single") -> Dict[str, Any]:
    document_summary = bundle.get("document_summary") or {}
    return {
        "mode": str(mode),
        "page_range": list(page_range) if page_range else None,
        "status": bundle.get("status"),
        "error": short_blob(str(bundle.get("error") or ""), max_len=600) or None,
        "stderr": short_blob(str(bundle.get("stderr") or ""), max_len=1200) or None,
        "warning_count": len(bundle.get("warnings") or []),
        "confidence_summary": bundle.get("confidence_summary"),
        "section_header_count": int(document_summary.get("section_header_count") or len(bundle.get("section_headers") or [])),
        "page_count": int(document_summary.get("page_count") or 0),
        "text_item_count": int(document_summary.get("text_item_count") or 0),
        "has_document": bool(bundle.get("document")),
    }


def docling_bundle_score(bundle: Dict[str, Any]) -> tuple[int, int, int, int]:
    status = normalize_docling_status_value(bundle.get("status"))
    status_rank = {
        "success": 4,
        "partial_success": 3,
        "failure": 2,
        "error": 1,
        "unavailable": 0,
        "disabled": 0,
        "skipped_page_limit": 0,
    }.get(status, 0)
    document_summary = bundle.get("document_summary") or {}
    return (
        int(status_rank),
        int(document_summary.get("section_header_count") or len(bundle.get("section_headers") or [])),
        int(document_summary.get("page_count") or 0),
        1 if bundle.get("document") else 0,
    )


def run_docling_single_attempt(
    path: Path,
    options: PhaseBOptions,
    *,
    max_num_pages: int,
    page_range: Optional[tuple[int, int]] = None,
    num_threads: Optional[int] = None,
) -> Dict[str, Any]:
    docling_available = _ensure_docling_imported()
    out: Dict[str, Any] = {
        "available": bool(docling_available),
        "enabled": bool(options.try_docling),
        "status": "unavailable",
        "error": None,
        "stdout": "",
        "stderr": "",
        "warnings": [],
        "result": None,
        "document": None,
        "markdown_preview": None,
        "confidence_summary": None,
        "section_headers": [],
        "document_summary": {},
    }
    if not docling_available or DocumentConverter is None:
        return out
    if not bool(options.try_docling):
        out["status"] = "disabled"
        return out
    native_warnings: List[str] = []
    try:
        convert_kwargs: Dict[str, Any] = {
            "raises_on_error": False,
            "max_num_pages": int(max_num_pages),
            "max_file_size": int(options.docling_max_file_size_bytes),
        }
        if page_range is not None:
            convert_kwargs["page_range"] = page_range
        with muted_mupdf_messages():
            captured = capture_python_noise(
                lambda: get_docling_converter(options, num_threads=num_threads).convert(
                    path,
                    **convert_kwargs,
                )
            )
            native_warnings = consume_mupdf_messages()
        res = captured["result"]
        out["stdout"] = captured["stdout"]
        out["stderr"] = captured["stderr"]
        out["warnings"] = unique_nonempty_texts(list(captured["warnings"] or []) + native_warnings)
        raw_dump = json_safe(res.model_dump()) if hasattr(res, "model_dump") else None
        out["result"] = {
            "status": raw_dump.get("status") if isinstance(raw_dump, dict) else None,
            "errors": raw_dump.get("errors") if isinstance(raw_dump, dict) else None,
            "input": raw_dump.get("input") if isinstance(raw_dump, dict) else None,
            "timings": raw_dump.get("timings") if isinstance(raw_dump, dict) else None,
            "confidence": raw_dump.get("confidence") if isinstance(raw_dump, dict) else None,
        }
        out["confidence_summary"] = summarize_docling_confidence(out["result"].get("confidence"))
        out["status"] = normalize_docling_status_value(out["result"].get("status") or "unknown")
        doc = getattr(res, "document", None)
        if doc is not None and should_export_docling_document(out["status"]):
            exported = json_safe(doc.export_to_dict())
            out["document"] = exported
            out["section_headers"] = extract_docling_section_headers(exported)
            out["document_summary"] = build_docling_document_summary(exported)
            try:
                out["markdown_preview"] = short_blob(doc.export_to_markdown(), max_len=8000)
            except Exception:
                out["markdown_preview"] = None
    except Exception as e:
        native_warnings = consume_mupdf_messages()
        out["status"] = "error"
        out["error"] = str(e)
        out["stderr"] = short_blob(traceback.format_exc())
        out["warnings"] = unique_nonempty_texts(list(out.get("warnings") or []) + native_warnings)
    return out


def run_docling_chunked_attempt(path: Path, page_count: int, options: PhaseBOptions, *, trigger_status: str) -> Dict[str, Any]:
    chunk_ranges = chunk_docling_page_ranges(int(page_count), int(options.docling_chunk_size))
    chunk_summaries: List[Dict[str, Any]] = []
    chunk_documents: List[Dict[str, Any]] = []
    chunk_section_headers: List[Dict[str, Any]] = []
    aggregated_errors: List[Any] = []
    aggregated_warnings: List[str] = []
    aggregated_stderr: List[str] = []
    aggregated_stdout: List[str] = []
    all_statuses: List[str] = []
    confidence_summaries: List[Dict[str, Any]] = []

    for idx, page_range in enumerate(chunk_ranges):
        bundle = run_docling_single_attempt(
            path,
            options,
            max_num_pages=max(int(options.docling_page_limit), int(page_count)),
            page_range=page_range,
            num_threads=int(options.docling_chunk_num_threads),
        )
        status = normalize_docling_status_value(bundle.get("status"))
        all_statuses.append(status)
        if bundle.get("result") and isinstance(bundle.get("result"), dict):
            aggregated_errors.extend(list(bundle["result"].get("errors") or []))
        aggregated_warnings.extend([str(x) for x in (bundle.get("warnings") or []) if str(x).strip()])
        if bundle.get("stderr"):
            aggregated_stderr.append(short_blob(str(bundle.get("stderr")), max_len=1200))
        if bundle.get("stdout"):
            aggregated_stdout.append(short_blob(str(bundle.get("stdout")), max_len=1200))
        if bundle.get("confidence_summary"):
            confidence_summaries.append(dict(bundle["confidence_summary"]))
        if bundle.get("document"):
            chunk_documents.append(dict(bundle["document"]))
        chunk_section_headers.extend(list(bundle.get("section_headers") or []))
        chunk_summaries.append(
            {
                "chunk_index": int(idx),
                **summarize_docling_attempt(bundle, page_range=page_range, mode="chunk"),
            }
        )
        if status not in DOCLING_SUCCESS_STATUSES and not bundle.get("document"):
            if idx == 0 and page_count > int(options.docling_page_limit):
                break

    header_seen = set()
    merged_header_texts: List[Dict[str, Any]] = []
    for header in chunk_section_headers:
        text = clean_text(header.get("text"))
        prov = header.get("prov") or []
        page_no = None
        if prov and isinstance(prov[0], dict):
            page_no = prov[0].get("page_no")
        key = (text.lower(), int(page_no) if page_no else None)
        if not text or key in header_seen:
            continue
        header_seen.add(key)
        merged_header_texts.append(simplify_docling_text_item(header, self_ref=f"#/texts/{len(merged_header_texts)}"))

    merged_pages: Dict[str, Any] = {}
    for doc in chunk_documents:
        for key, value in (doc.get("pages") or {}).items():
            merged_pages[str(key)] = value

    merged_document = None
    if merged_header_texts:
        merged_document = {
            "schema_name": "DoclingSectionHeaderAggregate",
            "version": "1.0",
            "name": path.stem,
            "origin": {
                "mimetype": "application/pdf",
                "filename": path.name,
            },
            "pages": merged_pages,
            "texts": merged_header_texts,
            "chunk_ranges": [list(rng) for rng in chunk_ranges[: len(chunk_summaries)]],
        }

    if all(status == "success" for status in all_statuses[: len(chunk_summaries)]) and chunk_summaries:
        overall_status = "success"
    elif any(status in DOCLING_SUCCESS_STATUSES for status in all_statuses):
        overall_status = "partial_success"
    else:
        overall_status = "failure"

    confidence_summary = {
        "mean_grade": combine_docling_grade([row.get("mean_grade") for row in confidence_summaries]),
        "low_grade": combine_docling_grade([row.get("low_grade") for row in confidence_summaries]),
        "very_low_grade": combine_docling_grade([row.get("very_low_grade") for row in confidence_summaries]),
    }

    markdown_preview = None
    if merged_header_texts:
        markdown_preview = short_blob("\n".join(f"## {item.get('text')}" for item in merged_header_texts[:80]), max_len=8000)

    return {
        "available": True,
        "enabled": True,
        "status": overall_status,
        "error": None if overall_status in DOCLING_SUCCESS_STATUSES else "chunked docling did not produce a success-like result",
        "stdout": short_blob("\n\n".join(aggregated_stdout), max_len=12000),
        "stderr": short_blob("\n\n".join(aggregated_stderr), max_len=12000),
        "warnings": list(dict.fromkeys(aggregated_warnings)),
        "result": {
            "status": overall_status,
            "errors": aggregated_errors,
            "input": {
                "file": str(path),
                "valid": bool(chunk_summaries and any(row.get("has_document") for row in chunk_summaries)),
                "page_count": int(page_count),
                "chunk_ranges": [list(rng) for rng in chunk_ranges[: len(chunk_summaries)]],
                "mode": "chunked",
            },
            "timings": {
                "chunk_count": len(chunk_summaries),
            },
            "confidence": confidence_summary,
        },
        "document": merged_document,
        "markdown_preview": markdown_preview,
        "confidence_summary": confidence_summary,
        "section_headers": merged_header_texts,
        "document_summary": build_docling_document_summary(merged_document),
        "chunking": {
            "trigger_status": str(trigger_status),
            "chunk_size": int(options.docling_chunk_size),
            "chunk_count": len(chunk_summaries),
            "max_pages": int(page_count),
            "num_threads": int(options.docling_chunk_num_threads),
            "chunks": chunk_summaries,
        },
    }


def extract_docling_bundle(path: Path, page_count: Optional[int], options: PhaseBOptions) -> Dict[str, Any]:
    docling_available = _ensure_docling_imported()
    out: Dict[str, Any] = {
        "available": bool(docling_available),
        "enabled": False,
        "status": "unavailable",
        "error": None,
        "stdout": "",
        "stderr": "",
        "warnings": [],
        "result": None,
        "document": None,
        "markdown_preview": None,
        "confidence_summary": None,
        "section_headers": [],
        "document_summary": {},
        "selected_mode": "none",
        "attempts": [],
        "chunking": None,
    }
    if not docling_available or DocumentConverter is None:
        return out
    if not bool(options.try_docling):
        out["status"] = "disabled"
        return out

    out["enabled"] = True
    if page_count and int(page_count) > int(options.docling_page_limit):
        if not bool(options.docling_enable_chunking):
            out["status"] = "skipped_page_limit"
            out["error"] = f"page_count={page_count} exceeds docling_page_limit={options.docling_page_limit}"
            return out
        if int(page_count) > int(options.docling_chunk_max_pages):
            out["status"] = "skipped_page_limit"
            out["error"] = (
                f"page_count={page_count} exceeds docling_page_limit={options.docling_page_limit} "
                f"and docling_chunk_max_pages={options.docling_chunk_max_pages}"
            )
            return out
        chunked = run_docling_chunked_attempt(path, int(page_count), options, trigger_status="skipped_page_limit")
        out.update(chunked)
        out["selected_mode"] = "chunked"
        out["attempts"] = [summarize_docling_attempt(chunked, mode="chunked_selected")]
        return out

    single = run_docling_single_attempt(
        path,
        options,
        max_num_pages=int(options.docling_page_limit),
        num_threads=int(options.docling_num_threads),
    )
    out.update(single)
    out["selected_mode"] = "single"
    out["attempts"] = [summarize_docling_attempt(single, mode="single_initial")]

    should_retry = bool(
        options.docling_enable_chunking
        and page_count
        and int(page_count) >= max(2, int(options.docling_chunk_size))
        and int(page_count) <= int(options.docling_chunk_max_pages)
        and normalize_docling_status_value(single.get("status")) in {"failure", "partial_success", "error"}
    )
    if should_retry:
        chunked = run_docling_chunked_attempt(path, int(page_count), options, trigger_status=str(single.get("status") or ""))
        out["chunking"] = chunked.get("chunking")
        out["attempts"].append(summarize_docling_attempt(chunked, mode="chunked_retry"))
        if docling_bundle_score(chunked) >= docling_bundle_score(single):
            for key in [
                "status",
                "error",
                "stdout",
                "stderr",
                "warnings",
                "result",
                "document",
                "markdown_preview",
                "confidence_summary",
                "section_headers",
                "document_summary",
                "chunking",
            ]:
                out[key] = chunked.get(key)
            out["selected_mode"] = "chunked"
    return out


def should_try_grobid(
    manifest_row: Dict[str, Any],
    page_count: Optional[int],
    options: PhaseBOptions,
    capabilities: Dict[str, Any],
) -> tuple[bool, str]:
    if not bool(options.try_grobid):
        return False, "disabled"
    grobid = capabilities.get("grobid", {})
    if not bool(grobid.get("configured")):
        return False, "not_configured"
    if not bool(grobid.get("reachable")):
        return False, f"service_{grobid.get('status') or 'unreachable'}"
    if page_count and int(page_count) > int(options.grobid_page_limit):
        return False, "skipped_page_limit"
    return True, "pdf_under_page_limit"


def summarize_grobid_xml(xml_text: str) -> Dict[str, Any]:
    xml_text = str(xml_text or "")
    if not xml_text:
        return {"status": "empty"}
    if BeautifulSoup is None:
        return {"status": "bs4_unavailable"}
    try:
        soup = BeautifulSoup(xml_text, "xml")
        head_texts = []
        for tag in soup.find_all("head"):
            txt = clean_text(tag.get_text(" ", strip=True))
            if txt:
                head_texts.append(txt)
        title_tag = soup.find("title")
        return {
            "status": "ok",
            "title": clean_text(title_tag.get_text(" ", strip=True)) if title_tag else None,
            "section_head_count": len(head_texts),
            "section_head_preview": head_texts[:15],
            "has_abstract": bool(soup.find("abstract")),
            "has_bibliography": bool(soup.find("listBibl")),
        }
    except Exception as e:
        return {"status": f"error:{type(e).__name__}", "error": str(e)}


def extract_grobid_bundle(
    path: Path,
    manifest_row: Dict[str, Any],
    page_count: Optional[int],
    options: PhaseBOptions,
    capabilities: Dict[str, Any],
) -> Dict[str, Any]:
    enabled, reason = should_try_grobid(manifest_row, page_count, options, capabilities)
    out: Dict[str, Any] = {
        "available": bool(requests is not None),
        "enabled": bool(enabled),
        "status": "not_attempted",
        "reason": reason,
        "error": None,
        "xml_text": None,
        "summary": None,
    }
    if not enabled:
        out["status"] = reason
        return out
    try:
        with path.open("rb") as f:
            response = requests.post(
                options.grobid_base_url.rstrip("/") + options.grobid_process_path,
                files={"input": (path.name, f, "application/pdf")},
                data={
                    "consolidateHeader": str(int(options.grobid_consolidate_header)),
                    "consolidateCitations": str(int(options.grobid_consolidate_citations)),
                    "includeRawCitations": str(int(options.grobid_include_raw_citations)),
                },
                timeout=int(options.grobid_timeout_sec),
            )
        if not response.ok:
            out["status"] = f"http_{response.status_code}"
            out["error"] = short_blob(response.text, max_len=4000)
            return out
        xml_text = response.text or ""
        out["xml_text"] = xml_text
        out["summary"] = summarize_grobid_xml(xml_text)
        out["status"] = "ok" if xml_text.strip() else "empty_response"
    except Exception as e:
        out["status"] = f"error:{type(e).__name__}"
        out["error"] = str(e)
    return out


def _docling_success_like(status: Any) -> bool:
    return str(status or "") in {"success", "partial_success"}


def compute_phase_b_counts(
    summary_rows: List[Dict[str, Any]],
    capabilities: Dict[str, Any],
    selected_count: int,
    failed_doc_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    failed_doc_ids = [str(doc_id) for doc_id in (failed_doc_ids or []) if str(doc_id)]
    low_coverage_docs = [
        row["doc_id"]
        for row in summary_rows
        if row.get("pages_with_text_pct") is None or float(row.get("pages_with_text_pct") or 0.0) < 50.0
    ]
    unreadable_docs = [row["doc_id"] for row in summary_rows if not row.get("readable_without_ocr")]
    cached_docs = [row["doc_id"] for row in summary_rows if row.get("cached")]
    runtime_capability_mismatch_docs = [row["doc_id"] for row in summary_rows if row.get("runtime_capability_mismatch")]
    fallback_docs = [row["doc_id"] for row in summary_rows if row.get("fallback_activated")]
    docling_success_like_docs = [row["doc_id"] for row in summary_rows if _docling_success_like(row.get("docling_status"))]
    docling_success_docs = [row["doc_id"] for row in summary_rows if str(row.get("docling_status") or "") == "success"]
    docling_partial_docs = [row["doc_id"] for row in summary_rows if str(row.get("docling_status") or "") == "partial_success"]
    docling_skipped_page_limit_docs = [row["doc_id"] for row in summary_rows if str(row.get("docling_status") or "") == "skipped_page_limit"]
    docling_chunk_selected_docs = [row["doc_id"] for row in summary_rows if str(row.get("docling_mode") or "") == "chunked"]
    docling_headerless_docs = [row["doc_id"] for row in summary_rows if _docling_success_like(row.get("docling_status")) and int(row.get("docling_section_header_count") or 0) == 0]
    grobid_ok_docs = [row["doc_id"] for row in summary_rows if str(row.get("grobid_status") or "") == "ok"]
    outline_docs = [row["doc_id"] for row in summary_rows if int(row.get("outline_count") or 0) > 0]

    return {
        "selected_count": int(selected_count),
        "documents_processed": len(summary_rows),
        "bundle_failure_count": len(failed_doc_ids),
        "bundle_failure_doc_ids": failed_doc_ids,
        "fitz_available": bool(capabilities.get("fitz_available")),
        "pypdf_available": bool(capabilities.get("pypdf_available")),
        "docling_available": bool(capabilities.get("docling_available")),
        "grobid_configured": bool(capabilities.get("grobid", {}).get("configured")),
        "grobid_reachable": bool(capabilities.get("grobid", {}).get("reachable")),
        "readable_without_ocr_count": sum(1 for row in summary_rows if row.get("readable_without_ocr")),
        "unreadable_without_ocr_count": len(unreadable_docs),
        "unreadable_without_ocr_docs": unreadable_docs,
        "low_text_coverage_count": len(low_coverage_docs),
        "low_text_coverage_docs": low_coverage_docs,
        "cached_doc_count": len(cached_docs),
        "cached_doc_ids": cached_docs,
        "runtime_capability_mismatch_count": len(runtime_capability_mismatch_docs),
        "runtime_capability_mismatch_docs": runtime_capability_mismatch_docs,
        "fallback_activated_count": len(fallback_docs),
        "fallback_activated_docs": fallback_docs,
        "docling_success_like_count": len(docling_success_like_docs),
        "docling_success_count": len(docling_success_docs),
        "docling_partial_success_count": len(docling_partial_docs),
        "docling_skipped_page_limit_count": len(docling_skipped_page_limit_docs),
        "docling_skipped_page_limit_docs": docling_skipped_page_limit_docs,
        "docling_chunk_selected_count": len(docling_chunk_selected_docs),
        "docling_chunk_selected_docs": docling_chunk_selected_docs,
        "docling_success_without_headers_count": len(docling_headerless_docs),
        "docling_success_without_headers_docs": docling_headerless_docs,
        "grobid_success_count": len(grobid_ok_docs),
        "outline_doc_count": len(outline_docs),
    }


def build_phase_b_assessment(
    summary_rows: List[Dict[str, Any]],
    capabilities: Dict[str, Any],
    selected_count: int,
    failed_doc_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    counts = compute_phase_b_counts(summary_rows, capabilities, selected_count, failed_doc_ids=failed_doc_ids)
    failures: List[str] = []
    warnings_list: List[str] = []
    infos: List[str] = []
    next_actions: List[str] = []

    if not counts["fitz_available"]:
        failures.append("PyMuPDF is unavailable. Phase B cannot satisfy the deterministic fallback contract.")
        next_actions.append("Install PyMuPDF in the notebook kernel and rerun Phase B.")
    if counts["documents_processed"] <= 0:
        failures.append(
            f"Phase B did not produce any parser bundles for the {counts['selected_count']} selected PDFs."
        )
        next_actions.append("Inspect parser logs and diagnostics for missing bundle outputs.")
    elif counts["bundle_failure_count"] > 0:
        warnings_list.append(
            f"{counts['bundle_failure_count']} selected PDF(s) failed during parser bundle creation and were skipped."
        )
        next_actions.append("Inspect parser logs and diagnostics for the failed PDFs before trusting full coverage.")
    if counts["unreadable_without_ocr_count"] >= counts["documents_processed"] and counts["documents_processed"] > 0:
        failures.append(
            f"All {counts['unreadable_without_ocr_count']} processed PDF(s) were not readable without OCR in a digital-only benchmark."
        )
        next_actions.append("Inspect the unreadable PDFs and confirm they are digitally extractable.")
    elif counts["unreadable_without_ocr_count"] > 0:
        warnings_list.append(
            f"{counts['unreadable_without_ocr_count']} processed PDF(s) were not readable without OCR and were kept only as partial coverage."
        )
        next_actions.append("Inspect the unreadable PDFs and confirm they are digitally extractable.")

    if not counts["pypdf_available"]:
        warnings_list.append("pypdf is unavailable in the current notebook runtime, so independent outline validation is missing.")
        next_actions.append("Install pypdf in the notebook kernel and inspect phase_b_runtime.json if the kernel path is unclear.")
    if not counts["docling_available"]:
        warnings_list.append("Docling is unavailable in the current notebook runtime.")
        next_actions.append("Install docling in the notebook kernel and inspect phase_b_runtime.json if the kernel path is unclear.")
    if counts["docling_success_like_count"] < max(1, counts["documents_processed"] // 2):
        warnings_list.append(
            "Docling succeeded only on a minority of documents, so Phase C will lean heavily on fallback structure signals."
        )
        next_actions.append("Review docling.json diagnostics and consider adjusting page limits or runtime setup.")
    if counts["docling_skipped_page_limit_count"] > 0:
        warnings_list.append(
            f"Docling was skipped on {counts['docling_skipped_page_limit_count']} document(s) because they exceeded the configured page limit."
        )
        next_actions.append("For long documents, decide explicitly whether outline-first fallback is acceptable or whether a split-parse strategy is needed.")
    if counts["docling_chunk_selected_count"] > 0:
        infos.append(f"Chunked Docling recovery was selected for {counts['docling_chunk_selected_count']} document(s).")
    if counts["docling_success_without_headers_count"] > 0:
        warnings_list.append(
            f"{counts['docling_success_without_headers_count']} Docling success-like document(s) still produced zero section headers."
        )
        next_actions.append("Inspect docling.json section_headers and fall back to outlines or heuristic headings for headerless docs.")
    if counts["low_text_coverage_count"] > 0:
        warnings_list.append(
            f"{counts['low_text_coverage_count']} PDF(s) had low extracted text coverage and may carry weak section evidence."
        )
        next_actions.append("Inspect pymupdf_pages.jsonl for low-coverage documents before Phase C.")
    if counts["fallback_activated_count"] > 0:
        warnings_list.append(
            f"Fallback parsing was activated for {counts['fallback_activated_count']} document(s)."
        )
    if counts["runtime_capability_mismatch_count"] > 0:
        warnings_list.append(
            "Some cached parser bundles were created under a different runtime capability profile than the current notebook session."
        )
        next_actions.append("Set force_rebuild=True for Phase B if you need a clean run under the current environment.")
    if not counts["grobid_configured"]:
        warnings_list.append("GROBID is not configured, so the scholarly enhancement lane is absent.")
        next_actions.append("Configure GROBID_URL or GROBID_BASE_URL if you want TEI structure recovery.")
    elif not counts["grobid_reachable"]:
        warnings_list.append("GROBID is configured but not reachable.")
        next_actions.append("Start or fix the GROBID service before rerunning Phase B.")

    if counts["outline_doc_count"] > 0:
        infos.append(f"{counts['outline_doc_count']} PDF(s) expose outline/bookmark structure already.")
    if counts["readable_without_ocr_count"] == counts["documents_processed"] and counts["documents_processed"] > 0:
        infos.append("All processed PDFs were readable without OCR.")

    if failures:
        status = "fail"
        quality_band = "degraded"
        can_continue = False
    elif warnings_list:
        status = "success_with_warnings"
        quality_band = "acceptable_with_issues"
        can_continue = True
    else:
        status = "success"
        quality_band = "strong"
        can_continue = True

    warnings_list = list(dict.fromkeys(warnings_list))
    next_actions = list(dict.fromkeys(next_actions))
    infos = list(dict.fromkeys(infos))

    return {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_b",
        "status": status,
        "quality_band": quality_band,
        "can_continue_to_next_phase": bool(can_continue),
        "failures": failures,
        "warnings": warnings_list,
        "info": infos,
        "recommended_next_actions": next_actions,
        "counts": counts,
    }


def build_qc_rows(
    summary_rows: List[Dict[str, Any]],
    capabilities: Dict[str, Any],
    selected_count: int,
    failed_doc_ids: Optional[List[str]] = None,
    assessment: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    def qc_row(check: str, status: str, value: Any, expected: str, why: str, fix: str) -> Dict[str, Any]:
        return {
            "check": str(check),
            "status": str(status),
            "value": str(value),
            "expected": str(expected),
            "why": str(why),
            "fix": str(fix),
        }

    counts = (
        assessment or build_phase_b_assessment(summary_rows, capabilities, selected_count, failed_doc_ids=failed_doc_ids)
    ).get("counts", {})
    low_coverage_docs = list(counts.get("low_text_coverage_docs") or [])
    unreadable_docs = list(counts.get("unreadable_without_ocr_docs") or [])
    docling_success_count = int(counts.get("docling_success_count") or 0)
    headerless_docs = list(counts.get("docling_success_without_headers_docs") or [])

    qc_rows = []
    qc_rows.append(
        qc_row(
            "documents_processed",
            "OK" if int(counts.get("documents_processed") or 0) >= 1 else "FAIL",
            counts.get("documents_processed"),
            f">= 1 of {selected_count}",
            "at least one selected PDF must emit a parser bundle or the pipeline cannot continue",
            "inspect diagnostics.json for any missing document output",
        )
    )
    qc_rows.append(
        qc_row(
            "bundle_failures",
            "OK" if int(counts.get("bundle_failure_count") or 0) == 0 else "WARN",
            counts.get("bundle_failure_count"),
            "0",
            "per-document parser failures reduce coverage but should not block the run when other PDFs succeed",
            "inspect diagnostics.json and docling.json for the failed PDFs",
        )
    )
    qc_rows.append(
        qc_row(
            "fitz_available",
            "OK" if bool(capabilities.get("fitz_available")) else "FAIL",
            bool(capabilities.get("fitz_available")),
            "True",
            "PyMuPDF is the deterministic fallback and text-coverage lane",
            "install PyMuPDF before rerunning Phase B",
        )
    )
    qc_rows.append(
        qc_row(
            "pypdf_available",
            "OK" if bool(capabilities.get("pypdf_available")) else "WARN",
            bool(capabilities.get("pypdf_available")),
            "True",
            "pypdf provides an independent metadata and outline lane",
            "install pypdf before rerunning Phase B",
        )
    )
    qc_rows.append(
        qc_row(
            "unreadable_without_ocr",
            "OK" if not unreadable_docs else "WARN",
            "none" if not unreadable_docs else ", ".join(unreadable_docs[:4]),
            "none",
            "this benchmark is restricted to digital PDFs with extractable text",
            "inspect diagnostics for any document flagged as unreadable",
        )
    )
    qc_rows.append(
        qc_row(
            "low_text_coverage_docs",
            "OK" if not low_coverage_docs else "WARN",
            "none" if not low_coverage_docs else ", ".join(low_coverage_docs[:4]),
            "none below 50% page text coverage",
            "low coverage usually indicates parser trouble or image-heavy pages",
            "inspect pymupdf_pages.jsonl and diagnostics for the affected PDFs",
        )
    )
    qc_rows.append(
        qc_row(
            "cache_runtime_mismatch",
            "OK" if int(counts.get("runtime_capability_mismatch_count") or 0) == 0 else "WARN",
            counts.get("runtime_capability_mismatch_count"),
            "0",
            "cached results from a different runtime can make the phase look healthier than the current kernel supports",
            "set force_rebuild=True for a clean run under the current environment",
        )
    )
    qc_rows.append(
        qc_row(
            "docling_success_count",
            "OK" if docling_success_count >= 1 else "WARN",
            docling_success_count,
            ">= 1 on a healthy environment, otherwise fallback path must carry",
            "Docling is the preferred structure-aware parser when it works",
            "inspect docling.json stdout/stderr and consider tuning page limits or environment setup",
        )
    )
    qc_rows.append(
        qc_row(
            "docling_headerless_success_docs",
            "OK" if not headerless_docs else "WARN",
            "none" if not headerless_docs else ", ".join(headerless_docs[:4]),
            "none",
            "Docling is only valuable for Phase C if it emits section headers or other usable structure",
            "inspect docling.json section_headers and rely on outline or heuristic headings where Docling stays headerless",
        )
    )
    qc_rows.append(
        qc_row(
            "grobid_service",
            "OK" if bool(capabilities.get("grobid", {}).get("reachable")) else "WARN",
            capabilities.get("grobid", {}).get("status"),
            "alive when scholarly enhancement is configured",
            "GROBID is optional but valuable for article/report structure recovery",
            "start a GROBID service and set GROBID_URL or GROBID_BASE_URL",
        )
    )
    if assessment is not None:
        qc_rows.append(
            qc_row(
                "phase_b_status",
                "OK" if assessment.get("status") == "success" else ("WARN" if assessment.get("status") == "success_with_warnings" else "FAIL"),
                assessment.get("status"),
                "success or success_with_warnings",
                "this is the persisted phase-level verdict used to judge whether the stage is healthy enough to continue",
                "inspect phase_b_assessment.json and the document diagnostics before continuing",
            )
        )
    return qc_rows


def resolve_phase_b_doc_concurrency(options: PhaseBOptions, *, capabilities: Dict[str, Any], doc_count: int) -> int:
    if int(doc_count) <= 1:
        return 1
    if options.max_concurrent_docs is not None:
        return max(1, min(int(doc_count), int(options.max_concurrent_docs)))

    cpu_count = available_cpu_count()
    if bool(options.try_docling) and bool(capabilities.get("docling_available")):
        per_doc_threads = max(1, int(options.docling_num_threads), int(options.docling_chunk_num_threads))
        auto = max(1, cpu_count // per_doc_threads)
        # Docling becomes unstable when too many PDFs are parsed in parallel.
        # Keep auto-sizing compute-aware, but cap it conservatively for stability.
        return max(1, min(int(doc_count), min(auto, 2)))
    return max(1, min(int(doc_count), min(cpu_count, 6)))


def build_phase_b_document_bundle(
    *,
    run_ctx: Any,
    parser_dir: Path,
    manifest_row: Dict[str, Any],
    options: PhaseBOptions,
    capabilities: Dict[str, Any],
) -> Dict[str, Any]:
    doc_id = str(manifest_row["doc_id"])
    source_path = Path(str(manifest_row["path"])).resolve()
    doc_dir = ensure_dir(parser_dir / doc_id)
    metadata_path = doc_dir / "metadata.json"
    diagnostics_path = doc_dir / "diagnostics.json"
    fitz_pages_path = doc_dir / "pymupdf_pages.jsonl"
    fitz_blocks_path = doc_dir / "pymupdf_blocks.jsonl"
    docling_path = doc_dir / "docling.json"
    grobid_summary_path = doc_dir / "grobid_summary.json"
    grobid_xml_path = doc_dir / "grobid.tei.xml"

    t0 = time.perf_counter()
    fitz_bundle = extract_fitz_bundle(source_path, min_page_words=options.min_page_words)
    pypdf_bundle = extract_pypdf_bundle(source_path)
    page_count = fitz_bundle.get("page_count") or pypdf_bundle.get("page_count") or manifest_row.get("page_count")
    fitz_pages = list(fitz_bundle.get("pages") or [])
    fitz_blocks = list(fitz_bundle.get("blocks") or [])
    pages_with_text = sum(1 for row in fitz_pages if row.get("has_text"))
    pages_with_substantive_text = sum(1 for row in fitz_pages if row.get("has_substantive_text"))
    total_chars = sum(int(row.get("char_len") or 0) for row in fitz_pages)
    pct_pages_with_text = round((pages_with_text / float(page_count)) * 100.0, 2) if page_count else None
    pct_pages_with_substantive_text = round((pages_with_substantive_text / float(page_count)) * 100.0, 2) if page_count else None
    readable_without_ocr = bool(total_chars >= int(options.min_doc_chars) and pages_with_substantive_text >= 1)
    ocr_required_or_unreadable = not readable_without_ocr
    outline_count = max(len(fitz_bundle.get("outline") or []), len(pypdf_bundle.get("outline") or []))
    page_count_agrees = (
        fitz_bundle.get("page_count") is None
        or pypdf_bundle.get("page_count") is None
        or int(fitz_bundle.get("page_count")) == int(pypdf_bundle.get("page_count"))
    )

    docling_bundle = extract_docling_bundle(source_path, page_count, options)
    docling_success = str(docling_bundle.get("status") or "") == "success"
    grobid_bundle = extract_grobid_bundle(source_path, manifest_row, page_count, options, capabilities)
    fallback_activated = bool(readable_without_ocr and not docling_success and str(fitz_bundle.get("status") or "") == "ok")
    bundle_status = "ok" if readable_without_ocr and str(fitz_bundle.get("status") or "") == "ok" else "needs_attention"
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    metadata_payload = {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_b",
        "doc_id": doc_id,
        "label": manifest_row.get("label"),
        "source_path": str(source_path),
        "file_name": source_path.name,
        "sha256": manifest_row.get("sha256"),
        "size_mb": manifest_row.get("size_mb"),
        "page_count": page_count,
        "page_count_sources": {
            "phase_a_manifest": manifest_row.get("page_count"),
            "fitz": fitz_bundle.get("page_count"),
            "pypdf": pypdf_bundle.get("page_count"),
            "agree": bool(page_count_agrees),
        },
        "outline_counts": {
            "fitz": len(fitz_bundle.get("outline") or []),
            "pypdf": len(pypdf_bundle.get("outline") or []),
        },
        "text_coverage": {
            "pages_with_text": pages_with_text,
            "pages_with_substantive_text": pages_with_substantive_text,
            "percent_pages_with_text": pct_pages_with_text,
            "percent_pages_with_substantive_text": pct_pages_with_substantive_text,
            "total_chars": total_chars,
            "readable_without_ocr": bool(readable_without_ocr),
            "ocr_required_or_unreadable": bool(ocr_required_or_unreadable),
        },
        "fitz": {
            "status": fitz_bundle.get("status"),
            "metadata": fitz_bundle.get("metadata"),
            "outline": fitz_bundle.get("outline"),
            "warnings": fitz_bundle.get("warnings"),
            "error": fitz_bundle.get("error"),
        },
        "pypdf": {
            "status": pypdf_bundle.get("status"),
            "metadata": pypdf_bundle.get("metadata"),
            "outline": pypdf_bundle.get("outline"),
            "error": pypdf_bundle.get("error"),
        },
        "docling": {
            "status": docling_bundle.get("status"),
            "enabled": docling_bundle.get("enabled"),
            "error": docling_bundle.get("error"),
            "warnings": docling_bundle.get("warnings"),
            "selected_mode": docling_bundle.get("selected_mode"),
            "confidence_summary": docling_bundle.get("confidence_summary"),
            "document_summary": docling_bundle.get("document_summary"),
            "section_headers": docling_bundle.get("section_headers"),
            "attempts": docling_bundle.get("attempts"),
            "chunking": docling_bundle.get("chunking"),
            "timings": ((docling_bundle.get("result") or {}).get("timings") if isinstance(docling_bundle.get("result"), dict) else None),
        },
        "grobid": {
            "status": grobid_bundle.get("status"),
            "reason": grobid_bundle.get("reason"),
            "summary": grobid_bundle.get("summary"),
            "error": grobid_bundle.get("error"),
        },
    }

    summary_row = {
        "doc_id": doc_id,
        "file_name": source_path.name,
        "page_count": page_count,
        "outline_count": outline_count,
        "pages_with_text_pct": pct_pages_with_text,
        "substantive_text_pct": pct_pages_with_substantive_text,
        "readable_without_ocr": bool(readable_without_ocr),
        "fitz_warning_count": len(fitz_bundle.get("warnings") or []),
        "docling_status": docling_bundle.get("status"),
        "docling_mode": docling_bundle.get("selected_mode"),
        "docling_conf_mean_grade": (docling_bundle.get("confidence_summary") or {}).get("mean_grade"),
        "docling_conf_low_grade": (docling_bundle.get("confidence_summary") or {}).get("low_grade"),
        "docling_warning_count": len(docling_bundle.get("warnings") or []),
        "docling_section_header_count": int((docling_bundle.get("document_summary") or {}).get("section_header_count") or len(docling_bundle.get("section_headers") or [])),
        "grobid_status": grobid_bundle.get("status"),
        "grobid_reason": grobid_bundle.get("reason"),
        "fallback_activated": bool(fallback_activated),
        "page_count_agrees": bool(page_count_agrees),
        "elapsed_ms": elapsed_ms,
        "cached": False,
        "cached_from_generated_at_utc": None,
        "runtime_capability_mismatch": False,
        "runtime_capability_mismatch_fields": [],
    }

    bundle_row = {
        "doc_id": doc_id,
        "source_path": str(source_path),
        "metadata_json": rel_to_run(Path(run_ctx.run_dir), metadata_path),
        "diagnostics_json": rel_to_run(Path(run_ctx.run_dir), diagnostics_path),
        "pymupdf_pages_jsonl": rel_to_run(Path(run_ctx.run_dir), fitz_pages_path),
        "pymupdf_blocks_jsonl": rel_to_run(Path(run_ctx.run_dir), fitz_blocks_path),
        "docling_json": rel_to_run(Path(run_ctx.run_dir), docling_path),
        "grobid_summary_json": rel_to_run(Path(run_ctx.run_dir), grobid_summary_path),
        "grobid_tei_xml": rel_to_run(Path(run_ctx.run_dir), grobid_xml_path) if grobid_bundle.get("xml_text") else None,
        "bundle_status": bundle_status,
    }

    diagnostics_payload = {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_b",
        "doc_id": doc_id,
        "bundle_status": bundle_status,
        "summary_row": summary_row,
        "bundle_row": bundle_row,
        "readable_without_ocr": bool(readable_without_ocr),
        "ocr_required_or_unreadable": bool(ocr_required_or_unreadable),
        "fallback_activated": bool(fallback_activated),
        "page_count_agrees": bool(page_count_agrees),
        "parser_statuses": {
            "fitz": fitz_bundle.get("status"),
            "pypdf": pypdf_bundle.get("status"),
            "docling": docling_bundle.get("status"),
            "grobid": grobid_bundle.get("status"),
        },
        "fitz_warning_count": len(fitz_bundle.get("warnings") or []),
        "fitz_warning_preview": list(fitz_bundle.get("warnings") or [])[:8],
        "docling_mode": docling_bundle.get("selected_mode"),
        "docling_confidence_summary": docling_bundle.get("confidence_summary"),
        "docling_warning_count": len(docling_bundle.get("warnings") or []),
        "docling_section_header_count": int((docling_bundle.get("document_summary") or {}).get("section_header_count") or len(docling_bundle.get("section_headers") or [])),
        "docling_attempts": docling_bundle.get("attempts"),
        "docling_chunking": docling_bundle.get("chunking"),
        "grobid_reason": grobid_bundle.get("reason"),
        "runtime_capabilities_snapshot": {
            "fitz_available": bool(capabilities.get("fitz_available")),
            "pypdf_available": bool(capabilities.get("pypdf_available")),
            "docling_available": bool(capabilities.get("docling_available")),
            "grobid_configured": bool(capabilities.get("grobid", {}).get("configured")),
            "grobid_reachable": bool(capabilities.get("grobid", {}).get("reachable")),
        },
        "phase_b_options_snapshot": json_safe(options.__dict__),
        "artifact_paths": bundle_row,
    }

    write_json_atomic(metadata_path, metadata_payload)
    write_jsonl_rows(fitz_pages_path, fitz_pages)
    write_jsonl_rows(fitz_blocks_path, fitz_blocks)
    write_json_atomic(docling_path, docling_bundle)
    write_json_atomic(grobid_summary_path, {k: v for k, v in grobid_bundle.items() if k != "xml_text"})
    if grobid_bundle.get("xml_text"):
        grobid_xml_path.write_text(str(grobid_bundle["xml_text"]), encoding="utf-8")
    elif grobid_xml_path.exists() and options.force_rebuild:
        grobid_xml_path.unlink()
    write_json_atomic(diagnostics_path, diagnostics_payload)

    return {
        "doc_id": doc_id,
        "summary_row": summary_row,
        "bundle_row": bundle_row,
        "log_payload": {
            "page_count": page_count,
            "fitz_status": fitz_bundle.get("status"),
            "pypdf_status": pypdf_bundle.get("status"),
            "docling_status": docling_bundle.get("status"),
            "grobid_status": grobid_bundle.get("status"),
            "fallback_activated": bool(fallback_activated),
            "elapsed_ms": elapsed_ms,
        },
        "event_payload": {
            "doc_id": doc_id,
            "source_path": str(source_path),
            "page_count": page_count,
            "fitz_status": fitz_bundle.get("status"),
            "pypdf_status": pypdf_bundle.get("status"),
            "docling_status": docling_bundle.get("status"),
            "grobid_status": grobid_bundle.get("status"),
            "readable_without_ocr": bool(readable_without_ocr),
            "fallback_activated": bool(fallback_activated),
            "elapsed_ms": elapsed_ms,
        },
    }


def run_phase_b(
    run_ctx: Any,
    pdf_manifest: List[Dict[str, Any]],
    options: PhaseBOptions,
    *,
    stable_hash_fn: Optional[Callable[..., str]] = None,
    log_event_fn: Optional[Callable[..., Any]] = None,
    run_logger: Optional[Any] = None,
) -> Dict[str, Any]:
    options = options.normalized()
    capabilities = detect_capabilities(options.grobid_base_url)
    required_kernel_packages = required_phase_b_kernel_packages(options)
    missing_kernel_packages = missing_phase_b_kernel_packages(capabilities, options)

    parser_dir = ensure_dir(Path(run_ctx.artifacts.parser_dir))
    config_path = parser_dir / "phase_b_config.json"
    runtime_path = parser_dir / "phase_b_runtime.json"
    summary_path = parser_dir / "phase_b_summary.json"
    assessment_path = parser_dir / "phase_b_assessment.json"
    index_path = parser_dir / "parsed_document_bundles.jsonl"

    selected_rows: List[Dict[str, Any]] = []
    include_doc_ids = set(options.include_doc_ids or [])
    exclude_doc_ids = set(options.exclude_doc_ids or [])

    for manifest_row in list(pdf_manifest or []):
        doc_id = compute_doc_id(manifest_row, stable_hash_fn=stable_hash_fn)
        if include_doc_ids and doc_id not in include_doc_ids:
            continue
        if doc_id in exclude_doc_ids:
            continue
        row = dict(manifest_row)
        row["doc_id"] = doc_id
        selected_rows.append(row)

    if options.doc_limit is not None:
        selected_rows = selected_rows[: int(options.doc_limit)]
    if not selected_rows:
        raise RuntimeError("Phase B selected zero PDFs after filtering. Adjust PhaseBOptions filters.")
    resolved_doc_concurrency = resolve_phase_b_doc_concurrency(options, capabilities=capabilities, doc_count=len(selected_rows))
    write_json_atomic(
        runtime_path,
        {
            "generated_at_utc": utc_now_iso(),
            "phase": "phase_b",
            "options": json_safe(options.__dict__),
            "required_kernel_packages": required_kernel_packages,
            "missing_kernel_packages": missing_kernel_packages,
            "capabilities": capabilities,
            "available_cpu_count": available_cpu_count(),
            "resolved_doc_concurrency": resolved_doc_concurrency,
        },
    )

    config_payload = {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_b",
        "options": json_safe(options.__dict__),
        "capabilities": capabilities,
        "runtime_path": rel_to_run(Path(run_ctx.run_dir), runtime_path),
        "available_cpu_count": available_cpu_count(),
        "resolved_doc_concurrency": resolved_doc_concurrency,
    }
    write_json_atomic(config_path, config_payload)
    if run_logger is not None:
        run_logger.info(
            "Phase B runtime | python=%s | missing_kernel_packages=%s",
            capabilities.get("runtime", {}).get("python_executable"),
            ",".join(missing_kernel_packages) if missing_kernel_packages else "none",
        )
        run_logger.info(
            "Phase B started | selected=%s | concurrency=%s | cpu_count=%s | force_rebuild=%s | fitz=%s | pypdf=%s | docling=%s | grobid=%s",
            len(selected_rows),
            resolved_doc_concurrency,
            available_cpu_count(),
            options.force_rebuild,
            capabilities.get("fitz_available"),
            capabilities.get("pypdf_available"),
            capabilities.get("docling_available"),
            capabilities.get("grobid", {}).get("status"),
        )

    summary_rows_by_pos: Dict[int, Dict[str, Any]] = {}
    bundle_rows_by_pos: Dict[int, Dict[str, Any]] = {}
    pending_rows: List[tuple[int, Dict[str, Any]]] = []

    for position, manifest_row in enumerate(selected_rows):
        doc_id = str(manifest_row["doc_id"])
        source_path = Path(str(manifest_row["path"])).resolve()
        doc_dir = ensure_dir(parser_dir / doc_id)
        metadata_path = doc_dir / "metadata.json"
        diagnostics_path = doc_dir / "diagnostics.json"
        fitz_pages_path = doc_dir / "pymupdf_pages.jsonl"
        fitz_blocks_path = doc_dir / "pymupdf_blocks.jsonl"
        docling_path = doc_dir / "docling.json"
        grobid_summary_path = doc_dir / "grobid_summary.json"
        grobid_xml_path = doc_dir / "grobid.tei.xml"

        required_cache_paths = [metadata_path, diagnostics_path, fitz_pages_path, fitz_blocks_path, docling_path, grobid_summary_path]
        if (not options.force_rebuild) and all(p.exists() for p in required_cache_paths):
            cached_diag = read_json(diagnostics_path)
            cached_summary = dict(cached_diag.get("summary_row") or {})
            if cached_summary:
                runtime_snapshot = dict(cached_diag.get("runtime_capabilities_snapshot") or {})
                cached_options_snapshot = dict(cached_diag.get("phase_b_options_snapshot") or {})
                parser_statuses = dict(cached_diag.get("parser_statuses") or {})
                mismatch_fields: List[str] = []
                for field in ["fitz_available", "pypdf_available", "docling_available"]:
                    current_val = bool(capabilities.get(field))
                    cached_val = runtime_snapshot.get(field)
                    if isinstance(cached_val, bool):
                        if current_val != cached_val:
                            mismatch_fields.append(field)
                        continue
                    if field == "fitz_available":
                        cached_status = str(parser_statuses.get("fitz") or "")
                        if current_val and cached_status in {"", "unavailable"}:
                            mismatch_fields.append(field)
                        if (not current_val) and cached_status not in {"", "unavailable"}:
                            mismatch_fields.append(field)
                    if field == "pypdf_available":
                        cached_status = str(parser_statuses.get("pypdf") or "")
                        if current_val and cached_status in {"", "unavailable"}:
                            mismatch_fields.append(field)
                        if (not current_val) and cached_status not in {"", "unavailable"}:
                            mismatch_fields.append(field)
                    if field == "docling_available":
                        cached_status = str(parser_statuses.get("docling") or "")
                        docling_was_enabled = bool(cached_options_snapshot.get("try_docling", True))
                        if docling_was_enabled and current_val and cached_status in {"", "unavailable", "disabled"}:
                            mismatch_fields.append(field)
                        if (not current_val) and cached_status not in {"", "unavailable", "disabled"}:
                            mismatch_fields.append(field)
                cached_summary["cached"] = True
                cached_summary["cached_from_generated_at_utc"] = cached_diag.get("generated_at_utc")
                cached_summary["runtime_capability_mismatch"] = bool(mismatch_fields)
                cached_summary["runtime_capability_mismatch_fields"] = mismatch_fields
                summary_rows_by_pos[position] = cached_summary
                bundle_rows_by_pos[position] = dict(cached_diag.get("bundle_row") or {})
                if run_logger is not None:
                    run_logger.info(
                        "Phase B cached document | doc_id=%s | bundle_status=%s | docling=%s | grobid=%s | mismatch=%s",
                        doc_id,
                        cached_diag.get("bundle_status"),
                        cached_diag.get("parser_statuses", {}).get("docling"),
                        cached_diag.get("parser_statuses", {}).get("grobid"),
                        bool(mismatch_fields),
                    )
                if log_event_fn is not None:
                    log_event_fn(
                        run_ctx,
                        stage="phase_b",
                        event="document_reused_from_cache",
                        doc_id=doc_id,
                        bundle_status=cached_diag.get("bundle_status"),
                        docling_status=cached_diag.get("parser_statuses", {}).get("docling"),
                        grobid_status=cached_diag.get("parser_statuses", {}).get("grobid"),
                        runtime_capability_mismatch=bool(mismatch_fields),
                    )
                continue
        pending_rows.append((position, manifest_row))

    if pending_rows:
        failed_doc_ids: List[str] = []
        with ThreadPoolExecutor(max_workers=resolved_doc_concurrency) as executor:
            future_map = {
                executor.submit(
                    build_phase_b_document_bundle,
                    run_ctx=run_ctx,
                    parser_dir=parser_dir,
                    manifest_row=manifest_row,
                    options=options,
                    capabilities=capabilities,
                ): (position, manifest_row)
                for position, manifest_row in pending_rows
            }
            for future in as_completed(future_map):
                position, manifest_row = future_map[future]
                doc_id = str(manifest_row["doc_id"])
                try:
                    result = future.result()
                except Exception as exc:
                    failed_doc_ids.append(doc_id)
                    if run_logger is not None:
                        run_logger.exception("Phase B doc failed | doc_id=%s | source_path=%s", doc_id, manifest_row.get("path"))
                    if log_event_fn is not None:
                        log_event_fn(
                            run_ctx,
                            stage="phase_b",
                            event="document_failed",
                            doc_id=doc_id,
                            source_path=manifest_row.get("path"),
                            error_type=type(exc).__name__,
                            error_message=short_blob(str(exc), max_len=600) or type(exc).__name__,
                        )
                    continue
                summary_rows_by_pos[position] = dict(result["summary_row"])
                bundle_rows_by_pos[position] = dict(result["bundle_row"])
                if run_logger is not None:
                    log_payload = dict(result.get("log_payload") or {})
                    run_logger.info(
                        "Phase B parsed document | doc_id=%s | page_count=%s | fitz=%s | pypdf=%s | docling=%s | grobid=%s | fallback=%s | elapsed_ms=%s",
                        doc_id,
                        log_payload.get("page_count"),
                        log_payload.get("fitz_status"),
                        log_payload.get("pypdf_status"),
                        log_payload.get("docling_status"),
                        log_payload.get("grobid_status"),
                        bool(log_payload.get("fallback_activated")),
                        log_payload.get("elapsed_ms"),
                    )
                if log_event_fn is not None:
                    log_event_fn(run_ctx, stage="phase_b", event="document_parsed", **dict(result.get("event_payload") or {}))
    else:
        failed_doc_ids = []

    summary_rows = [summary_rows_by_pos[idx] for idx in range(len(selected_rows)) if idx in summary_rows_by_pos]
    bundle_rows = [bundle_rows_by_pos[idx] for idx in range(len(selected_rows)) if idx in bundle_rows_by_pos]

    assessment = build_phase_b_assessment(summary_rows, capabilities, len(selected_rows), failed_doc_ids=failed_doc_ids)
    qc_rows = build_qc_rows(
        summary_rows,
        capabilities,
        len(selected_rows),
        failed_doc_ids=failed_doc_ids,
        assessment=assessment,
    )

    write_json_atomic(
        summary_path,
        {
            "generated_at_utc": utc_now_iso(),
            "run_id": run_ctx.run_id,
            "phase": "phase_b",
            "options": json_safe(options.__dict__),
            "runtime_path": rel_to_run(Path(run_ctx.run_dir), runtime_path),
            "capabilities": capabilities,
            "assessment": assessment,
            "qc_rows": qc_rows,
            "documents": summary_rows,
            "artifacts": bundle_rows,
        },
    )
    write_json_atomic(
        assessment_path,
        {
            "generated_at_utc": utc_now_iso(),
            "run_id": run_ctx.run_id,
            "phase": "phase_b",
            "assessment": assessment,
            "qc_rows": qc_rows,
            "runtime_path": rel_to_run(Path(run_ctx.run_dir), runtime_path),
            "summary_path": rel_to_run(Path(run_ctx.run_dir), summary_path),
            "index_path": rel_to_run(Path(run_ctx.run_dir), index_path),
        },
    )
    write_jsonl_rows(index_path, bundle_rows)
    if run_logger is not None:
        run_logger.info(
            "Phase B completed | status=%s | quality=%s | processed=%s | cached=%s | fallback=%s | warnings=%s | failures=%s",
            assessment.get("status"),
            assessment.get("quality_band"),
            assessment.get("counts", {}).get("documents_processed"),
            assessment.get("counts", {}).get("cached_doc_count"),
            assessment.get("counts", {}).get("fallback_activated_count"),
            len(assessment.get("warnings") or []),
            len(assessment.get("failures") or []),
        )

    metrics_update = {
        "initialized_at_utc": utc_now_iso(),
        "document_count": len(summary_rows),
        "readable_document_count": sum(1 for row in summary_rows if row.get("readable_without_ocr")),
        "docling_success_count": sum(1 for row in summary_rows if str(row.get("docling_status") or "") == "success"),
        "docling_success_like_count": sum(1 for row in summary_rows if _docling_success_like(row.get("docling_status"))),
        "docling_chunk_selected_count": sum(1 for row in summary_rows if str(row.get("docling_mode") or "") == "chunked"),
        "grobid_success_count": sum(1 for row in summary_rows if str(row.get("grobid_status") or "") == "ok"),
        "grobid_reachable": bool(capabilities.get("grobid", {}).get("reachable")),
        "cached_doc_count": sum(1 for row in summary_rows if row.get("cached")),
        "runtime_capability_mismatch_count": sum(1 for row in summary_rows if row.get("runtime_capability_mismatch")),
        "bundle_failure_count": len(failed_doc_ids),
        "status": assessment.get("status"),
        "quality_band": assessment.get("quality_band"),
        "can_continue_to_next_phase": assessment.get("can_continue_to_next_phase"),
        "warning_count": len(assessment.get("warnings") or []),
        "failure_count": len(assessment.get("failures") or []),
        "assessment_path": rel_to_run(Path(run_ctx.run_dir), assessment_path),
    }

    from pdf_reporting import update_run_pdf_reports

    update_run_pdf_reports(run_ctx, phase_name="phase_b")

    return {
        "config_path": config_path,
        "runtime_path": runtime_path,
        "summary_path": summary_path,
        "assessment_path": assessment_path,
        "index_path": index_path,
        "capabilities": capabilities,
        "required_kernel_packages": required_kernel_packages,
        "missing_kernel_packages": missing_kernel_packages,
        "summary_rows": summary_rows,
        "bundle_rows": bundle_rows,
        "metrics_update": metrics_update,
        "assessment": assessment,
        "qc_rows": qc_rows,
        "selected_count": len(selected_rows),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase B lab for the PDF scan pipeline.")
    parser.add_argument("--input-mode", choices=["small_gold", "manual"], default="small_gold")
    parser.add_argument("--pipeline-version", default="pdf_scan_v3_phase_b_lab")
    parser.add_argument("--force-rebuild-phase-a", action="store_true")
    parser.add_argument("--force-rebuild-phase-b", action="store_true")
    parser.add_argument("--suite-manifest", default="benchmark/small_gold/manifests/suite_manifest.json")
    parser.add_argument("--chapter-index", type=int, default=0)
    parser.add_argument("--doc-limit", type=int, default=None)
    parser.add_argument("--include-doc-id", action="append", default=[])
    parser.add_argument("--exclude-doc-id", action="append", default=[])
    parser.add_argument("--chapter-title", default="")
    parser.add_argument("--chapter-description", default="")
    parser.add_argument("--pdf", action="append", default=[])
    parser.add_argument("--pdf-dir", default="")
    parser.add_argument("--pdf-glob", default="*.pdf")
    parser.add_argument("--pdf-recursive", action="store_true")
    parser.add_argument("--max-pdfs", type=int, default=20)
    parser.add_argument("--grobid-base-url", default=(os.getenv("GROBID_URL") or os.getenv("GROBID_BASE_URL") or "").strip())
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    phase_a_args = Namespace(
        input_mode=args.input_mode,
        pipeline_version=args.pipeline_version,
        force_rebuild=bool(args.force_rebuild_phase_a),
        runs_root="",
        suite_manifest=args.suite_manifest,
        chapter_index=int(args.chapter_index),
        doc_limit=args.doc_limit,
        include_doc_id=list(args.include_doc_id or []),
        exclude_doc_id=list(args.exclude_doc_id or []),
        chapter_title=str(args.chapter_title or ""),
        chapter_description=str(args.chapter_description or ""),
        pdf=list(args.pdf or []),
        pdf_dir=str(args.pdf_dir or ""),
        pdf_glob=str(args.pdf_glob or "*.pdf"),
        pdf_recursive=bool(args.pdf_recursive),
        max_pdfs=int(args.max_pdfs),
    )

    phase_a_result = run_phase_a(phase_a_args)
    run_ctx = phase_a_result["run_ctx"]
    pdf_manifest = phase_a_result["manifest_rows"]
    phase_b_logger = setup_run_logger(run_ctx)

    phase_b_options = PhaseBOptions(
        force_rebuild=bool(args.force_rebuild_phase_b),
        doc_limit=args.doc_limit,
        include_doc_ids=list(args.include_doc_id or []),
        exclude_doc_ids=list(args.exclude_doc_id or []),
        min_page_words=20,
        min_doc_chars=200,
        try_docling=True,
        docling_page_limit=400,
        docling_max_file_size_bytes=50 * 1024 * 1024,
        docling_do_ocr=False,
        docling_do_table_structure=False,
        docling_document_timeout_sec=180,
        docling_num_threads=4,
        docling_enable_chunking=True,
        docling_chunk_size=20,
        docling_chunk_max_pages=400,
        docling_chunk_num_threads=1,
        try_grobid=True,
        grobid_page_limit=400,
        grobid_base_url=str(args.grobid_base_url or "").strip(),
        grobid_process_path="/api/processFulltextDocument",
        grobid_timeout_sec=120,
        grobid_consolidate_header=0,
        grobid_consolidate_citations=0,
        grobid_include_raw_citations=0,
    )

    with stage_timer(run_ctx, "phase_b"):
        phase_b_result = run_phase_b(
            run_ctx,
            pdf_manifest,
            phase_b_options,
            stable_hash_fn=stable_hash,
            log_event_fn=log_event,
            run_logger=phase_b_logger,
        )
        metrics = load_metrics(run_ctx)
        metrics.setdefault("stages", {}).setdefault("phase_b", {}).update(phase_b_result["metrics_update"])
        save_metrics(run_ctx, metrics)

    summary_rows = phase_b_result["summary_rows"]
    docling_success_count = sum(1 for row in summary_rows if str(row.get("docling_status") or "") == "success")
    docling_chunk_selected_count = sum(1 for row in summary_rows if str(row.get("docling_mode") or "") == "chunked")
    grobid_success_count = sum(1 for row in summary_rows if str(row.get("grobid_status") or "") == "ok")
    fallback_activated_docs = sum(1 for row in summary_rows if row.get("fallback_activated"))

    rel = lambda path: rel_to_run(Path(run_ctx.run_dir), Path(path))

    print_section("Phase B Lab - Parser Capabilities")
    print_kv(
        {
            "fitz_available": phase_b_result["capabilities"].get("fitz_available"),
            "pypdf_available": phase_b_result["capabilities"].get("pypdf_available"),
            "docling_available": phase_b_result["capabilities"].get("docling_available"),
            "python_executable": phase_b_result["capabilities"].get("runtime", {}).get("python_executable"),
            "grobid_status": phase_b_result["capabilities"].get("grobid", {}).get("status"),
            "selected_documents": phase_b_result["selected_count"],
            "docling_success_count": docling_success_count,
            "docling_chunk_selected_count": docling_chunk_selected_count,
            "grobid_success_count": grobid_success_count,
        }
    )

    print_section("Phase B Lab - What Happened")
    print_kv(
        {
            "phase_b_config_json": rel(phase_b_result["config_path"]),
            "phase_b_runtime_json": rel(phase_b_result["runtime_path"]),
            "phase_b_summary_json": rel(phase_b_result["summary_path"]),
            "phase_b_assessment_json": rel(phase_b_result["assessment_path"]),
            "parsed_document_bundles_jsonl": rel(phase_b_result["index_path"]),
            "documents_processed": len(summary_rows),
            "readable_without_ocr": sum(1 for row in summary_rows if row.get("readable_without_ocr")),
            "fallback_activated_docs": fallback_activated_docs,
            "missing_kernel_packages": ", ".join(phase_b_result.get("missing_kernel_packages") or []) or "none",
            "phase_status": phase_b_result["assessment"].get("status"),
            "quality_band": phase_b_result["assessment"].get("quality_band"),
        }
    )

    print_section("Phase B Lab - Document Summary")
    print_table(
        summary_rows,
        columns=["doc_id", "file_name", "page_count", "outline_count", "pages_with_text_pct", "docling_status", "docling_mode", "docling_section_header_count", "fallback_activated"],
        max_rows=20,
        max_col_width=44,
    )

    print_section("Phase B Lab - QC")
    print_table(
        phase_b_result["qc_rows"],
        columns=["check", "status", "value", "expected", "why", "fix"],
        max_rows=20,
        max_col_width=46,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
