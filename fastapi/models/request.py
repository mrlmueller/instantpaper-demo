from pydantic import BaseModel, Field
from typing import Literal


class ProcessPaperRequest(BaseModel):
    """Request model for processing a paper with OpenAI"""

    paper_id: str = Field(..., description="ID of the paper to process")
    user_input: str = Field(..., description="User instructions for the AI", min_length=1)
    model: Literal["gpt-5-nano", "gpt-5-mini", "gpt-5.1"] = Field(
        default="gpt-5-mini",
        description="OpenAI model to use for processing"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "paper_id": "abc123",
                "user_input": "Summarize the main points of this paper",
                "model": "gpt-5-mini"
            }
        }
