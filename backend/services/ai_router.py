"""
Provider routing: selects OpenAIService or ClaudeService based on model name.

Usage:
    from services.ai_router import get_ai_service
    result = await get_ai_service(model).process_quelle(...)
"""
from __future__ import annotations

from utils.openai_models import is_claude_model


def get_ai_service(model: str):
    """
    Return the correct AI service instance for the given model name.
    - Models starting with 'claude-' → ClaudeService
    - All other models → OpenAIService
    """
    if is_claude_model(model):
        from services.claude_service import claude_service
        return claude_service
    from services.openai_service import openai_service
    return openai_service
