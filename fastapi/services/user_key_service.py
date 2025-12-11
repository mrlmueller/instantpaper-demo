import logging
from datetime import datetime
from typing import Optional, Tuple

from fastapi import HTTPException
from openai import AsyncOpenAI, APIStatusError, OpenAIError

from services.firebase_service import firebase_service
from utils.config import config
from utils.crypto import EncryptionService

logger = logging.getLogger(__name__)


class UserKeyService:
    """Handles storage, encryption, validation, and resolution of per-user OpenAI keys."""

    def __init__(self):
        self._encryption = EncryptionService(config.USER_KEY_ENCRYPTION_KEY)

    async def _validate_openai_key(self, api_key: str) -> None:
        """Validate the provided key by calling the OpenAI models endpoint."""
        client = AsyncOpenAI(api_key=api_key)
        try:
            await client.models.list()
            logger.info("OpenAI key validated successfully for user submission")
        except APIStatusError as exc:
            logger.warning(f"OpenAI key validation failed with status {exc.status_code}")
            if exc.status_code in (401, 403):
                raise ValueError("Der OpenAI API Key ist ungültig oder abgelaufen.") from exc
            raise ValueError("OpenAI Validierung fehlgeschlagen. Bitte später erneut versuchen.") from exc
        except OpenAIError as exc:  # pragma: no cover - defensive
            logger.error(f"OpenAI validation failed: {exc}")
            raise ValueError("OpenAI Validierung fehlgeschlagen. Bitte später erneut versuchen.") from exc
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"Unexpected error during OpenAI validation: {exc}")
            raise ValueError("OpenAI Validierung fehlgeschlagen. Bitte später erneut versuchen.") from exc

    async def save_user_key(self, user_id: str, api_key: str) -> dict:
        """Validate, encrypt, and persist a user's OpenAI key."""
        normalized = (api_key or "").strip()
        if not normalized:
            raise ValueError("Bitte gib einen OpenAI API Key ein.")

        await self._validate_openai_key(normalized)

        encrypted = self._encryption.encrypt(normalized)
        payload = {
            **encrypted,
            "last4": normalized[-4:] if len(normalized) >= 4 else normalized,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }

        await firebase_service.save_user_openai_secret(user_id, payload)
        return await self.get_status(user_id)

    async def delete_user_key(self, user_id: str) -> dict:
        """Remove a stored OpenAI key."""
        await firebase_service.delete_user_openai_secret(user_id)
        return await self.get_status(user_id)

    async def get_status(self, user_id: str) -> dict:
        """Return a safe status object for the frontend."""
        secret = await firebase_service.get_user_openai_secret(user_id)
        allow_platform = await firebase_service.get_allow_platform_key(user_id)
        return {
            "has_key": bool(secret),
            "last4": secret.get("last4") if secret else None,
            "allow_platform_key": allow_platform,
        }

    async def _decrypt_user_key(self, user_id: str) -> Optional[str]:
        secret = await firebase_service.get_user_openai_secret(user_id)
        if not secret:
            return None
        try:
            return self._encryption.decrypt(secret)
        except Exception as exc:
            logger.error(f"Failed to decrypt OpenAI key for user {user_id}: {exc}")
            raise HTTPException(
                status_code=500,
                detail="Gespeicherter OpenAI-Schlüssel ist beschädigt. Bitte speichere ihn erneut."
            )

    async def resolve_api_key_for_user(self, user_id: str) -> Tuple[str, str]:
        """
        Return (api_key, source) where source is 'user' or 'platform'.
        Raises HTTPException if no usable key is available.
        """
        user_key = await self._decrypt_user_key(user_id)
        if user_key:
            return user_key, "user"

        allow_platform = await firebase_service.get_allow_platform_key(user_id)
        if allow_platform:
            if not config.OPENAI_API_KEY:
                raise HTTPException(
                    status_code=500,
                    detail="Plattform-API-Key ist nicht konfiguriert."
                )
            return config.OPENAI_API_KEY, "platform"

        raise HTTPException(
            status_code=403,
            detail="Kein OpenAI API Key hinterlegt. Bitte füge deinen Key im Profil hinzu."
        )


# Singleton
user_key_service = UserKeyService()
