import logging
import asyncio
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.firebase_service import firebase_service, AI_GENERIC_ERROR_MESSAGE
from services.ai_router import get_ai_service
from services.prompt_service import prompt_service
from services.cost_service import get_cost_service, TokenUsage
from services.openai_budget_service import get_openai_budget_service
from services.openai_estimation_service import get_openai_estimation_service
from services.shorten_service import shorten_service
from services.user_key_service import user_key_service
from utils.config import config
from utils.openai_models import is_claude_model, normalize_forward_text_model
from utils.quellen_zitat import resolve_quelle_zitat_value

logger = logging.getLogger(__name__)

REFINEMENT_SYSTEM_PROMPT = (
    "Mache die änderungen die von der -Aktuelle Nutzeranweisung- verlangt werden "
    "an dem neuesten -Generated Text-."
)

_ORDINAL_EN = {
    1: "First",
    2: "Second",
    3: "Third",
    4: "Fourth",
    5: "Fifth",
    6: "Sixth",
    7: "Seventh",
    8: "Eighth",
    9: "Ninth",
    10: "Tenth",
}


def _ordinal_en(n: int) -> str:
    return _ORDINAL_EN.get(n, str(n))


class RefinementService:
    """Text refinement flow service (phase 1+: combined + shortened + lesefluss + per-result texts)."""

    def __init__(self) -> None:
        pass

    async def _resolve_api_key_for_model(
        self, user_id: str, model: str
    ) -> tuple[str, str]:
        provider = "anthropic" if is_claude_model(model) else "openai"
        return await user_key_service.resolve_api_key_for_user(
            user_id, provider=provider
        )

    async def _generate_refinement_text(
        self,
        *,
        prompt_body: str,
        model: str,
        api_key: str,
        debug_prompt_dump_path: str | None,
        stage: str,
    ) -> dict:
        return await get_ai_service(model).generate_text(
            prompt_body,
            model,
            api_key=api_key,
            debug_prompt_dump_path=debug_prompt_dump_path,
            system_prompt=REFINEMENT_SYSTEM_PROMPT,
            stage=stage,
        )

    def _normalize_manual_refinement_content(self, content: str) -> str:
        text = str(content or "").replace("\r\n", "\n").replace("\r", "\n")
        if not text.strip():
            raise ValueError("Manual edit content is empty.")
        if len(text) > 140000:
            raise ValueError("Manual edit content is too long.")
        return text

    def _build_manual_refinement_version(
        self, *, parent: dict, content: str
    ) -> tuple[str, dict]:
        version_id = str(uuid4())
        parent_depth = int((parent or {}).get("depth") or 0)
        parent_usage = (parent or {}).get("usage")
        usage = parent_usage if isinstance(parent_usage, dict) else {}
        version_data = {
            "parentVersionId": (parent or {}).get("id") or "root",
            "depth": parent_depth + 1,
            "userMessage": "Manuelle Bearbeitung",
            "assistantText": content,
            "hasContent": True,
            "status": "success",
            "model": (parent or {}).get("model") or "",
            "usage": {
                "inputTokens": 0,
                "cachedInputTokens": 0,
                "outputTokens": 0,
                "reasoningTokens": 0,
                "totalTokens": 0,
            },
            "costUsd": 0.0,
            "keySource": "manual",
            "source": "manual",
            "manualEdit": True,
            "createdAt": SERVER_TIMESTAMP,
            "updatedAt": SERVER_TIMESTAMP,
            "baseUsage": {
                "inputTokens": int(usage.get("inputTokens", 0) or 0),
                "cachedInputTokens": int(usage.get("cachedInputTokens", 0) or 0),
                "outputTokens": int(usage.get("outputTokens", 0) or 0),
                "reasoningTokens": int(usage.get("reasoningTokens", 0) or 0),
                "totalTokens": int(usage.get("totalTokens", 0) or 0),
            },
        }
        return version_id, version_data

    def _validate_manual_parent(self, parent: dict | None) -> dict:
        if not parent:
            raise ValueError("Parent version not found.")
        if str(parent.get("status") or "success") != "success":
            raise ValueError("Only successful versions can be manually edited.")
        if not str(parent.get("assistantText") or "").strip():
            raise ValueError("Parent text is empty.")
        return parent

    def _build_refinement_conversation_prompt(
        self,
        *,
        base_user_message: str,
        history_path: list[dict],
        new_user_message: str,
    ) -> str:
        """
        Build a single long user prompt for refinement.

        Order:
        - Erste User Message: (the original stage prompt that generated the root text)
        - First Generated Text: (root output)
        - Second/Third/... User Message + Generated Text: (prior refinements)
        - Aktuelle Nutzeranweisung: (the new instruction for this refinement call)
        """
        blocks: list[str] = []

        blocks.append("Erste User Message:\n" + (base_user_message or "").strip())

        root_text = ""
        if history_path:
            root_text = (history_path[0].get("assistantText") or "").strip()
        blocks.append("First Generated Text:\n" + root_text)

        # Subsequent refinement iterations (already executed)
        for idx, v in enumerate(history_path[1:], start=2):
            ordinal = _ordinal_en(idx)
            blocks.append(
                f"{ordinal} User Message:\n" + ((v.get("userMessage") or "").strip())
            )
            blocks.append(
                f"{ordinal} Generated Text:\n"
                + ((v.get("assistantText") or "").strip())
            )

        blocks.append("Aktuelle Nutzeranweisung:\n" + (new_user_message or "").strip())
        blocks.append("Gib ausschließlich den finalen Text aus.")

        return ("\n\n".join(blocks)).strip() + "\n"

    async def init_combined_refinement(
        self, user_id: str, kapitel_id: str, run_id: str
    ) -> dict:
        """Ensure root version + metadata exist for this run's combined text."""
        try:
            return await firebase_service.ensure_combined_refinement_root_version(
                user_id=user_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                max_depth=config.TEXT_REFINEMENT_MAX_DEPTH,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def init_shortened_refinement(
        self, user_id: str, kapitel_id: str, run_id: str
    ) -> dict:
        """Ensure root version + metadata exist for this run's shortened text."""
        try:
            return await firebase_service.ensure_shortened_refinement_root_version(
                user_id=user_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                max_depth=config.TEXT_REFINEMENT_MAX_DEPTH,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def init_lesefluss_refinement(
        self, user_id: str, kapitel_id: str, run_id: str
    ) -> dict:
        """Ensure root version + metadata exist for this run's lesefluss text."""
        try:
            return await firebase_service.ensure_lesefluss_refinement_root_version(
                user_id=user_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                max_depth=config.TEXT_REFINEMENT_MAX_DEPTH,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def init_result_refinement(
        self, user_id: str, kapitel_id: str, run_id: str, quelle_id: str
    ) -> dict:
        """Ensure root version + metadata exist for this run's Quelle result text."""
        try:
            return await firebase_service.ensure_result_refinement_root_version(
                user_id=user_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                quelle_id=quelle_id,
                max_depth=config.TEXT_REFINEMENT_MAX_DEPTH,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def create_manual_combined_refinement(
        self,
        *,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        parent_version_id: str,
        content: str,
    ) -> dict:
        await firebase_service.ensure_combined_refinement_root_version(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            max_depth=config.TEXT_REFINEMENT_MAX_DEPTH,
        )
        parent = self._validate_manual_parent(
            await firebase_service.get_combined_refinement_version(
                user_id, kapitel_id, run_id, parent_version_id
            )
        )
        text = self._normalize_manual_refinement_content(content)
        version_id, version_data = self._build_manual_refinement_version(
            parent=parent, content=text
        )
        await firebase_service.apply_combined_refinement_version(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            version_id=version_id,
            version_data=version_data,
            content=text,
        )
        return {
            "status": "success",
            "version_id": version_id,
            "parent_version_id": parent.get("id") or parent_version_id,
            "depth": version_data["depth"],
            "source": "manual",
        }

    async def create_manual_shortened_refinement(
        self,
        *,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        parent_version_id: str,
        content: str,
    ) -> dict:
        await firebase_service.ensure_shortened_refinement_root_version(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            max_depth=config.TEXT_REFINEMENT_MAX_DEPTH,
        )
        parent = self._validate_manual_parent(
            await firebase_service.get_shortened_refinement_version(
                user_id, kapitel_id, run_id, parent_version_id
            )
        )
        text = self._normalize_manual_refinement_content(content)
        version_id, version_data = self._build_manual_refinement_version(
            parent=parent, content=text
        )
        await firebase_service.apply_shortened_refinement_version(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            version_id=version_id,
            version_data=version_data,
            content=text,
        )
        return {
            "status": "success",
            "version_id": version_id,
            "parent_version_id": parent.get("id") or parent_version_id,
            "depth": version_data["depth"],
            "source": "manual",
        }

    async def create_manual_lesefluss_refinement(
        self,
        *,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        parent_version_id: str,
        content: str,
    ) -> dict:
        await firebase_service.ensure_lesefluss_refinement_root_version(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            max_depth=config.TEXT_REFINEMENT_MAX_DEPTH,
        )
        parent = self._validate_manual_parent(
            await firebase_service.get_lesefluss_refinement_version(
                user_id, kapitel_id, run_id, parent_version_id
            )
        )
        text = self._normalize_manual_refinement_content(content)
        version_id, version_data = self._build_manual_refinement_version(
            parent=parent, content=text
        )
        await firebase_service.apply_lesefluss_refinement_version(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            version_id=version_id,
            version_data=version_data,
            content=text,
        )
        return {
            "status": "success",
            "version_id": version_id,
            "parent_version_id": parent.get("id") or parent_version_id,
            "depth": version_data["depth"],
            "source": "manual",
        }

    async def create_manual_result_refinement(
        self,
        *,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        quelle_id: str,
        parent_version_id: str,
        content: str,
    ) -> dict:
        await firebase_service.ensure_result_refinement_root_version(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            quelle_id=quelle_id,
            max_depth=config.TEXT_REFINEMENT_MAX_DEPTH,
        )
        parent = self._validate_manual_parent(
            await firebase_service.get_result_refinement_version(
                user_id, kapitel_id, run_id, quelle_id, parent_version_id
            )
        )
        text = self._normalize_manual_refinement_content(content)
        version_id, version_data = self._build_manual_refinement_version(
            parent=parent, content=text
        )
        await firebase_service.apply_result_refinement_version(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            quelle_id=quelle_id,
            version_id=version_id,
            version_data=version_data,
            content=text,
        )
        return {
            "status": "success",
            "version_id": version_id,
            "parent_version_id": parent.get("id") or parent_version_id,
            "depth": version_data["depth"],
            "source": "manual",
        }

    async def _get_heading_topic_and_base_texts(
        self, user_id: str, kapitel_id: str, run_id: str
    ) -> tuple[str, str, str, list[dict]]:
        run = await firebase_service.get_run(user_id, kapitel_id, run_id)
        if not run:
            raise ValueError("Run not found.")

        prompt_payload = run.get("promptPayload") or run.get("prompt_payload") or {}
        heading = (prompt_payload.get("heading", "") or "").strip() or "Zusammenfassung"
        topic = (prompt_payload.get("topic", "") or "").strip() or "Thema"
        model = (run.get("model", "") or "").strip() or "gpt-5-mini"

        results = await firebase_service.get_run_results(user_id, kapitel_id, run_id)
        eligible: list[dict] = []
        for res in results:
            if not res.get("hasContent", True):
                continue
            content = res.get("content")
            if content:
                eligible.append({"id": res.get("id"), "content": content})

        if len(eligible) < 2:
            raise ValueError(
                "Not enough eligible texts to refine (need at least 2 with content)."
            )

        # Deterministic ordering (useful for caching/debugging)
        eligible.sort(key=lambda item: str(item.get("id") or ""))

        return heading, topic, model, eligible

    async def _get_ueberschrift_thema_and_base_texts(
        self, user_id: str, kapitel_id: str, run_id: str
    ) -> tuple[str, str, list[dict]]:
        run = await firebase_service.get_run(user_id, kapitel_id, run_id)
        if not run:
            raise ValueError("Run not found.")

        ueberschrift = (run.get("ueberschrift", "") or "").strip() or "Kapitel"
        thema = (
            (run.get("thema", "") or "").strip()
            or (run.get("instruction", "") or "").strip()
            or "Thema"
        )

        results = await firebase_service.get_run_results(user_id, kapitel_id, run_id)
        eligible: list[dict] = []
        for res in results:
            if not res.get("hasContent", True):
                continue
            content = res.get("content")
            if content:
                eligible.append({"id": res.get("id"), "content": content})

        if len(eligible) < 2:
            raise ValueError(
                "Not enough eligible texts to refine (need at least 2 with content)."
            )

        eligible.sort(key=lambda item: str(item.get("id") or ""))
        return ueberschrift, thema, eligible

    async def _get_version_path(
        self, user_id: str, kapitel_id: str, run_id: str, head_version_id: str
    ) -> list[dict]:
        """
        Return versions from root -> head (inclusive), by following parent_version_id.
        """
        path: list[dict] = []
        current_id: str | None = head_version_id

        safety = 0
        while current_id is not None and safety < 32:
            safety += 1
            version = await firebase_service.get_combined_refinement_version(
                user_id, kapitel_id, run_id, current_id
            )
            if not version:
                raise ValueError(f"Refinement version '{current_id}' not found.")
            path.append(version)
            current_id = version.get("parentVersionId")

        path.reverse()
        return path

    async def _get_shortened_version_path(
        self, user_id: str, kapitel_id: str, run_id: str, head_version_id: str
    ) -> list[dict]:
        """Return shortened versions from root -> head (inclusive), following parent_version_id."""
        path: list[dict] = []
        current_id: str | None = head_version_id

        safety = 0
        while current_id is not None and safety < 32:
            safety += 1
            version = await firebase_service.get_shortened_refinement_version(
                user_id, kapitel_id, run_id, current_id
            )
            if not version:
                raise ValueError(f"Refinement version '{current_id}' not found.")
            path.append(version)
            current_id = version.get("parentVersionId")

        path.reverse()
        return path

    async def _get_lesefluss_version_path(
        self, user_id: str, kapitel_id: str, run_id: str, head_version_id: str
    ) -> list[dict]:
        """Return lesefluss versions from root -> head (inclusive), following parent_version_id."""
        path: list[dict] = []
        current_id: str | None = head_version_id

        safety = 0
        while current_id is not None and safety < 32:
            safety += 1
            version = await firebase_service.get_lesefluss_refinement_version(
                user_id, kapitel_id, run_id, current_id
            )
            if not version:
                raise ValueError(f"Refinement version '{current_id}' not found.")
            path.append(version)
            current_id = version.get("parentVersionId")

        path.reverse()
        return path

    async def _get_result_version_path(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        quelle_id: str,
        head_version_id: str,
    ) -> list[dict]:
        """Return per-result versions from root -> head (inclusive), following parent_version_id."""
        path: list[dict] = []
        current_id: str | None = head_version_id

        safety = 0
        while current_id is not None and safety < 32:
            safety += 1
            version = await firebase_service.get_result_refinement_version(
                user_id, kapitel_id, run_id, quelle_id, current_id
            )
            if not version:
                raise ValueError(f"Refinement version '{current_id}' not found.")
            path.append(version)
            current_id = version.get("parentVersionId")

        path.reverse()
        return path

    def _build_refinement_prompt_body(
        self,
        *,
        base_user_message: str,
        history_path: list[dict],
        user_message: str,
    ) -> str:
        return self._build_refinement_conversation_prompt(
            base_user_message=base_user_message,
            history_path=history_path,
            new_user_message=user_message,
        )

    def _get_prompt_dump_path(self, prefix: str, version_id: str) -> str | None:
        if not config.DUMP_REFINEMENT_PROMPTS:
            return None

        # TODO(text-refinement): Remove this debug dump once prompts are validated end-to-end.
        base_dir = Path(__file__).resolve().parent.parent / ".prompt_dumps"
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}_{version_id}.md"
        return str(base_dir / filename)

    def _build_lesefluss_refinement_prompt_body(
        self,
        *,
        base_user_message: str,
        history_path: list[dict],
        user_message: str,
    ) -> str:
        return self._build_refinement_conversation_prompt(
            base_user_message=base_user_message,
            history_path=history_path,
            new_user_message=user_message,
        )

    def _build_result_refinement_user_input(
        self,
        *,
        base_user_input: str,
        history_path: list[dict],
        user_message: str,
    ) -> str:
        return self._build_refinement_conversation_prompt(
            base_user_message=base_user_input,
            history_path=history_path,
            new_user_message=user_message,
        )

    def _build_shortened_refinement_prompt_body(
        self,
        *,
        base_user_message: str,
        history_path: list[dict],
        user_message: str,
    ) -> str:
        return self._build_refinement_conversation_prompt(
            base_user_message=base_user_message,
            history_path=history_path,
            new_user_message=user_message,
        )

    async def queue_combined_refinement(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        parent_version_id: str,
        user_message: str,
    ) -> dict:
        """
        Create a pending refinement version doc and return queued info.
        Background processing must be scheduled by the caller.
        """
        run = await firebase_service.get_run(user_id, kapitel_id, run_id)
        if not run:
            raise ValueError("Run not found.")
        run_model = (run.get("model", "") or "").strip() or "gpt-5-mini"

        init_state = await firebase_service.ensure_combined_refinement_root_version(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            max_depth=config.TEXT_REFINEMENT_MAX_DEPTH,
        )

        parent = await firebase_service.get_combined_refinement_version(
            user_id, kapitel_id, run_id, parent_version_id
        )
        if not parent:
            raise ValueError("Parent version not found.")

        parent_depth = int(parent.get("depth") or 0)
        next_depth = parent_depth + 1
        if next_depth > int(init_state["max_depth"]):
            raise ValueError(
                f"Max refinement depth reached ({init_state['max_depth']})."
            )

        version_id = str(uuid4())
        pending = {
            "parentVersionId": parent_version_id,
            "depth": next_depth,
            "userMessage": user_message,
            "assistantText": "",
            "hasContent": True,
            "status": "running",
            "model": run_model,
            "usage": {
                "inputTokens": 0,
                "cachedInputTokens": 0,
                "outputTokens": 0,
                "reasoningTokens": 0,
                "totalTokens": 0,
            },
            "costUsd": 0.0,
            "keySource": None,
            "createdAt": SERVER_TIMESTAMP,
            "updatedAt": SERVER_TIMESTAMP,
        }
        await firebase_service.save_combined_refinement_version(
            user_id, kapitel_id, run_id, version_id, pending
        )
        await firebase_service.increment_run_refinement_running_count(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            delta=1,
        )

        return {
            "status": "queued",
            "version_id": version_id,
            "parent_version_id": parent_version_id,
            "depth": next_depth,
            "max_depth": init_state["max_depth"],
            "model": run_model,
        }

    async def process_combined_refinement(
        self,
        *,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        version_id: str,
        parent_version_id: str,
        user_message: str,
    ) -> None:
        """
        Execute the combined text refinement and persist results into versions/{version_id}.
        """
        try:
            # Ensure root exists
            await firebase_service.ensure_combined_refinement_root_version(
                user_id=user_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                max_depth=config.TEXT_REFINEMENT_MAX_DEPTH,
            )

            parent = await firebase_service.get_combined_refinement_version(
                user_id, kapitel_id, run_id, parent_version_id
            )
            if not parent:
                raise ValueError("Parent version not found.")

            parent_text = parent.get("assistantText") or ""
            if not parent_text:
                raise ValueError("Parent text is empty.")

            heading, topic, model, eligible = (
                await self._get_heading_topic_and_base_texts(
                    user_id, kapitel_id, run_id
                )
            )
            api_key, key_source = await self._resolve_api_key_for_model(user_id, model)

            combine_instructions = await prompt_service.get_rendered_instructions(
                user_id,
                "combine",
                {"KAPITEL_TITEL": heading, "KAPITEL_BESCHREIBUNG": topic},
            )
            source_texts = [e["content"] for e in eligible]

            draft_parts: list[str] = []
            for idx, text in enumerate(source_texts, start=1):
                draft_parts.append(f"Text {idx}:\n{text}")
            drafts_content = "\n\n".join(draft_parts)

            base_user_message = combine_instructions or ""
            if "{DRAFTS}" in base_user_message:
                base_user_message = base_user_message.replace(
                    "{DRAFTS}", drafts_content
                )
            else:
                base_user_message = (
                    f"{base_user_message}\n\n[ENTWÜRFE]\n{drafts_content}"
                )

            history_path = await self._get_version_path(
                user_id, kapitel_id, run_id, parent_version_id
            )

            prompt_body = self._build_refinement_prompt_body(
                base_user_message=base_user_message,
                history_path=history_path,
                user_message=user_message,
            )

            debug_dump_path = self._get_prompt_dump_path("refine_combined", version_id)

            operation_id = version_id
            estimation_service = get_openai_estimation_service(firebase_service)
            estimate_obj = await estimation_service.estimate_operation(
                user_id=user_id,
                operation_type="refine_combined",
                model=model,
                system_text=REFINEMENT_SYSTEM_PROMPT,
                user_text=prompt_body,
                parent_generated_text=parent_text,
            )

            budget_service = get_openai_budget_service(firebase_service)
            reservation_released = False
            reservation = await budget_service.reserve_operation(
                user_id=user_id,
                operation_id=operation_id,
                operation_type="refine_combined",
                user_action_id=version_id,
                estimate=estimate_obj.to_dict(),
                kapitel_id=kapitel_id,
                run_id=run_id,
                operation_details={
                    "versionId": version_id,
                    "parentVersionId": parent_version_id,
                    "baseTextCount": len(source_texts),
                    "hasUserMessage": bool((user_message or "").strip()),
                },
            )

            if reservation.result == "blocked":
                await firebase_service.update_combined_refinement_version(
                    user_id,
                    kapitel_id,
                    run_id,
                    version_id,
                    {
                        "status": "blocked",
                        "errorMessage": "Kein Guthaben verf\u00fcgbar. Bitte lade Credits im Profil unter Billing auf.",
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                )
                return
            if reservation.result in {"already_reserved", "finalized"}:
                await firebase_service.update_combined_refinement_version(
                    user_id,
                    kapitel_id,
                    run_id,
                    version_id,
                    {
                        "status": "error",
                        "errorMessage": "Operation already exists. Please retry later.",
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                )
                return

            await budget_service.mark_running(user_id=user_id, operation_id=operation_id)
            try:
                openai_result = await self._generate_refinement_text(
                    prompt_body=prompt_body,
                    model=model,
                    api_key=api_key,
                    debug_prompt_dump_path=debug_dump_path,
                    stage="refine_combined",
                )
            except Exception as exc:
                await budget_service.mark_status(
                    user_id=user_id,
                    operation_id=operation_id,
                    status="error",
                    error_message=str(exc),
                )
                await budget_service.release_reservation(
                    user_id=user_id,
                    operation_id=operation_id,
                    reason="error",
                )
                reservation_released = True
                raise

            cost_service = get_cost_service(firebase_service)
            usage_obj = TokenUsage.from_any(
                openai_result.get("input_tokens", 0),
                openai_result.get("cached_input_tokens", 0),
                openai_result.get("output_tokens", 0),
            )
            cost_breakdown, matched_model, pricing, _match_type = (
                await cost_service.calculate_cost(
                    model=openai_result.get("model") or model,
                    usage=usage_obj,
                )
            )

            kapitel = await firebase_service.get_kapitel(user_id, kapitel_id)
            projekt_id = (kapitel or {}).get("projektId")

            projekt_snapshot = None
            if projekt_id:
                project = await firebase_service.get_project(user_id, projekt_id)
                if project:
                    projekt_snapshot = {
                        "id": projekt_id,
                        "name": project.get("name"),
                        "archived": bool(project.get("archived", False)),
                    }

            kapitel_snapshot = (
                {
                    "id": kapitel_id,
                    "nummer": (kapitel or {}).get("nummer", "?"),
                    "title": (kapitel or {}).get("title", "Untitled"),
                }
                if kapitel
                else None
            )

            run = await firebase_service.get_run(user_id, kapitel_id, run_id)
            run_snapshot = {
                "id": run_id,
                "index": (run or {}).get("index"),
            }

            await cost_service.log_operation(
                operation_id=operation_id,
                operation_type="refine_combined",
                user_id=user_id,
                user_action_id=version_id,
                operation_details={
                    "versionId": version_id,
                    "parentVersionId": parent_version_id,
                    "baseTextCount": len(source_texts),
                    "hasUserMessage": bool((user_message or "").strip()),
                },
                model=openai_result.get("model") or model,
                usage=usage_obj,
                cost_breakdown=cost_breakdown,
                matched_model_key=matched_model,
                pricing=pricing,
                key_source=key_source,
                projekt_id=projekt_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                projekt_snapshot=projekt_snapshot,
                kapitel_snapshot=kapitel_snapshot,
                run_snapshot=run_snapshot,
            )

            cost = float(cost_breakdown.total_cost_usd)

            await budget_service.release_reservation(
                user_id=user_id,
                operation_id=operation_id,
                reason="success",
            )
            reservation_released = True

            version_update = {
                "assistantText": openai_result["content"],
                "hasContent": True,
                "status": "success",
                "model": openai_result["model"],
                "usage": {
                    "inputTokens": int(openai_result["input_tokens"]),
                    "cachedInputTokens": int(
                        openai_result.get("cached_input_tokens", 0)
                    ),
                    "outputTokens": int(openai_result["output_tokens"]),
                    "reasoningTokens": int(openai_result.get("reasoning_tokens", 0)),
                    "totalTokens": int(openai_result["tokens"]),
                },
                "costUsd": float(cost),
                "keySource": key_source,
                "updatedAt": SERVER_TIMESTAMP,
            }

            await firebase_service.update_combined_refinement_version(
                user_id, kapitel_id, run_id, version_id, version_update
            )

            await firebase_service.increment_combined_refinement_cost_total(
                user_id, kapitel_id, run_id, float(cost)
            )

        except Exception as e:
            logger.error(
                f"Combined refinement failed for kapitel {kapitel_id}, run {run_id}, version {version_id}: {e}",
                exc_info=True,
            )
            try:
                if (
                    "budget_service" in locals()
                    and "operation_id" in locals()
                    and not locals().get("reservation_released")
                ):
                    await budget_service.mark_status(
                        user_id=user_id,
                        operation_id=operation_id,
                        status="error",
                        error_message=str(e),
                    )
                    await budget_service.release_reservation(
                        user_id=user_id,
                        operation_id=operation_id,
                        reason="error",
                    )
            except Exception:
                pass
            try:
                await firebase_service.update_combined_refinement_version(
                    user_id,
                    kapitel_id,
                    run_id,
                    version_id,
                    {
                        "status": "error",
                        "errorMessage": AI_GENERIC_ERROR_MESSAGE,
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                )
            except Exception:
                pass
        finally:
            try:
                await firebase_service.increment_run_refinement_running_count(
                    user_id=user_id,
                    kapitel_id=kapitel_id,
                    run_id=run_id,
                    delta=-1,
                )
            except Exception:
                pass

    async def queue_shortened_refinement(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        parent_version_id: str,
        user_message: str,
    ) -> dict:
        """
        Create a pending shortened refinement version doc and return queued info.
        Background processing must be scheduled by the caller.
        """
        init_state = await firebase_service.ensure_shortened_refinement_root_version(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            max_depth=config.TEXT_REFINEMENT_MAX_DEPTH,
        )

        parent = await firebase_service.get_shortened_refinement_version(
            user_id, kapitel_id, run_id, parent_version_id
        )
        if not parent:
            raise ValueError("Parent version not found.")

        parent_depth = int(parent.get("depth") or 0)
        next_depth = parent_depth + 1
        if next_depth > int(init_state["max_depth"]):
            raise ValueError(
                f"Max refinement depth reached ({init_state['max_depth']})."
            )

        root = await firebase_service.get_shortened_refinement_version(
            user_id, kapitel_id, run_id, "root"
        )
        stage_model = normalize_forward_text_model((root or {}).get("model"), default="gpt-5-mini")

        version_id = str(uuid4())
        pending = {
            "parentVersionId": parent_version_id,
            "depth": next_depth,
            "userMessage": user_message,
            "assistantText": "",
            "hasContent": True,
            "status": "running",
            "model": stage_model,
            "usage": {
                "inputTokens": 0,
                "cachedInputTokens": 0,
                "outputTokens": 0,
                "reasoningTokens": 0,
                "totalTokens": 0,
            },
            "costUsd": 0.0,
            "keySource": None,
            "createdAt": SERVER_TIMESTAMP,
            "updatedAt": SERVER_TIMESTAMP,
        }
        await firebase_service.save_shortened_refinement_version(
            user_id, kapitel_id, run_id, version_id, pending
        )
        await firebase_service.increment_run_refinement_running_count(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            delta=1,
        )

        return {
            "status": "queued",
            "version_id": version_id,
            "parent_version_id": parent_version_id,
            "depth": next_depth,
            "max_depth": init_state["max_depth"],
            "model": stage_model,
        }

    async def process_shortened_refinement(
        self,
        *,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        version_id: str,
        parent_version_id: str,
        user_message: str,
    ) -> None:
        """Execute the shortened text refinement and persist results into versions/{version_id}."""
        try:
            await firebase_service.ensure_shortened_refinement_root_version(
                user_id=user_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                max_depth=config.TEXT_REFINEMENT_MAX_DEPTH,
            )

            parent = await firebase_service.get_shortened_refinement_version(
                user_id, kapitel_id, run_id, parent_version_id
            )
            if not parent:
                raise ValueError("Parent version not found.")

            parent_text = parent.get("assistantText") or ""
            if not parent_text:
                raise ValueError("Parent text is empty.")

            run = await firebase_service.get_run(user_id, kapitel_id, run_id)
            if not run:
                raise ValueError("Run not found.")

            ueberschrift = (run.get("ueberschrift") or "").strip() or "Kapitel"
            thema = (
                (run.get("thema") or "").strip()
                or (run.get("instruction") or "").strip()
                or "Thema"
            )

            combined = await firebase_service.get_combined_result(
                user_id, kapitel_id, run_id
            )
            if not combined or not (combined.get("content") or "").strip():
                raise ValueError("No combined result found for this run.")
            base_target_text = (combined.get("content") or "").strip()

            shortened = await firebase_service.get_shortened_result(
                user_id, kapitel_id, run_id
            )
            if not shortened:
                raise ValueError("No shortened result found for this run.")

            context_kapitel_ids = shortened.get("usedKapitelIds") or []
            if not isinstance(context_kapitel_ids, list):
                context_kapitel_ids = []

            valid_context_ids: list[str] = [
                str(cid) for cid in context_kapitel_ids if str(cid) != str(kapitel_id)
            ]

            summaries: dict[str, str] = {}
            for ctx_id in valid_context_ids:
                summary_doc = await firebase_service.get_summary_result(
                    user_id, kapitel_id, run_id, ctx_id
                )
                content = (
                    (summary_doc or {}).get("content")
                    if isinstance(summary_doc, dict)
                    else ""
                )
                content = (content or "").strip()
                if content:
                    summaries[str(ctx_id)] = content

            kapitel = await firebase_service.get_kapitel(user_id, kapitel_id)
            projekt_id = (kapitel or {}).get("projektId")

            all_kapitels: list[dict] = []
            if (projekt_id or "").strip():
                all_kapitels = await firebase_service.list_kapitel_metadata_for_project(
                    user_id, projekt_id
                )

            if not all_kapitels:
                fallback_ids = list(dict.fromkeys([kapitel_id] + valid_context_ids))
                for kid in fallback_ids:
                    metadata = await firebase_service.get_kapitel_metadata(user_id, kid)
                    if metadata:
                        all_kapitels.append(metadata)

            all_kapitels.sort(
                key=lambda k: shorten_service._nummer_sort_key(k.get("nummer", ""))
            )
            gliederung = await shorten_service.build_gliederung(
                user_id, kapitel_id, all_kapitels, summaries
            )

            active_template_id, _ = await prompt_service.resolve_active_template_id(
                user_id, "shorten"
            )
            template_instructions = await prompt_service.get_instructions_for_template(
                user_id, "shorten", active_template_id
            )

            rendered = prompt_service.render(
                template_instructions,
                {
                    "KAPITEL_TITEL": ueberschrift,
                    "KAPITEL_BESCHREIBUNG": thema,
                    "GLIEDERUNG_SUMMARY": gliederung,
                    "KAPITELTEXT": base_target_text,
                },
            )
            uses_inline_inputs = (
                "{GLIEDERUNG_SUMMARY}" in template_instructions
            ) and ("{KAPITELTEXT}" in template_instructions)

            base_user_message = rendered
            if not uses_inline_inputs:
                base_user_message = f"""{rendered}

### Gliederung:
{gliederung}

### Text zum Kürzen:
{base_target_text}"""

            history_path = await self._get_shortened_version_path(
                user_id, kapitel_id, run_id, parent_version_id
            )

            prompt_body = self._build_shortened_refinement_prompt_body(
                base_user_message=base_user_message,
                history_path=history_path,
                user_message=user_message,
            )

            pending = await firebase_service.get_shortened_refinement_version(
                user_id, kapitel_id, run_id, version_id
            )
            model = normalize_forward_text_model((pending or {}).get("model"), default="gpt-5-mini")
            api_key, key_source = await self._resolve_api_key_for_model(user_id, model)

            debug_dump_path = self._get_prompt_dump_path("refine_shortened", version_id)

            operation_id = version_id
            estimation_service = get_openai_estimation_service(firebase_service)
            estimate_obj = await estimation_service.estimate_operation(
                user_id=user_id,
                operation_type="refine_shortened",
                model=model,
                system_text=REFINEMENT_SYSTEM_PROMPT,
                user_text=prompt_body,
                parent_generated_text=parent_text,
            )

            budget_service = get_openai_budget_service(firebase_service)
            reservation_released = False
            reservation = await budget_service.reserve_operation(
                user_id=user_id,
                operation_id=operation_id,
                operation_type="refine_shortened",
                user_action_id=version_id,
                estimate=estimate_obj.to_dict(),
                kapitel_id=kapitel_id,
                run_id=run_id,
                operation_details={
                    "versionId": version_id,
                    "parentVersionId": parent_version_id,
                    "usedKapitelIds": valid_context_ids,
                    "summaryCount": len(summaries),
                    "hasUserMessage": bool((user_message or "").strip()),
                },
            )

            if reservation.result == "blocked":
                await firebase_service.update_shortened_refinement_version(
                    user_id,
                    kapitel_id,
                    run_id,
                    version_id,
                    {
                        "status": "blocked",
                        "errorMessage": "Kein Guthaben verf\u00fcgbar. Bitte lade Credits im Profil unter Billing auf.",
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                )
                return
            if reservation.result in {"already_reserved", "finalized"}:
                await firebase_service.update_shortened_refinement_version(
                    user_id,
                    kapitel_id,
                    run_id,
                    version_id,
                    {
                        "status": "error",
                        "errorMessage": "Operation already exists. Please retry later.",
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                )
                return

            await budget_service.mark_running(user_id=user_id, operation_id=operation_id)
            try:
                openai_result = await self._generate_refinement_text(
                    prompt_body=prompt_body,
                    model=model,
                    api_key=api_key,
                    debug_prompt_dump_path=debug_dump_path,
                    stage="refine_shortened",
                )
            except Exception as exc:
                await budget_service.mark_status(
                    user_id=user_id,
                    operation_id=operation_id,
                    status="error",
                    error_message=str(exc),
                )
                await budget_service.release_reservation(
                    user_id=user_id,
                    operation_id=operation_id,
                    reason="error",
                )
                reservation_released = True
                raise

            cost_service = get_cost_service(firebase_service)
            usage_obj = TokenUsage.from_any(
                openai_result.get("input_tokens", 0),
                openai_result.get("cached_input_tokens", 0),
                openai_result.get("output_tokens", 0),
            )
            cost_breakdown, matched_model, pricing, _match_type = (
                await cost_service.calculate_cost(
                    model=openai_result.get("model") or model,
                    usage=usage_obj,
                )
            )

            projekt_snapshot = None
            if projekt_id:
                project = await firebase_service.get_project(user_id, projekt_id)
                if project:
                    projekt_snapshot = {
                        "id": projekt_id,
                        "name": project.get("name"),
                        "archived": bool(project.get("archived", False)),
                    }

            kapitel_snapshot = (
                {
                    "id": kapitel_id,
                    "nummer": (kapitel or {}).get("nummer", "?"),
                    "title": (kapitel or {}).get("title", "Untitled"),
                }
                if kapitel
                else None
            )

            run_snapshot = {
                "id": run_id,
                "index": (run or {}).get("index"),
            }

            await cost_service.log_operation(
                operation_id=operation_id,
                operation_type="refine_shortened",
                user_id=user_id,
                user_action_id=version_id,
                operation_details={
                    "versionId": version_id,
                    "parentVersionId": parent_version_id,
                    "usedKapitelIds": valid_context_ids,
                    "summaryCount": len(summaries),
                    "hasUserMessage": bool((user_message or "").strip()),
                },
                model=openai_result.get("model") or model,
                usage=usage_obj,
                cost_breakdown=cost_breakdown,
                matched_model_key=matched_model,
                pricing=pricing,
                key_source=key_source,
                projekt_id=projekt_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                projekt_snapshot=projekt_snapshot,
                kapitel_snapshot=kapitel_snapshot,
                run_snapshot=run_snapshot,
            )

            cost = float(cost_breakdown.total_cost_usd)

            await budget_service.release_reservation(
                user_id=user_id,
                operation_id=operation_id,
                reason="success",
            )
            reservation_released = True

            version_update = {
                "assistantText": openai_result["content"],
                "hasContent": True,
                "status": "success",
                "model": openai_result["model"],
                "usage": {
                    "inputTokens": int(openai_result["input_tokens"]),
                    "cachedInputTokens": int(
                        openai_result.get("cached_input_tokens", 0)
                    ),
                    "outputTokens": int(openai_result["output_tokens"]),
                    "reasoningTokens": int(openai_result.get("reasoning_tokens", 0)),
                    "totalTokens": int(openai_result["tokens"]),
                },
                "costUsd": float(cost),
                "keySource": key_source,
                "updatedAt": SERVER_TIMESTAMP,
            }

            await firebase_service.update_shortened_refinement_version(
                user_id, kapitel_id, run_id, version_id, version_update
            )

            await firebase_service.increment_shortened_refinement_cost_total(
                user_id, kapitel_id, run_id, float(cost)
            )

        except Exception as e:
            logger.error(
                f"Shortened refinement failed for kapitel {kapitel_id}, run {run_id}, version {version_id}: {e}",
                exc_info=True,
            )
            try:
                if (
                    "budget_service" in locals()
                    and "operation_id" in locals()
                    and not locals().get("reservation_released")
                ):
                    await budget_service.mark_status(
                        user_id=user_id,
                        operation_id=operation_id,
                        status="error",
                        error_message=str(e),
                    )
                    await budget_service.release_reservation(
                        user_id=user_id,
                        operation_id=operation_id,
                        reason="error",
                    )
            except Exception:
                pass
            try:
                await firebase_service.update_shortened_refinement_version(
                    user_id,
                    kapitel_id,
                    run_id,
                    version_id,
                    {
                        "status": "error",
                        "errorMessage": AI_GENERIC_ERROR_MESSAGE,
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                )
            except Exception:
                pass
        finally:
            try:
                await firebase_service.increment_run_refinement_running_count(
                    user_id=user_id,
                    kapitel_id=kapitel_id,
                    run_id=run_id,
                    delta=-1,
                )
            except Exception:
                pass

    async def queue_lesefluss_refinement(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        parent_version_id: str,
        user_message: str,
    ) -> dict:
        """
        Create a pending lesefluss refinement version doc and return queued info.
        Background processing must be scheduled by the caller.
        """
        init_state = await firebase_service.ensure_lesefluss_refinement_root_version(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            max_depth=config.TEXT_REFINEMENT_MAX_DEPTH,
        )

        parent = await firebase_service.get_lesefluss_refinement_version(
            user_id, kapitel_id, run_id, parent_version_id
        )
        if not parent:
            raise ValueError("Parent version not found.")

        parent_depth = int(parent.get("depth") or 0)
        next_depth = parent_depth + 1
        if next_depth > int(init_state["max_depth"]):
            raise ValueError(
                f"Max refinement depth reached ({init_state['max_depth']})."
            )

        root = await firebase_service.get_lesefluss_refinement_version(
            user_id, kapitel_id, run_id, "root"
        )
        stage_model = normalize_forward_text_model((root or {}).get("model"), default="gpt-5-mini")

        version_id = str(uuid4())
        pending = {
            "parentVersionId": parent_version_id,
            "depth": next_depth,
            "userMessage": user_message,
            "assistantText": "",
            "hasContent": True,
            "status": "running",
            "model": stage_model,
            "usage": {
                "inputTokens": 0,
                "cachedInputTokens": 0,
                "outputTokens": 0,
                "reasoningTokens": 0,
                "totalTokens": 0,
            },
            "costUsd": 0.0,
            "keySource": None,
            "createdAt": SERVER_TIMESTAMP,
            "updatedAt": SERVER_TIMESTAMP,
        }
        await firebase_service.save_lesefluss_refinement_version(
            user_id, kapitel_id, run_id, version_id, pending
        )
        await firebase_service.increment_run_refinement_running_count(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            delta=1,
        )

        return {
            "status": "queued",
            "version_id": version_id,
            "parent_version_id": parent_version_id,
            "depth": next_depth,
            "max_depth": init_state["max_depth"],
            "model": stage_model,
        }

    async def process_lesefluss_refinement(
        self,
        *,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        version_id: str,
        parent_version_id: str,
        user_message: str,
    ) -> None:
        """Execute the lesefluss text refinement and persist results into versions/{version_id}."""
        try:
            await firebase_service.ensure_lesefluss_refinement_root_version(
                user_id=user_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                max_depth=config.TEXT_REFINEMENT_MAX_DEPTH,
            )

            parent = await firebase_service.get_lesefluss_refinement_version(
                user_id, kapitel_id, run_id, parent_version_id
            )
            if not parent:
                raise ValueError("Parent version not found.")

            parent_text = parent.get("assistantText") or ""
            if not parent_text:
                raise ValueError("Parent text is empty.")

            lesefluss_doc = await firebase_service.get_lesefluss_result(
                user_id, kapitel_id, run_id
            )
            if not lesefluss_doc:
                raise ValueError("No lesefluss result found for this run.")

            aufgabenstellung = (lesefluss_doc.get("aufgabenstellung") or "").strip()
            if not aufgabenstellung:
                raise ValueError("Lesefluss aufgabenstellung is missing.")

            context_kapitel_ids = lesefluss_doc.get("usedKapitelIds") or []
            if (
                not isinstance(context_kapitel_ids, list)
                or len(context_kapitel_ids) == 0
            ):
                raise ValueError(
                    "Lesefluss context chapters are missing (usedKapitelIds)."
                )

            shortened = await firebase_service.get_shortened_result(
                user_id, kapitel_id, run_id
            )
            if not shortened:
                raise ValueError("No shortened result found for this run.")
            base_target_text = (shortened.get("content") or "").strip()
            if not base_target_text:
                raise ValueError("Shortened content is empty.")

            pending = await firebase_service.get_lesefluss_refinement_version(
                user_id, kapitel_id, run_id, version_id
            )
            model = normalize_forward_text_model((pending or {}).get("model"), default="gpt-5-mini")
            api_key, key_source = await self._resolve_api_key_for_model(user_id, model)

            # Summaries / Gliederung (reuse cache if present)
            summary_tasks = [
                shorten_service.get_or_create_summary(
                    user_id=user_id,
                    target_kapitel_id=kapitel_id,
                    target_run_id=run_id,
                    source_kapitel_id=str(ctx_id),
                    model=model,
                    api_key=api_key,
                    key_source=key_source,
                    user_action_id=version_id,
                )
                for ctx_id in context_kapitel_ids
            ]
            summaries_list = await asyncio.gather(
                *summary_tasks, return_exceptions=True
            )

            summaries: dict[str, str] = {}
            valid_context_ids: list[str] = []
            blocked_for_credits = False
            for ctx_id, summary_result in zip(context_kapitel_ids, summaries_list):
                if isinstance(summary_result, Exception):
                    if isinstance(summary_result, HTTPException) and summary_result.status_code == 402:
                        blocked_for_credits = True
                    logger.error(
                        f"Failed to get summary for Kapitel {ctx_id}: {summary_result}"
                    )
                else:
                    summaries[str(ctx_id)] = str(summary_result)
                    valid_context_ids.append(str(ctx_id))

            if not summaries:
                if blocked_for_credits:
                    await firebase_service.update_lesefluss_refinement_version(
                        user_id,
                        kapitel_id,
                        run_id,
                        version_id,
                        {
                            "status": "blocked",
                            "errorMessage": "Kein Guthaben verf\u00fcgbar. Bitte lade Credits im Profil unter Billing auf.",
                            "updatedAt": SERVER_TIMESTAMP,
                        },
                    )
                    return
                raise ValueError("No valid summaries could be generated for context Kapitels.")

            kapitel = await firebase_service.get_kapitel(user_id, kapitel_id)
            projekt_id = (kapitel or {}).get("projektId")

            all_kapitels: list[dict] = []
            if (projekt_id or "").strip():
                all_kapitels = await firebase_service.list_kapitel_metadata_for_project(
                    user_id, projekt_id
                )

            if not all_kapitels:
                fallback_ids = list(dict.fromkeys([kapitel_id] + valid_context_ids))
                for kid in fallback_ids:
                    metadata = await firebase_service.get_kapitel_metadata(user_id, kid)
                    if metadata:
                        all_kapitels.append(metadata)

            all_kapitels.sort(
                key=lambda k: shorten_service._nummer_sort_key(k.get("nummer", ""))
            )

            kapitel_nummer = (kapitel or {}).get("nummer") or "?"
            next_kapitel_nummer = ""
            uebernaechstes_kapitel_nummer = ""
            for idx, k in enumerate(all_kapitels):
                if str(k.get("id")) == str(kapitel_id):
                    kapitel_nummer = str(k.get("nummer") or kapitel_nummer or "?")
                    if idx + 1 < len(all_kapitels):
                        next_kapitel_nummer = str(
                            all_kapitels[idx + 1].get("nummer") or ""
                        )
                    if idx + 2 < len(all_kapitels):
                        uebernaechstes_kapitel_nummer = str(
                            all_kapitels[idx + 2].get("nummer") or ""
                        )
                    break

            gliederung = await shorten_service.build_gliederung(
                user_id, kapitel_id, all_kapitels, summaries
            )

            active_template_id, _ = await prompt_service.resolve_active_template_id(
                user_id, "lesefluss"
            )
            template_instructions = await prompt_service.get_instructions_for_template(
                user_id, "lesefluss", active_template_id
            )

            base_payload = {
                "AUFGABENSTELLUNG": aufgabenstellung,
                "GLIEDERUNG_SUMMARY": gliederung,
                "KAPITELTEXT": base_target_text,
                "AKTUELLES_KAPITEL_NUMMER": str(kapitel_nummer),
                "NAECHSTES_KAPITEL_NUMMER": next_kapitel_nummer,
                "UEBERNAECHSTES_KAPITEL_NUMMER": uebernaechstes_kapitel_nummer,
            }

            rendered_base = prompt_service.render(template_instructions, base_payload)
            uses_inline_inputs = (
                "{GLIEDERUNG_SUMMARY}" in template_instructions
                and "{KAPITELTEXT}" in template_instructions
            )

            base_user_message = rendered_base
            if not uses_inline_inputs:
                base_user_message = f"""{rendered_base}

### Gliederung:
{gliederung}

### Kapitel {kapitel_nummer} (TEXT AN DEM DU ARBEITEN SOLLST)
{base_target_text}"""

            history_path = await self._get_lesefluss_version_path(
                user_id, kapitel_id, run_id, parent_version_id
            )

            prompt_body = self._build_lesefluss_refinement_prompt_body(
                base_user_message=base_user_message,
                history_path=history_path,
                user_message=user_message,
            )

            debug_dump_path = self._get_prompt_dump_path("refine_lesefluss", version_id)

            operation_id = version_id
            estimation_service = get_openai_estimation_service(firebase_service)
            estimate_obj = await estimation_service.estimate_operation(
                user_id=user_id,
                operation_type="refine_lesefluss",
                model=model,
                system_text=REFINEMENT_SYSTEM_PROMPT,
                user_text=prompt_body,
                parent_generated_text=parent_text,
            )

            budget_service = get_openai_budget_service(firebase_service)
            reservation_released = False
            reservation = await budget_service.reserve_operation(
                user_id=user_id,
                operation_id=operation_id,
                operation_type="refine_lesefluss",
                user_action_id=version_id,
                estimate=estimate_obj.to_dict(),
                kapitel_id=kapitel_id,
                run_id=run_id,
                operation_details={
                    "versionId": version_id,
                    "parentVersionId": parent_version_id,
                    "usedKapitelIds": valid_context_ids,
                    "summaryCount": len(summaries),
                    "hasUserMessage": bool((user_message or "").strip()),
                },
            )

            if reservation.result == "blocked":
                await firebase_service.update_lesefluss_refinement_version(
                    user_id,
                    kapitel_id,
                    run_id,
                    version_id,
                    {
                        "status": "blocked",
                        "errorMessage": "Kein Guthaben verf\u00fcgbar. Bitte lade Credits im Profil unter Billing auf.",
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                )
                return
            if reservation.result in {"already_reserved", "finalized"}:
                await firebase_service.update_lesefluss_refinement_version(
                    user_id,
                    kapitel_id,
                    run_id,
                    version_id,
                    {
                        "status": "error",
                        "errorMessage": "Operation already exists. Please retry later.",
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                )
                return

            await budget_service.mark_running(user_id=user_id, operation_id=operation_id)
            try:
                openai_result = await self._generate_refinement_text(
                    prompt_body=prompt_body,
                    model=model,
                    api_key=api_key,
                    debug_prompt_dump_path=debug_dump_path,
                    stage="refine_lesefluss",
                )
            except Exception as exc:
                await budget_service.mark_status(
                    user_id=user_id,
                    operation_id=operation_id,
                    status="error",
                    error_message=str(exc),
                )
                await budget_service.release_reservation(
                    user_id=user_id,
                    operation_id=operation_id,
                    reason="error",
                )
                reservation_released = True
                raise

            content = (openai_result.get("content") or "").strip()

            input_tokens = int(openai_result.get("input_tokens", 0) or 0)
            cached_input_tokens = int(openai_result.get("cached_input_tokens", 0) or 0)
            output_tokens = int(openai_result.get("output_tokens", 0) or 0)
            total_tokens = input_tokens + output_tokens

            cost_service = get_cost_service(firebase_service)
            usage_obj = TokenUsage.from_any(
                input_tokens, cached_input_tokens, output_tokens
            )
            model_used = (openai_result.get("model") or model).strip() or model
            cost_breakdown, matched_model, pricing, _match_type = (
                await cost_service.calculate_cost(
                    model=model_used,
                    usage=usage_obj,
                )
            )

            projekt_snapshot = None
            if projekt_id:
                project = await firebase_service.get_project(user_id, projekt_id)
                if project:
                    projekt_snapshot = {
                        "id": projekt_id,
                        "name": project.get("name"),
                        "archived": bool(project.get("archived", False)),
                    }

            kapitel_snapshot = (
                {
                    "id": kapitel_id,
                    "nummer": (kapitel or {}).get("nummer", "?"),
                    "title": (kapitel or {}).get("title", "Untitled"),
                }
                if kapitel
                else None
            )

            run = await firebase_service.get_run(user_id, kapitel_id, run_id)
            run_snapshot = {
                "id": run_id,
                "index": (run or {}).get("index"),
            }

            await cost_service.log_operation(
                operation_id=operation_id,
                operation_type="refine_lesefluss",
                user_id=user_id,
                user_action_id=version_id,
                operation_details={
                    "versionId": version_id,
                    "parentVersionId": parent_version_id,
                    "usedKapitelIds": valid_context_ids,
                    "summaryCount": len(summaries),
                    "hasUserMessage": bool((user_message or "").strip()),
                },
                model=model_used,
                usage=usage_obj,
                cost_breakdown=cost_breakdown,
                matched_model_key=matched_model,
                pricing=pricing,
                key_source=key_source,
                projekt_id=projekt_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                projekt_snapshot=projekt_snapshot,
                kapitel_snapshot=kapitel_snapshot,
                run_snapshot=run_snapshot,
            )

            cost = float(cost_breakdown.total_cost_usd)

            await budget_service.release_reservation(
                user_id=user_id,
                operation_id=operation_id,
                reason="success",
            )
            reservation_released = True

            version_update = {
                "assistantText": content,
                "hasContent": True,
                "status": "success",
                "model": model_used,
                "usage": {
                    "inputTokens": input_tokens,
                    "cachedInputTokens": cached_input_tokens,
                    "outputTokens": output_tokens,
                    "reasoningTokens": 0,
                    "totalTokens": total_tokens,
                },
                "costUsd": float(cost),
                "keySource": key_source,
                "updatedAt": SERVER_TIMESTAMP,
            }

            await firebase_service.update_lesefluss_refinement_version(
                user_id, kapitel_id, run_id, version_id, version_update
            )

            await firebase_service.increment_lesefluss_refinement_cost_total(
                user_id, kapitel_id, run_id, float(cost)
            )

        except Exception as e:
            logger.error(
                f"Lesefluss refinement failed for kapitel {kapitel_id}, run {run_id}, version {version_id}: {e}",
                exc_info=True,
            )
            try:
                if (
                    "budget_service" in locals()
                    and "operation_id" in locals()
                    and not locals().get("reservation_released")
                ):
                    await budget_service.mark_status(
                        user_id=user_id,
                        operation_id=operation_id,
                        status="error",
                        error_message=str(e),
                    )
                    await budget_service.release_reservation(
                        user_id=user_id,
                        operation_id=operation_id,
                        reason="error",
                    )
            except Exception:
                pass
            try:
                await firebase_service.update_lesefluss_refinement_version(
                    user_id,
                    kapitel_id,
                    run_id,
                    version_id,
                    {
                        "status": "error",
                        "errorMessage": AI_GENERIC_ERROR_MESSAGE,
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                )
            except Exception:
                pass
        finally:
            try:
                await firebase_service.increment_run_refinement_running_count(
                    user_id=user_id,
                    kapitel_id=kapitel_id,
                    run_id=run_id,
                    delta=-1,
                )
            except Exception:
                pass

    async def queue_result_refinement(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        quelle_id: str,
        parent_version_id: str,
        user_message: str,
    ) -> dict:
        """
        Create a pending per-result refinement version doc and return queued info.
        Background processing must be scheduled by the caller.
        """
        init_state = await firebase_service.ensure_result_refinement_root_version(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            quelle_id=quelle_id,
            max_depth=config.TEXT_REFINEMENT_MAX_DEPTH,
        )

        parent = await firebase_service.get_result_refinement_version(
            user_id, kapitel_id, run_id, quelle_id, parent_version_id
        )
        if not parent:
            raise ValueError("Parent version not found.")

        parent_depth = int(parent.get("depth") or 0)
        next_depth = parent_depth + 1
        if next_depth > int(init_state["max_depth"]):
            raise ValueError(
                f"Max refinement depth reached ({init_state['max_depth']})."
            )

        root = await firebase_service.get_result_refinement_version(
            user_id, kapitel_id, run_id, quelle_id, "root"
        )
        stage_model = normalize_forward_text_model((root or {}).get("model"), default="gpt-5-mini")

        version_id = str(uuid4())
        pending = {
            "parentVersionId": parent_version_id,
            "depth": next_depth,
            "userMessage": user_message,
            "assistantText": "",
            "hasContent": True,
            "status": "running",
            "model": stage_model,
            "usage": {
                "inputTokens": 0,
                "cachedInputTokens": 0,
                "outputTokens": 0,
                "reasoningTokens": 0,
                "totalTokens": 0,
            },
            "costUsd": 0.0,
            "keySource": None,
            "createdAt": SERVER_TIMESTAMP,
            "updatedAt": SERVER_TIMESTAMP,
        }
        await firebase_service.save_result_refinement_version(
            user_id, kapitel_id, run_id, quelle_id, version_id, pending
        )
        await firebase_service.increment_run_refinement_running_count(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            delta=1,
        )

        return {
            "status": "queued",
            "version_id": version_id,
            "parent_version_id": parent_version_id,
            "depth": next_depth,
            "max_depth": init_state["max_depth"],
            "model": stage_model,
        }

    async def process_result_refinement(
        self,
        *,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        quelle_id: str,
        version_id: str,
        parent_version_id: str,
        user_message: str,
    ) -> None:
        """Execute the per-result refinement and persist results into versions/{version_id}."""
        try:
            await firebase_service.ensure_result_refinement_root_version(
                user_id=user_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                quelle_id=quelle_id,
                max_depth=config.TEXT_REFINEMENT_MAX_DEPTH,
            )

            parent = await firebase_service.get_result_refinement_version(
                user_id, kapitel_id, run_id, quelle_id, parent_version_id
            )
            if not parent:
                raise ValueError("Parent version not found.")

            parent_text = parent.get("assistantText") or ""

            result_doc = await firebase_service.get_run_result(
                user_id, kapitel_id, run_id, quelle_id
            )
            if not result_doc:
                raise ValueError("Result not found.")

            run = await firebase_service.get_run(user_id, kapitel_id, run_id)
            grundlegende_informationen = (run or {}).get("grundlegendeInformationen")

            quelle = await firebase_service.get_quelle(user_id, quelle_id)
            if not quelle:
                raise ValueError("Quelle not found.")

            base_user_input = (result_doc.get("userInput") or "").strip()
            # Prompts are no longer stored on result docs (hidden from user). Reconstruct from run settings.
            prompt_template_id = str(((run or {}).get("promptTemplateId") or "")).strip()
            if not prompt_template_id:
                prompt_template_id, _ = await prompt_service.resolve_active_template_id(
                    user_id, "process_quelle"
                )

            if not base_user_input:

                payload: dict = {}
                raw_payload = (
                    (run or {}).get("promptPayload")
                    or (run or {}).get("prompt_payload")
                    or {}
                )
                if isinstance(raw_payload, dict):
                    payload = {k: v for k, v in raw_payload.items()}

                # Backward-compat fallback for older runs.
                if (
                    run
                    and not payload.get("heading")
                    and (run.get("ueberschrift") or "").strip()
                ):
                    payload["heading"] = (run.get("ueberschrift") or "").strip()
                if (
                    run
                    and not payload.get("topic")
                    and (run.get("thema") or "").strip()
                ):
                    payload["topic"] = (run.get("thema") or "").strip()

                heading = str(payload.get("heading") or "").strip()
                topic = str(payload.get("topic") or "").strip()
                if not heading or not topic:
                    raise ValueError("Run promptPayload is missing heading/topic.")

                quelle_zitat_value = resolve_quelle_zitat_value(quelle)

                base_user_input = (
                    await prompt_service.get_rendered_instructions_for_template(
                        user_id=user_id,
                        stage="process_quelle",
                        template_id=prompt_template_id,
                        payload={
                            "KAPITEL_TITEL": heading,
                            "KAPITEL_BESCHREIBUNG": topic,
                            "QUELLE_ZITAT": quelle_zitat_value,
                        },
                    )
                )

            history_path = await self._get_result_version_path(
                user_id, kapitel_id, run_id, quelle_id, parent_version_id
            )

            refined_user_input = self._build_result_refinement_user_input(
                base_user_input=base_user_input,
                history_path=history_path,
                user_message=user_message,
            )

            pending = await firebase_service.get_result_refinement_version(
                user_id, kapitel_id, run_id, quelle_id, version_id
            )
            model = normalize_forward_text_model((pending or {}).get("model"), default="gpt-5-mini")
            api_key, key_source = await self._resolve_api_key_for_model(user_id, model)

            quelle_content_doc = await firebase_service.get_quelle_content(
                user_id, quelle_id
            )
            if (
                not quelle_content_doc
                or not (quelle_content_doc.get("text") or "").strip()
            ):
                raise ValueError("Quelle content is empty.")

            quelle_images = None
            if isinstance(quelle.get("images"), list):
                image_dicts = [img for img in quelle["images"] if isinstance(img, dict)]
                urls = [str(img.get("url") or "").strip() for img in image_dicts if str(img.get("url") or "").strip()]
                if urls:
                    quelle_images = urls
                    quelle_image_meta = image_dicts
                else:
                    quelle_image_meta = None
            else:
                quelle_image_meta = None

            debug_dump_path = self._get_prompt_dump_path("refine_result", version_id)

            quelle_text = quelle_content_doc.get("text") or ""
            prompt_text = (refined_user_input or "").replace("{BILDINHALT_ODER_LEER}", "")
            has_quelltext_placeholder = "{QUELLTEXT}" in prompt_text
            has_basic_info_placeholder = "{OPTIONAL_GRUNDLEGENDE_INFOS}" in prompt_text

            if has_basic_info_placeholder:
                prompt_text = prompt_text.replace(
                    "{OPTIONAL_GRUNDLEGENDE_INFOS}",
                    (grundlegende_informationen or "").strip(),
                )

            if has_quelltext_placeholder:
                prompt_text = prompt_text.replace("{QUELLTEXT}", quelle_text)
            else:
                if grundlegende_informationen and grundlegende_informationen.strip() and not has_basic_info_placeholder:
                    prompt_text = f"""{quelle_text}

### Grundlegende Informationen
{grundlegende_informationen}

{prompt_text}"""
                else:
                    prompt_text = f"""{quelle_text}

{prompt_text}"""

            estimation_service = get_openai_estimation_service(firebase_service)
            estimate_obj = await estimation_service.estimate_operation(
                user_id=user_id,
                operation_type="refine_result",
                model=model,
                system_text=REFINEMENT_SYSTEM_PROMPT,
                user_text=prompt_text,
                output_source_text=quelle_text,
                images=quelle_image_meta,
            )

            budget_service = get_openai_budget_service(firebase_service)
            operation_id = str(version_id or "").strip()
            reservation_released = False

            reservation = await budget_service.reserve_operation(
                user_id=user_id,
                operation_id=operation_id,
                operation_type="refine_result",
                user_action_id=version_id,
                estimate=estimate_obj.to_dict(),
                kapitel_id=kapitel_id,
                run_id=run_id,
                quelle_id=quelle_id,
                operation_details={
                    "versionId": version_id,
                    "parentVersionId": parent_version_id,
                    "hasUserMessage": bool((user_message or "").strip()),
                    "quelleHasImages": bool(quelle_images),
                },
            )

            if reservation.result == "blocked":
                await firebase_service.update_result_refinement_version(
                    user_id,
                    kapitel_id,
                    run_id,
                    quelle_id,
                    version_id,
                    {
                        "status": "blocked",
                        "errorMessage": "Kein Guthaben verfügbar. Bitte lade Credits im Profil unter Billing auf.",
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                )
                return
            if reservation.result in {"already_reserved", "finalized"}:
                await firebase_service.update_result_refinement_version(
                    user_id,
                    kapitel_id,
                    run_id,
                    quelle_id,
                    version_id,
                    {
                        "status": "error",
                        "errorMessage": "Operation already exists. Please retry later.",
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                )
                return

            await budget_service.mark_running(user_id=user_id, operation_id=operation_id)

            try:
                openai_result = await get_ai_service(model).process_quelle(
                    quelle_text,
                    refined_user_input,
                    model,
                    grundlegende_informationen,
                    api_key=api_key,
                    quelle_images=quelle_images,
                    debug_prompt_dump_path=debug_dump_path,
                    system_prompt=REFINEMENT_SYSTEM_PROMPT,
                )
            except Exception as exc:
                await budget_service.mark_status(
                    user_id=user_id,
                    operation_id=operation_id,
                    status="error",
                    error_message=str(exc),
                )
                await budget_service.release_reservation(
                    user_id=user_id,
                    operation_id=operation_id,
                    reason="error",
                )
                reservation_released = True
                raise

            cost_service = get_cost_service(firebase_service)
            usage_obj = TokenUsage.from_any(
                openai_result.get("input_tokens", 0),
                openai_result.get("cached_input_tokens", 0),
                openai_result.get("output_tokens", 0),
            )
            cost_breakdown, matched_model, pricing, _match_type = (
                await cost_service.calculate_cost(
                    model=openai_result.get("model") or model,
                    usage=usage_obj,
                )
            )

            kapitel = await firebase_service.get_kapitel(user_id, kapitel_id)
            projekt_id = (kapitel or {}).get("projektId")

            projekt_snapshot = None
            if projekt_id:
                project = await firebase_service.get_project(user_id, projekt_id)
                if project:
                    projekt_snapshot = {
                        "id": projekt_id,
                        "name": project.get("name"),
                        "archived": bool(project.get("archived", False)),
                    }

            kapitel_snapshot = (
                {
                    "id": kapitel_id,
                    "nummer": (kapitel or {}).get("nummer", "?"),
                    "title": (kapitel or {}).get("title", "Untitled"),
                }
                if kapitel
                else None
            )

            run_snapshot = {
                "id": run_id,
                "index": (run or {}).get("index"),
            }

            quelle_snapshot = {
                "id": quelle_id,
                "title": quelle.get("title"),
            }

            await cost_service.log_operation(
                operation_id=operation_id,
                operation_type="refine_result",
                user_id=user_id,
                user_action_id=version_id,
                operation_details={
                    "versionId": version_id,
                    "parentVersionId": parent_version_id,
                    "hasUserMessage": bool((user_message or "").strip()),
                    "quelleHasImages": bool(quelle_images),
                },
                model=openai_result.get("model") or model,
                usage=usage_obj,
                cost_breakdown=cost_breakdown,
                matched_model_key=matched_model,
                pricing=pricing,
                key_source=key_source,
                projekt_id=projekt_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                quelle_id=quelle_id,
                projekt_snapshot=projekt_snapshot,
                kapitel_snapshot=kapitel_snapshot,
                run_snapshot=run_snapshot,
                quelle_snapshot=quelle_snapshot,
            )

            cost = float(cost_breakdown.total_cost_usd)
            await budget_service.release_reservation(
                user_id=user_id,
                operation_id=operation_id,
                reason="success",
            )
            reservation_released = True

            version_update = {
                "assistantText": openai_result["content"],
                "hasContent": bool(openai_result.get("has_content", True)),
                "status": "success",
                "model": openai_result["model"],
                "usage": {
                    "inputTokens": int(openai_result["input_tokens"]),
                    "cachedInputTokens": int(
                        openai_result.get("cached_input_tokens", 0)
                    ),
                    "outputTokens": int(openai_result["output_tokens"]),
                    "reasoningTokens": int(openai_result.get("reasoning_tokens", 0)),
                    "totalTokens": int(openai_result["tokens"]),
                },
                "costUsd": float(cost),
                "keySource": key_source,
                "updatedAt": SERVER_TIMESTAMP,
            }

            await firebase_service.update_result_refinement_version(
                user_id, kapitel_id, run_id, quelle_id, version_id, version_update
            )

            await firebase_service.increment_result_refinement_cost_total(
                user_id, kapitel_id, run_id, quelle_id, float(cost)
            )

        except Exception as e:
            logger.error(
                f"Result refinement failed for kapitel {kapitel_id}, run {run_id}, quelle {quelle_id}, version {version_id}: {e}",
                exc_info=True,
            )
            try:
                if "budget_service" in locals() and "operation_id" in locals() and not locals().get("reservation_released"):
                    await budget_service.release_reservation(
                        user_id=user_id,
                        operation_id=operation_id,
                        reason="error",
                    )
            except Exception:
                pass
            try:
                await firebase_service.update_result_refinement_version(
                    user_id,
                    kapitel_id,
                    run_id,
                    quelle_id,
                    version_id,
                    {
                        "status": "error",
                        "errorMessage": AI_GENERIC_ERROR_MESSAGE,
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                )
            except Exception:
                pass
        finally:
            try:
                await firebase_service.increment_run_refinement_running_count(
                    user_id=user_id,
                    kapitel_id=kapitel_id,
                    run_id=run_id,
                    delta=-1,
                )
            except Exception:
                pass


refinement_service = RefinementService()
