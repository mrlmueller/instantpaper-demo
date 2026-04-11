import logging
from typing import Tuple

from fastapi import HTTPException

from utils.config import config

logger = logging.getLogger(__name__)


class UserKeyService:
    """Resolves the OpenAI key for a user (platform-only)."""

    async def save_user_key(self, user_id: str, api_key: str) -> dict:
        raise HTTPException(
            status_code=410,
            detail="Eigene OpenAI-Keys werden nicht mehr unterstützt.",
        )

    async def delete_user_key(self, user_id: str) -> dict:
        raise HTTPException(
            status_code=410,
            detail="Eigene OpenAI-Keys werden nicht mehr unterstützt.",
        )

    async def get_status(self, user_id: str) -> dict:
        return {
            "has_key": False,
            "last4": None,
            "allow_platform_key": True,
        }

    async def resolve_api_key_for_user(self, user_id: str, provider: str = "openai") -> tuple[str, str]:
        """
        Resolve the platform API key for the given provider.
        provider: "openai" (default) | "anthropic"
        Returns (api_key, key_source).
        """
        from utils.config import config as _config
        if provider == "anthropic":
            if not _config.CLAUDE_API_KEY:
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=500,
                    detail="Plattform-Anthropic-Key ist nicht konfiguriert.",
                )
            return _config.CLAUDE_API_KEY, "platform"
        # Default: openai
        if not _config.OPENAI_API_KEY:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=500,
                detail="Plattform-API-Key ist nicht konfiguriert.",
            )
        return _config.OPENAI_API_KEY, "platform"


user_key_service = UserKeyService()
