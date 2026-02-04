from __future__ import annotations

import os
import json
import logging
import time
import uuid
from typing import Any, Optional

import numpy as np
import pandas as pd
from fastapi import HTTPException

from services.cost_service import TokenUsage, get_cost_service
from services.credits_service import get_credits_service
from services.firebase_service import firebase_service
from services.openai_budget_service import get_openai_budget_service
from services.openai_service import OpenAIService
from services.user_key_service import user_key_service
from utils.token_estimation import count_tokens

from services.quellen_finder_sources_pipeline import (
    BLUEPRINT_INSTRUCTIONS,
    CHAPTER_BLUEPRINT_JSON_SCHEMA,
    ChapterBlueprint,
    EmbedBatchResult,
    STAGEC3_RERANK_JSON_SCHEMA,
    add_stageD_mmr_tfidf_v2,
    add_stagec3_signal_v1,
    add_stagec_final_scores,
    build_stagea,
    fetch_openalex_for_chapter,
    fetch_s2_for_chapter,
    query_list_for_chapter,
    score_pool_with_embeddings,
    score_stagec_pool_for_chapter,
    stagec3_rerank_topn,
)

logger = logging.getLogger(__name__)


def _get(obj: Any, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_text_from_response(resp: Any) -> str:
    t = _get(resp, "output_text", None)
    if isinstance(t, str) and t.strip():
        return t

    chunks: list[str] = []
    for item in _get(resp, "output", []) or []:
        if _get(item, "type") != "message":
            continue
        for part in _get(item, "content", []) or []:
            part_type = _get(part, "type")
            if part_type in ("output_text", "text"):
                txt = _get(part, "text", "")
                if txt:
                    chunks.append(txt)
    return "".join(chunks)


def _output_token_estimate_for_operation(operation_type: str) -> int:
    op = (operation_type or "").strip().lower()
    if op.endswith("stageb_blueprint"):
        return 1800
    if op.endswith("stagec3_rerank"):
        return 250
    if op.endswith("stagec_embeddings"):
        return 0
    return 1500


class QuellenFinderSourcesService:
    def __init__(self):
        self.firebase = firebase_service
        self.openai = OpenAIService()

    async def _reserve_and_call_json_schema(
        self,
        *,
        user_id: str,
        projekt_id: str,
        kapitel_id: str,
        research_run_id: str,
        operation_id: str,
        operation_type: str,
        model: str,
        system_message: str,
        prompt: str,
        schema_name: str,
        schema: dict,
        operation_details: dict | None = None,
        api_key: Optional[str],
        key_source: str,
    ) -> dict:
        credits_service = get_credits_service(self.firebase)
        cost_service = get_cost_service(self.firebase)
        budget_service = get_openai_budget_service(self.firebase)

        spend_rate = float(await credits_service.get_spend_rate_for_user(user_id))
        pricing_model, pricing, _match_type = await cost_service.resolve_model_pricing(model)
        input_price, cached_input_price, output_price = pricing

        input_tokens_est = int(count_tokens(system_message) + count_tokens(prompt))
        output_tokens_est = int(_output_token_estimate_for_operation(operation_type))
        cost_est_usd = float((input_tokens_est / 1_000_000) * float(input_price) + (output_tokens_est / 1_000_000) * float(output_price))
        credits_est = float(cost_est_usd * spend_rate)
        if credits_est <= 0:
            credits_est = 0.0001

        estimate = {
            "operationType": str(operation_type),
            "model": str(model),
            "pricingModel": str(pricing_model),
            "inputTokens": int(input_tokens_est),
            "outputTokens": int(output_tokens_est),
            "totalTokens": int(input_tokens_est + output_tokens_est),
            "costUsd": float(cost_est_usd),
            "spendRate": float(spend_rate),
            "credits": float(credits_est),
        }

        reservation = await budget_service.reserve_operation(
            user_id=user_id,
            operation_id=operation_id,
            operation_type=operation_type,
            user_action_id=research_run_id,
            estimate=estimate,
            projekt_id=projekt_id,
            kapitel_id=kapitel_id,
            operation_details=operation_details,
        )
        if reservation.result == "blocked":
            raise HTTPException(
                status_code=402,
                detail="Nicht genügend Credits verfügbar. Bitte lade Credits im Profil unter Billing auf.",
            )
        if reservation.result in {"already_reserved", "finalized"}:
            raise HTTPException(status_code=409, detail="Operation already exists. Please retry later.")

        await budget_service.mark_running(user_id=user_id, operation_id=operation_id)

        client = self.openai._get_client(api_key)  # pylint: disable=protected-access
        try:
            logger.debug(
                "QF OpenAI json_schema start | run_id=%s operation_id=%s operation_type=%s model=%s schema=%s in_est=%s out_est=%s credits_est=%.6f key_source=%s",
                research_run_id,
                operation_id,
                operation_type,
                model,
                schema_name,
                int(input_tokens_est),
                int(output_tokens_est),
                float(credits_est),
                key_source,
            )
            resp = await client.responses.create(
                model=model,
                service_tier="default",
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": system_message}]},
                    {"role": "user", "content": [{"type": "input_text", "text": prompt}]},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": schema,
                        "strict": True,
                    }
                },
                reasoning={"effort": "low"},
                max_output_tokens=None,
                store=False,
            )
        except Exception as exc:
            logger.error(
                "QF OpenAI json_schema failed | run_id=%s operation_id=%s operation_type=%s model=%s schema=%s",
                research_run_id,
                operation_id,
                operation_type,
                model,
                schema_name,
                exc_info=True,
            )
            await budget_service.mark_status(
                user_id=user_id,
                operation_id=operation_id,
                status="error",
                error_message=str(exc),
            )
            await budget_service.release_reservation(user_id=user_id, operation_id=operation_id, reason="error")
            raise

        raw = _extract_text_from_response(resp).strip()
        if not raw:
            logger.error(
                "QF OpenAI json_schema empty output | run_id=%s operation_id=%s operation_type=%s model=%s schema=%s",
                research_run_id,
                operation_id,
                operation_type,
                model,
                schema_name,
            )
            await budget_service.release_reservation(user_id=user_id, operation_id=operation_id, reason="error")
            raise RuntimeError("Model returned no parsable output text (empty).")

        try:
            data = json.loads(raw)
        except Exception as exc:
            preview = raw[:220].replace("\n", "\\n")
            logger.error(
                "QF OpenAI json_schema parse failed | run_id=%s operation_id=%s operation_type=%s model=%s schema=%s raw_len=%s raw_preview=%s",
                research_run_id,
                operation_id,
                operation_type,
                model,
                schema_name,
                len(raw),
                preview,
            )
            await budget_service.release_reservation(user_id=user_id, operation_id=operation_id, reason="error")
            raise RuntimeError("Failed to parse JSON output.") from exc

        usage = cost_service.extract_usage_from_response(resp)
        cost_breakdown, matched_model, pricing, _match_type = await cost_service.calculate_cost(
            model=str(getattr(resp, "model", None) or model),
            usage=usage,
        )

        await cost_service.log_operation(
            operation_id=operation_id,
            operation_type=operation_type,
            user_id=user_id,
            user_action_id=research_run_id,
            operation_details=operation_details,
            model=str(getattr(resp, "model", None) or model),
            usage=usage,
            cost_breakdown=cost_breakdown,
            matched_model_key=matched_model,
            pricing=pricing,
            key_source=key_source,
            projekt_id=projekt_id,
            kapitel_id=kapitel_id,
            run_id=None,
            quelle_id=None,
        )

        await budget_service.release_reservation(user_id=user_id, operation_id=operation_id, reason="success")

        if str(operation_type or "").strip().lower().endswith("stageb_blueprint"):
            logger.info(
                "QF OpenAI json_schema success | run_id=%s operation_id=%s operation_type=%s model=%s input_tokens=%s output_tokens=%s cost_usd=%.6f",
                research_run_id,
                operation_id,
                operation_type,
                str(getattr(resp, "model", None) or model),
                int(usage.input_tokens),
                int(usage.output_tokens),
                float(cost_breakdown.total_cost_usd),
            )
        else:
            logger.debug(
                "QF OpenAI json_schema success | run_id=%s operation_id=%s operation_type=%s model=%s input_tokens=%s output_tokens=%s cost_usd=%.6f",
                research_run_id,
                operation_id,
                operation_type,
                str(getattr(resp, "model", None) or model),
                int(usage.input_tokens),
                int(usage.output_tokens),
                float(cost_breakdown.total_cost_usd),
            )

        return {
            "data": data,
            "usage": usage,
            "model": str(getattr(resp, "model", None) or model),
            "_meta": {
                "requests": 1,
                "input_tokens": int(usage.input_tokens),
                "cached_input_tokens": int(usage.cached_input_tokens),
                "output_tokens": int(usage.output_tokens),
                "cost_usd": float(cost_breakdown.total_cost_usd),
                "llm_cached": False,
            },
        }

    async def _embed_texts_with_budget(
        self,
        *,
        user_id: str,
        projekt_id: str,
        kapitel_id: str,
        research_run_id: str,
        operation_id_prefix: str,
        texts: list[str],
        model: str,
        batch_size: int,
        api_key: Optional[str],
        key_source: str,
    ) -> EmbedBatchResult:
        credits_service = get_credits_service(self.firebase)
        cost_service = get_cost_service(self.firebase)
        budget_service = get_openai_budget_service(self.firebase)

        spend_rate = float(await credits_service.get_spend_rate_for_user(user_id))
        pricing_model, pricing, _match_type = await cost_service.resolve_model_pricing(model)
        input_price, cached_input_price, output_price = pricing

        client = self.openai._get_client(api_key)  # pylint: disable=protected-access

        all_vecs: list[np.ndarray] = []
        reqs = 0
        toks = 0

        for bi in range(0, len(texts), int(batch_size)):
            batch = texts[bi : bi + int(batch_size)]
            if not batch:
                continue

            op_id = f"{operation_id_prefix}_b{bi}"
            operation_type = "quellen_finder_sources_stagec_embeddings"

            input_tokens_est = int(sum(count_tokens(t) for t in batch))
            cost_est_usd = float((input_tokens_est / 1_000_000) * float(input_price))
            credits_est = float(cost_est_usd * spend_rate)
            if credits_est <= 0:
                credits_est = 0.0001

            estimate = {
                "operationType": operation_type,
                "model": str(model),
                "pricingModel": str(pricing_model),
                "inputTokens": int(input_tokens_est),
                "outputTokens": 0,
                "totalTokens": int(input_tokens_est),
                "costUsd": float(cost_est_usd),
                "spendRate": float(spend_rate),
                "credits": float(credits_est),
            }

            reservation = await budget_service.reserve_operation(
                user_id=user_id,
                operation_id=op_id,
                operation_type=operation_type,
                user_action_id=research_run_id,
                estimate=estimate,
                projekt_id=projekt_id,
                kapitel_id=kapitel_id,
            )
            if reservation.result == "blocked":
                raise HTTPException(
                    status_code=402,
                    detail="Nicht genügend Credits verfügbar. Bitte lade Credits im Profil unter Billing auf.",
                )
            if reservation.result in {"already_reserved", "finalized"}:
                raise HTTPException(status_code=409, detail="Operation already exists. Please retry later.")

            await budget_service.mark_running(user_id=user_id, operation_id=op_id)

            try:
                logger.debug(
                    "QF embeddings start | run_id=%s operation_id=%s model=%s batchSize=%s in_est=%s credits_est=%.6f key_source=%s",
                    research_run_id,
                    op_id,
                    model,
                    int(len(batch)),
                    int(input_tokens_est),
                    float(credits_est),
                    key_source,
                )
                resp = await client.embeddings.create(model=model, input=batch)
            except Exception as exc:
                logger.error(
                    "QF embeddings failed | run_id=%s operation_id=%s model=%s batchSize=%s",
                    research_run_id,
                    op_id,
                    model,
                    int(len(batch)),
                    exc_info=True,
                )
                await budget_service.mark_status(user_id=user_id, operation_id=op_id, status="error", error_message=str(exc))
                await budget_service.release_reservation(user_id=user_id, operation_id=op_id, reason="error")
                raise

            vecs = [np.array(item.embedding, dtype=np.float32) for item in resp.data]
            all_vecs.extend(vecs)

            usage_obj = getattr(resp, "usage", None)
            prompt_tokens = int(getattr(usage_obj, "total_tokens", 0) or getattr(usage_obj, "prompt_tokens", 0) or 0)
            toks += prompt_tokens
            reqs += 1

            usage = TokenUsage.from_any(prompt_tokens, 0, 0)
            cost_breakdown, matched_model, pricing, _match_type = await cost_service.calculate_cost(model=model, usage=usage)

            await cost_service.log_operation(
                operation_id=op_id,
                operation_type=operation_type,
                user_id=user_id,
                user_action_id=research_run_id,
                operation_details={"batchSize": int(len(batch))},
                model=model,
                usage=usage,
                cost_breakdown=cost_breakdown,
                matched_model_key=matched_model,
                pricing=pricing,
                key_source=key_source,
                projekt_id=projekt_id,
                kapitel_id=kapitel_id,
            )

            await budget_service.release_reservation(user_id=user_id, operation_id=op_id, reason="success")

        if not all_vecs:
            return EmbedBatchResult(embeds=np.zeros((0, 1), dtype=np.float32), requests=0, input_tokens=0)

        return EmbedBatchResult(embeds=np.vstack(all_vecs), requests=int(reqs), input_tokens=int(toks))

    async def run_sources_search(
        self,
        *,
        user_id: str,
        projekt_id: str,
        kapitel_id: str,
        research_run_id: str,
        blueprint_model: str = "gpt-5-mini",
    ) -> tuple[pd.DataFrame, dict]:
        projekt_id = str(projekt_id or "").strip()
        kapitel_id = str(kapitel_id or "").strip()
        if not projekt_id:
            raise HTTPException(status_code=400, detail="projekt_id is required")
        if not kapitel_id:
            raise HTTPException(status_code=400, detail="kapitel_id is required")

        projekt = await self.firebase.get_project(user_id, projekt_id)
        if not projekt:
            raise HTTPException(status_code=404, detail="Projekt nicht gefunden.")

        kapitel = await self.firebase.get_kapitel(user_id, kapitel_id)
        if not kapitel:
            raise HTTPException(status_code=404, detail="Kapitel nicht gefunden.")
        if str(kapitel.get("projektId") or "").strip() != projekt_id:
            raise HTTPException(status_code=400, detail="Kapitel gehört nicht zu diesem Projekt.")

        chapter_spec = {
            "chapter_id": kapitel_id,
            "title": str(kapitel.get("title") or "").strip(),
            "original_text_language": "de",
            "original_text": str(kapitel.get("thema") or "").strip(),
        }
        if not chapter_spec["title"]:
            raise HTTPException(status_code=400, detail="Kapitelüberschrift fehlt (Kapitel.title).")
        if not chapter_spec["original_text"]:
            raise HTTPException(status_code=400, detail="Thema & Anweisungen fehlt (Kapitel.thema).")

        api_key, key_source = await user_key_service.resolve_api_key_for_user(user_id)

        workflow_id = uuid.uuid4().hex
        logger.info(
            "QF sources search start | run_id=%s projekt_id=%s kapitel_id=%s blueprint_model=%s workflow_id=%s key_source=%s",
            research_run_id,
            projekt_id,
            kapitel_id,
            blueprint_model,
            workflow_id,
            key_source,
        )

        # Stage B: blueprint
        op_id_b = f"{workflow_id}_qf_sources_stageb_{kapitel_id}"
        bp_prompt = (
            "Create a ChapterBlueprint for academic literature retrieval.\n"
            "Return ONLY the structured output fields required by the schema.\n\n"
            "CHAPTER_SPEC_JSON:\n"
            + json.dumps(chapter_spec, ensure_ascii=False, indent=2)
        )

        t_stageb = time.perf_counter()
        logger.info("QF sources Stage B (blueprint) start | run_id=%s model=%s", research_run_id, blueprint_model)
        bp_res = await self._reserve_and_call_json_schema(
            user_id=user_id,
            projekt_id=projekt_id,
            kapitel_id=kapitel_id,
            research_run_id=research_run_id,
            operation_id=op_id_b,
            operation_type="quellen_finder_sources_stageb_blueprint",
            model=blueprint_model,
            system_message=BLUEPRINT_INSTRUCTIONS,
            prompt=bp_prompt,
            schema_name="chapter_blueprint",
            schema=CHAPTER_BLUEPRINT_JSON_SCHEMA,
            operation_details={"chapterId": kapitel_id},
            api_key=api_key,
            key_source=key_source,
        )

        blueprint = ChapterBlueprint.model_validate(bp_res["data"])
        logger.info(
            "QF sources Stage B (blueprint) done | run_id=%s seconds=%.2f must_cover=%s facet_queries=%s keywords=%s preferred_types=%s",
            research_run_id,
            float(time.perf_counter() - t_stageb),
            int(len(blueprint.must_cover or [])),
            int(len(blueprint.facet_queries or [])),
            int(len(blueprint.keywords or [])),
            int(len(blueprint.preferred_source_types or [])) if blueprint.preferred_source_types else 0,
        )

        # Stage A: external APIs
        queries = query_list_for_chapter(blueprint)
        openalex_key = str(os.getenv("OPENALEX_API_KEY", "") or "").strip()
        s2_key = str(os.getenv("SEMANTICSCHOLAR_API_KEY", "") or "").strip()

        t_stagea = time.perf_counter()
        logger.info(
            "QF sources Stage A (fetch) start | run_id=%s queries=%s openalex_key=%s s2_key=%s",
            research_run_id,
            int(len(queries)),
            bool(openalex_key),
            bool(s2_key),
        )
        try:
            df_oa = fetch_openalex_for_chapter(chapter_id=kapitel_id, queries=queries, openalex_api_key=openalex_key)
            df_s2 = fetch_s2_for_chapter(chapter_id=kapitel_id, queries=queries, semanticscholar_api_key=s2_key)
            df_stageA = build_stagea(df_oa_raw=df_oa, df_s2_raw=df_s2, chapter_id=kapitel_id)
        except Exception:
            logger.error("QF sources Stage A (fetch) failed | run_id=%s", research_run_id, exc_info=True)
            raise
        logger.info(
            "QF sources Stage A (fetch) done | run_id=%s seconds=%.2f openalex_rows=%s s2_rows=%s merged_rows=%s",
            research_run_id,
            float(time.perf_counter() - t_stagea),
            int(len(df_oa)) if isinstance(df_oa, pd.DataFrame) else None,
            int(len(df_s2)) if isinstance(df_s2, pd.DataFrame) else None,
            int(len(df_stageA)) if isinstance(df_stageA, pd.DataFrame) else None,
        )

        if df_stageA.empty:
            logger.info("QF sources Stage A empty -> success-with-empty | run_id=%s", research_run_id)
            return pd.DataFrame(), {"blueprint": blueprint.model_dump(), "queries": queries}

        # Stage C: pool + scoring
        t_stagec = time.perf_counter()
        pool = score_stagec_pool_for_chapter(chapter_id=kapitel_id, stagea_df=df_stageA, blueprint=blueprint)
        if pool.empty:
            logger.info("QF sources Stage C pool empty -> success-with-empty | run_id=%s", research_run_id)
            return pd.DataFrame(), {"blueprint": blueprint.model_dump(), "queries": queries}
        logger.info(
            "QF sources Stage C pool built | run_id=%s pool_rows=%s",
            research_run_id,
            int(len(pool)) if isinstance(pool, pd.DataFrame) else None,
        )

        bp_dict = blueprint.model_dump()

        async def _embed_texts(texts: list[str], *, model: str, batch_size: int) -> EmbedBatchResult:
            op_prefix = f"{workflow_id}_qf_sources_embed_{kapitel_id}"
            return await self._embed_texts_with_budget(
                user_id=user_id,
                projekt_id=projekt_id,
                kapitel_id=kapitel_id,
                research_run_id=research_run_id,
                operation_id_prefix=op_prefix,
                texts=texts,
                model=model,
                batch_size=batch_size,
                api_key=api_key,
                key_source=key_source,
            )

        pool_scored, embed_totals = await score_pool_with_embeddings(bp_dict, pool, embed_texts=_embed_texts)
        pool_scored = add_stagec_final_scores(pool_scored)
        logger.info(
            "QF sources Stage C scoring done | run_id=%s seconds=%.2f embed_requests=%s embed_input_tokens=%s",
            research_run_id,
            float(time.perf_counter() - t_stagec),
            int((embed_totals or {}).get("requests") or 0),
            int((embed_totals or {}).get("input_tokens") or 0),
        )

        # Stage C.3 rerank
        async def _call_stagec3_rerank(*, model: str, system: str, prompt: str) -> dict:
            doc_hash = uuid.uuid4().hex[:10]
            op_id = f"{workflow_id}_qf_sources_stagec3_{kapitel_id}_{doc_hash}"
            res = await self._reserve_and_call_json_schema(
                user_id=user_id,
                projekt_id=projekt_id,
                kapitel_id=kapitel_id,
                research_run_id=research_run_id,
                operation_id=op_id,
                operation_type="quellen_finder_sources_stagec3_rerank",
                model=model,
                system_message=system,
                prompt=prompt,
                schema_name="stagec3_rerank",
                schema=STAGEC3_RERANK_JSON_SCHEMA,
                operation_details={"chapterId": kapitel_id},
                api_key=api_key,
                key_source=key_source,
            )
            out = res["data"]
            out["_meta"] = res.get("_meta") or {}
            return out

        logger.info("QF sources Stage C3 (rerank) start | run_id=%s", research_run_id)
        stagec3_df, stagec3_totals = await stagec3_rerank_topn(
            pool_scored,
            blueprints_by_chapter_id={kapitel_id: blueprint},
            call_rerank_llm=_call_stagec3_rerank,
            min_non_exclude=20,
        )
        logger.info(
            "QF sources Stage C3 (rerank) done | run_id=%s seconds=%.2f requests=%s cached_files=%s",
            research_run_id,
            float((stagec3_totals or {}).get("seconds") or 0.0),
            int((stagec3_totals or {}).get("requests") or 0),
            int((stagec3_totals or {}).get("cached_files") or 0),
        )

        # Stage D
        final_score_col = "score_stageC3_topn_final"
        t_staged = time.perf_counter()
        stagec3_df = add_stagec3_signal_v1(stagec3_df)
        stagec3_df = add_stageD_mmr_tfidf_v2(stagec3_df)
        final_score_col = "score_stageD_final"
        logger.info(
            "QF sources Stage D done | run_id=%s seconds=%.2f rows=%s",
            research_run_id,
            float(time.perf_counter() - t_staged),
            int(len(stagec3_df)) if isinstance(stagec3_df, pd.DataFrame) else None,
        )

        # Final top30
        out = stagec3_df.sort_values(final_score_col, ascending=False, kind="mergesort").copy()
        if "llm_label" in out.columns:
            out = out[~out["llm_label"].fillna("").astype(str).eq("exclude")].copy()
        out = out.head(30).copy()
        logger.info(
            "QF sources final top30 | run_id=%s out_rows=%s finalScoreCol=%s",
            research_run_id,
            int(len(out)) if isinstance(out, pd.DataFrame) else None,
            final_score_col,
        )

        meta = {
            "blueprint": blueprint.model_dump(),
            "queries": queries,
            "embed_totals": embed_totals,
            "stagec3_totals": stagec3_totals,
            "final_score_col": final_score_col,
        }
        return out, meta


quellen_finder_sources_service = QuellenFinderSourcesService()
