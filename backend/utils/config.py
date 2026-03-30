import os
from pathlib import Path
from dotenv import load_dotenv
import logging
from typing import List

# Load environment variables from `backend/.env` regardless of current working directory.
# override=True ensures the local `.env` wins over any pre-set env vars (e.g. accidental system-wide OPENAI_API_KEY).
_dotenv_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_dotenv_path, override=True)

logger = logging.getLogger(__name__)


def _read_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"Invalid int for env {name}: {raw!r} (using default {default})")
        return default


def _read_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "on"}


def _is_cloud_run_env() -> bool:
    # Cloud Run services expose K_SERVICE; Cloud Run jobs expose CLOUD_RUN_JOB/CLOUD_RUN_EXECUTION.
    return any(
        str(os.getenv(name, "") or "").strip()
        for name in ("K_SERVICE", "CLOUD_RUN_JOB", "CLOUD_RUN_EXECUTION")
    )


def _normalized_execution_backend(raw: str, *, default: str) -> str:
    value = str(raw or "").strip().lower()
    if value in {"cloud_run_split_jobs", "local_split_jobs"}:
        return value
    return str(default or "").strip().lower() or "local_split_jobs"


class Config:
    """Application configuration loaded from environment variables"""

    # Firebase Admin SDK
    FIREBASE_PROJECT_ID: str = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    GOOGLE_CLOUD_PROJECT: str = (
        os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        or os.getenv("GCP_PROJECT_ID", "").strip()
        or FIREBASE_PROJECT_ID
    )
    FIREBASE_PRIVATE_KEY: str = os.getenv("FIREBASE_PRIVATE_KEY", "").strip()
    FIREBASE_CLIENT_EMAIL: str = os.getenv("FIREBASE_CLIENT_EMAIL", "").strip()
    FIREBASE_STORAGE_BUCKET: str = os.getenv(
        "FIREBASE_STORAGE_BUCKET",
        f"{os.getenv('FIREBASE_PROJECT_ID', '').strip()}.firebasestorage.app",
    ).strip()

    # Token verification can fail if the server clock is slightly behind (1-2s). Allow small skew.
    # Firebase Admin supports 0-60 seconds. Keep this small for security.
    FIREBASE_CLOCK_SKEW_SECONDS: int = max(
        0, min(60, _read_int_env("FIREBASE_CLOCK_SKEW_SECONDS", 5))
    )

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
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    IS_CLOUD_RUN: bool = _is_cloud_run_env()

    # Cloud Run Job launcher
    TWO_LANE_CLOUD_RUN_JOB_NAME: str = os.getenv(
        "TWO_LANE_CLOUD_RUN_JOB_NAME", "instantpaper-two-lane-sources"
    ).strip()
    TWO_LANE_CLOUD_RUN_JOB_REGION: str = os.getenv(
        "TWO_LANE_CLOUD_RUN_JOB_REGION", "europe-west3"
    ).strip()
    TWO_LANE_SOURCES_EXECUTION_BACKEND: str = os.getenv(
        "TWO_LANE_SOURCES_EXECUTION_BACKEND",
        "cloud_run_job" if IS_CLOUD_RUN else "local_background",
    ).strip().lower()
    TWO_LANE_ARTIFACT_BUCKET: str = os.getenv(
        "TWO_LANE_ARTIFACT_BUCKET",
        os.getenv(
            "FIREBASE_STORAGE_BUCKET",
            f"{os.getenv('FIREBASE_PROJECT_ID', '').strip()}.firebasestorage.app",
        ),
    ).strip()
    TWO_LANE_ARTIFACT_PREFIX: str = os.getenv(
        "TWO_LANE_ARTIFACT_PREFIX",
        "two-lane-runs",
    ).strip().strip("/")
    TWO_LANE_TASK_DISPATCH_BACKEND: str = os.getenv(
        "TWO_LANE_TASK_DISPATCH_BACKEND",
        "cloud_tasks" if IS_CLOUD_RUN else "local_background",
    ).strip().lower()
    TWO_LANE_TASKS_PROJECT: str = os.getenv(
        "TWO_LANE_TASKS_PROJECT",
        GOOGLE_CLOUD_PROJECT,
    ).strip()
    TWO_LANE_TASKS_LOCATION: str = os.getenv(
        "TWO_LANE_TASKS_LOCATION",
        TWO_LANE_CLOUD_RUN_JOB_REGION,
    ).strip()
    TWO_LANE_OPENALEX_TASK_QUEUE: str = os.getenv(
        "TWO_LANE_OPENALEX_TASK_QUEUE",
        "quellen-finder-openalex",
    ).strip()
    TWO_LANE_SEMANTICSCHOLAR_TASK_QUEUE: str = os.getenv(
        "TWO_LANE_SEMANTICSCHOLAR_TASK_QUEUE",
        "quellen-finder-semanticscholar",
    ).strip()
    TWO_LANE_TASK_HANDLER_URL: str = os.getenv(
        "TWO_LANE_TASK_HANDLER_URL",
        "",
    ).strip()
    TWO_LANE_TASK_DISPATCH_TOKEN: str = os.getenv(
        "TWO_LANE_TASK_DISPATCH_TOKEN",
        "",
    ).strip()
    PDF_SCAN_CPU_CLOUD_RUN_JOB_NAME: str = os.getenv(
        "PDF_SCAN_CPU_CLOUD_RUN_JOB_NAME",
        "instantpaper-pdf-scan-cpu",
    ).strip()
    PDF_SCAN_CPU_CLOUD_RUN_JOB_REGION: str = os.getenv(
        "PDF_SCAN_CPU_CLOUD_RUN_JOB_REGION",
        "europe-west3",
    ).strip()
    PDF_SCAN_GPU_CLOUD_RUN_JOB_NAME: str = os.getenv(
        "PDF_SCAN_GPU_CLOUD_RUN_JOB_NAME", "instantpaper-pdf-scan-gpu"
    ).strip()
    PDF_SCAN_GPU_CLOUD_RUN_JOB_REGION: str = os.getenv(
        "PDF_SCAN_GPU_CLOUD_RUN_JOB_REGION", "europe-west1"
    ).strip()
    PDF_SCAN_ARTIFACT_BUCKET: str = os.getenv(
        "PDF_SCAN_ARTIFACT_BUCKET",
        os.getenv(
            "FIREBASE_STORAGE_BUCKET",
            f"{os.getenv('FIREBASE_PROJECT_ID', '').strip()}.firebasestorage.app",
        ),
    ).strip()
    PDF_SCAN_ARTIFACT_PREFIX: str = os.getenv(
        "PDF_SCAN_ARTIFACT_PREFIX",
        "pdf-scan-runs",
    ).strip().strip("/")
    PDF_SCAN_EXECUTION_BACKEND_RAW: str = os.getenv(
        "PDF_SCAN_EXECUTION_BACKEND",
        "",
    ).strip().lower()
    PDF_SCAN_EXECUTION_BACKEND: str = _normalized_execution_backend(
        PDF_SCAN_EXECUTION_BACKEND_RAW,
        default="cloud_run_split_jobs" if IS_CLOUD_RUN else "local_split_jobs",
    )
    PDF_SCAN_LOCAL_PYTHON_BIN: str = os.getenv("PDF_SCAN_LOCAL_PYTHON_BIN", "").strip()
    PDF_SCAN_STORAGE_RPC_TIMEOUT_SEC: int = max(
        10,
        _read_int_env("PDF_SCAN_STORAGE_RPC_TIMEOUT_SEC", 90),
    )
    PDF_SCAN_STORAGE_TOTAL_DOWNLOAD_TIMEOUT_SEC: int = max(
        PDF_SCAN_STORAGE_RPC_TIMEOUT_SEC,
        _read_int_env("PDF_SCAN_STORAGE_TOTAL_DOWNLOAD_TIMEOUT_SEC", 240),
    )
    PDF_SCAN_MAX_PDF_BYTES: int = max(
        1,
        _read_int_env("PDF_SCAN_MAX_PDF_BYTES", 50 * 1024 * 1024),
    )

    # Admin access endpoint (Basic Auth)
    # Used to set Firebase Auth custom claims (e.g. {"fullAccess": true}) for gating user access.
    ADMIN_BASIC_USER: str = os.getenv("ADMIN_BASIC_USER", "admin").strip() or "admin"
    ADMIN_BASIC_PASSWORD: str = os.getenv("ADMIN_BASIC_PASSWORD", "").strip()

    # Admin access (UID allowlist)
    # Comma-separated Firebase Auth UIDs that may access /api/admin/* endpoints.
    _ADMIN_UIDS_RAW: str = os.getenv("ADMIN_UIDS", "").strip()
    ADMIN_UIDS: List[str] = [
        uid.strip()
        for uid in _ADMIN_UIDS_RAW.split(",")
        if uid.strip()
    ]

    # Text refinement flow
    TEXT_REFINEMENT_MAX_DEPTH: int = int(os.getenv("TEXT_REFINEMENT_MAX_DEPTH", "4"))
    DUMP_REFINEMENT_PROMPTS: bool = (
        os.getenv(
            "DUMP_REFINEMENT_PROMPTS",
            "true" if (DEBUG and not IS_CLOUD_RUN) else "false",
        ).lower()
        == "true"
    )

    # Prompt dumps (all OpenAI requests)
    DUMP_OPENAI_PROMPTS: bool = (
        os.getenv(
            "DUMP_OPENAI_PROMPTS",
            "true" if (DEBUG and not IS_CLOUD_RUN) else "false",
        ).lower()
        == "true"
    )
    OPENAI_PROMPT_DUMP_DIR: str = os.getenv("OPENAI_PROMPT_DUMP_DIR", "").strip()

    @classmethod
    def validate(cls) -> None:
        """Validate that all required configuration is present"""
        required_fields = ["FIREBASE_PROJECT_ID", "OPENAI_API_KEY"]

        missing_fields = []
        for field in required_fields:
            value = getattr(cls, field)
            if not value:
                missing_fields.append(field)

        has_key_pair = bool(cls.FIREBASE_PRIVATE_KEY and cls.FIREBASE_CLIENT_EMAIL)
        has_partial_key_pair = bool(cls.FIREBASE_PRIVATE_KEY or cls.FIREBASE_CLIENT_EMAIL)
        has_adc_hint = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip())

        if has_partial_key_pair and not has_key_pair:
            if not cls.FIREBASE_PRIVATE_KEY:
                missing_fields.append("FIREBASE_PRIVATE_KEY")
            if not cls.FIREBASE_CLIENT_EMAIL:
                missing_fields.append("FIREBASE_CLIENT_EMAIL")
        elif not cls.IS_CLOUD_RUN and not has_key_pair and not has_adc_hint:
            missing_fields.append(
                "FIREBASE_PRIVATE_KEY/FIREBASE_CLIENT_EMAIL or GOOGLE_APPLICATION_CREDENTIALS"
            )

        if missing_fields:
            raise ValueError(
                f"Missing required configuration: {', '.join(missing_fields)}. "
                "Please check your .env file."
            )


# Create a singleton config instance
config = Config()
