"""Quellen-Finder PDF extract/highlight pipeline (ported from pdf-scan/text-extract-test.ipynb).

This module extracts a *section band* around a hit anchor using strict heading detection and
returns per-page highlight rectangles (normalized 0..1) that can be rendered in a PDF viewer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF

from utils.pdf_text_utils import norm_match, norm_token, normalize_ws


# Cell 3 — Robust anchor search (word-based, survives line breaks)


@dataclass
class AnchorMatch:
    page: int  # 1-based
    y0: float
    y1: float
    x0: float
    x1: float
    start_word_i: int
    end_word_i: int


def _tokenize_anchor(anchor: str) -> List[str]:
    toks = [norm_token(t) for t in normalize_ws(anchor).split()]
    return [t for t in toks if t]


def find_anchor_in_page_words(page: Any, anchor_tokens: List[str]) -> List[AnchorMatch]:
    if len(anchor_tokens) < 3:
        return []

    words = page.get_text("words") or []
    # (x0, y0, x1, y1, text, block_no, line_no, word_no)
    words.sort(key=lambda w: (w[5], w[6], w[7], w[1], w[0]))  # reading-ish order
    page_tokens = [norm_token(w[4]) for w in words]

    n = len(anchor_tokens)
    if len(page_tokens) < n:
        return []

    matches: List[AnchorMatch] = []
    for i in range(0, len(page_tokens) - n + 1):
        if page_tokens[i : i + n] == anchor_tokens:
            xs0 = min(words[j][0] for j in range(i, i + n))
            ys0 = min(words[j][1] for j in range(i, i + n))
            xs1 = max(words[j][2] for j in range(i, i + n))
            ys1 = max(words[j][3] for j in range(i, i + n))
            matches.append(
                AnchorMatch(
                    page=page.number + 1,
                    y0=float(ys0),
                    y1=float(ys1),
                    x0=float(xs0),
                    x1=float(xs1),
                    start_word_i=i,
                    end_word_i=i + n - 1,
                )
            )
    return matches


def find_anchor_matches_in_doc(
    doc: Any,
    anchor: str,
    *,
    max_keep: int = 20,
) -> Dict[str, Any]:
    """Returns {anchor, total, matches, truncated}.

    - total counts all matches (full scan)
    - matches keeps up to max_keep earliest matches (page/y order)
    """

    anchor_norm = normalize_ws(anchor)
    tokens = _tokenize_anchor(anchor_norm)
    if not anchor_norm or len(tokens) < 3:
        return {"anchor": anchor_norm, "total": 0, "matches": [], "truncated": False}

    total = 0
    kept: List[AnchorMatch] = []

    for pno in range(doc.page_count):
        page = doc.load_page(pno)
        hits = find_anchor_in_page_words(page, tokens)
        if not hits:
            continue
        total += len(hits)
        if len(kept) < int(max_keep):
            kept.extend(hits[: max(0, int(max_keep) - len(kept))])

    kept.sort(key=lambda m: (m.page, m.y0, m.x0))
    return {
        "anchor": anchor_norm,
        "total": int(total),
        "matches": kept,
        "truncated": bool(total > len(kept)),
    }


# Cell 4 — Body-font estimation + strict heading detection + merging


@dataclass
class Heading:
    text: str
    page: int  # 1-based
    y0: float
    level: int  # 1 = highest
    font_size: float
    is_numbered: bool


HEADING_KEYWORDS = {
    "abstract",
    "introduction",
    "background",
    "related work",
    "methodology",
    "methods",
    "results",
    "discussion",
    "conclusion",
    "conclusions",
    "future work",
    "references",
    "acknowledgment",
    "acknowledgements",
    "appendix",
}

METADATA_BADWORDS = {
    "issn",
    "doi",
    "volume",
    "issue",
    "pages",
    "website",
    "journal",
    "http",
    "https",
    "www.",
}


def estimate_body_font_size(doc: Any, max_pages: int = 12) -> float:
    """Estimate dominant body font size (weighted by characters) from first N pages."""

    size_weight: Dict[float, int] = {}

    n_pages = min(doc.page_count, int(max_pages))
    for pno in range(n_pages):
        page = doc.load_page(pno)
        d = page.get_text("dict")
        for b in d.get("blocks", []):
            if b.get("type") != 0:
                continue
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    txt = span.get("text", "")
                    if not txt.strip():
                        continue
                    sz = round(float(span.get("size", 0.0)), 1)
                    size_weight[sz] = size_weight.get(sz, 0) + len(txt)

    if not size_weight:
        return 12.0

    body_size = max(size_weight.items(), key=lambda kv: kv[1])[0]
    return float(body_size)


def looks_like_metadata(line: str) -> bool:
    s = (line or "").lower()
    if any(w in s for w in METADATA_BADWORDS):
        return True
    if "||" in s and ("volume" in s or "issue" in s or "pages" in s):
        return True
    return False


def is_heading_candidate(text: str, avg_size: float, body_size: float, font_names: List[str]) -> bool:
    """Very strict: accept only if matches heading patterns/keywords or clearly larger than body."""

    t = normalize_ws(text)
    if not t:
        return False
    low = t.lower()

    if looks_like_metadata(t):
        return False

    if len(t) > 140:
        return False

    if re.match(r"^(\d+(\.\d+)*)\s+\S+", t):
        return True

    if low in HEADING_KEYWORDS:
        return True

    is_boldish = any("bold" in (fn or "").lower() for fn in (font_names or []))

    if float(avg_size) >= float(body_size) + 1.6:
        return True
    if is_boldish and float(avg_size) >= float(body_size) + 0.8 and len(t.split()) <= 14:
        return True

    return False


def merge_multiline_headings(headings: List[Heading]) -> List[Heading]:
    """Merge consecutive headings on same page with similar font size/level and close y-distance."""

    if not headings:
        return headings

    merged: List[Heading] = []
    cur = headings[0]

    for h in headings[1:]:
        same_page = h.page == cur.page
        close_y = same_page and abs(h.y0 - cur.y0) <= 50
        similar_size = abs(h.font_size - cur.font_size) <= 0.4
        same_level = h.level == cur.level

        if same_page and close_y and similar_size and same_level:
            cur = Heading(
                text=normalize_ws(cur.text + " " + h.text),
                page=cur.page,
                y0=min(cur.y0, h.y0),
                level=cur.level,
                font_size=cur.font_size,
                is_numbered=cur.is_numbered or h.is_numbered,
            )
        else:
            merged.append(cur)
            cur = h

    merged.append(cur)
    return merged


def filter_repeated_running_headers(
    headings: List[Heading],
    doc: Any,
    *,
    min_count: int = 4,
    min_ratio: float = 0.2,
    margin_y: float = 70.0,
) -> List[Heading]:
    """Drop very frequently repeated headings near page top/bottom (likely running headers/footers)."""

    if not headings:
        return headings

    page_heights = {pno + 1: float(doc.load_page(pno).rect.height) for pno in range(doc.page_count)}

    key_for = lambda t: norm_match(t).lower().strip()
    groups: Dict[str, List[Heading]] = {}
    for h in headings:
        groups.setdefault(key_for(h.text), []).append(h)

    total_pages = max(1, int(doc.page_count))
    drop_keys = set()

    for k, hs in groups.items():
        if len(hs) < int(min_count):
            continue
        if (len(hs) / total_pages) < float(min_ratio):
            continue

        all_margin = True
        for h in hs:
            ph = page_heights.get(int(h.page), 0.0)
            if not (float(h.y0) <= float(margin_y) or float(h.y0) >= ph - float(margin_y)):
                all_margin = False
                break
        if all_margin:
            drop_keys.add(k)

    if not drop_keys:
        return headings

    return [h for h in headings if key_for(h.text) not in drop_keys]


def build_heading_index_strict(doc: Any, max_levels: int = 4) -> Tuple[List[Heading], float]:
    body_size = estimate_body_font_size(doc)

    candidates = []
    for pno in range(doc.page_count):
        page = doc.load_page(pno)
        d = page.get_text("dict")
        for b in d.get("blocks", []):
            if b.get("type") != 0:
                continue
            for line in b.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue

                line_text = "".join(sp.get("text", "") for sp in spans)
                t = normalize_ws(line_text)
                if not t:
                    continue

                num = 0.0
                den = 0
                fonts = []
                for sp in spans:
                    txt = sp.get("text", "")
                    if not txt:
                        continue
                    sz = float(sp.get("size", 0.0))
                    w = len(txt)
                    num += sz * w
                    den += w
                    fonts.append(sp.get("font", ""))
                avg_size = (num / den) if den else float(spans[0].get("size", 0.0))

                if not is_heading_candidate(t, avg_size, body_size, fonts):
                    continue

                if t.endswith((",", ";", ":")) and not re.match(r"^(\d+(\.\d+)*)\s+\S+", t):
                    continue

                y0 = min(sp["bbox"][1] for sp in spans if "bbox" in sp)
                is_num = bool(re.match(r"^(\d+(\.\d+)*)\s+\S+", t))
                candidates.append((t, pno + 1, float(y0), float(avg_size), bool(is_num)))

    if not candidates:
        return [], body_size

    sizes = sorted({round(c[3], 1) for c in candidates}, reverse=True)
    size_levels = sizes[: int(max_levels)]

    def level_for(sz: float, text: str) -> int:
        m = re.match(r"^(\d+(\.\d+)*)\s+", text)
        if m:
            depth = m.group(1).count(".") + 1
            return max(1, min(4, int(depth)))
        s = round(float(sz), 1)
        nearest = min(size_levels, key=lambda x: abs(x - s))
        return int(size_levels.index(nearest) + 1)

    headings = [
        Heading(
            text=t,
            page=int(pg),
            y0=float(y0),
            level=int(level_for(sz, t)),
            font_size=float(sz),
            is_numbered=bool(is_num),
        )
        for (t, pg, y0, sz, is_num) in candidates
    ]
    headings.sort(key=lambda h: (h.page, h.y0))
    headings = merge_multiline_headings(headings)
    headings = filter_repeated_running_headers(headings, doc)
    return headings, body_size


# Cell 5 — Extraction using STRICT headings (and a sanity fallback)


_SECTION_END_EPS = 0.1  # exclude the next heading line


def find_heading_before_anchor(headings: List[Heading], loc: AnchorMatch) -> Optional[int]:
    best = None
    for i, h in enumerate(headings):
        if (h.page < loc.page) or (h.page == loc.page and h.y0 <= loc.y0):
            best = i
        else:
            break
    return best


def extract_between(doc: Any, start: Tuple[int, float], end: Optional[Tuple[int, float]] = None) -> str:
    start_page, start_y = start
    if end is None:
        end_page, end_y = doc.page_count, None
    else:
        end_page, end_y = end

    parts = []
    for pno in range(start_page, end_page + 1):
        page = doc.load_page(pno - 1)
        rect = page.rect
        y0 = float(start_y) if pno == start_page else float(rect.y0)
        y1 = float(end_y) if (end_y is not None and pno == end_page) else float(rect.y1)
        clip = fitz.Rect(rect.x0, y0, rect.x1, y1)
        parts.append(page.get_text("text", clip=clip))

    return "\n".join(parts).replace("\u00ad", "")


def _iter_section_page_ranges(
    doc: Any,
    start: Tuple[int, float],
    end: Optional[Tuple[int, float]],
):
    start_page, start_y = int(start[0]), float(start[1])
    if end is None:
        end_page, end_y = int(doc.page_count), None
    else:
        end_page, end_y = int(end[0]), float(end[1])

    for pno in range(start_page, end_page + 1):
        page = doc.load_page(pno - 1)
        rect = page.rect
        y0 = float(start_y) if pno == start_page else float(rect.y0)
        y1 = float(end_y) if (end_y is not None and pno == end_page) else float(rect.y1)
        yield pno, page, rect, y0, y1


def build_section_highlights(
    doc: Any,
    start: Tuple[int, float],
    end: Optional[Tuple[int, float]],
    *,
    pad_x: float = 0.6,
    pad_y: float = 0.4,
    max_rects_per_page: int = 2000,
) -> Dict[str, Any]:
    """Return highlight rectangles for the whole section.

    Coordinates are in PyMuPDF page space (origin top-left, y down, units=points).
    Also returns normalized coords (0..1) for easy overlay rendering.
    """

    pages_out = []
    any_truncated = False

    for pno, page, rect, y0, y1 in _iter_section_page_ranges(doc, start, end):
        words = page.get_text("words") or []
        # (x0, y0, x1, y1, text, block_no, line_no, word_no)

        # Filter words that intersect the vertical band.
        band_words = []
        for w in words:
            wy0, wy1 = float(w[1]), float(w[3])
            if wy1 < float(y0) or wy0 > float(y1):
                continue
            band_words.append(w)

        # Group by (block_no, line_no) and merge into a stripe.
        groups = {}
        for w in band_words:
            key = (int(w[5]), int(w[6]))
            groups.setdefault(key, []).append(w)

        line_rects = []
        for (_blk, _ln), ws in groups.items():
            x0 = min(float(w[0]) for w in ws)
            y0l = min(float(w[1]) for w in ws)
            x1 = max(float(w[2]) for w in ws)
            y1l = max(float(w[3]) for w in ws)

            # Clamp to the section band and add a small padding.
            x0 = max(float(rect.x0), x0 - float(pad_x))
            x1 = min(float(rect.x1), x1 + float(pad_x))
            y0c = max(float(y0), y0l - float(pad_y))
            y1c = min(float(y1), y1l + float(pad_y))

            if x1 <= x0 or y1c <= y0c:
                continue

            w_page = float(rect.width) or 1.0
            h_page = float(rect.height) or 1.0

            line_rects.append(
                {
                    "x0": float(x0),
                    "y0": float(y0c),
                    "x1": float(x1),
                    "y1": float(y1c),
                    "x0n": float(x0) / w_page,
                    "y0n": float(y0c) / h_page,
                    "x1n": float(x1) / w_page,
                    "y1n": float(y1c) / h_page,
                }
            )

        line_rects.sort(key=lambda r: (r["y0"], r["x0"]))

        truncated = False
        if len(line_rects) > int(max_rects_per_page):
            line_rects = line_rects[: int(max_rects_per_page)]
            truncated = True
            any_truncated = True

        pages_out.append(
            {
                "page": int(pno),
                "width": float(rect.width),
                "height": float(rect.height),
                "y0": float(y0),
                "y1": float(y1),
                "rects": line_rects,
                "truncated": bool(truncated),
            }
        )

    return {"pages": pages_out, "truncated": bool(any_truncated)}


def _hint_tokens(locator_hint: Optional[str]) -> List[str]:
    toks = [norm_token(t) for t in normalize_ws(locator_hint or "").split()]
    return [t for t in toks if t]


def _token_overlap_score(tokens: List[str], text: str, *, cap: int) -> int:
    if not tokens:
        return 0
    s = normalize_ws(text)
    if not s:
        return 0
    present = {norm_token(t) for t in s.split() if norm_token(t)}
    score = sum(1 for t in tokens if t in present)
    return int(min(int(cap), int(score)))


def _context_window_text(doc: Any, loc: AnchorMatch, *, above: float = 250.0, below: float = 800.0) -> str:
    page = doc.load_page(loc.page - 1)
    rect = page.rect
    top = max(float(rect.y0), float(loc.y0) - float(above))
    bot = min(float(rect.y1), float(loc.y1) + float(below))
    clip = fitz.Rect(rect.x0, top, rect.x1, bot)
    return page.get_text("text", clip=clip)


def _pick_best_loc(
    doc: Any,
    headings: List[Heading],
    *,
    anchor: str,
    anchor_alt: str,
    locator_hint: Optional[str],
) -> Dict[str, Any]:
    """Pick best location among all matches using heading+hint heuristics.

    If still tied, returns the first match (page/y order) and sets ambiguous=True.
    """

    primary = find_anchor_matches_in_doc(doc, anchor, max_keep=30)
    alt = (
        find_anchor_matches_in_doc(doc, anchor_alt, max_keep=30)
        if normalize_ws(anchor_alt)
        else {"anchor": "", "total": 0, "matches": [], "truncated": False}
    )

    candidates = []
    for variant, res, bonus in [
        ("anchor", primary, 100),
        ("anchor_alt", alt, 90),
    ]:
        for m in res.get("matches") or []:
            candidates.append((variant, m, bonus, int(res.get("total") or 0), bool(res.get("truncated"))))

    if not candidates:
        return {"ok": False, "reason": "anchor_not_found"}

    hint_toks = _hint_tokens(locator_hint)

    scored = []
    for variant, m, base, total, truncated in candidates:
        score = int(base)

        h_idx = find_heading_before_anchor(headings, m)
        if h_idx is not None:
            h = headings[int(h_idx)]
            score += 25
            score += _token_overlap_score(hint_toks, h.text, cap=10)

        if hint_toks:
            ctx = _context_window_text(doc, m)
            score += _token_overlap_score(hint_toks, ctx, cap=15)

        scored.append(
            {
                "variant": variant,
                "match": m,
                "score": int(score),
                "match_total": int(total),
                "match_truncated": bool(truncated),
            }
        )

    scored.sort(key=lambda x: (-x["score"], x["match"].page, x["match"].y0, x["match"].x0))
    best = scored[0]
    best_score = best["score"]
    ties = [x for x in scored if x["score"] == best_score]

    best["ambiguous"] = bool(len(ties) > 1)
    best["tied_candidates"] = int(len(ties))
    if best["ambiguous"]:
        best["tied_pages"] = sorted({int(x["match"].page) for x in ties})

    return {"ok": True, **best}


def _section_end_from_heading(headings: List[Heading], h_idx: int) -> Optional[Tuple[int, float]]:
    h = headings[int(h_idx)]
    for nxt in headings[int(h_idx) + 1 :]:
        if int(nxt.level) <= int(h.level):
            return (int(nxt.page), float(nxt.y0) - float(_SECTION_END_EPS))
    return None


def extract_section_by_hit(doc: Any, hit: Any, headings: List[Heading]) -> Dict[str, Any]:
    if isinstance(hit, str):
        anchor = hit
        anchor_alt = ""
        locator_hint = None
    elif isinstance(hit, dict):
        anchor = str(hit.get("anchor") or "")
        anchor_alt = str(hit.get("anchor_alt") or "")
        locator_hint = hit.get("locator_hint")
    else:
        return {"ok": False, "reason": "invalid_hit"}

    picked = _pick_best_loc(doc, headings, anchor=anchor, anchor_alt=anchor_alt, locator_hint=locator_hint)
    if not picked.get("ok"):
        return {"ok": False, "reason": picked.get("reason"), "anchor": anchor}

    loc: AnchorMatch = picked["match"]
    h_idx = find_heading_before_anchor(headings, loc)

    if h_idx is None:
        page = doc.load_page(loc.page - 1)
        rect = page.rect
        top = max(float(rect.y0), float(loc.y0) - 300)
        bot = min(float(rect.y1), float(loc.y1) + 1200)
        txt = page.get_text("text", clip=fitz.Rect(rect.x0, top, rect.x1, bot)).replace("­", "")
        hl = build_section_highlights(doc, (int(loc.page), float(top)), (int(loc.page), float(bot)))
        return {
            "ok": True,
            "method": "window_fallback",
            "section_title": None,
            "section_level": None,
            "anchor_page": int(loc.page),
            "anchor_used": picked.get("variant"),
            "anchor_match_total": int(picked.get("match_total") or 0),
            "anchor_match_truncated": bool(picked.get("match_truncated")),
            "ambiguous": bool(picked.get("ambiguous")),
            "tied_candidates": int(picked.get("tied_candidates") or 0),
            "tied_pages": picked.get("tied_pages"),
            "start": {"page": int(loc.page), "y": float(top)},
            "end": {"page": int(loc.page), "y": float(bot)},
            "highlights": hl,
            "text": txt,
        }

    h = headings[int(h_idx)]
    end = _section_end_from_heading(headings, int(h_idx))

    text = extract_between(doc, (int(h.page), float(h.y0)), end)
    hl = build_section_highlights(doc, (int(h.page), float(h.y0)), end)

    return {
        "ok": True,
        "method": "heading_bounds",
        "section_title": h.text,
        "section_level": int(h.level),
        "anchor_page": int(loc.page),
        "anchor_used": picked.get("variant"),
        "anchor_match_total": int(picked.get("match_total") or 0),
        "anchor_match_truncated": bool(picked.get("match_truncated")),
        "ambiguous": bool(picked.get("ambiguous")),
        "tied_candidates": int(picked.get("tied_candidates")) if picked.get("tied_candidates") is not None else 0,
        "tied_pages": picked.get("tied_pages"),
        "start": {"page": int(h.page), "y": float(h.y0)},
        "end": {"page": int(end[0]), "y": float(end[1])} if end else None,
        "highlights": hl,
        "text": text,
    }

