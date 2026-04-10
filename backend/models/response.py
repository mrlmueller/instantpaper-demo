from pydantic import BaseModel, Field
from typing import Optional


class ProcessQuelleResponse(BaseModel):
    """Response model for Quelle processing result"""

    result_id: str = Field(..., description="ID of the saved result document")
    quelle_id: str = Field(..., description="ID of the source Quelle")
    kapitel_id: Optional[str] = Field(None, description="Kapitel ID for the run")
    run_id: Optional[str] = Field(None, description="Run ID within the Kapitel")
    result_content: str = Field(..., description="AI-generated content")
    model_used: str = Field(..., description="OpenAI model that was used")
    tokens_used: int = Field(..., description="Total tokens consumed")
    created_at: str = Field(..., description="ISO timestamp of when the result was created")

    class Config:
        json_schema_extra = {
            "example": {
                "result_id": "xyz789",
                "quelle_id": "abc123",
                "kapitel_id": "kap456",
                "run_id": "run789",
                "result_content": "Summary of the Quelle...",
                "model_used": "gpt-5.4",
                "tokens_used": 1523,
                "created_at": "2025-01-15T10:30:00Z"
            }
        }
