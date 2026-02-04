"""Quellen-Finder PDF scan pipeline (ported from pdf-scan-test.ipynb).

This module contains mostly pure helpers used by the PDF scan job.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from utils.pdf_text_utils import (
    normalize_spaces,
    norm_word,
    validate_anchor,
    derive_anchor_alt_from_span,
    expand_span,
)

logger = logging.getLogger(__name__)


def normalize_whitespace(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines).strip()


PREPROCESS_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "optimized_description": {
            "type": "string",
            "description": "Kompakte such-optimierte Kapitelbeschreibung (Deutsch, max ~1200 Zeichen).",
            "maxLength": 1200,
        },
        "must_terms": {
            "type": "array",
            "description": "Begriffe/Phrasen, die idealerweise im Treffer vorkommen (DE/EN gemischt erlaubt).",
            "maxItems": 18,
            "items": {"type": "string", "maxLength": 80},
        },
        "should_terms": {
            "type": "array",
            "description": "Unterstützende Begriffe/Synonyme/Keywords (DE/EN).",
            "maxItems": 35,
            "items": {"type": "string", "maxLength": 80},
        },
        "subpoints": {
            "type": "array",
            "description": "Unterpunkte wie (2.1) ... (falls vorhanden), sonst leere Liste.",
            "maxItems": 25,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "maxLength": 20},
                    "label": {"type": "string", "maxLength": 180},
                    "keywords": {
                        "type": "array",
                        "description": "Retrieval-Keywords je Subpoint (DE/EN erlaubt).",
                        "maxItems": 14,
                        "items": {"type": "string", "maxLength": 80},
                    },
                    "exclusions": {
                        "type": "array",
                        "maxItems": 10,
                        "items": {"type": "string", "maxLength": 80},
                    },
                },
                "required": ["id", "label", "keywords", "exclusions"],
            },
        },
        "preferred_search_terms": {
            "type": "array",
            "description": "Kurze Liste von Keywords/Synonymen für Retrieval (DE/EN erlaubt).",
            "maxItems": 30,
            "items": {"type": "string", "maxLength": 80},
        },
        "hard_exclusions": {
            "type": "array",
            "description": "Was explizit NICHT rein soll (kurz).",
            "maxItems": 30,
            "items": {"type": "string", "maxLength": 100},
        },
        "scope_notes": {
            "type": "string",
            "description": "1–3 kurze Sätze: woran man erkennt, dass ein Treffer wirklich im Scope ist.",
            "maxLength": 280,
        },
    },
    "required": [
        "optimized_description",
        "subpoints",
        "preferred_search_terms",
        "hard_exclusions",
        "must_terms",
        "should_terms",
        "scope_notes",
    ],
}


PREPROCESS_SYSTEM_PROMPT = (
    "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
    "(diese beschreibt genau um was es alles in dem Kapitel später gehen soll).\n"
    "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
    "Regeln:\n"
    "- Schreibe auf Deutsch.\n"
    "- Gib NUR gültiges JSON zurück, exakt passend zum Schema.\n"
    "- optimized_description: 600–1200 Zeichen, nur Scope/Intent des Kapitels, keine Metakommentare.\n"
    "- Extrahiere Unterpunkte (z.B. 2.1, 2.2) NUR wenn sie explizit im Text stehen, sonst subpoints=[].\n"
    "- preferred_search_terms / must_terms / should_terms: DE/EN gemischt erlaubt (PDFs können gemischtsprachig sein).\n"
    "- Füge Synonyme/Keywords hinzu, aber erfinde keine neuen Themen außerhalb des Scopes.\n"
    "- hard_exclusions: kurze Negativbegriffe/Abschnitte (z.B. Referenzen/Anhang), wenn sie Retrieval stören.\n"
    "- scope_notes: 1–3 Sätze, woran man erkennt, dass ein Treffer wirklich im Scope ist.\n"
)


def build_preprocess_user_prompt(*, chapter_title: str, chapter_description: str) -> str:
    return (
        f"Kapitel-Titel: {chapter_title}\n\n"
        f"Rohbeschreibung:\n{normalize_whitespace(chapter_description)}\n"
    )


RESULT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "none_found": {
            "type": "boolean",
            "description": "True nur wenn gar nichts Sinnvolles gefunden wurde (auch keine Fallback-6er).",
        },
        "primary_found": {
            "type": "boolean",
            "description": "True wenn mindestens ein Treffer mit score >= 7 vorhanden ist.",
        },
        "diagnostic": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "reason": {
                    "type": "string",
                    "enum": ["no_evidence", "no_scope_match", "only_weak_evidence", "mixed_or_unclear"],
                },
                "best_score": {"type": "integer", "minimum": 1, "maximum": 10},
                "notes": {"type": "string", "maxLength": 280},
            },
            "required": ["reason", "best_score", "notes"],
        },
        "results": {
            "type": "array",
            "maxItems": 30,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "subpoint": {"type": "string"},
                    "score_1_to_10": {"type": "integer", "minimum": 1, "maximum": 10},
                    "tier": {
                        "type": "string",
                        "enum": ["primary", "fallback"],
                        "description": "primary = score>=7; fallback = score==6 (nur wenn keine primary existieren).",
                    },
                    "subpoint_scores": {
                        "type": "array",
                        "description": "Optional: zusätzliche Scores pro Subpoint (für Multi-Label Relevanz).",
                        "maxItems": 12,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "subpoint": {"type": "string"},
                                "score_1_to_10": {"type": "integer", "minimum": 1, "maximum": 10},
                            },
                            "required": ["subpoint", "score_1_to_10"],
                        },
                    },
                    "anchor": {"type": "string", "description": "8–20 Wörter, exakt aus EVIDENCE."},
                    "anchor_alt": {
                        "type": "string",
                        "description": "Zweites wörtliches Zitat aus EVIDENCE (6–14 Wörter), als Backup.",
                    },
                    "locator_hint": {
                        "type": "string",
                        "description": "Kurzer Hinweis zum Wiederfinden (kein Zitat).",
                        "maxLength": 200,
                    },
                    "coverage": {
                        "type": "string",
                        "description": "Welche Teilaspekte des Kapitels/Subpoints der Treffer gut abdeckt (1 Satz).",
                        "maxLength": 200,
                    },
                    "summary": {"type": "string", "description": "2–4 Sätze, nur basierend auf EVIDENCE."},
                    "score_rationale": {
                        "type": "string",
                        "description": "Sehr kurz: Warum diese Zahl (z.B. direct definition, detailed mechanism, only overview).",
                        "maxLength": 180,
                    },
                },
                "required": [
                    "subpoint",
                    "score_1_to_10",
                    "tier",
                    "subpoint_scores",
                    "anchor",
                    "anchor_alt",
                    "locator_hint",
                    "coverage",
                    "summary",
                    "score_rationale",
                ],
            },
        },
    },
    "required": ["none_found", "primary_found", "diagnostic", "results"],
}


def build_stage2_system_prompt(*, max_hits: int) -> str:
    return "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"


async def _collect_async_paginator(paginator: Any) -> list:
    items: list = []
    try:
        async for item in paginator:
            items.append(item)
    except Exception:
        return []
    return items


async def vector_store_search_items(
    client: Any,
    *,
    vector_store_id: str,
    query: str,
    max_num_results: int,
    rewrite_query: bool = True,
    filters: Any = None,
) -> list:
    try:
        kwargs: dict[str, Any] = {}
        if filters is not None:
            kwargs["filters"] = filters

        paginator = client.vector_stores.search(
            vector_store_id=vector_store_id,
            query=query,
            max_num_results=int(max_num_results),
            rewrite_query=bool(rewrite_query),
            **kwargs,
        )
        return await _collect_async_paginator(paginator)
    except Exception:
        return []


def item_file_id(item: Any) -> Optional[str]:
    fid = getattr(item, "file_id", None)
    if isinstance(fid, str) and fid.strip():
        return fid.strip()
    if isinstance(fid, dict):
        v = fid.get("id") or fid.get("file_id")
        if isinstance(v, str) and v.strip():
            return v.strip()
    if fid is not None and hasattr(fid, "id"):
        v = getattr(fid, "id", None)
        if isinstance(v, str) and v.strip():
            return v.strip()

    f = getattr(item, "file", None)
    if isinstance(f, str) and f.strip():
        return f.strip()
    if isinstance(f, dict):
        v = f.get("id") or f.get("file_id")
        if isinstance(v, str) and v.strip():
            return v.strip()
    if f is not None and hasattr(f, "id"):
        v = getattr(f, "id", None)
        if isinstance(v, str) and v.strip():
            return v.strip()

    md = getattr(item, "metadata", None)
    if isinstance(md, dict):
        v = md.get("file_id") or md.get("file")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def item_score(it: Any) -> float:
    v = getattr(it, "score", None)
    if v is None:
        v = getattr(it, "relevance_score", None)
    try:
        return float(v)
    except Exception:
        return 0.0


def item_text(it: Any) -> str:
    parts = []
    content = getattr(it, "content", None)
    if content:
        for c in content:
            if isinstance(c, dict):
                t = c.get("text")
                if isinstance(t, str) and t.strip():
                    parts.append(t)
            else:
                t = getattr(c, "text", None)
                if isinstance(t, str) and t.strip():
                    parts.append(t)
    text = " ".join(" ".join(parts).split()).strip()
    if not text:
        t = getattr(it, "text", None)
        if isinstance(t, str) and t.strip():
            text = " ".join(t.split()).strip()
    return text


def _stable_key(fid: str, it: Any) -> str:
    cid = getattr(it, "id", None) or getattr(it, "chunk_id", None) or getattr(it, "item_id", None)
    if isinstance(cid, str) and cid.strip():
        return f"{fid}:{cid.strip()}"
    txt = item_text(it)
    h = hashlib.sha1((txt or "").encode("utf-8", errors="ignore")).hexdigest()
    return f"{fid}:h:{h[:12]}"


def dedup_and_sort(items: list) -> list:
    seen = set()
    out = []
    for it in items:
        fid = item_file_id(it) or ""
        key = _stable_key(fid, it)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    out.sort(key=item_score, reverse=True)
    return out


def build_evidence_from_vector_store_search(
    search_page: Any,
    *,
    max_hits: int = 12,
    max_chars_per_hit: int = 1800,
) -> str:
    items = getattr(search_page, "data", None)
    if items is None:
        try:
            items = list(search_page)
        except Exception:
            items = []

    evidence_parts = []
    for i, item in enumerate(list(items)[: max(0, int(max_hits))], start=1):
        score = getattr(item, "score", None)
        if score is None:
            score = getattr(item, "relevance_score", None)

        parts = []
        content = getattr(item, "content", None)
        if content:
            for c in content:
                if isinstance(c, dict):
                    t = c.get("text")
                    if isinstance(t, str) and t.strip():
                        parts.append(t)
                else:
                    t = getattr(c, "text", None)
                    if isinstance(t, str) and t.strip():
                        parts.append(t)

        text = "\n".join(parts).strip()
        if not text:
            t = getattr(item, "text", None)
            if isinstance(t, str) and t.strip():
                text = t.strip()

        text = " ".join(text.split())
        if not text:
            continue

        if len(text) > int(max_chars_per_hit):
            text = text[: max(0, int(max_chars_per_hit))]
            if " " in text:
                text = text.rsplit(" ", 1)[0]
            text = text.strip()

        score_str = f"{float(score):.3f}" if score is not None else "n/a"
        evidence_parts.append(f"[EVIDENCE {i} | score={score_str}]\n{text}")

    return "\n\n".join(evidence_parts)


def postprocess_and_filter(data: Dict[str, Any], evidence: str, *, max_hits: int) -> Dict[str, Any]:
    raw_results = data.get("results") or []
    validated_results = []
    dropped_invalid_shape = 0
    invalid_anchor = 0
    invalid_anchor_alt = 0
    derived_anchor = 0
    derived_anchor_alt = 0

    for r in raw_results:
        if not isinstance(r, dict):
            dropped_invalid_shape += 1
            continue

        try:
            score = int(r.get("score_1_to_10", 0) or 0)
        except Exception:
            score = 0

        # Normalize/defend subpoint_scores (Multi-Label)
        subpoint_scores = []
        raw_sps = r.get("subpoint_scores")
        if isinstance(raw_sps, list):
            for it in raw_sps:
                if not isinstance(it, dict):
                    continue
                sp = (it.get("subpoint") or "").strip()
                try:
                    sc = int(it.get("score_1_to_10", 0) or 0)
                except Exception:
                    sc = 0
                if not sp:
                    continue
                sc = max(1, min(10, sc))
                subpoint_scores.append({"subpoint": sp, "score_1_to_10": int(sc)})

        if not subpoint_scores:
            sp = (r.get("subpoint") or "(Allgemein)").strip() or "(Allgemein)"
            sc = max(1, min(10, int(score or 1)))
            subpoint_scores = [{"subpoint": sp, "score_1_to_10": int(sc)}]

        # De-dup by subpoint (keep max score)
        sps_by_sp = {}
        for it in subpoint_scores:
            sp = (it.get("subpoint") or "").strip()
            sc = int(it.get("score_1_to_10", 0) or 0)
            if not sp:
                continue
            if sp not in sps_by_sp or sc > int(sps_by_sp[sp].get("score_1_to_10", 0) or 0):
                sps_by_sp[sp] = {"subpoint": sp, "score_1_to_10": int(sc)}
        subpoint_scores = list(sps_by_sp.values())

        a = validate_anchor(r.get("anchor"), evidence, min_words=8, max_words=20)
        aa = validate_anchor(r.get("anchor_alt"), evidence, min_words=6, max_words=14)

        if bool(a.get("ok")) and not bool(aa.get("ok")):
            derived = derive_anchor_alt_from_span(evidence, a.get("span"))
            if derived:
                aa = {"text": derived, "ok": True, "reason": "derived_from_anchor", "span": None}
                derived_anchor_alt += 1

        if bool(aa.get("ok")) and not bool(a.get("ok")):
            exp = expand_span(evidence, aa.get("span"))
            if exp:
                start, n = exp
                ev_words = normalize_spaces(evidence).split(" ")
                a = {
                    "text": " ".join(ev_words[start : start + n]),
                    "ok": True,
                    "reason": "derived_from_anchor_alt",
                    "span": exp,
                }
                derived_anchor += 1

        if not bool(a.get("ok")):
            invalid_anchor += 1
        if not bool(aa.get("ok")):
            invalid_anchor_alt += 1

        rr = dict(r)
        rr["score_1_to_10"] = int(score)
        rr["tier"] = "primary" if int(score) >= 7 else ("fallback" if int(score) == 6 else str(r.get("tier") or ""))
        rr["subpoint_scores"] = subpoint_scores
        rr["anchor"] = str(a.get("text") or "")
        rr["anchor_alt"] = str(aa.get("text") or "")
        rr["_anchor_ok"] = bool(a.get("ok"))
        rr["_anchor_reason"] = str(a.get("reason") or "")
        rr["_anchor_alt_ok"] = bool(aa.get("ok"))
        rr["_anchor_alt_reason"] = str(aa.get("reason") or "")
        validated_results.append(rr)

    prim = [r for r in validated_results if int(r.get("score_1_to_10", 0) or 0) >= 7]
    fallback = [r for r in validated_results if int(r.get("score_1_to_10", 0) or 0) == 6]

    # Keep BOTH tiers (Stage 3 will curate globally). Still cap at MAX_HITS.
    prim_sorted = sorted(
        prim,
        key=lambda r: (
            int(r.get("score_1_to_10", 0) or 0),
            1 if (r.get("_anchor_ok") and r.get("_anchor_alt_ok")) else 0,
            1 if (r.get("_anchor_ok") or r.get("_anchor_alt_ok")) else 0,
        ),
        reverse=True,
    )
    fallback_sorted = sorted(
        fallback,
        key=lambda r: (
            int(r.get("score_1_to_10", 0) or 0),
            1 if (r.get("_anchor_ok") and r.get("_anchor_alt_ok")) else 0,
            1 if (r.get("_anchor_ok") or r.get("_anchor_alt_ok")) else 0,
        ),
        reverse=True,
    )

    keep = []
    if prim_sorted:
        keep.extend(prim_sorted[: int(max_hits)])
        remaining = max(0, int(max_hits) - len(keep))
        if remaining:
            keep.extend(fallback_sorted[: int(remaining)])
    else:
        keep.extend(fallback_sorted[: int(max_hits)])

    keep = sorted(
        keep,
        key=lambda r: (
            int(r.get("score_1_to_10", 0) or 0),
            1 if (r.get("_anchor_ok") and r.get("_anchor_alt_ok")) else 0,
            1 if (r.get("_anchor_ok") or r.get("_anchor_alt_ok")) else 0,
        ),
        reverse=True,
    )[: int(max_hits)]

    primary_found = bool(prim)
    none_found = not keep

    best_score = 1
    if keep:
        try:
            best_score = max(1, min(10, int(keep[0].get("score_1_to_10", 1) or 1)))
        except Exception:
            best_score = 1

    if not evidence.strip():
        reason = "no_evidence"
    elif primary_found:
        reason = "mixed_or_unclear"
    elif keep:
        reason = "only_weak_evidence"
    else:
        reason = "no_scope_match"

    notes = (
        f"raw={len(raw_results)}, kept={len(keep)}, primary={len(prim)}, fallback={len(fallback)}; "
        f"invalid_anchor={invalid_anchor}, invalid_anchor_alt={invalid_anchor_alt}; "
        f"derived_anchor={derived_anchor}, derived_anchor_alt={derived_anchor_alt}"
    )
    if dropped_invalid_shape:
        notes += f"; dropped_invalid_shape={dropped_invalid_shape}"

    keep_clean = [{k: v for k, v in r.items() if not str(k).startswith("_")} for r in keep]
    clean_data = dict(data)
    clean_data["results"] = keep_clean
    clean_data["primary_found"] = bool(primary_found)
    clean_data["none_found"] = bool(none_found)
    clean_data["diagnostic"] = {"reason": reason, "best_score": int(best_score), "notes": (notes or "")[:280]}

    stats = {
        "dropped_invalid_shape": dropped_invalid_shape,
        "invalid_anchor": invalid_anchor,
        "invalid_anchor_alt": invalid_anchor_alt,
        "derived_anchor": derived_anchor,
        "derived_anchor_alt": derived_anchor_alt,
    }
    return {"clean_data": clean_data, "keep_debug": keep, "stats": stats}


def normalize_subpoint_id(sp: Any) -> str:
    s = (sp if isinstance(sp, str) else str(sp or "")).strip()
    if not s:
        return "(Allgemein)"
    low = s.lower()
    if "allgemein" in low or low in {"general", "misc", "miscellaneous"}:
        return "(Allgemein)"
    if s.startswith("(") and s.endswith(")"):
        inner = s[1:-1].strip()
        if inner:
            s = inner
    return s


def curate_pdf_sections(
    *,
    pdf_results: list[dict],
    subpoints: list[dict],
    subpoint_importance: dict[str, float] | None,
    soft_total_sections_target: int | None,
    hard_max_selected_sections: int,
) -> Optional[dict]:
    """
    Stage 3 (Curation) ported from pdf-scan-test.ipynb.
    Returns a CURATED dict or None if curation is disabled.
    """

    try:
        import fitz  # type: ignore
    except Exception as e:
        fitz = None
        logger.warning("fitz import failed; PDF heading lookup disabled: %s", e)

    def _hash10(s: str) -> str:
        return hashlib.sha1((s or "").encode("utf-8", errors="ignore")).hexdigest()[:10]

    def _pdf_norm_ws(s: str) -> str:
        return normalize_spaces(s)

    def _pdf_norm_token(w: str) -> str:
        return norm_word(w)

    @dataclass
    class AnchorLoc:
        page: int  # 1-based
        y0: float
        x0: float

    @dataclass
    class PdfHeading:
        text: str
        page: int  # 1-based
        y0: float
        level: int
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

    METADATA_BADWORDS = {"issn", "doi", "volume", "issue", "pages", "website", "journal", "http", "https", "www."}

    def _looks_like_metadata(line: str) -> bool:
        s = (line or "").lower()
        if any(w in s for w in METADATA_BADWORDS):
            return True
        if "||" in s and ("volume" in s or "issue" in s or "pages" in s):
            return True
        return False

    def _estimate_body_font_size(pdf_path: str, max_pages: int = 12) -> float:
        if not fitz:
            return 12.0
        doc = fitz.open(pdf_path)
        size_weight = {}
        n_pages = min(len(doc), int(max_pages))
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
                        size_weight[sz] = int(size_weight.get(sz, 0)) + int(len(txt))
        if not size_weight:
            return 12.0
        return float(max(size_weight.items(), key=lambda kv: kv[1])[0])

    def _is_heading_candidate(text: str, avg_size: float, body_size: float, font_names: list) -> bool:
        t = _pdf_norm_ws(text)
        if not t:
            return False
        low = t.lower()
        if _looks_like_metadata(t):
            return False
        if len(t) > 140:
            return False
        if re.match(r"^(\\d+(\\.\\d+)*)\\s+\\S+", t):
            return True
        if low in HEADING_KEYWORDS:
            return True
        if len(t.split()) <= 4 and any(k == low for k in HEADING_KEYWORDS):
            return True
        is_boldish = any("bold" in (fn or "").lower() for fn in (font_names or []))
        if float(avg_size) >= float(body_size) + 1.6:
            return True
        if is_boldish and float(avg_size) >= float(body_size) + 0.8 and len(t.split()) <= 14:
            return True
        return False

    def _merge_multiline_headings(headings: list, y_gap: float = 3.5) -> list:
        if not headings:
            return headings
        merged = []
        cur = headings[0]
        for h in headings[1:]:
            same_page = h.page == cur.page
            close_y = same_page and abs(h.y0 - cur.y0) <= 50
            similar_size = abs(h.font_size - cur.font_size) <= 0.4
            same_level = h.level == cur.level
            if same_page and close_y and similar_size and same_level:
                cur = PdfHeading(
                    text=_pdf_norm_ws(cur.text + " " + h.text),
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

        out = []
        seen = set()
        for h in merged:
            key = (h.page, h.level, _pdf_norm_ws(h.text).lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(h)
        return out

    def _build_heading_index_strict(pdf_path: str, max_levels: int = 4) -> list:
        if not fitz:
            return []
        doc = fitz.open(pdf_path)
        body_size = _estimate_body_font_size(pdf_path)

        candidates = []
        for pno in range(len(doc)):
            page = doc.load_page(pno)
            d = page.get_text("dict")
            for b in d.get("blocks", []):
                if b.get("type") != 0:
                    continue
                for line in b.get("lines", []):
                    spans = line.get("spans", [])
                    if not spans:
                        continue
                    txt = "".join([s.get("text", "") for s in spans]).strip()
                    if not txt:
                        continue
                    szs = [float(s.get("size", 0.0) or 0.0) for s in spans if s.get("size")]
                    if not szs:
                        continue
                    avg_size = float(sum(szs) / float(len(szs)))
                    fns = [str(s.get("font", "") or "") for s in spans]
                    is_num = bool(re.match(r"^(\\d+(\\.\\d+)*)\\s+", txt))
                    if _is_heading_candidate(txt, avg_size, body_size, fns):
                        y0 = float(line.get("bbox", [0, 0, 0, 0])[1] or 0.0)
                        candidates.append((_pdf_norm_ws(txt), int(pno + 1), float(y0), float(avg_size), bool(is_num)))

        if not candidates:
            return []

        sizes = sorted({round(c[3], 1) for c in candidates}, reverse=True)
        size_levels = sizes[: int(max_levels)]

        def level_for(sz: float, text: str) -> int:
            m = re.match(r"^(\\d+(\\.\\d+)*)\\s+", text)
            if m:
                depth = m.group(1).count(".") + 1
                return max(1, min(4, int(depth)))
            s = round(float(sz), 1)
            nearest = min(size_levels, key=lambda x: abs(x - s))
            return int(size_levels.index(nearest) + 1)

        headings = [
            PdfHeading(
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
        return _merge_multiline_headings(headings)

    def _find_heading_before(headings: list, page: int, y0: float) -> Optional[int]:
        best = None
        for i, h in enumerate(headings):
            if (h.page < int(page)) or (h.page == int(page) and float(h.y0) <= float(y0)):
                best = i
            else:
                break
        return best

    DOC_CACHE: dict[str, Any] = {}
    TOC_CACHE: dict[str, list] = {}
    STRICT_HEADINGS_CACHE: dict[str, list] = {}
    ANCHOR_LOC_CACHE: dict[tuple[str, str], Optional[AnchorLoc]] = {}

    def _get_doc(pdf_path: str):
        if not fitz:
            return None
        d = DOC_CACHE.get(pdf_path)
        if d is None:
            d = fitz.open(pdf_path)
            DOC_CACHE[pdf_path] = d
        return d

    def _get_toc(pdf_path: str) -> list:
        toc = TOC_CACHE.get(pdf_path)
        if toc is not None:
            return toc
        doc = _get_doc(pdf_path)
        if not doc:
            toc = []
        else:
            try:
                toc = doc.get_toc(simple=True) or []
            except Exception:
                toc = []
        TOC_CACHE[pdf_path] = toc
        return toc

    def _get_strict_headings(pdf_path: str) -> list:
        hs = STRICT_HEADINGS_CACHE.get(pdf_path)
        if hs is not None:
            return hs
        try:
            hs = _build_heading_index_strict(pdf_path)
        except Exception:
            hs = []
        STRICT_HEADINGS_CACHE[pdf_path] = hs
        return hs

    def _find_anchor_loc_in_doc(doc: Any, anchor: str) -> Optional[AnchorLoc]:
        if not doc:
            return None
        anchor = _pdf_norm_ws(anchor)
        if not anchor:
            return None

        cache_key = (getattr(doc, "name", None) or "", anchor)
        cached = ANCHOR_LOC_CACHE.get(cache_key)
        if cached is not None:
            return cached

        # Fast: page.search_for (exact string match)
        for pno in range(len(doc)):
            page = doc.load_page(pno)
            try:
                rects = page.search_for(anchor)
            except Exception:
                rects = []
            if rects:
                r = rects[0]
                loc = AnchorLoc(page=int(pno + 1), y0=float(r.y0), x0=float(r.x0))
                ANCHOR_LOC_CACHE[cache_key] = loc
                return loc

        # Fallback: word-based match (survives line breaks)
        anchor_tokens = [_pdf_norm_token(t) for t in anchor.split()]
        anchor_tokens = [t for t in anchor_tokens if t]
        if len(anchor_tokens) < 3:
            ANCHOR_LOC_CACHE[cache_key] = None
            return None

        n = len(anchor_tokens)
        for pno in range(len(doc)):
            page = doc.load_page(pno)
            words = page.get_text("words") or []
            words.sort(key=lambda w: (w[5], w[6], w[7], w[1], w[0]))
            page_tokens = [_pdf_norm_token(w[4]) for w in words]
            if len(page_tokens) < n:
                continue
            for i in range(0, len(page_tokens) - n + 1):
                if page_tokens[i : i + n] == anchor_tokens:
                    xs0 = min(words[j][0] for j in range(i, i + n))
                    ys0 = min(words[j][1] for j in range(i, i + n))
                    loc = AnchorLoc(page=int(pno + 1), y0=float(ys0), x0=float(xs0))
                    ANCHOR_LOC_CACHE[cache_key] = loc
                    return loc

        ANCHOR_LOC_CACHE[cache_key] = None
        return None

    def resolve_pdf_section(pdf_path: str, anchor: str, anchor_alt: str) -> Dict[str, Any]:
        out = {"ok": False, "method": None, "section_title": None, "section_index": None, "anchor_page": None}
        if not pdf_path or not Path(pdf_path).exists() or not fitz:
            return out
        doc = _get_doc(pdf_path)
        if not doc:
            return out

        loc = _find_anchor_loc_in_doc(doc, anchor) or _find_anchor_loc_in_doc(doc, anchor_alt)
        if not loc:
            out["ok"] = False
            out["method"] = "anchor_not_found"
            return out
        out["anchor_page"] = int(loc.page)

        toc = _get_toc(pdf_path)
        if toc:
            best = None
            for i, entry in enumerate(toc):
                try:
                    _lvl, _title, pg = entry
                except Exception:
                    continue
                try:
                    pg_i = int(pg)
                except Exception:
                    continue
                if pg_i <= int(loc.page):
                    best = i
                else:
                    break
            if best is not None:
                out.update({"ok": True, "method": "toc", "section_title": str(toc[best][1]), "section_index": int(best)})
                return out

        headings = _get_strict_headings(pdf_path)
        if headings:
            idx = _find_heading_before(headings, loc.page, loc.y0)
            if idx is not None:
                h = headings[int(idx)]
                out.update({"ok": True, "method": "strict", "section_title": str(h.text), "section_index": int(idx)})
                return out

        out.update({"ok": True, "method": "page_only", "section_title": None, "section_index": None})
        return out

    # --- Build section candidates (unique by PDF section) ---
    subpoint_ids = []
    subpoint_label: dict[str, str] = {}
    if subpoints:
        for sp in subpoints:
            sid = normalize_subpoint_id((sp.get("id") if isinstance(sp, dict) else None) or "")
            if not sid or sid == "(Allgemein)":
                continue
            if sid not in subpoint_label:
                subpoint_ids.append(sid)
                subpoint_label[sid] = ((sp.get("label") if isinstance(sp, dict) else None) or "").strip()
    if not subpoint_ids:
        subpoint_ids = ["(Allgemein)"]
        subpoint_label["(Allgemein)"] = "(Allgemein)"

    importance = {sid: float((subpoint_importance or {}).get(sid, 1) or 1) for sid in subpoint_ids}

    all_hits = []
    for pdf in pdf_results:
        for r in (pdf.get("keep_debug") or []):
            h = dict(r)
            h["pdf_label"] = pdf.get("label")
            h["pdf_file_id"] = pdf.get("file_id")
            h["pdf_path"] = pdf.get("path") or ""
            all_hits.append(h)

    sections: dict[str, dict] = {}
    for h in all_hits:
        pdf_path = (h.get("pdf_path") or "").strip()
        file_id = (h.get("pdf_file_id") or "").strip()
        if not file_id:
            continue
        anchor = str(h.get("anchor") or "")
        anchor_alt = str(h.get("anchor_alt") or "")

        sec_info = resolve_pdf_section(pdf_path, anchor, anchor_alt)
        sec_idx = sec_info.get("section_index")
        sec_method = sec_info.get("method") or "none"
        sec_title = sec_info.get("section_title")
        anchor_page = sec_info.get("anchor_page")

        if sec_idx is not None:
            section_key = f"{file_id}::sec::{sec_method}::{int(sec_idx)}"
        else:
            section_key = f"{file_id}::anchor::{_hash10(anchor or anchor_alt)}"

        sec = sections.get(section_key)
        if sec is None:
            sec = {
                "section_key": section_key,
                "pdf_label": h.get("pdf_label"),
                "pdf_file_id": file_id,
                "pdf_path": pdf_path,
                "pdf_heading": sec_title,
                "pdf_heading_method": sec_method,
                "anchor_page": anchor_page,
                "hit_count": 0,
                "subpoint_scores": {},
                "best_hit_by_subpoint": {},
                "best_hit": None,
            }
            sections[section_key] = sec

        sec["hit_count"] = int(sec.get("hit_count", 0) or 0) + 1

        rep = sec.get("best_hit")
        if rep is None:
            sec["best_hit"] = h
        else:
            try:
                cur = int(h.get("score_1_to_10", 0) or 0)
                prev = int(rep.get("score_1_to_10", 0) or 0)
            except Exception:
                cur, prev = 0, 0
            if (cur, int(bool(h.get("_anchor_ok"))), int(bool(h.get("_anchor_alt_ok")))) > (
                prev,
                int(bool(rep.get("_anchor_ok"))),
                int(bool(rep.get("_anchor_alt_ok"))),
            ):
                sec["best_hit"] = h

        sps = h.get("subpoint_scores") or []
        if not isinstance(sps, list) or not sps:
            sps = [{"subpoint": h.get("subpoint") or "(Allgemein)", "score_1_to_10": h.get("score_1_to_10", 0)}]

        for it in sps:
            if not isinstance(it, dict):
                continue
            spid = normalize_subpoint_id(it.get("subpoint") or "(Allgemein)")
            try:
                sc = int(it.get("score_1_to_10", 0) or 0)
            except Exception:
                sc = 0
            if sc <= 0:
                continue
            prev_sc = int(sec["subpoint_scores"].get(spid, 0) or 0)
            if sc > prev_sc:
                sec["subpoint_scores"][spid] = int(sc)
                sec["best_hit_by_subpoint"][spid] = h

    section_list = list(sections.values())

    # Determine per-subpoint thresholds (primary>=7, else allow fallback==6)
    has_primary_any = {}
    for spid in subpoint_ids:
        has_primary_any[spid] = any(
            int(sec.get("subpoint_scores", {}).get(spid, 0) or 0) >= 7 for sec in section_list
        )
    threshold_by_subpoint = {spid: (7 if has_primary_any.get(spid) else 6) for spid in subpoint_ids}

    import math

    def _auto_per_subpoint_target(n: int) -> float:
        n = int(max(1, n))
        if n <= 1:
            return 5.0
        if n <= 2:
            return 4.0
        if n >= 6:
            return 2.0
        return 4.0 - 0.5 * float(n - 2)

    n_sp = int(len(subpoint_ids))
    per_sp_target = float(_auto_per_subpoint_target(n_sp))
    auto_soft_total_target = int(round(per_sp_target * float(n_sp)))
    soft_total_cfg = soft_total_sections_target
    if soft_total_cfg is None:
        soft_total_cfg = auto_soft_total_target
    soft_total = max(0, min(int(soft_total_cfg), len(section_list)))

    base_max_per_subpoint = int(math.ceil(per_sp_target + 2.0))

    available_section_counts: dict[str, int] = {}
    eligible_subpoints = []
    for spid in subpoint_ids:
        th = int(threshold_by_subpoint.get(spid, 7))
        c = sum(1 for sec in section_list if int(sec.get("subpoint_scores", {}).get(spid, 0) or 0) >= th)
        available_section_counts[spid] = int(c)
        if c > 0:
            eligible_subpoints.append(spid)

    desired_by_subpoint = {spid: 0 for spid in subpoint_ids}
    max_by_subpoint: dict[str, int] = {}
    for spid in subpoint_ids:
        imp = float(importance.get(spid, 1.0) or 1.0)
        bump = max(0, int(round(imp - 1.0)))
        max_by_subpoint[spid] = int(min(int(hard_max_selected_sections), max(1, base_max_per_subpoint + bump)))

    budget = int(soft_total)
    if budget > 0 and eligible_subpoints:
        for spid in sorted(
            eligible_subpoints, key=lambda s: (float(importance.get(s, 1.0) or 1.0), s), reverse=True
        ):
            if budget <= 0:
                break
            if desired_by_subpoint[spid] < int(max_by_subpoint.get(spid, 1)):
                desired_by_subpoint[spid] += 1
                budget -= 1

        while budget > 0:
            candidates = [s for s in eligible_subpoints if desired_by_subpoint[s] < int(max_by_subpoint.get(s, 1))]
            if not candidates:
                break
            spid = max(
                candidates,
                key=lambda s: (
                    float(importance.get(s, 1.0) or 1.0) / (float(desired_by_subpoint[s]) + 1.0),
                    float(importance.get(s, 1.0) or 1.0),
                    -int(desired_by_subpoint[s]),
                ),
            )
            desired_by_subpoint[spid] += 1
            budget -= 1

    display_limit_by_subpoint = {}
    for spid in subpoint_ids:
        desired = int(desired_by_subpoint.get(spid, 0) or 0)
        if int(available_section_counts.get(spid, 0) or 0) > 0:
            display_limit_by_subpoint[spid] = max(1, desired)
        else:
            display_limit_by_subpoint[spid] = 0

    picked_counts = {spid: 0 for spid in subpoint_ids}
    selected = []
    selected_keys = set()

    def _score_factor(sc: int) -> float:
        sc = int(sc or 0)
        if sc <= 5:
            return 0.0
        return max(0.0, min(1.0, (float(sc) - 5.0) / 5.0))

    def _section_gain(sec: Dict[str, Any]) -> float:
        gain = 0.0
        sp_scores = sec.get("subpoint_scores") or {}
        for spid in subpoint_ids:
            sc = int(sp_scores.get(spid, 0) or 0)
            if sc < int(threshold_by_subpoint.get(spid, 7)):
                continue
            w = float(importance.get(spid, 1.0) or 1.0)
            sf = _score_factor(sc)
            desired = int(desired_by_subpoint.get(spid, 0) or 0)
            if picked_counts.get(spid, 0) < int(desired):
                nf = 1.0
            else:
                nf = 0.25
            gain += w * sf * nf
        return float(gain)

    while len(selected) < int(hard_max_selected_sections) and int(soft_total) > 0:
        best = None
        best_gain = 0.0
        for sec in section_list:
            key = sec.get("section_key")
            if key in selected_keys:
                continue
            g = _section_gain(sec)
            if g > best_gain:
                best_gain = g
                best = sec

        if best is None:
            break
        if len(selected) >= int(soft_total) and float(best_gain) < 0.25:
            break
        if float(best_gain) <= 0.0:
            break

        selected.append(best)
        selected_keys.add(best.get("section_key"))
        for spid in subpoint_ids:
            sc = int(best.get("subpoint_scores", {}).get(spid, 0) or 0)
            if sc >= int(threshold_by_subpoint.get(spid, 7)):
                picked_counts[spid] = int(picked_counts.get(spid, 0) or 0) + 1

    curated_by_subpoint = {}
    for spid in subpoint_ids:
        hits = []
        for sec in selected:
            sc = int(sec.get("subpoint_scores", {}).get(spid, 0) or 0)
            if sc < int(threshold_by_subpoint.get(spid, 7)):
                continue
            h = sec.get("best_hit_by_subpoint", {}).get(spid) or sec.get("best_hit") or {}
            tier = "primary" if sc >= 7 else "fallback"
            hits.append(
                {
                    "pdf_label": sec.get("pdf_label"),
                    "pdf_file_id": sec.get("pdf_file_id"),
                    "pdf_path": sec.get("pdf_path"),
                    "pdf_heading": sec.get("pdf_heading"),
                    "pdf_heading_method": sec.get("pdf_heading_method"),
                    "anchor_page": sec.get("anchor_page"),
                    "subpoint": spid,
                    "score_1_to_10": int(sc),
                    "tier": tier,
                    "anchor": h.get("anchor"),
                    "anchor_alt": h.get("anchor_alt"),
                    "summary": h.get("summary"),
                    "coverage": h.get("coverage"),
                    "locator_hint": h.get("locator_hint"),
                }
            )
        hits = sorted(hits, key=lambda r: int(r.get("score_1_to_10", 0) or 0), reverse=True)[
            : int(display_limit_by_subpoint.get(spid, 0) or 0)
        ]
        curated_by_subpoint[spid] = hits

    missing_subpoints = [spid for spid in subpoint_ids if int(available_section_counts.get(spid, 0) or 0) == 0]
    uncovered_subpoints = [
        spid
        for spid in subpoint_ids
        if int(available_section_counts.get(spid, 0) or 0) > 0 and int(picked_counts.get(spid, 0) or 0) == 0
    ]

    selected_sections = []
    for sec in selected:
        rep = sec.get("best_hit") or {}
        covers = []
        for spid in subpoint_ids:
            sc = int(sec.get("subpoint_scores", {}).get(spid, 0) or 0)
            if sc >= int(threshold_by_subpoint.get(spid, 7)):
                covers.append(
                    {"subpoint": spid, "score_1_to_10": int(sc), "tier": ("primary" if sc >= 7 else "fallback")}
                )
        covers = sorted(covers, key=lambda x: int(x.get("score_1_to_10", 0) or 0), reverse=True)
        selected_sections.append(
            {
                "pdf_label": sec.get("pdf_label"),
                "pdf_file_id": sec.get("pdf_file_id"),
                "pdf_path": sec.get("pdf_path"),
                "pdf_heading": sec.get("pdf_heading"),
                "pdf_heading_method": sec.get("pdf_heading_method"),
                "anchor_page": sec.get("anchor_page"),
                "hit_count": int(sec.get("hit_count", 0) or 0),
                "representative_anchor": rep.get("anchor"),
                "representative_anchor_alt": rep.get("anchor_alt"),
                "representative_summary": rep.get("summary"),
                "covers": covers,
            }
        )

    curated = {
        "soft_total_target": int(soft_total),
        "soft_total_cfg": (None if soft_total_sections_target is None else int(soft_total_sections_target)),
        "soft_total_auto": int(auto_soft_total_target),
        "per_subpoint_target_auto": float(per_sp_target),
        "base_max_per_subpoint_auto": int(base_max_per_subpoint),
        "desired_by_subpoint": desired_by_subpoint,
        "display_limit_by_subpoint": display_limit_by_subpoint,
        "available_section_counts": available_section_counts,
        "threshold_by_subpoint": threshold_by_subpoint,
        "picked_counts": picked_counts,
        "missing_subpoints": missing_subpoints,
        "uncovered_subpoints": uncovered_subpoints,
        "selected_sections": selected_sections,
        "by_subpoint": curated_by_subpoint,
    }

    try:
        for _p, _d in list(DOC_CACHE.items()):
            try:
                if _d:
                    _d.close()
            except Exception:
                pass
        DOC_CACHE.clear()
    except Exception:
        pass

    return curated
