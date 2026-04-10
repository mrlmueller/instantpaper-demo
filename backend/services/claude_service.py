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
            self._client = AsyncAnthropic(api_key=config.CLAUDE_API_KEY)
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


claude_service = ClaudeService()
