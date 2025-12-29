from fastapi import Header, HTTPException, Cookie, Depends
from services.firebase_service import firebase_service
from utils.config import config
import logging

logger = logging.getLogger(__name__)

def _is_approved(decoded_token: dict) -> bool:
    # Firebase Admin returns custom claims as top-level keys in decoded tokens/session cookies.
    return bool(decoded_token.get("approved") is True)


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

    # Try session cookie first (preferred)
    if __session:
        try:
            decoded_token = await firebase_service.verify_session_cookie(__session)
            user_id = decoded_token['uid']
            if not _is_approved(decoded_token):
                raise HTTPException(status_code=403, detail="Account not authorized")
            logger.debug(f"Session cookie verified for user {user_id}")
            return user_id
        except Exception as e:
            logger.warning(f"Session cookie verification failed: {str(e)}")
            # Continue to try Authorization header

    # Fall back to ID token in Authorization header (backwards compatibility)
    if not authorization:
        logger.warning("No session cookie or Authorization header provided")
        raise HTTPException(
            status_code=401,
            detail="Missing authentication credentials"
        )

    if not authorization.startswith("Bearer "):
        logger.warning("Invalid Authorization header format")
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'"
        )

    # Extract token from "Bearer <token>"
    token = authorization.split("Bearer ")[1]

    try:
        # Verify ID token using Firebase Admin SDK
        decoded_token = await firebase_service.verify_token(token)
        user_id = decoded_token['uid']

        if not _is_approved(decoded_token):
            raise HTTPException(status_code=403, detail="Account not authorized")

        logger.debug(f"ID token verified successfully for user {user_id}")
        return user_id

    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        logger.error(f"Token verification failed: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail=f"Invalid or expired token: {str(e)}"
        )


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
