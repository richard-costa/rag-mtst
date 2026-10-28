"""Ingestion job status endpoints."""

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.api.dependencies import SettingsDependency, StorageDependency
from app.api.schemas import JobResponse
from app.storage import jobs

router = APIRouter(tags=["jobs"])


@router.get(
    "/jobs/{job_id}", response_model=JobResponse, summary="Read ingestion job status"
)
async def get_job(
    job_id: UUID, settings: SettingsDependency, storage: StorageDependency
) -> JobResponse:
    """Read the status and progress of a tenant-owned ingestion job.

    ### Parameter
    - `job_id`: Job UUID returned by source submission.

    ### Responses
    - **200**: Status, stage, counters, attempts, timestamps, and safe error text.
    - **401**: Missing or invalid bearer token.
    - **404**: Job is missing or belongs to another tenant.
    - **422**: Invalid job UUID.

    Worker claim tokens, staged paths, and credentials are not exposed.
    """
    job = await jobs.get_ingestion_job(storage, settings.tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    fields = asdict(job)
    fields.pop("claim_token")
    fields["id"] = str(job.id)
    fields["source_id"] = str(job.source_id)
    return JobResponse(**fields)
