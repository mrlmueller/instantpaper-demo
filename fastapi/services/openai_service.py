from openai import AsyncOpenAI
from utils.config import config
import logging

logger = logging.getLogger(__name__)

SUMMARIZE_SYSTEM_MESSAGE = (
    "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
)
SHORTEN_SYSTEM_MESSAGE = "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"

LESEFLUSS_SYSTEM_MESSAGE = "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"

NO_CONTENT_SENTINEL = "NO_CONTENT"


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

    def _get_client(self, api_key: str | None = None) -> AsyncOpenAI:
        """
        Return an AsyncOpenAI client for the given key.
        Defaults to the platform key (cached).
        """
        if api_key is None or api_key == config.OPENAI_API_KEY:
            return self.client
        return AsyncOpenAI(api_key=api_key)

    async def process_quelle(
        self,
        quelle_content: str,
        user_input: str,
        model: str,
        grundlegende_informationen: str = None,
        api_key: str | None = None
    ) -> dict:
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        try:
            client = self._get_client(api_key)
            # Build prompt with optional grundlegende informationen
            if grundlegende_informationen and grundlegende_informationen.strip():
                prompt = f"""{quelle_content}

### Grundlegende Informationen
{grundlegende_informationen}

{user_input}"""
            else:
                prompt = f"""{quelle_content}

{user_input}"""

            logger.info(f"Processing Quelle with {model}")
            logger.debug(f"Prompt length: {len(prompt)} characters")

            # Call OpenAI API
            system_message = (
                "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
                "Think step-by-step to ensure correctness. "
                f"If the Quelle does NOT contain any useful information for the request, respond with the single token '{NO_CONTENT_SENTINEL}' only. "
                "Otherwise, return only the final answer without any extra commentary."
            )

            response = await client.responses.create(
                model=model,
                input=[
                    {
                        "role": "system",
                        "content": system_message,
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

            # Detect sentinel for no-content cases
            stripped = result_text.strip()
            has_content = stripped != NO_CONTENT_SENTINEL
            if not has_content:
                logger.info("Model returned NO_CONTENT sentinel (no useful information detected)")
                result_text = "ChatGPT sagt da sind keine infos in dem Text die Brauchbar sind"

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
                f"Total: {tokens_used} tokens, Has content: {has_content}"
            )

            return {
                "content": result_text,
                "has_content": has_content,
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


    async def combine_texts(
        self,
        texts: list[str],
        heading: str,
        topic: str,
        model: str,
        api_key: str | None = None,
    ) -> dict:
        """
        Combine multiple texts into one consolidated text.
        """
        try:
            client = self._get_client(api_key)
            combined_texts = "\n\n".join(
                [f"### Text {i+1}:\n{texts[i]}" for i in range(len(texts))]
            )

            prompt = "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"

            logger.info(f"Combining {len(texts)} texts with model {model}")

            response = await client.responses.create(
                model=model,
                input=[
                    {
                        "role": "system",
                        "content": "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>",
                    },
                    {"role": "user", "content": prompt},
                ],
                reasoning={"effort": "high"},
                max_output_tokens=None,
            )

            result_text = None
            if hasattr(response, "output_text") and response.output_text is not None:
                result_text = response.output_text
            elif hasattr(response, "output") and response.output:
                try:
                    result_text = response.output[0].content[0].text
                except Exception:
                    pass

            if not result_text:
                raise ValueError("No text output returned from OpenAI response")

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

            cached_input_tokens = 0
            input_details = getattr(usage, "input_tokens_details", None)
            if input_details:
                cached_input_tokens = getattr(input_details, "cached_tokens", 0) or 0

            reasoning_tokens = 0
            completion_details = getattr(usage, "completion_tokens_details", None)
            if completion_details:
                reasoning_tokens = (
                    getattr(completion_details, "reasoning_tokens", 0) or 0
                )

            tokens_used = input_tokens + output_tokens + reasoning_tokens
            model_used = response.model

            logger.info(
                f"OpenAI combination complete. "
                f"Input: {input_tokens} (cached: {cached_input_tokens}), "
                f"Output: {output_tokens}, Reasoning: {reasoning_tokens}, "
                f"Total: {tokens_used} tokens"
            )

            return {
                "content": result_text,
                "has_content": True,
                "tokens": tokens_used,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": reasoning_tokens,
                "model": model_used,
            }

        except Exception as e:
            logger.error(f"OpenAI combine error: {str(e)}")
            raise

    async def summarize_kapitel(self, prompt: str, model: str, api_key: str | None = None) -> tuple[str, dict]:
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        try:
            client = self._get_client(api_key)
            logger.info(f"Summarizing Kapitel with model {model}")

            response = await client.responses.create(
                model=model,
                input=[
                    {
                        "role": "system",
                        "content": SUMMARIZE_SYSTEM_MESSAGE,
                    },
                    {"role": "user", "content": prompt},
                ],
                reasoning={"effort": "low"},
                max_output_tokens=None,
            )

            result_text = None
            if hasattr(response, "output_text") and response.output_text is not None:
                result_text = response.output_text
            elif hasattr(response, "output") and response.output:
                try:
                    result_text = response.output[0].content[0].text
                except Exception:
                    pass

            if not result_text:
                raise ValueError("No text output returned from OpenAI response")

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

            cached_input_tokens = 0
            input_details = getattr(usage, "input_tokens_details", None)
            if input_details:
                cached_input_tokens = getattr(input_details, "cached_tokens", 0) or 0

            reasoning_tokens = 0
            completion_details = getattr(usage, "completion_tokens_details", None)
            if completion_details:
                reasoning_tokens = (
                    getattr(completion_details, "reasoning_tokens", 0) or 0
                )

            tokens_used = input_tokens + output_tokens + reasoning_tokens

            logger.info(
                f"Summarization complete. "
                f"Input: {input_tokens} (cached: {cached_input_tokens}), "
                f"Output: {output_tokens}, Total: {tokens_used} tokens"
            )

            # Return content and usage dict
            usage_dict = {
                'prompt_tokens': input_tokens,
                'prompt_tokens_details': {'cached_tokens': cached_input_tokens},
                'completion_tokens': output_tokens,
            }

            return result_text, usage_dict

        except Exception as e:
            logger.error(f"OpenAI summarization error: {str(e)}")
            raise

    async def shorten_and_deduplicate(
        self,
        prompt: str,
        model: str,
        api_key: str | None = None
    ) -> tuple[str, dict, dict]:
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        try:
            client = self._get_client(api_key)
            logger.info(f"Shortening and deduplicating Kapitel with model {model}")

            response = await client.responses.create(
                model=model,
                input=[
                    {
                        "role": "system",
                        "content": SHORTEN_SYSTEM_MESSAGE,
                    },
                    {"role": "user", "content": prompt},
                ],
                reasoning={"effort": "high"},
                max_output_tokens=None,
            )

            result_text = None
            if hasattr(response, "output_text") and response.output_text is not None:
                result_text = response.output_text
            elif hasattr(response, "output") and response.output:
                try:
                    result_text = response.output[0].content[0].text
                except Exception:
                    pass

            if not result_text:
                raise ValueError("No text output returned from OpenAI response")

            # Try to parse as JSON
            import json
            shortened_text = result_text
            explanation_dict = {}

            try:
                # Attempt to parse JSON response
                json_response = json.loads(result_text.strip())

                if isinstance(json_response, dict) and 'shortened_text' in json_response:
                    shortened_text = json_response.get('shortened_text', '')
                    explanation_dict = json_response.get('explanation', {})

                    logger.info("Successfully parsed JSON response with structured explanation")
                else:
                    logger.warning("JSON response missing 'shortened_text' field, using plain text fallback")

            except json.JSONDecodeError:
                logger.info("Response is not JSON, using plain text (backward compatibility)")
                # Keep shortened_text as result_text and explanation_dict as empty

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

            cached_input_tokens = 0
            input_details = getattr(usage, "input_tokens_details", None)
            if input_details:
                cached_input_tokens = getattr(input_details, "cached_tokens", 0) or 0

            reasoning_tokens = 0
            completion_details = getattr(usage, "completion_tokens_details", None)
            if completion_details:
                reasoning_tokens = (
                    getattr(completion_details, "reasoning_tokens", 0) or 0
                )

            tokens_used = input_tokens + output_tokens + reasoning_tokens

            logger.info(
                f"Shortening complete. "
                f"Input: {input_tokens} (cached: {cached_input_tokens}), "
                f"Output: {output_tokens}, Total: {tokens_used} tokens"
            )

            # Return content and usage dict
            usage_dict = {
                'prompt_tokens': input_tokens,
                'prompt_tokens_details': {'cached_tokens': cached_input_tokens},
                'completion_tokens': output_tokens,
            }

            return shortened_text, usage_dict, explanation_dict

        except Exception as e:
            logger.error(f"OpenAI shortening error: {str(e)}")
            raise

    async def improve_reading_flow(
        self,
        prompt: str,
        model: str,
        api_key: str | None = None
    ) -> tuple[str, dict]:
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        try:
            client = self._get_client(api_key)
            logger.info(f"Improving reading flow with model {model}")

            response = await client.responses.create(
                model=model,
                input=[
                    {
                        "role": "system",
                        "content": LESEFLUSS_SYSTEM_MESSAGE,
                    },
                    {"role": "user", "content": prompt},
                ],
                reasoning={"effort": "high"},  # High effort for narrative quality
                max_output_tokens=None,
            )

            result_text = None
            if hasattr(response, "output_text") and response.output_text is not None:
                result_text = response.output_text
            elif hasattr(response, "output") and response.output:
                try:
                    result_text = response.output[0].content[0].text
                except Exception:
                    pass

            if not result_text:
                raise ValueError("No text output returned from OpenAI response")

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

            cached_input_tokens = 0
            input_details = getattr(usage, "input_tokens_details", None)
            if input_details:
                cached_input_tokens = getattr(input_details, "cached_tokens", 0) or 0

            reasoning_tokens = 0
            completion_details = getattr(usage, "completion_tokens_details", None)
            if completion_details:
                reasoning_tokens = (
                    getattr(completion_details, "reasoning_tokens", 0) or 0
                )

            tokens_used = input_tokens + output_tokens + reasoning_tokens

            logger.info(
                f"Reading flow improvement complete. "
                f"Input: {input_tokens} (cached: {cached_input_tokens}), "
                f"Output: {output_tokens}, Total: {tokens_used} tokens"
            )

            # Return content and usage dict
            usage_dict = {
                'prompt_tokens': input_tokens,
                'prompt_tokens_details': {'cached_tokens': cached_input_tokens},
                'completion_tokens': output_tokens,
            }

            return result_text, usage_dict

        except Exception as e:
            logger.error(f"OpenAI reading flow improvement error: {str(e)}")
            raise

# Create singleton instance
openai_service = OpenAIService()
