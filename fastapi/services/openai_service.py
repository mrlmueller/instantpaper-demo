from openai import AsyncOpenAI
from utils.config import config
from utils.prompt_dumps import dump_prompt_markdown
import logging
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)

SUMMARIZE_SYSTEM_MESSAGE = (
    "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
)
SHORTEN_SYSTEM_MESSAGE = "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"

LESEFLUSS_SYSTEM_MESSAGE = "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"

NO_CONTENT_SENTINEL = "NO_CONTENT"


def _prompt_cache_kwargs(model: str) -> dict:
    """
    Enable prompt caching for supported models only.

    OpenAI currently supports prompt caching for gpt-5.1 and gpt-5.2.
    """
    model = (model or "").strip()
    if model in {"gpt-5.1", "gpt-5.2"}:
        return {"extra_body": {"prompt_cache_retention": "24h"}}
    return {}


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

    def _get_client(self, api_key: Optional[str] = None) -> AsyncOpenAI:
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
        api_key: Optional[str] = None,
        quelle_images: Optional[List[str]] = None,
        debug_prompt_dump_path: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> dict:
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        try:
            client = self._get_client(api_key)

            template = user_input or ""
            has_quelltext_placeholder = "{QUELLTEXT}" in template
            has_basic_info_placeholder = "{GRUNDLEGENDE_INFOS_ODER_LEER}" in template
            has_image_info_placeholder = "{BILDINHALT_ODER_LEER}" in template

            if has_basic_info_placeholder:
                template = template.replace(
                    "{GRUNDLEGENDE_INFOS_ODER_LEER}",
                    (grundlegende_informationen or "").strip(),
                )
            if has_image_info_placeholder:
                template = template.replace("{BILDINHALT_ODER_LEER}", "")

            if has_quelltext_placeholder:
                prompt = template.replace("{QUELLTEXT}", quelle_content)
            else:
                # Backward-compatible v1 layout: source text first, optional basic info, then instructions.
                if grundlegende_informationen and grundlegende_informationen.strip() and not has_basic_info_placeholder:
                    prompt = f"""{quelle_content}

### Grundlegende Informationen
{grundlegende_informationen}

{template}"""
                else:
                    prompt = f"""{quelle_content}

{template}"""

            logger.info(f"Processing Quelle with {model}")
            logger.debug(f"Prompt length: {len(prompt)} characters")
            if quelle_images:
                logger.info(f"Including {len(quelle_images)} image(s) in request")

            system_message = (system_prompt or "").strip() or (
                "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
                "You can analyze both text and images provided. "
                "Think step-by-step to ensure correctness. "
                f"If the Quelle does NOT contain any useful information for the request, respond with the single token '{NO_CONTENT_SENTINEL}' only. "
                "Otherwise, return only the final answer without any extra commentary."
            )

            dump_prompt_markdown(
                stage="process_quelle",
                model=model,
                sections=[
                    ("System Prompt", system_message),
                    ("Instructions", prompt),
                ],
                images=quelle_images,
                dump_path=debug_prompt_dump_path,
            )

            # Build user message content (multimodal format)
            user_message_content = [
                {"type": "input_text", "text": prompt}
            ]

            # Add images if provided
            if quelle_images and len(quelle_images) > 0:
                for img_url in quelle_images:
                    user_message_content.append({
                        "type": "input_image",
                        "image_url": img_url
                    })

            response = await client.responses.create(
                model=model,
                service_tier="default",
                input=[
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_message}],
                    },
                    {"role": "user", "content": user_message_content},
                ],
                reasoning={"effort": "high"},
                max_output_tokens=None,  # allow model to decide; adjust if you want a hard cap
                **_prompt_cache_kwargs(model),
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

            # Extract token usage from response (input, cached input, output only)
            usage = getattr(response, "usage", None)
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

            cached_input_tokens = 0
            input_details = getattr(usage, "input_tokens_details", None) if usage else None
            if input_details is not None:
                cached_input_tokens = int(getattr(input_details, "cached_tokens", 0) or 0)

            tokens_used = input_tokens + output_tokens
            model_used = response.model

            logger.info(
                f"OpenAI processing complete. "
                f"Input: {input_tokens} (cached: {cached_input_tokens}), "
                f"Output: {output_tokens}, "
                f"Total: {tokens_used} tokens, Has content: {has_content}"
            )

            return {
                "content": result_text,
                "has_content": has_content,
                "tokens": tokens_used,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": 0,
                "model": model_used,
            }

        except Exception as e:
            logger.error(f"OpenAI API error: {str(e)}")
            raise


    async def combine_texts(
        self,
        texts: List[str],
        heading: str,
        topic: str,
        model: str,
        instructions: Optional[str] = None,
        api_key: Optional[str] = None,
        quelle_images: Optional[List[str]] = None,
        debug_prompt_dump_path: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> dict:
        """
        Combine multiple texts into one consolidated text.
        """
        try:
            client = self._get_client(api_key)
            draft_parts: list[str] = []
            for idx, text in enumerate(texts, start=1):
                draft_parts.append(f"Text {idx}:\n{text}")
            drafts_content = "\n\n".join(draft_parts)

            prompt_body = instructions or "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
            if "{DRAFTS}" in (prompt_body or ""):
                prompt = (prompt_body or "").replace("{DRAFTS}", drafts_content)
            else:
                drafts_block = f"[ENTWÜRFE]\n{drafts_content}"
                prompt = f"{prompt_body}\n\n{drafts_block}"

            logger.info(f"Combining {len(texts)} texts with model {model}")

            system_message = (system_prompt or "").strip() or (
                "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
            )

            dump_prompt_markdown(
                stage="combine",
                model=model,
                sections=[
                    ("System Prompt", system_message),
                    ("Instructions", prompt),
                ],
                dump_path=debug_prompt_dump_path,
            )

            response = await client.responses.create(
                model=model,
                service_tier="default",
                input=[
                    {
                        "role": "system",
                        "content": [
                            {
                                "type": "input_text",
                                "text": system_message,
                            }
                        ],
                    },
                    {"role": "user", "content": [{"type": "input_text", "text": prompt}]},
                ],
                reasoning={"effort": "high"},
                max_output_tokens=None,
                **_prompt_cache_kwargs(model),
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
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

            cached_input_tokens = 0
            input_details = getattr(usage, "input_tokens_details", None) if usage else None
            if input_details is not None:
                cached_input_tokens = int(getattr(input_details, "cached_tokens", 0) or 0)

            tokens_used = input_tokens + output_tokens
            model_used = response.model

            logger.info(
                f"OpenAI combination complete. "
                f"Input: {input_tokens} (cached: {cached_input_tokens}), "
                f"Output: {output_tokens}, "
                f"Total: {tokens_used} tokens"
            )

            return {
                "content": result_text,
                "has_content": True,
                "tokens": tokens_used,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": 0,
                "model": model_used,
            }

        except Exception as e:
            logger.error(f"OpenAI combine error: {str(e)}")
            raise

    async def summarize_kapitel(
        self,
        prompt: str,
        model: str,
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> Tuple[str, dict]:
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        try:
            client = self._get_client(api_key)
            logger.info(f"Summarizing Kapitel with model {model}")

            system_message = (system_prompt or "").strip() or SUMMARIZE_SYSTEM_MESSAGE

            dump_prompt_markdown(
                stage="summary",
                model=model,
                sections=[
                    ("System Prompt", system_message),
                    ("Instructions", prompt),
                ],
            )

            response = await client.responses.create(
                model=model,
                service_tier="default",
                input=[
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_message}],
                    },
                    {"role": "user", "content": [{"type": "input_text", "text": prompt}]},
                ],
                reasoning={"effort": "low"},
                max_output_tokens=None,
                **_prompt_cache_kwargs(model),
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
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

            cached_input_tokens = 0
            input_details = getattr(usage, "input_tokens_details", None) if usage else None
            if input_details is not None:
                cached_input_tokens = int(getattr(input_details, "cached_tokens", 0) or 0)

            tokens_used = input_tokens + output_tokens

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
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
        debug_prompt_dump_path: Optional[str] = None,
    ) -> Tuple[str, dict]:
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        try:
            client = self._get_client(api_key)
            logger.info(f"Shortening and deduplicating Kapitel with model {model}")

            system_message = (system_prompt or "").strip() or SHORTEN_SYSTEM_MESSAGE

            dump_prompt_markdown(
                stage="shorten",
                model=model,
                sections=[
                    ("System Prompt", system_message),
                    ("Instructions", prompt),
                ],
                dump_path=debug_prompt_dump_path,
            )

            response = await client.responses.create(
                model=model,
                service_tier="default",
                input=[
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_message}],
                    },
                    {"role": "user", "content": [{"type": "input_text", "text": prompt}]},
                ],
                reasoning={"effort": "high"},
                max_output_tokens=None,
                **_prompt_cache_kwargs(model),
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

            # Backward compatible: some prompts may still return JSON; extract shortened_text when present.
            shortened_text = result_text

            try:
                import json

                json_response = json.loads(result_text.strip())

                if isinstance(json_response, dict) and 'shortened_text' in json_response:
                    shortened_text = json_response.get('shortened_text', '')
                    logger.info("Successfully parsed JSON response with 'shortened_text'")
                else:
                    logger.warning("JSON response missing 'shortened_text' field, using plain text fallback")

            except json.JSONDecodeError:
                logger.info("Response is not JSON, using plain text (backward compatibility)")

            usage = getattr(response, "usage", None)
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

            cached_input_tokens = 0
            input_details = getattr(usage, "input_tokens_details", None) if usage else None
            if input_details is not None:
                cached_input_tokens = int(getattr(input_details, "cached_tokens", 0) or 0)

            tokens_used = input_tokens + output_tokens

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

            return shortened_text, usage_dict

        except Exception as e:
            logger.error(f"OpenAI shortening error: {str(e)}")
            raise

    async def improve_reading_flow(
        self,
        prompt: str,
        model: str,
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
        debug_prompt_dump_path: Optional[str] = None,
    ) -> Tuple[str, dict]:



        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        try:
            client = self._get_client(api_key)
            logger.info(f"Improving reading flow with model {model}")

            system_message = (system_prompt or "").strip() or LESEFLUSS_SYSTEM_MESSAGE

            dump_prompt_markdown(
                stage="lesefluss",
                model=model,
                sections=[
                    ("System Prompt", system_message),
                    ("Instructions", prompt),
                ],
                dump_path=debug_prompt_dump_path,
            )

            response = await client.responses.create(
                model=model,
                service_tier="default",
                input=[
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_message}],
                    },
                    {"role": "user", "content": [{"type": "input_text", "text": prompt}]},
                ],
                reasoning={"effort": "high"},  # High effort for narrative quality
                max_output_tokens=None,
                **_prompt_cache_kwargs(model),
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
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

            cached_input_tokens = 0
            input_details = getattr(usage, "input_tokens_details", None) if usage else None
            if input_details is not None:
                cached_input_tokens = int(getattr(input_details, "cached_tokens", 0) or 0)

            tokens_used = input_tokens + output_tokens

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

    async def generate_text(
        self,
        prompt: str,
        model: str,
        *,
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
        debug_prompt_dump_path: Optional[str] = None,
        stage: str = "refine",
        reasoning_effort: str = "high",
    ) -> dict:
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        try:
            client = self._get_client(api_key)
            logger.info(f"Generating text with model {model} (stage={stage})")

            system_message = (system_prompt or "").strip() or "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"

            dump_prompt_markdown(
                stage=stage,
                model=model,
                sections=[
                    ("System Prompt", system_message),
                    ("Instructions", prompt),
                ],
                dump_path=debug_prompt_dump_path,
            )

            response = await client.responses.create(
                model=model,
                service_tier="default",
                input=[
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_message}],
                    },
                    {"role": "user", "content": [{"type": "input_text", "text": prompt}]},
                ],
                reasoning={"effort": reasoning_effort},
                max_output_tokens=None,
                **_prompt_cache_kwargs(model),
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
            input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
            output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

            cached_input_tokens = 0
            input_details = getattr(usage, "input_tokens_details", None) if usage else None
            if input_details is not None:
                cached_input_tokens = int(getattr(input_details, "cached_tokens", 0) or 0)

            tokens_used = input_tokens + output_tokens
            model_used = getattr(response, "model", None) or model

            return {
                "content": result_text,
                "has_content": True,
                "tokens": tokens_used,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": 0,
                "model": model_used,
            }

        except Exception as e:
            logger.error(f"OpenAI text generation error: {str(e)}")
            raise

# Create singleton instance
openai_service = OpenAIService()
