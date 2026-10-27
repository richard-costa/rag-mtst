"""HTTP request and response models."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.retrieval import RetrievalMethod


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int | None = Field(
        default=None, ge=1,
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
        default=None, ge=0,
        description=(
            "Number of neighboring chunks on each side of a seed; used only by the window method. "
            "Null or omitted uses the server-configured window."
        ),
    )


class AskRequest(SearchRequest):
    generation_provider: Literal["openai", "deepseek", "ollama", "anthropic"] | None = None
    generation_model: str | None = Field(default=None, min_length=1, pattern=r"\S")


class ConversationTurnRequest(AskRequest):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, pattern=r"\S")


class ConversationResponse(BaseModel):
    id: UUID
    created_at: datetime
    updated_at: datetime


class SourceResponse(BaseModel):
    id: str
    status: Literal["pending", "running", "unchanged"]
    job_id: str | None
    status_url: str | None


class JobResponse(BaseModel):
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
    answer: str
    matches: list[SearchMatchResponse]
    citations: list[CitationResponse]


class MessageResponse(BaseModel):
    id: UUID
    sequence: int
    role: Literal["user", "assistant"]
    content: str
    citations: list[CitationResponse]
    created_at: datetime
