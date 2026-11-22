"""Source upload, listing, and deletion endpoints."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse

from app.api.dependencies import SettingsDependency, StorageDependency
from app.api.schemas.sources import SourceDetailsResponse, SourceResponse
from app.ingestion import cleanup_ingestion_inputs, enqueue_bytes
from app.storage import documents
from app.storage.documents import SourceBusy, SourceNotFound
from app.storage.records import SourceSummary

router = APIRouter(tags=["sources"])


def _source_details(source: SourceSummary) -> SourceDetailsResponse:
    """Convert a stored source summary into its HTTP response.

    Args:
        source: Stored source with its chunk count.

    Returns:
        Public source metadata.
    """
    return SourceDetailsResponse(
        id=source.id,
        source_type=source.source_type,
        title=source.title,
        reference=source.reference,
        mime_type=source.mime_type,
        chunk_count=source.chunk_count,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


@router.get(
    "/sources", response_model=list[SourceDetailsResponse], summary="List sources"
)
async def list_sources(
    settings: SettingsDependency,
    storage: StorageDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SourceDetailsResponse]:
    """List a page of tenant sources, newest first.

    ### Parameters
    - `limit`: Maximum sources, from 1 to 100; defaults to 50.
    - `offset`: Number of sources to skip; defaults to 0.

    ### Responses
    - **200**: Source metadata with current indexed chunk counts.
    - **401**: Missing or invalid bearer token.
    - **422**: Invalid pagination parameters.

    A source with pending first-time indexing reports zero chunks.
    """
    sources = await documents.list_sources(
        storage, settings.tenant_id, limit=limit, offset=offset
    )
    return [_source_details(source) for source in sources]


@router.get(
    "/sources/{source_id}",
    response_model=SourceDetailsResponse,
    summary="Read a source",
)
async def get_source(
    source_id: UUID, settings: SettingsDependency, storage: StorageDependency
) -> SourceDetailsResponse:
    """Read the metadata of a tenant-owned source.

    ### Parameter
    - `source_id`: Source UUID returned by source submission.

    ### Responses
    - **200**: Source metadata with its current indexed chunk count.
    - **401**: Missing or invalid bearer token.
    - **404**: Source is missing or belongs to another tenant.
    - **422**: Invalid source UUID.
    """
    source = await documents.get_source(storage, settings.tenant_id, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return _source_details(source)


@router.delete("/sources/{source_id}", status_code=204, summary="Delete a source")
async def delete_source(
    source_id: UUID, settings: SettingsDependency, storage: StorageDependency
) -> Response:
    """Delete a source, its indexed chunks, and its finished job history.

    ### Parameter
    - `source_id`: Source UUID returned by source submission.

    ### Responses
    - **204**: Source deleted; it no longer appears in search or answers.
    - **401**: Missing or invalid bearer token.
    - **404**: Source is missing or belongs to another tenant.
    - **409**: An ingestion job for the source is pending or running.
    - **422**: Invalid source UUID.

    Saved conversation citations are snapshots and remain unchanged.
    """
    await cleanup_ingestion_inputs(settings=settings, storage=storage)
    try:
        await documents.delete_source(storage, settings.tenant_id, source_id)
    except SourceNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SourceBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(status_code=204)


@router.post(
    "/sources/file",
    response_model=SourceResponse,
    status_code=202,
    summary="Submit a document for indexing",
)
async def add_source_file(
    file: Annotated[UploadFile, File(description="A supported document file")],
    settings: SettingsDependency,
    storage: StorageDependency,
    reindex: bool = False,
    extraction_method: Literal["parser", "visual"] = "parser",
) -> SourceResponse | JSONResponse:
    """Upload a document and submit durable indexing work.

    ### Inputs
    - `file`: Multipart TXT, Markdown, PDF, DOCX, or PPTX upload with a filename.
    - `reindex`: Query flag allowing replacement of an existing index.
    - `extraction_method`: Query selection, `parser` (default) or `visual`.
      Unsupported input never silently falls back to another extraction method.

    ### Responses
    - **202**: A new or matching active job; poll the returned `status_url`.
    - **200**: Source already indexed with the same extraction profile; no job.
    - **401**: Missing or invalid bearer token.
    - **422**: Invalid filename, unsupported input, or conflicting submission.

    A separate worker processes queued jobs. File bytes are staged temporarily,
    not permanently archived; unsuccessful reindexing preserves the prior index.
    """
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
