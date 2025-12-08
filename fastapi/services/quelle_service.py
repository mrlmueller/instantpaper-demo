from fastapi import HTTPException
from services.firebase_service import firebase_service
from services.openai_service import openai_service
import logging

logger = logging.getLogger(__name__)

# Pricing per million tokens (input, output)
MODEL_PRICING = {
    "gpt-4o": (1.25, 10.00),           # 5.1
    "gpt-4o-mini": (0.25, 2.00),       # 5-mini
    "gpt-4o-nano": (0.05, 0.40),       # 5-nano
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Calculate cost in USD based on model and token usage

    Args:
        model: Model name (e.g., "gpt-4o", "gpt-4o-mini", "gpt-4o-nano")
        input_tokens: Number of input tokens used
        output_tokens: Number of output tokens used

    Returns:
        float: Total cost in USD
    """
    # Find the pricing for this model (case-insensitive partial match)
    model_lower = model.lower()
    pricing = None

    for model_key, (input_price, output_price) in MODEL_PRICING.items():
        if model_key.lower() in model_lower:
            pricing = (input_price, output_price)
            break

    if not pricing:
        logger.warning(f"Unknown model '{model}', using default pricing (gpt-4o-mini)")
        pricing = MODEL_PRICING["gpt-4o-mini"]

    input_price, output_price = pricing

    # Calculate cost (prices are per million tokens)
    input_cost = (input_tokens / 1_000_000) * input_price
    output_cost = (output_tokens / 1_000_000) * output_price
    total_cost = input_cost + output_cost

    logger.info(f"Cost calculation for {model}: Input ${input_cost:.6f} + Output ${output_cost:.6f} = ${total_cost:.6f}")

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

            # Step 2.5: Calculate cost
            cost = calculate_cost(
                model=openai_result['model'],
                input_tokens=openai_result['input_tokens'],
                output_tokens=openai_result['output_tokens']
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
                output_tokens=openai_result['output_tokens'],
                cost=cost
            )

            logger.info(f"Quelle processing complete. Result ID: {result_id}, Cost: ${cost:.6f}")

            return {
                "result_id": result_id,
                "content": openai_result['content'],
                "model": openai_result['model'],
                "tokens": openai_result['tokens'],
                "input_tokens": openai_result['input_tokens'],
                "output_tokens": openai_result['output_tokens'],
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
