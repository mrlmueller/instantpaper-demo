from pydantic import BaseModel, Field
from typing import Literal, List, Optional


TextGenerationModel = Literal[
    "gpt-5-nano", "gpt-5-mini", "gpt-5.4", "gpt-5.2",
    "claude-opus-4-6", "claude-sonnet-4-6",
]


class ProcessQuelleRequest(BaseModel):
    """Request model for processing a Quelle with OpenAI"""

    quelle_id: str = Field(..., description="ID of the Quelle to process")
    kapitel_id: str = Field(..., description="Kapitel ID this run belongs to")
    run_id: str = Field(..., description="Kapitel run ID for grouping results")
    model: TextGenerationModel = Field(
        default="gpt-5.4",
        description="OpenAI model to use for processing"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "quelle_id": "abc123",
                "kapitel_id": "kap456",
                "run_id": "run789",
                "model": "gpt-5.4"
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
    model: TextGenerationModel = Field(
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
    model: TextGenerationModel = Field(
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
    model: TextGenerationModel = Field(
        default="gpt-5.4",
        description="OpenAI model to use for generating the outline draft",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "projekt_id": "proj123",
                "aufgabenstellung": "Analyse der Auswirkungen von KI auf die Arbeitswelt",
                "gliederung_studienbrief_mit_seiten": "1 Einführung (S. 1–10)\n2 Grundlagen (S. 11–45)",
                "extra_kontext": "Schreibe auf Deutsch. Keine konkreten Modelle nennen, außer explizit gefordert.",
                "model": "gpt-5.4",
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


class ManualRefineCombinedRequest(BaseModel):
    """Request model for manually editing a combined text refinement version."""

    kapitel_id: str = Field(..., description="Kapitel ID")
    run_id: str = Field(..., description="Run ID that contains the combined text")
    parent_version_id: str = Field(..., description="Version ID to edit from")
    content: str = Field(..., description="Manually edited final text", min_length=1, max_length=140000)


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


class ManualRefineShortenedRequest(BaseModel):
    """Request model for manually editing a shortened text refinement version."""

    kapitel_id: str = Field(..., description="Kapitel ID")
    run_id: str = Field(..., description="Run ID that contains the shortened text")
    parent_version_id: str = Field(..., description="Version ID to edit from")
    content: str = Field(..., description="Manually edited final text", min_length=1, max_length=140000)


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


class ManualRefineLeseflussRequest(BaseModel):
    """Request model for manually editing a lesefluss text refinement version."""

    kapitel_id: str = Field(..., description="Kapitel ID")
    run_id: str = Field(..., description="Run ID that contains the lesefluss text")
    parent_version_id: str = Field(..., description="Version ID to edit from")
    content: str = Field(..., description="Manually edited final text", min_length=1, max_length=140000)


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


class ManualRefineResultRequest(BaseModel):
    """Request model for manually editing a Quelle result refinement version."""

    kapitel_id: str = Field(..., description="Kapitel ID")
    run_id: str = Field(..., description="Run ID that contains the Quelle results")
    quelle_id: str = Field(..., description="Quelle ID / result document ID to edit")
    parent_version_id: str = Field(..., description="Version ID to edit from")
    content: str = Field(..., description="Manually edited final text", min_length=1, max_length=140000)


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


class QuellenFinderTwoLaneStartRequest(BaseModel):
    """Request model for running Quellen-Finder two-lane paper retrieval for a single Kapitel."""

    projekt_id: str = Field(..., description="Project ID this Quellen-Finder run belongs to")
    kapitel_id: str = Field(..., description="Kapitel ID to run two-lane source retrieval for")

    planner_model: TextGenerationModel = Field(
        default="gpt-5-mini",
        description="Model to use for Phase B (facet planner)",
    )
    openalex_query_builder_model: TextGenerationModel = Field(
        default="gpt-5-mini",
        description="Model to use for Phase C (OpenAlex query builder)",
    )
    s2_query_builder_model: TextGenerationModel = Field(
        default="gpt-5-mini",
        description="Model to use for Phase C (Semantic Scholar query builder)",
    )
    rerank_model: Literal["gpt-5-nano", "gpt-5-mini"] = Field(
        default="gpt-5-nano",
        description="Model to use for Phase I reranking (gpt-5.4 disabled for cost)",
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Embedding model used in Phase F",
    )

    reasoning_effort: Literal["low", "medium", "high"] = Field(
        default="high",
        description="Reasoning effort for Phase B/C schema calls",
    )
    rerank_concurrency: int = Field(default=20, ge=1, le=50, description="Concurrent rerank calls in Phase I")

    class Config:
        json_schema_extra = {
            "example": {
                "projekt_id": "proj123",
                "kapitel_id": "kap456",
                "planner_model": "gpt-5-mini",
                "openalex_query_builder_model": "gpt-5-mini",
                "s2_query_builder_model": "gpt-5-mini",
                "rerank_model": "gpt-5-nano",
                "embedding_model": "text-embedding-3-small",
                "reasoning_effort": "high",
                "rerank_concurrency": 20,
            }
        }


class QuellenFinderTwoLaneCancelRequest(BaseModel):
    """Request model for requesting cancellation of a two-lane Quellen-Finder run."""

    projekt_id: str = Field(..., description="Project ID this Quellen-Finder run belongs to")
    run_id: str = Field(..., description="Research run ID (kind=sources_two_lane)")

    class Config:
        json_schema_extra = {"example": {"projekt_id": "proj123", "run_id": "run456"}}


class QuellenFinderPdfScanRequest(BaseModel):
    """Request model for running Quellen-Finder PDF scan for one or more Kapitels and selected project PDFs."""

    projekt_id: str = Field(..., description="Project ID this Quellen-Finder run belongs to")
    kapitel_ids: List[str] = Field(
        default_factory=list,
        description="Ordered Kapitel IDs to run PDF scan for",
        min_length=0,
    )
    kapitel_id: Optional[str] = Field(
        default=None,
        description="Legacy single Kapitel ID input; normalized into kapitel_ids server-side",
    )
    confirm_duplicate_kapitel_run: bool = Field(
        default=False,
        description="Explicit confirmation required to start another PDF scan while any requested Kapitel already has a queued or running scan",
    )
    pdf_ids: List[str] = Field(
        ...,
        description="Project PDF document IDs to scan (max 30 per run)",
        min_length=1,
    )

    class Config:
        json_schema_extra = {
            "example": {
                "projekt_id": "proj123",
                "kapitel_ids": ["kap456", "kap789"],
                "confirm_duplicate_kapitel_run": False,
                "pdf_ids": ["pdfA", "pdfB"],
            }
        }


class QuellenFinderPdfScanCancelRequest(BaseModel):
    """Request model for requesting cancellation of a PDF scan run."""

    projekt_id: str = Field(..., description="Project ID this Quellen-Finder run belongs to")
    run_id: str = Field(..., description="Research run ID (kind=pdf_scan)")

    class Config:
        json_schema_extra = {"example": {"projekt_id": "proj123", "run_id": "run456"}}


class QuellenFinderPdfExtractRequest(BaseModel):
    """Request model for extracting/highlighting a final PDF section from a PDF scan run."""

    projekt_id: str = Field(..., description="Project ID this Quellen-Finder run belongs to")
    run_id: str = Field(..., description="Research run ID (kind=pdf_scan)")
    chapter_id: Optional[str] = Field(
        default=None,
        description="Optional chapter ID for chapter-scoped PDF scan results",
    )
    pdf_doc_id: str = Field(..., description="PDF summary document ID inside the selected PDF-scan result view")
    section_doc_id: str = Field(..., description="Final section document ID inside the selected PDF-scan result view")

    class Config:
        json_schema_extra = {
            "example": {
                "projekt_id": "proj123",
                "run_id": "run456",
                "chapter_id": "kap456",
                "pdf_doc_id": "currency_bullion_and_accounts-d06d74cdba02",
                "section_doc_id": "currency_bullion_and_accounts-d06d74cdba02__cf857d73af6067fc",
            }
        }


class QuellenFinderProjectPdfDuplicateCheckRequest(BaseModel):
    """Request model for checking whether a project PDF is already uploaded."""

    projekt_id: str = Field(..., description="Project ID that owns the PDF library")
    filename: str = Field(..., description="Original filename of the candidate PDF")
    size: int = Field(..., description="File size in bytes", ge=0)
    page_count: Optional[int] = Field(default=None, description="Optional PDF page count", ge=1)
    file_hash: Optional[str] = Field(default=None, description="Optional SHA-256 hash of the PDF file")

    class Config:
        json_schema_extra = {
            "example": {
                "projekt_id": "proj123",
                "filename": "Ward-Perkins Fall of Rome End of Civilization.pdf",
                "size": 2318475,
                "page_count": 256,
                "file_hash": "8f2d1891a7f7b097c1fe5c7e8d9de79e6c95d6d95f96de4b0a3f8b9eb45af6e8",
            }
        }


class QuellenFinderProjectPdfColorUpdateRequest(BaseModel):
    """Request model for updating a project PDF color."""

    projekt_id: str = Field(..., description="Project ID that owns the PDF library")
    pdf_id: str = Field(..., description="PDF document ID in the project library")
    color: Optional[Literal["blue", "green", "teal", "lavender", "cream", "peach", "rose"]] = Field(
        default=None,
        description="Optional explicit color for grouping and display; null clears the manual color.",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "projekt_id": "proj123",
                "pdf_id": "pdf_8f2d1891a7f7b097c1fe5c7e8d9de79e6c95d6d95f96de4b0a3f8b9eb45af6e8",
                "color": "blue",
            }
        }
