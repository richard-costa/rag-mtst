"""Source retrieval endpoints."""

from fastapi import APIRouter, HTTPException

from app.api.dependencies import SettingsDependency, StorageDependency
from app.api.schemas import SearchMatchResponse, SearchRequest
from app.api.services import search_match_response
from app.embeddings import EmbeddingError
from app.retrieval import search

router = APIRouter(tags=["search"])


@router.post(
    "/search",
    response_model=list[SearchMatchResponse],
    description=(
        "Return matching source chunks. In window mode, overlapping same-source windows are merged. "
        "Chunks within each group follow document order; groups are ranked by their best seed. "
        "Preserve this order rather than sorting individual chunks by score."
    ),
)
async def search_sources(
    request: SearchRequest, settings: SettingsDependency, storage: StorageDependency
) -> list[SearchMatchResponse]:
    try:
        matches = await search(
            request.query,
            limit=request.limit,
            method=request.method,
            window=request.window,
            settings=settings,
            storage=storage,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except EmbeddingError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return [search_match_response(match) for match in matches]
