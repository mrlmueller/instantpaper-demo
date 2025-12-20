import os
from pathlib import Path
from dotenv import load_dotenv
import logging
from typing import List

# Load environment variables from `fastapi/.env` regardless of current working directory.
# override=True ensures the local `.env` wins over any pre-set env vars (e.g. accidental system-wide OPENAI_API_KEY).
_dotenv_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_dotenv_path, override=True)

logger = logging.getLogger(__name__)


class Config:
    """Application configuration loaded from environment variables"""

    # Firebase Admin SDK
    FIREBASE_PROJECT_ID: str = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    FIREBASE_PRIVATE_KEY: str = os.getenv("FIREBASE_PRIVATE_KEY", "").strip()
    FIREBASE_CLIENT_EMAIL: str = os.getenv("FIREBASE_CLIENT_EMAIL", "").strip()

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    USER_KEY_ENCRYPTION_KEY: str = os.getenv("USER_KEY_ENCRYPTION_KEY", "").strip()

    # Server
    PORT: int = int(os.getenv("PORT", "8000"))

    # CORS
    # Supports either a single origin (`https://example.com`) or a comma-separated list
    # (`https://example.com,https://www.example.com,http://localhost:3000`).
    _ALLOWED_ORIGINS_RAW: str = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").strip()
    ALLOWED_ORIGINS: List[str] = [
        origin.strip().rstrip("/")
        for origin in _ALLOWED_ORIGINS_RAW.split(",")
        if origin.strip()
    ]

    # Development
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

    # Admin approval endpoint (Basic Auth)
    # Used to set Firebase Auth custom claims (e.g. {"approved": true}) for allowlisting users.
    ADMIN_BASIC_USER: str = os.getenv("ADMIN_BASIC_USER", "admin").strip() or "admin"
    ADMIN_BASIC_PASSWORD: str = os.getenv("ADMIN_BASIC_PASSWORD", "").strip()

    # Text refinement flow
    TEXT_REFINEMENT_MAX_DEPTH: int = int(os.getenv("TEXT_REFINEMENT_MAX_DEPTH", "4"))
    DUMP_REFINEMENT_PROMPTS: bool = (
        os.getenv("DUMP_REFINEMENT_PROMPTS", "true" if DEBUG else "false").lower() == "true"
    )

    # Prompt dumps (all OpenAI requests)
    DUMP_OPENAI_PROMPTS: bool = (
        os.getenv("DUMP_OPENAI_PROMPTS", "true" if DEBUG else "false").lower() == "true"
    )
    OPENAI_PROMPT_DUMP_DIR: str = os.getenv("OPENAI_PROMPT_DUMP_DIR", "").strip()

    @classmethod
    def validate(cls) -> None:
        """Validate that all required configuration is present"""
        required_fields = [
            "FIREBASE_PROJECT_ID",
            "FIREBASE_PRIVATE_KEY",
            "FIREBASE_CLIENT_EMAIL",
            "OPENAI_API_KEY",
            "USER_KEY_ENCRYPTION_KEY",
        ]

        missing_fields = []
        for field in required_fields:
            value = getattr(cls, field)
            if not value:
                missing_fields.append(field)

        if missing_fields:
            raise ValueError(
                f"Missing required configuration: {', '.join(missing_fields)}. "
                "Please check your .env file."
            )


# Create a singleton config instance
config = Config()
