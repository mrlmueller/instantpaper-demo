from pydantic import BaseModel, Field


class ProcessPaperResponse(BaseModel):
    """Response model for paper processing result"""

    result_id: str = Field(..., description="ID of the saved result document")
    paper_id: str = Field(..., description="ID of the source paper")
    result_content: str = Field(..., description="AI-generated content")
    model_used: str = Field(..., description="OpenAI model that was used")
    tokens_used: int = Field(..., description="Total tokens consumed")
    created_at: str = Field(..., description="ISO timestamp of when the result was created")

    class Config:
        json_schema_extra = {
            "example": {
                "result_id": "xyz789",
                "paper_id": "abc123",
                "result_content": "Summary of the paper...",
                "model_used": "gpt-4o-mini",
                "tokens_used": 1523,
                "created_at": "2025-01-15T10:30:00Z"
            }
        }
