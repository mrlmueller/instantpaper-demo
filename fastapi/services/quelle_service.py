from fastapi import HTTPException
from services.firebase_service import firebase_service
from services.openai_service import openai_service
import logging

logger = logging.getLogger(__name__)

# Pricing per million tokens (input, cached_input, output)
MODEL_PRICING = {
    "gpt-5.1": (1.25, 0.125, 10.00),      # Most expensive model
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
        model: Model name (e.g., "gpt-5.1", "gpt-5-mini", "gpt-5-nano")
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
    # Find the pricing for this model (case-insensitive exact match)
    model_lower = model.lower()
    pricing = None

    logger.info(f"Matching model '{model}' against pricing dictionary")

    for model_key, (input_price, cached_input_price, output_price) in MODEL_PRICING.items():
        if model_key.lower() == model_lower:
            pricing = (input_price, cached_input_price, output_price)
            logger.info(
                f"Matched pricing key: '{model_key}' -> "
                f"${input_price}/M input, ${cached_input_price}/M cached, ${output_price}/M output"
            )
            break

    if not pricing:
        logger.warning(f"Unknown model '{model}', using default pricing (gpt-5-mini)")
        pricing = MODEL_PRICING["gpt-5-mini"]

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
        f"Non-cached input ${non_cached_input_cost:.6f} ({non_cached_input_tokens:,} × ${input_price}/M) + "
        f"Cached input ${cached_input_cost:.6f} ({cached_input_tokens:,} × ${cached_input_price}/M) + "
        f"Output ${output_cost:.6f} ({output_tokens:,} + {reasoning_tokens:,} reasoning × ${output_price}/M) = "
        f"${total_cost:.6f}"
    )

    return total_cost


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

            # Step 2: Process with OpenAI
            logger.info(f"Processing Quelle {quelle_id} with OpenAI model {model}")
            openai_result = await self.openai.process_quelle(
                quelle['content'],
                user_input,
                model
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
                model_used=openai_result['model'],
                tokens_used=openai_result['tokens'],
                input_tokens=openai_result['input_tokens'],
                cached_input_tokens=openai_result.get('cached_input_tokens', 0),
                output_tokens=openai_result['output_tokens'],
                reasoning_tokens=openai_result.get('reasoning_tokens', 0),
                cost=cost
            )

            logger.info(f"Quelle processing complete. Result ID: {result_id}, Cost: ${cost:.6f}")

            return {
                "result_id": result_id,
                "content": openai_result['content'],
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


# Create singleton instance
quelle_service = QuelleService()
