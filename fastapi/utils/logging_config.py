import os
import logging
import logging.config
from pathlib import Path
from dotenv import load_dotenv


def _parse_level(value: str, default: str = "WARNING") -> str:
    v = (value or "").strip().upper()
    if v in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
        return v
    return default


def configure_logging() -> None:
    """
    Configure logging for the FastAPI app.

    Goals:
    - Keep uvicorn access logs (INFO) visible.
    - Reduce app/background verbosity (default WARNING).
    - Provide an env toggle via FASTAPI_LOG_LEVEL.
    - Avoid writing log files.
    """
    # Ensure `.env` values are available even when this is called before utils.config import.
    # override=True so local dev uses the checked-in `fastapi/.env` consistently.
    dotenv_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=dotenv_path, override=True)

    app_level = _parse_level(
        os.getenv("FASTAPI_LOG_LEVEL", "WARNING"), default="WARNING"
    )

    logging_config: dict = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "app": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
            # Keep uvicorn's access log formatting (INFO: 127.0.0.1:...).
            "uvicorn_access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
            },
            "uvicorn_default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
                "use_colors": None,
            },
        },
        "handlers": {
            "app_console": {
                "class": "logging.StreamHandler",
                "level": app_level,
                "formatter": "app",
                "stream": "ext://sys.stdout",
            },
            "uvicorn_access_console": {
                "class": "logging.StreamHandler",
                "level": "INFO",
                "formatter": "uvicorn_access",
                "stream": "ext://sys.stdout",
            },
            "uvicorn_default_console": {
                "class": "logging.StreamHandler",
                "level": app_level,
                "formatter": "uvicorn_default",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": app_level,
            "handlers": ["app_console"],
        },
        "loggers": {
            # Keep request logs.
            "uvicorn.access": {
                "handlers": ["uvicorn_access_console"],
                "level": "INFO",
                "propagate": False,
            },
            # Uvicorn startup/errors should follow app level.
            "uvicorn.error": {
                "handlers": ["uvicorn_default_console"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn": {
                "handlers": ["uvicorn_default_console"],
                "level": "INFO",
                "propagate": False,
            },
            # Silence background/service chatter by default (can be raised via FASTAPI_LOG_LEVEL).
            "services": {"level": app_level},
            "middleware": {"level": app_level},
            "utils": {"level": app_level},
            # Third-party noisy libs.
            "httpx": {"level": "WARNING"},
            "openai": {"level": "WARNING"},
            "firebase_admin": {"level": "WARNING"},
            "google": {"level": "WARNING"},
        },
    }

    logging.config.dictConfig(logging_config)
