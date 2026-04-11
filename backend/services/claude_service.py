import asyncio

from anthropic import AsyncAnthropic
from utils.config import config
from utils.prompt_dumps import dump_prompt_markdown
import logging
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)

CLAUDE_MAX_TOKENS = 32000

NO_CONTENT_SENTINEL = "NO_CONTENT"

SUMMARIZE_SYSTEM_MESSAGE = (
    "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
)
SHORTEN_SYSTEM_MESSAGE = "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"

LESEFLUSS_SYSTEM_MESSAGE = "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"


def _build_image_content_block(img_url: str) -> dict:
    """Build a Claude-format image content block from a URL."""
    return {
        "type": "image",
        "source": {"type": "url", "url": img_url},
    }


def _extract_usage(response) -> tuple[int, int, int]:
    """Return (input_tokens, cached_input_tokens, output_tokens) from a Claude response."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0, 0
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    cached_input_tokens = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    return input_tokens, cached_input_tokens, output_tokens


class ClaudeService:
    """Service for Anthropic Claude API operations — mirrors OpenAIService interface."""

    _instance = None
    _initialized = False
    _client: Optional[AsyncAnthropic] = None
    # Limit concurrent Claude API calls to avoid exceeding the TPM rate limit.
    # Anthropic free/low-tier orgs are capped at 30k input tokens/minute;
    # processing many Quellen in parallel instantly saturates that budget.
    _semaphore: asyncio.Semaphore = asyncio.Semaphore(3)

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        pass

    def _ensure_initialized(self):
        if not self._initialized:
            if not config.CLAUDE_API_KEY:
                raise ValueError(
                    "Claude API key not configured. Add CLAUDE_API_KEY to backend/.env"
                )
            # max_retries=5: SDK handles 429 with exponential backoff automatically.
            self._client = AsyncAnthropic(api_key=config.CLAUDE_API_KEY, max_retries=5)
            self._initialized = True
            logger.info("Anthropic Claude client initialized successfully")

    def _get_client(self, api_key: Optional[str] = None) -> AsyncAnthropic:
        """Always returns the platform client — user keys not supported for Claude."""
        self._ensure_initialized()
        return self._client  # type: ignore[return-value]

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
        """Process Quelle content with Claude. Returns same dict shape as OpenAIService."""
        try:
            client = self._get_client()

            template = (user_input or "").replace("{BILDINHALT_ODER_LEER}", "")
            has_quelltext_placeholder = "{QUELLTEXT}" in template
            has_basic_info_placeholder = "{OPTIONAL_GRUNDLEGENDE_INFOS}" in template

            if has_basic_info_placeholder:
                template = template.replace(
                    "{OPTIONAL_GRUNDLEGENDE_INFOS}",
                    (grundlegende_informationen or "").strip(),
                )

            if has_quelltext_placeholder:
                prompt = template.replace("{QUELLTEXT}", quelle_content)
            else:
                if grundlegende_informationen and grundlegende_informationen.strip() and not has_basic_info_placeholder:
                    prompt = f"""{quelle_content}

### Grundlegende Informationen
{grundlegende_informationen}

{template}"""
                else:
                    prompt = f"""{quelle_content}

{template}"""

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
                sections=[("System Prompt", system_message), ("Instructions", prompt)],
                images=quelle_images,
                dump_path=debug_prompt_dump_path,
            )

            user_content: list = [{"type": "text", "text": prompt}]
            if quelle_images:
                for img_url in quelle_images:
                    user_content.append(_build_image_content_block(img_url))

            logger.info(f"Processing Quelle with Claude model {model}")
            async with self._semaphore:
                async with client.messages.stream(
                    model=model,
                    max_tokens=CLAUDE_MAX_TOKENS,
                    system=system_message,
                    messages=[{"role": "user", "content": user_content}],
                ) as stream:
                    response = await stream.get_final_message()

            result_text = response.content[0].text if response.content else None
            if not result_text:
                raise ValueError("No text output returned from Claude response")

            stripped = result_text.strip()
            has_content = stripped != NO_CONTENT_SENTINEL
            if not has_content:
                logger.info("Claude returned NO_CONTENT sentinel")
                result_text = "Claude sagt da sind keine Infos in dem Text die brauchbar sind"

            input_tokens, cached_input_tokens, output_tokens = _extract_usage(response)
            tokens_used = input_tokens + output_tokens
            model_used = response.model

            logger.info(
                f"Claude process_quelle complete. "
                f"Input: {input_tokens} (cached: {cached_input_tokens}), "
                f"Output: {output_tokens}, Total: {tokens_used}"
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
            logger.error(f"Claude API error (process_quelle): {e}")
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
        """Combine multiple texts. Returns same dict shape as OpenAIService."""
        try:
            client = self._get_client()
            draft_parts = [f"Text {idx}:\n{text}" for idx, text in enumerate(texts, start=1)]
            drafts_content = "\n\n".join(draft_parts)

            prompt_body = instructions or "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
            if "{DRAFTS}" in (prompt_body or ""):
                prompt = (prompt_body or "").replace("{DRAFTS}", drafts_content)
            else:
                prompt = f"{prompt_body}\n\n[ENTWÜRFE]\n{drafts_content}"

            system_message = (system_prompt or "").strip() or (
                "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
            )

            dump_prompt_markdown(
                stage="combine",
                model=model,
                sections=[("System Prompt", system_message), ("Instructions", prompt)],
                dump_path=debug_prompt_dump_path,
            )

            user_content: list = [{"type": "text", "text": prompt}]
            if quelle_images:
                for img_url in quelle_images:
                    user_content.append(_build_image_content_block(img_url))

            logger.info(f"Combining {len(texts)} texts with Claude model {model}")
            async with self._semaphore:
                async with client.messages.stream(
                    model=model,
                    max_tokens=CLAUDE_MAX_TOKENS,
                    system=system_message,
                    messages=[{"role": "user", "content": user_content}],
                ) as stream:
                    response = await stream.get_final_message()

            result_text = response.content[0].text if response.content else None
            if not result_text:
                raise ValueError("No text output returned from Claude response (combine)")

            input_tokens, cached_input_tokens, output_tokens = _extract_usage(response)
            tokens_used = input_tokens + output_tokens

            logger.info(
                f"Claude combine_texts complete. "
                f"Input: {input_tokens} (cached: {cached_input_tokens}), "
                f"Output: {output_tokens}, Total: {tokens_used}"
            )

            return {
                "content": result_text,
                "has_content": True,
                "tokens": tokens_used,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": 0,
                "model": response.model,
            }

        except Exception as e:
            logger.error(f"Claude API error (combine_texts): {e}")
            raise

    async def summarize_kapitel(
        self,
        prompt: str,
        model: str,
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> tuple:
        """Summarize a Kapitel. Returns (text, usage_dict) matching OpenAIService."""
        try:
            client = self._get_client()
            system_message = (system_prompt or "").strip() or SUMMARIZE_SYSTEM_MESSAGE

            dump_prompt_markdown(
                stage="summary",
                model=model,
                sections=[("System Prompt", system_message), ("Instructions", prompt)],
            )

            logger.info(f"Summarizing Kapitel with Claude model {model}")
            async with self._semaphore:
                async with client.messages.stream(
                    model=model,
                    max_tokens=CLAUDE_MAX_TOKENS,
                    system=system_message,
                    messages=[{"role": "user", "content": prompt}],
                ) as stream:
                    response = await stream.get_final_message()

            result_text = response.content[0].text if response.content else None
            if not result_text:
                raise ValueError("No text output from Claude (summarize_kapitel)")

            input_tokens, cached_input_tokens, output_tokens = _extract_usage(response)
            usage_dict = {
                "prompt_tokens": input_tokens,
                "prompt_tokens_details": {"cached_tokens": cached_input_tokens},
                "completion_tokens": output_tokens,
            }
            return result_text, usage_dict

        except Exception as e:
            logger.error(f"Claude API error (summarize_kapitel): {e}")
            raise

    async def shorten_and_deduplicate(
        self,
        prompt: str,
        model: str,
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
        debug_prompt_dump_path: Optional[str] = None,
    ) -> tuple:
        """Shorten and deduplicate. Returns (text, usage_dict) matching OpenAIService."""
        try:
            import json as _json
            client = self._get_client()
            system_message = (system_prompt or "").strip() or SHORTEN_SYSTEM_MESSAGE

            dump_prompt_markdown(
                stage="shorten",
                model=model,
                sections=[("System Prompt", system_message), ("Instructions", prompt)],
                dump_path=debug_prompt_dump_path,
            )

            logger.info(f"Shortening with Claude model {model}")
            async with self._semaphore:
                async with client.messages.stream(
                    model=model,
                    max_tokens=CLAUDE_MAX_TOKENS,
                    system=system_message,
                    messages=[{"role": "user", "content": prompt}],
                ) as stream:
                    response = await stream.get_final_message()

            result_text = response.content[0].text if response.content else None
            if not result_text:
                raise ValueError("No text output from Claude (shorten_and_deduplicate)")

            # Backward-compat: some callers may still expect JSON with shortened_text key.
            shortened_text = result_text
            try:
                parsed = _json.loads(result_text.strip())
                if isinstance(parsed, dict) and "shortened_text" in parsed:
                    shortened_text = parsed["shortened_text"]
            except _json.JSONDecodeError:
                pass

            input_tokens, cached_input_tokens, output_tokens = _extract_usage(response)
            usage_dict = {
                "prompt_tokens": input_tokens,
                "prompt_tokens_details": {"cached_tokens": cached_input_tokens},
                "completion_tokens": output_tokens,
            }
            return shortened_text, usage_dict

        except Exception as e:
            logger.error(f"Claude API error (shorten_and_deduplicate): {e}")
            raise

    async def improve_reading_flow(
        self,
        prompt: str,
        model: str,
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
        debug_prompt_dump_path: Optional[str] = None,
    ) -> tuple:
        """Improve reading flow. Returns (text, usage_dict) matching OpenAIService."""
        try:
            client = self._get_client()
            system_message = (system_prompt or "").strip() or LESEFLUSS_SYSTEM_MESSAGE

            dump_prompt_markdown(
                stage="lesefluss",
                model=model,
                sections=[("System Prompt", system_message), ("Instructions", prompt)],
                dump_path=debug_prompt_dump_path,
            )

            logger.info(f"Improving reading flow with Claude model {model}")
            async with self._semaphore:
                async with client.messages.stream(
                    model=model,
                    max_tokens=CLAUDE_MAX_TOKENS,
                    system=system_message,
                    messages=[{"role": "user", "content": prompt}],
                ) as stream:
                    response = await stream.get_final_message()

            result_text = response.content[0].text if response.content else None
            if not result_text:
                raise ValueError("No text output from Claude (improve_reading_flow)")

            input_tokens, cached_input_tokens, output_tokens = _extract_usage(response)
            usage_dict = {
                "prompt_tokens": input_tokens,
                "prompt_tokens_details": {"cached_tokens": cached_input_tokens},
                "completion_tokens": output_tokens,
            }
            return result_text, usage_dict

        except Exception as e:
            logger.error(f"Claude API error (improve_reading_flow): {e}")
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
        reasoning_effort: str = "high",  # accepted for signature compat; unused by Claude
    ) -> dict:
        """Generic text generation. Returns same dict shape as OpenAIService.generate_text."""
        try:
            client = self._get_client()
            system_message = (system_prompt or "").strip() or "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"

            dump_prompt_markdown(
                stage=stage,
                model=model,
                sections=[("System Prompt", system_message), ("Instructions", prompt)],
                dump_path=debug_prompt_dump_path,
            )

            logger.info(f"Generating text with Claude model {model} (stage={stage})")
            async with self._semaphore:
                async with client.messages.stream(
                    model=model,
                    max_tokens=CLAUDE_MAX_TOKENS,
                    system=system_message,
                    messages=[{"role": "user", "content": prompt}],
                ) as stream:
                    response = await stream.get_final_message()

            result_text = response.content[0].text if response.content else None
            if not result_text:
                raise ValueError("No text output from Claude (generate_text)")

            input_tokens, cached_input_tokens, output_tokens = _extract_usage(response)
            tokens_used = input_tokens + output_tokens

            return {
                "content": result_text,
                "has_content": True,
                "tokens": tokens_used,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": 0,
                "model": getattr(response, "model", None) or model,
            }

        except Exception as e:
            logger.error(f"Claude API error (generate_text): {e}")
            raise

    async def generate_gliederung_json(
        self,
        *,
        model: str,
        system_message: str,
        instructions: str,
        json_schema: dict,
        stage: str = "gliederung",
        debug_prompt_dump_path: Optional[str] = None,
    ) -> tuple:
        "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
        try:
            client = self._get_client()

            dump_prompt_markdown(
                stage=stage,
                model=model,
                sections=[("System Prompt", system_message), ("Instructions", instructions)],
                dump_path=debug_prompt_dump_path,
            )

            tool_name = "generate_structured_output"
            tool = {
                "name": tool_name,
                "description": "Generate the structured output according to the provided schema.",
                "input_schema": json_schema,
            }

            logger.info(f"Generating gliederung JSON with Claude {model} (tool use)")
            async with self._semaphore:
                response = await client.messages.create(
                    model=model,
                    max_tokens=8192,
                    system=system_message,
                    messages=[{"role": "user", "content": instructions}],
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool_name},
                )

            tool_use_block = next(
                (b for b in response.content if getattr(b, "type", None) == "tool_use"),
                None,
            )
            if tool_use_block is None:
                raise RuntimeError(
                    f"Claude returned no tool_use block. "
                    f"stop_reason={response.stop_reason}, content={response.content}"
                )

            data = tool_use_block.input
            if not isinstance(data, dict):
                raise RuntimeError(f"Claude tool_use.input is not a dict: {type(data)}")

            input_tokens, cached_input_tokens, output_tokens = _extract_usage(response)
            logger.info(
                f"Gliederung JSON generated. "
                f"Input: {input_tokens}, Output: {output_tokens}"
            )
            return data, input_tokens, cached_input_tokens, output_tokens

        except Exception as e:
            logger.error(f"Claude API error (generate_gliederung_json): {e}")
            raise


claude_service = ClaudeService()
