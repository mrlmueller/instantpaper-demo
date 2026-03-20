from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
import sys

import fitz  # PyMuPDF
from utils.runtime_paths import resolve_pdf_scan_runtime_dir

PDF_SCAN_RUNTIME_DIR = resolve_pdf_scan_runtime_dir(__file__)
if str(PDF_SCAN_RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(PDF_SCAN_RUNTIME_DIR))

from phase_b_lab import extract_fitz_bundle  # noqa: E402
from phase_c_lab import build_block_index  # noqa: E402


def rebuild_phase_c_block_index(pdf_path: Path, *, min_page_words: int = 1) -> dict[str, Any]:
    bundle = extract_fitz_bundle(pdf_path, min_page_words=min_page_words)
    block_rows = list(bundle.get("blocks") or [])
    if not block_rows:
        raise RuntimeError("Phase B produced no text blocks for this PDF.")
    index = build_block_index(block_rows)
    if not list(index.get("ordered_blocks") or []):
        raise RuntimeError("Phase C block index is empty for this PDF.")
    return index


def _normalize_rect(page: fitz.Page, *, x0: float, y0: float, x1: float, y1: float) -> dict[str, float] | None:
    width = float(page.rect.width or 0.0)
    height = float(page.rect.height or 0.0)
    if width <= 0 or height <= 0:
        return None
    left = max(0.0, min(width, float(min(x0, x1))))
    right = max(0.0, min(width, float(max(x0, x1))))
    top = max(0.0, min(height, float(min(y0, y1))))
    bottom = max(0.0, min(height, float(max(y0, y1))))
    if right <= left or bottom <= top:
        return None
    return {
        "x0n": round(left / width, 6),
        "y0n": round(top / height, 6),
        "x1n": round(right / width, 6),
        "y1n": round(bottom / height, 6),
    }


def extract_section_by_locator(
    doc: fitz.Document,
    *,
    locator: dict[str, Any],
    block_index: dict[str, Any],
    section_title: str | None = None,
) -> dict[str, Any]:
    ordered_blocks = list(block_index.get("ordered_blocks") or [])
    if not ordered_blocks:
        return {"ok": False, "reason": "empty_block_index"}

    span = locator.get("span") if isinstance(locator.get("span"), dict) else {}
    heading_anchor = locator.get("headingAnchor") if isinstance(locator.get("headingAnchor"), dict) else {}

    start_abs = int(span.get("startAbsBlockIndex") or -1)
    end_abs = int(span.get("endAbsBlockIndex") or -1)
    if start_abs < 0 or end_abs < start_abs or end_abs >= len(ordered_blocks):
        return {
            "ok": False,
            "reason": "invalid_block_span",
            "detail": f"start={start_abs}, end={end_abs}, blocks={len(ordered_blocks)}",
        }

    span_blocks = ordered_blocks[start_abs : end_abs + 1]
    if not span_blocks:
        return {"ok": False, "reason": "empty_span"}

    pages_map: dict[int, list[dict[str, float]]] = defaultdict(list)
    for row in span_blocks:
        page_no = int(row.get("page") or 0)
        if page_no <= 0 or page_no > doc.page_count:
            continue
        page = doc.load_page(page_no - 1)
        rect = _normalize_rect(
            page,
            x0=float(row.get("x0") or 0.0),
            y0=float(row.get("y0") or 0.0),
            x1=float(row.get("x1") or 0.0),
            y1=float(row.get("y1") or 0.0),
        )
        if rect is None:
            continue
        pages_map[page_no].append(rect)

    highlight_pages = [{"page": page_no, "rects": rects} for page_no, rects in sorted(pages_map.items()) if rects]
    if not highlight_pages:
        return {"ok": False, "reason": "no_highlight_rects"}

    first_block = span_blocks[0]
    last_block = span_blocks[-1]
    anchor_page = int(heading_anchor.get("page") or first_block.get("page") or 1)
    return {
        "ok": True,
        "method": "phase_c_block_span",
        "section_title": section_title,
        "anchor_page": anchor_page,
        "start": {"page": int(first_block.get("page") or 1), "y": float(first_block.get("y0") or 0.0)},
        "end": {"page": int(last_block.get("page") or anchor_page), "y": float(last_block.get("y1") or 0.0)},
        "highlights": {
            "truncated": False,
            "pages": highlight_pages,
        },
    }
