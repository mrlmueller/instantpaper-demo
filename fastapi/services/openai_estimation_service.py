from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from services.cost_service import get_cost_service
from services.credits_service import get_credits_service
from utils.token_estimation import count_tokens, count_words, estimate_image_tokens

logger = logging.getLogger(__name__)


def _clamp_int(value: float, min_value: int | None, max_value: int | None) -> int:
    try:
        n = int(round(float(value)))
    except Exception:
        n = 0
    if min_value is not None:
        n = max(int(min_value), n)
    if max_value is not None:
        n = min(int(max_value), n)
    return int(n)


def _sum_image_tokens(images: list[dict] | None) -> int:
    if not images:
        return 0
    total = 0
    for img in images:
        if not isinstance(img, dict):
            continue
        total += estimate_image_tokens(img.get("widthPx"), img.get("heightPx"))
    return int(total)


@dataclass(frozen=True)
class OpenAIEstimate:
    operation_type: str
    model: str
    pricing_model: str
    pricing_match: str
    input_words: int
    output_words: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    spend_rate: float
    credits: float
    system_words: int
    system_tokens: int
    user_words: int
    user_tokens: int
    image_tokens: int

    def to_dict(self) -> dict:
        return {
            "operationType": self.operation_type,
            "model": self.model,
            "pricingModel": self.pricing_model,
            "pricingMatch": self.pricing_match,
            "inputWords": int(self.input_words),
            "outputWords": int(self.output_words),
            "inputTokens": int(self.input_tokens),
            "outputTokens": int(self.output_tokens),
            "totalTokens": int(self.total_tokens),
            "costUsd": float(self.cost_usd),
            "spendRate": float(self.spend_rate),
            "credits": float(self.credits),
            "system": {"words": int(self.system_words), "tokens": int(self.system_tokens)},
            "user": {"words": int(self.user_words), "tokens": int(self.user_tokens)},
            "images": {"tokens": int(self.image_tokens)},
        }


class OpenAIEstimationService:
    """
    Pure estimation helper for OpenAI operations:
    system/user text + image tiles -> tokens -> USD (pricing) -> credits (spend rate).
    """

    def __init__(self, firebase_service):
        self.firebase = firebase_service

    async def estimate_operation(
        self,
        *,
        user_id: str,
        operation_type: str,
        model: str,
        system_text: str,
        user_text: str,
        output_source_text: str | None = None,
        parent_generated_text: str | None = None,
        images: list[dict] | None = None,
    ) -> OpenAIEstimate:
        op_type = str(operation_type or "").strip()
        model = str(model or "").strip()
        if not op_type:
            raise ValueError("operation_type is required")
        if not model:
            raise ValueError("model is required")

        system_words = count_words(system_text)
        system_tokens = count_tokens(system_text)
        user_words = count_words(user_text)
        user_tokens = count_tokens(user_text)
        image_tokens = _sum_image_tokens(images)

        input_words = int(system_words + user_words)
        input_tokens = int(system_tokens + user_tokens + image_tokens)

        op_lower = op_type.lower()
        is_refine = op_lower.startswith("refine_") or op_lower == "refine"

        source_text = output_source_text if output_source_text is not None else ""
        parent_text = parent_generated_text if parent_generated_text is not None else ""

        if is_refine:
            if not parent_text:
                raise ValueError("parent_generated_text is required for refinement estimation")
            output_words = count_words(parent_text)
            output_tokens = count_tokens(parent_text)
        else:
            if output_source_text is None:
                raise ValueError("output_source_text is required for estimation")

            source_words = count_words(source_text)

            if op_lower == "summary":
                output_words = _clamp_int(0.35 * float(source_words), 50, 2000)
            elif op_lower == "process_quelle":
                output_words = _clamp_int(0.50 * float(source_words), 50, 2000)
            elif op_lower in {"combine", "combine_intermediate"}:
                output_words = _clamp_int(0.70 * float(source_words), 50, 2000)
            elif op_lower == "shorten":
                output_words = _clamp_int(0.70 * float(source_words), 50, 2000)
            elif op_lower == "lesefluss":
                output_words = _clamp_int(1.20 * float(source_words), 50, 2500)
            else:
                raise ValueError(f"Unsupported operation_type for estimation: {op_type}")

            source_tokens = count_tokens(source_text)
            tokens_per_word = float(source_tokens) / float(max(int(source_words), 1))
            output_tokens = int(round(float(output_words) * float(tokens_per_word)))

        total_tokens = int(input_tokens + output_tokens)

        cost_service = get_cost_service(self.firebase)
        matched_model_key, pricing, match_type = await cost_service.resolve_model_pricing(model)
        input_per_million, _cached_input_per_million, output_per_million = pricing

        cost_usd_dec = (Decimal(int(input_tokens)) / Decimal(1_000_000)) * input_per_million + (
            Decimal(int(output_tokens)) / Decimal(1_000_000)
        ) * output_per_million
        cost_usd = float(cost_usd_dec)

        credits_service = get_credits_service(self.firebase)
        spend_rate = float(await credits_service.get_spend_rate_for_user(user_id))
        credits = float(cost_usd * spend_rate)

        return OpenAIEstimate(
            operation_type=op_type,
            model=model,
            pricing_model=str(matched_model_key),
            pricing_match=str(match_type),
            input_words=int(input_words),
            output_words=int(output_words),
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            total_tokens=int(total_tokens),
            cost_usd=float(cost_usd),
            spend_rate=float(spend_rate),
            credits=float(credits),
            system_words=int(system_words),
            system_tokens=int(system_tokens),
            user_words=int(user_words),
            user_tokens=int(user_tokens),
            image_tokens=int(image_tokens),
        )


_openai_estimation_service_instance: Optional[OpenAIEstimationService] = None


def get_openai_estimation_service(firebase_service) -> OpenAIEstimationService:
    global _openai_estimation_service_instance
    if _openai_estimation_service_instance is None:
        _openai_estimation_service_instance = OpenAIEstimationService(firebase_service)
    return _openai_estimation_service_instance

