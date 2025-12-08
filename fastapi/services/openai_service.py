from openai import AsyncOpenAI
from utils.config import config
import logging

logger = logging.getLogger(__name__)


class OpenAIService:
    """Service for OpenAI API operations"""

    _instance = None
    _initialized = False
    _client = None

    def __new__(cls):
        """Singleton pattern to ensure only one OpenAI instance"""
        if cls._instance is None:
            cls._instance = super(OpenAIService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Constructor - does not initialize OpenAI yet (lazy initialization)"""
        pass

    def _ensure_initialized(self):
        """Lazy initialization - only initialize when actually needed"""
        if not self._initialized:
            try:
                # Check if API key is configured
                if not config.OPENAI_API_KEY or config.OPENAI_API_KEY == "":
                    raise ValueError(
                        "OpenAI API key not configured. Please add your OpenAI API key to the .env file. "
                        "Get it from: https://platform.openai.com/api-keys"
                    )

                self._client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
                self._initialized = True
                logger.info("OpenAI client initialized successfully")

            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {str(e)}")
                raise

    @property
    def client(self):
        """Get OpenAI client, initializing if needed"""
        self._ensure_initialized()
        return self._client

    async def process_quelle(
        self, quelle_content: str, user_input: str, model: str
    ) -> dict:
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        try:
            # Combine Quelle content and user instructions
            prompt = f"""Quelle Content:
{quelle_content}

User Instructions:
{user_input}"""

            logger.info(f"Processing Quelle with {model}")
            logger.debug(f"Prompt length: {len(prompt)} characters")

            # Call OpenAI API
            response = await self.client.responses.create(
                model=model,
                input=[
                    {
                        "role": "system",
                        "content": "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
                        "Think step-by-step to ensure correctness, but return only the final answer unless formatting is requested.",
                    },
                    {"role": "user", "content": prompt},
                ],
                reasoning={"effort": "high"},
                max_output_tokens=None,  # allow model to decide; adjust if you want a hard cap
            )

            # Extract text output safely
            result_text = None
            if hasattr(response, "output_text") and response.output_text is not None:
                result_text = response.output_text
            elif hasattr(response, "output") and response.output:
                # Fallback: navigate output -> content -> text
                try:
                    result_text = response.output[0].content[0].text
                except Exception:
                    pass

            if not result_text:
                raise ValueError("No text output returned from OpenAI response")

            # Extract token usage from response
            usage = getattr(response, "usage", None)
            input_tokens = (
                getattr(usage, "input_tokens", None)
                or getattr(usage, "prompt_tokens", 0)
                or 0
            )
            output_tokens = (
                getattr(usage, "output_tokens", None)
                or getattr(usage, "completion_tokens", 0)
                or 0
            )

            # Extract cached input tokens (charged at lower rate)
            cached_input_tokens = 0
            input_details = getattr(usage, "input_tokens_details", None)
            if input_details:
                cached_input_tokens = getattr(input_details, "cached_tokens", 0) or 0

            # Extract reasoning tokens (for reasoning models like o1, o1-mini, etc.)
            reasoning_tokens = 0
            completion_details = getattr(usage, "completion_tokens_details", None)
            if completion_details:
                reasoning_tokens = (
                    getattr(completion_details, "reasoning_tokens", 0) or 0
                )

            tokens_used = input_tokens + output_tokens + reasoning_tokens
            model_used = response.model

            logger.info(
                f"OpenAI processing complete. "
                f"Input: {input_tokens} (cached: {cached_input_tokens}), "
                f"Output: {output_tokens}, Reasoning: {reasoning_tokens}, "
                f"Total: {tokens_used} tokens"
            )

            return {
                "content": result_text,
                "tokens": tokens_used,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": reasoning_tokens,
                "model": model_used,
            }

        except Exception as e:
            logger.error(f"OpenAI API error: {str(e)}")
            raise


# Create singleton instance
openai_service = OpenAIService()
