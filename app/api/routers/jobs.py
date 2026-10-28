"""Ingestion job status endpoints."""

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.api.dependencies import SettingsDependency, StorageDependency
from app.api.schemas import JobResponse
from app.storage import jobs

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID, settings: SettingsDependency, storage: StorageDependency
) -> JobResponse:
    job = await jobs.get_ingestion_job(storage, settings.tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    fields = asdict(job)
    fields.pop("claim_token")
    fields["id"] = str(job.id)
    fields["source_id"] = str(job.source_id)
    return JobResponse(**fields)
