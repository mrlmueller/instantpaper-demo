from fastapi import HTTPException
from services.firebase_service import firebase_service
from services.openai_service import NO_CONTENT_SENTINEL, openai_service
from services.cost_service import get_cost_service, TokenUsage
from services.credits_service import get_credits_service
from services.openai_budget_service import get_openai_budget_service
from services.openai_estimation_service import get_openai_estimation_service
from services.user_key_service import user_key_service
from services.prompt_service import prompt_service
from utils.quellen_zitat import resolve_quelle_zitat_value
import logging
import asyncio
import uuid
from typing import Optional, List

logger = logging.getLogger(__name__)


def _build_process_quelle_prompt_text(
    *,
    quelle_text: str,
    user_input_template: str,
    grundlegende_informationen: str | None,
) -> str:
    template = (user_input_template or "").replace("{BILDINHALT_ODER_LEER}", "")
    has_quelltext_placeholder = "{QUELLTEXT}" in template
    has_basic_info_placeholder = "{OPTIONAL_GRUNDLEGENDE_INFOS}" in template

    if has_basic_info_placeholder:
        template = template.replace(
            "{OPTIONAL_GRUNDLEGENDE_INFOS}",
            (grundlegende_informationen or "").strip(),
        )

    if has_quelltext_placeholder:
        return template.replace("{QUELLTEXT}", quelle_text or "")

    # Backward-compatible v1 layout: source text first, optional basic info, then instructions.
    if grundlegende_informationen and grundlegende_informationen.strip() and not has_basic_info_placeholder:
        return f"""{quelle_text}

### Grundlegende Informationen
{grundlegende_informationen}

{template}"""

    return f"""{quelle_text}

{template}"""

def calculate_groups(num_items: int, min_group_size: int = 4, max_group_size: int = 5) -> List[List[int]]:
    "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
    if num_items <= max_group_size:
        return [list(range(num_items))]

    # Aim for groups of max_group_size, adjust for even distribution
    num_groups = (num_items + max_group_size - 1) // max_group_size  # ceil(num_items / max_group_size)
    base_size = num_items // num_groups
    remainder = num_items % num_groups

    groups = []
    idx = 0
    for i in range(num_groups):
        # Distribute remainder items to first groups
        size = base_size + (1 if i < remainder else 0)
        groups.append(list(range(idx, idx + size)))
        idx += size

    return groups


class QuelleService:
    """Service for Quelle processing operations"""

    def __init__(self):
        """Initialize Quelle service"""
        self.firebase = firebase_service
        self.openai = openai_service
        logger.info("Quelle service initialized")

    async def process_single_quelle(
        self,
        user_id: str,
        quelle_id: str,
        kapitel_id: str,
        run_id: str,
        model: str
    ) -> dict:
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        try:
            if not kapitel_id or not run_id:
                raise HTTPException(
                    status_code=400,
                    detail="kapitel_id and run_id are required to save results"
                )

            # Step 1: Fetch Quelle meta + content (V2 stores content separately)
            logger.info(f"Fetching Quelle {quelle_id} for user {user_id}")
            quelle_meta = await self.firebase.get_quelle_meta(user_id, quelle_id)
            if not quelle_meta:
                logger.warning(f"Quelle {quelle_id} not found for user {user_id}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Quelle {quelle_id} not found or you don't have access to it",
                )

            quelle_content_doc = await self.firebase.get_quelle_content(user_id, quelle_id)
            if not quelle_content_doc or not (quelle_content_doc.get("text") or "").strip():
                raise HTTPException(
                    status_code=400,
                    detail=f"Quelle {quelle_id} has no content. Please open/edit the Quelle first.",
                )

            # Step 1.5: Fetch run to get grundlegendeInformationen
            run = await self.firebase.get_run(user_id, kapitel_id, run_id)
            grundlegende_informationen = run.get('grundlegendeInformationen') if run else None

            # Resolve and render the prompt server-side (prompts are not sent from the client).
            prompt_template_id = (run.get("promptTemplateId") or "").strip() if run else ""
            prompt_template_id = prompt_template_id or "default"

            payload: dict = {}
            raw_payload = (run.get("promptPayload") or run.get("prompt_payload")) if run else None
            if isinstance(raw_payload, dict):
                payload = {k: v for k, v in raw_payload.items()}

            # Backward-compat fallback for older runs.
            if run and not payload.get("heading") and (run.get("ueberschrift") or "").strip():
                payload["heading"] = (run.get("ueberschrift") or "").strip()
            if run and not payload.get("topic") and (run.get("thema") or "").strip():
                payload["topic"] = (run.get("thema") or "").strip()

            if not (str(payload.get("heading") or "").strip()):
                raise HTTPException(status_code=400, detail="Run is missing heading/promptPayload.heading.")
            if not (str(payload.get("topic") or "").strip()):
                raise HTTPException(status_code=400, detail="Run is missing topic/promptPayload.topic.")

            heading = str(payload.get("heading") or "").strip()
            topic = str(payload.get("topic") or "").strip()

            quelle_zitat_value = resolve_quelle_zitat_value(quelle_meta)

            rendered_instructions = await prompt_service.get_rendered_instructions_for_template(
                user_id=user_id,
                stage="process_quelle",
                template_id=prompt_template_id,
                payload={
                    "KAPITEL_TITEL": heading,
                    "KAPITEL_BESCHREIBUNG": topic,
                    "QUELLE_ZITAT": quelle_zitat_value,
                },
            )
            system_prompt = await prompt_service.get_system_prompt_for_template(
                stage="process_quelle",
                template_id=prompt_template_id,
            )
            run_model = (run.get("model") or "").strip() if run else ""
            if run_model:
                if model and model != run_model:
                    logger.info(
                        f"Overriding requested model '{model}' with run model '{run_model}' "
                        f"(Kapitel {kapitel_id}, run {run_id})"
                    )
                model = run_model

            # Step 1.6: Extract image URLs from Quelle (if any)
            quelle_images = None
            quelle_image_meta = None
            if isinstance(quelle_meta.get("images"), list):
                image_dicts = [img for img in quelle_meta["images"] if isinstance(img, dict)]
                urls = [str(img.get("url") or "").strip() for img in image_dicts if str(img.get("url") or "").strip()]
                if urls:
                    quelle_images = urls
                    quelle_image_meta = image_dicts
                    logger.info(f"Quelle has {len(quelle_images)} image(s)")

            # Step 2: Process with OpenAI
            api_key, key_source = await user_key_service.resolve_api_key_for_user(user_id)
            logger.info(f"Processing Quelle {quelle_id} with OpenAI model {model}")

            quelle_text = quelle_content_doc.get("text") or ""
            prompt_text = _build_process_quelle_prompt_text(
                quelle_text=quelle_text,
                user_input_template=rendered_instructions,
                grundlegende_informationen=grundlegende_informationen,
            )
            system_message = (system_prompt or "").strip() or (
                "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
                "You can analyze both text and images provided. "
                "Think step-by-step to ensure correctness. "
                f"If the Quelle does NOT contain any useful information for the request, respond with the single token '{NO_CONTENT_SENTINEL}' only. "
                "Otherwise, return only the final answer without any extra commentary."
            )

            workflow_id = uuid.uuid4().hex
            operation_id = f"{workflow_id}_process_quelle_{quelle_id}"

            estimation_service = get_openai_estimation_service(firebase_service)
            estimate_obj = await estimation_service.estimate_operation(
                user_id=user_id,
                operation_type="process_quelle",
                model=model,
                system_text=system_message,
                user_text=prompt_text,
                output_source_text=quelle_text,
                images=quelle_image_meta,
            )

            budget_service = get_openai_budget_service(firebase_service)
            reservation_released = False

            reservation = await budget_service.reserve_operation(
                user_id=user_id,
                operation_id=operation_id,
                operation_type="process_quelle",
                user_action_id=run_id,
                estimate=estimate_obj.to_dict(),
                kapitel_id=kapitel_id,
                run_id=run_id,
                quelle_id=quelle_id,
                operation_details={"quelleHasImages": bool(quelle_images)},
            )
            if reservation.result == "blocked":
                raise HTTPException(
                    status_code=402,
                    detail="Kein Guthaben verfügbar. Bitte lade Credits im Profil unter Billing auf.",
                )
            if reservation.result in {"already_reserved", "finalized"}:
                raise HTTPException(
                    status_code=409,
                    detail="Operation already exists. Please retry later.",
                )

            await budget_service.mark_running(user_id=user_id, operation_id=operation_id)

            try:
                openai_result = await self.openai.process_quelle(
                    quelle_text,
                    rendered_instructions,
                    model,
                    grundlegende_informationen,
                    api_key=api_key,
                    quelle_images=quelle_images,
                    system_prompt=system_prompt,
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

            # Step 2.5: Calculate cost and log immutable operation (costMetrics)
            cost_service = get_cost_service(firebase_service)
            usage = TokenUsage.from_any(
                openai_result.get("input_tokens", 0),
                openai_result.get("cached_input_tokens", 0),
                openai_result.get("output_tokens", 0),
            )

            cost_breakdown, matched_model, pricing, _match_type = await cost_service.calculate_cost(
                model=openai_result.get("model") or model,
                usage=usage,
            )

            kapitel = await self.firebase.get_kapitel(user_id, kapitel_id)
            projekt_id = (kapitel or {}).get("projektId")

            projekt_snapshot = None
            if projekt_id:
                project = await self.firebase.get_project(user_id, projekt_id)
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
                "title": quelle_meta.get("title"),
            }

            await cost_service.log_operation(
                operation_id=operation_id,
                operation_type="process_quelle",
                user_id=user_id,
                user_action_id=run_id,
                operation_details={
                    "hasContent": bool(openai_result.get("has_content", True)),
                    "quelleHasImages": bool(quelle_images),
                },
                model=openai_result.get("model") or model,
                usage=usage,
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

            await budget_service.release_reservation(
                user_id=user_id,
                operation_id=operation_id,
                reason="success",
            )
            reservation_released = True

            cost = float(cost_breakdown.total_cost_usd)

            # Step 3: Save result to Firestore under the Kapitel run
            logger.info(f"Saving result for Quelle {quelle_id} in Kapitel {kapitel_id} run {run_id} (cost: ${cost:.6f})")
            result_id = await self.firebase.save_result(
                user_id=user_id,
                quelle_id=quelle_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                result_content=openai_result['content'],
                has_content=openai_result.get('has_content', True),
                model_used=openai_result['model'],
                tokens_used=usage.total_tokens,
                input_tokens=usage.input_tokens,
                cached_input_tokens=usage.cached_input_tokens,
                output_tokens=usage.output_tokens,
                reasoning_tokens=0,
                cost=cost,
                key_source=key_source
            )

            logger.info(f"Quelle processing complete. Result ID: {result_id}, Cost: ${cost:.6f}")

            # Check if we should trigger auto-combine
            await self._check_and_trigger_auto_combine(user_id, kapitel_id, run_id)

            return {
                "result_id": result_id,
                "content": openai_result['content'],
                "has_content": openai_result.get('has_content', True),
                "model": openai_result['model'],
                "tokens": usage.total_tokens,
                "input_tokens": usage.input_tokens,
                "cached_input_tokens": usage.cached_input_tokens,
                "output_tokens": usage.output_tokens,
                "reasoning_tokens": 0,
                "cost": cost
            }

        except HTTPException:
            # Re-raise HTTP exceptions
            try:
                if "operation_id" in locals() and "budget_service" in locals() and not locals().get("reservation_released"):
                    await budget_service.release_reservation(
                        user_id=user_id,
                        operation_id=operation_id,
                        reason="error",
                    )
            except Exception:
                pass
            raise
        except Exception as e:
            logger.error(f"Error processing Quelle: {str(e)}")
            try:
                if "operation_id" in locals() and "budget_service" in locals() and not locals().get("reservation_released"):
                    await budget_service.release_reservation(
                        user_id=user_id,
                        operation_id=operation_id,
                        reason="error",
                    )
            except Exception:
                pass
            raise HTTPException(
                status_code=500,
                detail=f"Failed to process Quelle: {str(e)}"
            )

    async def _check_and_trigger_auto_combine(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str
    ):
        """
        Check if all Quellen are processed and trigger auto-combine if enabled.
        This is called after each Quelle finishes processing.
        """
        try:
            # Get the run to check if auto-combine is enabled
            run = await self.firebase.get_run(user_id, kapitel_id, run_id)
            if not run:
                logger.warning(f"Run {run_id} not found, skipping auto-combine check")
                return

            auto_combine = run.get('autoCombine', False)
            if not auto_combine:
                logger.debug(f"Auto-combine not enabled for run {run_id}")
                return

            # Check if a combined result already exists
            existing_combined = await self.firebase.get_combined_result(user_id, kapitel_id, run_id)
            if existing_combined:
                logger.info(f"Combined result already exists for run {run_id}, skipping")
                return

            # Check if all Quellen are processed
            all_processed, content_count = await self.firebase.check_all_quellen_processed(
                user_id, kapitel_id, run_id
            )

            if not all_processed:
                logger.info(f"Not all Quellen processed yet for run {run_id}, skipping auto-combine")
                return

            if content_count < 2:
                if content_count == 1:
                    logger.info(
                        f"Auto-combine passthrough for run {run_id}: exactly 1 text with content. "
                        "Adopting it as combined text..."
                    )
                    try:
                        await self.adopt_single_result_as_combined(
                            user_id=user_id,
                            kapitel_id=kapitel_id,
                            run_id=run_id,
                            quelle_id=None,
                        )
                    except HTTPException as exc:
                        # If we can't adopt (e.g. eligibility mismatch), reset status so the UI does not spin forever.
                        logger.warning(
                            f"Auto-adopt failed for run {run_id} (HTTP {exc.status_code}): {exc.detail}"
                        )
                        await self.firebase.set_run_artifact_status(
                            user_id=user_id,
                            kapitel_id=kapitel_id,
                            run_id=run_id,
                            artifact_id="combined",
                            status="empty",
                        )
                    except Exception as exc:
                        logger.error(f"Auto-adopt failed for run {run_id}: {exc}", exc_info=True)
                        await self.firebase.mark_artifact_error(
                            user_id=user_id,
                            kapitel_id=kapitel_id,
                            run_id=run_id,
                            artifact_id="combined",
                            key_source=None,
                        )
                    return

                logger.info(
                    f"Auto-combine skipped for run {run_id}: only {content_count} text(s) with content "
                    "(need at least 2)"
                )
                # Auto-combine is enabled, but we can't combine. Reset combined stage status so the UI
                # does not show an infinite "combining..." state.
                await self.firebase.set_run_artifact_status(
                    user_id=user_id,
                    kapitel_id=kapitel_id,
                    run_id=run_id,
                    artifact_id="combined",
                    status="empty",
                )
                return

            # All conditions met - trigger auto-combine after delay
            logger.info(
                f"All Quellen processed for run {run_id} with {content_count} texts having content. "
                "Triggering auto-combine after 2.5 second delay..."
            )

            # Wait 2.5 seconds before combining
            await asyncio.sleep(2.5)

            # Trigger combine
            logger.info(f"Starting auto-combine for run {run_id}")
            await self.combine_run_results(user_id, kapitel_id, run_id)
            logger.info(f"Auto-combine completed successfully for run {run_id}")

        except Exception as e:
            # Log the error but don't fail the Quelle processing
                logger.error(f"Error in auto-combine check for run {run_id}: {str(e)}")

    async def adopt_single_result_as_combined(
        self,
        *,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        quelle_id: Optional[str] = None,
    ) -> dict:
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        run = await self.firebase.get_run(user_id, kapitel_id, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        existing_combined = await self.firebase.get_combined_result(user_id, kapitel_id, run_id)
        if existing_combined:
            existing_status = (existing_combined.get("status") or "").strip()
            existing_content = (existing_combined.get("content") or "").strip()
            if existing_status == "running":
                raise HTTPException(status_code=400, detail="Kombination läuft bereits.")
            if existing_content and (existing_status == "success" or not existing_status):
                raise HTTPException(status_code=400, detail="Kombinierter Text existiert bereits für diesen Run.")

        prompt_payload = run.get("promptPayload") or run.get("prompt_payload") or {}
        heading = (
            (prompt_payload.get("heading") or "").strip()
            or (run.get("ueberschrift") or "").strip()
            or "Zusammenfassung"
        )
        topic = (
            (prompt_payload.get("topic") or "").strip()
            or (run.get("thema") or "").strip()
            or "Thema"
        )
        run_model = (run.get("model") or "").strip() or "gpt-5.2"

        results = await self.firebase.get_run_results(user_id, kapitel_id, run_id)
        eligible = []
        for res in results:
            status_value = (res.get("status") or "").strip()
            if status_value in {"running", "error", "no-content"}:
                continue
            if not bool(res.get("hasContent", True)):
                continue
            content = (res.get("content") or "")
            if content and content.strip():
                eligible.append(
                    {
                        "id": res.get("id"),
                        "content": content,
                        "model": (res.get("model") or "").strip(),
                    }
                )

        if len(eligible) != 1:
            raise HTTPException(
                status_code=400,
                detail="Not exactly one eligible text to adopt (need exactly 1 with content).",
            )

        selected_id = (quelle_id or "").strip() or str(eligible[0]["id"])
        if selected_id != str(eligible[0]["id"]):
            raise HTTPException(
                status_code=400,
                detail="Selected Quelle is not the only eligible text for this run.",
            )

        source_quelle_ids = [selected_id]
        model_used = eligible[0].get("model") or run_model

        combined_id = await self.firebase.save_combined_result(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            combined_content=str(eligible[0]["content"]),
            source_quelle_ids=source_quelle_ids,
            heading=heading,
            topic=topic,
            model_used=model_used,
            tokens_used=0,
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            reasoning_tokens=0,
            cost=0.0,
            key_source=None,
        )

        return {
            "combined_id": combined_id,
            "content": str(eligible[0]["content"]),
            "model": model_used,
            "tokens": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "cost": 0.0,
            "source_quelle_ids": source_quelle_ids,
            "heading": heading,
            "topic": topic,
        }

    async def combine_run_results(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str
    ) -> dict:
        """
        Combine multiple Quelle results for a run into a single text.
        """
        api_key: Optional[str] = None
        key_source: Optional[str] = None
        marked_running = False

        try:
            run = await self.firebase.get_run(user_id, kapitel_id, run_id)
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")

            api_key, key_source = await user_key_service.resolve_api_key_for_user(user_id)

            existing_combined = await self.firebase.get_combined_result(user_id, kapitel_id, run_id)
            if existing_combined:
                existing_status = (existing_combined.get("status") or "").strip()
                existing_content = (existing_combined.get("content") or "").strip()
                # Allow if a placeholder exists (status=running) or a previous attempt errored.
                # Block only if we already have a finished combined text.
                if existing_content and (existing_status == "success" or not existing_status):
                    raise HTTPException(status_code=400, detail="Combined result already exists for this run.")

            prompt_payload = run.get("promptPayload") or run.get("prompt_payload") or {}
            heading = prompt_payload.get("heading", "").strip() or "Zusammenfassung"
            topic = prompt_payload.get("topic", "").strip() or "Thema"
            model = run.get("model") or "gpt-5.2"

            results = await self.firebase.get_run_results(user_id, kapitel_id, run_id)
            combine_instructions = await prompt_service.get_rendered_instructions(
                user_id,
                "combine",
                {"KAPITEL_TITEL": heading, "KAPITEL_BESCHREIBUNG": topic},
            )
            combine_template_id = await self.firebase.get_active_prompt_id(user_id, "combine")
            combine_template_id = (combine_template_id or "").strip() or "default"
            combine_system_prompt = await prompt_service.get_system_prompt_for_template(
                stage="combine",
                template_id=combine_template_id,
            )
            eligible = []
            for res in results:
                if not res.get("hasContent", True):
                    continue
                content = res.get("content")
                if content:
                    eligible.append({"id": res["id"], "content": content})

            if len(eligible) < 2:
                raise HTTPException(
                    status_code=400,
                    detail="Not enough eligible texts to combine (need at least 2 with content)."
                )

            # Mark combined artifact as running (auto-combine path calls this method directly).
            # This creates/merges the target doc and updates runs/{runId}.artifactsStatus.combined
            # so the UI can show an in-progress state immediately.
            await self.firebase.mark_artifact_running(
                user_id=user_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                artifact_id="combined",
                model=model,
                key_source=key_source,
            )
            marked_running = True
            workflow_id = uuid.uuid4().hex

            # DECISION POINT: Single-level vs Hierarchical combining
            if len(eligible) > 5:
                # Hierarchical combining for large sets
                logger.info(f"Using hierarchical combining for {len(eligible)} sources")
                return await self._hierarchical_combine(
                    user_id,
                    kapitel_id,
                    run_id,
                    eligible,
                    workflow_id,
                    heading,
                    topic,
                    model,
                    api_key,
                    key_source,
                    combine_instructions,
                    combine_system_prompt,
                )

            # Single-level combining (existing logic for ≤5 sources)
            source_quelle_ids = [res["id"] for res in eligible]
            texts = [res["content"] for res in eligible]

            draft_parts: list[str] = []
            for idx, text in enumerate(texts, start=1):
                draft_parts.append(f"Text {idx}:\n{text}")
            drafts_content = "\n\n".join(draft_parts)

            prompt_body = combine_instructions or ""
            if "{DRAFTS}" in prompt_body:
                prompt_text = prompt_body.replace("{DRAFTS}", drafts_content)
            else:
                prompt_text = f"{prompt_body}\n\n[ENTWšRFE]\n{drafts_content}"

            system_message = (combine_system_prompt or "").strip() or (
                "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
            )

            operation_id = f"{workflow_id}_combine_final"
            estimation_service = get_openai_estimation_service(firebase_service)
            estimate_obj = await estimation_service.estimate_operation(
                user_id=user_id,
                operation_type="combine",
                model=model,
                system_text=system_message,
                user_text=prompt_text,
                output_source_text=drafts_content,
            )

            budget_service = get_openai_budget_service(firebase_service)
            reservation_released = False
            reservation = await budget_service.reserve_operation(
                user_id=user_id,
                operation_id=operation_id,
                operation_type="combine",
                user_action_id=run_id,
                estimate=estimate_obj.to_dict(),
                kapitel_id=kapitel_id,
                run_id=run_id,
                operation_details={"sourceCount": len(source_quelle_ids)},
            )
            if reservation.result == "blocked":
                raise HTTPException(
                    status_code=402,
                    detail="Kein Guthaben verfügbar. Bitte lade Credits im Profil unter Billing auf.",
                )
            if reservation.result in {"already_reserved", "finalized"}:
                raise HTTPException(
                    status_code=409,
                    detail="Operation already exists. Please retry later.",
                )

            await budget_service.mark_running(user_id=user_id, operation_id=operation_id)

            try:
                openai_result = await self.openai.combine_texts(
                    texts,
                    heading,
                    topic,
                    model,
                    api_key=api_key,
                    instructions=combine_instructions,
                    system_prompt=combine_system_prompt,
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
            usage = TokenUsage.from_any(
                openai_result.get("input_tokens", 0),
                openai_result.get("cached_input_tokens", 0),
                openai_result.get("output_tokens", 0),
            )
            cost_breakdown, matched_model, pricing, _match_type = await cost_service.calculate_cost(
                model=openai_result.get("model") or model,
                usage=usage,
            )

            kapitel = await self.firebase.get_kapitel(user_id, kapitel_id)
            projekt_id = (kapitel or {}).get("projektId")

            projekt_snapshot = None
            if projekt_id:
                project = await self.firebase.get_project(user_id, projekt_id)
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
                operation_type="combine",
                user_id=user_id,
                user_action_id=run_id,
                operation_details={"sourceCount": len(source_quelle_ids)},
                model=openai_result.get("model") or model,
                usage=usage,
                cost_breakdown=cost_breakdown,
                matched_model_key=matched_model,
                pricing=pricing,
                key_source=key_source,
                projekt_id=projekt_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                quelle_id=None,
                projekt_snapshot=projekt_snapshot,
                kapitel_snapshot=kapitel_snapshot,
                run_snapshot=run_snapshot,
                quelle_snapshot=None,
            )

            cost = float(cost_breakdown.total_cost_usd)
            await budget_service.release_reservation(
                user_id=user_id,
                operation_id=operation_id,
                reason="success",
            )
            reservation_released = True

            combined_id = await self.firebase.save_combined_result(
                user_id=user_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                combined_content=openai_result['content'],
                source_quelle_ids=source_quelle_ids,
                heading=heading,
                topic=topic,
                model_used=openai_result['model'],
                tokens_used=usage.total_tokens,
                input_tokens=usage.input_tokens,
                cached_input_tokens=usage.cached_input_tokens,
                output_tokens=usage.output_tokens,
                reasoning_tokens=0,
                cost=cost,
                key_source=key_source
            )

            logger.info(
                f"Combined result saved (id: {combined_id}) for run {run_id} in kapitel {kapitel_id} "
                f"(cost: ${cost:.6f}, sources: {len(source_quelle_ids)})"
            )

            return {
                "combined_id": combined_id,
                "content": openai_result['content'],
                "model": openai_result['model'],
                "tokens": usage.total_tokens,
                "input_tokens": usage.input_tokens,
                "cached_input_tokens": usage.cached_input_tokens,
                "output_tokens": usage.output_tokens,
                "reasoning_tokens": 0,
                "cost": cost,
                "source_quelle_ids": source_quelle_ids,
                "heading": heading,
                "topic": topic,
            }

        except HTTPException as exc:
            if marked_running:
                try:
                    await self.firebase.mark_artifact_error(
                        user_id=user_id,
                        kapitel_id=kapitel_id,
                        run_id=run_id,
                        artifact_id="combined",
                        key_source=key_source,
                    )
                except Exception:
                    pass
            try:
                if "budget_service" in locals() and "operation_id" in locals() and not locals().get("reservation_released"):
                    await budget_service.release_reservation(
                        user_id=user_id,
                        operation_id=operation_id,
                        reason="error",
                    )
            except Exception:
                pass
            raise exc
        except Exception as e:
            logger.error(f"Error combining run results: {str(e)}")
            if marked_running:
                await self.firebase.mark_artifact_error(
                    user_id=user_id,
                    kapitel_id=kapitel_id,
                    run_id=run_id,
                    artifact_id="combined",
                    key_source=key_source,
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
            raise HTTPException(
                status_code=500,
                detail=f"Failed to combine run results: {str(e)}"
            )

    async def _hierarchical_combine(
        self,
        user_id: str,
        kapitel_id: str,
        run_id: str,
        eligible: list,
        workflow_id: str,
        heading: str,
        topic: str,
        model: str,
        api_key: str,
        key_source: str,
        instructions: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> dict:
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        logger.info(f"Starting hierarchical combine for {len(eligible)} sources")

        # Calculate grouping
        groups = calculate_groups(len(eligible))
        logger.info(f"Created {len(groups)} groups: {[len(g) for g in groups]}")

        # STEP 1: Combine each group
        intermediate_results = []
        total_intermediate_cost = 0.0
        total_usage_input = 0
        total_usage_cached = 0
        total_usage_output = 0

        cost_service = get_cost_service(firebase_service)
        run = await self.firebase.get_run(user_id, kapitel_id, run_id)
        kapitel = await self.firebase.get_kapitel(user_id, kapitel_id)
        projekt_id = (kapitel or {}).get("projektId")

        projekt_snapshot = None
        if projekt_id:
            project = await self.firebase.get_project(user_id, projekt_id)
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

        for group_idx, group_indices in enumerate(groups):
            group_number = group_idx + 1
            group_items = [eligible[i] for i in group_indices]
            group_texts = [item["content"] for item in group_items]
            group_quelle_ids = [item["id"] for item in group_items]

            logger.info(f"Combining group {group_number} with {len(group_texts)} sources")

            draft_parts: list[str] = []
            for idx, text in enumerate(group_texts, start=1):
                draft_parts.append(f"Text {idx}:\n{text}")
            drafts_content = "\n\n".join(draft_parts)

            prompt_body = instructions or ""
            if "{DRAFTS}" in prompt_body:
                prompt_text = prompt_body.replace("{DRAFTS}", drafts_content)
            else:
                prompt_text = f"{prompt_body}\n\n[ENTWšRFE]\n{drafts_content}"

            system_message = (system_prompt or "").strip() or (
                "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
            )

            operation_id = f"{workflow_id}_combine_group_{group_number}"
            estimation_service = get_openai_estimation_service(firebase_service)
            estimate_obj = await estimation_service.estimate_operation(
                user_id=user_id,
                operation_type="combine_intermediate",
                model=model,
                system_text=system_message,
                user_text=prompt_text,
                output_source_text=drafts_content,
            )

            budget_service = get_openai_budget_service(firebase_service)
            reservation_released = False
            reservation = await budget_service.reserve_operation(
                user_id=user_id,
                operation_id=operation_id,
                operation_type="combine_intermediate",
                user_action_id=run_id,
                estimate=estimate_obj.to_dict(),
                kapitel_id=kapitel_id,
                run_id=run_id,
                operation_details={
                    "groupNumber": int(group_number),
                    "sourceCount": len(group_quelle_ids),
                },
            )
            if reservation.result == "blocked":
                raise HTTPException(
                    status_code=402,
                    detail="Kein Guthaben verfügbar. Bitte lade Credits im Profil unter Billing auf.",
                )
            if reservation.result in {"already_reserved", "finalized"}:
                raise HTTPException(
                    status_code=409,
                    detail="Operation already exists. Please retry later.",
                )

            await budget_service.mark_running(user_id=user_id, operation_id=operation_id)

            try:
                openai_result = await self.openai.combine_texts(
                    group_texts,
                    heading,
                    topic,
                    model,
                    api_key=api_key,
                    instructions=instructions,
                    system_prompt=system_prompt,
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

            try:
                usage = TokenUsage.from_any(
                    openai_result.get("input_tokens", 0),
                    openai_result.get("cached_input_tokens", 0),
                    openai_result.get("output_tokens", 0),
                )
                cost_breakdown, matched_model, pricing, _match_type = await cost_service.calculate_cost(
                    model=openai_result.get("model") or model,
                    usage=usage,
                )

                await cost_service.log_operation(
                    operation_id=operation_id,
                    operation_type="combine_intermediate",
                    user_id=user_id,
                    user_action_id=run_id,
                    operation_details={
                        "groupNumber": int(group_number),
                        "sourceCount": len(group_quelle_ids),
                    },
                    model=openai_result.get("model") or model,
                    usage=usage,
                    cost_breakdown=cost_breakdown,
                    matched_model_key=matched_model,
                    pricing=pricing,
                    key_source=key_source,
                    projekt_id=projekt_id,
                    kapitel_id=kapitel_id,
                    run_id=run_id,
                    quelle_id=None,
                    projekt_snapshot=projekt_snapshot,
                    kapitel_snapshot=kapitel_snapshot,
                    run_snapshot=run_snapshot,
                    quelle_snapshot=None,
                )

                cost = float(cost_breakdown.total_cost_usd)
                await budget_service.release_reservation(
                    user_id=user_id,
                    operation_id=operation_id,
                    reason="success",
                )
                reservation_released = True
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
            total_intermediate_cost += cost
            total_usage_input += usage.input_tokens
            total_usage_cached += usage.cached_input_tokens
            total_usage_output += usage.output_tokens

            # Save intermediate result to database
            group_id = await self.firebase.save_intermediate_group_result(
                user_id=user_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                group_number=group_number,
                combined_content=openai_result['content'],
                source_quelle_ids=group_quelle_ids,
                heading=heading,
                topic=topic,
                model_used=openai_result['model'],
                tokens_used=usage.total_tokens,
                input_tokens=usage.input_tokens,
                cached_input_tokens=usage.cached_input_tokens,
                output_tokens=usage.output_tokens,
                reasoning_tokens=0,
                cost=cost,
                key_source=key_source
            )

            logger.info(f"Group {group_number} combined and saved (id: {group_id}, cost: ${cost:.6f})")

            intermediate_results.append({
                'group_id': group_id,
                'content': openai_result['content']
            })

        # STEP 2: Combine all intermediate results into final text
        logger.info(f"Combining {len(intermediate_results)} intermediate results into final text")

        intermediate_texts = [r['content'] for r in intermediate_results]

        draft_parts: list[str] = []
        for idx, text in enumerate(intermediate_texts, start=1):
            draft_parts.append(f"Text {idx}:\n{text}")
        drafts_content = "\n\n".join(draft_parts)

        prompt_body = instructions or ""
        if "{DRAFTS}" in prompt_body:
            prompt_text = prompt_body.replace("{DRAFTS}", drafts_content)
        else:
            prompt_text = f"{prompt_body}\n\n[ENTWšRFE]\n{drafts_content}"

        system_message = (system_prompt or "").strip() or (
            "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        )

        operation_id = f"{workflow_id}_combine_final"
        estimation_service = get_openai_estimation_service(firebase_service)
        estimate_obj = await estimation_service.estimate_operation(
            user_id=user_id,
            operation_type="combine",
            model=model,
            system_text=system_message,
            user_text=prompt_text,
            output_source_text=drafts_content,
        )

        budget_service = get_openai_budget_service(firebase_service)
        reservation_released = False
        reservation = await budget_service.reserve_operation(
            user_id=user_id,
            operation_id=operation_id,
            operation_type="combine",
            user_action_id=run_id,
            estimate=estimate_obj.to_dict(),
            kapitel_id=kapitel_id,
            run_id=run_id,
            operation_details={
                "intermediateGroupsCount": len(groups),
                "sourceCount": len(eligible),
            },
        )
        if reservation.result == "blocked":
            raise HTTPException(
                status_code=402,
                detail="Kein Guthaben verfügbar. Bitte lade Credits im Profil unter Billing auf.",
            )
        if reservation.result in {"already_reserved", "finalized"}:
            raise HTTPException(
                status_code=409,
                detail="Operation already exists. Please retry later.",
            )

        await budget_service.mark_running(user_id=user_id, operation_id=operation_id)

        try:
            final_openai_result = await self.openai.combine_texts(
                intermediate_texts,
                heading,
                topic,
                model,
                api_key=api_key,
                instructions=instructions,
                system_prompt=system_prompt,
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

        final_usage = TokenUsage.from_any(
            final_openai_result.get("input_tokens", 0),
            final_openai_result.get("cached_input_tokens", 0),
            final_openai_result.get("output_tokens", 0),
        )
        try:
            final_breakdown, final_matched_model, final_pricing, _final_match_type = await cost_service.calculate_cost(
                model=final_openai_result.get("model") or model,
                usage=final_usage,
            )
            await cost_service.log_operation(
                operation_id=operation_id,
                operation_type="combine",
                user_id=user_id,
                user_action_id=run_id,
                operation_details={
                    "intermediateGroupsCount": len(groups),
                    "sourceCount": len(eligible),
                },
                model=final_openai_result.get("model") or model,
                usage=final_usage,
                cost_breakdown=final_breakdown,
                matched_model_key=final_matched_model,
                pricing=final_pricing,
                key_source=key_source,
                projekt_id=projekt_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                quelle_id=None,
                projekt_snapshot=projekt_snapshot,
                kapitel_snapshot=kapitel_snapshot,
                run_snapshot=run_snapshot,
                quelle_snapshot=None,
            )
            await budget_service.release_reservation(
                user_id=user_id,
                operation_id=operation_id,
                reason="success",
            )
            reservation_released = True
        except Exception as exc:
            await budget_service.mark_status(
                user_id=user_id,
                operation_id=operation_id,
                status="error",
                error_message=str(exc),
            )
            if not reservation_released:
                await budget_service.release_reservation(
                    user_id=user_id,
                    operation_id=operation_id,
                    reason="error",
                )
                reservation_released = True
            raise

        final_cost = float(final_breakdown.total_cost_usd)

        # STEP 3: Save final combined result (same as before)
        all_source_quelle_ids = [item['id'] for item in eligible]

        total_usage_input += final_usage.input_tokens
        total_usage_cached += final_usage.cached_input_tokens
        total_usage_output += final_usage.output_tokens
        total_usage = TokenUsage.from_any(total_usage_input, total_usage_cached, total_usage_output)

        combined_id = await self.firebase.save_combined_result(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            combined_content=final_openai_result['content'],
            source_quelle_ids=all_source_quelle_ids,
            heading=heading,
            topic=topic,
            model_used=final_openai_result['model'],
            tokens_used=total_usage.total_tokens,
            input_tokens=total_usage.input_tokens,
            cached_input_tokens=total_usage.cached_input_tokens,
            output_tokens=total_usage.output_tokens,
            reasoning_tokens=0,
            cost=total_intermediate_cost + final_cost,
            key_source=key_source
        )

        total_cost = total_intermediate_cost + final_cost

        logger.info(
            f"Hierarchical combine complete: "
            f"{len(groups)} groups -> final (total cost: ${total_cost:.6f}, "
            f"intermediate: ${total_intermediate_cost:.6f}, final: ${final_cost:.6f})"
        )

        return {
            "combined_id": combined_id,
            "content": final_openai_result['content'],
            "model": final_openai_result['model'],
            "tokens": total_usage.total_tokens,
            "input_tokens": total_usage.input_tokens,
            "cached_input_tokens": total_usage.cached_input_tokens,
            "output_tokens": total_usage.output_tokens,
            "reasoning_tokens": 0,
            "cost": total_cost,  # Return total cost (intermediate + final)
            "source_quelle_ids": all_source_quelle_ids,
            "heading": heading,
            "topic": topic,
            "intermediate_groups_count": len(groups),
            "intermediate_cost": total_intermediate_cost,
            "final_cost": final_cost,
        }


# Create singleton instance
quelle_service = QuelleService()
