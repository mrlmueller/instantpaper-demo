"""Quellen-Finder PDF scan background job (ported from pdf-scan-test.ipynb)."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException
from firebase_admin import storage
from google.api_core.exceptions import NotFound
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.cost_service import get_cost_service
from services.credits_service import get_credits_service
from services.firebase_service import firebase_service
from services.openai_budget_service import get_openai_budget_service
from services.openai_service import OpenAIService
from services.quellen_finder_firestore_service import QuellenFinderFirestoreService
from services.user_key_service import user_key_service
from utils.config import config
from utils.token_estimation import count_tokens

from services.quellen_finder_pdf_scan_pipeline import (
    PREPROCESS_SCHEMA,
    PREPROCESS_SYSTEM_PROMPT,
    RESULT_SCHEMA,
    build_preprocess_user_prompt,
    build_stage2_system_prompt,
    build_evidence_from_vector_store_search,
    curate_pdf_sections,
    dedup_and_sort,
    item_file_id,
    normalize_whitespace,
    postprocess_and_filter,
    vector_store_search_items,
)

logger = logging.getLogger(__name__)


# Notebook-aligned defaults
PREPROCESS_MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_PREPROCESS_MAX_OUTPUT_TOKENS", "6000") or "6000")
PREPROCESS_RETRY_MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_PREPROCESS_RETRY_MAX_OUTPUT_TOKENS", "15000") or "15000")
FILE_SEARCH_MAX_RESULTS_PER_PDF = int(os.getenv("OPENAI_PDF_SCAN_FILE_SEARCH_MAX_RESULTS_PER_PDF", "10") or "10")
MAX_HITS = int(os.getenv("OPENAI_PDF_SCAN_MAX_HITS", "8") or "8")
MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_PDF_SCAN_MAX_OUTPUT_TOKENS", "6000") or "6000")
REASONING_EFFORT = (os.getenv("OPENAI_REASONING_EFFORT", "low") or "low").strip() or "low"

# Stage 3 defaults
ENABLE_STAGE3_CURATION = True
ENABLE_BALANCED_RETRIEVAL = True
BALANCED_RETRIEVAL_TARGET_HITS_PER_PDF = None
ENABLE_SUBPOINT_TOPUP = True
SUBPOINT_TOPUP_MAX_CALLS = 3
SOFT_TOTAL_SECTIONS_TARGET = None
HARD_MAX_SELECTED_SECTIONS = 25
SUBPOINT_IMPORTANCE: dict[str, float] = {}


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
    with path.open("rb") as f:
        head = f.read(5)
    if not head.startswith(b"%PDF"):
        raise RuntimeError(f"Downloaded file does not look like a PDF (header={head!r}): {path}")


def _download_pdf_from_firebase_storage(
    *,
    storage_path: str,
    dest_path: Path,
    expected_size: int | None,
    max_retries: int = 6,
) -> None:
    storage_path = str(storage_path or "").strip().lstrip("/")
    if not storage_path:
        raise ValueError("storage_path is required")

    last_exc: Exception | None = None
    for attempt in range(1, int(max_retries) + 1):
        for bucket_name in _candidate_bucket_names(config.FIREBASE_PROJECT_ID, config.FIREBASE_STORAGE_BUCKET):
            try:
                bucket = storage.bucket(bucket_name)
                blob = bucket.blob(storage_path)
                if not blob.exists():
                    continue
                blob.download_to_filename(str(dest_path))
                _verify_pdf_file(dest_path, expected_size=expected_size)
                return
            except NotFound as exc:
                last_exc = exc
                continue
            except Exception as exc:
                last_exc = exc
                continue

        sleep_s = min(8.0, 0.8 * (2 ** (attempt - 1)))
        time.sleep(float(sleep_s))

    raise RuntimeError(f"Failed to download {storage_path} from Firebase Storage") from last_exc


async def _ensure_attached_and_indexed(
    client: Any,
    *,
    vector_store_id: str,
    file_id: str,
    attributes: dict | None,
) -> Any:
    vs_file = None
    try:
        vs_file = await client.vector_stores.files.retrieve(vector_store_id=vector_store_id, file_id=file_id)
    except Exception:
        vs_file = None

    if vs_file is None:
        if hasattr(client.vector_stores.files, "create_and_poll"):
            try:
                vs_file = await client.vector_stores.files.create_and_poll(
                    vector_store_id=vector_store_id, file_id=file_id, attributes=attributes
                )
            except Exception as e:
                logger.warning("Attach failed, trying retrieve: %s", e)
                vs_file = await client.vector_stores.files.retrieve(vector_store_id=vector_store_id, file_id=file_id)
        else:
            try:
                await client.vector_stores.files.create(
                    vector_store_id=vector_store_id, file_id=file_id, attributes=attributes
                )
            except Exception as e:
                logger.warning("Attach failed (continuing): %s", e)
            vs_file = await client.vector_stores.files.retrieve(vector_store_id=vector_store_id, file_id=file_id)

    if attributes:
        try:
            await client.vector_stores.files.update(
                vector_store_id=vector_store_id,
                file_id=file_id,
                attributes=attributes,
            )
        except Exception as e:
            logger.warning("Could not update vector store file attributes (continuing): %s", e)

    status = getattr(vs_file, "status", None)
    if status and status not in {"completed", "failed"} and hasattr(client.vector_stores.files, "poll"):
        vs_file = await client.vector_stores.files.poll(vector_store_id=vector_store_id, file_id=file_id)
        status = getattr(vs_file, "status", status)

    if status == "failed":
        raise RuntimeError(f"Vector store indexing failed for file_id={file_id}.")

    logger.info("Vector store file status: %s %s", file_id, status)
    return vs_file


class QuellenFinderPdfScanJob:
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
        max_output_tokens: int,
        operation_details: dict | None,
        api_key: Optional[str],
        key_source: str,
    ) -> dict:
        credits_service = get_credits_service(self.firebase)
        cost_service = get_cost_service(self.firebase)
        budget_service = get_openai_budget_service(self.firebase)

        spend_rate = float(await credits_service.get_spend_rate_for_user(user_id))
        pricing_model, pricing, _match_type = await cost_service.resolve_model_pricing(model)
        input_price, _cached_input_price, output_price = pricing

        input_tokens_est = int(count_tokens(system_message) + count_tokens(prompt))
        output_tokens_est = int(max(1, int(max_output_tokens)))
        cost_est_usd = float(
            (input_tokens_est / 1_000_000) * float(input_price) + (output_tokens_est / 1_000_000) * float(output_price)
        )
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
                reasoning={"effort": REASONING_EFFORT},
                max_output_tokens=int(max_output_tokens),
                store=False,
            )
        except Exception as exc:
            await budget_service.mark_status(user_id=user_id, operation_id=operation_id, status="error", error_message=str(exc))
            await budget_service.release_reservation(user_id=user_id, operation_id=operation_id, reason="error")
            raise

        raw = _extract_text_from_response(resp).strip()
        if not raw:
            await budget_service.release_reservation(user_id=user_id, operation_id=operation_id, reason="error")
            raise RuntimeError("Model returned no parsable output text (empty).")

        try:
            data = json.loads(raw)
        except Exception as exc:
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
        )

        await budget_service.release_reservation(user_id=user_id, operation_id=operation_id, reason="success")

        return {"data": data, "usage": usage, "model": str(getattr(resp, "model", None) or model)}

    async def run(
        self,
        *,
        user_id: str,
        projekt_id: str,
        kapitel_id: str,
        run_id: str,
        pdf_ids: list[str],
        preprocess: bool,
    ) -> None:
        fs = QuellenFinderFirestoreService()

        projekt_id = str(projekt_id or "").strip()
        kapitel_id = str(kapitel_id or "").strip()
        run_id = str(run_id or "").strip()
        pdf_ids = [str(x or "").strip() for x in (pdf_ids or []) if str(x or "").strip()]

        if not projekt_id or not kapitel_id or not run_id:
            raise HTTPException(status_code=400, detail="Missing required identifiers.")

        projekt = await self.firebase.get_project(user_id, projekt_id)
        if not projekt:
            raise HTTPException(status_code=404, detail="Projekt nicht gefunden.")
        kapitel = await self.firebase.get_kapitel(user_id, kapitel_id)
        if not kapitel:
            raise HTTPException(status_code=404, detail="Kapitel nicht gefunden.")

        if str(kapitel.get("projektId") or "").strip() != projekt_id:
            raise HTTPException(status_code=400, detail="Kapitel gehört nicht zu diesem Projekt.")

        chapter_title = str(kapitel.get("title") or "").strip()
        chapter_description = str(kapitel.get("thema") or "").strip()
        if not chapter_title:
            raise HTTPException(status_code=400, detail="Kapitelüberschrift fehlt (Kapitel.title).")
        if not chapter_description:
            raise HTTPException(status_code=400, detail="Thema & Anweisungen fehlt (Kapitel.thema).")

        await get_credits_service(self.firebase).assert_not_negative_balance(user_id)

        api_key, key_source = await user_key_service.resolve_api_key_for_user(user_id)
        client = self.openai._get_client(api_key)  # pylint: disable=protected-access

        workflow_id = uuid.uuid4().hex

        had_partial_failures = False
        openai_file_ids: list[str] = []
        vector_store_id: str | None = None

        try:
            fs.mark_running(user_id=user_id, projekt_id=projekt_id, run_id=run_id)

            with tempfile.TemporaryDirectory(prefix="qf_pdf_scan_") as tmpdir:
                tmpdir_path = Path(tmpdir)

                fs.set_progress(
                    user_id=user_id,
                    projekt_id=projekt_id,
                    run_id=run_id,
                    stage="download_pdfs",
                    message="Downloading PDFs from Firebase Storage",
                    current=0,
                    total=len(pdf_ids),
                )

                project_pdf_docs: dict[str, dict] = {}
                for pdf_id in pdf_ids:
                    snap = (
                        self.firebase.db.collection("users")
                        .document(user_id)
                        .collection("projects")
                        .document(projekt_id)
                        .collection("pdfs")
                        .document(pdf_id)
                        .get()
                    )
                    if not snap.exists:
                        had_partial_failures = True
                        continue
                    project_pdf_docs[pdf_id] = snap.to_dict() or {}

                downloaded: list[dict] = []
                done = 0
                for pdf_id, doc in project_pdf_docs.items():
                    done += 1
                    fs.set_progress(
                        user_id=user_id,
                        projekt_id=projekt_id,
                        run_id=run_id,
                        stage="download_pdfs",
                        message=f"Downloading {doc.get('filename') or pdf_id}",
                        current=done,
                        total=len(project_pdf_docs),
                    )

                    storage_path = str(doc.get("storagePath") or "").strip()
                    filename = str(doc.get("filename") or "document.pdf").strip() or "document.pdf"
                    expected_size = int(doc.get("size") or 0) if isinstance(doc.get("size"), (int, float)) else None

                    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)[:120] or f"{pdf_id}.pdf"
                    local_path = tmpdir_path / f"{pdf_id}_{safe_name}"

                    try:
                        _download_pdf_from_firebase_storage(
                            storage_path=storage_path,
                            dest_path=local_path,
                            expected_size=expected_size,
                        )
                    except Exception as exc:
                        had_partial_failures = True
                        logger.warning("Failed to download PDF %s (%s): %s", pdf_id, storage_path, exc)
                        continue

                    downloaded.append(
                        {
                            "pdf_id": pdf_id,
                            "filename": filename,
                            "storage_path": storage_path,
                            "local_path": str(local_path),
                        }
                    )

                if not downloaded:
                    fs.mark_success(
                        user_id=user_id,
                        projekt_id=projekt_id,
                        run_id=run_id,
                        had_partial_failures=had_partial_failures,
                        extra={"resultCount": 0},
                    )
                    return

                fs.set_progress(
                    user_id=user_id,
                    projekt_id=projekt_id,
                    run_id=run_id,
                    stage="stage0_vector_store",
                    message="Creating vector store + uploading PDFs",
                )

                vector_store = await client.vector_stores.create(
                    name=f"quellen-finder-pdf-scan:{projekt_id}:{run_id}",
                    expires_after={"anchor": "last_active_at", "days": 2},
                )
                vector_store_id = str(vector_store.id)

                pdf_artifacts: list[dict] = []
                for idx, pdf in enumerate(downloaded, start=1):
                    fs.set_progress(
                        user_id=user_id,
                        projekt_id=projekt_id,
                        run_id=run_id,
                        stage="stage0_vector_store",
                        message=f"Uploading {pdf.get('filename')}",
                        current=idx,
                        total=len(downloaded),
                    )
                    local_path = Path(str(pdf.get("local_path") or ""))
                    if not local_path.exists():
                        had_partial_failures = True
                        continue
                    try:
                        with local_path.open("rb") as f:
                            file_obj = await client.files.create(file=f, purpose="assistants")
                        openai_file_id = str(getattr(file_obj, "id", "") or "")
                        if not openai_file_id:
                            raise RuntimeError("OpenAI file upload returned no id.")
                        openai_file_ids.append(openai_file_id)

                        await _ensure_attached_and_indexed(
                            client,
                            vector_store_id=vector_store_id,
                            file_id=openai_file_id,
                            attributes={
                                "pdf_label": str(pdf.get("filename") or pdf.get("pdf_id")),
                                "pdf_file_id": openai_file_id,
                            },
                        )

                        pdf_artifacts.append(
                            {
                                "label": str(pdf.get("filename") or pdf.get("pdf_id")),
                                "file_id": openai_file_id,
                                "path": str(local_path),
                                "pdf_id": str(pdf.get("pdf_id")),
                            }
                        )
                    except Exception as exc:
                        had_partial_failures = True
                        logger.warning("Failed to upload/index PDF %s: %s", pdf.get("pdf_id"), exc)
                        continue

                if not pdf_artifacts:
                    fs.mark_success(
                        user_id=user_id,
                        projekt_id=projekt_id,
                        run_id=run_id,
                        had_partial_failures=True,
                        extra={"resultCount": 0},
                    )
                    return

                optimized_description = normalize_whitespace(chapter_description)
                subpoints: list[dict] = []
                preferred_search_terms: list[str] = []
                must_terms: list[str] = []
                should_terms: list[str] = []
                scope_notes = ""
                hard_exclusions: list[str] = []

                if bool(preprocess):
                    fs.set_progress(
                        user_id=user_id,
                        projekt_id=projekt_id,
                        run_id=run_id,
                        stage="stage1_preprocess",
                        message="Running preprocess (Stage 1)",
                    )
                    user_prompt = build_preprocess_user_prompt(
                        chapter_title=chapter_title,
                        chapter_description=chapter_description,
                    )
                    preprocess_model = str(os.getenv("OPENAI_PDF_SCAN_PREPROCESS_MODEL", "gpt-5-nano") or "gpt-5-nano").strip() or "gpt-5-nano"
                    fallback_model = str(os.getenv("OPENAI_PDF_SCAN_PREPROCESS_FALLBACK_MODEL", "gpt-5-mini") or "gpt-5-mini").strip() or "gpt-5-mini"

                    pre_json: dict | None = None
                    try:
                        op_id = f"{workflow_id}_qf_pdf_preprocess_{kapitel_id}"
                        res = await self._reserve_and_call_json_schema(
                            user_id=user_id,
                            projekt_id=projekt_id,
                            kapitel_id=kapitel_id,
                            research_run_id=run_id,
                            operation_id=op_id,
                            operation_type="quellen_finder_pdf_preprocess",
                            model=preprocess_model,
                            system_message=PREPROCESS_SYSTEM_PROMPT,
                            prompt=user_prompt,
                            schema_name="chapter_preprocess",
                            schema=PREPROCESS_SCHEMA,
                            max_output_tokens=int(PREPROCESS_MAX_OUTPUT_TOKENS),
                            operation_details={"stage": "preprocess"},
                            api_key=api_key,
                            key_source=key_source,
                        )
                        pre_json = res.get("data") if isinstance(res, dict) else None
                    except Exception as exc:
                        had_partial_failures = True
                        logger.warning("Preprocess failed; retrying once with higher max_output_tokens: %s", exc)
                        try:
                            op_id2 = f"{workflow_id}_qf_pdf_preprocess_retry_{kapitel_id}"
                            res2 = await self._reserve_and_call_json_schema(
                                user_id=user_id,
                                projekt_id=projekt_id,
                                kapitel_id=kapitel_id,
                                research_run_id=run_id,
                                operation_id=op_id2,
                                operation_type="quellen_finder_pdf_preprocess_retry",
                                model=preprocess_model,
                                system_message=PREPROCESS_SYSTEM_PROMPT,
                                prompt=user_prompt,
                                schema_name="chapter_preprocess",
                                schema=PREPROCESS_SCHEMA,
                                max_output_tokens=int(PREPROCESS_RETRY_MAX_OUTPUT_TOKENS),
                                operation_details={"stage": "preprocess_retry"},
                                api_key=api_key,
                                key_source=key_source,
                            )
                            pre_json = res2.get("data") if isinstance(res2, dict) else None
                        except Exception as exc2:
                            had_partial_failures = True
                            logger.warning("Preprocess retry failed; trying fallback model=%s: %s", fallback_model, exc2)
                            if fallback_model and fallback_model != preprocess_model:
                                try:
                                    op_id3 = f"{workflow_id}_qf_pdf_preprocess_fallback_{kapitel_id}"
                                    res3 = await self._reserve_and_call_json_schema(
                                        user_id=user_id,
                                        projekt_id=projekt_id,
                                        kapitel_id=kapitel_id,
                                        research_run_id=run_id,
                                        operation_id=op_id3,
                                        operation_type="quellen_finder_pdf_preprocess_fallback",
                                        model=fallback_model,
                                        system_message=PREPROCESS_SYSTEM_PROMPT,
                                        prompt=user_prompt,
                                        schema_name="chapter_preprocess",
                                        schema=PREPROCESS_SCHEMA,
                                        max_output_tokens=int(PREPROCESS_RETRY_MAX_OUTPUT_TOKENS),
                                        operation_details={"stage": "preprocess_fallback"},
                                        api_key=api_key,
                                        key_source=key_source,
                                    )
                                    pre_json = res3.get("data") if isinstance(res3, dict) else None
                                except Exception as exc3:
                                    had_partial_failures = True
                                    logger.warning("Preprocess fallback failed; continuing without it: %s", exc3)

                    if isinstance(pre_json, dict):
                        optimized_description = str(pre_json.get("optimized_description") or "").strip() or optimized_description
                        subpoints = pre_json.get("subpoints") or []
                        preferred_search_terms = pre_json.get("preferred_search_terms") or []
                        must_terms = pre_json.get("must_terms") or []
                        should_terms = pre_json.get("should_terms") or []
                        scope_notes = str(pre_json.get("scope_notes") or "").strip()
                        hard_exclusions = pre_json.get("hard_exclusions") or []

                subpoints_block = ""
                if subpoints:
                    lines = []
                    for sp in subpoints:
                        if not isinstance(sp, dict):
                            continue
                        sid = sp.get("id")
                        label = sp.get("label")
                        kws = sp.get("keywords") or []
                        excl = sp.get("exclusions") or []
                        kw_s = ", ".join([str(k) for k in kws[:14] if str(k).strip()])
                        excl_s = ", ".join([str(x) for x in excl[:10] if str(x).strip()])
                        line = f"- ({sid}) {label}".strip()
                        if kw_s:
                            line += f" | keywords: {kw_s}"
                        if excl_s:
                            line += f" | exclusions: {excl_s}"
                        lines.append(line)
                    subpoints_block = "\n".join(lines)
                else:
                    subpoints_block = "- (Allgemein) Keine Unterpunkte erkannt (du kannst sie in der Beschreibung hinzufügen)."

                terms_block = ", ".join([str(x) for x in (preferred_search_terms or []) if str(x).strip()]) if preferred_search_terms else ""
                must_terms_block = ", ".join([str(x) for x in (must_terms or []) if str(x).strip()]) if must_terms else ""
                should_terms_block = ", ".join([str(x) for x in (should_terms or []) if str(x).strip()]) if should_terms else ""
                scope_notes_block = (scope_notes or "").strip()
                excl_block = "\n".join([f"- {x}" for x in hard_exclusions]) if hard_exclusions else ""

                search_query = normalize_whitespace(
                    f"{chapter_title}\n\n{optimized_description}\n\n"
                    f"MUST: {must_terms_block}\n"
                    f"SHOULD: {should_terms_block}\n"
                    f"Preferred: {terms_block}\n\n"
                    f"Scope notes: {scope_notes_block}\n\n"
                    f"Subpoints:\n{subpoints_block}\n\n"
                    f"Exclusions:\n{excl_block}"
                )

                fs.set_progress(
                    user_id=user_id,
                    projekt_id=projekt_id,
                    run_id=run_id,
                    stage="stage0_retrieval",
                    message="Searching vector store for evidence",
                )

                per_pdf = max(1, min(50, int(FILE_SEARCH_MAX_RESULTS_PER_PDF)))
                total = int(per_pdf) * max(1, len(pdf_artifacts))
                if int(total) > 50:
                    total = 50

                search_items = await vector_store_search_items(
                    client,
                    vector_store_id=vector_store_id,
                    query=search_query,
                    max_num_results=int(total),
                    rewrite_query=True,
                )

                file_ids = [a["file_id"] for a in (pdf_artifacts or [])]
                items_by_file: dict[str, list] = {fid: [] for fid in file_ids}

                unknown_items = 0
                for it in search_items:
                    fid = item_file_id(it)
                    if fid and fid in items_by_file:
                        items_by_file[fid].append(it)
                    else:
                        unknown_items += 1
                if unknown_items:
                    had_partial_failures = True

                for fid in list(items_by_file.keys()):
                    items_by_file[fid] = dedup_and_sort(items_by_file.get(fid, []))

                if ENABLE_BALANCED_RETRIEVAL:
                    target = BALANCED_RETRIEVAL_TARGET_HITS_PER_PDF
                    if target is None:
                        target = max(3, min(int(per_pdf), 10))
                    target = max(1, min(50, int(target)))

                    label_by_file_id = {a["file_id"]: a["label"] for a in pdf_artifacts}
                    for fid in file_ids:
                        cur = items_by_file.get(fid, [])
                        if len(cur) >= int(target):
                            continue
                        label = label_by_file_id.get(fid) or fid
                        extra = []
                        last_err = None
                        filter_candidates = [
                            {"type": "eq", "key": "pdf_file_id", "value": fid},
                            {"type": "eq", "key": "file_id", "value": fid},
                            {"type": "eq", "key": "pdf_label", "value": label},
                        ]
                        for flt in filter_candidates:
                            try:
                                extra = await vector_store_search_items(
                                    client,
                                    vector_store_id=vector_store_id,
                                    query=search_query,
                                    max_num_results=int(target),
                                    rewrite_query=True,
                                    filters=flt,
                                )
                                if extra:
                                    break
                            except Exception as e:
                                last_err = e
                                extra = []
                        if not extra and last_err is not None:
                            had_partial_failures = True
                        if extra:
                            items_by_file[fid] = dedup_and_sort(list(cur) + list(extra))

                    if ENABLE_SUBPOINT_TOPUP and subpoints:
                        sp_candidates = []
                        for sp in subpoints:
                            if not isinstance(sp, dict):
                                continue
                            sid = (sp.get("id") or "").strip()
                            if not sid:
                                continue
                            try:
                                imp = float(SUBPOINT_IMPORTANCE.get(sid, 1) or 1)
                            except Exception:
                                imp = 1.0
                            if imp <= 1:
                                continue
                            sp_candidates.append((imp, sid, sp))

                        sp_candidates.sort(key=lambda t: t[0], reverse=True)
                        for imp, sid, sp in sp_candidates[: int(max(0, SUBPOINT_TOPUP_MAX_CALLS))]:
                            kw = sp.get("keywords") or []
                            kw_s = ", ".join([str(k) for k in kw[:14] if str(k).strip()])
                            q = normalize_whitespace(
                                f"""{chapter_title}

Subpoint ({sid}) {(sp.get("label") or "")}

Keywords: {kw_s}

{optimized_description}

MUST: {must_terms_block}
SHOULD: {should_terms_block}
Scope notes: {scope_notes_block}

Exclusions:
{excl_block}
"""
                            )
                            n = int(min(50, max(8, round(8 + 4 * (imp - 1)))))
                            extra_items = await vector_store_search_items(
                                client,
                                vector_store_id=vector_store_id,
                                query=q,
                                max_num_results=int(n),
                                rewrite_query=True,
                            )
                            by_f: dict[str, list] = {}
                            for it in extra_items:
                                fid = item_file_id(it)
                                if fid and fid in items_by_file:
                                    by_f.setdefault(fid, []).append(it)
                            for fid, its in by_f.items():
                                items_by_file[fid] = dedup_and_sort(list(items_by_file.get(fid, [])) + list(its))

                evidence_max_hits_per_pdf = min(12, int(per_pdf))
                evidence_by_file: dict[str, str] = {}
                for a in pdf_artifacts:
                    fid = a["file_id"]
                    evidence_by_file[fid] = build_evidence_from_vector_store_search(
                        items_by_file.get(fid, []),
                        max_hits=int(evidence_max_hits_per_pdf),
                        max_chars_per_hit=1800,
                    )

                fs.set_progress(
                    user_id=user_id,
                    projekt_id=projekt_id,
                    run_id=run_id,
                    stage="stage2_extract",
                    message="Running evidence extractor (Stage 2)",
                    current=0,
                    total=len(pdf_artifacts),
                )

                stage2_model = str(os.getenv("OPENAI_PDF_SCAN_MODEL", "gpt-5-mini") or "gpt-5-mini").strip() or "gpt-5-mini"
                system2 = build_stage2_system_prompt(max_hits=int(MAX_HITS))

                artifact_by_file_id = {a.get("file_id"): a for a in (pdf_artifacts or []) if a.get("file_id")}

                pdf_stage2_outputs: list[dict] = []
                for idx, a in enumerate(pdf_artifacts, start=1):
                    pdf_label = a.get("label")
                    file_id = a.get("file_id")
                    pdf_id = a.get("pdf_id")
                    evidence = evidence_by_file.get(str(file_id), "") if file_id else ""

                    fs.set_progress(
                        user_id=user_id,
                        projekt_id=projekt_id,
                        run_id=run_id,
                        stage="stage2_extract",
                        message=f"Stage 2: {pdf_label}",
                        current=idx,
                        total=len(pdf_artifacts),
                    )

                    if not str(evidence or "").strip():
                        pdf_stage2_outputs.append(
                            {
                                "label": pdf_label,
                                "file_id": file_id,
                                "data": {
                                    "none_found": True,
                                    "primary_found": False,
                                    "diagnostic": {
                                        "reason": "no_evidence",
                                        "best_score": 1,
                                        "notes": "Keine EVIDENCE für dieses PDF.",
                                    },
                                    "results": [],
                                },
                            }
                        )
                        continue

                    user2 = f"""### PDF
Label: {pdf_label}
OpenAI file_id: {file_id}

### Kapitel
Titel: {chapter_title}

### Such-Spezifikation (optimiert)
{optimized_description}

### Must-Terms (Core)
{must_terms_block}

### Should-Terms (Support)
{should_terms_block}

### Scope notes
{scope_notes_block}

### Unterpunkte (für Zuordnung)
{subpoints_block}

### Optionale Keywords/Synonyme
{terms_block}

### Ausschlüsse
{excl_block}

### Aufgabe
Analysiere die EVIDENCE-Auszüge und gib nur wirklich passende Stellen zurück.
Wichtig: Für jeden Treffer muss 'subpoint_scores' befüllt sein (Multi-Subpoint Scoring, siehe System-Regeln).

### EVIDENCE
{evidence}
"""

                    data: dict
                    try:
                        op_id = f"{workflow_id}_qf_pdf_stage2_{pdf_id or file_id}"
                        res = await self._reserve_and_call_json_schema(
                            user_id=user_id,
                            projekt_id=projekt_id,
                            kapitel_id=kapitel_id,
                            research_run_id=run_id,
                            operation_id=str(op_id),
                            operation_type="quellen_finder_pdf_stage2_extract",
                            model=stage2_model,
                            system_message=system2,
                            prompt=user2,
                            schema_name="pdf_findings_evidence",
                            schema=RESULT_SCHEMA,
                            max_output_tokens=int(MAX_OUTPUT_TOKENS),
                            operation_details={
                                "stage": "stage2",
                                "pdfId": str(pdf_id or ""),
                                "pdfLabel": str(pdf_label or ""),
                            },
                            api_key=api_key,
                            key_source=key_source,
                        )
                        data_raw = res.get("data") if isinstance(res, dict) else None
                        if not isinstance(data_raw, dict):
                            raise RuntimeError("Stage 2 returned invalid data shape (expected object).")
                        data = data_raw
                    except Exception as exc:
                        had_partial_failures = True
                        logger.warning("Stage 2 failed for pdf=%s (file_id=%s): %s", pdf_label, file_id, exc)
                        data = {
                            "none_found": True,
                            "primary_found": False,
                            "diagnostic": {
                                "reason": "mixed_or_unclear",
                                "best_score": 1,
                                "notes": (f"Stage2 failed: {exc}"[:280]),
                            },
                            "results": [],
                        }

                    pdf_stage2_outputs.append({"label": pdf_label, "file_id": file_id, "data": data})

                fs.set_progress(
                    user_id=user_id,
                    projekt_id=projekt_id,
                    run_id=run_id,
                    stage="postprocess",
                    message="Validating anchors + filtering (postprocess)",
                )

                pdf_results: list[dict] = []
                for item in pdf_stage2_outputs:
                    label = item.get("label")
                    file_id = item.get("file_id")
                    evidence = evidence_by_file.get(str(file_id), "") if file_id else ""
                    data = item.get("data") if isinstance(item.get("data"), dict) else {}

                    out = postprocess_and_filter(data, evidence, max_hits=int(MAX_HITS))
                    artifact = artifact_by_file_id.get(file_id) or {}
                    pdf_results.append(
                        {
                            "label": label,
                            "file_id": file_id,
                            "pdf_id": artifact.get("pdf_id"),
                            "path": artifact.get("path") or "",
                            "clean_data": out.get("clean_data") if isinstance(out, dict) else {},
                            "keep_debug": out.get("keep_debug") if isinstance(out, dict) else [],
                            "stats": out.get("stats") if isinstance(out, dict) else {},
                        }
                    )

                curated: dict | None = None
                if ENABLE_STAGE3_CURATION:
                    fs.set_progress(
                        user_id=user_id,
                        projekt_id=projekt_id,
                        run_id=run_id,
                        stage="stage3_curate",
                        message="Curating unique PDF sections (Stage 3)",
                    )
                    try:
                        curated = curate_pdf_sections(
                            pdf_results=pdf_results,
                            subpoints=subpoints,
                            subpoint_importance=SUBPOINT_IMPORTANCE,
                            soft_total_sections_target=SOFT_TOTAL_SECTIONS_TARGET,
                            hard_max_selected_sections=int(HARD_MAX_SELECTED_SECTIONS),
                        )
                    except Exception as exc:
                        had_partial_failures = True
                        curated = None
                        logger.warning("Stage 3 curation failed (continuing with Stage 2 only): %s", exc, exc_info=True)

                fs.set_progress(
                    user_id=user_id,
                    projekt_id=projekt_id,
                    run_id=run_id,
                    stage="write_results",
                    message="Saving Stage 2 + Stage 3 results to database",
                )

                fs.clear_subcollection(user_id=user_id, projekt_id=projekt_id, run_id=run_id, name="pdfStage2")
                fs.clear_subcollection(user_id=user_id, projekt_id=projekt_id, run_id=run_id, name="pdfStage3")

                def _as_str(v: Any) -> str | None:
                    if v is None:
                        return None
                    try:
                        s = str(v).strip()
                    except Exception:
                        return None
                    return s or None

                stage2_docs: list[tuple[str, dict]] = []
                stage2_count = 0
                for pdf in pdf_results:
                    pdf_id = _as_str(pdf.get("pdf_id"))
                    file_id = _as_str(pdf.get("file_id"))
                    if not pdf_id:
                        had_partial_failures = True
                        continue
                    pdf_label = _as_str(pdf.get("label")) or pdf_id
                    pdf_diag = (pdf.get("clean_data") or {}).get("diagnostic") if isinstance(pdf.get("clean_data"), dict) else None
                    pdf_stats = pdf.get("stats") if isinstance(pdf.get("stats"), dict) else None
                    keep_debug = pdf.get("keep_debug") if isinstance(pdf.get("keep_debug"), list) else []
                    for hit_idx, hit in enumerate(keep_debug, start=1):
                        if not isinstance(hit, dict):
                            had_partial_failures = True
                            continue
                        doc_id = f"{pdf_id}_{hit_idx:02d}"
                        try:
                            score = int(hit.get("score_1_to_10", 0) or 0)
                        except Exception:
                            score = 0
                        subpoint_scores_map: dict[str, int] = {}
                        for sp in hit.get("subpoint_scores") or []:
                            if not isinstance(sp, dict):
                                continue
                            spid = _as_str(sp.get("subpoint"))
                            if not spid:
                                continue
                            try:
                                sp_sc = int(sp.get("score_1_to_10", 0) or 0)
                            except Exception:
                                sp_sc = 0
                            subpoint_scores_map[spid] = int(max(1, min(10, sp_sc)))

                        stage2_docs.append(
                            (
                                doc_id,
                                {
                                    "pdfId": pdf_id,
                                    "pdfLabel": pdf_label,
                                    "pdfFileId": file_id,
                                    "subpoint": _as_str(hit.get("subpoint")) or "(Allgemein)",
                                    "tier": _as_str(hit.get("tier")),
                                    "score": (None if score <= 0 else int(score)),
                                    "anchor": _as_str(hit.get("anchor")),
                                    "anchorAlt": _as_str(hit.get("anchor_alt")),
                                    "locatorHint": _as_str(hit.get("locator_hint")),
                                    "coverage": _as_str(hit.get("coverage")),
                                    "summary": _as_str(hit.get("summary")),
                                    "scoreRationale": _as_str(hit.get("score_rationale")),
                                    "subpointScores": subpoint_scores_map or None,
                                    "diagnostics": {
                                        "anchorOk": bool(hit.get("_anchor_ok")),
                                        "anchorReason": _as_str(hit.get("_anchor_reason")),
                                        "anchorAltOk": bool(hit.get("_anchor_alt_ok")),
                                        "anchorAltReason": _as_str(hit.get("_anchor_alt_reason")),
                                        "pdfDiagnostic": pdf_diag,
                                        "pdfStats": pdf_stats,
                                    },
                                    "createdAt": SERVER_TIMESTAMP,
                                },
                            )
                        )
                        stage2_count += 1

                stage3_docs: list[tuple[str, dict]] = []
                stage3_count = 0
                if isinstance(curated, dict):
                    selected_sections = curated.get("selected_sections") or []
                    for sec_idx, sec in enumerate(selected_sections, start=1):
                        if not isinstance(sec, dict):
                            had_partial_failures = True
                            continue
                        pdf_file_id = _as_str(sec.get("pdf_file_id"))
                        if not pdf_file_id:
                            had_partial_failures = True
                            continue
                        artifact = artifact_by_file_id.get(pdf_file_id) or {}
                        pdf_id = _as_str(artifact.get("pdf_id"))
                        if not pdf_id:
                            had_partial_failures = True
                            continue

                        covers = sec.get("covers") or []
                        covered_subpoints: list[str] = []
                        best_score = 0
                        for c in covers:
                            if not isinstance(c, dict):
                                continue
                            spid = _as_str(c.get("subpoint"))
                            if spid:
                                covered_subpoints.append(spid)
                            try:
                                sc = int(c.get("score_1_to_10", 0) or 0)
                            except Exception:
                                sc = 0
                            best_score = max(best_score, int(sc))

                        sec_sanitized = {k: v for k, v in sec.items() if k not in {"pdf_path"}}

                        stage3_docs.append(
                            (
                                f"{sec_idx:02d}",
                                {
                                    "pdfId": pdf_id,
                                    "pdfLabel": _as_str(sec.get("pdf_label")) or _as_str(artifact.get("label")) or pdf_id,
                                    "pdfFileId": pdf_file_id,
                                    "heading": _as_str(sec.get("pdf_heading")),
                                    "headingMethod": _as_str(sec.get("pdf_heading_method")),
                                    "anchorPage": sec.get("anchor_page"),
                                    "hitCount": sec.get("hit_count"),
                                    "anchor": _as_str(sec.get("representative_anchor")),
                                    "anchorAlt": _as_str(sec.get("representative_anchor_alt")),
                                    "summary": _as_str(sec.get("representative_summary")),
                                    "coveredSubpoints": covered_subpoints or None,
                                    "score": (None if best_score <= 0 else int(best_score)),
                                    "diagnostics": {"covers": covers, "raw": sec_sanitized},
                                    "createdAt": SERVER_TIMESTAMP,
                                },
                            )
                        )
                        stage3_count += 1

                if stage2_docs:
                    fs.write_subcollection_docs(
                        user_id=user_id,
                        projekt_id=projekt_id,
                        run_id=run_id,
                        name="pdfStage2",
                        docs=stage2_docs,
                    )
                if stage3_docs:
                    fs.write_subcollection_docs(
                        user_id=user_id,
                        projekt_id=projekt_id,
                        run_id=run_id,
                        name="pdfStage3",
                        docs=stage3_docs,
                    )

                fs.mark_success(
                    user_id=user_id,
                    projekt_id=projekt_id,
                    run_id=run_id,
                    had_partial_failures=had_partial_failures,
                    extra={
                        "resultCount": int(stage2_count),
                        "stage2Count": int(stage2_count),
                        "stage3Count": int(stage3_count),
                    },
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
            logger.error("Quellen-Finder PDF scan failed (run_id=%s): %s", run_id, exc, exc_info=True)
            logger.debug("Traceback:\n%s", traceback.format_exc())
            fs.mark_error(
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                error_message=str(exc),
                had_partial_failures=had_partial_failures,
            )
        finally:
            cleanup_errors: list[str] = []
            if vector_store_id:
                try:
                    await client.vector_stores.delete(vector_store_id)
                except Exception as exc:
                    cleanup_errors.append(f"vector_store_delete:{exc}")
            for fid in openai_file_ids:
                try:
                    await client.files.delete(fid)
                except Exception as exc:
                    cleanup_errors.append(f"file_delete:{fid}:{exc}")

            if cleanup_errors:
                self.firebase.db.collection("users").document(user_id).collection("projects").document(projekt_id).collection("researchRuns").document(run_id).set(
                    {"cleanupErrors": cleanup_errors[:50], "hadPartialFailures": True, "updatedAt": SERVER_TIMESTAMP},
                    merge=True,
                )


async def run_quellen_finder_pdf_scan_job(
    *,
    user_id: str,
    projekt_id: str,
    kapitel_id: str,
    run_id: str,
    pdf_ids: list[str],
    preprocess: bool,
) -> None:
    """
    Background task wrapper for Quellen-Finder PDF scan.

    Intended to be scheduled via FastAPI BackgroundTasks.
    """
    job = QuellenFinderPdfScanJob()
    await job.run(
        user_id=user_id,
        projekt_id=projekt_id,
        kapitel_id=kapitel_id,
        run_id=run_id,
        pdf_ids=pdf_ids,
        preprocess=preprocess,
    )
