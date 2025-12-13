from fastapi import HTTPException
from services.firebase_service import firebase_service
from services.openai_service import openai_service
from services.user_key_service import user_key_service
from services.prompt_service import prompt_service
import logging
import re
import asyncio

logger = logging.getLogger(__name__)

# Pricing per million tokens (input, cached_input, output)
MODEL_PRICING = {
    "gpt-5.2": (1.75, 0.175, 14.00),      # Most expensive model
    "gpt-5-mini": (0.25, 0.025, 2.00),    # Mid-tier model
    "gpt-5-nano": (0.05, 0.005, 0.40),    # Most economical model
}


def calculate_cost(
    model: str,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int = 0
) -> float:
    """
    Calculate cost in USD based on model and token usage

    Args:
        model: Model name (e.g., "gpt-5.2", "gpt-5-mini", "gpt-5-nano")
        input_tokens: Total number of input tokens used
        cached_input_tokens: Number of input tokens from cache (charged at 10% rate)
        output_tokens: Number of output tokens used (visible output)
        reasoning_tokens: Number of reasoning tokens used (internal chain-of-thought)

    Returns:
        float: Total cost in USD

    Note:
        - Cached input tokens are charged at 10% of regular input rate
        - Non-cached input = input_tokens - cached_input_tokens
        - Reasoning tokens are charged at the output token rate
    """
    def _resolve_pricing(model_name: str):
        """
        Return pricing tuple and matched key for potentially versioned model names.

        The OpenAI API returns release-stamped model names (e.g., gpt-5.2-2025-11-13).
        We normalize those back to their base product name so we don't undercharge
        when a date suffix appears.
        """
        model_lower = (model_name or "").lower()
        normalized_pricing = {key.lower(): (key, price) for key, price in MODEL_PRICING.items()}

        # 1) Exact match
        if model_lower in normalized_pricing:
            matched_key, pricing = normalized_pricing[model_lower]
            return matched_key, pricing, "exact"

        # 2) Strip release-date suffixes (e.g., gpt-5.2-2025-11-13 -> gpt-5.2)
        date_stripped = re.sub(r"-20\d{2}-\d{2}-\d{2}$", "", model_lower)
        if date_stripped in normalized_pricing:
            matched_key, pricing = normalized_pricing[date_stripped]
            return matched_key, pricing, "date_suffix"

        # 3) Prefix match for other versioned variants (e.g., gpt-5.2-xyz)
        for key_lower, (original_key, pricing) in normalized_pricing.items():
            if model_lower.startswith(f"{key_lower}-"):
                return original_key, pricing, "prefix"

        # 4) Fallback to default pricing
        return "gpt-5-mini", MODEL_PRICING["gpt-5-mini"], "fallback"

    logger.info(f"Matching model '{model}' against pricing dictionary")

    matched_key, pricing, match_type = _resolve_pricing(model)

    if match_type == "fallback":
        logger.warning(f"Unknown model '{model}', using default pricing (gpt-5-mini)")
    else:
        normalized_note = "" if matched_key.lower() == model.lower() else f" (normalized from '{model}')"
        input_price, cached_input_price, output_price = pricing
        logger.info(
            f"Matched pricing key: '{matched_key}'{normalized_note} -> "
            f"${input_price}/M input, ${cached_input_price}/M cached, ${output_price}/M output"
        )

    input_price, cached_input_price, output_price = pricing

    # Calculate non-cached input tokens (regular rate)
    non_cached_input_tokens = input_tokens - cached_input_tokens

    # Calculate cost (prices are per million tokens)
    non_cached_input_cost = (non_cached_input_tokens / 1_000_000) * input_price
    cached_input_cost = (cached_input_tokens / 1_000_000) * cached_input_price
    total_output_tokens = output_tokens + reasoning_tokens
    output_cost = (total_output_tokens / 1_000_000) * output_price

    total_cost = non_cached_input_cost + cached_input_cost + output_cost

    logger.info(
        f"Cost calculation for {model}: "
        f"Non-cached input ${non_cached_input_cost:.6f} ({non_cached_input_tokens:,} x ${input_price}/M) + "
        f"Cached input ${cached_input_cost:.6f} ({cached_input_tokens:,} x ${cached_input_price}/M) + "
        f"Output ${output_cost:.6f} ({output_tokens:,} + {reasoning_tokens:,} reasoning x ${output_price}/M) = "
        f"${total_cost:.6f}"
    )

    return total_cost


def calculate_groups(num_items: int, min_group_size: int = 4, max_group_size: int = 5) -> list[list[int]]:
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
        user_input: str,
        model: str
    ) -> dict:
        """
        Process a single Quelle with OpenAI and save under a Kapitel run

        Args:
            user_id: ID of the user making the request
            quelle_id: ID of the Quelle to process
            kapitel_id: ID of the Kapitel this run belongs to
            run_id: Run ID for grouping results
            user_input: User instructions for processing
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

            # Step 1: Fetch Quelle from Firestore (verifies ownership)
            logger.info(f"Fetching Quelle {quelle_id} for user {user_id}")
            quelle = await self.firebase.get_quelle(user_id, quelle_id)

            if not quelle:
                logger.warning(f"Quelle {quelle_id} not found for user {user_id}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Quelle {quelle_id} not found or you don't have access to it"
                )

            # Step 1.5: Fetch run to get grundlegendeInformationen
            run = await self.firebase.get_run(user_id, kapitel_id, run_id)
            grundlegende_informationen = run.get('grundlegendeInformationen') if run else None

            # Step 1.6: Extract image URLs from Quelle (if any)
            quelle_images = None
            if 'images' in quelle and isinstance(quelle['images'], list):
                quelle_images = [img['url'] for img in quelle['images'] if 'url' in img]
                logger.info(f"Quelle has {len(quelle_images)} image(s)")

            # Step 2: Process with OpenAI
            api_key, key_source = await user_key_service.resolve_api_key_for_user(user_id)
            logger.info(f"Processing Quelle {quelle_id} with OpenAI model {model}")
            openai_result = await self.openai.process_quelle(
                quelle['content'],
                user_input,
                model,
                grundlegende_informationen,
                api_key=api_key,
                quelle_images=quelle_images
            )

            # Step 2.5: Calculate cost (including cached input and reasoning tokens)
            cost = calculate_cost(
                model=openai_result['model'],
                input_tokens=openai_result['input_tokens'],
                cached_input_tokens=openai_result.get('cached_input_tokens', 0),
                output_tokens=openai_result['output_tokens'],
                reasoning_tokens=openai_result.get('reasoning_tokens', 0)
            )

            # Step 3: Save result to Firestore under the Kapitel run
            logger.info(f"Saving result for Quelle {quelle_id} in Kapitel {kapitel_id} run {run_id} (cost: ${cost:.6f})")
            result_id = await self.firebase.save_result(
                user_id=user_id,
                quelle_id=quelle_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                user_input=user_input,
                result_content=openai_result['content'],
                has_content=openai_result.get('has_content', True),
                model_used=openai_result['model'],
                tokens_used=openai_result['tokens'],
                input_tokens=openai_result['input_tokens'],
                cached_input_tokens=openai_result.get('cached_input_tokens', 0),
                output_tokens=openai_result['output_tokens'],
                reasoning_tokens=openai_result.get('reasoning_tokens', 0),
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
                "tokens": openai_result['tokens'],
                "input_tokens": openai_result['input_tokens'],
                "cached_input_tokens": openai_result.get('cached_input_tokens', 0),
                "output_tokens": openai_result['output_tokens'],
                "reasoning_tokens": openai_result.get('reasoning_tokens', 0),
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
        try:
            run = await self.firebase.get_run(user_id, kapitel_id, run_id)
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")

            api_key, key_source = await user_key_service.resolve_api_key_for_user(user_id)

            existing_combined = await self.firebase.get_combined_result(user_id, kapitel_id, run_id)
            if existing_combined:
                raise HTTPException(status_code=400, detail="Combined result already exists for this run.")

            prompt_payload = run.get("promptPayload") or run.get("prompt_payload") or {}
            heading = prompt_payload.get("heading", "").strip() or "Zusammenfassung"
            topic = prompt_payload.get("topic", "").strip() or "Thema"
            model = run.get("model") or "gpt-5.2"

            results = await self.firebase.get_run_results(user_id, kapitel_id, run_id)
            combine_instructions = await prompt_service.get_rendered_instructions(
                user_id, "combine", {"heading": heading, "topic": topic}
            )
            eligible = []
            for res in results:
                if not res.get("has_content", True):
                    continue
                content = (
                    res.get("result_content")
                    or res.get("resultContent")
                    or res.get("content")
                )
                if content:
                    eligible.append({"id": res["id"], "content": content})

            if len(eligible) < 2:
                raise HTTPException(
                    status_code=400,
                    detail="Not enough eligible texts to combine (need at least 2 with content)."
                )

            # DECISION POINT: Single-level vs Hierarchical combining
            if len(eligible) > 5:
                # Hierarchical combining for large sets
                logger.info(f"Using hierarchical combining for {len(eligible)} sources")
                return await self._hierarchical_combine(
                    user_id, kapitel_id, run_id, eligible, heading, topic, model, api_key, key_source, combine_instructions
                )

            # Single-level combining (existing logic for ≤5 sources)
            source_quelle_ids = [res["id"] for res in eligible]
            texts = [res["content"] for res in eligible]

            openai_result = await self.openai.combine_texts(
                texts, heading, topic, model, api_key=api_key, instructions=combine_instructions
            )

            cost = calculate_cost(
                model=openai_result['model'],
                input_tokens=openai_result['input_tokens'],
                cached_input_tokens=openai_result.get('cached_input_tokens', 0),
                output_tokens=openai_result['output_tokens'],
                reasoning_tokens=openai_result.get('reasoning_tokens', 0)
            )

            combined_id = await self.firebase.save_combined_result(
                user_id=user_id,
                kapitel_id=kapitel_id,
                run_id=run_id,
                combined_content=openai_result['content'],
                source_quelle_ids=source_quelle_ids,
                heading=heading,
                topic=topic,
                model_used=openai_result['model'],
                tokens_used=openai_result['tokens'],
                input_tokens=openai_result['input_tokens'],
                cached_input_tokens=openai_result.get('cached_input_tokens', 0),
                output_tokens=openai_result['output_tokens'],
                reasoning_tokens=openai_result.get('reasoning_tokens', 0),
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
                "tokens": openai_result['tokens'],
                "input_tokens": openai_result['input_tokens'],
                "cached_input_tokens": openai_result.get('cached_input_tokens', 0),
                "output_tokens": openai_result['output_tokens'],
                "reasoning_tokens": openai_result.get('reasoning_tokens', 0),
                "cost": cost,
                "source_quelle_ids": source_quelle_ids,
                "heading": heading,
                "topic": topic,
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error combining run results: {str(e)}")
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
        instructions: str | None = None,
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

        for group_idx, group_indices in enumerate(groups):
            group_number = group_idx + 1
            group_items = [eligible[i] for i in group_indices]
            group_texts = [item["content"] for item in group_items]
            group_quelle_ids = [item["id"] for item in group_items]

            logger.info(f"Combining group {group_number} with {len(group_texts)} sources")

            # Call OpenAI to combine this group
            openai_result = await self.openai.combine_texts(
                group_texts, heading, topic, model, api_key=api_key, instructions=instructions
            )

            # Calculate cost
            cost = calculate_cost(
                model=openai_result['model'],
                input_tokens=openai_result['input_tokens'],
                cached_input_tokens=openai_result.get('cached_input_tokens', 0),
                output_tokens=openai_result['output_tokens'],
                reasoning_tokens=openai_result.get('reasoning_tokens', 0)
            )
            total_intermediate_cost += cost

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
                tokens_used=openai_result['tokens'],
                input_tokens=openai_result['input_tokens'],
                cached_input_tokens=openai_result.get('cached_input_tokens', 0),
                output_tokens=openai_result['output_tokens'],
                reasoning_tokens=openai_result.get('reasoning_tokens', 0),
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
            intermediate_texts, heading, topic, model, api_key=api_key, instructions=instructions
        )

        final_cost = calculate_cost(
            model=final_openai_result['model'],
            input_tokens=final_openai_result['input_tokens'],
            cached_input_tokens=final_openai_result.get('cached_input_tokens', 0),
            output_tokens=final_openai_result['output_tokens'],
            reasoning_tokens=final_openai_result.get('reasoning_tokens', 0)
        )

        # STEP 3: Save final combined result (same as before)
        all_source_quelle_ids = [item['id'] for item in eligible]

        combined_id = await self.firebase.save_combined_result(
            user_id=user_id,
            kapitel_id=kapitel_id,
            run_id=run_id,
            combined_content=final_openai_result['content'],
            source_quelle_ids=all_source_quelle_ids,
            heading=heading,
            topic=topic,
            model_used=final_openai_result['model'],
            tokens_used=final_openai_result['tokens'],
            input_tokens=final_openai_result['input_tokens'],
            cached_input_tokens=final_openai_result.get('cached_input_tokens', 0),
            output_tokens=final_openai_result['output_tokens'],
            reasoning_tokens=final_openai_result.get('reasoning_tokens', 0),
            cost=final_cost,
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
            "tokens": final_openai_result['tokens'],
            "input_tokens": final_openai_result['input_tokens'],
            "cached_input_tokens": final_openai_result.get('cached_input_tokens', 0),
            "output_tokens": final_openai_result['output_tokens'],
            "reasoning_tokens": final_openai_result.get('reasoning_tokens', 0),
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
