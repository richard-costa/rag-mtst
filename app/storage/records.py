"""Persisted records and indexing inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Source:
    """Persisted source identity, origin, and extraction metadata."""

    id: UUID
    tenant_id: str
    source_type: str
    reference: str
    mime_type: str | None
    content_hash: str
    created_at: datetime
    updated_at: datetime

    @property
    def title(self) -> str:
        """Derive a display title without treating every origin as a file path.

        Returns:
            Reference basename for file sources; the full reference otherwise.
        """
        return (
            Path(self.reference).name if self.source_type == "file" else self.reference
        )


@dataclass(frozen=True, slots=True)
class Chunk:
    """Persisted source chunk with embedding and metadata."""

    id: UUID
    tenant_id: str
    source_id: UUID
    chunk_index: int
    page_number: int | None
    content: str
    embedding: Any | None
    metadata: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ChunkInput:
    """New chunk content, optional vector, and provenance metadata."""

    content: str
    metadata: dict[str, Any]
    page_number: int | None = None
    embedding: list[float] | None = None


@dataclass(frozen=True, slots=True)
class StoredChunk:
    """Retrieved chunk joined to its source metadata."""

    id: UUID
    source_id: UUID
    source_type: str
    source_reference: str
    chunk_index: int
    content: str
    metadata: dict[str, Any]

    @property
    def source_title(self) -> str:
        """Derive the source's display title from its origin reference.

        Returns:
            Reference basename for file sources; the full reference otherwise.
        """
        return (
            Path(self.source_reference).name
            if self.source_type == "file"
            else self.source_reference
        )


@dataclass(frozen=True, slots=True)
class ScoredChunk(StoredChunk):
    """Stored chunk with a retrieval relevance score."""

    score: float


@dataclass(frozen=True, slots=True)
class IngestionJob:
    """Durable ingestion job and its ownership and progress fields."""

    id: UUID
    source_id: UUID
    status: str
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
    claim_token: UUID | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class IngestionJobInput:
    """Staged input file metadata for an ingestion job."""

    job_id: UUID
    input_path: str | None
    source_name: str
    extraction_profile: dict[str, Any]
    configuration: dict[str, Any]
    reindex: bool


@dataclass(frozen=True, slots=True)
class Conversation:
    """Persisted conversation identifier and timestamps."""

    id: UUID
    tenant_id: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Message:
    """Persisted conversation message with sequence information."""

    id: UUID
    conversation_id: UUID
    sequence: int
    role: str
    content: str
    citations: list[dict[str, Any]]
    created_at: datetime


@dataclass(slots=True)
class ConversationTurn:
    """Recent history and the reply to commit when the turn succeeds."""

    history: list[Message]
    answer: str | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
