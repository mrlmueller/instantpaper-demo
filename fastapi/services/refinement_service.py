import logging
import asyncio
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.firebase_service import firebase_service, AI_GENERIC_ERROR_MESSAGE
from services.openai_service import openai_service
from services.prompt_service import prompt_service
from services.cost_service import get_cost_service, TokenUsage
from services.shorten_service import shorten_service
from services.user_key_service import user_key_service
from utils.config import config

logger = logging.getLogger(__name__)


class RefinementService:
    """Text refinement flow service (phase 1+: combined + shortened + lesefluss + per-result texts)."""

    def __init__(self) -> None:
        pass

    async def init_combined_refinement(self, user_id: str, kapitel_id: str, run_id: str) -> dict:
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

    async def init_shortened_refinement(self, user_id: str, kapitel_id: str, run_id: str) -> dict:
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

    async def init_lesefluss_refinement(self, user_id: str, kapitel_id: str, run_id: str) -> dict:
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
            raise ValueError("Not enough eligible texts to refine (need at least 2 with content).")

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
        thema = (run.get("thema", "") or "").strip() or (run.get("instruction", "") or "").strip() or "Thema"

        results = await firebase_service.get_run_results(user_id, kapitel_id, run_id)
        eligible: list[dict] = []
        for res in results:
            if not res.get("hasContent", True):
                continue
            content = res.get("content")
            if content:
                eligible.append({"id": res.get("id"), "content": content})

        if len(eligible) < 2:
            raise ValueError("Not enough eligible texts to refine (need at least 2 with content).")

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
        self, user_id: str, kapitel_id: str, run_id: str, quelle_id: str, head_version_id: str
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
        combine_instructions: str,
        history_path: list[dict],
        parent_text: str,
        user_message: str,
    ) -> str:
        history_blocks: list[str] = []
        for v in history_path:
            version_id = v.get("id")
            if version_id == "root":
                history_blocks.append(
                    "ASSISTANT (Root / Ausgangstext):\n" + (v.get("assistantText") or "")
                )
                continue
            history_blocks.append(
                "USER:\n"
                + (v.get("userMessage") or "")
                + "\n\nASSISTANT:\n"
                + (v.get("assistantText") or "")
            )

        history_text = "\n\n---\n\n".join(history_blocks) if history_blocks else "Keine bisherigen Iterationen."

        return f"""{combine_instructions}

### Text Refinement Flow (Kombinierter Text)
Du wirst gleich die ursprünglichen Einzeltexte sehen, aus denen der kombinierte Text erstellt wurde.

### Bisheriger Verlauf
{history_text}

### Aktueller Text (zu überarbeiten)
{parent_text}

### Neue Nutzeranweisung
{user_message}

### Aufgabe
Schreibe den kombinierten Text neu und setze die neue Nutzeranweisung um.
WICHTIG:
- Nutze ausschließlich Informationen aus den gleich folgenden Einzeltexten.
- Behalte Zitate/Quellen wie [1] bei, sofern die Information erhalten bleibt.
- Gib ausschließlich den finalen Text aus (keine Erklärungen).
"""

    def _get_prompt_dump_path(self, prefix: str, version_id: str) -> str | None:
        if not config.DUMP_REFINEMENT_PROMPTS:
            return None

        # TODO(text-refinement): Remove this debug dump once prompts are validated end-to-end.
        base_dir = Path(__file__).resolve().parent.parent / ".prompt_dumps"
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}_{version_id}.md"
        return str(base_dir / filename)

    def _split_lesefluss_output(self, output_text: str) -> tuple[str, str]:
        """
        Split lesefluss output into (content, explanation).
        The system prompt asks for 2 sentences at the end; we heuristically take the last paragraph.
        """
        lines = (output_text or "").split("\n")
        last_empty_idx = -1
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == "":
                last_empty_idx = i
                break

        if last_empty_idx > 0:
            content_lines = lines[:last_empty_idx]
            explanation_lines = lines[last_empty_idx + 1 :]
        else:
            content_lines = lines
            explanation_lines = []

        content = "\n".join(content_lines).strip()
        explanation = " ".join([l.strip() for l in explanation_lines if l.strip()]).strip()
        if not explanation:
            explanation = "Keine Erklärung gefunden."
        return content, explanation

    def _build_lesefluss_refinement_prompt_body(
        self,
        lesefluss_instructions: str,
        gliederung: str,
        base_target_text: str,
        history_path: list[dict],
        parent_text: str,
        user_message: str,
        kapitel_nummer: str,
    ) -> str:
        history_blocks: list[str] = []
        for v in history_path:
            version_id = v.get("id")
            if version_id == "root":
                history_blocks.append(
                    "ASSISTANT (Root / Ausgangstext):\n" + (v.get("assistantText") or "")
                )
                continue
            history_blocks.append(
                "USER:\n"
                + (v.get("userMessage") or "")
                + "\n\nASSISTANT:\n"
                + (v.get("assistantText") or "")
            )

        history_text = "\n\n---\n\n".join(history_blocks) if history_blocks else "Keine bisherigen Iterationen."

        return f"""{lesefluss_instructions}

### Text Refinement Flow (Verbesserter Text / Lesefluss)

### Gliederung (Kontext-Zusammenfassungen)
{gliederung}

### Ausgangstext (Gekuerzter Text)
{base_target_text}

### Bisheriger Verlauf
{history_text}

### Aktueller Text (Kapitel {kapitel_nummer}, zu ueberarbeiten)
{parent_text}

### Neue Nutzeranweisung
{user_message}

### Aufgabe
Schreibe den verbesserten Text neu und setze die neue Nutzeranweisung um.
WICHTIG:
- Nutze ausschliesslich Informationen aus dem Ausgangstext und der Gliederung.
- Behalte Zitate/Quellen wie [1] bei, sofern die Information erhalten bleibt.
- Erfinde keine neuen Informationen oder Kapitel.
- Gib ausschliesslich den finalen Text aus (keine Erklaerungen im Text; die 2 Saetze am Ende sind ok).
"""

    def _build_result_refinement_user_input(
        self,
        base_user_input: str,
        history_path: list[dict],
        parent_text: str,
        user_message: str,
    ) -> str:
        history_blocks: list[str] = []
        for v in history_path:
            version_id = v.get("id")
            if version_id == "root":
                history_blocks.append(
                    "ASSISTANT (Root / Ausgangstext):\n" + (v.get("assistantText") or "")
                )
                continue
            history_blocks.append(
                "USER:\n"
                + (v.get("userMessage") or "")
                + "\n\nASSISTANT:\n"
                + (v.get("assistantText") or "")
            )

        history_text = "\n\n---\n\n".join(history_blocks) if history_blocks else "Keine bisherigen Iterationen."

        return f"""{base_user_input}

### Text Refinement Flow (Quellen-Text)

### Bisheriger Verlauf
{history_text}

### Aktueller Text (zu ueberarbeiten)
{parent_text}

### Neue Nutzeranweisung
{user_message}

### Aufgabe
Schreibe den Text neu und setze die neue Nutzeranweisung um.
WICHTIG:
- Nutze ausschliesslich Informationen aus der Quelle (Text + Bilder) und den obigen Anweisungen.
- Wenn die Quelle keine relevanten Infos enthaelt, antworte mit dem NO_CONTENT Sentinel wie im System-Prompt beschrieben.
- Gib ausschliesslich den finalen Text aus (keine Erklaerungen).
"""

    def _build_shortened_refinement_prompt_body(
        self,
        shorten_instructions: str,
        history_path: list[dict],
        parent_text: str,
        user_message: str,
    ) -> str:
        history_blocks: list[str] = []
        for v in history_path:
            version_id = v.get("id")
            if version_id == "root":
                history_blocks.append(
                    "ASSISTANT (Root / Ausgangstext):\n" + (v.get("assistantText") or "")
                )
                continue
            history_blocks.append(
                "USER:\n"
                + (v.get("userMessage") or "")
                + "\n\nASSISTANT:\n"
                + (v.get("assistantText") or "")
            )

        history_text = "\n\n---\n\n".join(history_blocks) if history_blocks else "Keine bisherigen Iterationen."

        return f"""{shorten_instructions}

### Text Refinement Flow (Gekuerzter Text)
Du wirst gleich die urspruenglichen Einzeltexte sehen, aus denen der kombinierte Text erstellt wurde.

### Bisheriger Verlauf
{history_text}

### Aktueller Text (gekuerzt, zu ueberarbeiten)
{parent_text}

### Neue Nutzeranweisung
{user_message}

### Aufgabe
Schreibe den gekuerzten Text neu und setze die neue Nutzeranweisung um.
WICHTIG:
- Nutze ausschliesslich Informationen aus den gleich folgenden Einzeltexten.
- Bleibe kurz, vermeide Wiederholungen und behalte die wissenschaftliche Schreibweise bei.
- Behalte Zitate/Quellen wie [1] bei, sofern die Information erhalten bleibt.
- Gib ausschliesslich den finalen Text aus (keine Erklaerungen, kein JSON).
"""

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
            raise ValueError(f"Max refinement depth reached ({init_state['max_depth']}).")

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
            api_key, key_source = await user_key_service.resolve_api_key_for_user(user_id)

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

            heading, topic, model, eligible = await self._get_heading_topic_and_base_texts(
                user_id, kapitel_id, run_id
            )

            combine_instructions = await prompt_service.get_rendered_instructions(
                user_id, "combine", {"heading": heading, "topic": topic}
            )
            combine_template_id = await firebase_service.get_active_prompt_id(user_id, "combine")
            combine_template_id = (combine_template_id or "").strip() or "default"
            combine_system_prompt = await prompt_service.get_system_prompt_for_template(
                stage="combine",
                template_id=combine_template_id,
            )

            history_path = await self._get_version_path(
                user_id, kapitel_id, run_id, parent_version_id
            )

            prompt_body = self._build_refinement_prompt_body(
                combine_instructions=combine_instructions,
                history_path=history_path,
                parent_text=parent_text,
                user_message=user_message,
            )

            source_texts = [e["content"] for e in eligible]
            debug_dump_path = self._get_prompt_dump_path("refine_combined", version_id)

            openai_result = await openai_service.combine_texts(
                source_texts,
                heading,
                topic,
                model,
                api_key=api_key,
                instructions=prompt_body,
                debug_prompt_dump_path=debug_dump_path,
                system_prompt=combine_system_prompt,
            )

            cost_service = get_cost_service(firebase_service)
            usage_obj = TokenUsage.from_any(
                openai_result.get("input_tokens", 0),
                openai_result.get("cached_input_tokens", 0),
                openai_result.get("output_tokens", 0),
            )
            cost_breakdown, matched_model, pricing, _match_type = await cost_service.calculate_cost(
                model=openai_result.get("model") or model,
                usage=usage_obj,
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

            version_update = {
                "assistantText": openai_result["content"],
                "hasContent": True,
                "status": "success",
                "model": openai_result["model"],
                "usage": {
                    "inputTokens": int(openai_result["input_tokens"]),
                    "cachedInputTokens": int(openai_result.get("cached_input_tokens", 0)),
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
            raise ValueError(f"Max refinement depth reached ({init_state['max_depth']}).")

        root = await firebase_service.get_shortened_refinement_version(
            user_id, kapitel_id, run_id, "root"
        )
        stage_model = (root or {}).get("model") or "gpt-5-mini"

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
            api_key, key_source = await user_key_service.resolve_api_key_for_user(user_id)

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

            ueberschrift, thema, eligible = await self._get_ueberschrift_thema_and_base_texts(
                user_id, kapitel_id, run_id
            )

            shorten_instructions = await prompt_service.get_rendered_instructions(
                user_id, "shorten", {"ueberschrift": ueberschrift, "thema": thema}
            )

            history_path = await self._get_shortened_version_path(
                user_id, kapitel_id, run_id, parent_version_id
            )

            prompt_body = self._build_shortened_refinement_prompt_body(
                shorten_instructions=shorten_instructions,
                history_path=history_path,
                parent_text=parent_text,
                user_message=user_message,
            )

            source_texts = [e["content"] for e in eligible]

            pending = await firebase_service.get_shortened_refinement_version(
                user_id, kapitel_id, run_id, version_id
            )
            model = (pending or {}).get("model") or "gpt-5-mini"

            debug_dump_path = self._get_prompt_dump_path("refine_shortened", version_id)

            openai_result = await openai_service.combine_texts(
                source_texts,
                ueberschrift,
                thema,
                model,
                api_key=api_key,
                instructions=prompt_body,
                debug_prompt_dump_path=debug_dump_path,
            )

            cost_service = get_cost_service(firebase_service)
            usage_obj = TokenUsage.from_any(
                openai_result.get("input_tokens", 0),
                openai_result.get("cached_input_tokens", 0),
                openai_result.get("output_tokens", 0),
            )
            cost_breakdown, matched_model, pricing, _match_type = await cost_service.calculate_cost(
                model=openai_result.get("model") or model,
                usage=usage_obj,
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
                operation_type="refine_shortened",
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

            version_update = {
                "assistantText": openai_result["content"],
                "hasContent": True,
                "status": "success",
                "model": openai_result["model"],
                "usage": {
                    "inputTokens": int(openai_result["input_tokens"]),
                    "cachedInputTokens": int(openai_result.get("cached_input_tokens", 0)),
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
            raise ValueError(f"Max refinement depth reached ({init_state['max_depth']}).")

        root = await firebase_service.get_lesefluss_refinement_version(
            user_id, kapitel_id, run_id, "root"
        )
        stage_model = (root or {}).get("model") or "gpt-5-mini"

        version_id = str(uuid4())
        pending = {
            "parentVersionId": parent_version_id,
            "depth": next_depth,
            "userMessage": user_message,
            "assistantText": "",
            "assistantExplanation": "",
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
            api_key, key_source = await user_key_service.resolve_api_key_for_user(user_id)

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

            lesefluss_doc = await firebase_service.get_lesefluss_result(user_id, kapitel_id, run_id)
            if not lesefluss_doc:
                raise ValueError("No lesefluss result found for this run.")

            aufgabenstellung = (lesefluss_doc.get("aufgabenstellung") or "").strip()
            if not aufgabenstellung:
                raise ValueError("Lesefluss aufgabenstellung is missing.")

            context_kapitel_ids = lesefluss_doc.get("usedKapitelIds") or []
            if not isinstance(context_kapitel_ids, list) or len(context_kapitel_ids) == 0:
                raise ValueError("Lesefluss context chapters are missing (usedKapitelIds).")

            shortened = await firebase_service.get_shortened_result(user_id, kapitel_id, run_id)
            if not shortened:
                raise ValueError("No shortened result found for this run.")
            base_target_text = (shortened.get("content") or "").strip()
            if not base_target_text:
                raise ValueError("Shortened content is empty.")

            pending = await firebase_service.get_lesefluss_refinement_version(
                user_id, kapitel_id, run_id, version_id
            )
            model = (pending or {}).get("model") or "gpt-5-mini"

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
            summaries_list = await asyncio.gather(*summary_tasks, return_exceptions=True)

            summaries: dict[str, str] = {}
            valid_context_ids: list[str] = []
            for ctx_id, summary_result in zip(context_kapitel_ids, summaries_list):
                if isinstance(summary_result, Exception):
                    logger.error(f"Failed to get summary for Kapitel {ctx_id}: {summary_result}")
                else:
                    summaries[str(ctx_id)] = str(summary_result)
                    valid_context_ids.append(str(ctx_id))

            if not summaries:
                raise ValueError("No valid summaries could be generated for context Kapitels.")

            context_kapitels: list[dict] = []
            for ctx_id in valid_context_ids:
                metadata = await firebase_service.get_kapitel_metadata(user_id, ctx_id)
                if metadata:
                    context_kapitels.append(metadata)

            context_kapitels.sort(key=lambda k: k.get('nummer', ''))
            gliederung = await shorten_service.build_gliederung_with_descriptions(
                user_id, kapitel_id, context_kapitels, summaries
            )

            target_meta = await firebase_service.get_kapitel_metadata(user_id, kapitel_id)
            kapitel_nummer = (target_meta or {}).get("nummer") or "?"

            lesefluss_instructions = await prompt_service.get_rendered_instructions(
                user_id,
                "lesefluss",
                {
                    "aufgabenstellung": aufgabenstellung,
                    "gliederung": gliederung,
                    "kapitel_nummer": str(kapitel_nummer),
                    "target_text": base_target_text,
                },
            )

            history_path = await self._get_lesefluss_version_path(
                user_id, kapitel_id, run_id, parent_version_id
            )

            prompt_body = self._build_lesefluss_refinement_prompt_body(
                lesefluss_instructions=lesefluss_instructions,
                gliederung=gliederung,
                base_target_text=base_target_text,
                history_path=history_path,
                parent_text=parent_text,
                user_message=user_message,
                kapitel_nummer=str(kapitel_nummer),
            )

            debug_dump_path = self._get_prompt_dump_path("refine_lesefluss", version_id)

            output_text, usage = await openai_service.improve_reading_flow(
                prompt_body,
                model,
                api_key=api_key,
                debug_prompt_dump_path=debug_dump_path,
            )

            content, explanation = self._split_lesefluss_output(output_text)

            input_tokens = int(usage.get("prompt_tokens", 0) or 0)
            cached_input_tokens = int(
                (usage.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0) or 0
            )
            output_tokens = int(usage.get("completion_tokens", 0) or 0)
            total_tokens = input_tokens + output_tokens

            cost_service = get_cost_service(firebase_service)
            usage_obj = TokenUsage.from_any(input_tokens, cached_input_tokens, output_tokens)
            cost_breakdown, matched_model, pricing, _match_type = await cost_service.calculate_cost(
                model=model,
                usage=usage_obj,
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
                model=model,
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

            version_update = {
                "assistantText": content,
                "assistantExplanation": explanation,
                "hasContent": True,
                "status": "success",
                "model": model,
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
            raise ValueError(f"Max refinement depth reached ({init_state['max_depth']}).")

        root = await firebase_service.get_result_refinement_version(
            user_id, kapitel_id, run_id, quelle_id, "root"
        )
        stage_model = (root or {}).get("model") or "gpt-5-mini"

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
            api_key, key_source = await user_key_service.resolve_api_key_for_user(user_id)

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

            result_doc = await firebase_service.get_run_result(user_id, kapitel_id, run_id, quelle_id)
            if not result_doc:
                raise ValueError("Result not found.")

            run = await firebase_service.get_run(user_id, kapitel_id, run_id)
            grundlegende_informationen = (run or {}).get("grundlegendeInformationen")

            base_user_input = (result_doc.get("userInput") or "").strip()
            # Prompts are no longer stored on result docs (hidden from user). Reconstruct from run settings.
            prompt_template_id = ((run or {}).get("promptTemplateId") or "").strip() or "default"

            if not base_user_input:

                payload: dict = {}
                raw_payload = (run or {}).get("promptPayload") or (run or {}).get("prompt_payload") or {}
                if isinstance(raw_payload, dict):
                    payload = {k: v for k, v in raw_payload.items()}

                # Backward-compat fallback for older runs.
                if run and not payload.get("heading") and (run.get("ueberschrift") or "").strip():
                    payload["heading"] = (run.get("ueberschrift") or "").strip()
                if run and not payload.get("topic") and (run.get("thema") or "").strip():
                    payload["topic"] = (run.get("thema") or "").strip()

                payload.setdefault("grundlegende_infos", (grundlegende_informationen or "").strip())

                heading = str(payload.get("heading") or "").strip()
                topic = str(payload.get("topic") or "").strip()
                grund_infos = str(payload.get("grundlegende_infos") or "").strip()
                if not heading or not topic:
                    raise ValueError("Run promptPayload is missing heading/topic.")

                base_user_input = await prompt_service.get_rendered_instructions_for_template(
                    user_id=user_id,
                    stage="process_quelle",
                    template_id=prompt_template_id,
                    payload={
                        "heading": heading,
                        "topic": topic,
                        "grundlegende_infos": grund_infos,
                        "KAPITEL_TITEL": heading,
                        "KAPITEL_BESCHREIBUNG": topic,
                        "ANWEISUNGEN": topic,
                    },
                )

            history_path = await self._get_result_version_path(
                user_id, kapitel_id, run_id, quelle_id, parent_version_id
            )

            refined_user_input = self._build_result_refinement_user_input(
                base_user_input=base_user_input,
                history_path=history_path,
                parent_text=parent_text,
                user_message=user_message,
            )

            pending = await firebase_service.get_result_refinement_version(
                user_id, kapitel_id, run_id, quelle_id, version_id
            )
            model = (pending or {}).get("model") or "gpt-5-mini"

            quelle = await firebase_service.get_quelle(user_id, quelle_id)
            if not quelle:
                raise ValueError("Quelle not found.")

            quelle_content_doc = await firebase_service.get_quelle_content(user_id, quelle_id)
            if not quelle_content_doc or not (quelle_content_doc.get("text") or "").strip():
                raise ValueError("Quelle content is empty.")

            quelle_images = None
            if 'images' in quelle and isinstance(quelle['images'], list):
                quelle_images = [img['url'] for img in quelle['images'] if 'url' in img]

            debug_dump_path = self._get_prompt_dump_path("refine_result", version_id)

            system_prompt = await prompt_service.get_system_prompt_for_template(
                stage="process_quelle",
                template_id=prompt_template_id,
            )

            openai_result = await openai_service.process_quelle(
                quelle_content_doc.get("text") or "",
                refined_user_input,
                model,
                grundlegende_informationen,
                api_key=api_key,
                quelle_images=quelle_images,
                debug_prompt_dump_path=debug_dump_path,
                system_prompt=system_prompt,
            )

            cost_service = get_cost_service(firebase_service)
            usage_obj = TokenUsage.from_any(
                openai_result.get("input_tokens", 0),
                openai_result.get("cached_input_tokens", 0),
                openai_result.get("output_tokens", 0),
            )
            cost_breakdown, matched_model, pricing, _match_type = await cost_service.calculate_cost(
                model=openai_result.get("model") or model,
                usage=usage_obj,
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

            version_update = {
                "assistantText": openai_result["content"],
                "hasContent": bool(openai_result.get("has_content", True)),
                "status": "success",
                "model": openai_result["model"],
                "usage": {
                    "inputTokens": int(openai_result["input_tokens"]),
                    "cachedInputTokens": int(openai_result.get("cached_input_tokens", 0)),
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


refinement_service = RefinementService()
