from fastapi import FastAPI, Depends, BackgroundTasks, status, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime
from utils.config import config
from middleware.auth import verify_firebase_token
from models.request import (
    ProcessQuelleRequest,
    CombineRunRequest,
    ShortenKapitelRequest,
    LeseflussKapitelRequest,
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
from firebase_admin import auth
from pydantic import BaseModel
import logging
import base64
import json

from utils.logging_config import configure_logging

# Configure logging early (no file logs; keep uvicorn access logs).
configure_logging()

logger = logging.getLogger(__name__)


class SaveOpenAIKeyRequest(BaseModel):
    key: str


class CreateSessionRequest(BaseModel):
    idToken: str


class RevokeSessionRequest(BaseModel):
    sessionCookie: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for startup and shutdown"""
    # Startup
    logger.debug("Starting InstantPaper API server...")
    logger.debug(f"Debug mode: {config.DEBUG}")
    logger.debug(f"Allowed origins: {config.ALLOWED_ORIGINS}")

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
        "openai": "connected" if config.OPENAI_API_KEY else "not configured"
    }


@app.post("/api/auth/session")
async def create_session(request: CreateSessionRequest):
    """
    Exchange Firebase ID token for a session cookie.

    Returns session cookie and expiration time in seconds.
    """
    try:
        # Verify ID token first
        decoded_token = await firebase_service.verify_token(request.idToken)

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
        request: ProcessQuelleRequest containing quelle_id, user_input, model, kapitel_id, and run_id
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
        user_input=request.user_input,
        model=model_to_use,
    )

    async def _run_process_single_quelle() -> None:
        try:
            await quelle_service.process_single_quelle(
                user_id,
                request.quelle_id,
                request.kapitel_id,
                request.run_id,
                request.user_input,
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
