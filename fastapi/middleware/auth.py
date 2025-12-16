from fastapi import Header, HTTPException, Cookie
from services.firebase_service import firebase_service
import logging

logger = logging.getLogger(__name__)


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
            logger.info(f"Session cookie verified for user {user_id}")
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

        logger.info(f"ID token verified successfully for user {user_id}")
        return user_id

    except Exception as e:
        logger.error(f"Token verification failed: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail=f"Invalid or expired token: {str(e)}"
        )
