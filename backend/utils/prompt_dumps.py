from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Tuple
from uuid import uuid4

from utils.config import config
from utils.openai_models import is_claude_model

logger = logging.getLogger(__name__)


def _sanitize_filename_component(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", (value or "").strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "unknown"


def _default_dump_dir() -> Path:
    override = (config.OPENAI_PROMPT_DUMP_DIR or "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / ".prompt_dumps"


def dump_prompt_markdown(
    *,
    stage: str,
    model: str,
    sections: Iterable[Tuple[str, str]],
    images: Optional[list[str]] = None,
    dump_path: Optional[str] = None,
) -> Optional[Path]:
    """
    Write a markdown prompt dump to disk.

    Prompt dumps are intended for local development only and are automatically disabled on Cloud Run.

    If `dump_path` is provided, writes to that path when dumping is enabled.
    Otherwise, writes only when `config.DUMP_OPENAI_PROMPTS` is enabled and uses the default dump dir.
    """
    if config.IS_CLOUD_RUN or not config.DEBUG:
        return None

    if not dump_path and not config.DUMP_OPENAI_PROMPTS:
        return None
    if dump_path and not (config.DUMP_OPENAI_PROMPTS or config.DUMP_REFINEMENT_PROMPTS):
        return None

    try:
        if dump_path:
            path = Path(dump_path)
        else:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            safe_stage = _sanitize_filename_component(stage)
            suffix = uuid4().hex[:8]
            provider_prefix = "anthropic" if is_claude_model(model) else "openai"
            path = _default_dump_dir() / f"{provider_prefix}_{safe_stage}_{timestamp}_{suffix}.md"

        path.parent.mkdir(parents=True, exist_ok=True)

        out: list[str] = []

        for title, body in sections:
            out.append(f"## {title}\n")
            out.append(body or "")
            if not (body or "").endswith("\n"):
                out.append("\n")
            out.append("\n")

        if images:
            urls = [u for u in images if (u or "").strip()]
            if urls:
                out.append("## Images\n")
                out.append("\n".join(urls))
                out.append("\n\n")

        path.write_text("".join(out), encoding="utf-8")
        return path
    except Exception as exc:  # pragma: no cover - debug helper
        logger.warning(f"Failed to write prompt dump: {exc}")
        return None
