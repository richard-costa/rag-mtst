"""Persisted records and indexing inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Source:
    id: UUID
    tenant_id: str
    source_type: str
    locator: str
    mime_type: str | None
    content_hash: str
    created_at: datetime
    updated_at: datetime

    @property
    def title(self) -> str:
        return Path(self.locator).name


@dataclass(frozen=True, slots=True)
class Chunk:
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
    content: str
    metadata: dict[str, Any]
    page_number: int | None = None
    embedding: list[float] | None = None


@dataclass(frozen=True, slots=True)
class StoredChunk:
    id: UUID
    source_id: UUID
    source_locator: str
    chunk_index: int
    content: str
    metadata: dict[str, Any]

    @property
    def source_title(self) -> str:
        return Path(self.source_locator).name


@dataclass(frozen=True, slots=True)
class ScoredChunk(StoredChunk):
    score: float


@dataclass(frozen=True, slots=True)
class IngestionJob:
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
    job_id: UUID
    input_path: str | None
    source_name: str
    extraction_profile: dict[str, Any]
    configuration: dict[str, Any]
    reindex: bool


@dataclass(frozen=True, slots=True)
class Conversation:
    id: UUID
    tenant_id: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Message:
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
