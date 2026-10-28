"""Source upload endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.api.dependencies import SettingsDependency, StorageDependency
from app.api.schemas import SourceResponse
from app.ingestion import enqueue_bytes

router = APIRouter(tags=["sources"])


@router.post("/sources/file", response_model=SourceResponse, status_code=202)
async def add_source_file(
    file: Annotated[UploadFile, File(description="A supported document file")],
    settings: SettingsDependency,
    storage: StorageDependency,
    reindex: bool = False,
    extraction_method: Literal["parser", "visual"] = "parser",
) -> SourceResponse | JSONResponse:
    if not file.filename:
        raise HTTPException(
            status_code=422, detail="The uploaded file needs a filename"
        )

    try:
        result = await enqueue_bytes(
            await file.read(),
            source_name=file.filename,
            settings=settings,
            storage=storage,
            reindex=reindex,
            extraction_method=extraction_method,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    job = result.job
    response = SourceResponse(
        id=str(result.source.id),
        status="unchanged" if job is None else job.status,
        job_id=str(job.id) if job is not None else None,
        status_url=f"/jobs/{job.id}" if job is not None else None,
    )
    if job is not None:
        return response
    return JSONResponse(status_code=200, content=response.model_dump())
