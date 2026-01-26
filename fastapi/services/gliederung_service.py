from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any, Optional

from fastapi import HTTPException
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.cost_service import TokenUsage, get_cost_service
from services.firebase_service import firebase_service
from services.openai_budget_service import get_openai_budget_service
from services.openai_estimation_service import get_openai_estimation_service
from services.openai_service import OpenAIService
from services.prompt_service import prompt_service, GLIEDERUNG_DEFAULT_V2_SYSTEM_PROMPT
from services.user_key_service import user_key_service
from utils.prompt_dumps import dump_prompt_markdown

logger = logging.getLogger(__name__)


GLIEDERUNG_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "kapitel": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nummer": {"type": "string"},
                    "titel": {"type": "string"},
                    "beschreibung": {"type": "string"},
                    "seitenumfang": {"type": "string"},
                    "relevanteStudienbriefKapitel": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "nummer": {"type": "string"},
                                "titel": {"type": "string"},
                                "label": {
                                    "type": "string",
                                    "enum": ["Hauptquelle", "Ergänzend", "Nur knapp"],
                                },
                            },
                            "required": ["nummer", "titel", "label"],
                            "additionalProperties": False,
                        },
                    },
                    "externeQuellenErforderlich": {"type": "boolean"},
                },
                "required": [
                    "nummer",
                    "titel",
                    "beschreibung",
                    "seitenumfang",
                    "relevanteStudienbriefKapitel",
                    "externeQuellenErforderlich",
                ],
                "additionalProperties": False,
            },
        },
        "kurzbegruendung": {"type": "array", "items": {"type": "string"}},
        "verwendeteStudienbriefKapitelUnique": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"nummer": {"type": "string"}, "titel": {"type": "string"}},
                "required": ["nummer", "titel"],
                "additionalProperties": False,
            },
        },
        "annahmen": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "kapitel",
        "kurzbegruendung",
        "verwendeteStudienbriefKapitelUnique",
        "annahmen",
    ],
    "additionalProperties": False,
}


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


def _prompt_cache_kwargs(model: str) -> dict:
    model = (model or "").strip()
    if model in {"gpt-5.1", "gpt-5.2"}:
        return {"extra_body": {"prompt_cache_retention": "24h"}}
    return {}


def _output_for_model(output: Any) -> dict:
    """
    Convert a stored draft output (UI-normalized) into the schema shape expected by the model.
    Strips UI-only fields like `id` and `reviewed`.
    """
    if not isinstance(output, dict):
        return {
            "kapitel": [],
            "kurzbegruendung": [],
            "verwendeteStudienbriefKapitelUnique": [],
            "annahmen": [],
        }

    chapters_in = output.get("kapitel") or []
    chapters_out: list[dict] = []
    if isinstance(chapters_in, list):
        for ch in chapters_in:
            if not isinstance(ch, dict):
                continue
            chapters_out.append(
                {
                    "nummer": str(ch.get("nummer") or "").strip(),
                    "titel": str(ch.get("titel") or "").strip(),
                    "beschreibung": str(ch.get("beschreibung") or "").strip(),
                    "seitenumfang": str(ch.get("seitenumfang") or "").strip(),
                    "relevanteStudienbriefKapitel": [
                        {
                            "nummer": str((k or {}).get("nummer") or "").strip(),
                            "titel": str((k or {}).get("titel") or "").strip(),
                            "label": str((k or {}).get("label") or "").strip(),
                        }
                        for k in (ch.get("relevanteStudienbriefKapitel") or [])
                        if isinstance(k, dict)
                    ],
                    "externeQuellenErforderlich": bool(
                        ch.get("externeQuellenErforderlich") is True
                    ),
                }
            )

    kurz = output.get("kurzbegruendung") or []
    used = output.get("verwendeteStudienbriefKapitelUnique") or []
    ann = output.get("annahmen") or []

    return {
        "kapitel": chapters_out,
        "kurzbegruendung": [str(x).strip() for x in kurz if isinstance(x, str) and x.strip()],
        "verwendeteStudienbriefKapitelUnique": [
            {
                "nummer": str((k or {}).get("nummer") or "").strip(),
                "titel": str((k or {}).get("titel") or "").strip(),
            }
            for k in used
            if isinstance(k, dict)
        ],
        "annahmen": [str(x).strip() for x in ann if isinstance(x, str) and x.strip()],
    }


def _build_refinement_prompt(
    *, base_user_message: str, current_output: dict, new_user_message: str
) -> str:
    blocks: list[str] = []
    blocks.append("Erste User Message:\n" + (base_user_message or "").strip())
    blocks.append(
        "First Generated Text:\n"
        + json.dumps(current_output or {}, ensure_ascii=False, indent=2).strip()
    )
    blocks.append("Aktuelle Nutzeranweisung:\n" + (new_user_message or "").strip())
    blocks.append("Gib ausschließlich gültiges JSON im vorgegebenen Schema aus.")
    return ("\n\n".join(blocks)).strip() + "\n"


@dataclass(frozen=True)
class GliederungGenerationResult:
    data: dict
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    model: str


class GliederungService:
    def __init__(self):
        self.openai = OpenAIService()

    def _draft_ref(self, user_id: str, draft_id: str):
        return (
            firebase_service.db.collection("users")
            .document(user_id)
            .collection("gliederungDrafts")
            .document(draft_id)
        )

    async def create_draft_placeholder(
        self,
        *,
        user_id: str,
        projekt_id: str,
        model: str,
        prompt_template_id: str,
        aufgabenstellung: str,
        gliederung_studienbrief_mit_seiten: str,
        extra_kontext: str,
    ) -> str:
        draft_ref = (
            firebase_service.db.collection("users")
            .document(user_id)
            .collection("gliederungDrafts")
            .document()
        )

        draft_ref.set(
            {
                "projektId": projekt_id,
                "status": "running",
                "errorMessage": None,
                "model": model,
                "promptTemplateId": prompt_template_id,
                "inputs": {
                    "aufgabenstellung": aufgabenstellung,
                    "gliederungStudienbriefMitSeiten": gliederung_studienbrief_mit_seiten,
                    "extraKontext": extra_kontext,
                },
                "output": None,
                "rootId": draft_ref.id,
                "version": 1,
                "archived": False,
                "createdAt": SERVER_TIMESTAMP,
                "updatedAt": SERVER_TIMESTAMP,
            }
        )
        return draft_ref.id

    async def _call_openai(
        self,
        *,
        stage: str,
        model: str,
        system_message: str,
        instructions: str,
        api_key: Optional[str],
    ) -> GliederungGenerationResult:
        client = self.openai._get_client(api_key)  # pylint: disable=protected-access

        dump_prompt_markdown(
            stage=(stage or "gliederung").strip() or "gliederung",
            model=model,
            sections=[
                ("System Prompt", system_message),
                ("Instructions", instructions),
            ],
        )

        resp = await client.responses.create(
            model=model,
            service_tier="default",
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_message}],
                },
                {"role": "user", "content": [{"type": "input_text", "text": instructions}]},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "gliederung_draft",
                    "schema": GLIEDERUNG_JSON_SCHEMA,
                    "strict": True,
                }
            },
            reasoning={"effort": "high"},
            max_output_tokens=None,
            store=False,
            **_prompt_cache_kwargs(model),
        )

        raw = _extract_text_from_response(resp).strip()
        if not raw:
            raise RuntimeError("Model returned no parsable output text (empty).")

        try:
            data = json.loads(raw)
        except JSONDecodeError as exc:
            logger.error("Failed to parse Gliederung JSON. raw_head=%r", raw[:200])
            raise RuntimeError("Failed to parse Gliederung JSON.") from exc

        usage = getattr(resp, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
        cached_input_tokens = 0
        details = getattr(usage, "input_tokens_details", None) if usage else None
        if details is not None:
            cached_input_tokens = int(getattr(details, "cached_tokens", 0) or 0)

        return GliederungGenerationResult(
            data=data,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            model=str(getattr(resp, "model", None) or model),
        )

    def _normalize_output(self, data: dict) -> dict:
        chapters = data.get("kapitel") or []
        out_chapters = []
        for ch in chapters:
            if not isinstance(ch, dict):
                continue
            out_chapters.append(
                {
                    "id": uuid.uuid4().hex,
                    "reviewed": False,
                    "nummer": str(ch.get("nummer") or "").strip(),
                    "titel": str(ch.get("titel") or "").strip(),
                    "beschreibung": str(ch.get("beschreibung") or "").strip(),
                    "seitenumfang": str(ch.get("seitenumfang") or "").strip(),
                    "relevanteStudienbriefKapitel": [
                        {
                            "nummer": str((k or {}).get("nummer") or "").strip(),
                            "titel": str((k or {}).get("titel") or "").strip(),
                            "label": str((k or {}).get("label") or "").strip(),
                        }
                        for k in (ch.get("relevanteStudienbriefKapitel") or [])
                        if isinstance(k, dict)
                    ],
                    "externeQuellenErforderlich": bool(
                        ch.get("externeQuellenErforderlich") is True
                    ),
                }
            )

        return {
            "kapitel": out_chapters,
            "kurzbegruendung": [
                str(x).strip()
                for x in (data.get("kurzbegruendung") or [])
                if isinstance(x, str) and x.strip()
            ],
            "verwendeteStudienbriefKapitelUnique": [
                {
                    "nummer": str((k or {}).get("nummer") or "").strip(),
                    "titel": str((k or {}).get("titel") or "").strip(),
                }
                for k in (data.get("verwendeteStudienbriefKapitelUnique") or [])
                if isinstance(k, dict)
            ],
            "annahmen": [
                str(x).strip()
                for x in (data.get("annahmen") or [])
                if isinstance(x, str) and x.strip()
            ],
        }

    async def generate_draft(self, *, user_id: str, draft_id: str) -> None:
        draft_ref = self._draft_ref(user_id, draft_id)
        draft_snap = draft_ref.get()
        if not draft_snap.exists:
            return

        draft = draft_snap.to_dict() or {}
        if (draft.get("status") or "").strip() != "running":
            return

        projekt_id = str(draft.get("projektId") or "").strip()
        prompt_template_id = str(draft.get("promptTemplateId") or "").strip() or "default_v2"
        model = str(draft.get("model") or "").strip() or "gpt-5.2"
        inputs = draft.get("inputs") if isinstance(draft.get("inputs"), dict) else {}

        aufgabenstellung = str((inputs or {}).get("aufgabenstellung") or "").strip()
        studienbrief = str((inputs or {}).get("gliederungStudienbriefMitSeiten") or "").strip()
        extra_kontext = str((inputs or {}).get("extraKontext") or "").strip()

        if not projekt_id:
            draft_ref.set(
                {
                    "status": "error",
                    "errorMessage": "projektId fehlt.",
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )
            return

        payload = {
            "AUFGABENSTELLUNG": aufgabenstellung,
            "GLIEDERUNG_STUDIENBRIEF_MIT_SEITEN": studienbrief,
            "EXTRA_KONTEXT": extra_kontext,
        }

        api_key: Optional[str] = None
        key_source: Optional[str] = None
        reservation_released = False

        try:
            api_key, key_source = await user_key_service.resolve_api_key_for_user(
                user_id
            )

            instructions = await prompt_service.get_rendered_instructions_for_template(
                user_id,
                "gliederung",
                prompt_template_id,
                payload,
            )
            system_prompt = await prompt_service.get_system_prompt_for_template(
                stage="gliederung",
                template_id=prompt_template_id,
            )
            system_message = (
                (system_prompt or "").strip() or GLIEDERUNG_DEFAULT_V2_SYSTEM_PROMPT
            )

            workflow_id = uuid.uuid4().hex
            operation_id = f"{workflow_id}_gliederung_{draft_id}"

            estimation_service = get_openai_estimation_service(firebase_service)
            output_source_text = "\n\n".join([aufgabenstellung, studienbrief, extra_kontext]).strip()
            if not output_source_text:
                output_source_text = aufgabenstellung

            estimate_obj = await estimation_service.estimate_operation(
                user_id=user_id,
                operation_type="gliederung",
                model=model,
                system_text=system_message,
                user_text=instructions,
                output_source_text=output_source_text,
            )

            budget_service = get_openai_budget_service(firebase_service)
            reservation = await budget_service.reserve_operation(
                user_id=user_id,
                operation_id=operation_id,
                operation_type="gliederung",
                user_action_id=draft_id,
                estimate=estimate_obj.to_dict(),
                projekt_id=projekt_id,
                operation_details={"draftId": draft_id},
            )
            if reservation.result == "blocked":
                draft_ref.set(
                    {
                        "status": "error",
                        "errorMessage": "Nicht genügend Credits verfügbar. Bitte lade Credits im Profil unter Billing auf.",
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                    merge=True,
                )
                return

            if reservation.result in {"already_reserved", "finalized"}:
                draft_ref.set(
                    {
                        "status": "error",
                        "errorMessage": "Operation bereits gestartet. Bitte später erneut versuchen.",
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                    merge=True,
                )
                return

            await budget_service.mark_running(user_id=user_id, operation_id=operation_id)

            try:
                openai_result = await self._call_openai(
                    stage="gliederung",
                    model=model,
                    system_message=system_message,
                    instructions=instructions,
                    api_key=api_key,
                )
            except Exception as exc:
                await budget_service.mark_status(
                    user_id=user_id,
                    operation_id=operation_id,
                    status="error",
                    error_message=str(exc),
                )
                await budget_service.release_reservation(
                    user_id=user_id, operation_id=operation_id, reason="error"
                )
                reservation_released = True
                raise

            normalized = self._normalize_output(openai_result.data)

            # Cost metrics + credits debit (critical)
            cost_service = get_cost_service(firebase_service)
            usage = TokenUsage.from_any(
                openai_result.input_tokens,
                openai_result.cached_input_tokens,
                openai_result.output_tokens,
            )
            cost_breakdown, matched_model, pricing, _match_type = await cost_service.calculate_cost(
                model=openai_result.model or model,
                usage=usage,
            )

            projekt_snapshot = None
            try:
                proj = await firebase_service.get_project(user_id, projekt_id)
                if proj:
                    projekt_snapshot = {
                        "id": projekt_id,
                        "name": proj.get("name"),
                        "archived": bool(proj.get("archived", False)),
                    }
            except Exception:
                projekt_snapshot = None

            await cost_service.log_operation(
                operation_id=operation_id,
                operation_type="gliederung",
                user_id=user_id,
                user_action_id=draft_id,
                operation_details={"draftId": draft_id},
                model=openai_result.model or model,
                usage=usage,
                cost_breakdown=cost_breakdown,
                matched_model_key=matched_model,
                pricing=pricing,
                key_source=key_source or "unknown",
                projekt_id=projekt_id,
                projekt_snapshot=projekt_snapshot,
            )

            await budget_service.release_reservation(
                user_id=user_id, operation_id=operation_id, reason="success"
            )
            reservation_released = True

            draft_ref.set(
                {
                    "status": "success",
                    "errorMessage": None,
                    "output": normalized,
                    "usage": {
                        "inputTokens": int(usage.input_tokens),
                        "cachedInputTokens": int(usage.cached_input_tokens),
                        "outputTokens": int(usage.output_tokens),
                        "totalTokens": int(usage.total_tokens),
                    },
                    "costUsd": float(cost_breakdown.total_cost_usd),
                    "operationId": operation_id,
                    "keySource": key_source,
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(
                "Gliederung draft generation failed (user=%s draft=%s): %s",
                user_id,
                draft_id,
                exc,
                exc_info=True,
            )

            try:
                if (
                    "budget_service" in locals()
                    and not reservation_released
                    and "operation_id" in locals()
                ):
                    await budget_service.mark_status(
                        user_id=user_id,
                        operation_id=operation_id,
                        status="error",
                        error_message=str(exc),
                    )
                    await budget_service.release_reservation(
                        user_id=user_id, operation_id=operation_id, reason="error"
                    )
            except Exception:
                pass

            try:
                draft_ref.set(
                    {
                        "status": "error",
                        "errorMessage": str(exc)[:1000] if exc else "Unbekannter Fehler",
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                    merge=True,
                )
            except Exception:
                pass

    async def refine_draft(self, *, user_id: str, draft_id: str, user_message: str) -> None:
        """
        Refine an existing Gliederung draft output using a new user instruction.

        Expects the draft to be marked as status=running before this executes.
        """
        draft_ref = self._draft_ref(user_id, draft_id)
        draft_snap = draft_ref.get()
        if not draft_snap.exists:
            return

        draft = draft_snap.to_dict() or {}
        if (draft.get("status") or "").strip() != "running":
            return

        projekt_id = str(draft.get("projektId") or "").strip()
        prompt_template_id = str(draft.get("promptTemplateId") or "").strip() or "default_v2"
        model = str(draft.get("model") or "").strip() or "gpt-5.2"
        inputs = draft.get("inputs") if isinstance(draft.get("inputs"), dict) else {}
        output_saved = draft.get("output") if isinstance(draft.get("output"), dict) else None

        if not projekt_id:
            draft_ref.set(
                {
                    "status": "error",
                    "errorMessage": "projektId fehlt.",
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )
            return

        if not isinstance(output_saved, dict):
            draft_ref.set(
                {
                    "status": "error",
                    "errorMessage": "Entwurf enthält kein Output zum Verfeinern.",
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )
            return

        aufgabenstellung = str((inputs or {}).get("aufgabenstellung") or "").strip()
        studienbrief = str((inputs or {}).get("gliederungStudienbriefMitSeiten") or "").strip()
        extra_kontext = str((inputs or {}).get("extraKontext") or "").strip()

        payload = {
            "AUFGABENSTELLUNG": aufgabenstellung,
            "GLIEDERUNG_STUDIENBRIEF_MIT_SEITEN": studienbrief,
            "EXTRA_KONTEXT": extra_kontext,
        }

        api_key: Optional[str] = None
        key_source: Optional[str] = None
        reservation_released = False

        try:
            api_key, key_source = await user_key_service.resolve_api_key_for_user(user_id)

            base_instructions = await prompt_service.get_rendered_instructions_for_template(
                user_id,
                "gliederung",
                prompt_template_id,
                payload,
            )
            system_prompt = await prompt_service.get_system_prompt_for_template(
                stage="gliederung",
                template_id=prompt_template_id,
            )
            system_message = (system_prompt or "").strip() or GLIEDERUNG_DEFAULT_V2_SYSTEM_PROMPT

            current_output = _output_for_model(output_saved)
            refinement_instructions = _build_refinement_prompt(
                base_user_message=base_instructions,
                current_output=current_output,
                new_user_message=user_message,
            )

            workflow_id = uuid.uuid4().hex
            operation_id = f"{workflow_id}_refine_gliederung_{draft_id}"

            estimation_service = get_openai_estimation_service(firebase_service)
            parent_text = json.dumps(current_output or {}, ensure_ascii=False)
            estimate_obj = await estimation_service.estimate_operation(
                user_id=user_id,
                operation_type="refine_gliederung",
                model=model,
                system_text=system_message,
                user_text=refinement_instructions,
                parent_generated_text=parent_text,
            )

            budget_service = get_openai_budget_service(firebase_service)
            reservation = await budget_service.reserve_operation(
                user_id=user_id,
                operation_id=operation_id,
                operation_type="refine_gliederung",
                user_action_id=draft_id,
                estimate=estimate_obj.to_dict(),
                projekt_id=projekt_id,
                operation_details={"draftId": draft_id},
            )
            if reservation.result == "blocked":
                draft_ref.set(
                    {
                        "status": "error",
                        "errorMessage": "Nicht genügend Credits verfügbar. Bitte lade Credits im Profil unter Billing auf.",
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                    merge=True,
                )
                return

            if reservation.result in {"already_reserved", "finalized"}:
                draft_ref.set(
                    {
                        "status": "error",
                        "errorMessage": "Operation bereits gestartet. Bitte später erneut versuchen.",
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                    merge=True,
                )
                return

            await budget_service.mark_running(user_id=user_id, operation_id=operation_id)

            try:
                openai_result = await self._call_openai(
                    stage="gliederung_refine",
                    model=model,
                    system_message=system_message,
                    instructions=refinement_instructions,
                    api_key=api_key,
                )
            except Exception as exc:
                await budget_service.mark_status(
                    user_id=user_id,
                    operation_id=operation_id,
                    status="error",
                    error_message=str(exc),
                )
                await budget_service.release_reservation(
                    user_id=user_id, operation_id=operation_id, reason="error"
                )
                reservation_released = True
                raise

            normalized = self._normalize_output(openai_result.data)

            cost_service = get_cost_service(firebase_service)
            usage = TokenUsage.from_any(
                openai_result.input_tokens,
                openai_result.cached_input_tokens,
                openai_result.output_tokens,
            )
            cost_breakdown, matched_model, pricing, _match_type = await cost_service.calculate_cost(
                model=openai_result.model or model,
                usage=usage,
            )

            projekt_snapshot = None
            try:
                proj = await firebase_service.get_project(user_id, projekt_id)
                if proj:
                    projekt_snapshot = {
                        "id": projekt_id,
                        "name": proj.get("name"),
                        "archived": bool(proj.get("archived", False)),
                    }
            except Exception:
                projekt_snapshot = None

            await cost_service.log_operation(
                operation_id=operation_id,
                operation_type="refine_gliederung",
                user_id=user_id,
                user_action_id=draft_id,
                operation_details={"draftId": draft_id},
                model=openai_result.model or model,
                usage=usage,
                cost_breakdown=cost_breakdown,
                matched_model_key=matched_model,
                pricing=pricing,
                key_source=key_source or "unknown",
                projekt_id=projekt_id,
                projekt_snapshot=projekt_snapshot,
            )

            await budget_service.release_reservation(
                user_id=user_id, operation_id=operation_id, reason="success"
            )
            reservation_released = True

            draft_ref.set(
                {
                    "status": "success",
                    "errorMessage": None,
                    "output": normalized,
                    "usage": {
                        "inputTokens": int(usage.input_tokens),
                        "cachedInputTokens": int(usage.cached_input_tokens),
                        "outputTokens": int(usage.output_tokens),
                        "totalTokens": int(usage.total_tokens),
                    },
                    "costUsd": float(cost_breakdown.total_cost_usd),
                    "operationId": operation_id,
                    "keySource": key_source,
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )
        except Exception as exc:
            logger.error(
                "Gliederung draft refinement failed (user=%s draft=%s): %s",
                user_id,
                draft_id,
                exc,
                exc_info=True,
            )

            try:
                if (
                    "budget_service" in locals()
                    and not reservation_released
                    and "operation_id" in locals()
                ):
                    await budget_service.mark_status(
                        user_id=user_id,
                        operation_id=operation_id,
                        status="error",
                        error_message=str(exc),
                    )
                    await budget_service.release_reservation(
                        user_id=user_id, operation_id=operation_id, reason="error"
                    )
            except Exception:
                pass

            try:
                draft_ref.set(
                    {
                        "status": "error",
                        "errorMessage": str(exc)[:1000] if exc else "Unbekannter Fehler",
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                    merge=True,
                )
            except Exception:
                pass


gliederung_service = GliederungService()
