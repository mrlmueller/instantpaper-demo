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
                if not config.OPENAI_API_KEY or config.OPENAI_API_KEY == '':
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
        self,
        quelle_content: str,
        user_input: str,
        model: str
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
            response = await self.client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"
                                   "Provide clear, accurate, and well-structured responses."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )

            result_content = response.choices[0].message.content
            tokens_used = response.usage.total_tokens
            model_used = response.model

            logger.info(f"OpenAI processing complete. Tokens used: {tokens_used}")

            return {
                "content": result_content,
                "tokens": tokens_used,
                "model": model_used
            }

        except Exception as e:
            logger.error(f"OpenAI API error: {str(e)}")
            raise


# Create singleton instance
openai_service = OpenAIService()
