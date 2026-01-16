from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.credits_service import get_credits_service

logger = logging.getLogger(__name__)


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return float(default)


def _status_norm(value: str | None) -> str:
    return str(value or "").strip().lower()


@dataclass(frozen=True)
class ReservationResult:
    result: str  # reserved | already_reserved | blocked | finalized
    status: str
    required_credits: float
    available_credits: float


class OpenAIBudgetService:
    """
    Concurrency-safe reservation engine on top of users/{uid}/billing/balance.reservedCredits.

    Creates/updates operation docs in:
      users/{uid}/costMetrics/v1/operations/{operationId}
    """

    def __init__(self, firebase_service):
        self.firebase = firebase_service

    def _balance_ref(self, user_id: str):
        return (
            self.firebase.db.collection("users")
            .document(user_id)
            .collection("billing")
            .document("balance")
        )

    def _operation_ref(self, user_id: str, operation_id: str):
        return (
            self.firebase.db.collection("users")
            .document(user_id)
            .collection("costMetrics")
            .document("v1")
            .collection("operations")
            .document(operation_id)
        )

    def _compute_total_and_available(self, user_id: str, balance: dict) -> tuple[float, float, float]:
        credits_service = get_credits_service(self.firebase)
        sub, topup, _expires_at = credits_service._normalize_balance(balance)  # pylint: disable=protected-access
        total = float(sub + topup)
        reserved = _as_float((balance or {}).get("reservedCredits"), 0.0)
        available = float(total - reserved)
        return total, reserved, available

    async def reserve_operation(
        self,
        *,
        user_id: str,
        operation_id: str,
        operation_type: str,
        user_action_id: str,
        estimate: dict,
        projekt_id: str | None = None,
        kapitel_id: str | None = None,
        run_id: str | None = None,
        quelle_id: str | None = None,
        operation_details: dict | None = None,
    ) -> ReservationResult:
        uid = str(user_id or "").strip()
        op_id = str(operation_id or "").strip()
        if not uid:
            raise ValueError("user_id is required")
        if not op_id:
            raise ValueError("operation_id is required")

        required = _as_float((estimate or {}).get("credits"), 0.0)
        if required <= 0:
            raise ValueError("estimate.credits must be > 0 for reservations")

        op_ref = self._operation_ref(uid, op_id)
        balance_ref = self._balance_ref(uid)

        now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        transaction = self.firebase.db.transaction()

        @firestore.transactional
        def txn(transaction):
            op_snap = op_ref.get(transaction=transaction)
            if op_snap.exists:
                existing = op_snap.to_dict() or {}
                existing_status = _status_norm(existing.get("status"))
                if existing_status in {"reserved", "running"}:
                    bal_snap = balance_ref.get(transaction=transaction)
                    bal = bal_snap.to_dict() if bal_snap.exists else {}
                    _total, _reserved, available = self._compute_total_and_available(uid, bal)
                    return ReservationResult(
                        result="already_reserved",
                        status=existing_status or "reserved",
                        required_credits=float(required),
                        available_credits=float(available),
                    )
                if existing_status in {"success", "error", "blocked", "skipped"}:
                    bal_snap = balance_ref.get(transaction=transaction)
                    bal = bal_snap.to_dict() if bal_snap.exists else {}
                    _total, _reserved, available = self._compute_total_and_available(uid, bal)
                    return ReservationResult(
                        result="finalized",
                        status=existing_status,
                        required_credits=float(required),
                        available_credits=float(available),
                    )

            bal_snap = balance_ref.get(transaction=transaction)
            balance = bal_snap.to_dict() if bal_snap.exists else {}
            _total, reserved, available = self._compute_total_and_available(uid, balance)

            if float(available) < float(required):
                transaction.set(
                    op_ref,
                    {
                        "operationId": op_id,
                        "userId": uid,
                        "userActionId": str(user_action_id or "").strip() or None,
                        "operationType": str(operation_type or "").strip(),
                        "operationDetails": operation_details,
                        "status": "blocked",
                        "errorMessage": "Insufficient available credits for estimate.",
                        "timestamp": SERVER_TIMESTAMP,
                        "projektId": projekt_id,
                        "kapitelId": kapitel_id,
                        "runId": run_id,
                        "quelleId": quelle_id,
                        "estimate": estimate,
                        "reservation": {
                            "reservedCredits": float(required),
                            "reservedAt": SERVER_TIMESTAMP,
                            "releasedAt": SERVER_TIMESTAMP,
                            "releaseReason": "blocked",
                            "debug": {"availableCredits": float(available), "checkedAt": now_iso},
                        },
                    },
                    merge=True,
                )

                return ReservationResult(
                    result="blocked",
                    status="blocked",
                    required_credits=float(required),
                    available_credits=float(available),
                )

            transaction.set(
                balance_ref,
                {
                    "reservedCredits": float(reserved + float(required)),
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )

            transaction.set(
                op_ref,
                {
                    "operationId": op_id,
                    "userId": uid,
                    "userActionId": str(user_action_id or "").strip() or None,
                    "operationType": str(operation_type or "").strip(),
                    "operationDetails": operation_details,
                    "status": "reserved",
                    "timestamp": SERVER_TIMESTAMP,
                    "projektId": projekt_id,
                    "kapitelId": kapitel_id,
                    "runId": run_id,
                    "quelleId": quelle_id,
                    "estimate": estimate,
                    "reservation": {
                        "reservedCredits": float(required),
                        "reservedAt": SERVER_TIMESTAMP,
                        "releasedAt": None,
                        "releaseReason": None,
                        "debug": {"availableCredits": float(available), "checkedAt": now_iso},
                    },
                },
                merge=True,
            )

            return ReservationResult(
                result="reserved",
                status="reserved",
                required_credits=float(required),
                available_credits=float(available),
            )

        return txn(transaction)

    async def mark_running(self, *, user_id: str, operation_id: str) -> None:
        uid = str(user_id or "").strip()
        op_id = str(operation_id or "").strip()
        if not uid or not op_id:
            return
        ref = self._operation_ref(uid, op_id)
        ref.set({"status": "running", "runningAt": SERVER_TIMESTAMP}, merge=True)

    async def mark_status(
        self,
        *,
        user_id: str,
        operation_id: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        uid = str(user_id or "").strip()
        op_id = str(operation_id or "").strip()
        if not uid or not op_id:
            return
        st = _status_norm(status) or "error"
        payload = {"status": st}
        if error_message is not None:
            payload["errorMessage"] = str(error_message)[:1000]
        self._operation_ref(uid, op_id).set(payload, merge=True)

    async def release_reservation(
        self,
        *,
        user_id: str,
        operation_id: str,
        reason: str,
    ) -> None:
        uid = str(user_id or "").strip()
        op_id = str(operation_id or "").strip()
        if not uid or not op_id:
            return

        op_ref = self._operation_ref(uid, op_id)
        balance_ref = self._balance_ref(uid)

        transaction = self.firebase.db.transaction()

        @firestore.transactional
        def txn(transaction):
            op_snap = op_ref.get(transaction=transaction)
            if not op_snap.exists:
                return False
            op = op_snap.to_dict() or {}
            reservation = op.get("reservation") if isinstance(op.get("reservation"), dict) else {}
            if reservation and reservation.get("releasedAt"):
                return False

            reserved_amt = _as_float(reservation.get("reservedCredits"), 0.0)
            if reserved_amt <= 0:
                reserved_amt = _as_float(((op.get("estimate") or {}) if isinstance(op.get("estimate"), dict) else {}).get("credits"), 0.0)

            bal_snap = balance_ref.get(transaction=transaction)
            bal = bal_snap.to_dict() if bal_snap.exists else {}
            current_reserved = _as_float((bal or {}).get("reservedCredits"), 0.0)
            next_reserved = float(current_reserved - float(max(reserved_amt, 0.0)))
            if next_reserved < 0:
                next_reserved = 0.0

            transaction.set(
                balance_ref,
                {
                    "reservedCredits": float(next_reserved),
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )

            transaction.set(
                op_ref,
                {
                    "reservation": {
                        "releasedAt": SERVER_TIMESTAMP,
                        "releaseReason": str(reason or "unknown"),
                    }
                },
                merge=True,
            )

            return True

        try:
            txn(transaction)
        except Exception as exc:
            logger.warning("Failed to release reservation user=%s op=%s: %s", uid, op_id, exc, exc_info=True)


_openai_budget_service_instance: Optional[OpenAIBudgetService] = None


def get_openai_budget_service(firebase_service) -> OpenAIBudgetService:
    global _openai_budget_service_instance
    if _openai_budget_service_instance is None:
        _openai_budget_service_instance = OpenAIBudgetService(firebase_service)
    return _openai_budget_service_instance

