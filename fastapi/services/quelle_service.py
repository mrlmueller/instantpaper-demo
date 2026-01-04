from fastapi import HTTPException
from services.firebase_service import firebase_service
from services.openai_service import openai_service
from services.cost_service import get_cost_service, TokenUsage
from services.user_key_service import user_key_service
from services.prompt_service import prompt_service
from utils.quellen_zitat import resolve_quelle_zitat_value
import logging
import asyncio
from typing import Optional, List

logger = logging.getLogger(__name__)

def calculate_groups(num_items: int, min_group_size: int = 4, max_group_size: int = 5) -> List[List[int]]:
    """
    Optimally distribute items into groups of 4-5 each.

    Args:
        num_items: Total number of items to group
        min_group_size: Minimum items per group (default: 4)
        max_group_size: Maximum items per group (default: 5)

    Returns:
        List of lists, where each inner list contains indices for that group

    Examples:
        7 items -> [[0,1,2,3], [4,5,6]]  (groups of 4,3)
        15 items -> [[0,1,2,3,4], [5,6,7,8,9], [10,11,12,13,14]]  (3 groups of 5)
        20 items -> [[0,1,2,3,4], [5,6,7,8,9], [10,11,12,13,14], [15,16,17,18,19]]  (4 groups of 5)
    """
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
        """
        Process a single Quelle with OpenAI and save under a Kapitel run

        Args:
            user_id: ID of the user making the request
            quelle_id: ID of the Quelle to process
            kapitel_id: ID of the Kapitel this run belongs to
            run_id: Run ID for grouping results
            model: OpenAI model to use

        Returns:
            dict: Processing result with content, tokens, model, and result_id

        Raises:
            HTTPException: 400 if kapitel/run IDs missing, 404 if Quelle not found
        """
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
            if isinstance(quelle_meta.get("images"), list):
                urls = [
                    str(img.get("url") or "").strip()
                    for img in quelle_meta["images"]
                    if isinstance(img, dict) and str(img.get("url") or "").strip()
                ]
                if urls:
                    quelle_images = urls
                    logger.info(f"Quelle has {len(quelle_images)} image(s)")

            # Step 2: Process with OpenAI
            api_key, key_source = await user_key_service.resolve_api_key_for_user(user_id)
            logger.info(f"Processing Quelle {quelle_id} with OpenAI model {model}")
            openai_result = await self.openai.process_quelle(
                quelle_content_doc.get("text") or "",
                rendered_instructions,
                model,
                grundlegende_informationen,
                api_key=api_key,
                quelle_images=quelle_images,
                system_prompt=system_prompt,
            )

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
            raise
        except Exception as e:
            logger.error(f"Error processing Quelle: {str(e)}")
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

            # DECISION POINT: Single-level vs Hierarchical combining
            if len(eligible) > 5:
                # Hierarchical combining for large sets
                logger.info(f"Using hierarchical combining for {len(eligible)} sources")
                return await self._hierarchical_combine(
                    user_id,
                    kapitel_id,
                    run_id,
                    eligible,
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

            openai_result = await self.openai.combine_texts(
                texts,
                heading,
                topic,
                model,
                api_key=api_key,
                instructions=combine_instructions,
                system_prompt=combine_system_prompt,
            )

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

        except HTTPException:
            raise
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
        heading: str,
        topic: str,
        model: str,
        api_key: str,
        key_source: str,
        instructions: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> dict:
        """
        Perform hierarchical combining:
        1. Split into groups of 4-5
        2. Combine each group (store intermediate results)
        3. Combine all intermediates into final result

        Returns same structure as combine_run_results()
        """
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

            # Call OpenAI to combine this group
            openai_result = await self.openai.combine_texts(
                group_texts,
                heading,
                topic,
                model,
                api_key=api_key,
                instructions=instructions,
                system_prompt=system_prompt,
            )

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

        final_openai_result = await self.openai.combine_texts(
            intermediate_texts,
            heading,
            topic,
            model,
            api_key=api_key,
            instructions=instructions,
            system_prompt=system_prompt,
        )

        final_usage = TokenUsage.from_any(
            final_openai_result.get("input_tokens", 0),
            final_openai_result.get("cached_input_tokens", 0),
            final_openai_result.get("output_tokens", 0),
        )
        final_breakdown, final_matched_model, final_pricing, _final_match_type = await cost_service.calculate_cost(
            model=final_openai_result.get("model") or model,
            usage=final_usage,
        )

        await cost_service.log_operation(
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
