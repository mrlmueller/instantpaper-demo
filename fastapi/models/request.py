from pydantic import BaseModel, Field
from typing import Literal


class ProcessQuelleRequest(BaseModel):
    """Request model for processing a Quelle with OpenAI"""

    quelle_id: str = Field(..., description="ID of the Quelle to process")
    kapitel_id: str = Field(..., description="Kapitel ID this run belongs to")
    run_id: str = Field(..., description="Kapitel run ID for grouping results")
    user_input: str = Field(..., description="User instructions for the AI", min_length=1)
    model: Literal["gpt-5-nano", "gpt-5-mini", "gpt-5.2"] = Field(
        default="gpt-5.2",
        description="OpenAI model to use for processing"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "quelle_id": "abc123",
                "kapitel_id": "kap456",
                "run_id": "run789",
                "user_input": "Summarize the main points of this Quelle",
                "model": "gpt-5.2"
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


class ShortenKapitelRequest(BaseModel):
    """Request model for shortening and deduplicating a Kapitel text"""

    kapitel_id: str = Field(..., description="ID of the Kapitel to shorten")
    run_id: str = Field(..., description="Run ID that contains the text to shorten")
    context_kapitel_ids: list[str] = Field(
        ...,
        description="IDs of other Kapitels to use for context (will be summarized)",
        min_length=1
    )
    model: Literal["gpt-5-nano", "gpt-5-mini", "gpt-5.2"] = Field(
        default="gpt-5-nano",
        description="OpenAI model to use for summarization and shortening"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "kapitel_id": "kap123",
                "run_id": "run456",
                "context_kapitel_ids": ["kap789", "kap012", "kap345"],
                "model": "gpt-5-nano"
            }
        }


class LeseflussKapitelRequest(BaseModel):
    """Request model for improving reading flow (Lese Fluss) of a Kapitel text"""

    kapitel_id: str = Field(..., description="ID of the Kapitel to improve reading flow for")
    run_id: str = Field(..., description="Run ID that contains the shortened text")
    context_kapitel_ids: list[str] = Field(
        ...,
        description="IDs of other Kapitels to use for context (will be summarized)",
        min_length=1
    )
    aufgabenstellung: str = Field(
        ...,
        description="Task description for the entire paper",
        min_length=10
    )
    model: Literal["gpt-5-nano", "gpt-5-mini", "gpt-5.2"] = Field(
        default="gpt-5-nano",
        description="OpenAI model to use for improving reading flow"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "kapitel_id": "kap123",
                "run_id": "run456",
                "context_kapitel_ids": ["kap789", "kap012", "kap345"],
                "aufgabenstellung": "Analyse der Auswirkungen von KI auf die Arbeitswelt",
                "model": "gpt-5-nano"
            }
        }


class RefineCombinedInitRequest(BaseModel):
    """Request model for initializing the text refinement flow for a combined text."""

    kapitel_id: str = Field(..., description="Kapitel ID")
    run_id: str = Field(..., description="Run ID that contains the combined text")


class RefineCombinedRequest(BaseModel):
    """Request model for refining a combined text (text refinement flow)."""

    kapitel_id: str = Field(..., description="Kapitel ID")
    run_id: str = Field(..., description="Run ID that contains the combined text")
    parent_version_id: str = Field(..., description="Version ID to refine from")
    user_message: str = Field(..., description="User instruction for refinement", min_length=1)
