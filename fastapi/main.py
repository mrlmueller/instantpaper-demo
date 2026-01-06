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
    approved: bool = True


class AdminSetPlatformKeyRequest(BaseModel):
    email: str
    allowPlatformKey: bool


class AdminSetSystemPromptExportRequest(BaseModel):
    email: str
    canDuplicateSystemPrompts: bool


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
        logger.warning("ADMIN_BASIC_PASSWORD is empty (admin approval endpoints disabled). env_diag=%s", diag)

    yield

    # Shutdown (if needed in the future)
    logger.debug("Shutting down InstantPaper API server...")


# Initialize FastAPI app with lifespan
app = FastAPI(
    title="InstantPaper API",
    version="1.0.0",
    description="FastAPI backend for processing Quellen with OpenAI",
    lifespan=lifespan
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
    return {
        "message": "InstantPaper API",
        "version": "1.0.0",
        "status": "running"
    }


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
        return datetime.utcfromtimestamp(int(ts_ms) / 1000.0).replace(microsecond=0).isoformat() + "Z"
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


@app.get("/api/admin/users")
async def admin_list_users(
    approved: bool | None = None,
    query: str | None = None,
    page_token: str | None = None,
    max_results: int = 200,
    _: str = Depends(verify_admin_user),
):
    """
    List Firebase Auth users (admin-only).

    This powers the admin approval UI: pending users are those with `approved != true`.
    """
    try:
        # Ensure Firebase Admin SDK is initialized.
        _ = firebase_service.db

        max_results = max(1, min(int(max_results or 200), 1000))
        q = (query or "").strip().lower()

        page = auth.list_users(page_token=page_token, max_results=max_results)
        users_out = []
        for user in page.users:
            email = (user.email or "").strip()
            display_name = (user.display_name or "").strip()
            if q and (q not in email.lower()) and (q not in display_name.lower()):
                continue

            claims = user.custom_claims or {}
            is_approved = bool(claims.get("approved") is True)
            if approved is not None and is_approved != bool(approved):
                continue

            allow_platform_key = False
            can_duplicate_system_prompts = False
            try:
                user_doc = await firebase_service.get_user_doc(user.uid)
                allow_platform_key = bool((user_doc or {}).get("allowPlatformKey") is True)
                can_duplicate_system_prompts = bool((user_doc or {}).get("canDuplicateSystemPrompts") is True)
            except Exception:
                allow_platform_key = False
                can_duplicate_system_prompts = False

            users_out.append(
                {
                    "uid": str(user.uid),
                    "email": email or None,
                    "displayName": display_name or None,
                    "approved": is_approved,
                    "canDuplicateSystemPrompts": can_duplicate_system_prompts,
                    "disabled": bool(user.disabled),
                    "allowPlatformKey": allow_platform_key,
                    "createdAt": _ms_to_iso(getattr(user.user_metadata, "creation_timestamp", None)),
                    "lastSignInAt": _ms_to_iso(getattr(user.user_metadata, "last_sign_in_timestamp", None)),
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
    """Approve/revoke a user by email by setting the Firebase Auth custom claim `approved`."""
    email = (payload.email or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")

    try:
        result = await firebase_service.set_user_approved_by_email(email=email, approved=bool(payload.approved))
        return {
            "status": "ok",
            "email": result.get("email"),
            "approved": result.get("approved"),
            "note": "User must sign out/in (or refresh token) for the claim to take effect.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update user approval.") from None


@app.post("/api/admin/users/platform-key")
async def admin_set_platform_key(
    payload: AdminSetPlatformKeyRequest,
    _: str = Depends(verify_admin_user),
):
    """Allow or block a user from using the platform OpenAI key (Firestore: users/{uid}.allowPlatformKey)."""
    email = (payload.email or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")

    allow_platform = bool(payload.allowPlatformKey)

    try:
        # Ensure Firebase Admin SDK is initialized.
        _ = firebase_service.db

        user = auth.get_user_by_email(email)

        user_ref = firebase_service.db.collection("users").document(user.uid)
        existing = user_ref.get()

        write_payload = {
            "uid": user.uid,
            "email": (user.email or "").strip() or email,
            "allowPlatformKey": allow_platform,
            "updatedAt": SERVER_TIMESTAMP,
        }
        if not existing.exists:
            write_payload["createdAt"] = SERVER_TIMESTAMP

        user_ref.set(write_payload, merge=True)

        return {
            "status": "ok",
            "email": (user.email or "").strip() or email,
            "allowPlatformKey": allow_platform,
        }
    except auth.UserNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail="User not found. Ask the user to sign in once, then try again.",
        ) from exc
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update platform-key permission.") from None


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
        raise HTTPException(status_code=500, detail="Failed to update system prompt copy permission.") from None


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
        raise HTTPException(status_code=400, detail="Instructions dürfen nicht leer sein.")
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
    approved = bool(claims.get("approved") is True)

    allow_platform_key = False
    can_duplicate_system_prompts = False
    try:
        user_doc = await firebase_service.get_user_doc(user.uid)
        allow_platform_key = bool((user_doc or {}).get("allowPlatformKey") is True)
        can_duplicate_system_prompts = bool((user_doc or {}).get("canDuplicateSystemPrompts") is True)
    except Exception:
        allow_platform_key = False
        can_duplicate_system_prompts = False

    try:
        key_status = await user_key_service.get_status(user.uid)
        has_key = bool(key_status.get("has_key"))
        last4 = key_status.get("last4") if has_key else None
        allow_platform_from_status = bool(key_status.get("allow_platform_key"))
    except Exception:
        has_key = False
        last4 = None
        allow_platform_from_status = allow_platform_key

    key_source = "user" if has_key else ("platform" if allow_platform_from_status else "none")

    return {
        "user": {
            "uid": str(user.uid),
            "email": (user.email or "").strip() or None,
            "displayName": (user.display_name or "").strip() or None,
            "approved": approved,
            "disabled": bool(user.disabled),
            "allowPlatformKey": allow_platform_key,
            "canDuplicateSystemPrompts": can_duplicate_system_prompts,
            "createdAt": _ms_to_iso(getattr(user.user_metadata, "creation_timestamp", None)),
            "lastSignInAt": _ms_to_iso(getattr(user.user_metadata, "last_sign_in_timestamp", None)),
        },
        "openaiKey": {
            "hasKey": has_key,
            "last4": last4,
            "allowPlatformKey": allow_platform_from_status,
            "source": key_source,
        },
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
                    "placeholders": list(data.get("placeholders") or []) or list(prompt_service.REQUIRED_PLACEHOLDERS.get(stage, []) or []),
                    "createdAt": _ts_to_iso(data.get("createdAt")),
                    "updatedAt": _ts_to_iso(data.get("updatedAt")),
                }
            )

        templates_out.sort(key=lambda t: (t.get("stage") or "", t.get("updatedAt") or t.get("createdAt") or ""), reverse=True)

        settings_doc = _prompt_settings_ref(uid_norm).get()
        settings = settings_doc.to_dict() if settings_doc.exists else {}
        active = settings.get("activeTemplates", {}) if isinstance(settings, dict) else {}
        ask_on_each = bool(settings.get("askOnEachProcess")) if isinstance(settings, dict) else False

        return {
            "templates": templates_out,
            "active": active or {},
            "askOnEachProcess": ask_on_each,
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list prompt templates.") from None


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
                "placeholders": list(prompt_service.REQUIRED_PLACEHOLDERS.get(stage_norm, []) or []),
                "createdAt": SERVER_TIMESTAMP,
                "updatedAt": SERVER_TIMESTAMP,
            }
        )
        return {"status": "ok", "id": doc_ref.id}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to create prompt template.") from None


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
                "placeholders": list(prompt_service.REQUIRED_PLACEHOLDERS.get(stage_norm, []) or []),
                "updatedAt": SERVER_TIMESTAMP,
            },
            merge=True,
        )
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update prompt template.") from None


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
                active_next = {**active, stage_norm: "default"}
                settings_ref.set({"activeTemplates": active_next, "updatedAt": SERVER_TIMESTAMP}, merge=True)

        tpl_ref.delete()
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to delete prompt template.") from None


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
                sys_tpl = await firebase_service.get_system_prompt_template(stage_norm, key_norm)
                if not sys_tpl:
                    raise HTTPException(status_code=404, detail="System prompt template not found.")
                if bool(sys_tpl.get("published", True) is not True) or bool(sys_tpl.get("archived", False) is True):
                    raise HTTPException(status_code=404, detail="System prompt template not available.")

        settings_ref = _prompt_settings_ref(uid_norm)
        settings_snap = settings_ref.get()
        current = settings_snap.to_dict() if settings_snap.exists else {}
        active = current.get("activeTemplates", {}) if isinstance(current, dict) else {}
        if not isinstance(active, dict):
            active = {}

        active_next = {**active, stage_norm: template_id}
        payload_out: dict = {"activeTemplates": active_next, "updatedAt": SERVER_TIMESTAMP}
        if not settings_snap.exists:
            payload_out["createdAt"] = SERVER_TIMESTAMP
        settings_ref.set(payload_out, merge=True)

        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to set active prompt.") from None


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
    return (parsed[0] if parsed else datetime.now(timezone.utc)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _scan_operations_for_backfill(db, uid: str, max_docs: int = 5000) -> tuple[int, dict[str, int]]:
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

            model_raw = data.get("modelNormalized") or data.get("model") or data.get("modelKey") or "unknown"
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
            cost_by_projekt.append({"projektId": "__standard__", "projektName": "Standard", "cost": 0})

        by_model = _as_record(agg.get("byModel"))
        model_usage = []
        for key, val in by_model.items():
            if isinstance(val, (int, float)):
                count = int(val or 0)
            else:
                count = int(_as_record(val).get("count", 0) or 0)
            if count > 0:
                model_usage.append({"model": _display_model_key(str(key)), "count": count})
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
                    for model, count in sorted(model_counts.items(), key=lambda kv: kv[1], reverse=True)
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
                        "model": str(data.get("modelNormalized") or data.get("model") or "") or None,
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
        raise HTTPException(status_code=500, detail="Failed to compute user stats.") from None


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
        raise HTTPException(status_code=500, detail="Failed to list projects.") from None


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
        ref = db.collection("users").document(uid_norm).collection("quellen").where("projektId", "==", proj_norm)
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
                can_duplicate = bool((user_doc or {}).get("canDuplicateSystemPrompts") is True)
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
                        "name": "System-Standard" if key == "default" else "System-Standard (v2)",
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
        raise HTTPException(status_code=500, detail="Failed to list system prompt templates.") from None


@app.post("/api/system-prompt-templates/duplicate")
async def duplicate_system_prompt_template(
    payload: DuplicateSystemPromptTemplateRequest,
    user_id: str = Depends(verify_system_prompt_export_user),
):
    """Duplicate a published system prompt template into the caller's user-owned prompt library."""
    stage_norm = _validate_prompt_stage(payload.stage)
    key_norm = _validate_template_key(payload.templateKey)

    try:
        sys_tpl = await firebase_service.get_system_prompt_template(stage_norm, key_norm)
        if not sys_tpl:
            raise HTTPException(status_code=404, detail="System prompt template not found.")
        if bool(sys_tpl.get("published", True) is not True) or bool(sys_tpl.get("archived", False) is True):
            raise HTTPException(status_code=404, detail="System prompt template not available.")

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
        raise HTTPException(status_code=500, detail="Failed to duplicate system prompt template.") from None


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
                    "systemPrompt": (str(tpl.get("systemPrompt")).rstrip() if tpl.get("systemPrompt") is not None else None),
                    "published": bool(tpl.get("published", True) is True),
                    "archived": bool(tpl.get("archived", False) is True),
                    "createdAt": _ts_to_iso(tpl.get("createdAt")),
                    "updatedAt": _ts_to_iso(tpl.get("updatedAt")),
                }
            )

        return {"templates": templates_out}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to list system prompt templates.") from None


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
    system_prompt = payload.systemPrompt.rstrip() if isinstance(payload.systemPrompt, str) else None

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
        raise HTTPException(status_code=500, detail="Failed to upsert system prompt template.") from None

def _require_admin(credentials: HTTPBasicCredentials = Depends(basic_security)) -> None:
    """
    Basic-auth gate for admin endpoints.

    Browser-friendly: opening the URL prompts for username/password.
    """
    if not config.ADMIN_BASIC_PASSWORD:
        logger.error("ADMIN_BASIC_PASSWORD is not configured. env_diag=%s", _safe_env_diagnostics())
        raise HTTPException(status_code=500, detail="ADMIN_BASIC_PASSWORD is not configured on the server.")

    username_ok = secrets.compare_digest(credentials.username or "", config.ADMIN_BASIC_USER)
    password_ok = secrets.compare_digest(credentials.password or "", config.ADMIN_BASIC_PASSWORD)
    if not (username_ok and password_ok):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})


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
        logger.error("ADMIN_BASIC_PASSWORD is not configured. env_diag=%s", _safe_env_diagnostics())
        raise HTTPException(status_code=500, detail="ADMIN_BASIC_PASSWORD is not configured on the server.")

    password_ok = secrets.compare_digest(credentials.password or "", config.ADMIN_BASIC_PASSWORD)
    if not password_ok:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": 'Basic realm="InstantPaper Admin (password required)"'},
        )

    email = (credentials.username or "").strip()
    if not email or "@" not in email:
        # Use 401 so the browser re-prompts, with a realm hint that username must be the target email.
        raise HTTPException(
            status_code=401,
            detail="Basic auth username must be the user's email.",
            headers={"WWW-Authenticate": 'Basic realm="InstantPaper Approve: username = user email"'},
        )
    return email


@app.get("/api/admin/approve")
async def admin_set_user_approved(
    email: str,
    approved: bool = True,
    _: None = Depends(_require_admin),
):
    """
    Approve/revoke a Google user by setting a Firebase Auth custom claim.

    Usage (browser will prompt for basic auth):
      /api/admin/approve?email=user@gmail.com&approved=true
    """
    try:
        result = await firebase_service.set_user_approved_by_email(email=email, approved=approved)
        return {
            "status": "ok",
            "email": result.get("email"),
            "uid": result.get("uid"),
            "approved": result.get("approved"),
            "note": "User must sign out/in (or refresh token) for the claim to take effect.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update user approval.") from None


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
        result = await firebase_service.set_user_approved_by_email(email=email, approved=True)
        return {
            "status": "ok",
            "email": result.get("email"),
            "uid": result.get("uid"),
            "approved": True,
            "note": "User must sign out/in (or refresh token) for the claim to take effect.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update user approval.") from None


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
        result = await firebase_service.set_user_approved_by_email(email=email, approved=False)
        return {
            "status": "ok",
            "email": result.get("email"),
            "uid": result.get("uid"),
            "approved": False,
            "note": "User must sign out/in (or refresh token) for the claim to take effect.",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update user approval.") from None


@app.get("/approve", response_class=HTMLResponse)
async def approve_page(
    email: str | None = None,
    approved: bool = True,
    _: None = Depends(_require_admin),
):
    """
    Browser-friendly approval page (Basic Auth protected).

    Uses POST (form) so email doesn't end up in the URL.
    """
    return _render_approve_page(email=email, approved=approved, message_html="")


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
    approved_raw = ((params.get("approved", ["true"]) or ["true"])[0] or "true").strip().lower()
    approved = approved_raw in {"true", "1", "yes", "on"}

    message_html = ""
    if email is not None and email.strip():
        try:
            result = await firebase_service.set_user_approved_by_email(email=email, approved=approved)
            state = "APPROVED" if result.get("approved") else "REVOKED"
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

    return _render_approve_page(email=email, approved=approved, message_html=message_html)


def _render_approve_page(email: str | None, approved: bool, message_html: str) -> HTMLResponse:
    selected_true = "selected" if approved else ""
    selected_false = "selected" if not approved else ""

    html_doc = f"""
    <!doctype html>
    <html lang="de">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>InstantPaper - User Approval</title>
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
          <h1>User Approval</h1>
          <form method="post" action="/approve">
            <label for="email">Google Email</label>
            <input id="email" name="email" type="email" placeholder="name@gmail.com" required value="{html_lib.escape(email or "")}" />
            <div class="row">
              <div>
                <label for="approved" style="margin:0 0 6px;">Status</label>
                <select id="approved" name="approved">
                  <option value="true" {selected_true}>approved</option>
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
        decoded_token = await firebase_service.verify_token(request.idToken)
        if not bool(decoded_token.get("approved") is True):
            raise HTTPException(status_code=403, detail="Account not authorized")

        # Create session cookie (14 days)
        session_cookie = await firebase_service.create_session_cookie(request.idToken, expires_in_days=14)

        return {
            "sessionCookie": session_cookie,
            "expiresIn": 14 * 24 * 60 * 60  # 14 days in seconds
        }
    except Exception as e:
        logger.error(f"Failed to create session cookie: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail=f"Failed to create session: {str(e)}"
        )


@app.post("/api/auth/revoke")
async def revoke_session(request: RevokeSessionRequest):
    """
    Revoke a session by revoking all refresh tokens for the user.
    """
    try:
        # Decode session cookie to get user ID (don't verify, just decode)
        # We decode without verification since we just need the UID
        parts = request.sessionCookie.split('.')
        if len(parts) >= 2:
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + '=='))
            user_id = payload.get('uid')

            if user_id:
                # Revoke all refresh tokens for this user
                auth.revoke_refresh_tokens(user_id)
                logger.info(f"Revoked refresh tokens for user {user_id}")

        return {"status": "revoked"}
    except Exception as e:
        logger.error(f"Failed to revoke session: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to revoke session: {str(e)}"
        )


@app.get("/test/auth")
async def test_auth(user_id: str = Depends(verify_firebase_token)):
    """
    Test endpoint to verify Firebase authentication

    Requires Authorization header with Firebase ID token
    """
    return {
        "message": "Authentication successful",
        "user_id": user_id
    }


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
    logger.info(f"Processing Quelle {request.quelle_id} for user {user_id} (Kapitel {request.kapitel_id}, run {request.run_id})")

    # Block duplicate processing while already running (prevents double charges + weird UI states).
    existing_result = await firebase_service.get_run_result(user_id, request.kapitel_id, request.run_id, request.quelle_id)
    if existing_result and existing_result.get("status") == "running":
        raise HTTPException(status_code=400, detail="Diese Quelle wird bereits verarbeitet.")

    run_doc = await firebase_service.get_run(user_id, request.kapitel_id, request.run_id)
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
            await firebase_service.mark_result_error(
                user_id=user_id,
                kapitel_id=request.kapitel_id,
                run_id=request.run_id,
                quelle_id=request.quelle_id,
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
    logger.info(f"Combining run {request.run_id} for user {user_id} (Kapitel {request.kapitel_id})")

    existing_combined = await firebase_service.get_combined_result(user_id, request.kapitel_id, request.run_id)
    if existing_combined:
        existing_status = (existing_combined.get("status") or "").strip()
        existing_content = (existing_combined.get("content") or "").strip()
        if existing_status == "running":
            raise HTTPException(status_code=400, detail="Kombination läuft bereits.")
        if existing_content and (existing_status == "success" or not existing_status):
            raise HTTPException(status_code=400, detail="Kombinierter Text existiert bereits für diesen Run.")

    run_doc = await firebase_service.get_run(user_id, request.kapitel_id, request.run_id)
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
            await firebase_service.mark_artifact_error(
                user_id=user_id,
                kapitel_id=request.kapitel_id,
                run_id=request.run_id,
                artifact_id="combined",
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

    existing_shortened = await firebase_service.get_shortened_result(user_id, request.kapitel_id, request.run_id)
    if existing_shortened and (existing_shortened.get("status") or "").strip() == "running":
        raise HTTPException(status_code=400, detail="Text wird bereits gekürzt.")

    # Create/merge placeholder artifact doc immediately so the UI can show running/error state.
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
            await firebase_service.mark_artifact_error(
                user_id=user_id,
                kapitel_id=request.kapitel_id,
                run_id=request.run_id,
                artifact_id="shortened",
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

        existing_lesefluss = await firebase_service.get_lesefluss_result(user_id, request.kapitel_id, request.run_id)
        if existing_lesefluss and (existing_lesefluss.get("status") or "").strip() == "running":
            raise HTTPException(status_code=400, detail="Lesefluss wird bereits erstellt.")

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
                await firebase_service.mark_artifact_error(
                    user_id=user_id,
                    kapitel_id=request.kapitel_id,
                    run_id=request.run_id,
                    artifact_id="lesefluss",
                    key_source=key_source,
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
        raise HTTPException(status_code=500, detail="Failed to queue refinement request.") from exc

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
        raise HTTPException(status_code=500, detail="Failed to queue refinement request.") from exc

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
        raise HTTPException(status_code=500, detail="Failed to queue refinement request.") from exc

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
        raise HTTPException(status_code=500, detail="Failed to queue refinement request.") from exc

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
