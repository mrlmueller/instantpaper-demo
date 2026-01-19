from fastapi import FastAPI, Depends, BackgroundTasks, status, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from utils.config import config
from middleware.auth import (
    verify_firebase_token,
    verify_admin_user,
    verify_firebase_token_decoded,
    verify_firebase_token_decoded_any_user,
    verify_system_prompt_export_user,
)
from models.request import (
    ProcessQuelleRequest,
    CombineRunRequest,
    AdoptCombinedRequest,
    ShortenKapitelRequest,
    LeseflussKapitelRequest,
    ExportDocxRequest,
    RefineCombinedInitRequest,
    RefineCombinedRequest,
    RefineShortenedInitRequest,
    RefineShortenedRequest,
    RefineLeseflussInitRequest,
    RefineLeseflussRequest,
    RefineResultInitRequest,
    RefineResultRequest,
)
from models.response import ProcessQuelleResponse
from services.quelle_service import quelle_service
from services.shorten_service import shorten_service
from services.user_key_service import user_key_service
from services.refinement_service import refinement_service
from services.firebase_service import firebase_service
from services.credits_service import get_credits_service
from services.prompt_service import prompt_service
from services.export_service import export_service
from firebase_admin import auth
from google.cloud.firestore_v1 import SERVER_TIMESTAMP
from google.cloud import firestore
from pydantic import BaseModel
import logging
import base64
import json
import secrets
import hashlib
import os
import re
from pathlib import Path
import html as html_lib
from urllib.parse import parse_qs
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from utils.logging_config import configure_logging

# Configure logging early (no file logs; keep uvicorn access logs).
configure_logging()

logger = logging.getLogger(__name__)
basic_security = HTTPBasic()

ALLOWED_PROMPT_STAGES = {"process_quelle", "combine", "summary", "shorten", "lesefluss"}
SYSTEM_TEMPLATE_KEYS_ALWAYS_AVAILABLE = {"default", "default_v2"}
TEMPLATE_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def _safe_env_diagnostics() -> dict:
    """
    Safe diagnostics for env injection issues (never includes secret values).

    Intended for logs only.
    """
    admin_env_keys = sorted([k for k in os.environ.keys() if "ADMIN" in k.upper()])
    return {
        "k_service": os.getenv("K_SERVICE", ""),
        "k_revision": os.getenv("K_REVISION", ""),
        "k_configuration": os.getenv("K_CONFIGURATION", ""),
        "env_count": len(os.environ),
        "admin_env_keys": admin_env_keys,
        "admin_basic_user_present": "ADMIN_BASIC_USER" in os.environ,
        "admin_basic_password_present": "ADMIN_BASIC_PASSWORD" in os.environ,
        "admin_basic_password_len": len(os.getenv("ADMIN_BASIC_PASSWORD", "") or ""),
        "dot_env_present": Path(".env").exists(),
        "fastapi_dot_env_present": Path("fastapi/.env").exists(),
    }


class SaveOpenAIKeyRequest(BaseModel):
    key: str


class CreateSessionRequest(BaseModel):
    idToken: str


class RevokeSessionRequest(BaseModel):
    sessionCookie: str


class AdminApproveUserRequest(BaseModel):
    email: str
    approved: bool = True  # Legacy: maps to `fullAccess`


class AdminSetFullAccessRequest(BaseModel):
    email: str
    fullAccess: bool = True


class AdminSetBlockedRequest(BaseModel):
    email: str
    blocked: bool = True


class AdminSetSpendRateRequest(BaseModel):
    spendRate: float | None = None


class AdminCreateCreditAdjustmentRequest(BaseModel):
    credits: float
    note: str | None = None


class AdminAdjustReservedCreditsRequest(BaseModel):
    mode: str  # "set" | "delta"
    amount: float
    note: str | None = None


class RedeemAccessCodeRequest(BaseModel):
    code: str


class AdminCreateAccessCodeRequest(BaseModel):
    name: str
    maxUses: int = 1
    note: str | None = None


class AdminUpdateAccessCodeRequest(BaseModel):
    disabled: bool | None = None
    name: str | None = None
    maxUses: int | None = None
    note: str | None = None


class AdminSetSystemPromptExportRequest(BaseModel):
    email: str
    canDuplicateSystemPrompts: bool


class AdminSetUsageInsightsRequest(BaseModel):
    email: str
    canViewUsageInsights: bool


class AdminUpsertSystemPromptTemplateRequest(BaseModel):
    stage: str
    templateKey: str
    name: str
    instructions: str
    systemPrompt: str | None = None
    published: bool = True
    archived: bool = False


class DuplicateSystemPromptTemplateRequest(BaseModel):
    stage: str
    templateKey: str
    name: str | None = None


class AdminCreateUserPromptTemplateRequest(BaseModel):
    stage: str
    name: str
    instructions: str


class AdminUpdateUserPromptTemplateRequest(BaseModel):
    name: str
    instructions: str


class AdminSetActiveUserPromptRequest(BaseModel):
    stage: str
    templateId: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for startup and shutdown"""
    # Startup
    logger.debug("Starting InstantPaper API server...")
    logger.debug(f"Debug mode: {config.DEBUG}")
    logger.debug(f"Allowed origins: {config.ALLOWED_ORIGINS}")

    # Safe diagnostics (no secrets) to debug Cloud Run env injection issues.
    if not config.ADMIN_BASIC_PASSWORD:
        diag = _safe_env_diagnostics()
        logger.warning(
            "ADMIN_BASIC_PASSWORD is empty (admin approval endpoints disabled). env_diag=%s",
            diag,
        )

    yield

    # Shutdown (if needed in the future)
    logger.debug("Shutting down InstantPaper API server...")


# Initialize FastAPI app with lifespan
app = FastAPI(
    title="InstantPaper API",
    version="1.0.0",
    description="FastAPI backend for processing Quellen with OpenAI",
    lifespan=lifespan,
)

# Configure CORS to allow Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    # Allow all methods so the frontend can preflight DELETE for removing API keys
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "InstantPaper API", "version": "1.0.0", "status": "running"}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    # Basic health check - in future phases we'll add Firebase and OpenAI connectivity checks
    return {
        "status": "healthy",
        "version": "1.0.0",
        "firebase": "connected" if config.FIREBASE_PROJECT_ID else "not configured",
        "openai": "connected" if config.OPENAI_API_KEY else "not configured",
        "adminApprovalConfigured": bool(config.ADMIN_BASIC_PASSWORD),
        "firebaseClockSkewSeconds": config.FIREBASE_CLOCK_SKEW_SECONDS,
    }


@app.get("/api/admin/me")
async def admin_me(_: str = Depends(verify_admin_user)):
    """Admin-only probe endpoint used by the frontend gate."""
    return {"status": "ok"}


def _ms_to_iso(ts_ms: int | None) -> str | None:
    if not ts_ms:
        return None
    try:
        return (
            datetime.utcfromtimestamp(int(ts_ms) / 1000.0)
            .replace(microsecond=0)
            .isoformat()
            + "Z"
        )
    except Exception:
        return None


def _ts_to_iso(value) -> str | None:
    if not value:
        return None
    try:
        if hasattr(value, "to_datetime"):
            value = value.to_datetime()
        if isinstance(value, datetime):
            dt = value
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            dt = dt.replace(microsecond=0)
            return dt.isoformat().replace("+00:00", "Z")
    except Exception:
        return None
    return None


def _normalize_access_code(raw: str) -> str:
    return str(raw or "").strip().upper().replace(" ", "").replace("_", "-")


ACCESS_CODE_RE = re.compile(r"^[A-Z]{2}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")


def _access_codes_doc():
    return firebase_service.db.collection("_config").document("accessCodes")


def _access_codes_col():
    return _access_codes_doc().collection("codes")


def _access_code_ref(code: str):
    return _access_codes_col().document(code)


def _access_code_attempts_col():
    return _access_codes_doc().collection("attempts")


def _access_code_rate_limits_col():
    return _access_codes_doc().collection("rateLimits")


def _read_client_ip(request: Request) -> str | None:
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        # First hop is the client IP.
        ip = xff.split(",")[0].strip()
        return ip or None
    xrip = (request.headers.get("x-real-ip") or "").strip()
    if xrip:
        return xrip
    return getattr(getattr(request, "client", None), "host", None) or None


def _truncate_header(value: str | None, max_len: int) -> str | None:
    if not value:
        return None
    txt = str(value)
    if len(txt) <= max_len:
        return txt
    return txt[:max_len]


def _rate_bucket(now: datetime, window_seconds: int) -> int:
    return int(now.timestamp()) // int(window_seconds)


def _hash_rate_key(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:32]


def _check_and_increment_rate_limit(
    *, kind: str, key: str, limit: int, window_seconds: int
) -> bool:
    """
    Returns True if allowed, False if rate-limited.

    Uses Firestore transaction counters stored under `_config/accessCodes/rateLimits/*`.
    """
    kind_norm = str(kind or "").strip().lower()
    key_norm = str(key or "").strip()
    if not kind_norm or not key_norm:
        return True

    now = datetime.now(timezone.utc)
    bucket = _rate_bucket(now, window_seconds)
    key_hash = _hash_rate_key(key_norm)
    doc_id = f"redeem-{kind_norm}-{bucket}-{key_hash}"
    ref = _access_code_rate_limits_col().document(doc_id)

    transaction = firebase_service.db.transaction()

    @firestore.transactional
    def txn(transaction):
        snap = ref.get(transaction=transaction)
        current = 0
        if snap.exists:
            current = int((snap.to_dict() or {}).get("count") or 0)
        if current >= int(limit):
            return False

        payload = {
            "kind": kind_norm,
            "keyHash": key_hash,
            "bucket": int(bucket),
            "windowSeconds": int(window_seconds),
            "count": int(current) + 1,
            "updatedAt": SERVER_TIMESTAMP,
        }
        if not snap.exists:
            payload["createdAt"] = SERVER_TIMESTAMP
            payload["key"] = key_norm
        transaction.set(ref, payload, merge=True)
        return True

    return bool(txn(transaction))


async def _is_user_blocked(uid: str) -> bool:
    uid_norm = (uid or "").strip()
    if not uid_norm:
        return True
    try:
        doc = await firebase_service.get_user_doc(uid_norm)
    except Exception:
        # Fail-closed on transient Firestore reads.
        return True
    if not doc:
        return False
    return str(doc.get("accountStatus") or "").strip().lower() == "blocked"


async def _can_user_view_usage_insights(uid: str) -> bool:
    uid_norm = (uid or "").strip()
    if not uid_norm:
        return False
    try:
        doc = await firebase_service.get_user_doc(uid_norm)
    except Exception:
        return False
    return bool((doc or {}).get("canViewUsageInsights") is True)


@app.get("/api/me")
async def get_me(decoded_token: dict = Depends(verify_firebase_token_decoded_any_user)):
    uid = str(decoded_token.get("uid") or "").strip()
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token (missing uid).")

    email = (decoded_token.get("email") or "").strip() or None

    try:
        claims = await firebase_service.get_user_custom_claims(uid)
    except Exception:
        claims = {}

    full_access = bool(
        claims.get("fullAccess") is True or claims.get("approved") is True
    )
    legacy_approved = bool(claims.get("approved") is True)

    try:
        user_doc = await firebase_service.get_user_doc(uid)
    except Exception:
        user_doc = None

    status = str((user_doc or {}).get("accountStatus") or "").strip().lower()
    blocked = status == "blocked"
    if not status:
        status = "active" if full_access else "pending"

    can_view_usage_insights = bool((user_doc or {}).get("canViewUsageInsights") is True)

    return {
        "uid": uid,
        "email": email,
        "accountStatus": status,
        "blocked": blocked,
        "fullAccess": full_access,
        "legacyApproved": legacy_approved,
        "canViewUsageInsights": can_view_usage_insights,
    }


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return float(default)


def _epoch_to_iso(value) -> str | None:
    """
    Convert a Stripe-style epoch (seconds or ms) to ISO.
    Returns None for invalid values.
    """
    try:
        if value is None:
            return None
        n = float(value)
        if not n:
            return None
        # Heuristic: Stripe epochs are seconds; treat very large values as ms.
        ms = int(n if n > 1e12 else n * 1000.0)
        return (
            datetime.utcfromtimestamp(ms / 1000.0).replace(microsecond=0).isoformat()
            + "Z"
        )
    except Exception:
        return None


def _compute_balance_summary(data: dict | None) -> dict:
    topup_credits = _as_float((data or {}).get("topupCredits"), 0.0)
    subscription_credits_raw = _as_float((data or {}).get("subscriptionCredits"), 0.0)
    subscription_expires_at = (data or {}).get("subscriptionExpiresAt")
    reserved_credits = _as_float((data or {}).get("reservedCredits"), 0.0)

    subscription_active = subscription_credits_raw
    if subscription_expires_at:
        try:
            dt = (
                subscription_expires_at.to_datetime()
                if hasattr(subscription_expires_at, "to_datetime")
                else subscription_expires_at
            )
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt <= datetime.now(timezone.utc):
                    subscription_active = 0.0
        except Exception:
            pass

    total = subscription_active + topup_credits
    available = float(total - reserved_credits)
    return {
        "totalCredits": float(total),
        "subscriptionCredits": float(subscription_active),
        "subscriptionExpiresAt": _ts_to_iso(subscription_expires_at),
        "topupCredits": float(topup_credits),
        "reservedCredits": float(reserved_credits),
        "availableCredits": float(available),
        "isNegative": bool(total < 0),
    }


async def _read_subscription_summary_for_user(user_id: str) -> dict | None:
    try:
        subs_ref = (
            firebase_service.db.collection("customers")
            .document(user_id)
            .collection("subscriptions")
        )
        subs = list(subs_ref.stream())
    except Exception:
        subs = []

    best = None
    best_id = None
    best_status = ""

    def _score(status: str) -> int:
        s = (status or "").strip().lower()
        if s == "active":
            return 4
        if s == "trialing":
            return 3
        if s == "past_due":
            return 2
        if s:
            return 1
        return 0

    for snap in subs:
        data = snap.to_dict() or {}
        status = str(data.get("status") or "").strip()
        if best is None or _score(status) > _score(best_status):
            best = data
            best_id = snap.id
            best_status = status

    if not best:
        return None

    current_period_end = best.get("current_period_end")
    return {
        "id": best_id,
        "status": str(best.get("status") or "") or None,
        "cancelAtPeriodEnd": bool(best.get("cancel_at_period_end") is True),
        "currentPeriodEnd": _ts_to_iso(current_period_end)
        or _epoch_to_iso(current_period_end),
    }


@app.get("/api/billing/balance")
async def billing_get_balance(user_id: str = Depends(verify_firebase_token)):
    """
    Return the user's cached credit balance.

    Source of truth for writes is the server-side credit ledger; this endpoint returns a safe read model.
    """
    try:
        await get_credits_service(firebase_service).sync_stripe_grants_for_user(user_id)
    except Exception:
        pass

    try:
        bal_ref = (
            firebase_service.db.collection("users")
            .document(user_id)
            .collection("billing")
            .document("balance")
        )
        bal_snap = bal_ref.get()
        data = bal_snap.to_dict() if bal_snap.exists else {}
    except Exception:
        data = {}

    return {"balance": _compute_balance_summary(data)}


@app.get("/api/billing/ledger")
async def billing_get_ledger(
    limit: int = 50,
    cursor: str | None = None,
    user_id: str = Depends(verify_firebase_token),
):
    """
    Return credit ledger entries (paginated, newest first).

    Cursor is the last returned entry id (doc id).
    """
    limit = max(1, min(int(limit or 50), 200))

    try:
        await get_credits_service(firebase_service).sync_stripe_grants_for_user(user_id)
    except Exception:
        pass

    base = (
        firebase_service.db.collection("users")
        .document(user_id)
        .collection("creditLedger")
        .order_by("createdAt", direction=firestore.Query.DESCENDING)
    )

    if cursor:
        try:
            cursor_snap = (
                firebase_service.db.collection("users")
                .document(user_id)
                .collection("creditLedger")
                .document(str(cursor))
                .get()
            )
            if cursor_snap.exists:
                base = base.start_after(cursor_snap)
        except Exception:
            pass

    docs = list(base.limit(limit).stream())
    out = []
    for snap in docs:
        data = snap.to_dict() or {}
        out.append(
            {
                "id": snap.id,
                "type": str(data.get("type") or ""),
                "source": str(data.get("source") or ""),
                "credits": _as_float(data.get("credits"), 0.0),
                "createdAt": _ts_to_iso(data.get("createdAt")),
                "expiresAt": _ts_to_iso(data.get("expiresAt")),
            }
        )

    next_cursor = docs[-1].id if len(docs) == limit else None
    return {"entries": out, "nextCursor": next_cursor}


@app.get("/api/billing/status")
async def billing_get_status(user_id: str = Depends(verify_firebase_token)):
    """
    Return a safe summary of the Stripe subscription status (read-only).

    Data comes from the Firebase Stripe Extension synced collection: customers/{uid}/subscriptions/*.
    """
    return {"subscription": await _read_subscription_summary_for_user(user_id)}


@app.get("/api/usage-insights/run/{run_id}")
async def usage_insights_run_summary(
    run_id: str,
    user_id: str = Depends(verify_firebase_token),
):
    """
    Return a credits-only summary for a single run (grouped by operationType).

    This is gated via `users/{uid}.canViewUsageInsights`.
    """
    run_id_norm = str(run_id or "").strip()
    if not run_id_norm:
        raise HTTPException(status_code=400, detail="run_id is required.")

    if not await _can_user_view_usage_insights(user_id):
        raise HTTPException(status_code=403, detail="Usage insights not enabled for this user.")

    ops_ref = (
        firebase_service.db.collection("users")
        .document(user_id)
        .collection("costMetrics")
        .document("v1")
        .collection("operations")
    )

    by_type: dict[str, dict] = {}
    try:
        docs = list(ops_ref.where("runId", "==", run_id_norm).stream())
    except Exception:
        docs = []

    for snap in docs:
        data = snap.to_dict() or {}
        op_type = str(data.get("operationType") or "").strip() or "unknown"

        costs = data.get("costs") if isinstance(data.get("costs"), dict) else {}
        cost_usd = _as_float((costs or {}).get("totalCostUsd"), 0.0)

        credits = _as_float(data.get("creditsDebited"), 0.0)
        if credits <= 0:
            spend_rate = _as_float(data.get("spendRate"), 0.0)
            if spend_rate > 0 and cost_usd > 0:
                credits = float(cost_usd * spend_rate)

        entry = by_type.get(op_type)
        if not entry:
            entry = {"operationType": op_type, "count": 0, "credits": 0.0, "costUsd": 0.0}
            by_type[op_type] = entry

        entry["count"] = int(entry.get("count") or 0) + 1
        entry["credits"] = float(entry.get("credits") or 0.0) + float(max(credits, 0.0))
        entry["costUsd"] = float(entry.get("costUsd") or 0.0) + float(max(cost_usd, 0.0))

    items = list(by_type.values())
    items.sort(
        key=lambda x: (
            -_as_float(x.get("credits"), 0.0),
            -int(x.get("count") or 0),
            str(x.get("operationType") or ""),
        )
    )
    total_credits = sum(_as_float(item.get("credits"), 0.0) for item in items)
    total_cost_usd = sum(_as_float(item.get("costUsd"), 0.0) for item in items)

    return {
        "runId": run_id_norm,
        "totalCredits": float(total_credits),
        "totalCostUsd": float(total_cost_usd),
        "byOperationType": items,
    }


@app.get("/api/usage-insights/stats")
async def usage_insights_stats(user_id: str = Depends(verify_firebase_token)):
    """
    Usage insights (credits-first) for the current user.

    This is gated via `users/{uid}.canViewUsageInsights`.
    """
    if not await _can_user_view_usage_insights(user_id):
        raise HTTPException(status_code=403, detail="Usage insights not enabled for this user.")

    # Counts (best-effort)
    def _count(col_ref) -> int:
        try:
            return len(list(col_ref.stream()))
        except Exception:
            return 0

    total_projects = _count(firebase_service.db.collection("users").document(user_id).collection("projects"))
    total_kapitel = _count(firebase_service.db.collection("users").document(user_id).collection("kapitels"))
    total_quellen = _count(firebase_service.db.collection("users").document(user_id).collection("quellen"))

    # USD aggregates (optional, for internal reference)
    agg = {}
    try:
        agg_ref = (
            firebase_service.db.collection("users")
            .document(user_id)
            .collection("costMetrics")
            .document("v1")
            .collection("aggregatesByUser")
            .document("lifetime")
        )
        snap = agg_ref.get()
        agg = snap.to_dict() if snap.exists else {}
    except Exception:
        agg = {}

    total_runs = int((agg or {}).get("operationCount") or 0)
    total_cost_usd = _as_float((agg or {}).get("totalCostUsd"), 0.0)
    total_output_tokens = int((agg or {}).get("totalOutputTokens") or 0)
    total_words = max(0, int(round(total_output_tokens * 0.75)))

    by_op = (agg or {}).get("byOperationType") if isinstance((agg or {}).get("byOperationType"), dict) else {}
    export_agg = by_op.get("export_docx") if isinstance(by_op.get("export_docx"), dict) else {}
    export_cost_usd = _as_float((export_agg or {}).get("totalCostUsd"), 0.0)
    export_count = int((export_agg or {}).get("count") or 0)

    spend_rate_fallback = 6.0
    try:
        spend_rate_fallback = float(await get_credits_service(firebase_service).get_spend_rate_for_user(user_id))
        if spend_rate_fallback <= 0:
            spend_rate_fallback = 6.0
    except Exception:
        spend_rate_fallback = 6.0

    # Scan operations (bounded) to compute credits-based breakdowns.
    ops_ref = (
        firebase_service.db.collection("users")
        .document(user_id)
        .collection("costMetrics")
        .document("v1")
        .collection("operations")
        .order_by("timestamp", direction=firestore.Query.DESCENDING)
    )

    by_month: dict[str, dict] = {}
    by_project: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    by_operation_type: dict[str, dict] = {}
    credits_total = 0.0

    batch_size = 500
    max_docs = 5000
    cursor = None
    scanned = 0

    while scanned < max_docs:
        q = ops_ref
        if cursor is not None:
            q = q.start_after(cursor)
        batch = list(q.limit(batch_size).stream())
        if not batch:
            break

        for snap in batch:
            data = snap.to_dict() or {}

            op_type = str(data.get("operationType") or "").strip() or "unknown"
            credits = _as_float(data.get("creditsDebited"), 0.0)
            if credits <= 0:
                spend_rate = _as_float(data.get("spendRate"), 0.0)
                costs = data.get("costs") if isinstance(data.get("costs"), dict) else {}
                cost_usd = _as_float((costs or {}).get("totalCostUsd"), 0.0)
                if cost_usd > 0:
                    rate = spend_rate if spend_rate > 0 else spend_rate_fallback
                    credits = float(cost_usd * rate)

            credits = float(max(credits, 0.0))
            credits_total += credits

            op_entry = by_operation_type.get(op_type)
            if not op_entry:
                op_entry = {"operationType": op_type, "count": 0, "credits": 0.0}
                by_operation_type[op_type] = op_entry
            op_entry["count"] = int(op_entry.get("count") or 0) + 1
            op_entry["credits"] = float(op_entry.get("credits") or 0.0) + credits

            year_month = str(data.get("yearMonth") or "").strip()
            if year_month:
                entry = by_month.get(year_month)
                if not entry:
                    entry = {"key": year_month, "count": 0, "credits": 0.0}
                    by_month[year_month] = entry
                entry["count"] = int(entry.get("count") or 0) + 1
                entry["credits"] = float(entry.get("credits") or 0.0) + credits

            projekt_id = str(data.get("projektId") or "").strip() or "unknown"
            proj_entry = by_project.get(projekt_id)
            if not proj_entry:
                proj_name = None
                snapshots = data.get("snapshots") if isinstance(data.get("snapshots"), dict) else {}
                proj_snap = snapshots.get("projekt") if isinstance(snapshots.get("projekt"), dict) else {}
                if proj_snap:
                    proj_name = (proj_snap.get("name") or "").strip() or None
                proj_entry = {"projektId": projekt_id, "projektName": proj_name or projekt_id, "credits": 0.0}
                by_project[projekt_id] = proj_entry
            proj_entry["credits"] = float(proj_entry.get("credits") or 0.0) + credits

            model_key = str(data.get("modelNormalized") or data.get("model") or "unknown").strip() or "unknown"
            model_entry = by_model.get(model_key)
            if not model_entry:
                model_entry = {"model": model_key, "count": 0, "credits": 0.0}
                by_model[model_key] = model_entry
            model_entry["count"] = int(model_entry.get("count") or 0) + 1
            model_entry["credits"] = float(model_entry.get("credits") or 0.0) + credits

        scanned += len(batch)
        cursor = batch[-1]
        if len(batch) < batch_size:
            break

    # Last 6 months including current (chronological)
    month_keys = []
    current = datetime.utcnow().replace(day=1)
    for i in range(5, -1, -1):
        m = current.month - i
        y = current.year
        while m <= 0:
            m += 12
            y -= 1
        month_keys.append(f"{y:04d}-{m:02d}")

    runs_by_month = []
    for key in month_keys:
        entry = by_month.get(key) or {}
        runs_by_month.append(
            {
                "key": key,
                "count": int(entry.get("count") or 0),
                "credits": _as_float(entry.get("credits"), 0.0),
            }
        )

    credits_by_project = list(by_project.values())
    credits_by_project.sort(key=lambda x: -_as_float(x.get("credits"), 0.0))
    credits_by_project = credits_by_project[:10]

    model_usage = list(by_model.values())
    model_usage.sort(key=lambda x: (-int(x.get("count") or 0), -_as_float(x.get("credits"), 0.0)))
    if not model_usage:
        model_usage = [{"model": "-", "count": 0, "credits": 0.0}]

    op_breakdown = list(by_operation_type.values())
    op_breakdown.sort(
        key=lambda x: (
            -_as_float(x.get("credits"), 0.0),
            -int(x.get("count") or 0),
            str(x.get("operationType") or ""),
        )
    )

    effective_spend_rate = float(spend_rate_fallback if spend_rate_fallback > 0 else 6.0)
    estimated_cost_usd = float(credits_total / effective_spend_rate) if effective_spend_rate > 0 else 0.0

    member_since = None
    try:
        user_doc = await firebase_service.get_user_doc(user_id)
        member_since = _ts_to_iso((user_doc or {}).get("createdAt"))
    except Exception:
        member_since = None
    if not member_since:
        member_since = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    return {
        "creditsTotal": float(credits_total),
        "spendRate": float(effective_spend_rate),
        "estimatedCostUsd": float(estimated_cost_usd),
        "runsTotal": int(total_runs),
        "exportCount": int(export_count),
        "totalProjects": int(total_projects),
        "totalKapitel": int(total_kapitel),
        "totalQuellen": int(total_quellen),
        "totalWords": int(total_words),
        "runsByMonth": runs_by_month,
        "creditsByProject": credits_by_project,
        "byOperationType": op_breakdown[:25],
        "modelUsage": model_usage,
        "memberSince": member_since,
        "usd": {
            "totalCostUsd": float(total_cost_usd),
            "exportCostUsd": float(export_cost_usd),
        },
        "limits": {"maxOperationsScanned": int(max_docs), "operationsScanned": int(scanned)},
    }


@app.post("/api/access-codes/redeem")
async def redeem_access_code(
    payload: RedeemAccessCodeRequest,
    request: Request,
    decoded_token: dict = Depends(verify_firebase_token_decoded_any_user),
):
    uid = str(decoded_token.get("uid") or "").strip()
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token (missing uid).")

    email = (decoded_token.get("email") or "").strip() or None
    display_name = (decoded_token.get("name") or "").strip() or None

    code_in = _normalize_access_code(payload.code)
    if not code_in or not ACCESS_CODE_RE.match(code_in):
        raise HTTPException(status_code=400, detail="Ungültiger Code.")

    # Hard gate: blocked overrides everything (including redeem).
    if await _is_user_blocked(uid):
        raise HTTPException(status_code=403, detail="Account gesperrt.")

    ip = _read_client_ip(request)
    user_agent = _truncate_header(request.headers.get("user-agent"), 400)

    # Rate limit: per-uid and per-ip (best-effort; deny if limit exceeded).
    try:
        if not _check_and_increment_rate_limit(
            kind="uid", key=uid, limit=5, window_seconds=300
        ):
            raise HTTPException(
                status_code=429,
                detail="Zu viele Versuche. Bitte warte kurz und versuche es erneut.",
            )
        if ip and not _check_and_increment_rate_limit(
            kind="ip", key=ip, limit=20, window_seconds=300
        ):
            raise HTTPException(
                status_code=429,
                detail="Zu viele Versuche. Bitte warte kurz und versuche es erneut.",
            )
    except HTTPException:
        raise
    except Exception:
        # Fail-closed: treat rate-limit failures as denial.
        raise HTTPException(
            status_code=429,
            detail="Zu viele Versuche. Bitte warte kurz und versuche es erneut.",
        ) from None

    # Do not consume uses if the user already has access (authoritative, not token-based).
    try:
        current_claims = await firebase_service.get_user_custom_claims(uid)
    except Exception:
        current_claims = {}
    if bool(
        current_claims.get("fullAccess") is True
        or current_claims.get("approved") is True
    ):
        _access_code_attempts_col().document().set(
            {
                "uid": uid,
                "email": email,
                "displayName": display_name,
                "code": code_in,
                "success": True,
                "reason": "already_full_access",
                "ip": ip,
                "userAgent": user_agent,
                "createdAt": SERVER_TIMESTAMP,
            }
        )
        return {"status": "ok", "result": "already_full_access"}

    # Transaction: validate code, enforce maxUses, store redemption, update counters.
    code_ref = _access_code_ref(code_in)
    redemption_ref = code_ref.collection("redemptions").document(uid)

    transaction = firebase_service.db.transaction()

    @firestore.transactional
    def redeem_txn(transaction):
        code_snap = code_ref.get(transaction=transaction)
        if not code_snap.exists:
            return ("not_found", None)

        data = code_snap.to_dict() or {}
        if bool(data.get("disabled") is True):
            return ("disabled", data)

        max_uses = int(data.get("maxUses") or 1)
        uses = int(data.get("uses") or 0)

        red_snap = redemption_ref.get(transaction=transaction)
        if red_snap.exists:
            transaction.set(
                redemption_ref,
                {
                    "uid": uid,
                    "lastRedeemedAt": SERVER_TIMESTAMP,
                    "lastIp": ip,
                    "lastUserAgent": user_agent,
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )
            transaction.set(
                code_ref,
                {
                    "lastUsedAt": SERVER_TIMESTAMP,
                    "updatedAt": SERVER_TIMESTAMP,
                },
                merge=True,
            )
            return ("already_redeemed", data)

        if uses >= max_uses:
            return ("exhausted", data)

        transaction.set(
            redemption_ref,
            {
                "uid": uid,
                "firstRedeemedAt": SERVER_TIMESTAMP,
                "lastRedeemedAt": SERVER_TIMESTAMP,
                "firstIp": ip,
                "firstUserAgent": user_agent,
                "lastIp": ip,
                "lastUserAgent": user_agent,
                "createdAt": SERVER_TIMESTAMP,
                "updatedAt": SERVER_TIMESTAMP,
            },
            merge=True,
        )
        transaction.set(
            code_ref,
            {
                "uses": uses + 1,
                "lastUsedAt": SERVER_TIMESTAMP,
                "updatedAt": SERVER_TIMESTAMP,
            },
            merge=True,
        )
        return ("redeemed", data)

    outcome, code_data = redeem_txn(transaction)

    # Log attempt (also for failures, but keep user-facing errors non-enumerating).
    _access_code_attempts_col().document().set(
        {
            "uid": uid,
            "email": email,
            "displayName": display_name,
            "code": code_in,
            "success": outcome in {"redeemed", "already_redeemed"},
            "reason": outcome,
            "ip": ip,
            "userAgent": user_agent,
            "createdAt": SERVER_TIMESTAMP,
        }
    )

    if outcome == "not_found":
        raise HTTPException(status_code=400, detail="Ungültiger Code.")
    if outcome in {"disabled", "exhausted"}:
        raise HTTPException(
            status_code=400, detail="Code ungültig oder nicht mehr aktiv."
        )
    if outcome not in {"redeemed", "already_redeemed"}:
        raise HTTPException(
            status_code=500, detail="Code konnte nicht eingelöst werden."
        )

    # Persist user metadata for admin audit.
    try:
        auth_user = auth.get_user(uid)
        user_email = (auth_user.email or "").strip() or None
        user_display = (auth_user.display_name or "").strip() or None
        user_photo = (auth_user.photo_url or "").strip() or None
    except Exception:
        user_email = (decoded_token.get("email") or "").strip() or None
        user_display = None
        user_photo = None

    try:
        redemption_ref.set(
            {
                "email": user_email,
                "displayName": user_display,
                "photoURL": user_photo,
                "updatedAt": SERVER_TIMESTAMP,
            },
            merge=True,
        )
    except Exception:
        pass

    # Update user profile doc (server-side) for later admin inspection.
    try:
        user_ref = firebase_service.db.collection("users").document(uid)
        existing = user_ref.get()
        upsert = {
            "uid": uid,
            "email": user_email,
            "displayName": user_display,
            "photoURL": user_photo,
            "activatedAt": SERVER_TIMESTAMP,
            "activatedByCode": code_in,
            "accountStatus": "active",
            "updatedAt": SERVER_TIMESTAMP,
        }
        if not existing.exists:
            upsert["createdAt"] = SERVER_TIMESTAMP
        user_ref.set(upsert, merge=True)
    except Exception:
        pass

    # Grant access via custom claim (token refresh required client-side).
    try:
        existing_claims = current_claims or {}
        next_claims = {**existing_claims, "fullAccess": True}
        next_claims.pop("approved", None)
        auth.set_custom_user_claims(uid, next_claims)
    except Exception:
        raise HTTPException(
            status_code=500, detail="Aktivierung fehlgeschlagen."
        ) from None

    return {"status": "ok", "result": outcome}


@app.get("/api/admin/users")
async def admin_list_users(
    fullAccess: bool | None = None,
    approved: bool | None = None,
    query: str | None = None,
    page_token: str | None = None,
    max_results: int = 200,
    _: str = Depends(verify_admin_user),
):
    """
    List Firebase Auth users (admin-only).

    This powers the admin user UI: pending users are those with `fullAccess != true`.
    """
    try:
        # Ensure Firebase Admin SDK is initialized.
        _ = firebase_service.db

        max_results = max(1, min(int(max_results or 200), 1000))
        q = (query or "").strip().lower()
        filter_access = fullAccess if fullAccess is not None else approved

        page = auth.list_users(page_token=page_token, max_results=max_results)
        users_out = []
        for user in page.users:
            email = (user.email or "").strip()
            display_name = (user.display_name or "").strip()
            if q and (q not in email.lower()) and (q not in display_name.lower()):
                continue

            claims = user.custom_claims or {}
            has_access = bool(
                claims.get("fullAccess") is True or claims.get("approved") is True
            )
            legacy_approved = bool(claims.get("approved") is True)
            if filter_access is not None and has_access != bool(filter_access):
                continue

            can_duplicate_system_prompts = False
            can_view_usage_insights = False
            blocked = False
            account_status = None
            billing_balance = None
            billing_subscription = None
            try:
                user_doc = await firebase_service.get_user_doc(user.uid)
                can_duplicate_system_prompts = bool(
                    (user_doc or {}).get("canDuplicateSystemPrompts") is True
                )
                can_view_usage_insights = bool(
                    (user_doc or {}).get("canViewUsageInsights") is True
                )
                account_status = (
                    str((user_doc or {}).get("accountStatus") or "").strip().lower()
                    or None
                )
                blocked = account_status == "blocked"
            except Exception:
                can_duplicate_system_prompts = False
                can_view_usage_insights = False
                blocked = False
                account_status = None

            try:
                bal_ref = (
                    firebase_service.db.collection("users")
                    .document(user.uid)
                    .collection("billing")
                    .document("balance")
                )
                bal_snap = bal_ref.get()
                balance_data = bal_snap.to_dict() if bal_snap.exists else {}
                billing_balance = _compute_balance_summary(balance_data)
            except Exception:
                billing_balance = None

            if has_access or blocked:
                try:
                    billing_subscription = await _read_subscription_summary_for_user(user.uid)
                except Exception:
                    billing_subscription = None

            users_out.append(
                {
                    "uid": str(user.uid),
                    "email": email or None,
                    "displayName": display_name or None,
                    "isAdmin": bool(
                        config.ADMIN_UIDS and user.uid in config.ADMIN_UIDS
                    ),
                    # New access state
                    "fullAccess": has_access,
                    "legacyApproved": legacy_approved,
                    "blocked": blocked,
                    "accountStatus": account_status,
                    # Legacy field (kept temporarily for older clients)
                    "approved": has_access,
                    "canDuplicateSystemPrompts": can_duplicate_system_prompts,
                    "canViewUsageInsights": can_view_usage_insights,
                    "disabled": bool(user.disabled),
                    "billingBalance": billing_balance,
                    "billingSubscription": billing_subscription,
                    "createdAt": _ms_to_iso(
                        getattr(user.user_metadata, "creation_timestamp", None)
                    ),
                    "lastSignInAt": _ms_to_iso(
                        getattr(user.user_metadata, "last_sign_in_timestamp", None)
                    ),
                }
            )

        return {"users": users_out, "nextPageToken": page.next_page_token}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list users.") from None


@app.post("/api/admin/users/approve")
async def admin_approve_user(
    payload: AdminApproveUserRequest,
    _: str = Depends(verify_admin_user),
):
    """Legacy endpoint (migration): maps `approved` to `fullAccess`."""
    email = (payload.email or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")

    try:
        result = await firebase_service.set_user_full_access_by_email(
            email=email, full_access=bool(payload.approved)
        )
        return {
            "status": "ok",
            "email": result.get("email"),
            "fullAccess": result.get("fullAccess"),
            "note": "User must refresh token (or re-login) for the claim to take effect.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to update user approval."
        ) from None


@app.post("/api/admin/users/full-access")
async def admin_set_user_full_access(
    payload: AdminSetFullAccessRequest,
    _: str = Depends(verify_admin_user),
):
    """Grant/revoke access by email by setting the Firebase Auth custom claim `fullAccess`."""
    email = (payload.email or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")

    try:
        result = await firebase_service.set_user_full_access_by_email(
            email=email, full_access=bool(payload.fullAccess)
        )
        return {
            "status": "ok",
            "email": result.get("email"),
            "fullAccess": result.get("fullAccess"),
            "note": "User must refresh token (or re-login) for the claim to take effect.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to update user access."
        ) from None


@app.post("/api/admin/users/block")
async def admin_set_user_blocked(
    payload: AdminSetBlockedRequest,
    admin_uid: str = Depends(verify_admin_user),
):
    """Block/unblock a user (hard gate, immediate via Firestore)."""
    email = (payload.email or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")

    try:
        result = await firebase_service.set_user_blocked_by_email(
            email=email,
            blocked=bool(payload.blocked),
            admin_uid=admin_uid,
        )
        return {
            "status": "ok",
            "email": result.get("email"),
            "blocked": result.get("blocked"),
            "note": "Firestore enforcement is immediate; Storage may take up to ~1h (stale token).",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to update user block status."
        ) from None


ACCESS_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _generate_access_code(*, prefix: str = "IP") -> str:
    p = str(prefix or "IP").strip().upper()
    if not p or not p.isalpha() or len(p) != 2:
        p = "IP"
    groups = [
        "".join(secrets.choice(ACCESS_CODE_ALPHABET) for _ in range(4))
        for _ in range(3)
    ]
    return f"{p}-{groups[0]}-{groups[1]}-{groups[2]}"


def _clamp_str(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    txt = str(value).strip()
    if not txt:
        return None
    if len(txt) <= int(max_len):
        return txt
    return txt[: int(max_len)].strip() or None


@app.get("/api/admin/access-codes")
async def admin_list_access_codes(_: str = Depends(verify_admin_user)):
    """List access codes (admin-only)."""
    try:
        docs = list(_access_codes_col().stream())
        out = []
        for snap in docs:
            data = snap.to_dict() or {}
            out.append(
                {
                    "code": snap.id,
                    "name": _clamp_str(data.get("name"), 120) or snap.id,
                    "note": _clamp_str(data.get("note"), 2000),
                    "maxUses": int(data.get("maxUses") or 1),
                    "uses": int(data.get("uses") or 0),
                    "disabled": bool(data.get("disabled") is True),
                    "createdAt": _ts_to_iso(data.get("createdAt")),
                    "lastUsedAt": _ts_to_iso(data.get("lastUsedAt")),
                }
            )
        out.sort(key=lambda c: (c.get("createdAt") or ""), reverse=True)
        return {"codes": out}
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to list access codes."
        ) from None


@app.post("/api/admin/access-codes")
async def admin_create_access_code(
    payload: AdminCreateAccessCodeRequest,
    admin_uid: str = Depends(verify_admin_user),
):
    """Create an access code (admin-only)."""
    name = _clamp_str(payload.name, 80)
    if not name:
        raise HTTPException(status_code=400, detail="name is required.")

    max_uses = int(payload.maxUses or 1)
    if max_uses < 1 or max_uses > 10000:
        raise HTTPException(
            status_code=400, detail="maxUses must be between 1 and 10000."
        )

    note = _clamp_str(payload.note, 500)

    # Try a few times to avoid collisions.
    code = None
    for _ in range(20):
        candidate = _generate_access_code(prefix="IP")
        if not ACCESS_CODE_RE.match(candidate):
            continue
        if not _access_code_ref(candidate).get().exists:
            code = candidate
            break
    if not code:
        raise HTTPException(status_code=500, detail="Failed to generate a unique code.")

    ref = _access_code_ref(code)
    ref.set(
        {
            "name": name,
            "note": note,
            "maxUses": max_uses,
            "uses": 0,
            "disabled": False,
            "createdBy": admin_uid,
            "createdAt": SERVER_TIMESTAMP,
            "updatedAt": SERVER_TIMESTAMP,
            "lastUsedAt": None,
        },
        merge=True,
    )

    return {
        "status": "ok",
        "code": code,
        "name": name,
        "note": note,
        "maxUses": max_uses,
        "uses": 0,
        "disabled": False,
    }


@app.get("/api/admin/access-codes/{code}")
async def admin_get_access_code_detail(code: str, _: str = Depends(verify_admin_user)):
    code_norm = _normalize_access_code(code)
    if not code_norm or not ACCESS_CODE_RE.match(code_norm):
        raise HTTPException(status_code=400, detail="Invalid code.")

    ref = _access_code_ref(code_norm)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Access code not found.")

    data = snap.to_dict() or {}

    redemptions = []
    try:
        q = (
            ref.collection("redemptions")
            .order_by("firstRedeemedAt", direction=firestore.Query.DESCENDING)
            .limit(200)
        )
        for rsnap in q.stream():
            r = rsnap.to_dict() or {}
            redemptions.append(
                {
                    "uid": r.get("uid") or rsnap.id,
                    "email": r.get("email") or None,
                    "displayName": r.get("displayName") or None,
                    "photoURL": r.get("photoURL") or None,
                    "firstRedeemedAt": _ts_to_iso(r.get("firstRedeemedAt")),
                    "lastRedeemedAt": _ts_to_iso(r.get("lastRedeemedAt")),
                    "firstIp": r.get("firstIp") or None,
                    "lastIp": r.get("lastIp") or None,
                    "firstUserAgent": _truncate_header(r.get("firstUserAgent"), 400),
                    "lastUserAgent": _truncate_header(r.get("lastUserAgent"), 400),
                }
            )
    except Exception:
        redemptions = []

    attempts = []
    try:
        q = (
            _access_code_attempts_col()
            .where("code", "==", code_norm)
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .limit(200)
        )
        for asnap in q.stream():
            a = asnap.to_dict() or {}
            attempts.append(
                {
                    "id": asnap.id,
                    "uid": a.get("uid") or None,
                    "email": a.get("email") or None,
                    "displayName": a.get("displayName") or None,
                    "success": bool(a.get("success") is True),
                    "reason": a.get("reason") or None,
                    "ip": a.get("ip") or None,
                    "userAgent": _truncate_header(a.get("userAgent"), 400),
                    "createdAt": _ts_to_iso(a.get("createdAt")),
                }
            )
    except Exception:
        attempts = []

    return {
        "code": {
            "code": code_norm,
            "name": _clamp_str(data.get("name"), 120) or code_norm,
            "note": _clamp_str(data.get("note"), 2000),
            "maxUses": int(data.get("maxUses") or 1),
            "uses": int(data.get("uses") or 0),
            "disabled": bool(data.get("disabled") is True),
            "createdAt": _ts_to_iso(data.get("createdAt")),
            "lastUsedAt": _ts_to_iso(data.get("lastUsedAt")),
        },
        "redemptions": redemptions,
        "attempts": attempts,
    }


@app.patch("/api/admin/access-codes/{code}")
async def admin_update_access_code(
    code: str,
    payload: AdminUpdateAccessCodeRequest,
    admin_uid: str = Depends(verify_admin_user),
):
    code_norm = _normalize_access_code(code)
    if not code_norm or not ACCESS_CODE_RE.match(code_norm):
        raise HTTPException(status_code=400, detail="Invalid code.")

    ref = _access_code_ref(code_norm)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Access code not found.")

    update: dict = {"updatedAt": SERVER_TIMESTAMP, "updatedBy": admin_uid}
    if payload.disabled is not None:
        update["disabled"] = bool(payload.disabled)
    if payload.maxUses is not None:
        max_uses = int(payload.maxUses)
        if max_uses < 1 or max_uses > 10000:
            raise HTTPException(
                status_code=400, detail="maxUses must be between 1 and 10000."
            )
        update["maxUses"] = max_uses
    if payload.name is not None:
        name = _clamp_str(payload.name, 80)
        if not name:
            raise HTTPException(status_code=400, detail="name must not be empty.")
        update["name"] = name
    if payload.note is not None:
        update["note"] = _clamp_str(payload.note, 500)

    ref.set(update, merge=True)
    return {"status": "ok"}


@app.delete("/api/admin/access-codes/{code}")
async def admin_delete_access_code(code: str, _: str = Depends(verify_admin_user)):
    code_norm = _normalize_access_code(code)
    if not code_norm or not ACCESS_CODE_RE.match(code_norm):
        raise HTTPException(status_code=400, detail="Invalid code.")

    ref = _access_code_ref(code_norm)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Access code not found.")

    try:
        ref.delete()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to delete access code.") from None

    return {"status": "ok"}


@app.post("/api/admin/users/system-prompt-copy")
async def admin_set_system_prompt_export(
    payload: AdminSetSystemPromptExportRequest,
    _: str = Depends(verify_admin_user),
):
    """Allow or block a user from duplicating server-only system prompts into their own prompt library."""
    email = (payload.email or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")

    try:
        result = await firebase_service.set_user_can_duplicate_system_prompts_by_email(
            email=email,
            allowed=bool(payload.canDuplicateSystemPrompts),
        )
        return {
            "status": "ok",
            "email": result.get("email"),
            "canDuplicateSystemPrompts": result.get("canDuplicateSystemPrompts"),
            "note": "Takes effect immediately for system prompt duplication (user may need to refresh the page).",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to update system prompt copy permission."
        ) from None


@app.post("/api/admin/users/usage-insights")
async def admin_set_usage_insights(
    payload: AdminSetUsageInsightsRequest,
    _: str = Depends(verify_admin_user),
):
    """Allow or block a user from seeing usage insights (dashboard + profile statistics)."""
    email = (payload.email or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")

    try:
        result = await firebase_service.set_user_can_view_usage_insights_by_email(
            email=email,
            allowed=bool(payload.canViewUsageInsights),
        )
        return {
            "status": "ok",
            "email": result.get("email"),
            "canViewUsageInsights": result.get("canViewUsageInsights"),
            "note": "Takes effect immediately (user may need to refresh the page).",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to update usage insights permission."
        ) from None


def _validate_prompt_stage(stage: str) -> str:
    stage_norm = (stage or "").strip()
    if stage_norm not in ALLOWED_PROMPT_STAGES:
        raise HTTPException(status_code=400, detail=f"Invalid stage: {stage_norm}")
    return stage_norm


def _validate_template_key(key: str) -> str:
    key_norm = (key or "").strip()
    if not key_norm or not TEMPLATE_KEY_RE.match(key_norm):
        raise HTTPException(
            status_code=400,
            detail="Invalid templateKey. Use letters/numbers plus '-'/'_' (max 64 chars).",
        )
    return key_norm


def _validate_required_placeholders(stage: str, instructions: str) -> None:
    required = list(prompt_service.REQUIRED_PLACEHOLDERS.get(stage, []) or [])
    if not required:
        return
    missing = [ph for ph in required if ph not in (instructions or "")]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required placeholders: {', '.join(missing)}",
        )


_ADMIN_MIN_PROMPT_NAME_LEN = 3
_ADMIN_MAX_PROMPT_NAME_LEN = 80
_ADMIN_MAX_TEMPLATES_PER_STAGE = 10


def _validate_user_prompt_name(name: str) -> str:
    n = str(name or "").strip()
    if len(n) < _ADMIN_MIN_PROMPT_NAME_LEN or len(n) > _ADMIN_MAX_PROMPT_NAME_LEN:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Name muss zwischen {_ADMIN_MIN_PROMPT_NAME_LEN} und {_ADMIN_MAX_PROMPT_NAME_LEN} Zeichen lang sein."
            ),
        )
    return n


def _require_non_empty_instructions(instructions: str) -> str:
    ins = str(instructions or "").strip()
    if not ins:
        raise HTTPException(
            status_code=400, detail="Instructions dürfen nicht leer sein."
        )
    return ins


def _prompt_templates_col(user_id: str):
    return (
        firebase_service.db.collection("users")
        .document(user_id)
        .collection("promptTemplates")
    )


def _prompt_settings_ref(user_id: str):
    return (
        firebase_service.db.collection("users")
        .document(user_id)
        .collection("promptSettings")
        .document("active")
    )


@app.get("/api/admin/users/{uid}")
async def admin_get_user_detail(
    uid: str,
    _: str = Depends(verify_admin_user),
):
    """Get a single user's account + settings summary (admin-only)."""
    uid_norm = (uid or "").strip()
    if not uid_norm:
        raise HTTPException(status_code=400, detail="uid is required.")

    try:
        user = auth.get_user(uid_norm)
    except auth.UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="User not found.") from exc
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to load user.") from None

    claims = user.custom_claims or {}
    full_access = bool(
        claims.get("fullAccess") is True or claims.get("approved") is True
    )
    legacy_approved = bool(claims.get("approved") is True)
    blocked_claim = bool(claims.get("blocked") is True)

    can_duplicate_system_prompts = False
    can_view_usage_insights = False
    account_status = None
    blocked = False
    activated_by_code = None
    activated_at = None
    spend_rate_override = None
    try:
        user_doc = await firebase_service.get_user_doc(user.uid)
        can_duplicate_system_prompts = bool(
            (user_doc or {}).get("canDuplicateSystemPrompts") is True
        )
        can_view_usage_insights = bool(
            (user_doc or {}).get("canViewUsageInsights") is True
        )
        account_status = (
            str((user_doc or {}).get("accountStatus") or "").strip().lower() or None
        )
        blocked = account_status == "blocked"
        activated_by_code = (user_doc or {}).get("activatedByCode") or None
        activated_at = _ts_to_iso((user_doc or {}).get("activatedAt"))
        spend_rate_raw = _as_float((user_doc or {}).get("spendRate"), 0.0)
        if spend_rate_raw and spend_rate_raw > 0:
            spend_rate_override = float(spend_rate_raw)
    except Exception:
        can_duplicate_system_prompts = False
        can_view_usage_insights = False
        account_status = None
        blocked = False
        activated_by_code = None
        activated_at = None
        spend_rate_override = None

    try:
        cfg = await get_credits_service(firebase_service).get_config()
        default_rate = float(cfg.default_spend_rate or 0.0)
        if default_rate <= 0:
            default_rate = 6.0
        effective_spend_rate = (
            float(spend_rate_override)
            if spend_rate_override is not None
            else float(default_rate)
        )
    except Exception:
        effective_spend_rate = (
            float(spend_rate_override) if spend_rate_override is not None else 6.0
        )

    try:
        bal_ref = (
            firebase_service.db.collection("users")
            .document(user.uid)
            .collection("billing")
            .document("balance")
        )
        bal_snap = bal_ref.get()
        balance_data = bal_snap.to_dict() if bal_snap.exists else {}
    except Exception:
        balance_data = {}

    billing_balance = _compute_balance_summary(balance_data)

    try:
        billing_subscription = await _read_subscription_summary_for_user(user.uid)
    except Exception:
        billing_subscription = None

    return {
        "user": {
            "uid": str(user.uid),
            "email": (user.email or "").strip() or None,
            "displayName": (user.display_name or "").strip() or None,
            "isAdmin": bool(config.ADMIN_UIDS and user.uid in config.ADMIN_UIDS),
            "fullAccess": full_access,
            "legacyApproved": legacy_approved,
            "blocked": blocked or blocked_claim,
            "accountStatus": account_status,
            "disabled": bool(user.disabled),
            "canDuplicateSystemPrompts": can_duplicate_system_prompts,
            "canViewUsageInsights": can_view_usage_insights,
            "spendRate": spend_rate_override,
            "effectiveSpendRate": float(effective_spend_rate),
            "activatedByCode": activated_by_code,
            "activatedAt": activated_at,
            "createdAt": _ms_to_iso(
                getattr(user.user_metadata, "creation_timestamp", None)
            ),
            "lastSignInAt": _ms_to_iso(
                getattr(user.user_metadata, "last_sign_in_timestamp", None)
            ),
        },
        "billing": {
            "balance": billing_balance,
            "subscription": billing_subscription,
        },
    }


@app.post("/api/admin/users/{uid}/spend-rate")
async def admin_set_user_spend_rate(
    uid: str,
    payload: AdminSetSpendRateRequest,
    admin_uid: str = Depends(verify_admin_user),
):
    """Set per-user spend rate override (`users/{uid}.spendRate`)."""
    uid_norm = (uid or "").strip()
    if not uid_norm:
        raise HTTPException(status_code=400, detail="uid is required.")

    try:
        auth.get_user(uid_norm)
    except auth.UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="User not found.") from exc
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to load user.") from None

    spend_rate_override = None
    spend_rate = payload.spendRate
    if spend_rate is not None:
        try:
            n = float(spend_rate)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid spendRate.") from None
        if n and n > 0:
            spend_rate_override = float(n)

    user_ref = firebase_service.db.collection("users").document(uid_norm)
    update: dict = {
        "updatedAt": SERVER_TIMESTAMP,
        "spendRateUpdatedAt": SERVER_TIMESTAMP,
        "spendRateUpdatedBy": str(admin_uid),
    }
    if spend_rate_override is None:
        update["spendRate"] = firestore.DELETE_FIELD
    else:
        update["spendRate"] = float(spend_rate_override)

    user_ref.set(update, merge=True)

    try:
        cfg = await get_credits_service(firebase_service).get_config()
        default_rate = float(cfg.default_spend_rate or 0.0)
        if default_rate <= 0:
            default_rate = 6.0
    except Exception:
        default_rate = 6.0

    effective = (
        float(spend_rate_override)
        if spend_rate_override is not None
        else float(default_rate)
    )
    return {
        "status": "ok",
        "uid": uid_norm,
        "spendRate": spend_rate_override,
        "effectiveSpendRate": float(effective),
    }


@app.get("/api/admin/users/{uid}/openai/operations")
async def admin_get_user_openai_operations(
    uid: str,
    limit: int = 50,
    cursor: str | None = None,
    status: str | None = None,
    _: str = Depends(verify_admin_user),
):
    """Return OpenAI operations for a user (paginated, newest first; admin-only)."""
    uid_norm = (uid or "").strip()
    if not uid_norm:
        raise HTTPException(status_code=400, detail="uid is required.")

    limit = max(1, min(int(limit or 50), 200))
    status_norm = str(status or "").strip().lower() or None

    ops_ref = (
        firebase_service.db.collection("users")
        .document(uid_norm)
        .collection("costMetrics")
        .document("v1")
        .collection("operations")
    )
    base = ops_ref.order_by("timestamp", direction=firestore.Query.DESCENDING)
    if status_norm:
        base = base.where("status", "==", status_norm)

    if cursor:
        try:
            cursor_snap = ops_ref.document(str(cursor)).get()
            if cursor_snap.exists:
                base = base.start_after(cursor_snap)
        except Exception:
            pass

    docs = list(base.limit(limit).stream())
    out = []
    for snap in docs:
        data = snap.to_dict() or {}
        estimate = _as_record(data.get("estimate"))
        costs = _as_record(data.get("costs"))
        reservation = _as_record(data.get("reservation"))

        actual_credits = None
        if estimate and costs:
            try:
                spend_rate = float(estimate.get("spendRate") or 0.0)
                cost_usd = float(costs.get("totalCostUsd") or 0.0)
                if spend_rate > 0 and cost_usd > 0:
                    actual_credits = float(cost_usd * spend_rate)
            except Exception:
                actual_credits = None

        reservation_out = None
        if reservation:
            reservation_out = dict(reservation)
            reservation_out["reservedAt"] = _ts_to_iso(reservation.get("reservedAt"))
            reservation_out["releasedAt"] = _ts_to_iso(reservation.get("releasedAt"))

        out.append(
            {
                "id": snap.id,
                "operationId": str(data.get("operationId") or snap.id),
                "timestamp": _ts_to_iso(data.get("timestamp")),
                "runningAt": _ts_to_iso(data.get("runningAt")),
                "status": str(data.get("status") or ""),
                "errorMessage": str(data.get("errorMessage") or "") or None,
                "operationType": str(data.get("operationType") or ""),
                "operationDetails": data.get("operationDetails"),
                "userActionId": str(data.get("userActionId") or "") or None,
                "model": str(data.get("modelNormalized") or data.get("model") or "")
                or None,
                "keySource": str(data.get("keySource") or "") or None,
                "projektId": str(data.get("projektId") or "") or None,
                "kapitelId": str(data.get("kapitelId") or "") or None,
                "runId": str(data.get("runId") or "") or None,
                "quelleId": str(data.get("quelleId") or "") or None,
                "tokens": _as_record(data.get("tokens")),
                "costs": costs,
                "estimate": estimate,
                "reservation": reservation_out,
                "actualCredits": actual_credits,
            }
        )

    next_cursor = docs[-1].id if len(docs) == limit else None
    return {"operations": out, "nextCursor": next_cursor}


@app.get("/api/admin/users/{uid}/billing/ledger")
async def admin_get_user_credit_ledger(
    uid: str,
    limit: int = 50,
    cursor: str | None = None,
    includeUsage: bool = True,
    _: str = Depends(verify_admin_user),
):
    """Return credit ledger entries for a user (paginated, newest first; admin-only)."""
    uid_norm = (uid or "").strip()
    if not uid_norm:
        raise HTTPException(status_code=400, detail="uid is required.")

    limit = max(1, min(int(limit or 50), 200))

    base = (
        firebase_service.db.collection("users")
        .document(uid_norm)
        .collection("creditLedger")
        .order_by("createdAt", direction=firestore.Query.DESCENDING)
    )

    if cursor:
        try:
            cursor_snap = (
                firebase_service.db.collection("users")
                .document(uid_norm)
                .collection("creditLedger")
                .document(str(cursor))
                .get()
            )
            if cursor_snap.exists:
                base = base.start_after(cursor_snap)
        except Exception:
            pass

    include_usage = bool(includeUsage)

    out = []
    last_processed_id = None

    if include_usage:
        docs = list(base.limit(limit).stream())
        for snap in docs:
            data = snap.to_dict() or {}
            out.append(
                {
                    "id": snap.id,
                    "type": str(data.get("type") or ""),
                    "source": str(data.get("source") or ""),
                    "credits": _as_float(data.get("credits"), 0.0),
                    "createdAt": _ts_to_iso(data.get("createdAt")),
                    "expiresAt": _ts_to_iso(data.get("expiresAt")),
                    "note": str(data.get("note") or "") or None,
                }
            )
        next_cursor = docs[-1].id if len(docs) == limit else None
        return {"entries": out, "nextCursor": next_cursor}

    # Non-usage view: filter out OpenAI debits (source=openai).
    batch_size = max(50, min(200, limit * 6))
    has_more_docs = True

    while len(out) < limit and has_more_docs:
        docs = list(base.limit(batch_size).stream())
        if not docs:
            has_more_docs = False
            break

        for snap in docs:
            last_processed_id = snap.id
            data = snap.to_dict() or {}
            source = str(data.get("source") or "")
            if source == "openai":
                continue
            out.append(
                {
                    "id": snap.id,
                    "type": str(data.get("type") or ""),
                    "source": source,
                    "credits": _as_float(data.get("credits"), 0.0),
                    "createdAt": _ts_to_iso(data.get("createdAt")),
                    "expiresAt": _ts_to_iso(data.get("expiresAt")),
                    "note": str(data.get("note") or "") or None,
                }
            )
            if len(out) >= limit:
                break

        if len(out) >= limit:
            # We can continue from the last processed document to pick up further non-usage entries.
            has_more_docs = True
            break

        if len(docs) < batch_size:
            has_more_docs = False
            break

        # Continue scanning after the last document in this batch.
        try:
            base = base.start_after(docs[-1])
        except Exception:
            has_more_docs = False
            break

    next_cursor = last_processed_id if (last_processed_id and has_more_docs) else None
    return {"entries": out, "nextCursor": next_cursor}


@app.post("/api/admin/users/{uid}/billing/reserved-credits")
async def admin_adjust_reserved_credits(
    uid: str,
    payload: AdminAdjustReservedCreditsRequest,
    admin_uid: str = Depends(verify_admin_user),
):
    """Set or delta-adjust a user's reservedCredits (admin-only)."""
    uid_norm = (uid or "").strip()
    if not uid_norm:
        raise HTTPException(status_code=400, detail="uid is required.")

    mode = str(payload.mode or "").strip().lower()
    if mode not in {"set", "delta"}:
        raise HTTPException(status_code=400, detail="mode must be 'set' or 'delta'.")

    try:
        amount = float(payload.amount)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid amount.") from None

    note = _clamp_str(payload.note, 500)

    balance_ref = (
        firebase_service.db.collection("users")
        .document(uid_norm)
        .collection("billing")
        .document("balance")
    )
    audit_id = f"reserved_adj_{secrets.token_hex(12)}"
    audit_ref = (
        firebase_service.db.collection("users")
        .document(uid_norm)
        .collection("billing")
        .document("audit")
        .collection("reservedCredits")
        .document(audit_id)
    )

    transaction = firebase_service.db.transaction()

    @firestore.transactional
    def txn(transaction):
        bal_snap = balance_ref.get(transaction=transaction)
        bal = bal_snap.to_dict() if bal_snap.exists else {}

        prev_reserved = _as_float(bal.get("reservedCredits"), 0.0)
        if mode == "set":
            next_reserved = float(max(0.0, float(amount)))
        else:
            next_reserved = float(max(0.0, float(prev_reserved) + float(amount)))

        transaction.set(
            balance_ref,
            {
                "reservedCredits": float(next_reserved),
                "updatedAt": SERVER_TIMESTAMP,
            },
            merge=True,
        )

        transaction.set(
            audit_ref,
            {
                "id": audit_id,
                "userId": uid_norm,
                "adminUid": str(admin_uid),
                "mode": mode,
                "amount": float(amount),
                "previousReservedCredits": float(prev_reserved),
                "newReservedCredits": float(next_reserved),
                "note": note,
                "createdAt": SERVER_TIMESTAMP,
            },
            merge=True,
        )

        return float(prev_reserved), float(next_reserved)

    prev, new = txn(transaction)
    return {
        "status": "ok",
        "uid": uid_norm,
        "mode": mode,
        "amount": float(amount),
        "previousReservedCredits": float(prev),
        "reservedCredits": float(new),
        "deltaApplied": float(new - prev),
        "auditId": audit_id,
    }


@app.post("/api/admin/users/{uid}/billing/adjustments")
async def admin_create_credit_adjustment(
    uid: str,
    payload: AdminCreateCreditAdjustmentRequest,
    admin_uid: str = Depends(verify_admin_user),
):
    """Create a manual +/- credit adjustment for a user (admin-only)."""
    uid_norm = (uid or "").strip()
    if not uid_norm:
        raise HTTPException(status_code=400, detail="uid is required.")

    try:
        credits = float(payload.credits)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid credits.") from None

    if not credits:
        raise HTTPException(status_code=400, detail="credits must be non-zero.")

    note = _clamp_str(payload.note, 500)

    ledger_id = f"admin_adj_{secrets.token_hex(12)}"
    ledger_ref = (
        firebase_service.db.collection("users")
        .document(uid_norm)
        .collection("creditLedger")
        .document(ledger_id)
    )
    balance_ref = (
        firebase_service.db.collection("users")
        .document(uid_norm)
        .collection("billing")
        .document("balance")
    )

    transaction = firebase_service.db.transaction()

    @firestore.transactional
    def txn(transaction):
        bal_snap = balance_ref.get(transaction=transaction)
        bal = bal_snap.to_dict() if bal_snap.exists else {}

        topup_raw = _as_float(bal.get("topupCredits"), 0.0)
        new_topup = float(topup_raw + float(credits))

        transaction.set(
            balance_ref,
            {
                "topupCredits": float(new_topup),
                "updatedAt": SERVER_TIMESTAMP,
            },
            merge=True,
        )

        transaction.set(
            ledger_ref,
            {
                "type": "credit" if credits > 0 else "debit",
                "source": "admin_adjustment",
                "credits": float(credits),
                "note": note,
                "createdAt": SERVER_TIMESTAMP,
                "expiresAt": None,
                "admin": {"uid": str(admin_uid)},
            },
        )

    try:
        txn(transaction)
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to write adjustment."
        ) from None

    try:
        bal_post = balance_ref.get()
        balance_data = bal_post.to_dict() if bal_post.exists else {}
    except Exception:
        balance_data = {}

    return {
        "status": "ok",
        "id": ledger_id,
        "credits": float(credits),
        "note": note,
        "balance": _compute_balance_summary(balance_data),
    }


@app.get("/api/admin/users/{uid}/prompt-templates")
async def admin_list_user_prompt_templates(
    uid: str,
    _: str = Depends(verify_admin_user),
):
    """List user-owned prompt templates + active selection (admin-only)."""
    uid_norm = (uid or "").strip()
    if not uid_norm:
        raise HTTPException(status_code=400, detail="uid is required.")

    try:
        templates_ref = _prompt_templates_col(uid_norm)
        docs = list(templates_ref.stream())
        templates_out = []
        for doc_snap in docs:
            data = doc_snap.to_dict() or {}
            stage = str(data.get("stage") or "").strip()
            if stage not in ALLOWED_PROMPT_STAGES:
                continue
            templates_out.append(
                {
                    "id": doc_snap.id,
                    "stage": stage,
                    "name": str((data.get("name") or "")).strip() or doc_snap.id,
                    "instructions": str((data.get("instructions") or "")).rstrip(),
                    "placeholders": list(data.get("placeholders") or [])
                    or list(prompt_service.REQUIRED_PLACEHOLDERS.get(stage, []) or []),
                    "createdAt": _ts_to_iso(data.get("createdAt")),
                    "updatedAt": _ts_to_iso(data.get("updatedAt")),
                }
            )

        templates_out.sort(
            key=lambda t: (
                t.get("stage") or "",
                t.get("updatedAt") or t.get("createdAt") or "",
            ),
            reverse=True,
        )

        settings_doc = _prompt_settings_ref(uid_norm).get()
        settings = settings_doc.to_dict() if settings_doc.exists else {}
        active = (
            settings.get("activeTemplates", {}) if isinstance(settings, dict) else {}
        )
        ask_on_each = (
            bool(settings.get("askOnEachProcess"))
            if isinstance(settings, dict)
            else False
        )

        return {
            "templates": templates_out,
            "active": active or {},
            "askOnEachProcess": ask_on_each,
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to list prompt templates."
        ) from None


@app.post("/api/admin/users/{uid}/prompt-templates")
async def admin_create_user_prompt_template(
    uid: str,
    payload: AdminCreateUserPromptTemplateRequest,
    _: str = Depends(verify_admin_user),
):
    """Create a user-owned prompt template (admin-only)."""
    uid_norm = (uid or "").strip()
    if not uid_norm:
        raise HTTPException(status_code=400, detail="uid is required.")

    stage_norm = _validate_prompt_stage(payload.stage)
    name = _validate_user_prompt_name(payload.name)
    instructions = _require_non_empty_instructions(payload.instructions)
    _validate_required_placeholders(stage_norm, instructions)

    try:
        templates_ref = _prompt_templates_col(uid_norm)
        existing = list(templates_ref.where("stage", "==", stage_norm).stream())
        if len(existing) >= _ADMIN_MAX_TEMPLATES_PER_STAGE:
            raise HTTPException(
                status_code=400,
                detail=f"Maximal {_ADMIN_MAX_TEMPLATES_PER_STAGE} Prompts für diese Stage erlaubt.",
            )

        doc_ref = templates_ref.document()
        doc_ref.set(
            {
                "stage": stage_norm,
                "name": name,
                "instructions": instructions,
                "placeholders": list(
                    prompt_service.REQUIRED_PLACEHOLDERS.get(stage_norm, []) or []
                ),
                "createdAt": SERVER_TIMESTAMP,
                "updatedAt": SERVER_TIMESTAMP,
            }
        )
        return {"status": "ok", "id": doc_ref.id}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to create prompt template."
        ) from None


@app.put("/api/admin/users/{uid}/prompt-templates/{template_id}")
async def admin_update_user_prompt_template(
    uid: str,
    template_id: str,
    payload: AdminUpdateUserPromptTemplateRequest,
    _: str = Depends(verify_admin_user),
):
    """Update a user-owned prompt template (admin-only)."""
    uid_norm = (uid or "").strip()
    tpl_id = (template_id or "").strip()
    if not uid_norm or not tpl_id:
        raise HTTPException(status_code=400, detail="uid and template_id are required.")

    name = _validate_user_prompt_name(payload.name)
    instructions = _require_non_empty_instructions(payload.instructions)

    try:
        tpl_ref = _prompt_templates_col(uid_norm).document(tpl_id)
        snap = tpl_ref.get()
        if not snap.exists:
            raise HTTPException(status_code=404, detail="Template nicht gefunden.")

        data = snap.to_dict() or {}
        stage = str(data.get("stage") or "").strip()
        stage_norm = _validate_prompt_stage(stage)
        _validate_required_placeholders(stage_norm, instructions)

        tpl_ref.set(
            {
                "name": name,
                "instructions": instructions,
                "placeholders": list(
                    prompt_service.REQUIRED_PLACEHOLDERS.get(stage_norm, []) or []
                ),
                "updatedAt": SERVER_TIMESTAMP,
            },
            merge=True,
        )
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to update prompt template."
        ) from None


@app.delete("/api/admin/users/{uid}/prompt-templates/{template_id}")
async def admin_delete_user_prompt_template(
    uid: str,
    template_id: str,
    _: str = Depends(verify_admin_user),
):
    """Delete a user-owned prompt template (admin-only)."""
    uid_norm = (uid or "").strip()
    tpl_id = (template_id or "").strip()
    if not uid_norm or not tpl_id:
        raise HTTPException(status_code=400, detail="uid and template_id are required.")

    try:
        tpl_ref = _prompt_templates_col(uid_norm).document(tpl_id)
        snap = tpl_ref.get()
        if not snap.exists:
            return {"status": "ok"}

        data = snap.to_dict() or {}
        stage = str(data.get("stage") or "").strip()
        stage_norm = _validate_prompt_stage(stage)

        settings_ref = _prompt_settings_ref(uid_norm)
        settings_snap = settings_ref.get()
        if settings_snap.exists:
            settings = settings_snap.to_dict() or {}
            active = settings.get("activeTemplates", {}) or {}
            if isinstance(active, dict) and active.get(stage_norm) == tpl_id:
                active_next = {**active, stage_norm: "default_v2"}
                settings_ref.set(
                    {"activeTemplates": active_next, "updatedAt": SERVER_TIMESTAMP},
                    merge=True,
                )

        tpl_ref.delete()
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to delete prompt template."
        ) from None


@app.post("/api/admin/users/{uid}/prompt-templates/active")
async def admin_set_user_active_prompt(
    uid: str,
    payload: AdminSetActiveUserPromptRequest,
    _: str = Depends(verify_admin_user),
):
    """Set active prompt template (user template id or system templateKey) for a stage (admin-only)."""
    uid_norm = (uid or "").strip()
    if not uid_norm:
        raise HTTPException(status_code=400, detail="uid is required.")

    stage_norm = _validate_prompt_stage(payload.stage)
    template_id = str(payload.templateId or "").strip()
    if not template_id:
        raise HTTPException(status_code=400, detail="templateId is required.")

    try:
        tpl_ref = _prompt_templates_col(uid_norm).document(template_id)
        tpl_snap = tpl_ref.get()
        if tpl_snap.exists:
            data = tpl_snap.to_dict() or {}
            tpl_stage = str(data.get("stage") or "").strip()
            if tpl_stage != stage_norm:
                raise HTTPException(status_code=400, detail="Template stage mismatch.")
        else:
            if template_id not in SYSTEM_TEMPLATE_KEYS_ALWAYS_AVAILABLE:
                key_norm = _validate_template_key(template_id)
                sys_tpl = await firebase_service.get_system_prompt_template(
                    stage_norm, key_norm
                )
                if not sys_tpl:
                    raise HTTPException(
                        status_code=404, detail="System prompt template not found."
                    )
                if bool(sys_tpl.get("published", True) is not True) or bool(
                    sys_tpl.get("archived", False) is True
                ):
                    raise HTTPException(
                        status_code=404, detail="System prompt template not available."
                    )

        settings_ref = _prompt_settings_ref(uid_norm)
        settings_snap = settings_ref.get()
        current = settings_snap.to_dict() if settings_snap.exists else {}
        active = current.get("activeTemplates", {}) if isinstance(current, dict) else {}
        if not isinstance(active, dict):
            active = {}

        active_next = {**active, stage_norm: template_id}
        payload_out: dict = {
            "activeTemplates": active_next,
            "updatedAt": SERVER_TIMESTAMP,
        }
        if not settings_snap.exists:
            payload_out["createdAt"] = SERVER_TIMESTAMP
        settings_ref.set(payload_out, merge=True)

        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to set active prompt."
        ) from None


_GERMAN_MONTHS = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]


def _cents_from_usd(value) -> int:
    try:
        num = float(value or 0)
    except Exception:
        return 0
    if num != num:
        return 0
    return int(round(num * 100))


def _as_record(value) -> dict:
    return value if isinstance(value, dict) else {}


def _display_model_key(key: str) -> str:
    return (key or "").replace("_", ".")


def _month_key(dt: datetime) -> str:
    return f"{dt.year:04d}-{dt.month:02d}"


def _add_months(dt: datetime, delta: int) -> datetime:
    year = int(dt.year)
    month = int(dt.month) + int(delta)
    while month <= 0:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def _month_label_de(month: int) -> str:
    try:
        return _GERMAN_MONTHS[int(month) - 1]
    except Exception:
        return str(month)


def _parse_iso_dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    raw = str(iso).strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _first_created_at_iso(db, uid: str, col_name: str) -> str | None:
    try:
        col_ref = db.collection("users").document(uid).collection(col_name)
        docs = (
            col_ref.order_by("createdAt", direction=firestore.Query.ASCENDING)
            .limit(1)
            .stream()
        )
        first = next(docs, None)
        if not first:
            return None
        data = first.to_dict() or {}
        return _ts_to_iso(data.get("createdAt"))
    except Exception:
        return None


def _get_member_since_iso(db, uid: str) -> str:
    candidates: list[str] = []

    try:
        user_snap = db.collection("users").document(uid).get()
        if user_snap.exists:
            iso = _ts_to_iso((user_snap.to_dict() or {}).get("createdAt"))
            if iso:
                candidates.append(iso)
    except Exception:
        pass

    for col in ("projects", "kapitels", "quellen"):
        iso = _first_created_at_iso(db, uid, col)
        if iso:
            candidates.append(iso)

    parsed = [d for d in (_parse_iso_dt(x) for x in candidates) if d is not None]
    parsed.sort(key=lambda d: d.timestamp())
    return (
        (parsed[0] if parsed else datetime.now(timezone.utc))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _scan_operations_for_backfill(
    db, uid: str, max_docs: int = 5000
) -> tuple[int, dict[str, int]]:
    output_tokens = 0
    model_counts: dict[str, int] = {}

    fetched = 0
    cursor = None
    base = (
        db.collection("users")
        .document(uid)
        .collection("costMetrics")
        .document("v1")
        .collection("operations")
    )

    while fetched < int(max_docs or 0):
        q = base.order_by("timestamp", direction=firestore.Query.DESCENDING).limit(500)
        if cursor is not None:
            q = q.start_after(cursor)
        docs = list(q.stream())
        if not docs:
            break

        for doc_snap in docs:
            data = doc_snap.to_dict() or {}
            tokens = _as_record(data.get("tokens"))
            out = tokens.get("outputTokens", 0)
            try:
                out_i = int(out or 0)
            except Exception:
                out_i = 0
            if out_i > 0:
                output_tokens += out_i

            model_raw = (
                data.get("modelNormalized")
                or data.get("model")
                or data.get("modelKey")
                or "unknown"
            )
            model = _display_model_key(str(model_raw or "unknown"))
            model_counts[model] = int(model_counts.get(model, 0)) + 1

        fetched += len(docs)
        cursor = docs[-1]
        if len(docs) < 500:
            break

    return output_tokens, model_counts


def _safe_count_collection(db, uid: str, col: str) -> int:
    try:
        return len(list(db.collection("users").document(uid).collection(col).stream()))
    except Exception:
        return 0


@app.get("/api/admin/users/{uid}/stats")
async def admin_get_user_stats(
    uid: str,
    operations_limit: int = 25,
    _: str = Depends(verify_admin_user),
):
    """Get live stats + recent operations for a user (admin-only, read-only)."""
    uid_norm = (uid or "").strip()
    if not uid_norm:
        raise HTTPException(status_code=400, detail="uid is required.")

    try:
        db = firebase_service.db

        total_projekte = _safe_count_collection(db, uid_norm, "projects")
        total_kapitel = _safe_count_collection(db, uid_norm, "kapitels")
        total_quellen = _safe_count_collection(db, uid_norm, "quellen")

        agg_ref = (
            db.collection("users")
            .document(uid_norm)
            .collection("costMetrics")
            .document("v1")
            .collection("aggregatesByUser")
            .document("lifetime")
        )
        agg_snap = agg_ref.get()
        agg = _as_record(agg_snap.to_dict() if agg_snap.exists else {})

        total_cost = _cents_from_usd(agg.get("totalCostUsd"))
        total_runs_raw = agg.get("operationCount", 0)
        try:
            total_runs = int(total_runs_raw or 0)
        except Exception:
            total_runs = 0

        by_op = _as_record(agg.get("byOperationType"))
        export_agg = _as_record(by_op.get("export_docx"))
        export_cost = _cents_from_usd(export_agg.get("totalCostUsd"))
        try:
            export_count = int(export_agg.get("count", 0) or 0)
        except Exception:
            export_count = 0

        by_time = _as_record(agg.get("byTimePeriod"))
        now = datetime.now(timezone.utc)
        runs_by_month = []
        for idx in range(6):
            dt = _add_months(now, -(5 - idx))
            key = _month_key(dt)
            entry = _as_record(by_time.get(key))
            try:
                runs = int(entry.get("count", 0) or 0)
            except Exception:
                runs = 0
            runs_by_month.append(
                {
                    "month": _month_label_de(dt.month),
                    "runs": runs,
                    "cost": _cents_from_usd(entry.get("totalCostUsd")),
                    "key": key,
                }
            )

        projects_ref = db.collection("users").document(uid_norm).collection("projects")
        projects = list(projects_ref.stream())
        project_name_by_id: dict[str, str] = {}
        for p in projects:
            data = p.to_dict() or {}
            project_name_by_id[p.id] = str(data.get("name") or p.id)

        project_agg_ref = (
            db.collection("users")
            .document(uid_norm)
            .collection("costMetrics")
            .document("v1")
            .collection("aggregatesByProject")
        )
        project_aggs = list(project_agg_ref.stream())
        cost_by_project_id: dict[str, int] = {}
        for doc_snap in project_aggs:
            data = _as_record(doc_snap.to_dict())
            cost_by_project_id[doc_snap.id] = _cents_from_usd(data.get("totalCostUsd"))
            if doc_snap.id not in project_name_by_id:
                snap = _as_record(data.get("projektSnapshot"))
                if snap.get("name"):
                    project_name_by_id[doc_snap.id] = str(snap.get("name"))

        cost_by_projekt = [
            {
                "projektId": pid,
                "projektName": pname,
                "cost": int(cost_by_project_id.get(pid, 0)),
            }
            for pid, pname in project_name_by_id.items()
        ]
        cost_by_projekt.sort(key=lambda x: int(x.get("cost", 0)), reverse=True)
        if not cost_by_projekt:
            cost_by_projekt.append(
                {"projektId": "__standard__", "projektName": "Standard", "cost": 0}
            )

        by_model = _as_record(agg.get("byModel"))
        model_usage = []
        for key, val in by_model.items():
            if isinstance(val, (int, float)):
                count = int(val or 0)
            else:
                count = int(_as_record(val).get("count", 0) or 0)
            if count > 0:
                model_usage.append(
                    {"model": _display_model_key(str(key)), "count": count}
                )
        model_usage.sort(key=lambda x: int(x.get("count", 0)), reverse=True)

        total_output_tokens_raw = agg.get("totalOutputTokens", 0)
        try:
            total_output_tokens = int(total_output_tokens_raw or 0)
        except Exception:
            total_output_tokens = 0

        if total_output_tokens <= 0 or not model_usage:
            out_tokens, model_counts = _scan_operations_for_backfill(db, uid_norm)
            if total_output_tokens <= 0:
                total_output_tokens = int(out_tokens or 0)
            if not model_usage:
                model_usage = [
                    {"model": model, "count": int(count)}
                    for model, count in sorted(
                        model_counts.items(), key=lambda kv: kv[1], reverse=True
                    )
                ]

        if not model_usage:
            model_usage = [{"model": "-", "count": 0}]

        total_words = max(0, int(round(float(total_output_tokens) * 0.75)))
        member_since = _get_member_since_iso(db, uid_norm)

        ops_limit = max(0, min(int(operations_limit or 0), 200))
        ops_out = []
        if ops_limit > 0:
            ops_ref = (
                db.collection("users")
                .document(uid_norm)
                .collection("costMetrics")
                .document("v1")
                .collection("operations")
            )
            recent = (
                ops_ref.order_by("timestamp", direction=firestore.Query.DESCENDING)
                .limit(ops_limit)
                .stream()
            )
            for op in recent:
                data = op.to_dict() or {}
                costs = _as_record(data.get("costs"))
                tokens = _as_record(data.get("tokens"))
                snapshots = _as_record(data.get("snapshots"))
                proj_snap = _as_record(snapshots.get("projekt"))
                ops_out.append(
                    {
                        "operationId": str(data.get("operationId") or op.id),
                        "timestamp": _ts_to_iso(data.get("timestamp")),
                        "operationType": str(data.get("operationType") or ""),
                        "status": str(data.get("status") or ""),
                        "errorMessage": str(data.get("errorMessage") or "") or None,
                        "model": str(
                            data.get("modelNormalized") or data.get("model") or ""
                        )
                        or None,
                        "keySource": str(data.get("keySource") or "") or None,
                        "cost": _cents_from_usd(costs.get("totalCostUsd")),
                        "outputTokens": int(tokens.get("outputTokens", 0) or 0),
                        "projektId": str(data.get("projektId") or "") or None,
                        "projektName": str(proj_snap.get("name") or "") or None,
                    }
                )

        return {
            "stats": {
                "totalCost": total_cost,
                "totalRuns": total_runs,
                "exportCost": export_cost,
                "exportCount": export_count,
                "totalProjekte": total_projekte,
                "totalKapitel": total_kapitel,
                "totalQuellen": total_quellen,
                "totalWords": total_words,
                "runsByMonth": runs_by_month,
                "costByProjekt": cost_by_projekt,
                "modelUsage": model_usage,
                "memberSince": member_since,
            },
            "operations": ops_out,
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to compute user stats."
        ) from None


@app.get("/api/admin/users/{uid}/projects")
async def admin_list_user_projects(
    uid: str,
    include_archived: bool = True,
    _: str = Depends(verify_admin_user),
):
    """List a user's projects (admin-only, read-only)."""
    uid_norm = (uid or "").strip()
    if not uid_norm:
        raise HTTPException(status_code=400, detail="uid is required.")

    try:
        db = firebase_service.db
        ref = db.collection("users").document(uid_norm).collection("projects")
        docs = list(ref.stream())
        out = []
        for doc_snap in docs:
            data = doc_snap.to_dict() or {}
            archived = bool(data.get("archived") is True)
            if not include_archived and archived:
                continue
            out.append(
                {
                    "id": doc_snap.id,
                    "name": str(data.get("name") or doc_snap.id),
                    "archived": archived,
                    "createdAt": _ts_to_iso(data.get("createdAt")),
                    "updatedAt": _ts_to_iso(data.get("updatedAt")),
                }
            )

        out.sort(key=lambda p: p.get("createdAt") or "", reverse=True)
        return {"projects": out}
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to list projects."
        ) from None


@app.get("/api/admin/users/{uid}/projects/{projekt_id}/quellen")
async def admin_list_user_quellen_for_project(
    uid: str,
    projekt_id: str,
    _: str = Depends(verify_admin_user),
):
    """List Quellen metadata for a project (admin-only, read-only)."""
    uid_norm = (uid or "").strip()
    proj_norm = (projekt_id or "").strip()
    if not uid_norm or not proj_norm:
        raise HTTPException(status_code=400, detail="uid and projekt_id are required.")

    try:
        db = firebase_service.db
        ref = (
            db.collection("users")
            .document(uid_norm)
            .collection("quellen")
            .where("projektId", "==", proj_norm)
        )
        docs = list(ref.stream())
        out = []
        for doc_snap in docs:
            data = doc_snap.to_dict() or {}
            out.append(
                {
                    "id": doc_snap.id,
                    "title": str(data.get("title") or doc_snap.id),
                    "projektId": str(data.get("projektId") or proj_norm),
                    "archived": bool(data.get("archived") is True),
                    "wordCount": int(data.get("wordCount") or 0),
                    "createdAt": _ts_to_iso(data.get("createdAt")),
                    "updatedAt": _ts_to_iso(data.get("updatedAt")),
                    "autor": data.get("autor"),
                    "jahr": data.get("jahr"),
                    "typ": data.get("typ"),
                    "url": data.get("url"),
                    "zugriffAm": data.get("zugriffAm"),
                    "zitat": data.get("zitat"),
                    "zitatModus": data.get("zitatModus"),
                }
            )

        out.sort(key=lambda q: q.get("createdAt") or "", reverse=True)
        return {"quellen": out}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list Quellen.") from None


@app.get("/api/admin/users/{uid}/quellen/{quelle_id}")
async def admin_get_user_quelle(
    uid: str,
    quelle_id: str,
    _: str = Depends(verify_admin_user),
):
    """Get Quelle metadata + content (admin-only, read-only)."""
    uid_norm = (uid or "").strip()
    quelle_norm = (quelle_id or "").strip()
    if not uid_norm or not quelle_norm:
        raise HTTPException(status_code=400, detail="uid and quelle_id are required.")

    try:
        meta = await firebase_service.get_quelle_meta(uid_norm, quelle_norm)
        if not meta:
            raise HTTPException(status_code=404, detail="Quelle not found.")
        content = await firebase_service.get_quelle_content(uid_norm, quelle_norm)
        return {
            "meta": {
                "id": meta.get("id") or quelle_norm,
                "title": meta.get("title"),
                "projektId": meta.get("projektId"),
                "archived": bool(meta.get("archived") is True),
                "wordCount": meta.get("wordCount"),
                "createdAt": _ts_to_iso(meta.get("createdAt")),
                "updatedAt": _ts_to_iso(meta.get("updatedAt")),
                "autor": meta.get("autor"),
                "jahr": meta.get("jahr"),
                "typ": meta.get("typ"),
                "url": meta.get("url"),
                "zugriffAm": meta.get("zugriffAm"),
                "zitat": meta.get("zitat"),
                "zitatModus": meta.get("zitatModus"),
                "images": meta.get("images") or [],
            },
            "content": {
                "text": (content or {}).get("text") if content else None,
                "wordCount": (content or {}).get("wordCount") if content else None,
            },
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to load Quelle.") from None


@app.get("/api/system-prompt-templates")
async def list_system_prompt_templates(
    stage: str | None = None,
    decoded_token: dict = Depends(verify_firebase_token_decoded),
):
    """List published, non-archived system prompt templates (metadata only)."""
    stage_norm = _validate_prompt_stage(stage) if stage else None

    try:
        uid = str(decoded_token.get("uid") or "").strip()
        can_duplicate = False
        if uid:
            try:
                user_doc = await firebase_service.get_user_doc(uid)
                can_duplicate = bool(
                    (user_doc or {}).get("canDuplicateSystemPrompts") is True
                )
            except Exception:
                can_duplicate = False

        templates_raw = await firebase_service.list_system_prompt_templates(stage_norm)
        existing_keys = set()
        for tpl in templates_raw:
            tpl_stage = (tpl.get("stage") or "").strip()
            tpl_key = (tpl.get("templateKey") or "").strip()
            if tpl_stage and tpl_key:
                existing_keys.add((tpl_stage, tpl_key))
        templates_out = []

        for tpl in templates_raw:
            tpl_stage = (tpl.get("stage") or "").strip()
            tpl_key = (tpl.get("templateKey") or "").strip()
            if not tpl_stage or not tpl_key:
                continue
            if stage_norm and tpl_stage != stage_norm:
                continue

            published = bool(tpl.get("published", True) is True)
            archived = bool(tpl.get("archived", False) is True)
            if not published or archived:
                continue

            templates_out.append(
                {
                    "stage": tpl_stage,
                    "templateKey": tpl_key,
                    "name": str((tpl.get("name") or "")).strip() or tpl_key,
                    "createdAt": _ts_to_iso(tpl.get("createdAt")),
                    "updatedAt": _ts_to_iso(tpl.get("updatedAt")),
                }
            )

        # Ensure defaults exist in the list even if Firestore has not been seeded yet.
        stages_to_ensure = [stage_norm] if stage_norm else sorted(ALLOWED_PROMPT_STAGES)
        by_stage_key = {(t["stage"], t["templateKey"]) for t in templates_out}
        for st in stages_to_ensure:
            for key in sorted(SYSTEM_TEMPLATE_KEYS_ALWAYS_AVAILABLE):
                if (st, key) in by_stage_key:
                    continue
                if (st, key) in existing_keys:
                    # Template exists in Firestore but is not selectable (e.g. archived/unpublished); do not synthesize.
                    continue
                templates_out.append(
                    {
                        "stage": st,
                        "templateKey": key,
                        "name": (
                            "System-Standard"
                            if key == "default"
                            else "System-Standard (v2)"
                        ),
                        "createdAt": None,
                        "updatedAt": None,
                    }
                )

        return {
            "templates": templates_out,
            "permissions": {
                "canDuplicateSystemPrompts": can_duplicate,
            },
        }
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to list system prompt templates."
        ) from None


@app.post("/api/system-prompt-templates/duplicate")
async def duplicate_system_prompt_template(
    payload: DuplicateSystemPromptTemplateRequest,
    user_id: str = Depends(verify_system_prompt_export_user),
):
    """Duplicate a published system prompt template into the caller's user-owned prompt library."""
    stage_norm = _validate_prompt_stage(payload.stage)
    key_norm = _validate_template_key(payload.templateKey)

    try:
        sys_tpl = await firebase_service.get_system_prompt_template(
            stage_norm, key_norm
        )
        if not sys_tpl:
            raise HTTPException(
                status_code=404, detail="System prompt template not found."
            )
        if bool(sys_tpl.get("published", True) is not True) or bool(
            sys_tpl.get("archived", False) is True
        ):
            raise HTTPException(
                status_code=404, detail="System prompt template not available."
            )

        name_override = (payload.name or "").strip() or None
        result = await firebase_service.duplicate_system_prompt_template_to_user(
            user_id=user_id,
            stage=stage_norm,
            template_key=key_norm,
            name=name_override,
        )
        return {"status": "ok", "id": result.get("id")}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to duplicate system prompt template."
        ) from None


@app.get("/api/admin/system-prompt-templates")
async def admin_list_system_prompt_templates(
    stage: str | None = None,
    _: str = Depends(verify_admin_user),
):
    """List system prompt templates (admin-only, includes full prompt text)."""
    stage_norm = _validate_prompt_stage(stage) if stage else None
    try:
        templates_raw = await firebase_service.list_system_prompt_templates(stage_norm)
        templates_out = []
        for tpl in templates_raw:
            tpl_stage = (tpl.get("stage") or "").strip()
            tpl_key = (tpl.get("templateKey") or "").strip()
            if not tpl_stage or not tpl_key:
                continue
            if stage_norm and tpl_stage != stage_norm:
                continue

            templates_out.append(
                {
                    "stage": tpl_stage,
                    "templateKey": tpl_key,
                    "name": str((tpl.get("name") or "")).strip() or tpl_key,
                    "instructions": str((tpl.get("instructions") or "")).rstrip(),
                    "systemPrompt": (
                        str(tpl.get("systemPrompt")).rstrip()
                        if tpl.get("systemPrompt") is not None
                        else None
                    ),
                    "published": bool(tpl.get("published", True) is True),
                    "archived": bool(tpl.get("archived", False) is True),
                    "createdAt": _ts_to_iso(tpl.get("createdAt")),
                    "updatedAt": _ts_to_iso(tpl.get("updatedAt")),
                }
            )

        return {"templates": templates_out}
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to list system prompt templates."
        ) from None


@app.post("/api/admin/system-prompt-templates")
async def admin_upsert_system_prompt_template(
    payload: AdminUpsertSystemPromptTemplateRequest,
    _: str = Depends(verify_admin_user),
):
    """Create or update a system prompt template (admin-only)."""
    stage_norm = _validate_prompt_stage(payload.stage)
    key_norm = _validate_template_key(payload.templateKey)
    name = (payload.name or "").strip()
    instructions = (payload.instructions or "").rstrip()
    system_prompt = (
        payload.systemPrompt.rstrip() if isinstance(payload.systemPrompt, str) else None
    )

    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not instructions.strip():
        raise HTTPException(status_code=400, detail="instructions is required")

    _validate_required_placeholders(stage_norm, instructions)

    try:
        await firebase_service.upsert_system_prompt_template(
            stage=stage_norm,
            template_key=key_norm,
            name=name,
            instructions=instructions,
            system_prompt=system_prompt,
            published=bool(payload.published),
            archived=bool(payload.archived),
        )
        return {"status": "ok"}
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to upsert system prompt template."
        ) from None


def _require_admin(credentials: HTTPBasicCredentials = Depends(basic_security)) -> None:
    """
    Basic-auth gate for admin endpoints.

    Browser-friendly: opening the URL prompts for username/password.
    """
    if not config.ADMIN_BASIC_PASSWORD:
        logger.error(
            "ADMIN_BASIC_PASSWORD is not configured. env_diag=%s",
            _safe_env_diagnostics(),
        )
        raise HTTPException(
            status_code=500,
            detail="ADMIN_BASIC_PASSWORD is not configured on the server.",
        )

    username_ok = secrets.compare_digest(
        credentials.username or "", config.ADMIN_BASIC_USER
    )
    password_ok = secrets.compare_digest(
        credentials.password or "", config.ADMIN_BASIC_PASSWORD
    )
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )


def _require_admin_password_and_get_target_email(
    credentials: HTTPBasicCredentials = Depends(basic_security),
) -> str:
    """
    Alternative admin flow:

    - Basic Auth username = target user's email
    - Basic Auth password = ADMIN_BASIC_PASSWORD

    This avoids passing the email in the query string (URL).
    """
    if not config.ADMIN_BASIC_PASSWORD:
        logger.error(
            "ADMIN_BASIC_PASSWORD is not configured. env_diag=%s",
            _safe_env_diagnostics(),
        )
        raise HTTPException(
            status_code=500,
            detail="ADMIN_BASIC_PASSWORD is not configured on the server.",
        )

    password_ok = secrets.compare_digest(
        credentials.password or "", config.ADMIN_BASIC_PASSWORD
    )
    if not password_ok:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={
                "WWW-Authenticate": 'Basic realm="InstantPaper Admin (password required)"'
            },
        )

    email = (credentials.username or "").strip()
    if not email or "@" not in email:
        # Use 401 so the browser re-prompts, with a realm hint that username must be the target email.
        raise HTTPException(
            status_code=401,
            detail="Basic auth username must be the user's email.",
            headers={
                "WWW-Authenticate": 'Basic realm="InstantPaper Approve: username = user email"'
            },
        )
    return email


@app.get("/api/admin/approve")
async def admin_set_user_full_access_basic(
    email: str,
    fullAccess: bool = True,
    approved: bool | None = None,
    _: None = Depends(_require_admin),
):
    """
    Grant/revoke access by setting the Firebase Auth custom claim `fullAccess`.

    Backwards compatible alias: `approved` maps to `fullAccess`.

    Usage (browser will prompt for basic auth):
      /api/admin/approve?email=user@gmail.com&fullAccess=true
    """
    try:
        if approved is not None:
            fullAccess = bool(approved)

        result = await firebase_service.set_user_full_access_by_email(
            email=email, full_access=bool(fullAccess)
        )
        return {
            "status": "ok",
            "email": result.get("email"),
            "uid": result.get("uid"),
            "fullAccess": result.get("fullAccess"),
            "note": "User must refresh token (or re-login) for the claim to take effect.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to update user access."
        ) from None


@app.get("/api/admin/quick-approve")
async def admin_quick_approve(
    email: str = Depends(_require_admin_password_and_get_target_email),
):
    """
    Quick approve without query params:

    - Open /api/admin/quick-approve in a browser
    - Basic Auth prompt: username = target email, password = ADMIN_BASIC_PASSWORD
    """
    try:
        result = await firebase_service.set_user_full_access_by_email(
            email=email, full_access=True
        )
        return {
            "status": "ok",
            "email": result.get("email"),
            "uid": result.get("uid"),
            "fullAccess": True,
            "note": "User must refresh token (or re-login) for the claim to take effect.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to update user access."
        ) from None


@app.get("/api/admin/quick-revoke")
async def admin_quick_revoke(
    email: str = Depends(_require_admin_password_and_get_target_email),
):
    """
    Quick revoke without query params:

    - Open /api/admin/quick-revoke in a browser
    - Basic Auth prompt: username = target email, password = ADMIN_BASIC_PASSWORD
    """
    try:
        result = await firebase_service.set_user_full_access_by_email(
            email=email, full_access=False
        )
        return {
            "status": "ok",
            "email": result.get("email"),
            "uid": result.get("uid"),
            "fullAccess": False,
            "note": "User must refresh token (or re-login) for the claim to take effect.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to update user access."
        ) from None


@app.get("/approve", response_class=HTMLResponse)
async def approve_page(
    email: str | None = None,
    fullAccess: bool = True,
    _: None = Depends(_require_admin),
):
    """
    Browser-friendly approval page (Basic Auth protected).

    Uses POST (form) so email doesn't end up in the URL.
    """
    return _render_approve_page(email=email, full_access=fullAccess, message_html="")


@app.post("/approve", response_class=HTMLResponse)
async def approve_page_submit(
    request: Request,
    _: None = Depends(_require_admin),
):
    """
    Handle approval form submission.

    Avoids extra deps by manually parsing x-www-form-urlencoded body.
    """
    body = (await request.body()).decode("utf-8", errors="ignore")
    params = parse_qs(body)
    email = (params.get("email", [""]) or [""])[0].strip() or None
    full_access_raw = (
        ((params.get("fullAccess", [""]) or [""])[0] or "").strip().lower()
    )
    approved_raw = ((params.get("approved", [""]) or [""])[0] or "").strip().lower()
    raw = full_access_raw or approved_raw or "true"
    full_access = raw in {"true", "1", "yes", "on"}

    message_html = ""
    if email is not None and email.strip():
        try:
            result = await firebase_service.set_user_full_access_by_email(
                email=email, full_access=full_access
            )
            state = "FULL ACCESS" if result.get("fullAccess") else "REVOKED"
            message_html = f"""
              <div class="ok">
                <div><strong>{state}</strong></div>
                <div>Email: <code>{html_lib.escape(result.get("email") or "")}</code></div>
                <div>UID: <code>{html_lib.escape(result.get("uid") or "")}</code></div>
                <div class="note">Hinweis: Der Nutzer muss sich ggf. einmal ab- und wieder anmelden, bis die Änderung wirksam ist.</div>
              </div>
            """
        except Exception as exc:
            message_html = f"""
              <div class="err">
                <div><strong>ERROR</strong></div>
                <div>{html_lib.escape(str(exc) or "Failed to update user approval.")}</div>
              </div>
            """

    return _render_approve_page(
        email=email, full_access=full_access, message_html=message_html
    )


def _render_approve_page(
    email: str | None, full_access: bool, message_html: str
) -> HTMLResponse:
    selected_true = "selected" if full_access else ""
    selected_false = "selected" if not full_access else ""

    html_doc = f"""
    <!doctype html>
    <html lang="de">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>InstantPaper - User Access</title>
        <style>
          body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; background: #0b0b0c; color: #f5f5f5; }}
          .card {{ max-width: 560px; margin: 0 auto; background: #141416; border: 1px solid #2a2a2e; border-radius: 14px; padding: 18px; }}
          h1 {{ font-size: 18px; margin: 0 0 12px; }}
          label {{ display: block; font-size: 13px; color: #cfcfd6; margin: 10px 0 6px; }}
          input[type="email"], select {{ width: 100%; padding: 10px 12px; border-radius: 10px; border: 1px solid #2a2a2e; background: #0f0f11; color: #f5f5f5; }}
          .row {{ display:flex; gap: 12px; align-items: end; margin-top: 10px; }}
          .row > * {{ flex: 1; }}
          .btn {{ display: inline-block; width: 100%; padding: 10px 12px; border-radius: 10px; border: 1px solid #2a2a2e; background: #f5f5f5; color: #0b0b0c; font-weight: 600; }}
          .btn:active {{ transform: translateY(1px); }}
          .muted {{ font-size: 12px; color: #a8a8b3; margin-top: 10px; }}
          .ok {{ margin-top: 14px; padding: 12px; border-radius: 12px; border: 1px solid #1f3b24; background: #0f1a12; }}
          .err {{ margin-top: 14px; padding: 12px; border-radius: 12px; border: 1px solid #4a1f1f; background: #1b0f0f; }}
          .note {{ margin-top: 8px; font-size: 12px; color: #cfcfd6; }}
          code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
        </style>
      </head>
      <body>
        <div class="card">
          <h1>User Access</h1>
          <form method="post" action="/approve">
            <label for="email">Google Email</label>
            <input id="email" name="email" type="email" placeholder="name@gmail.com" required value="{html_lib.escape(email or "")}" />
            <div class="row">
              <div>
                <label for="fullAccess" style="margin:0 0 6px;">Status</label>
                <select id="fullAccess" name="fullAccess">
                  <option value="true" {selected_true}>fullAccess</option>
                  <option value="false" {selected_false}>revoked</option>
                </select>
              </div>
              <button class="btn" type="submit">Speichern</button>
            </div>
            <div class="muted">Tipp: Nutzer muss ggf. Token refreshen / neu anmelden.</div>
          </form>
          {message_html}
        </div>
      </body>
    </html>
    """

    return HTMLResponse(content=html_doc, status_code=200)


@app.post("/api/auth/session")
async def create_session(request: CreateSessionRequest):
    """
    Exchange Firebase ID token for a session cookie.

    Returns session cookie and expiration time in seconds.
    """
    try:
        # Verify ID token first
        await firebase_service.verify_token(request.idToken)

        # Create session cookie (14 days)
        session_cookie = await firebase_service.create_session_cookie(
            request.idToken, expires_in_days=14
        )

        return {
            "sessionCookie": session_cookie,
            "expiresIn": 14 * 24 * 60 * 60,  # 14 days in seconds
        }
    except Exception as e:
        logger.error(f"Failed to create session cookie: {str(e)}")
        raise HTTPException(
            status_code=401, detail=f"Failed to create session: {str(e)}"
        )


@app.post("/api/auth/revoke")
async def revoke_session(request: RevokeSessionRequest):
    """
    Revoke a session by revoking all refresh tokens for the user.
    """
    try:
        # Decode session cookie to get user ID (don't verify, just decode)
        # We decode without verification since we just need the UID
        parts = request.sessionCookie.split(".")
        if len(parts) >= 2:
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
            user_id = payload.get("uid")

            if user_id:
                # Revoke all refresh tokens for this user
                auth.revoke_refresh_tokens(user_id)
                logger.info(f"Revoked refresh tokens for user {user_id}")

        return {"status": "revoked"}
    except Exception as e:
        logger.error(f"Failed to revoke session: {str(e)}")
        raise HTTPException(
            status_code=400, detail=f"Failed to revoke session: {str(e)}"
        )


@app.get("/test/auth")
async def test_auth(user_id: str = Depends(verify_firebase_token)):
    """
    Test endpoint to verify Firebase authentication

    Requires Authorization header with Firebase ID token
    """
    return {"message": "Authentication successful", "user_id": user_id}


@app.get("/api/user/openai-key")
async def get_openai_key_status(user_id: str = Depends(verify_firebase_token)):
    """Return whether a user has their own OpenAI key and if platform key is allowed."""
    return await user_key_service.get_status(user_id)


@app.post("/api/user/openai-key")
async def save_openai_key(
    payload: SaveOpenAIKeyRequest,
    user_id: str = Depends(verify_firebase_token),
):
    """Validate and store a user's OpenAI key securely."""
    try:
        return await user_key_service.save_user_key(user_id, payload.key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/user/openai-key")
async def delete_openai_key(user_id: str = Depends(verify_firebase_token)):
    """Delete the stored OpenAI key for the user."""
    return await user_key_service.delete_user_key(user_id)


@app.post("/api/process", status_code=status.HTTP_202_ACCEPTED)
async def process_quelle(
    request: ProcessQuelleRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(verify_firebase_token),
):
    """
    Process a Quelle with OpenAI

    Requires Authorization header with Firebase ID token.
    Fetches the Quelle, processes it with OpenAI, and saves the result.

    Args:
        request: ProcessQuelleRequest containing quelle_id, model, kapitel_id, and run_id
        user_id: Extracted from verified Firebase token (dependency)

    Returns:
        ProcessQuelleResponse with result details
    """
    logger.info(
        f"Processing Quelle {request.quelle_id} for user {user_id} (Kapitel {request.kapitel_id}, run {request.run_id})"
    )

    # Block duplicate processing while already running (prevents double charges + weird UI states).
    existing_result = await firebase_service.get_run_result(
        user_id, request.kapitel_id, request.run_id, request.quelle_id
    )
    if existing_result and existing_result.get("status") == "running":
        raise HTTPException(
            status_code=400, detail="Diese Quelle wird bereits verarbeitet."
        )

    await get_credits_service(firebase_service).assert_not_negative_balance(user_id)

    run_doc = await firebase_service.get_run(
        user_id, request.kapitel_id, request.run_id
    )
    run_model = (run_doc.get("model") or "").strip() if run_doc else ""
    model_to_use = run_model or request.model

    # Create/merge placeholder result doc immediately so the UI can show running/error state.
    await firebase_service.mark_result_running(
        user_id=user_id,
        kapitel_id=request.kapitel_id,
        run_id=request.run_id,
        quelle_id=request.quelle_id,
        model=model_to_use,
    )

    async def _run_process_single_quelle() -> None:
        try:
            await quelle_service.process_single_quelle(
                user_id,
                request.quelle_id,
                request.kapitel_id,
                request.run_id,
                model_to_use,
            )
        except Exception as e:
            logger.error(
                f"Background processing failed for Quelle {request.quelle_id} "
                f"(Kapitel {request.kapitel_id}, run {request.run_id}, user {user_id}): {e}",
                exc_info=True,
            )
            error_message = None
            if isinstance(e, HTTPException) and e.status_code == 402:
                error_message = str(e.detail)
            await firebase_service.mark_result_error(
                user_id=user_id,
                kapitel_id=request.kapitel_id,
                run_id=request.run_id,
                quelle_id=request.quelle_id,
                error_message=error_message,
            )

    # Process Quelle in the background to return immediately
    background_tasks.add_task(_run_process_single_quelle)

    return {
        "status": "queued",
        "quelle_id": request.quelle_id,
        "kapitel_id": request.kapitel_id,
        "run_id": request.run_id,
        "queued_at": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/api/combine-run", status_code=status.HTTP_202_ACCEPTED)
async def combine_run(
    request: CombineRunRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(verify_firebase_token),
):
    """
    Combine multiple Quelle results within a run into a single text.

    Requires Authorization header with Firebase ID token.
    """
    logger.info(
        f"Combining run {request.run_id} for user {user_id} (Kapitel {request.kapitel_id})"
    )

    existing_combined = await firebase_service.get_combined_result(
        user_id, request.kapitel_id, request.run_id
    )
    if existing_combined:
        existing_status = (existing_combined.get("status") or "").strip()
        existing_content = (existing_combined.get("content") or "").strip()
        if existing_status == "running":
            raise HTTPException(status_code=400, detail="Kombination läuft bereits.")
        if existing_content and (existing_status == "success" or not existing_status):
            raise HTTPException(
                status_code=400,
                detail="Kombinierter Text existiert bereits für diesen Run.",
            )

    await get_credits_service(firebase_service).assert_not_negative_balance(user_id)

    run_doc = await firebase_service.get_run(
        user_id, request.kapitel_id, request.run_id
    )
    run_model = (run_doc.get("model") or "").strip() if run_doc else None

    # Create/merge placeholder artifact doc immediately so the UI can show running/error state.
    await firebase_service.mark_artifact_running(
        user_id=user_id,
        kapitel_id=request.kapitel_id,
        run_id=request.run_id,
        artifact_id="combined",
        model=run_model,
    )

    async def _run_combine_run_results() -> None:
        try:
            await quelle_service.combine_run_results(
                user_id,
                request.kapitel_id,
                request.run_id,
            )
        except Exception as e:
            logger.error(
                f"Background combine failed for run {request.run_id} "
                f"(Kapitel {request.kapitel_id}, user {user_id}): {e}",
                exc_info=True,
            )
            error_message = None
            if isinstance(e, HTTPException) and e.status_code == 402:
                error_message = str(e.detail)
            await firebase_service.mark_artifact_error(
                user_id=user_id,
                kapitel_id=request.kapitel_id,
                run_id=request.run_id,
                artifact_id="combined",
                error_message=error_message,
            )

    background_tasks.add_task(_run_combine_run_results)

    return {
        "status": "queued",
        "kapitel_id": request.kapitel_id,
        "run_id": request.run_id,
        "queued_at": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/api/adopt-combined", status_code=status.HTTP_200_OK)
async def adopt_combined(
    request: AdoptCombinedRequest,
    user_id: str = Depends(verify_firebase_token),
):
    """
    Adopt a single Quelle result as the combined text for a run (no LLM call).

    Requires Authorization header with Firebase ID token.
    """
    logger.info(
        f"Adopting combined text for user {user_id} "
        f"(Kapitel {request.kapitel_id}, run {request.run_id}, quelle {request.quelle_id})"
    )
    return await quelle_service.adopt_single_result_as_combined(
        user_id=user_id,
        kapitel_id=request.kapitel_id,
        run_id=request.run_id,
        quelle_id=request.quelle_id,
    )


@app.post("/api/shorten", status_code=status.HTTP_202_ACCEPTED)
async def shorten_kapitel(
    request: ShortenKapitelRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(verify_firebase_token),
):
    """
    Shorten and deduplicate a Kapitel text using context from other Kapitels.

    Requires Authorization header with Firebase ID token.
    """
    logger.info(
        f"Shortening Kapitel {request.kapitel_id} run {request.run_id} for user {user_id} "
        f"with {len(request.context_kapitel_ids)} context Kapitels"
    )

    existing_shortened = await firebase_service.get_shortened_result(
        user_id, request.kapitel_id, request.run_id
    )
    if (
        existing_shortened
        and (existing_shortened.get("status") or "").strip() == "running"
    ):
        raise HTTPException(status_code=400, detail="Text wird bereits gekürzt.")

    # Create/merge placeholder artifact doc immediately so the UI can show running/error state.
    await get_credits_service(firebase_service).assert_not_negative_balance(user_id)

    await firebase_service.mark_artifact_running(
        user_id=user_id,
        kapitel_id=request.kapitel_id,
        run_id=request.run_id,
        artifact_id="shortened",
        model=request.model,
        used_kapitel_ids=request.context_kapitel_ids,
    )

    async def _run_shorten_process() -> None:
        try:
            await shorten_service.process_shorten_request(
                user_id,
                request.kapitel_id,
                request.run_id,
                request.context_kapitel_ids,
                request.model,
            )
        except Exception as e:
            logger.error(
                f"Background shortening failed for Kapitel {request.kapitel_id} "
                f"(run {request.run_id}, user {user_id}): {e}",
                exc_info=True,
            )
            error_message = None
            if isinstance(e, HTTPException) and e.status_code == 402:
                error_message = str(e.detail)
            await firebase_service.mark_artifact_error(
                user_id=user_id,
                kapitel_id=request.kapitel_id,
                run_id=request.run_id,
                artifact_id="shortened",
                error_message=error_message,
            )

    background_tasks.add_task(_run_shorten_process)

    return {
        "status": "queued",
        "kapitel_id": request.kapitel_id,
        "run_id": request.run_id,
        "queued_at": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/api/lesefluss", status_code=status.HTTP_202_ACCEPTED)
async def improve_lesefluss(
    request: LeseflussKapitelRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(verify_firebase_token),
):
    """
    Improve reading flow (Lese Fluss) for a Kapitel.

    Requirements:
    - Kapitel must have shortened text
    - Context kapitels must have shortened text
    - Aufgabenstellung (task description) required

    Queues background task and returns immediately.
    """
    try:
        logger.info(
            f"Received lesefluss request for kapitel {request.kapitel_id}, "
            f"run {request.run_id}, user {user_id}"
        )

        existing_lesefluss = await firebase_service.get_lesefluss_result(
            user_id, request.kapitel_id, request.run_id
        )
        if (
            existing_lesefluss
            and (existing_lesefluss.get("status") or "").strip() == "running"
        ):
            raise HTTPException(
                status_code=400, detail="Lesefluss wird bereits erstellt."
            )

        await get_credits_service(firebase_service).assert_not_negative_balance(user_id)

        # Resolve API key (user key or platform key)
        api_key, key_source = await user_key_service.resolve_api_key_for_user(user_id)

        # Create/merge placeholder artifact doc immediately so the UI can show running/error state.
        await firebase_service.mark_artifact_running(
            user_id=user_id,
            kapitel_id=request.kapitel_id,
            run_id=request.run_id,
            artifact_id="lesefluss",
            model=request.model,
            used_kapitel_ids=request.context_kapitel_ids,
            aufgabenstellung=request.aufgabenstellung,
        )

        # Queue the lesefluss process as a background task
        async def _run_lesefluss_process() -> None:
            try:
                await shorten_service.process_lesefluss_request(
                    user_id=user_id,
                    kapitel_id=request.kapitel_id,
                    run_id=request.run_id,
                    context_kapitel_ids=request.context_kapitel_ids,
                    aufgabenstellung=request.aufgabenstellung,
                    model=request.model,
                    api_key=api_key,
                    key_source=key_source,
                )
            except Exception as e:
                logger.error(
                    f"Background lesefluss failed for Kapitel {request.kapitel_id} "
                    f"(run {request.run_id}, user {user_id}): {e}",
                    exc_info=True,
                )
                error_message = None
                if isinstance(e, HTTPException) and e.status_code == 402:
                    error_message = str(e.detail)
                await firebase_service.mark_artifact_error(
                    user_id=user_id,
                    kapitel_id=request.kapitel_id,
                    run_id=request.run_id,
                    artifact_id="lesefluss",
                    key_source=key_source,
                    error_message=error_message,
                )

        background_tasks.add_task(_run_lesefluss_process)

        return {
            "status": "queued",
            "kapitel_id": request.kapitel_id,
            "run_id": request.run_id,
            "queued_at": datetime.utcnow().isoformat() + "Z",
        }

    except Exception as e:
        logger.error(f"Error queueing lesefluss request: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to queue lesefluss request: {str(e)}",
        )


@app.post("/api/export-docx", status_code=status.HTTP_202_ACCEPTED)
async def export_docx(
    request: ExportDocxRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(verify_firebase_token),
):
    """
    Export improved Kapitel texts (lesefluss) to a single DOCX and store it in Firebase Storage.

    Queues a background task and returns immediately. The UI should read export status from
    Firestore (`users/{uid}/exports/{exportId}`).
    """
    credits_service = get_credits_service(firebase_service)
    available_credits = float(await credits_service.get_available_credits(user_id))
    if available_credits <= 0:
        raise HTTPException(
            status_code=402,
            detail="Kein Guthaben verf\u00fcgbar. Bitte lade Credits im Profil unter Billing auf.",
        )

    # Validate that an API key is available (user key or platform key). The export may need LLM fixups.
    await user_key_service.resolve_api_key_for_user(user_id)

    export_id = await export_service.create_export_job(
        user_id=user_id,
        projekt_id=request.projekt_id,
        selection=request.selection,
        kapitel_ids=request.kapitel_ids,
    )

    async def _run_export() -> None:
        await export_service.process_export_job(user_id=user_id, export_id=export_id)

    background_tasks.add_task(_run_export)

    return {
        "status": "queued",
        "export_id": export_id,
        "queued_at": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/api/refine/combined/init")
async def init_combined_refinement(
    request: RefineCombinedInitRequest,
    user_id: str = Depends(verify_firebase_token),
):
    """
    Initialize the text refinement flow for a combined text.

    Ensures:
    - combined/combined/versions/root exists
    - combined doc has refinement metadata fields
    """
    logger.info(
        f"Initializing combined refinement for user {user_id} "
        f"(kapitel {request.kapitel_id}, run {request.run_id})"
    )
    return await refinement_service.init_combined_refinement(
        user_id=user_id,
        kapitel_id=request.kapitel_id,
        run_id=request.run_id,
    )


@app.post("/api/refine/combined", status_code=status.HTTP_202_ACCEPTED)
async def refine_combined_text(
    request: RefineCombinedRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(verify_firebase_token),
):
    """
    Queue a combined text refinement step (text refinement flow).

    Writes a pending versions/{versionId} doc and processes the OpenAI call in the background.
    """
    logger.info(
        f"Queueing combined refinement for user {user_id} "
        f"(kapitel {request.kapitel_id}, run {request.run_id}, parent {request.parent_version_id})"
    )
    try:
        await get_credits_service(firebase_service).assert_not_negative_balance(user_id)

        # Validate that an API key is available (user key or platform key)
        await user_key_service.resolve_api_key_for_user(user_id)

        queued = await refinement_service.queue_combined_refinement(
            user_id=user_id,
            kapitel_id=request.kapitel_id,
            run_id=request.run_id,
            parent_version_id=request.parent_version_id,
            user_message=request.user_message,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error queueing combined refinement: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to queue refinement request."
        ) from exc

    async def _run_refine() -> None:
        await refinement_service.process_combined_refinement(
            user_id=user_id,
            kapitel_id=request.kapitel_id,
            run_id=request.run_id,
            version_id=queued["version_id"],
            parent_version_id=request.parent_version_id,
            user_message=request.user_message,
        )

    background_tasks.add_task(_run_refine)
    queued["queued_at"] = datetime.utcnow().isoformat() + "Z"
    return queued


@app.post("/api/refine/shortened/init")
async def init_shortened_refinement(
    request: RefineShortenedInitRequest,
    user_id: str = Depends(verify_firebase_token),
):
    """
    Initialize the text refinement flow for a shortened text.

    Ensures:
    - shortened/shortened/versions/root exists
    - shortened doc has refinement metadata fields
    """
    logger.info(
        f"Initializing shortened refinement for user {user_id} "
        f"(kapitel {request.kapitel_id}, run {request.run_id})"
    )
    return await refinement_service.init_shortened_refinement(
        user_id=user_id,
        kapitel_id=request.kapitel_id,
        run_id=request.run_id,
    )


@app.post("/api/refine/shortened", status_code=status.HTTP_202_ACCEPTED)
async def refine_shortened_text(
    request: RefineShortenedRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(verify_firebase_token),
):
    """
    Queue a shortened text refinement step (text refinement flow).

    Writes a pending versions/{versionId} doc and processes the OpenAI call in the background.
    """
    logger.info(
        f"Queueing shortened refinement for user {user_id} "
        f"(kapitel {request.kapitel_id}, run {request.run_id}, parent {request.parent_version_id})"
    )
    try:
        await get_credits_service(firebase_service).assert_not_negative_balance(user_id)

        # Validate that an API key is available (user key or platform key)
        await user_key_service.resolve_api_key_for_user(user_id)

        queued = await refinement_service.queue_shortened_refinement(
            user_id=user_id,
            kapitel_id=request.kapitel_id,
            run_id=request.run_id,
            parent_version_id=request.parent_version_id,
            user_message=request.user_message,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error queueing shortened refinement: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to queue refinement request."
        ) from exc

    async def _run_refine() -> None:
        await refinement_service.process_shortened_refinement(
            user_id=user_id,
            kapitel_id=request.kapitel_id,
            run_id=request.run_id,
            version_id=queued["version_id"],
            parent_version_id=request.parent_version_id,
            user_message=request.user_message,
        )

    background_tasks.add_task(_run_refine)
    queued["queued_at"] = datetime.utcnow().isoformat() + "Z"
    return queued


@app.post("/api/refine/lesefluss/init")
async def init_lesefluss_refinement(
    request: RefineLeseflussInitRequest,
    user_id: str = Depends(verify_firebase_token),
):
    """
    Initialize the text refinement flow for a lesefluss text.

    Ensures:
    - lesefluss/lesefluss/versions/root exists
    - lesefluss doc has refinement metadata fields
    """
    logger.info(
        f"Initializing lesefluss refinement for user {user_id} "
        f"(kapitel {request.kapitel_id}, run {request.run_id})"
    )
    return await refinement_service.init_lesefluss_refinement(
        user_id=user_id,
        kapitel_id=request.kapitel_id,
        run_id=request.run_id,
    )


@app.post("/api/refine/lesefluss", status_code=status.HTTP_202_ACCEPTED)
async def refine_lesefluss_text(
    request: RefineLeseflussRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(verify_firebase_token),
):
    """
    Queue a lesefluss text refinement step (text refinement flow).

    Writes a pending versions/{versionId} doc and processes the OpenAI call in the background.
    """
    logger.info(
        f"Queueing lesefluss refinement for user {user_id} "
        f"(kapitel {request.kapitel_id}, run {request.run_id}, parent {request.parent_version_id})"
    )
    try:
        await get_credits_service(firebase_service).assert_not_negative_balance(user_id)

        # Validate that an API key is available (user key or platform key)
        await user_key_service.resolve_api_key_for_user(user_id)

        queued = await refinement_service.queue_lesefluss_refinement(
            user_id=user_id,
            kapitel_id=request.kapitel_id,
            run_id=request.run_id,
            parent_version_id=request.parent_version_id,
            user_message=request.user_message,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error queueing lesefluss refinement: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to queue refinement request."
        ) from exc

    async def _run_refine() -> None:
        await refinement_service.process_lesefluss_refinement(
            user_id=user_id,
            kapitel_id=request.kapitel_id,
            run_id=request.run_id,
            version_id=queued["version_id"],
            parent_version_id=request.parent_version_id,
            user_message=request.user_message,
        )

    background_tasks.add_task(_run_refine)
    queued["queued_at"] = datetime.utcnow().isoformat() + "Z"
    return queued


@app.post("/api/refine/result/init")
async def init_result_refinement(
    request: RefineResultInitRequest,
    user_id: str = Depends(verify_firebase_token),
):
    """
    Initialize the text refinement flow for a Quelle result text.

    Ensures:
    - results/{quelleId}/versions/root exists
    - result doc has refinement metadata fields
    """
    logger.info(
        f"Initializing result refinement for user {user_id} "
        f"(kapitel {request.kapitel_id}, run {request.run_id}, quelle {request.quelle_id})"
    )
    return await refinement_service.init_result_refinement(
        user_id=user_id,
        kapitel_id=request.kapitel_id,
        run_id=request.run_id,
        quelle_id=request.quelle_id,
    )


@app.post("/api/refine/result", status_code=status.HTTP_202_ACCEPTED)
async def refine_result_text(
    request: RefineResultRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(verify_firebase_token),
):
    """
    Queue a Quelle result text refinement step (text refinement flow).

    Writes a pending results/{quelleId}/versions/{versionId} doc and processes the OpenAI call in the background.
    """
    logger.info(
        f"Queueing result refinement for user {user_id} "
        f"(kapitel {request.kapitel_id}, run {request.run_id}, quelle {request.quelle_id}, parent {request.parent_version_id})"
    )
    try:
        await get_credits_service(firebase_service).assert_not_negative_balance(user_id)

        # Validate that an API key is available (user key or platform key)
        await user_key_service.resolve_api_key_for_user(user_id)

        queued = await refinement_service.queue_result_refinement(
            user_id=user_id,
            kapitel_id=request.kapitel_id,
            run_id=request.run_id,
            quelle_id=request.quelle_id,
            parent_version_id=request.parent_version_id,
            user_message=request.user_message,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error queueing result refinement: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to queue refinement request."
        ) from exc

    async def _run_refine() -> None:
        await refinement_service.process_result_refinement(
            user_id=user_id,
            kapitel_id=request.kapitel_id,
            run_id=request.run_id,
            quelle_id=request.quelle_id,
            version_id=queued["version_id"],
            parent_version_id=request.parent_version_id,
            user_message=request.user_message,
        )

    background_tasks.add_task(_run_refine)
    queued["queued_at"] = datetime.utcnow().isoformat() + "Z"
    return queued


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=config.PORT,
        reload=config.DEBUG,
        # Use our in-app logging config; keep access logs.
        log_config=None,
        access_log=True,
    )
