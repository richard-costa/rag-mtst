"""HTTP ingestion job response model."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


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
