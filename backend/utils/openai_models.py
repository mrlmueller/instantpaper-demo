from __future__ import annotations

DEFAULT_PRIMARY_TEXT_MODEL = "gpt-5.4"
LEGACY_PRIMARY_TEXT_MODEL = "gpt-5.2"


def normalize_forward_text_model(model: str | None, default: str = DEFAULT_PRIMARY_TEXT_MODEL) -> str:
    """
    Upgrade legacy gpt-5.2 execution requests to gpt-5.4 going forward.

    Historical records should keep their stored model labels. This helper is only for
    selecting which model a new API call should execute with.
    """

    raw = str(model or "").strip()
    if not raw:
        return default

    model_lower = raw.lower()
    if model_lower == LEGACY_PRIMARY_TEXT_MODEL or model_lower.startswith(f"{LEGACY_PRIMARY_TEXT_MODEL}-"):
        return DEFAULT_PRIMARY_TEXT_MODEL

    return raw


def is_claude_model(model: str | None) -> bool:
    """Return True if the model string identifies a Claude (Anthropic) model."""
    return str(model or "").strip().lower().startswith("claude-")
