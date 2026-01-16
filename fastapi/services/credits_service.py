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
    topup_price_id: str
    subscription_price_id: str


DEFAULT_CREDITS_CONFIG = CreditsConfig(
    purchase_credits_per_usd=3.0,
    default_spend_rate=6.0,
    subscription_bonus_credits=10.0,
    subscription_credits_per_period=85.0,
    topup_price_id="price_1SpqTADXfswW2xixLU9G63O6",
    subscription_price_id="price_1SpqOYDXfswW2xixZsMQLjUI",
)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return float(default)


def _as_str(value: Any) -> str | None:
    if not value:
        return None
    try:
        s = str(value).strip()
    except Exception:
        return None
    return s or None


def _cents_to_usd(value: Any) -> float | None:
    try:
        if value is None:
            return None
        n = float(value)
        if not n:
            return None
        return float(n / 100.0)
    except Exception:
        return None


def _is_successful_payment(data: dict) -> bool:
    status = str((data or {}).get("status") or "").strip().lower()
    if status in ("succeeded", "paid"):
        return True
    if (data or {}).get("paid") is True:
        return True
    return False


def _collect_price_ids(data: dict) -> set[str]:
    out: set[str] = set()

    def push(candidate: Any) -> None:
        s = _as_str(candidate)
        if s:
            out.add(s)

    push((data or {}).get("price"))
    push((data or {}).get("priceId"))
    push((data or {}).get("price_id"))

    try:
        line_items = (data or {}).get("line_items")
        if isinstance(line_items, dict):
            items = line_items.get("data")
            if isinstance(items, list) and items:
                first = items[0] if isinstance(items[0], dict) else {}
                price = first.get("price")
                if isinstance(price, dict):
                    push(price.get("id"))
                else:
                    push(price)
    except Exception:
        pass

    items = (data or {}).get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            price = item.get("price")
            if isinstance(price, dict):
                push(price.get("id"))
            else:
                push(price)
            push(item.get("priceId"))

    prices = (data or {}).get("prices")
    if isinstance(prices, list):
        for p in prices:
            if isinstance(p, dict):
                push(p.get("id"))
            else:
                push(p)

    metadata = (data or {}).get("metadata")
    if isinstance(metadata, dict):
        push(metadata.get("priceId"))
        push(metadata.get("price_id"))

    return out


def _to_datetime_utc(value: Any) -> datetime | None:
    if not value:
        return None

    try:
        if hasattr(value, "to_datetime"):
            value = value.to_datetime()
    except Exception:
        pass

    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt

    # Stripe-like epoch (seconds or ms).
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip()):
            n = float(value)
            if not n:
                return None
            ms = int(n if n > 1e12 else n * 1000.0)
            return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except Exception:
        pass

    if isinstance(value, dict):
        seconds = _as_float(value.get("seconds"), 0.0)
        nanos = _as_float(value.get("nanoseconds"), 0.0)
        if seconds:
            return datetime.fromtimestamp(float(seconds) + float(nanos) / 1_000_000_000.0, tz=timezone.utc)

    return None


class CreditsService:
    def __init__(self, firebase_service):
        self.firebase = firebase_service
        self._config_cache: Optional[CreditsConfig] = None
        self._config_cache_time: Optional[datetime] = None
        self._config_cache_ttl = timedelta(minutes=5)

        self._stripe_sync_cache: dict[str, datetime] = {}
        self._stripe_sync_ttl = timedelta(seconds=15)

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
            topup_price_id=_as_str(
                (data or {}).get("topupPriceId")
                or (data or {}).get("topup_price_id")
                or (data or {}).get("topupPriceID")
            )
            or DEFAULT_CREDITS_CONFIG.topup_price_id,
            subscription_price_id=_as_str(
                (data or {}).get("subscriptionPriceId")
                or (data or {}).get("subscription_price_id")
                or (data or {}).get("subscriptionPriceID")
            )
            or DEFAULT_CREDITS_CONFIG.subscription_price_id,
        )

        self._config_cache = cfg
        self._config_cache_time = now
        return cfg

    def _stripe_sync_due(self, user_id: str) -> bool:
        uid = (user_id or "").strip()
        if not uid:
            return False

        now = datetime.now(timezone.utc)
        last = self._stripe_sync_cache.get(uid)
        if last and now - last < self._stripe_sync_ttl:
            return False

        self._stripe_sync_cache[uid] = now
        if len(self._stripe_sync_cache) > 5000:
            self._stripe_sync_cache.clear()
        return True

    async def sync_stripe_grants_for_user(self, user_id: str) -> None:
        uid = (user_id or "").strip()
        if not uid:
            return
        if not self._stripe_sync_due(uid):
            return

        cfg = await self.get_config()

        try:
            self._sync_stripe_subscription_grant(uid, cfg)
        except Exception as exc:
            logger.warning("Stripe subscription sync failed for user %s: %s", uid, exc, exc_info=True)

        try:
            self._sync_stripe_topup_grants(uid, cfg)
        except Exception as exc:
            logger.warning("Stripe topup sync failed for user %s: %s", uid, exc, exc_info=True)

    def _sync_stripe_subscription_grant(self, user_id: str, cfg: CreditsConfig) -> None:
        subs_ref = (
            self.firebase.db.collection("customers")
            .document(user_id)
            .collection("subscriptions")
        )

        subs = list(subs_ref.stream())
        if not subs:
            return

        def _score(status: str) -> int:
            s = str(status or "").strip().lower()
            if s == "active":
                return 2
            if s == "trialing":
                return 1
            return 0

        best_data: dict | None = None
        best_id: str | None = None
        best_status = ""

        for snap in subs:
            data = snap.to_dict() or {}
            status = str(data.get("status") or "").strip()
            if _score(status) <= 0:
                continue
            if best_data is None or _score(status) > _score(best_status):
                best_data = data
                best_id = snap.id
                best_status = status

        if not best_data or not best_id:
            return

        period_end_dt = _to_datetime_utc(best_data.get("current_period_end"))
        if not period_end_dt:
            return

        period_end_seconds = int(period_end_dt.timestamp())
        ledger_id = f"stripe_subscription_{best_id}_{period_end_seconds}"

        credits = float(cfg.subscription_credits_per_period or 0.0)
        if not credits:
            return

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

        status_norm = str(best_status or "").strip().lower()
        period_end_firestore = period_end_dt

        transaction = self.firebase.db.transaction()

        @firestore.transactional
        def txn(transaction):
            existing = ledger_ref.get(transaction=transaction)
            if existing.exists:
                return False

            bal_snap = balance_ref.get(transaction=transaction)
            bal = bal_snap.to_dict() if bal_snap.exists else {}

            existing_expires_at = _to_datetime_utc(bal.get("subscriptionExpiresAt"))
            existing_sub = _as_float(bal.get("subscriptionCredits"), 0.0)

            same_period = bool(
                existing_expires_at
                and int(existing_expires_at.timestamp()) == int(period_end_dt.timestamp())
            )

            next_sub = float(existing_sub) if same_period else float(credits)

            transaction.set(
                balance_ref,
                {
                    "subscriptionCredits": float(next_sub),
                    "subscriptionExpiresAt": period_end_firestore,
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )

            transaction.set(
                ledger_ref,
                {
                    "type": "grant",
                    "source": "stripe_subscription",
                    "credits": float(credits),
                    "createdAt": SERVER_TIMESTAMP,
                    "expiresAt": period_end_firestore,
                    "stripe": {
                        "subscriptionId": str(best_id),
                        "status": status_norm,
                        "currentPeriodEnd": period_end_firestore,
                    },
                },
            )

            return True

        try:
            txn(transaction)
        except Exception as exc:
            logger.warning(
                "Failed to sync stripe subscription grant user %s sub %s: %s",
                user_id,
                best_id,
                exc,
                exc_info=True,
            )

    def _sync_stripe_topup_grants(self, user_id: str, cfg: CreditsConfig) -> None:
        payments_ref = (
            self.firebase.db.collection("customers")
            .document(user_id)
            .collection("payments")
        )

        docs = []
        try:
            docs = list(
                payments_ref.order_by("created", direction=firestore.Query.DESCENDING)
                .limit(25)
                .stream()
            )
        except Exception:
            try:
                docs = list(payments_ref.limit(25).stream())
            except Exception:
                docs = []

        if not docs:
            return

        topup_price_id = (cfg.topup_price_id or "").strip()

        for snap in docs:
            data = snap.to_dict() or {}
            if not _is_successful_payment(data):
                continue

            invoice_id = _as_str(
                data.get("invoice")
                or data.get("invoiceId")
                or data.get("invoice_id")
            )
            if invoice_id:
                continue

            price_ids = _collect_price_ids(data)
            if price_ids and topup_price_id and topup_price_id not in price_ids:
                continue

            amount_usd = (
                _cents_to_usd(data.get("amount_received"))
                or _cents_to_usd(data.get("amount_total"))
                or _cents_to_usd(data.get("amount"))
                or _cents_to_usd(data.get("amount_subtotal"))
            )
            if amount_usd is None:
                continue

            credits = float(amount_usd) * float(cfg.purchase_credits_per_usd or 0.0)
            if not credits:
                continue

            payment_id = str(snap.id or "").strip()
            if not payment_id:
                continue

            ledger_id = f"stripe_topup_{payment_id}"
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

            currency = str(data.get("currency") or "usd").lower()

            transaction = self.firebase.db.transaction()

            @firestore.transactional
            def txn(transaction):
                existing = ledger_ref.get(transaction=transaction)
                if existing.exists:
                    return False

                bal_snap = balance_ref.get(transaction=transaction)
                bal = bal_snap.to_dict() if bal_snap.exists else {}
                topup_raw = _as_float(bal.get("topupCredits"), 0.0)

                transaction.set(
                    balance_ref,
                    {
                        "topupCredits": float(topup_raw + float(credits)),
                        "updatedAt": SERVER_TIMESTAMP,
                    },
                    merge=True,
                )

                transaction.set(
                    ledger_ref,
                    {
                        "type": "grant",
                        "source": "stripe_topup",
                        "credits": float(credits),
                        "createdAt": SERVER_TIMESTAMP,
                        "expiresAt": None,
                        "stripe": {
                            "paymentId": payment_id,
                            "priceIds": sorted(list(price_ids)),
                            "amountUsd": float(amount_usd),
                            "currency": currency,
                        },
                    },
                )

                return True

            try:
                txn(transaction)
            except Exception as exc:
                logger.warning(
                    "Failed to sync stripe topup grant user %s payment %s: %s",
                    user_id,
                    payment_id,
                    exc,
                    exc_info=True,
                )

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

    async def get_available_credits(self, user_id: str) -> float:
        try:
            await self.sync_stripe_grants_for_user(user_id)
        except Exception:
            pass

        try:
            balance = self._read_balance_doc(user_id)
        except Exception:
            return 0.0

        sub, topup, _expires_at = self._normalize_balance(balance)
        reserved = _as_float((balance or {}).get("reservedCredits"), 0.0)
        return float(float(sub + topup) - float(reserved))

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
                dt = expires_at.to_datetime() if hasattr(expires_at, "to_datetime") else expires_at
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
            await self.sync_stripe_grants_for_user(user_id)
        except Exception:
            pass

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
                detail="Kein Guthaben verfügbar. Bitte lade Credits im Profil unter Billing auf.",
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
                    dt = expires_at.to_datetime() if hasattr(expires_at, "to_datetime") else expires_at
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
