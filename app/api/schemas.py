"""HTTP request and response models."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.retrieval import RetrievalMethod


class SearchRequest(BaseModel):
    """Search parameters accepted by the HTTP API."""

    query: str = Field(min_length=1)
    limit: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Maximum matches for cosine, lexical, and hybrid methods. In window mode, "
            "counts seed matches before context expansion; the returned chunk count may exceed this limit. "
            "Null or omitted uses the server-configured limit."
        ),
    )
    method: RetrievalMethod | None = Field(
        default=None,
        description="Retrieval strategy. Null or omitted uses the server-configured method.",
    )
    window: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Number of neighboring chunks on each side of a seed; used only by the window method. "
            "Null or omitted uses the server-configured window."
        ),
    )


class GenerationRequest(SearchRequest):
    """Search parameters and optional generation-provider overrides."""

    generation_provider: Literal["openai", "deepseek", "ollama", "anthropic"] | None = (
        None
    )
    generation_model: str | None = Field(default=None, min_length=1, pattern=r"\S")


class HistoryMessage(BaseModel):
    """A prior question or answer supplied by the caller."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, pattern=r"\S")


class AskRequest(GenerationRequest):
    """Stateless answer request with optional caller-supplied history."""

    history: list[HistoryMessage] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Prior turns, oldest first, as complete user/assistant pairs. "
            "Used only as untrusted generation context: retrieval searches only the query, "
            "and history is never cited or stored. Older turns are dropped when they exceed "
            "the history share of the prompt budget."
        ),
    )

    @field_validator("history")
    @classmethod
    def _require_complete_turns(
        cls, history: list[HistoryMessage]
    ) -> list[HistoryMessage]:
        """Reject history that is not ordered user/assistant pairs.

        Args:
            history: Caller-supplied prior messages.

        Returns:
            The unchanged history.
        """
        roles = [message.role for message in history]
        if roles != ["user", "assistant"] * (len(roles) // 2):
            raise ValueError("history must contain complete user/assistant turns")
        return history


class ConversationTurnRequest(GenerationRequest):
    """Strict request payload for a conversation turn."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, pattern=r"\S")


class ConversationResponse(BaseModel):
    """Identifiers and timestamps for a conversation."""

    id: UUID
    created_at: datetime
    updated_at: datetime


class SourceResponse(BaseModel):
    """Source identifier and the associated ingestion status."""

    id: str
    status: Literal["pending", "running", "unchanged"]
    job_id: str | None
    status_url: str | None


class SourceDetailsResponse(BaseModel):
    """Stored source metadata and its current indexed chunk count."""

    id: UUID
    source_type: Literal["file", "url"]
    title: str
    reference: str
    mime_type: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class JobResponse(BaseModel):
    """Progress, timing, and status details of an ingestion job."""

    id: str
    source_id: str
    status: Literal["pending", "running", "completed", "failed"]
    stage: str | None
    progress: int | None
    processed: int | None
    total: int | None
    attempts: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    heartbeat_at: datetime | None
    finished_at: datetime | None


class SearchMatchResponse(BaseModel):
    """A retrieved passage and its similarity score."""

    source_id: str
    source_title: str
    chunk_index: int
    content: str
    score: float | None = Field(
        description=(
            "Method-specific ranking score for diagnostics, not a probability; "
            "scores are not comparable across methods. "
            "Null means the chunk was added as window context, not independently scored; "
            "it does not mean zero relevance."
        ),
    )


class CitationResponse(BaseModel):
    """A numbered citation to a retrieved source passage."""

    id: int
    source_id: str
    source_title: str
    source_reference: str = Field(
        description=(
            "Descriptive reference to the source's origin, such as a filename, URL, or external record identifier. "
            "Not necessarily unique or accessible; not used to fetch the source. "
            "File ingestion currently stores the filename."
        ),
    )
    chunk_index: int
    content: str
    truncated: bool


class AskResponse(BaseModel):
    """Generated answer with supporting matches and citations."""

    answer: str
    matches: list[SearchMatchResponse]
    citations: list[CitationResponse]


class MessageResponse(BaseModel):
    """A stored question or answer within a conversation."""

    id: UUID
    sequence: int
    role: Literal["user", "assistant"]
    content: str
    citations: list[CitationResponse]
    created_at: datetime
