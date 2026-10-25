"""HTTP request and response models."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.retrieval import RetrievalMethod


class SearchRequest(BaseModel):
    """Search parameters accepted by the HTTP API."""
    query: str = Field(min_length=1)
    limit: int | None = Field(default=None, ge=1)
    method: RetrievalMethod | None = None
    window: int | None = Field(default=None, ge=0)


class AskRequest(SearchRequest):
    """Search parameters and optional generation-provider overrides."""
    generation_provider: Literal["openai", "deepseek", "ollama", "anthropic"] | None = None
    generation_model: str | None = Field(default=None, min_length=1, pattern=r"\S")


class ConversationTurnRequest(AskRequest):
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
    score: float | None


class CitationResponse(BaseModel):
    """A numbered citation to a retrieved source passage."""
    id: int
    source_id: str
    source_title: str
    source_locator: str
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
