from fastapi import Header, HTTPException, Cookie, Depends
from services.firebase_service import firebase_service
from utils.config import config
import logging

logger = logging.getLogger(__name__)

def _is_approved(decoded_token: dict) -> bool:
    # Firebase Admin returns custom claims as top-level keys in decoded tokens/session cookies.
    return bool(decoded_token.get("approved") is True)

def _can_duplicate_system_prompts(decoded_token: dict) -> bool:
    return bool(decoded_token.get("canDuplicateSystemPrompts") is True)


async def verify_firebase_token_decoded(
    authorization: str = Header(None),
    __session: str = Cookie(None),
) -> dict:
    """
    Dependency to verify Firebase token (session cookie or ID token) and return decoded claims.

    Enforces the `approved` custom claim.
    """
    # Try session cookie first (preferred)
    if __session:
        try:
            decoded_token = await firebase_service.verify_session_cookie(__session)
            if not _is_approved(decoded_token):
                raise HTTPException(status_code=403, detail="Account not authorized")
            return decoded_token
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Session cookie verification failed: {str(e)}")
            # Continue to try Authorization header

    if not authorization:
        logger.warning("No session cookie or Authorization header provided")
        raise HTTPException(status_code=401, detail="Missing authentication credentials")

    if not authorization.startswith("Bearer "):
        logger.warning("Invalid Authorization header format")
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'",
        )

    token = authorization.split("Bearer ")[1]
    try:
        decoded_token = await firebase_service.verify_token(token)
        if not _is_approved(decoded_token):
            raise HTTPException(status_code=403, detail="Account not authorized")
        return decoded_token
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token verification failed: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {str(e)}")


async def verify_firebase_token(
    authorization: str = Header(None),
    __session: str = Cookie(None)  # Check for session cookie
) -> str:
    """
    Dependency to verify Firebase token (session cookie or ID token).

    Checks session cookie first, then Authorization header for backwards compatibility.

    Args:
        authorization: Authorization header value (e.g., "Bearer <token>")
        __session: Session cookie value

    Returns:
        str: User ID extracted from verified token

    Raises:
        HTTPException: 401 if token is missing or invalid
    """
    decoded_token = await verify_firebase_token_decoded(authorization=authorization, __session=__session)
    user_id = decoded_token["uid"]
    logger.debug(f"Firebase token verified for user {user_id}")
    return user_id


async def verify_firebase_token_any_user(
    authorization: str = Header(None),
    __session: str = Cookie(None),
) -> str:
    """
    Dependency to verify Firebase auth (session cookie or ID token) without enforcing `approved`.

    Intended for admin allowlist checks to avoid self-lockout if `approved` is misconfigured.
    """
    # Try session cookie first (preferred)
    if __session:
        try:
            decoded_token = await firebase_service.verify_session_cookie(__session)
            user_id = decoded_token["uid"]
            logger.debug(f"Session cookie verified for user {user_id}")
            return user_id
        except Exception as e:
            logger.warning(f"Session cookie verification failed: {str(e)}")
            # Continue to try Authorization header

    # Fall back to ID token in Authorization header
    if not authorization:
        logger.warning("No session cookie or Authorization header provided")
        raise HTTPException(status_code=401, detail="Missing authentication credentials")

    if not authorization.startswith("Bearer "):
        logger.warning("Invalid Authorization header format")
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'",
        )

    token = authorization.split("Bearer ")[1]
    try:
        decoded_token = await firebase_service.verify_token(token)
        user_id = decoded_token["uid"]
        logger.debug(f"ID token verified successfully for user {user_id}")
        return user_id
    except Exception as e:
        logger.error(f"Token verification failed: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {str(e)}")


async def verify_admin_user(user_id: str = Depends(verify_firebase_token_any_user)) -> str:
    """
    Dependency to ensure the authenticated user is an admin.

    Admins are configured via the `ADMIN_UIDS` env var (comma-separated Firebase Auth UIDs).
    """
    if not config.ADMIN_UIDS:
        logger.error("ADMIN_UIDS is not configured; denying admin access.")
        raise HTTPException(status_code=500, detail="Admin access is not configured on the server.")

    if user_id not in config.ADMIN_UIDS:
        raise HTTPException(status_code=403, detail="Admin access denied.")

    return user_id


async def verify_system_prompt_export_user(decoded_token: dict = Depends(verify_firebase_token_decoded)) -> str:
    """
    Dependency to ensure the authenticated user may duplicate server-only system prompts.
    """
    user_id = decoded_token.get("uid")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token (missing uid).")

    # Do not trust decoded token claims for this permission: they can stay "true" until the client refreshes.
    # Use Firestore `users/{uid}.canDuplicateSystemPrompts` so revocations take effect immediately.
    try:
        user_doc = await firebase_service.get_user_doc(str(user_id))
    except Exception:
        raise HTTPException(status_code=403, detail="System prompt export not allowed.") from None

    if not bool((user_doc or {}).get("canDuplicateSystemPrompts") is True):
        raise HTTPException(status_code=403, detail="System prompt export not allowed.")
    return str(user_id)
