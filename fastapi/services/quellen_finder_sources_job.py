from __future__ import annotations

import json
import logging
import math
import traceback
from typing import Any, Iterable, Optional

import pandas as pd
from fastapi import HTTPException
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.quellen_finder_firestore_service import QuellenFinderFirestoreService
from services.quellen_finder_sources_service import QuellenFinderSourcesService

logger = logging.getLogger(__name__)


def _is_nan(value: Any) -> bool:
    try:
        return value is None or (isinstance(value, float) and math.isnan(value))
    except Exception:
        return False


def _as_int_or_none(value: Any) -> int | None:
    if _is_nan(value):
        return None
    try:
        n = int(value)
    except Exception:
        try:
            n = int(float(value))
        except Exception:
            return None
    return n


def _as_float_or_none(value: Any) -> float | None:
    if _is_nan(value):
        return None
    try:
        n = float(value)
    except Exception:
        return None
    if not math.isfinite(n):
        return None
    return float(n)


def _as_str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if _is_nan(value):
        return None
    try:
        s = str(value).strip()
    except Exception:
        return None
    return s or None


def _split_authors(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for a in value:
            s = _as_str_or_none(a)
            if s:
                out.append(s)
        return out
    s = _as_str_or_none(value) or ""
    if not s:
        return []
    parts = [p.strip() for p in s.split(";")]
    return [p for p in parts if p]


def _normalize_doi(value: Any) -> str | None:
    s = _as_str_or_none(value)
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    low = s.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if low.startswith(prefix):
            s = s[len(prefix) :].strip()
            low = s.lower()
    return s or None


def _choose_url(row: dict) -> str | None:
    for k in ("s2_url", "openalex_id", "url"):
        s = _as_str_or_none(row.get(k))
        if s:
            return s
    doi = _normalize_doi(row.get("doi_norm") or row.get("doi"))
    if doi:
        return f"https://doi.org/{doi}"
    return None


def _trim_raw(raw: dict, *, max_chars: int = 20_000) -> dict:
    """
    Firestore documents have a 1 MiB limit. Keep raw JSON helpful but bounded.
    """
    out: dict[str, Any] = {}
    for k, v in (raw or {}).items():
        if isinstance(v, str) and len(v) > max_chars:
            out[k] = v[: max_chars - 20] + "…(trimmed)"
        else:
            out[k] = v
    return out


def _row_to_jsonable(row: dict) -> dict:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, (pd.Timestamp,)):
            out[k] = v.isoformat()
            continue
        if hasattr(v, "item"):
            try:
                v = v.item()
            except Exception:
                pass
        if isinstance(v, float) and math.isnan(v):
            out[k] = None
        elif isinstance(v, (list, dict, str, int, bool)) or v is None:
            out[k] = v
        else:
            out[k] = _as_str_or_none(v)
    return out


def _sources_df_to_docs(df: pd.DataFrame, *, final_score_col: str) -> Iterable[tuple[str, dict]]:
    rows = df.to_dict(orient="records") if isinstance(df, pd.DataFrame) else []
    for idx, row in enumerate(rows):
        row_norm = _row_to_jsonable(row if isinstance(row, dict) else {})
        score = _as_float_or_none(row_norm.get(final_score_col))
        citation_count = _as_int_or_none(row_norm.get("citation_count_max") or row_norm.get("citation_count"))

        doi_norm = _normalize_doi(row_norm.get("doi_norm") or row_norm.get("doi"))
        payload = {
            "title": _as_str_or_none(row_norm.get("title")),
            "authors": _split_authors(row_norm.get("authors(first6)") or row_norm.get("authors")),
            "year": _as_int_or_none(row_norm.get("year")),
            "venue": _as_str_or_none(row_norm.get("venue")),
            "doi": doi_norm,
            "url": _choose_url(row_norm),
            "abstract": _as_str_or_none(row_norm.get("abstract")),
            "citationCount": citation_count,
            "source": _as_str_or_none(row_norm.get("source")) or "unknown",
            "score": score,
            "rank": int(idx + 1),
            "raw": _trim_raw(row_norm),
            "createdAt": SERVER_TIMESTAMP,
        }
        doc_id = f"{idx + 1:02d}"
        yield doc_id, payload


async def run_quellen_finder_sources_search_job(
    *,
    user_id: str,
    projekt_id: str,
    kapitel_id: str,
    run_id: str,
    blueprint_model: str,
) -> None:
    fs = QuellenFinderFirestoreService()
    svc = QuellenFinderSourcesService()

    had_partial_failures = False

    try:
        fs.mark_running(user_id=user_id, projekt_id=projekt_id, run_id=run_id)

        fs.set_progress(
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            stage="stageB_blueprint",
            message="Generating chapter blueprint (Stage B)",
        )

        fs.set_progress(
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            stage="stageA_fetch",
            message="Fetching sources from OpenAlex + Semantic Scholar (Stage A)",
        )

        df, meta = await svc.run_sources_search(
            user_id=user_id,
            projekt_id=projekt_id,
            kapitel_id=kapitel_id,
            research_run_id=run_id,
            blueprint_model=blueprint_model,
        )

        final_score_col = str((meta or {}).get("final_score_col") or "score_stageD_final")

        fs.set_progress(
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            stage="write_results",
            message="Saving results to database",
        )

        fs.clear_subcollection(user_id=user_id, projekt_id=projekt_id, run_id=run_id, name="sourcesResults")

        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            fs.mark_success(
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                had_partial_failures=had_partial_failures,
                extra={"resultCount": 0},
            )
            return

        docs = list(_sources_df_to_docs(df, final_score_col=final_score_col))
        fs.write_sources_results(user_id=user_id, projekt_id=projekt_id, run_id=run_id, docs=docs)

        fs.mark_success(
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            had_partial_failures=had_partial_failures,
            extra={"resultCount": int(len(docs)), "finalScoreCol": final_score_col},
        )
    except HTTPException as exc:
        detail = getattr(exc, "detail", None)
        msg = str(detail or exc)[:1000]
        fs.mark_error(
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            error_message=msg,
            had_partial_failures=had_partial_failures,
        )
    except Exception as exc:
        logger.error("Quellen-Finder sources search failed (run_id=%s): %s", run_id, exc)
        logger.debug("Traceback:\n%s", traceback.format_exc())
        fs.mark_error(
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            error_message=str(exc),
            had_partial_failures=had_partial_failures,
        )

