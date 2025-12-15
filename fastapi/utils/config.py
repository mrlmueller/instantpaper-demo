import os
from dotenv import load_dotenv
import logging

# Load environment variables from .env file
# override=True ensures .env file takes precedence over system environment variables
load_dotenv(override=True)

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

    # Log the last 4 characters of API key for debugging (on module load)
    if OPENAI_API_KEY:
        logger.info(f"OpenAI API Key loaded (ends with: ...{OPENAI_API_KEY[-4:]})")
    if USER_KEY_ENCRYPTION_KEY:
        logger.info("User key encryption key loaded")

    # Server
    PORT: int = int(os.getenv("PORT", "8000"))
    # Strip whitespace/newlines to avoid CORS origin mismatches
    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").strip()

    # Development
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

    # Text refinement flow
    TEXT_REFINEMENT_MAX_DEPTH: int = int(os.getenv("TEXT_REFINEMENT_MAX_DEPTH", "4"))
    DUMP_REFINEMENT_PROMPTS: bool = os.getenv("DUMP_REFINEMENT_PROMPTS", "false").lower() == "true"

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
