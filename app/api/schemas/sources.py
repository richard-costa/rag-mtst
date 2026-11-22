"""HTTP source response models."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


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
