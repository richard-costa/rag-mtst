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
    summary="Search source passages",
)
async def search_sources(
    request: SearchRequest, settings: SettingsDependency, storage: StorageDependency
) -> list[SearchMatchResponse]:
    """Retrieve indexed source passages without generating an answer.

    ### Request body
    - `query`: Search text.
    - `method`, `limit`, `window`: Optional retrieval settings; omitted values use
      server defaults. In window mode, `limit` counts seeds before expansion.

    ### Ordering and scores
    Overlapping same-source windows are merged and deduplicated.
    Chunks within each group follow document order; groups are ranked by their best seed.
    Preserve this order rather than sorting individual chunks by score.
    Scores are method-specific diagnostics, not probabilities or comparable
    across methods. A null score identifies a neighbor added as context.

    ### Responses
    - **200**: Matching passages; an empty list means no matches.
    - **401**: Missing or invalid bearer token.
    - **422**: Invalid request or retrieval settings.
    - **502**: Embedding provider failure.
    """
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
