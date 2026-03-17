#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import fitz  # PyMuPDF
except Exception as e:  # pragma: no cover
    fitz = None
    FITZ_IMPORT_ERROR = f"{type(e).__name__}: {e}"
else:
    FITZ_IMPORT_ERROR = ""

from phase_a_lab import print_kv, print_section, print_table
from phase_b_lab import ensure_dir, write_json_atomic as write_json
from phase_c_lab import (
    clean_text,
    classify_section_type,
    count_words,
    has_heading_numbering,
    is_probable_affiliation_line,
    is_probable_author_line,
    heading_key_without_numbers,
    normalize_heading_display,
    normalize_heading_key,
    read_jsonl_rows,
    strip_heading_numbering,
    title_similarity,
)


def page_html_path(doc_dir: Path, page_number: int) -> Path:
    return doc_dir / "pages" / f"page_{int(page_number):04d}.html"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def collapse_spaced_caps(text: Any) -> str:
    tokens = clean_text(text).split()
    out: List[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if len(token) == 1 and token.isalpha() and token.isupper():
            parts = [token]
            j = i + 1
            while j < len(tokens) and len(tokens[j]) == 1 and tokens[j].isalpha() and tokens[j].isupper():
                parts.append(tokens[j])
                j += 1
            if j < len(tokens) and tokens[j].isalpha() and tokens[j].upper() == tokens[j] and len(tokens[j]) <= 20:
                parts.append(tokens[j])
                j += 1
            if len(parts) >= 2:
                out.append("".join(parts))
                i = j
                continue
        out.append(token)
        i += 1
    return " ".join(out)


def normalize_key(text: Any) -> str:
    collapsed = collapse_spaced_caps(text)
    return heading_key_without_numbers(collapsed) or normalize_heading_key(collapsed)


def text_contains_heading(text: Any, heading: Any) -> bool:
    hay = f" {normalize_key(text)} "
    needle = f" {normalize_key(heading)} "
    if needle.strip() == "":
        return False
    return needle in hay


def fuzzy_title_match(a: Any, b: Any) -> float:
    a_display = normalize_heading_display(a)
    b_display = normalize_heading_display(b)
    a_number = extract_number_prefix(a_display)
    b_number = extract_number_prefix(b_display)
    if a_number and b_number and a_number == b_number:
        a_body = normalize_key(strip_heading_numbering(a_display))
        b_body = normalize_key(strip_heading_numbering(b_display))
        if re.fullmatch(r"(?:\d+\s*)+", a_body or ""):
            a_body = ""
        if re.fullmatch(r"(?:\d+\s*)+", b_body or ""):
            b_body = ""
        if not a_body or not b_body or f" {a_body} " in f" {b_body} " or f" {b_body} " in f" {a_body} ":
            return 0.985
    a_key = normalize_key(a)
    b_key = normalize_key(b)
    if not a_key or not b_key:
        return 0.0
    if a_key == b_key:
        return 1.0
    if f" {a_key} " in f" {b_key} " or f" {b_key} " in f" {a_key} ":
        return 0.96
    return round(
        max(
            title_similarity(a_key, b_key),
            title_similarity(normalize_heading_display(a), normalize_heading_display(b)),
        ),
        4,
    )


def extract_number_prefix(text: Any) -> str:
    value = normalize_heading_display(text)
    match = re.match(r"^(\d+(?:\.\d+){0,4})\b", value)
    return str(match.group(1)) if match else ""


def is_probable_heading_text(text: str) -> bool:
    text = normalize_heading_display(collapse_spaced_caps(text))
    if not text:
        return False
    words = count_words(text)
    if words < 1 or words > 18:
        return False
    if len(text) > 180:
        return False
    if text.endswith(".") and words > 4:
        return False
    lowered = text.lower()
    if lowered.startswith(("fig.", "figure ", "table ", "copyright", "doi:", "received ", "accepted ")):
        return False
    if "@" in text:
        return False
    if len(normalize_key(text)) <= 1:
        return False
    if normalize_key(text).isdigit():
        return False
    if sum(ch.isdigit() for ch in text) > max(3, len(text) * 0.25):
        return False
    return True


def extract_page_rows(doc: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for page_index in range(doc.page_count):
        page = doc[page_index]
        text = clean_text(page.get_text("text"))
        rows.append(
            {
                "page": page_index + 1,
                "char_len": len(text),
                "word_count": count_words(text),
                "text": text,
            }
        )
    return rows


def extract_outline_rows(doc: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    toc = doc.get_toc(simple=True) if fitz is not None else []
    for idx, item in enumerate(toc or [], start=1):
        if len(item) < 3:
            continue
        level, title, page = item[:3]
        rows.append(
            {
                "outline_index": idx,
                "level": int(level or 0),
                "title": normalize_heading_display(title),
                "page": int(page or 0),
            }
        )
    return rows


def extract_visual_heading_candidates(doc: Any) -> List[Dict[str, Any]]:
    doc_font_samples: List[float] = []
    page_payloads: List[Tuple[int, Dict[str, Any]]] = []
    for page_index in range(doc.page_count):
        page = doc[page_index]
        payload = page.get_text("dict")
        page_payloads.append((page_index + 1, payload))
        for block in payload.get("blocks") or []:
            if block.get("type") != 0:
                continue
            for line in block.get("lines") or []:
                text = clean_text(" ".join(clean_text(span.get("text")) for span in line.get("spans") or []))
                if not text or count_words(text) < 3:
                    continue
                sizes = [float(span.get("size") or 0.0) for span in line.get("spans") or [] if float(span.get("size") or 0.0) > 0.0]
                if sizes:
                    doc_font_samples.append(max(sizes))
    body_font = statistics.median(doc_font_samples) if doc_font_samples else 10.0

    rows: List[Dict[str, Any]] = []
    for page_number, payload in page_payloads:
        page_height = float(payload.get("height") or 0.0)
        for block_index, block in enumerate(payload.get("blocks") or []):
            if block.get("type") != 0:
                continue
            for line_index, line in enumerate(block.get("lines") or []):
                spans = line.get("spans") or []
                text = normalize_heading_display(collapse_spaced_caps(" ".join(clean_text(span.get("text")) for span in spans)))
                if not is_probable_heading_text(text):
                    continue
                bbox = line.get("bbox") or [0.0, 0.0, 0.0, 0.0]
                y0 = float(bbox[1] or 0.0)
                if page_height and y0 > page_height * 0.92:
                    continue
                max_size = max(float(span.get("size") or 0.0) for span in spans) if spans else 0.0
                font_names = " ".join(str(span.get("font") or "") for span in spans)
                bold = "bold" in font_names.lower()
                uppercase_ratio = (
                    sum(1 for ch in text if ch.isupper()) / max(1, sum(1 for ch in text if ch.isalpha()))
                    if any(ch.isalpha() for ch in text)
                    else 0.0
                )
                titlecase_hits = sum(1 for token in text.split() if token[:1].isupper())
                is_upper = any(ch.isalpha() for ch in text) and text.upper() == text
                score = 0.0
                if max_size >= body_font * 1.18:
                    score += 2.0
                elif max_size >= body_font * 1.08:
                    score += 1.0
                elif max_size >= body_font * 0.95 and (bold or is_upper):
                    score += 0.7
                if bold:
                    score += 1.0
                if titlecase_hits >= max(1, math.ceil(count_words(text) * 0.6)):
                    score += 0.7
                if uppercase_ratio >= 0.65:
                    score += 0.8
                if has_heading_numbering(text):
                    score += 1.0
                if count_words(text) <= 8:
                    score += 0.4
                if page_height and y0 <= page_height * 0.22:
                    score += 0.2
                rows.append(
                    {
                        "page": page_number,
                        "block_index": block_index,
                        "line_index": line_index,
                        "title": text,
                        "norm_key": normalize_key(text),
                        "font_size": round(max_size, 3),
                        "body_font_size": round(body_font, 3),
                        "bold": bold,
                        "score": round(score, 4),
                        "y0": round(y0, 2),
                    }
                )
    rows.sort(key=lambda row: (int(row["page"]), -float(row["score"]), float(row["y0"])))
    return rows


def find_contents_pages(page_rows: List[Dict[str, Any]]) -> List[int]:
    pages: List[int] = []
    for row in page_rows[: min(30, len(page_rows))]:
        text = normalize_key(row.get("text"))
        if "table of contents" in text or "contents" in text:
            pages.append(int(row.get("page") or 0))
    return pages


def verify_outline_rows(outline_rows: List[Dict[str, Any]], page_rows: List[Dict[str, Any]], visual_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    page_lookup = {int(row.get("page") or 0): row for row in page_rows}
    visual_by_page: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for row in visual_rows:
        visual_by_page[int(row.get("page") or 0)].append(row)

    verified: List[Dict[str, Any]] = []
    for row in outline_rows:
        title = row.get("title")
        target_page = int(row.get("page") or 0)
        if not title or target_page <= 0:
            continue
        best: Dict[str, Any] = {"matched": False, "score": 0.0}
        for candidate_page in range(max(1, target_page - 1), target_page + 2):
            for visual in visual_by_page.get(candidate_page, []):
                score = fuzzy_title_match(title, visual.get("title"))
                if score > float(best.get("score") or 0.0):
                    best = {
                        "matched": score >= 0.84,
                        "score": round(score, 4),
                        "evidence": "visual_heading",
                        "matched_title": visual.get("title"),
                        "matched_page": candidate_page,
                    }
            page_text = (page_lookup.get(candidate_page) or {}).get("text") or ""
            if text_contains_heading(page_text, title):
                best = {
                    "matched": True,
                    "score": max(float(best.get("score") or 0.0), 0.88),
                    "evidence": "page_text",
                    "matched_title": title,
                    "matched_page": candidate_page,
                }
        if best.get("matched"):
            verified.append({**row, **best})
    return verified


def build_truth_headings(
    outline_rows: List[Dict[str, Any]],
    verified_outline_rows: List[Dict[str, Any]],
    visual_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    truth_rows: List[Dict[str, Any]] = []
    seen: set[Tuple[str, int]] = set()

    def add_row(kind: str, title: str, page: int, score: float, source_row: Dict[str, Any]) -> None:
        key = (normalize_key(title), int(page))
        if not key[0] or key in seen:
            return
        seen.add(key)
        truth_rows.append(
            {
                "kind": kind,
                "title": normalize_heading_display(title),
                "norm_key": normalize_key(title),
                "page": int(page),
                "confidence": round(float(score), 4),
                "source_row": source_row,
            }
        )

    for row in verified_outline_rows:
        add_row("verified_outline", str(row.get("title") or ""), int(row.get("matched_page") or row.get("page") or 0), float(row.get("score") or 1.0), row)

    verified_keys = {normalize_key(row.get("title")) for row in verified_outline_rows}
    has_outline = bool(outline_rows)
    verified_outline_prefixes = {
        (extract_number_prefix(row.get("title")), int(row.get("matched_page") or row.get("page") or 0))
        for row in verified_outline_rows
        if extract_number_prefix(row.get("title"))
    }
    visual_page_counts: Dict[str, int] = defaultdict(int)
    for row in visual_rows:
        key = normalize_key(row.get("title"))
        if key:
            visual_page_counts[key] += 1
    for row in visual_rows:
        if float(row.get("score") or 0.0) < (3.6 if has_outline else 2.8):
            continue
        title = str(row.get("title") or "")
        key = normalize_key(title)
        if not key or key in verified_keys:
            continue
        if not strip_heading_numbering(title).strip() and has_heading_numbering(title):
            continue
        if key.isdigit():
            continue
        if int(visual_page_counts.get(key) or 0) >= 3:
            continue
        if is_probable_author_line(title) or is_probable_affiliation_line(title):
            continue
        if has_outline:
            if int(row.get("page") or 0) <= 1:
                continue
            if count_words(title) < 2:
                continue
            prefix = extract_number_prefix(title)
            if prefix:
                if any(abs(int(row.get("page") or 0) - page) <= 1 and prefix == verified_prefix for verified_prefix, page in verified_outline_prefixes):
                    continue
            near_outline = False
            for outline in verified_outline_rows:
                if abs(int(outline.get("matched_page") or outline.get("page") or 0) - int(row.get("page") or 0)) > 1:
                    continue
                if fuzzy_title_match(outline.get("title"), title) >= 0.6:
                    near_outline = True
                    break
            if near_outline:
                continue
        else:
            if (
                int(row.get("page") or 0) == 1
                and not has_heading_numbering(title)
                and classify_section_type(title) == "body_other"
            ):
                continue
            if re.match(r"^summary:", normalize_heading_display(title), flags=re.IGNORECASE):
                continue
            if (
                count_words(title) == 1
                and not has_heading_numbering(title)
                and classify_section_type(title) == "body_other"
            ):
                continue
            if (
                title.isupper()
                and count_words(title) <= 4
                and not has_heading_numbering(title)
                and classify_section_type(title) == "body_other"
            ):
                continue
        add_row("visual_heading", title, int(row.get("page") or 0), float(row.get("score") or 0.0), row)

    truth_rows.sort(key=lambda row: (int(row["page"]), str(row["title"])))
    return truth_rows


def compare_truth_to_phase_c(
    truth_rows: List[Dict[str, Any]],
    section_rows: List[Dict[str, Any]],
    passage_rows: List[Dict[str, Any]],
    page_rows: List[Dict[str, Any]],
    visual_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    section_rows = list(section_rows)
    section_by_id = {str(row.get("section_id") or ""): row for row in section_rows}
    passages_by_section: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    page_lookup = {int(row.get("page") or 0): row for row in page_rows}
    visual_by_page: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for row in visual_rows:
        visual_by_page[int(row.get("page") or 0)].append(row)
    for row in passage_rows:
        passages_by_section[str(row.get("section_id") or "")].append(row)

    used_section_ids: set[str] = set()
    truth_matches: List[Dict[str, Any]] = []
    missing_truth_rows: List[Dict[str, Any]] = []

    for truth in truth_rows:
        direct_candidates = []
        truth_key = normalize_key(truth.get("title"))
        truth_page = int(truth.get("page") or 0)
        for section in section_rows:
            section_id = str(section.get("section_id") or "")
            if not section_id or section_id in used_section_ids:
                continue
            if normalize_key(section.get("title")) != truth_key:
                continue
            direct_candidates.append(section)
        if direct_candidates:
            direct_candidates.sort(
                key=lambda section: (
                    abs(int(section.get("page_start") or 0) - truth_page),
                    abs(int(section.get("page_end") or 0) - truth_page),
                )
            )
            section = direct_candidates[0]
            best_match = {
                "section_id": str(section.get("section_id") or ""),
                "section_title": section.get("title"),
                "section_page_start": int(section.get("page_start") or 0),
                "section_page_end": int(section.get("page_end") or 0),
                "title_score": 1.0,
                "page_delta": abs(int(section.get("page_start") or 0) - truth_page),
                "total_score": 1.0,
            }
        else:
            best_match = None
        for section in section_rows:
            section_id = str(section.get("section_id") or "")
            if not section_id or section_id in used_section_ids:
                continue
            title_score = fuzzy_title_match(truth.get("title"), section.get("title"))
            page_delta = abs(int(section.get("page_start") or 0) - int(truth.get("page") or 0))
            page_score = 1.0 if page_delta == 0 else 0.85 if page_delta == 1 else 0.7 if page_delta == 2 else 0.45 if page_delta <= 4 else 0.0
            total = round((title_score * 0.8) + (page_score * 0.2), 4)
            candidate = {
                "section_id": section_id,
                "section_title": section.get("title"),
                "section_page_start": int(section.get("page_start") or 0),
                "section_page_end": int(section.get("page_end") or 0),
                "title_score": title_score,
                "page_delta": page_delta,
                "total_score": total,
            }
            if best_match is None or float(candidate["total_score"]) > float(best_match["total_score"]):
                best_match = candidate
        if best_match and (
            (float(best_match["title_score"]) >= 0.86 and int(best_match["page_delta"]) <= 2)
            or (float(best_match["title_score"]) >= 0.93 and int(best_match["page_delta"]) <= 5)
        ):
            used_section_ids.add(str(best_match["section_id"]))
            matched_section = section_by_id[str(best_match["section_id"])]
            section_passages = passages_by_section.get(str(best_match["section_id"]), [])
            matched_payload = {
                "truth_title": truth.get("title"),
                "truth_page": truth.get("page"),
                "truth_kind": truth.get("kind"),
                **best_match,
                "retrieval_eligible": bool(matched_section.get("retrieval_eligible", True)),
                "quality_flags": list(matched_section.get("quality_flags") or []),
                "passage_count": len(section_passages),
                "passage_page_start": min([int((row.get("page_span") or {}).get("page_start") or matched_section.get("page_start") or 0) for row in section_passages], default=int(matched_section.get("page_start") or 0)),
                "passage_page_end": max([int((row.get("page_span") or {}).get("page_end") or matched_section.get("page_end") or 0) for row in section_passages], default=int(matched_section.get("page_end") or 0)),
            }
            truth_matches.append(matched_payload)
        else:
            missing_truth_rows.append(
                {
                    "truth_title": truth.get("title"),
                    "truth_page": truth.get("page"),
                    "truth_kind": truth.get("kind"),
                    "best_section_title": (best_match or {}).get("section_title"),
                    "best_title_score": (best_match or {}).get("title_score"),
                    "best_page_delta": (best_match or {}).get("page_delta"),
                }
            )

    unmatched_sections: List[Dict[str, Any]] = []
    for section in section_rows:
        section_id = str(section.get("section_id") or "")
        if not section_id or section_id in used_section_ids:
            continue
        page_start = int(section.get("page_start") or 0)
        independent_visual_match = False
        for candidate_page in range(max(1, page_start - 1), page_start + 2):
            for visual in visual_by_page.get(candidate_page, []):
                if fuzzy_title_match(section.get("title"), visual.get("title")) >= 0.84:
                    independent_visual_match = True
                    break
            if independent_visual_match:
                break
        independent_text_match = any(
            text_contains_heading((page_lookup.get(candidate_page) or {}).get("text") or "", section.get("title"))
            for candidate_page in range(max(1, page_start - 1), page_start + 2)
        )
        unmatched_sections.append(
            {
                "section_id": section_id,
                "title": section.get("title"),
                "page_start": page_start,
                "page_end": int(section.get("page_end") or 0),
                "retrieval_eligible": bool(section.get("retrieval_eligible", True)),
                "quality_flags": list(section.get("quality_flags") or []),
                "independently_verified": bool(independent_visual_match or independent_text_match),
            }
        )

    content_extras = [
        row
        for row in unmatched_sections
        if bool(row.get("retrieval_eligible", True))
        and "structural_wrapper" not in (row.get("quality_flags") or [])
        and not bool(row.get("independently_verified"))
    ]
    wrapper_extras = [row for row in unmatched_sections if row not in content_extras]
    page_deltas = [int(row.get("page_delta") or 0) for row in truth_matches]
    return {
        "matches": truth_matches,
        "missing_truth_rows": missing_truth_rows,
        "unmatched_sections": unmatched_sections,
        "content_extras": content_extras,
        "wrapper_extras": wrapper_extras,
        "summary": {
            "truth_heading_count": len(truth_rows),
            "matched_truth_heading_count": len(truth_matches),
            "missing_truth_heading_count": len(missing_truth_rows),
            "unmatched_section_count": len(unmatched_sections),
            "content_extra_count": len(content_extras),
            "wrapper_extra_count": len(wrapper_extras),
            "median_page_delta": statistics.median(page_deltas) if page_deltas else None,
        },
    }


def classify_doc_result(summary: Dict[str, Any]) -> str:
    truth_count = int(summary.get("truth_heading_count") or 0)
    missing = int(summary.get("missing_truth_heading_count") or 0)
    content_extras = int(summary.get("content_extra_count") or 0)
    match_ratio = float(summary.get("matched_truth_heading_count") or 0) / max(1, truth_count)
    if truth_count == 0:
        return "needs_manual_review"
    if match_ratio >= 0.88 and missing <= 2 and content_extras <= 3:
        return "strong"
    if match_ratio >= 0.72 and missing <= 6 and content_extras <= 8:
        return "acceptable_with_noise"
    return "needs_follow_up"


def write_jsonl(path: Path, rows: Iterable[Any]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def render_doc_index_html(
    doc_dir: Path,
    *,
    doc_row: Dict[str, Any],
    outline_rows: List[Dict[str, Any]],
    verified_outline_rows: List[Dict[str, Any]],
    truth_rows: List[Dict[str, Any]],
    evaluation: Dict[str, Any],
    selected_pages: List[int],
) -> None:
    def table(headers: List[str], rows: List[Dict[str, Any]]) -> str:
        head_html = "".join(f"<th>{html.escape(col)}</th>" for col in headers)
        body_rows = []
        for row in rows:
            body_cells = "".join(f"<td>{html.escape(str(row.get(col, '')))}</td>" for col in headers)
            body_rows.append(f"<tr>{body_cells}</tr>")
        body_html = "".join(body_rows) or f"<tr><td colspan='{len(headers)}'>(empty)</td></tr>"
        return f"<table><thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table>"

    page_links = "".join(
        f"<li><a href='pages/page_{int(page):04d}.html'>Page {int(page)}</a></li>"
        for page in selected_pages
    )
    html_text = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{html.escape(str(doc_row.get("doc_id") or ""))}</title>
  <style>
    body {{ font-family: Georgia, 'Times New Roman', serif; margin: 24px; line-height: 1.4; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th, td {{ border: 1px solid #ccc; padding: 6px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f3f3; }}
    code {{ background: #f5f5f5; padding: 1px 4px; }}
  </style>
</head>
<body>
  <h1>{html.escape(str(doc_row.get("title") or ""))}</h1>
  <p><strong>doc_id:</strong> <code>{html.escape(str(doc_row.get("doc_id") or ""))}</code></p>
  <p><strong>source:</strong> {html.escape(str(doc_row.get("source_path") or ""))}</p>
  <h2>Summary</h2>
  {table(["metric", "value"], [{"metric": k, "value": v} for k, v in evaluation.get("summary", {}).items()])}
  <h2>Outline Rows</h2>
  {table(["level", "title", "page"], outline_rows[:50])}
  <h2>Verified Outline Rows</h2>
  {table(["level", "title", "page", "matched_page", "evidence", "score"], verified_outline_rows[:50])}
  <h2>Truth Headings</h2>
  {table(["kind", "title", "page", "confidence"], truth_rows[:80])}
  <h2>Matched Truth Headings</h2>
  {table(["truth_title", "truth_page", "section_title", "section_page_start", "title_score", "page_delta", "passage_count"], evaluation.get("matches", [])[:80])}
  <h2>Missing Truth Headings</h2>
  {table(["truth_title", "truth_page", "best_section_title", "best_title_score", "best_page_delta"], evaluation.get("missing_truth_rows", [])[:80])}
  <h2>Content Extras</h2>
  {table(["title", "page_start", "page_end", "retrieval_eligible", "quality_flags"], evaluation.get("content_extras", [])[:80])}
  <h2>Inspection Pages</h2>
  <ul>{page_links}</ul>
</body>
</html>
"""
    (doc_dir / "index.html").write_text(html_text, encoding="utf-8")


def select_inspection_pages(
    page_rows: List[Dict[str, Any]],
    verified_outline_rows: List[Dict[str, Any]],
    truth_rows: List[Dict[str, Any]],
    evaluation: Dict[str, Any],
) -> List[int]:
    pages = {1, 2}
    pages.update(find_contents_pages(page_rows))
    pages.update(int(row.get("matched_page") or row.get("page") or 0) for row in verified_outline_rows[:8])
    pages.update(int(row.get("page") or 0) for row in truth_rows[:10])
    pages.update(int(row.get("truth_page") or 0) for row in (evaluation.get("missing_truth_rows") or [])[:8])
    pages = {page for page in pages if page > 0}
    return sorted(pages)


def write_page_html(doc: Any, page_number: int, out_path: Path) -> None:
    page = doc[int(page_number) - 1]
    html_text = page.get_text("html")
    out_path.write_text(html_text, encoding="utf-8")


def evaluate_doc(
    run_dir: Path,
    doc_row: Dict[str, Any],
    section_rows: List[Dict[str, Any]],
    passage_rows: List[Dict[str, Any]],
    output_dir: Path,
) -> Dict[str, Any]:
    if fitz is None:
        raise RuntimeError(f"PyMuPDF unavailable: {FITZ_IMPORT_ERROR}")

    source_path = Path(str(doc_row.get("source_path") or "")).resolve()
    doc_dir = ensure_dir(output_dir / str(doc_row.get("doc_id") or "unknown"))
    doc = fitz.open(source_path)
    page_rows = extract_page_rows(doc)
    outline_rows = extract_outline_rows(doc)
    visual_rows = extract_visual_heading_candidates(doc)
    verified_outline_rows = verify_outline_rows(outline_rows, page_rows, visual_rows)
    truth_rows = build_truth_headings(outline_rows, verified_outline_rows, visual_rows)
    evaluation = compare_truth_to_phase_c(truth_rows, section_rows, passage_rows, page_rows, visual_rows)
    category = classify_doc_result(evaluation["summary"])
    selected_pages = select_inspection_pages(page_rows, verified_outline_rows, truth_rows, evaluation)

    write_json(doc_dir / "document_summary.json", {**doc_row, **evaluation["summary"], "category": category})
    write_json(doc_dir / "outline_rows.json", {"rows": outline_rows})
    write_json(doc_dir / "verified_outline_rows.json", {"rows": verified_outline_rows})
    write_json(doc_dir / "truth_headings.json", {"rows": truth_rows})
    write_json(doc_dir / "evaluation.json", {"category": category, **evaluation})
    write_jsonl(doc_dir / "page_texts.jsonl", page_rows)
    write_jsonl(doc_dir / "visual_headings.jsonl", visual_rows)

    for page_number in selected_pages:
        out_path = page_html_path(doc_dir, page_number)
        ensure_dir(out_path.parent)
        write_page_html(doc, page_number, out_path)

    render_doc_index_html(
        doc_dir,
        doc_row=doc_row,
        outline_rows=outline_rows,
        verified_outline_rows=verified_outline_rows,
        truth_rows=truth_rows,
        evaluation=evaluation,
        selected_pages=selected_pages,
    )

    match_ratio = round(
        float(evaluation["summary"].get("matched_truth_heading_count") or 0) / max(1, int(evaluation["summary"].get("truth_heading_count") or 0)),
        4,
    )
    return {
        "doc_id": doc_row.get("doc_id"),
        "title": doc_row.get("title"),
        "source_path": str(source_path),
        "page_count": doc.page_count,
        "outline_count": len(outline_rows),
        "verified_outline_count": len(verified_outline_rows),
        "truth_heading_count": len(truth_rows),
        "matched_truth_heading_count": evaluation["summary"].get("matched_truth_heading_count"),
        "missing_truth_heading_count": evaluation["summary"].get("missing_truth_heading_count"),
        "content_extra_count": evaluation["summary"].get("content_extra_count"),
        "wrapper_extra_count": evaluation["summary"].get("wrapper_extra_count"),
        "median_page_delta": evaluation["summary"].get("median_page_delta"),
        "match_ratio": match_ratio,
        "category": category,
        "inspection_index_html": str((doc_dir / "index.html").relative_to(run_dir)),
        "sample_missing_truth_titles": [row.get("truth_title") for row in (evaluation.get("missing_truth_rows") or [])[:6]],
        "sample_content_extras": [row.get("title") for row in (evaluation.get("content_extras") or [])[:6]],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Independent Phase C truth-lab against the actual PDFs.")
    parser.add_argument("--base-dir", default="pdf-scan", help="Path to pdf-scan")
    parser.add_argument("--run-id", required=True, help="Run id containing normalized Phase C outputs")
    parser.add_argument("--output-subdir", default="phase_c_truth", help="Subdirectory under the run directory")
    parser.add_argument("--max-docs", type=int, default=None, help="Optional cap for debugging")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    base_dir = Path(args.base_dir).resolve()
    run_dir = (base_dir / "runs" / str(args.run_id)).resolve()
    normalized_dir = run_dir / "normalized"
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    documents = read_jsonl_rows(normalized_dir / "documents.jsonl")
    sections = read_jsonl_rows(normalized_dir / "sections.jsonl")
    passages = read_jsonl_rows(normalized_dir / "passages.jsonl")
    if args.max_docs is not None:
        documents = documents[: int(args.max_docs)]

    sections_by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    passages_by_doc: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    section_doc_lookup: Dict[str, str] = {}
    for row in sections:
        doc_id = str(row.get("doc_id") or "")
        sections_by_doc[doc_id].append(row)
        section_doc_lookup[str(row.get("section_id") or "")] = doc_id
    for row in passages:
        section_id = str(row.get("section_id") or "")
        doc_id = section_doc_lookup.get(section_id, "")
        if doc_id:
            passages_by_doc[doc_id].append(row)

    output_dir = ensure_dir(run_dir / str(args.output_subdir))
    aggregate_rows: List[Dict[str, Any]] = []
    for doc_row in documents:
        doc_id = str(doc_row.get("doc_id") or "")
        result = evaluate_doc(
            run_dir,
            doc_row,
            sections_by_doc.get(doc_id, []),
            passages_by_doc.get(doc_id, []),
            output_dir,
        )
        aggregate_rows.append(result)

    category_counts: Dict[str, int] = defaultdict(int)
    for row in aggregate_rows:
        category_counts[str(row.get("category") or "unknown")] += 1
    match_ratios = [float(row.get("match_ratio") or 0.0) for row in aggregate_rows if row.get("truth_heading_count")]
    aggregate_summary = {
        "run_id": run_dir.name,
        "doc_count": len(aggregate_rows),
        "category_counts": dict(category_counts),
        "mean_match_ratio": round(sum(match_ratios) / max(1, len(match_ratios)), 4),
        "median_match_ratio": round(statistics.median(match_ratios), 4) if match_ratios else None,
        "docs_needing_follow_up": [row.get("doc_id") for row in aggregate_rows if row.get("category") == "needs_follow_up"],
        "docs_requiring_manual_review": [row.get("doc_id") for row in aggregate_rows if row.get("category") == "needs_manual_review"],
    }

    write_json(output_dir / "aggregate_summary.json", aggregate_summary)
    write_json(output_dir / "aggregate_rows.json", {"rows": aggregate_rows})

    print_section("Phase C Truth Lab")
    print_kv(aggregate_summary)
    print_section("Per-Document Results")
    print_table(
        aggregate_rows,
        columns=[
            "doc_id",
            "truth_heading_count",
            "matched_truth_heading_count",
            "missing_truth_heading_count",
            "content_extra_count",
            "match_ratio",
            "category",
        ],
        max_rows=40,
        max_col_width=36,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
