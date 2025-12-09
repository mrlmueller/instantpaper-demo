from pydantic import BaseModel, Field
from typing import Literal


class ProcessQuelleRequest(BaseModel):
    """Request model for processing a Quelle with OpenAI"""

    quelle_id: str = Field(..., description="ID of the Quelle to process")
    kapitel_id: str = Field(..., description="Kapitel ID this run belongs to")
    run_id: str = Field(..., description="Kapitel run ID for grouping results")
    user_input: str = Field(..., description="User instructions for the AI", min_length=1)
    model: Literal["gpt-5-nano", "gpt-5-mini", "gpt-5.1"] = Field(
        default="gpt-5.1",
        description="OpenAI model to use for processing"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "quelle_id": "abc123",
                "kapitel_id": "kap456",
                "run_id": "run789",
                "user_input": "Summarize the main points of this Quelle",
                "model": "gpt-5.1"
            }
        }


class CombineRunRequest(BaseModel):
    """Request model for combining multiple Quelle results in a run"""

    kapitel_id: str = Field(..., description="Kapitel ID for the run")
    run_id: str = Field(..., description="Run ID to combine results for")

    class Config:
        json_schema_extra = {
            "example": {
                "kapitel_id": "kap456",
                "run_id": "run789",
            }
        }
