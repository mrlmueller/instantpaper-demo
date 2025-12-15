import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.firebase_service import firebase_service
from services.openai_service import openai_service
from services.prompt_service import prompt_service
from services.quelle_service import calculate_cost
from services.user_key_service import user_key_service
from utils.config import config

logger = logging.getLogger(__name__)


class RefinementService:
    """Text refinement flow service (phase 1–2: combined text only)."""

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

    async def _get_heading_topic_and_base_texts(
        self, user_id: str, kapitel_id: str, run_id: str
    ) -> tuple[str, str, list[dict]]:
        run = await firebase_service.get_run(user_id, kapitel_id, run_id)
        if not run:
            raise ValueError("Run not found.")

        prompt_payload = run.get("promptPayload") or run.get("prompt_payload") or {}
        heading = (prompt_payload.get("heading", "") or "").strip() or "Zusammenfassung"
        topic = (prompt_payload.get("topic", "") or "").strip() or "Thema"

        results = await firebase_service.get_run_results(user_id, kapitel_id, run_id)
        eligible: list[dict] = []
        for res in results:
            if not res.get("has_content", True):
                continue
            content = (
                res.get("result_content")
                or res.get("resultContent")
                or res.get("content")
            )
            if content:
                eligible.append({"id": res.get("id"), "content": content})

        if len(eligible) < 2:
            raise ValueError("Not enough eligible texts to refine (need at least 2 with content).")

        # Deterministic ordering (useful for caching/debugging)
        eligible.sort(key=lambda item: str(item.get("id") or ""))

        return heading, topic, eligible

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
            current_id = version.get("parent_version_id")

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
                    "ASSISTANT (Root / Ausgangstext):\n" + (v.get("assistant_text") or "")
                )
                continue
            history_blocks.append(
                "USER:\n"
                + (v.get("user_message") or "")
                + "\n\nASSISTANT:\n"
                + (v.get("assistant_text") or "")
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

    def _maybe_dump_prompt(self, version_id: str, prompt: str) -> None:
        if not config.DUMP_REFINEMENT_PROMPTS:
            return

        # TODO(text-refinement): Remove this debug dump once prompts are validated end-to-end.
        base_dir = Path(__file__).resolve().parent.parent / ".prompt_dumps"
        base_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"refine_combined_{timestamp}_{version_id}.md"
        (base_dir / filename).write_text(prompt, encoding="utf-8")

    async def queue_combined_refinement(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        parent_version_id: str,
        user_message: str,
        model: str,
    ) -> dict:
        """
        Create a pending refinement version doc and return queued info.
        Background processing must be scheduled by the caller.
        """
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
            "parent_version_id": parent_version_id,
            "depth": next_depth,
            "user_message": user_message,
            "assistant_text": "",
            "status": "running",
            "model": model,
            "cost": 0.0,
            "created_at": SERVER_TIMESTAMP,
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
        model: str,
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

            parent_text = parent.get("assistant_text") or ""
            if not parent_text:
                raise ValueError("Parent text is empty.")

            heading, topic, eligible = await self._get_heading_topic_and_base_texts(
                user_id, kapitel_id, run_id
            )

            combine_instructions = await prompt_service.get_rendered_instructions(
                user_id, "combine", {"heading": heading, "topic": topic}
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

            # For debugging, dump the exact prompt that will be sent (includes appended source texts)
            combined_texts = "\n\n".join(
                [f"### Text {i+1}:\n{source_texts[i]}" for i in range(len(source_texts))]
            )
            full_prompt = f"{prompt_body}\n\n{combined_texts}"
            self._maybe_dump_prompt(version_id, full_prompt)

            openai_result = await openai_service.combine_texts(
                source_texts,
                heading,
                topic,
                model,
                api_key=api_key,
                instructions=prompt_body,
            )

            cost = calculate_cost(
                model=openai_result["model"],
                input_tokens=openai_result["input_tokens"],
                cached_input_tokens=openai_result.get("cached_input_tokens", 0),
                output_tokens=openai_result["output_tokens"],
                reasoning_tokens=openai_result.get("reasoning_tokens", 0),
            )

            version_update = {
                "assistant_text": openai_result["content"],
                "status": "success",
                "model": openai_result["model"],
                "usage": {
                    "input_tokens": openai_result["input_tokens"],
                    "cached_input_tokens": openai_result.get("cached_input_tokens", 0),
                    "output_tokens": openai_result["output_tokens"],
                    "reasoning_tokens": openai_result.get("reasoning_tokens", 0),
                    "total_tokens": openai_result["tokens"],
                },
                "cost": float(cost),
                "key_source": key_source,
                "updated_at": datetime.utcnow().isoformat() + "Z",
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
                        "error_message": str(e),
                        "updated_at": datetime.utcnow().isoformat() + "Z",
                    },
                )
            except Exception:
                pass


refinement_service = RefinementService()
