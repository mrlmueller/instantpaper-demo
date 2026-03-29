from __future__ import annotations

import logging
import math
import random
import threading
import time
from dataclasses import dataclass
from typing import Optional, Protocol

from google.cloud import firestore
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.firebase_service import firebase_service

logger = logging.getLogger(__name__)
_STORE_LOCK = threading.Lock()
_LOCAL_STORES: dict[str, "InMemoryProviderRateLimitStore"] = {}
_FIRESTORE_STORES: dict[str, "FirestoreProviderRateLimitStore"] = {}


def _now_epoch_ms() -> int:
    return int(time.time() * 1000.0)


def _interval_ms_from_rps(rps: float) -> int:
    rps_f = float(rps or 0.0)
    if rps_f <= 0.0:
        return 0
    return max(1, int(math.ceil(1000.0 / rps_f)))


def _sleep_seconds(reserved_at_epoch_ms: int) -> float:
    return max(0.0, (int(reserved_at_epoch_ms) - _now_epoch_ms()) / 1000.0)


@dataclass(frozen=True)
class ProviderRateLimitReservation:
    provider: str
    backend: str
    observed_at_epoch_ms: int
    reserved_at_epoch_ms: int
    next_allowed_at_epoch_ms: int
    min_interval_ms: int
    sleep_s: float


class ProviderRateLimitStore(Protocol):
    def reserve(
        self,
        *,
        provider: str,
        min_interval_ms: int,
        dispatch_buffer_ms: int,
        holder: Optional[str],
        run_id: Optional[str],
        stage: Optional[str],
        max_future_ms: int,
    ) -> ProviderRateLimitReservation:
        ...


class InMemoryProviderRateLimitStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._next_allowed_ms: dict[str, int] = {}

    def reserve(
        self,
        *,
        provider: str,
        min_interval_ms: int,
        dispatch_buffer_ms: int,
        holder: Optional[str],
        run_id: Optional[str],
        stage: Optional[str],
        max_future_ms: int,
    ) -> ProviderRateLimitReservation:
        del holder, run_id, stage
        now_ms = _now_epoch_ms()
        with self._lock:
            next_allowed_ms = int(self._next_allowed_ms.get(str(provider), 0) or 0)
            if max_future_ms > 0 and next_allowed_ms > now_ms + int(max_future_ms):
                next_allowed_ms = now_ms
            reserved_at_ms = max(now_ms + int(dispatch_buffer_ms), next_allowed_ms)
            new_next_allowed_ms = int(reserved_at_ms) + int(min_interval_ms)
            self._next_allowed_ms[str(provider)] = int(new_next_allowed_ms)

        return ProviderRateLimitReservation(
            provider=str(provider),
            backend="local",
            observed_at_epoch_ms=int(now_ms),
            reserved_at_epoch_ms=int(reserved_at_ms),
            next_allowed_at_epoch_ms=int(new_next_allowed_ms),
            min_interval_ms=int(min_interval_ms),
            sleep_s=_sleep_seconds(int(reserved_at_ms)),
        )


class FirestoreProviderRateLimitStore:
    def __init__(
        self,
        *,
        collection_name: str,
        db=None,
        max_transaction_attempts: int = 8,
    ):
        self.collection_name = str(collection_name or "").strip() or "quellenFinderProviderRateLimits"
        self.db = db or firebase_service.db
        self.max_transaction_attempts = max(1, int(max_transaction_attempts))

    def _doc_ref(self, provider: str):
        return self.db.collection(self.collection_name).document(str(provider).strip().lower())

    def reserve(
        self,
        *,
        provider: str,
        min_interval_ms: int,
        dispatch_buffer_ms: int,
        holder: Optional[str],
        run_id: Optional[str],
        stage: Optional[str],
        max_future_ms: int,
    ) -> ProviderRateLimitReservation:
        ref = self._doc_ref(provider)
        provider_norm = str(provider).strip().lower()

        last_exc: Exception | None = None
        for attempt in range(1, self.max_transaction_attempts + 1):
            transaction = self.db.transaction()

            @firestore.transactional
            def txn(txn_obj):
                now_ms = _now_epoch_ms()
                snap = ref.get(transaction=txn_obj)
                data = snap.to_dict() if snap.exists else {}
                next_allowed_ms = int((data or {}).get("nextAllowedAtEpochMs") or 0)
                reservation_count = int((data or {}).get("reservationCount") or 0)

                if max_future_ms > 0 and next_allowed_ms > now_ms + int(max_future_ms):
                    logger.warning(
                        "Resetting implausibly-future provider rate limit doc | provider=%s next_allowed_ms=%s now_ms=%s",
                        provider_norm,
                        next_allowed_ms,
                        now_ms,
                    )
                    next_allowed_ms = now_ms

                reserved_at_ms = max(now_ms + int(dispatch_buffer_ms), next_allowed_ms)
                new_next_allowed_ms = int(reserved_at_ms) + int(min_interval_ms)
                payload = {
                    "provider": provider_norm,
                    "backend": "firestore",
                    "minIntervalMs": int(min_interval_ms),
                    "nextAllowedAtEpochMs": int(new_next_allowed_ms),
                    "lastReservedAtEpochMs": int(reserved_at_ms),
                    "updatedAtEpochMs": int(now_ms),
                    "updatedAt": SERVER_TIMESTAMP,
                    "reservationCount": int(reservation_count) + 1,
                }
                holder_norm = str(holder or "").strip()
                run_id_norm = str(run_id or "").strip()
                stage_norm = str(stage or "").strip()
                if holder_norm:
                    payload["lastHolder"] = holder_norm
                if run_id_norm:
                    payload["lastRunId"] = run_id_norm
                if stage_norm:
                    payload["lastStage"] = stage_norm
                if not snap.exists:
                    payload["createdAt"] = SERVER_TIMESTAMP

                txn_obj.set(ref, payload, merge=True)
                return now_ms, reserved_at_ms, new_next_allowed_ms

            try:
                observed_at_ms, reserved_at_ms, new_next_allowed_ms = txn(transaction)
                return ProviderRateLimitReservation(
                    provider=provider_norm,
                    backend="firestore",
                    observed_at_epoch_ms=int(observed_at_ms),
                    reserved_at_epoch_ms=int(reserved_at_ms),
                    next_allowed_at_epoch_ms=int(new_next_allowed_ms),
                    min_interval_ms=int(min_interval_ms),
                    sleep_s=_sleep_seconds(int(reserved_at_ms)),
                )
            except Exception as exc:  # pragma: no cover - exercised via live Firestore script
                last_exc = exc
                if attempt >= self.max_transaction_attempts:
                    raise
                wait_s = min(2.0, 0.05 * (2 ** max(0, attempt - 1)))
                wait_s = max(0.01, wait_s * (1.0 + random.uniform(-0.2, 0.2)))
                time.sleep(wait_s)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"Failed to reserve provider rate limit slot for {provider_norm}")


class SharedProviderRateLimiter:
    def __init__(
        self,
        *,
        provider: str,
        rps: float,
        store: ProviderRateLimitStore,
        holder: Optional[str] = None,
        run_id: Optional[str] = None,
        stage: Optional[str] = None,
        max_future_ms: int = 86_400_000,
        dispatch_buffer_ms: int = 0,
    ):
        self.provider = str(provider).strip().lower()
        self.rps = float(rps or 0.0)
        self.min_interval_ms = _interval_ms_from_rps(self.rps)
        self.store = store
        self.holder = str(holder or "").strip() or None
        self.run_id = str(run_id or "").strip() or None
        self.stage = str(stage or "").strip() or None
        self.max_future_ms = max(0, int(max_future_ms))
        self.dispatch_buffer_ms = max(0, int(dispatch_buffer_ms))

    def acquire(self) -> ProviderRateLimitReservation | None:
        if self.min_interval_ms <= 0:
            return None
        reservation = self.store.reserve(
            provider=self.provider,
            min_interval_ms=int(self.min_interval_ms),
            dispatch_buffer_ms=int(self.dispatch_buffer_ms),
            holder=self.holder,
            run_id=self.run_id,
            stage=self.stage,
            max_future_ms=int(self.max_future_ms),
        )
        if float(reservation.sleep_s) > 0.0:
            time.sleep(float(reservation.sleep_s))
        return reservation


def build_provider_rate_limiter(
    *,
    provider: str,
    rps: float,
    backend: str,
    collection_name: str,
    holder: Optional[str],
    run_id: Optional[str],
    stage: Optional[str],
    max_future_ms: int,
    dispatch_buffer_ms: int,
) -> SharedProviderRateLimiter:
    backend_norm = str(backend or "firestore").strip().lower()
    if backend_norm not in {"firestore", "local"}:
        raise ValueError(f"Unsupported provider_rate_limit_backend: {backend}")

    store_key = f"{backend_norm}:{str(collection_name or '').strip().lower() or 'quellenfinderproviderratelimits'}"
    with _STORE_LOCK:
        if backend_norm == "local":
            store = _LOCAL_STORES.get(store_key)
            if store is None:
                store = InMemoryProviderRateLimitStore()
                _LOCAL_STORES[store_key] = store
        else:
            store = _FIRESTORE_STORES.get(store_key)
            if store is None:
                store = FirestoreProviderRateLimitStore(collection_name=collection_name)
                _FIRESTORE_STORES[store_key] = store

    return SharedProviderRateLimiter(
        provider=provider,
        rps=rps,
        store=store,
        holder=holder,
        run_id=run_id,
        stage=stage,
        max_future_ms=max_future_ms,
        dispatch_buffer_ms=dispatch_buffer_ms,
    )


def delete_provider_rate_limit_docs(*, collection_name: str, providers: list[str]) -> None:
    col = firebase_service.db.collection(str(collection_name or "").strip() or "quellenFinderProviderRateLimits")
    for provider in providers:
        provider_norm = str(provider or "").strip().lower()
        if not provider_norm:
            continue
        try:
            col.document(provider_norm).delete()
        except Exception:
            logger.warning("Failed to delete provider rate limit doc | collection=%s provider=%s", collection_name, provider_norm)
