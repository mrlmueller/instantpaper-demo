"""
Credits engine (ledger + cached balance).

Writes:
- users/{uid}/creditLedger/* (append-only; server-only writes)
- users/{uid}/billing/balance (cached; server-only writes)

Read model:
- subscriptionCredits (expiring at subscriptionExpiresAt)
- topupCredits (non-expiring; may become negative)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException
from google.cloud import firestore
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreditsConfig:
    purchase_credits_per_usd: float
    default_spend_rate: float
    subscription_bonus_credits: float
    subscription_credits_per_period: float


DEFAULT_CREDITS_CONFIG = CreditsConfig(
    purchase_credits_per_usd=3.0,
    default_spend_rate=6.0,
    subscription_bonus_credits=10.0,
    subscription_credits_per_period=85.0,
)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return float(default)


class CreditsService:
    def __init__(self, firebase_service):
        self.firebase = firebase_service
        self._config_cache: Optional[CreditsConfig] = None
        self._config_cache_time: Optional[datetime] = None
        self._config_cache_ttl = timedelta(minutes=5)

    async def get_config(self) -> CreditsConfig:
        now = datetime.now(timezone.utc)
        if (
            self._config_cache is not None
            and self._config_cache_time is not None
            and now - self._config_cache_time < self._config_cache_ttl
        ):
            return self._config_cache

        try:
            doc = self.firebase.db.collection("_config").document("credits").get()
            data = doc.to_dict() if doc.exists else {}
        except Exception:
            data = {}

        cfg = CreditsConfig(
            purchase_credits_per_usd=_as_float(
                (data or {}).get("purchaseCreditsPerUsd"),
                DEFAULT_CREDITS_CONFIG.purchase_credits_per_usd,
            ),
            default_spend_rate=_as_float(
                (data or {}).get("defaultSpendRate"),
                DEFAULT_CREDITS_CONFIG.default_spend_rate,
            ),
            subscription_bonus_credits=_as_float(
                (data or {}).get("subscriptionBonusCredits"),
                DEFAULT_CREDITS_CONFIG.subscription_bonus_credits,
            ),
            subscription_credits_per_period=_as_float(
                (data or {}).get("subscriptionCreditsPerPeriod"),
                DEFAULT_CREDITS_CONFIG.subscription_credits_per_period,
            ),
        )

        self._config_cache = cfg
        self._config_cache_time = now
        return cfg

    async def get_spend_rate_for_user(self, user_id: str) -> float:
        try:
            user_doc = await self.firebase.get_user_doc(user_id)
        except Exception:
            user_doc = None

        override = _as_float((user_doc or {}).get("spendRate"), 0.0)
        if override and override > 0:
            return float(override)

        cfg = await self.get_config()
        return float(
            cfg.default_spend_rate
            if cfg.default_spend_rate > 0
            else DEFAULT_CREDITS_CONFIG.default_spend_rate
        )

    def _read_balance_doc(self, user_id: str) -> dict:
        ref = (
            self.firebase.db.collection("users")
            .document(user_id)
            .collection("billing")
            .document("balance")
        )
        snap = ref.get()
        return snap.to_dict() if snap.exists else {}

    def _normalize_balance(self, balance: dict) -> tuple[float, float, Any | None]:
        """
        Returns (subscription_credits_active, topup_credits, subscription_expires_at_raw).
        If subscription is expired, returns 0 for subscription credits.
        """
        topup = _as_float((balance or {}).get("topupCredits"), 0.0)
        sub_raw = _as_float((balance or {}).get("subscriptionCredits"), 0.0)
        expires_at = (balance or {}).get("subscriptionExpiresAt")

        if expires_at:
            try:
                dt = expires_at.to_datetime() if hasattr(expires_at, "to_datetime") else None
                if isinstance(dt, datetime):
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt <= datetime.now(timezone.utc):
                        return 0.0, topup, expires_at
            except Exception:
                pass

        return sub_raw, topup, expires_at

    async def assert_not_negative_balance(self, user_id: str) -> None:
        """
        Enforce: if balance is already negative, block new OpenAI operations.
        """
        try:
            balance = self._read_balance_doc(user_id)
        except Exception:
            raise HTTPException(
                status_code=503,
                detail="Billing temporarily unavailable. Please try again.",
            ) from None

        sub, topup, _expires_at = self._normalize_balance(balance)
        total = float(sub + topup)
        if total < 0:
            raise HTTPException(
                status_code=402,
                detail="Kein Guthaben verfuegbar. Bitte im Profil unter Billing Credits aufladen.",
            )

    async def debit_openai_operation(
        self,
        *,
        user_id: str,
        operation_id: str,
        operation_type: str,
        cost_usd: float,
    ) -> None:
        """
        Create exactly one debit ledger entry for a costed OpenAI operation and update cached balance.

        Idempotent by operation_id (ledger doc id).
        """
        op_id = (operation_id or "").strip()
        if not op_id:
            return

        cost = float(cost_usd or 0.0)
        if cost <= 0:
            return

        spend_rate = await self.get_spend_rate_for_user(user_id)
        if spend_rate <= 0:
            return

        debit_credits = float(cost * spend_rate)
        if not debit_credits:
            return

        ledger_id = f"openai_{op_id}"
        ledger_ref = (
            self.firebase.db.collection("users")
            .document(user_id)
            .collection("creditLedger")
            .document(ledger_id)
        )
        balance_ref = (
            self.firebase.db.collection("users")
            .document(user_id)
            .collection("billing")
            .document("balance")
        )

        now = datetime.now(timezone.utc)
        transaction = self.firebase.db.transaction()

        @firestore.transactional
        def txn(transaction):
            existing = ledger_ref.get(transaction=transaction)
            if existing.exists:
                return False

            bal_snap = balance_ref.get(transaction=transaction)
            bal = bal_snap.to_dict() if bal_snap.exists else {}

            sub_raw = _as_float(bal.get("subscriptionCredits"), 0.0)
            topup_raw = _as_float(bal.get("topupCredits"), 0.0)
            expires_at = bal.get("subscriptionExpiresAt")

            # Expire subscription credits if needed (fail-soft on parsing).
            sub_active = sub_raw
            if expires_at:
                try:
                    dt = expires_at.to_datetime() if hasattr(expires_at, "to_datetime") else None
                    if isinstance(dt, datetime):
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt <= now:
                            sub_active = 0.0
                except Exception:
                    pass

            from_sub = min(float(sub_active), float(debit_credits))
            remaining = float(debit_credits) - float(from_sub)

            new_sub = float(sub_active) - float(from_sub)
            new_topup = float(topup_raw) - float(remaining)

            # Persist normalized subscriptionCredits (expired => 0).
            transaction.set(
                balance_ref,
                {
                    "subscriptionCredits": float(new_sub),
                    "topupCredits": float(new_topup),
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )

            transaction.set(
                ledger_ref,
                {
                    "type": "debit",
                    "source": "openai",
                    "credits": float(-debit_credits),
                    "createdAt": SERVER_TIMESTAMP,
                    "expiresAt": None,
                    "openai": {
                        "operationId": op_id,
                        "operationType": str(operation_type or ""),
                        "costUsd": float(cost),
                        "spendRate": float(spend_rate),
                        "deducted": {
                            "subscription": float(from_sub),
                            "topup": float(remaining),
                        },
                    },
                },
            )

            return True

        try:
            txn(transaction)
        except Exception as exc:
            logger.error(
                "Failed to debit credits for operation %s user %s: %s",
                op_id,
                user_id,
                exc,
                exc_info=True,
            )
            raise


_credits_service_instance: Optional[CreditsService] = None


def get_credits_service(firebase_service) -> CreditsService:
    global _credits_service_instance
    if _credits_service_instance is None:
        _credits_service_instance = CreditsService(firebase_service)
    return _credits_service_instance

