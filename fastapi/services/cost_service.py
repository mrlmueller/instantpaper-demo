"""
Centralized cost tracking for OpenAI API operations.

Goals:
- Correct token accounting (input, cached input, output) per OpenAI response.
- Accurate USD cost calculation using configurable pricing (Firestore-backed).
- Durable, immutable cost logging (append-only per-operation log) + aggregates.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from google.cloud.firestore_v1 import Increment, SERVER_TIMESTAMP
from services.credits_service import get_credits_service

logger = logging.getLogger(__name__)

_COST_METRICS_ROOT_DOC_ID = "v1"

# Hardcoded pricing fallback (USD per 1M tokens) used when Firestore config is missing.
FALLBACK_MODEL_PRICING: dict[str, tuple[Decimal, Decimal, Decimal]] = {
    "gpt-5.2": (Decimal("1.75"), Decimal("0.175"), Decimal("14.00")),
    "gpt-5.1": (Decimal("1.25"), Decimal("0.125"), Decimal("10.00")),
    "gpt-5-mini": (Decimal("0.25"), Decimal("0.025"), Decimal("2.00")),
    "gpt-5-nano": (Decimal("0.05"), Decimal("0.005"), Decimal("0.40")),
    # Embeddings (input-only pricing; output tokens are zero)
    "text-embedding-3-small": (Decimal("0.02"), Decimal("0.00"), Decimal("0.00")),
}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return float(default)


def _sanitize_map_key(value: str) -> str:
    """
    Sanitize a string for use as a Firestore map key segment in dot-path updates.

    Firestore dot-path updates split on '.', so we must remove/replace dots.
    """

    return (value or "").replace(".", "_")


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int

    @property
    def uncached_input_tokens(self) -> int:
        return max(int(self.input_tokens) - int(self.cached_input_tokens), 0)

    @property
    def total_tokens(self) -> int:
        # Cost accounting is based on input/output only (no separate reasoning tokens).
        return int(self.input_tokens) + int(self.output_tokens)

    @staticmethod
    def from_any(input_tokens: Any, cached_input_tokens: Any, output_tokens: Any) -> "TokenUsage":
        def _to_int(x: Any) -> int:
            try:
                return max(int(x or 0), 0)
            except Exception:
                return 0

        return TokenUsage(
            input_tokens=_to_int(input_tokens),
            cached_input_tokens=_to_int(cached_input_tokens),
            output_tokens=_to_int(output_tokens),
        )


@dataclass(frozen=True)
class CostBreakdown:
    input_cost_usd: Decimal
    cached_input_cost_usd: Decimal
    output_cost_usd: Decimal

    @property
    def total_cost_usd(self) -> Decimal:
        return self.input_cost_usd + self.cached_input_cost_usd + self.output_cost_usd

    def to_firestore(self) -> dict:
        # Firestore stores floats; keep high precision but avoid absurd repr.
        return {
            "inputCostUsd": float(self.input_cost_usd),
            "cachedInputCostUsd": float(self.cached_input_cost_usd),
            "outputCostUsd": float(self.output_cost_usd),
            "totalCostUsd": float(self.total_cost_usd),
        }


class CostService:
    """
    Centralized cost tracking service.

    Pricing is loaded from Firestore:
      _config/pricing
        - fallbackModel: string
        - models: map
            { modelKey: { inputPerMillion, cachedInputPerMillion, outputPerMillion } }
    """

    def __init__(self, firebase_service):
        self.firebase = firebase_service
        self._pricing_cache: Optional[dict] = None
        self._pricing_cache_time: Optional[datetime] = None
        self._pricing_cache_ttl = timedelta(minutes=5)

    def extract_usage_from_response(self, resp: Any) -> TokenUsage:
        """
        Extract (input_tokens, cached_input_tokens, output_tokens) from an OpenAI Responses API response.
        Matches the user-provided cheat sheet logic.
        """

        usage = getattr(resp, "usage", None)
        if usage is None:
            return TokenUsage.from_any(0, 0, 0)

        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)

        cached_tokens = 0
        input_details = getattr(usage, "input_tokens_details", None)
        if input_details is not None:
            cached_tokens = int(getattr(input_details, "cached_tokens", 0) or 0)

        return TokenUsage.from_any(input_tokens, cached_tokens, output_tokens)

    async def get_pricing_config(self) -> Optional[dict]:
        now = datetime.utcnow()
        if (
            self._pricing_cache is not None
            and self._pricing_cache_time is not None
            and now - self._pricing_cache_time < self._pricing_cache_ttl
        ):
            return self._pricing_cache

        try:
            doc = self.firebase.db.collection("_config").document("pricing").get()
            if not doc.exists:
                return None
            config = doc.to_dict() or {}
            self._pricing_cache = config
            self._pricing_cache_time = now
            return config
        except Exception as exc:
            logger.error(f"Failed to load pricing config from Firestore: {exc}")
            return None

    async def resolve_model_pricing(
        self, model: str
    ) -> tuple[str, tuple[Decimal, Decimal, Decimal], str]:
        config = await self.get_pricing_config()

        fallback_model = "gpt-5-mini"
        pricing_table: dict[str, tuple[Decimal, Decimal, Decimal]] = dict(FALLBACK_MODEL_PRICING)

        if isinstance(config, dict):
            if isinstance(config.get("fallbackModel"), str) and config.get("fallbackModel"):
                fallback_model = str(config.get("fallbackModel"))

            models = config.get("models")
            if isinstance(models, dict) and models:
                parsed: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
                for key, model_data in models.items():
                    if not isinstance(key, str) or not isinstance(model_data, dict):
                        continue
                    try:
                        parsed[key] = (
                            Decimal(str(model_data.get("inputPerMillion"))),
                            Decimal(str(model_data.get("cachedInputPerMillion"))),
                            Decimal(str(model_data.get("outputPerMillion"))),
                        )
                    except Exception:
                        continue
                if parsed:
                    pricing_table = parsed

        model_lower = (model or "").lower()
        normalized_pricing = {k.lower(): (k, v) for k, v in pricing_table.items()}

        # 1) Exact match
        if model_lower in normalized_pricing:
            matched_key, pricing = normalized_pricing[model_lower]
            return matched_key, pricing, "exact"

        # 2) Strip release-date suffixes (e.g., gpt-5.2-2025-11-13 -> gpt-5.2)
        date_stripped = re.sub(r"-20\d{2}-\d{2}-\d{2}$", "", model_lower)
        if date_stripped != model_lower and date_stripped in normalized_pricing:
            matched_key, pricing = normalized_pricing[date_stripped]
            return matched_key, pricing, "date_suffix"

        # 3) Prefix match (e.g., gpt-5.2-xyz)
        for key_lower, (original_key, pricing) in normalized_pricing.items():
            if model_lower.startswith(f"{key_lower}-"):
                return original_key, pricing, "prefix"

        # 4) Fallback
        if fallback_model.lower() in normalized_pricing:
            matched_key, pricing = normalized_pricing[fallback_model.lower()]
            return matched_key, pricing, "fallback"

        return "gpt-5-mini", FALLBACK_MODEL_PRICING["gpt-5-mini"], "fallback"

    async def calculate_cost(
        self, model: str, usage: TokenUsage
    ) -> tuple[CostBreakdown, str, tuple[Decimal, Decimal, Decimal], str]:
        matched_key, pricing, match_type = await self.resolve_model_pricing(model)
        input_price, cached_input_price, output_price = pricing

        input_cost = (Decimal(usage.uncached_input_tokens) / Decimal(1_000_000)) * input_price
        cached_cost = (Decimal(usage.cached_input_tokens) / Decimal(1_000_000)) * cached_input_price
        output_cost = (Decimal(usage.output_tokens) / Decimal(1_000_000)) * output_price

        breakdown = CostBreakdown(
            input_cost_usd=input_cost,
            cached_input_cost_usd=cached_cost,
            output_cost_usd=output_cost,
        )
        return breakdown, matched_key, pricing, match_type

    async def log_operation(
        self,
        *,
        operation_id: str | None = None,
        operation_type: str,
        user_id: str,
        user_action_id: str,
        operation_details: Optional[dict] = None,
        model: str,
        usage: TokenUsage,
        cost_breakdown: CostBreakdown,
        matched_model_key: str,
        pricing: tuple[Decimal, Decimal, Decimal],
        key_source: str,
        projekt_id: Optional[str] = None,
        kapitel_id: Optional[str] = None,
        run_id: Optional[str] = None,
        quelle_id: Optional[str] = None,
        projekt_snapshot: Optional[dict] = None,
        kapitel_snapshot: Optional[dict] = None,
        run_snapshot: Optional[dict] = None,
        quelle_snapshot: Optional[dict] = None,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> str:
        """
        Write an immutable per-operation cost log and update aggregates.

        The operation log write + credits debit are CRITICAL (must succeed).
        Aggregate updates are best-effort.
        """

        operation_id_in = (operation_id or "").strip()
        operation_id = operation_id_in or str(uuid.uuid4())
        year_month = datetime.utcnow().strftime("%Y-%m")

        model_key = _sanitize_map_key(matched_model_key)
        projekt_key = _sanitize_map_key(projekt_id or "unknown")

        cost_usd = float(cost_breakdown.total_cost_usd)
        credits_service = get_credits_service(self.firebase)
        spend_rate_value: float | None = None
        try:
            spend_rate_value = float(await credits_service.get_spend_rate_for_user(user_id))
            if spend_rate_value <= 0:
                spend_rate_value = None
        except Exception:
            spend_rate_value = None

        credits_debited = float(cost_usd * spend_rate_value) if spend_rate_value is not None else 0.0

        operation_data = {
            "operationId": operation_id,
            "userId": user_id,
            "userActionId": user_action_id,
            "operationType": operation_type,
            "operationDetails": operation_details,
            "status": status,
            "errorMessage": error_message,
            "timestamp": SERVER_TIMESTAMP,
            "projektId": projekt_id,
            "kapitelId": kapitel_id,
            "runId": run_id,
            "quelleId": quelle_id,
            "snapshots": {
                "projekt": projekt_snapshot,
                "kapitel": kapitel_snapshot,
                "run": run_snapshot,
                "quelle": quelle_snapshot,
            },
            "model": model,
            "modelNormalized": matched_model_key,
            "modelKey": model_key,
            "keySource": key_source,
            "tokens": {
                "inputTokens": int(usage.input_tokens),
                "cachedInputTokens": int(usage.cached_input_tokens),
                "outputTokens": int(usage.output_tokens),
                "totalTokens": int(usage.total_tokens),
                "uncachedInputTokens": int(usage.uncached_input_tokens),
            },
            "pricingPerMillion": {
                "input": float(pricing[0]),
                "cachedInput": float(pricing[1]),
                "output": float(pricing[2]),
            },
            "costs": cost_breakdown.to_firestore(),
            "creditsDebited": float(credits_debited),
            "spendRate": float(spend_rate_value) if spend_rate_value is not None else None,
            "yearMonth": year_month,
        }

        # 1) Immutable operation log (critical)
        op_ref = (
            self.firebase.db.collection("users")
            .document(user_id)
            .collection("costMetrics")
            .document(_COST_METRICS_ROOT_DOC_ID)
            .collection("operations")
            .document(operation_id)
        )
        op_ref.set(operation_data, merge=bool(operation_id_in))

        # 2) Aggregates (best-effort)
        try:
            user_ref = (
                self.firebase.db.collection("users")
                .document(user_id)
                .collection("costMetrics")
                .document(_COST_METRICS_ROOT_DOC_ID)
                .collection("aggregatesByUser")
                .document("lifetime")
            )

            user_ref.set(
                {
                    "userId": user_id,
                    "totalCostUsd": Increment(cost_usd),
                    "operationCount": Increment(1),
                    "totalInputTokens": Increment(int(usage.input_tokens)),
                    "totalCachedInputTokens": Increment(int(usage.cached_input_tokens)),
                    "totalOutputTokens": Increment(int(usage.output_tokens)),
                    "totalTokens": Increment(int(usage.total_tokens)),
                    "lastUpdated": SERVER_TIMESTAMP,
                    f"byOperationType.{operation_type}.count": Increment(1),
                    f"byOperationType.{operation_type}.totalCostUsd": Increment(cost_usd),
                    f"byModel.{model_key}.count": Increment(1),
                    f"byModel.{model_key}.totalCostUsd": Increment(cost_usd),
                    f"byTimePeriod.{year_month}.count": Increment(1),
                    f"byTimePeriod.{year_month}.totalCostUsd": Increment(cost_usd),
                    f"byProject.{projekt_key}.count": Increment(1),
                    f"byProject.{projekt_key}.totalCostUsd": Increment(cost_usd),
                },
                merge=True,
            )
        except Exception as exc:
            logger.error(f"Non-critical: failed to update user cost aggregate: {exc}")

        if projekt_id:
            try:
                proj_ref = (
                    self.firebase.db.collection("users")
                    .document(user_id)
                    .collection("costMetrics")
                    .document(_COST_METRICS_ROOT_DOC_ID)
                    .collection("aggregatesByProject")
                    .document(projekt_id)
                )

                proj_ref.set(
                    {
                        "userId": user_id,
                        "projektId": projekt_id,
                        "projektSnapshot": projekt_snapshot,
                        "totalCostUsd": Increment(cost_usd),
                        "operationCount": Increment(1),
                        "totalInputTokens": Increment(int(usage.input_tokens)),
                        "totalCachedInputTokens": Increment(int(usage.cached_input_tokens)),
                        "totalOutputTokens": Increment(int(usage.output_tokens)),
                        "totalTokens": Increment(int(usage.total_tokens)),
                        "lastUpdated": SERVER_TIMESTAMP,
                        f"byOperationType.{operation_type}.count": Increment(1),
                        f"byOperationType.{operation_type}.totalCostUsd": Increment(cost_usd),
                        f"byModel.{model_key}.count": Increment(1),
                        f"byModel.{model_key}.totalCostUsd": Increment(cost_usd),
                        f"byTimePeriod.{year_month}.count": Increment(1),
                        f"byTimePeriod.{year_month}.totalCostUsd": Increment(cost_usd),
                    },
                    merge=True,
                )
            except Exception as exc:
                logger.error(f"Non-critical: failed to update project cost aggregate: {exc}")

        # Credits debit: append-only ledger entry + cached balance update (critical).
        await credits_service.debit_openai_operation(
            user_id=user_id,
            operation_id=operation_id,
            operation_type=operation_type,
            cost_usd=cost_usd,
            spend_rate=spend_rate_value,
        )

        return operation_id

    async def log_billed_operation(
        self,
        *,
        operation_id: str | None = None,
        operation_type: str,
        user_id: str,
        user_action_id: str,
        cost_usd: float,
        credits_source: str,
        operation_details: Optional[dict] = None,
        model: str | None = None,
        usage: TokenUsage | None = None,
        key_source: str = "aggregate",
        billing_components: Optional[dict] = None,
        projekt_id: Optional[str] = None,
        kapitel_id: Optional[str] = None,
        run_id: Optional[str] = None,
        quelle_id: Optional[str] = None,
        projekt_snapshot: Optional[dict] = None,
        kapitel_snapshot: Optional[dict] = None,
        run_snapshot: Optional[dict] = None,
        quelle_snapshot: Optional[dict] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        spend_rate: float | None = None,
    ) -> str:
        operation_id_in = (operation_id or "").strip()
        operation_id = operation_id_in or str(uuid.uuid4())
        usage_payload = usage or TokenUsage.from_any(0, 0, 0)
        year_month = datetime.utcnow().strftime("%Y-%m")

        model_name = (str(model or "").strip() or str(operation_type or "").strip() or str(credits_source or "").strip() or "custom_operation")
        model_key = _sanitize_map_key(model_name)
        projekt_key = _sanitize_map_key(projekt_id or "unknown")

        op_ref = (
            self.firebase.db.collection("users")
            .document(user_id)
            .collection("costMetrics")
            .document(_COST_METRICS_ROOT_DOC_ID)
            .collection("operations")
            .document(operation_id)
        )

        if operation_id_in:
            try:
                existing = op_ref.get()
                existing_data = existing.to_dict() if existing.exists else {}
                existing_costs = existing_data.get("costs") if isinstance(existing_data.get("costs"), dict) else {}
                if (
                    str((existing_data or {}).get("status") or "").strip().lower() == "success"
                    and _as_float(existing_costs.get("totalCostUsd"), 0.0) >= 0.0
                    and (
                        _as_float(existing_costs.get("totalCostUsd"), 0.0) > 0.0
                        or _as_float((existing_data or {}).get("creditsDebited"), 0.0) > 0.0
                    )
                ):
                    return operation_id
            except Exception:
                pass

        credits_service = get_credits_service(self.firebase)
        spend_rate_value: float | None = None
        try:
            spend_rate_value = float(spend_rate) if spend_rate is not None else float(await credits_service.get_spend_rate_for_user(user_id))
            if spend_rate_value <= 0:
                spend_rate_value = None
        except Exception:
            spend_rate_value = None

        total_cost_usd = float(max(cost_usd, 0.0))
        credits_debited = float(total_cost_usd * spend_rate_value) if spend_rate_value is not None else 0.0
        costs_payload = {
            "inputCostUsd": 0.0,
            "cachedInputCostUsd": 0.0,
            "outputCostUsd": 0.0,
            "totalCostUsd": float(total_cost_usd),
        }
        if isinstance(billing_components, dict) and billing_components:
            costs_payload["components"] = billing_components

        operation_data = {
            "operationId": operation_id,
            "userId": user_id,
            "userActionId": user_action_id,
            "operationType": operation_type,
            "operationDetails": operation_details,
            "status": status,
            "errorMessage": error_message,
            "timestamp": SERVER_TIMESTAMP,
            "projektId": projekt_id,
            "kapitelId": kapitel_id,
            "runId": run_id,
            "quelleId": quelle_id,
            "snapshots": {
                "projekt": projekt_snapshot,
                "kapitel": kapitel_snapshot,
                "run": run_snapshot,
                "quelle": quelle_snapshot,
            },
            "model": model_name,
            "modelNormalized": model_name,
            "modelKey": model_key,
            "keySource": str(key_source or "aggregate"),
            "tokens": {
                "inputTokens": int(usage_payload.input_tokens),
                "cachedInputTokens": int(usage_payload.cached_input_tokens),
                "outputTokens": int(usage_payload.output_tokens),
                "totalTokens": int(usage_payload.total_tokens),
                "uncachedInputTokens": int(usage_payload.uncached_input_tokens),
            },
            "costs": costs_payload,
            "creditsDebited": float(credits_debited),
            "spendRate": float(spend_rate_value) if spend_rate_value is not None else None,
            "yearMonth": year_month,
        }

        op_ref.set(operation_data, merge=bool(operation_id_in))

        try:
            user_ref = (
                self.firebase.db.collection("users")
                .document(user_id)
                .collection("costMetrics")
                .document(_COST_METRICS_ROOT_DOC_ID)
                .collection("aggregatesByUser")
                .document("lifetime")
            )

            user_ref.set(
                {
                    "userId": user_id,
                    "totalCostUsd": Increment(total_cost_usd),
                    "operationCount": Increment(1),
                    "totalInputTokens": Increment(int(usage_payload.input_tokens)),
                    "totalCachedInputTokens": Increment(int(usage_payload.cached_input_tokens)),
                    "totalOutputTokens": Increment(int(usage_payload.output_tokens)),
                    "totalTokens": Increment(int(usage_payload.total_tokens)),
                    "lastUpdated": SERVER_TIMESTAMP,
                    f"byOperationType.{operation_type}.count": Increment(1),
                    f"byOperationType.{operation_type}.totalCostUsd": Increment(total_cost_usd),
                    f"byModel.{model_key}.count": Increment(1),
                    f"byModel.{model_key}.totalCostUsd": Increment(total_cost_usd),
                    f"byTimePeriod.{year_month}.count": Increment(1),
                    f"byTimePeriod.{year_month}.totalCostUsd": Increment(total_cost_usd),
                    f"byProject.{projekt_key}.count": Increment(1),
                    f"byProject.{projekt_key}.totalCostUsd": Increment(total_cost_usd),
                },
                merge=True,
            )
        except Exception as exc:
            logger.error(f"Non-critical: failed to update user billed cost aggregate: {exc}")

        if projekt_id:
            try:
                proj_ref = (
                    self.firebase.db.collection("users")
                    .document(user_id)
                    .collection("costMetrics")
                    .document(_COST_METRICS_ROOT_DOC_ID)
                    .collection("aggregatesByProject")
                    .document(projekt_id)
                )

                proj_ref.set(
                    {
                        "userId": user_id,
                        "projektId": projekt_id,
                        "projektSnapshot": projekt_snapshot,
                        "totalCostUsd": Increment(total_cost_usd),
                        "operationCount": Increment(1),
                        "totalInputTokens": Increment(int(usage_payload.input_tokens)),
                        "totalCachedInputTokens": Increment(int(usage_payload.cached_input_tokens)),
                        "totalOutputTokens": Increment(int(usage_payload.output_tokens)),
                        "totalTokens": Increment(int(usage_payload.total_tokens)),
                        "lastUpdated": SERVER_TIMESTAMP,
                        f"byOperationType.{operation_type}.count": Increment(1),
                        f"byOperationType.{operation_type}.totalCostUsd": Increment(total_cost_usd),
                        f"byModel.{model_key}.count": Increment(1),
                        f"byModel.{model_key}.totalCostUsd": Increment(total_cost_usd),
                        f"byTimePeriod.{year_month}.count": Increment(1),
                        f"byTimePeriod.{year_month}.totalCostUsd": Increment(total_cost_usd),
                    },
                    merge=True,
                )
            except Exception as exc:
                logger.error(f"Non-critical: failed to update project billed cost aggregate: {exc}")

        await credits_service.debit_tracked_operation(
            user_id=user_id,
            operation_id=operation_id,
            operation_type=operation_type,
            source=credits_source,
            cost_usd=total_cost_usd,
            spend_rate=spend_rate_value,
            metadata={
                "runId": run_id,
                "projektId": projekt_id,
                "kapitelId": kapitel_id,
                "billingComponents": dict(billing_components or {}),
            },
        )

        return operation_id


_cost_service_instance: Optional[CostService] = None


def get_cost_service(firebase_service) -> CostService:
    global _cost_service_instance
    if _cost_service_instance is None:
        _cost_service_instance = CostService(firebase_service)
    return _cost_service_instance
