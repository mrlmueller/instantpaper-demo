from __future__ import annotations

import asyncio
import logging
import time
import traceback
from typing import Any, Dict, Iterable, List, Tuple

from fastapi import HTTPException
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.quellen_finder_firestore_service import QuellenFinderFirestoreService
from services.two_lane_sources.runner import TwoLaneRunCancelled, run_two_lane_sources_pipeline

logger = logging.getLogger(__name__)


def _as_str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    try:
        s = str(value).strip()
    except Exception:
        return None
    return s or None


def _as_int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _trim_text(value: Any, *, max_chars: int = 5000) -> str | None:
    s = _as_str_or_none(value)
    if not s:
        return None
    if len(s) <= int(max_chars):
        return s
    return s[: max(0, int(max_chars) - 1)].rstrip() + "…"


def _build_two_lane_results_docs(*, output: Dict[str, Any]) -> List[Tuple[str, dict]]:
    top = output.get("top") or {}

    docs: List[Tuple[str, dict]] = []
    for lane in ["match", "authority"]:
        for pool in ["with_abstract", "without_abstract"]:
            cards = list(((top.get(lane) or {}).get(pool) or []))
            for rank, card in enumerate(cards[:40], start=1):
                cid = _as_str_or_none(card.get("id")) or ""

                rerank = card.get("rerank")
                if not isinstance(rerank, dict):
                    rerank = None
                else:
                    rerank = {
                        "llm_score_0_100": _as_int_or_none(rerank.get("llm_score_0_100")),
                        "covered_facets": list(rerank.get("covered_facets") or []),
                        "rationale": _trim_text(rerank.get("rationale"), max_chars=5000),
                        "insufficient_info": bool(rerank.get("insufficient_info")) if rerank.get("insufficient_info") is not None else None,
                    }

                coverage_tags_in = card.get("coverage_tags")
                coverage_tags = None
                if isinstance(coverage_tags_in, list):
                    ct = []
                    for t in coverage_tags_in:
                        if not isinstance(t, dict):
                            continue
                        fid = _as_str_or_none(t.get("facet_id"))
                        if not fid:
                            continue
                        ct.append(
                            {
                                "facet_id": fid,
                                "score": float(t.get("score") or 0.0),
                                "excerpt": _trim_text(t.get("excerpt"), max_chars=240) or "",
                            }
                        )
                    coverage_tags = ct

                authors_in = card.get("authors")
                authors: List[str] = []
                if isinstance(authors_in, list):
                    for a in authors_in:
                        s = _as_str_or_none(a)
                        if s:
                            authors.append(s)

                scores = card.get("scores") if isinstance(card.get("scores"), dict) else {}

                payload = {
                    "lane": lane,
                    "pool": pool,
                    "rank": int(rank),
                    "id": cid,
                    "doi": _as_str_or_none(card.get("doi")),
                    "title": _as_str_or_none(card.get("title")),
                    "authors": authors,
                    "year": _as_int_or_none(card.get("year")),
                    "venue": _as_str_or_none(card.get("venue")),
                    "url": _as_str_or_none(card.get("url")),
                    "language": _as_str_or_none(card.get("language")),
                    "abstract": _trim_text(card.get("abstract"), max_chars=5000),
                    "citations": _as_int_or_none(card.get("citations")),
                    "influential_citations": _as_int_or_none(card.get("influential_citations")),
                    "provider": _as_str_or_none(card.get("provider")),
                    "provider_ids": (card.get("provider_ids") if isinstance(card.get("provider_ids"), dict) else None),
                    "external_ids": (card.get("external_ids") if isinstance(card.get("external_ids"), dict) else None),
                    "sources": (card.get("sources") if isinstance(card.get("sources"), list) else None),
                    "scores": scores,
                    "coverage_tags": coverage_tags,
                    "rerank": rerank,
                    "createdAt": SERVER_TIMESTAMP,
                }

                doc_id = f"{lane}_{pool}_{rank:03d}"
                docs.append((doc_id, payload))

    return docs


def _build_two_lane_telemetry_docs(*, telemetry: Dict[str, Any]) -> List[Tuple[str, dict]]:
    docs: List[Tuple[str, dict]] = []
    for doc_id, payload in (telemetry or {}).items():
        if not isinstance(doc_id, str) or not doc_id.strip():
            continue
        if not isinstance(payload, dict):
            payload = {"value": payload}
        docs.append(
            (
                doc_id.strip(),
                {
                    **payload,
                    "createdAt": SERVER_TIMESTAMP,
                },
            )
        )
    return docs


async def run_quellen_finder_sources_two_lane_job(
    *,
    user_id: str,
    projekt_id: str,
    kapitel_id: str,
    run_id: str,
    settings: Dict[str, Any],
) -> None:
    fs = QuellenFinderFirestoreService()

    t0 = time.perf_counter()
    logger.info(
        "QF two-lane job start | run_id=%s projekt_id=%s kapitel_id=%s settings_keys=%s",
        run_id,
        projekt_id,
        kapitel_id,
        sorted(list((settings or {}).keys())),
    )

    def _cancel_requested_sync() -> bool:
        snap = fs.run_ref(user_id, projekt_id, run_id).get()
        data = snap.to_dict() if snap is not None else {}
        return bool((data or {}).get("cancelRequestedAt"))

    async def check_cancel() -> None:
        if await asyncio.to_thread(_cancel_requested_sync):
            raise TwoLaneRunCancelled("Cancellation requested.")

    last_stage: str | None = None

    async def on_progress(stage: str, message: str) -> None:
        nonlocal last_stage
        stage_s = str(stage)
        stage_started_at = stage_s != (last_stage or "")
        if stage_started_at:
            last_stage = stage_s
        await asyncio.to_thread(
            fs.set_progress,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            stage=stage_s,
            message=str(message),
            stage_started_at=bool(stage_started_at),
        )

    async def on_telemetry(docs: Dict[str, Dict[str, Any]]) -> None:
        if not isinstance(docs, dict) or not docs:
            return
        try:
            docs_telemetry = _build_two_lane_telemetry_docs(telemetry=docs)
            await asyncio.to_thread(fs.write_two_lane_telemetry, user_id=user_id, projekt_id=projekt_id, run_id=run_id, docs=docs_telemetry)
        except Exception:
            return

    try:
        await check_cancel()
        fs.mark_running(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        await on_progress("starting", "Starting two-lane pipeline")
        await asyncio.to_thread(fs.clear_subcollection, user_id=user_id, projekt_id=projekt_id, run_id=run_id, name="twoLaneResults")
        await asyncio.to_thread(fs.clear_subcollection, user_id=user_id, projekt_id=projekt_id, run_id=run_id, name="twoLaneTelemetry")

        result = await run_two_lane_sources_pipeline(
            user_id=user_id,
            projekt_id=projekt_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            chapter_title=str((settings or {}).get("chapter_title") or "").strip(),
            chapter_spec_text=str((settings or {}).get("chapter_spec_text") or "").strip(),
            settings=(settings or {}).get("pipeline_settings") if isinstance((settings or {}).get("pipeline_settings"), dict) else {},
            check_cancel=check_cancel,
            on_progress=on_progress,
            on_telemetry=on_telemetry,
        )

        await on_progress("write_results", "Saving results")

        output = result.get("output") if isinstance(result, dict) else None
        telemetry = (result.get("telemetry") if isinstance(result, dict) else None) or {}
        costs = (result.get("costs") if isinstance(result, dict) else None) or {}
        effective_settings = (result.get("effective_settings") if isinstance(result, dict) else None) or {}

        if not isinstance(output, dict):
            raise RuntimeError("Pipeline produced no output.")

        docs_results = _build_two_lane_results_docs(output=output)
        docs_telemetry = _build_two_lane_telemetry_docs(telemetry=telemetry)

        fs.write_two_lane_results(user_id=user_id, projekt_id=projekt_id, run_id=run_id, docs=docs_results)

        telemetry_ok = True
        telemetry_error: str | None = None
        try:
            fs.write_two_lane_telemetry(user_id=user_id, projekt_id=projekt_id, run_id=run_id, docs=docs_telemetry)
        except Exception as exc:
            telemetry_ok = False
            telemetry_error = str(exc)[:800] if exc is not None else "unknown"
            logger.warning("QF two-lane telemetry write failed (ignored) | run_id=%s error=%s", run_id, telemetry_error)

        dt = time.perf_counter() - t0
        logger.info(
            "QF two-lane job success | run_id=%s seconds=%.2f results=%s telemetry_docs=%s cost_usd=%.4f",
            run_id,
            dt,
            int(len(docs_results)),
            int(len(docs_telemetry)),
            float(costs.get("total_cost_usd") or 0.0),
        )

        fs.mark_success(
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            had_partial_failures=not telemetry_ok,
            extra={
                "resultCount": int(len(docs_results)),
                "twoLaneSettings": effective_settings,
                "summary": {
                    "total_cost_usd": float(costs.get("total_cost_usd") or 0.0),
                    "budget_cap_usd": float(costs.get("budget_cap_usd") or 2.0),
                    "seconds_total": float(dt),
                    "telemetry_docs": int(len(docs_telemetry)),
                    "telemetry_write_ok": bool(telemetry_ok),
                    "telemetry_write_error": telemetry_error,
                },
            },
        )
    except TwoLaneRunCancelled:
        logger.info("QF two-lane job cancelled | run_id=%s", run_id)
        fs.mark_cancelled(user_id=user_id, projekt_id=projekt_id, run_id=run_id)
    except HTTPException as exc:
        logger.error(
            "QF two-lane job HTTPException | run_id=%s status=%s detail=%s",
            run_id,
            getattr(exc, "status_code", None),
            getattr(exc, "detail", None),
            exc_info=True,
        )
        detail = getattr(exc, "detail", None)
        msg = str(detail or exc)[:1000]
        fs.mark_error(user_id=user_id, projekt_id=projekt_id, run_id=run_id, error_message=msg, had_partial_failures=False)
    except Exception as exc:
        logger.error("QF two-lane job failed | run_id=%s error=%s", run_id, exc, exc_info=True)
        logger.debug("Traceback:\n%s", traceback.format_exc())
        fs.mark_error(user_id=user_id, projekt_id=projekt_id, run_id=run_id, error_message=str(exc), had_partial_failures=False)
