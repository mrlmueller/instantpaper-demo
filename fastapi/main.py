from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime
from utils.config import config
from middleware.auth import verify_firebase_token
from models.request import ProcessPaperRequest
from models.response import ProcessPaperResponse
from services.paper_service import paper_service
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO if config.DEBUG else logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('fastapi.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for startup and shutdown"""
    # Startup
    logger.info("Starting InstantPaper API server...")
    logger.info(f"Debug mode: {config.DEBUG}")
    logger.info(f"Allowed origins: {config.ALLOWED_ORIGINS}")

    yield

    # Shutdown (if needed in the future)
    logger.info("Shutting down InstantPaper API server...")


# Initialize FastAPI app with lifespan
app = FastAPI(
    title="InstantPaper API",
    version="1.0.0",
    description="FastAPI backend for processing papers with OpenAI",
    lifespan=lifespan
)

# Configure CORS to allow Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.ALLOWED_ORIGINS],
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
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


@app.post("/api/process", response_model=ProcessPaperResponse)
async def process_paper(
    request: ProcessPaperRequest,
    user_id: str = Depends(verify_firebase_token)
):
    """
    Process a paper with OpenAI

    Requires Authorization header with Firebase ID token.
    Fetches the paper, processes it with OpenAI, and saves the result.

    Args:
        request: ProcessPaperRequest containing paper_id, user_input, and model
        user_id: Extracted from verified Firebase token (dependency)

    Returns:
        ProcessPaperResponse with result details
    """
    logger.info(f"Processing paper {request.paper_id} for user {user_id}")

    # Process paper
    result = await paper_service.process_single_paper(
        user_id=user_id,
        paper_id=request.paper_id,
        user_input=request.user_input,
        model=request.model
    )

    # Return response
    return ProcessPaperResponse(
        result_id=result['result_id'],
        paper_id=request.paper_id,
        result_content=result['content'],
        model_used=result['model'],
        tokens_used=result['tokens'],
        created_at=datetime.utcnow().isoformat() + "Z"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=config.PORT,
        reload=config.DEBUG
    )
