"""HTTP conversation request and response models."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.answers import CitationResponse, GenerationRequest


class ConversationTurnRequest(GenerationRequest):
    """Strict request payload for a conversation turn."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, pattern=r"\S")


class ConversationResponse(BaseModel):
    """Identifiers and timestamps for a conversation."""

    id: UUID
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    """A stored question or answer within a conversation."""

    id: UUID
    sequence: int
    role: Literal["user", "assistant"]
    content: str
    citations: list[CitationResponse]
    created_at: datetime
