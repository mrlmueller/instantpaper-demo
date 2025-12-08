from fastapi import Header, HTTPException
from services.firebase_service import firebase_service
import logging

logger = logging.getLogger(__name__)


async def verify_firebase_token(authorization: str = Header(None)) -> str:
    """
    Dependency to verify Firebase ID token from Authorization header

    Args:
        authorization: Authorization header value (e.g., "Bearer <token>")

    Returns:
        str: User ID extracted from verified token

    Raises:
        HTTPException: 401 if token is missing or invalid
    """
    if not authorization:
        logger.warning("Missing Authorization header")
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header"
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
        # Verify token using Firebase Admin SDK
        decoded_token = await firebase_service.verify_token(token)
        user_id = decoded_token['uid']

        logger.info(f"Token verified successfully for user {user_id}")
        return user_id

    except Exception as e:
        logger.error(f"Token verification failed: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail=f"Invalid or expired token: {str(e)}"
        )
