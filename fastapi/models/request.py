from pydantic import BaseModel, Field
from typing import Literal, List


class ProcessQuelleRequest(BaseModel):
    """Request model for processing a Quelle with OpenAI"""

    quelle_id: str = Field(..., description="ID of the Quelle to process")
    kapitel_id: str = Field(..., description="Kapitel ID this run belongs to")
    run_id: str = Field(..., description="Kapitel run ID for grouping results")
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


class AdoptCombinedRequest(BaseModel):
    """Request model for adopting a single Quelle result as the combined text (no LLM call)."""

    kapitel_id: str = Field(..., description="Kapitel ID for the run")
    run_id: str = Field(..., description="Run ID to adopt the combined text for")
    quelle_id: str = Field(..., description="Quelle ID / result document ID to adopt")


class ShortenKapitelRequest(BaseModel):
    """Request model for shortening and deduplicating a Kapitel text"""

    kapitel_id: str = Field(..., description="ID of the Kapitel to shorten")
    run_id: str = Field(..., description="Run ID that contains the text to shorten")
    context_kapitel_ids: List[str] = Field(
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
    context_kapitel_ids: List[str] = Field(
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


class GenerateGliederungRequest(BaseModel):
    """Request model for creating a Gliederung (outline) draft for a project."""

    projekt_id: str = Field(..., description="Project ID this draft belongs to")
    aufgabenstellung: str = Field(..., description="Task description for the paper", min_length=10)
    gliederung_studienbrief_mit_seiten: str = Field(
        default="",
        description="Optional: Studienbrief outline with chapter numbers/titles/pages (free text)",
    )
    extra_kontext: str = Field(
        default="",
        description="Optional: extra context / constraints (free text)",
    )
    model: Literal["gpt-5-nano", "gpt-5-mini", "gpt-5.2"] = Field(
        default="gpt-5.2",
        description="OpenAI model to use for generating the outline draft",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "projekt_id": "proj123",
                "aufgabenstellung": "Analyse der Auswirkungen von KI auf die Arbeitswelt",
                "gliederung_studienbrief_mit_seiten": "1 Einführung (S. 1–10)\n2 Grundlagen (S. 11–45)",
                "extra_kontext": "Schreibe auf Deutsch. Keine konkreten Modelle nennen, außer explizit gefordert.",
                "model": "gpt-5.2",
            }
        }


class RefineGliederungRequest(BaseModel):
    """Request model for refining an existing Gliederung draft with a user instruction."""

    draft_id: str = Field(..., description="Gliederung draft ID to refine")
    message: str = Field(..., description="Requested changes / instruction", min_length=1)

    class Config:
        json_schema_extra = {
            "example": {
                "draft_id": "draft123",
                "message": "Bitte Kapitel 2 und 3 vertauschen und Kapitel 3.2 kürzen.",
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


class RefineShortenedInitRequest(BaseModel):
    """Request model for initializing the text refinement flow for a shortened text."""

    kapitel_id: str = Field(..., description="Kapitel ID")
    run_id: str = Field(..., description="Run ID that contains the shortened text")


class RefineShortenedRequest(BaseModel):
    """Request model for refining a shortened text (text refinement flow)."""

    kapitel_id: str = Field(..., description="Kapitel ID")
    run_id: str = Field(..., description="Run ID that contains the shortened text")
    parent_version_id: str = Field(..., description="Version ID to refine from")
    user_message: str = Field(..., description="User instruction for refinement", min_length=1)


class RefineLeseflussInitRequest(BaseModel):
    """Request model for initializing the text refinement flow for a lesefluss text."""

    kapitel_id: str = Field(..., description="Kapitel ID")
    run_id: str = Field(..., description="Run ID that contains the lesefluss text")


class RefineLeseflussRequest(BaseModel):
    """Request model for refining a lesefluss text (text refinement flow)."""

    kapitel_id: str = Field(..., description="Kapitel ID")
    run_id: str = Field(..., description="Run ID that contains the lesefluss text")
    parent_version_id: str = Field(..., description="Version ID to refine from")
    user_message: str = Field(..., description="User instruction for refinement", min_length=1)


class RefineResultInitRequest(BaseModel):
    """Request model for initializing the text refinement flow for a Quelle result text."""

    kapitel_id: str = Field(..., description="Kapitel ID")
    run_id: str = Field(..., description="Run ID that contains the Quelle results")
    quelle_id: str = Field(..., description="Quelle ID / result document ID to refine")


class RefineResultRequest(BaseModel):
    """Request model for refining a Quelle result text (text refinement flow)."""

    kapitel_id: str = Field(..., description="Kapitel ID")
    run_id: str = Field(..., description="Run ID that contains the Quelle results")
    quelle_id: str = Field(..., description="Quelle ID / result document ID to refine")
    parent_version_id: str = Field(..., description="Version ID to refine from")
    user_message: str = Field(..., description="User instruction for refinement", min_length=1)


class ExportDocxRequest(BaseModel):
    """Request model for exporting improved Kapitel texts (lesefluss) to a DOCX."""

    projekt_id: str = Field(..., description="Project ID this export belongs to")
    include_footnotes: bool = Field(
        default=True,
        description="Whether citations should be extracted and added as DOCX footnotes",
    )
    selection: Literal["all", "selected"] = Field(
        default="all",
        description="Whether the export includes all available Kapitels or a selected subset",
    )
    kapitel_ids: List[str] = Field(
        ...,
        description="Kapitel IDs to include (only Kapitels with lesefluss text should be provided)",
        min_length=1,
    )


class QuellenFinderSourcesSearchRequest(BaseModel):
    """Request model for running Quellen-Finder paper search for a single Kapitel."""

    projekt_id: str = Field(..., description="Project ID this Quellen-Finder run belongs to")
    kapitel_id: str = Field(..., description="Kapitel ID to run paper search for")
    blueprint_model: Literal["gpt-5-nano", "gpt-5-mini", "gpt-5.2"] = Field(
        default="gpt-5-mini",
        description="Model to use for Stage B (ChapterBlueprint generation)",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "projekt_id": "proj123",
                "kapitel_id": "kap456",
                "blueprint_model": "gpt-5-mini",
            }
        }


class QuellenFinderPdfScanRequest(BaseModel):
    """Request model for running Quellen-Finder PDF scan for a single Kapitel and selected project PDFs."""

    projekt_id: str = Field(..., description="Project ID this Quellen-Finder run belongs to")
    kapitel_id: str = Field(..., description="Kapitel ID to run PDF scan for")
    pdf_ids: List[str] = Field(..., description="Project PDF document IDs to scan", min_length=1)
    preprocess: bool = Field(default=True, description="Whether to run the LLM preprocess stage before PDF retrieval")

    class Config:
        json_schema_extra = {
            "example": {
                "projekt_id": "proj123",
                "kapitel_id": "kap456",
                "pdf_ids": ["pdfA", "pdfB"],
                "preprocess": True,
            }
        }


class QuellenFinderPdfExtractRequest(BaseModel):
    """Request model for extracting/highlighting a PDF section from a Stage-2 hit or Stage-3 section."""

    projekt_id: str = Field(..., description="Project ID this Quellen-Finder run belongs to")
    run_id: str = Field(..., description="Research run ID (kind=pdf_scan)")
    stage: Literal["stage2", "stage3"] = Field(..., description="Which run subcollection to read the doc from")
    doc_id: str = Field(..., description="Stage document ID to extract from")

    class Config:
        json_schema_extra = {
            "example": {
                "projekt_id": "proj123",
                "run_id": "run456",
                "stage": "stage2",
                "doc_id": "stageDoc789",
            }
        }
