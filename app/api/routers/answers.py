"""Stateless answer-generation endpoints."""

from fastapi import APIRouter, HTTPException

from app.api.dependencies import SettingsDependency, StorageDependency
from app.api.schemas import AskRequest, AskResponse
from app.api.services import generate_answer
from app.embeddings import EmbeddingError
from app.generation import GenerationError

router = APIRouter(tags=["answers"])


@router.post("/ask", response_model=AskResponse, summary="Generate a cited answer")
async def ask_source(
    request: AskRequest, settings: SettingsDependency, storage: StorageDependency
) -> AskResponse:
    """Generate a stateless answer grounded in indexed source passages.

    ### Request body
    - `query`: Question to answer.
    - `method`, `limit`, `window`: Optional retrieval settings; omitted values use
        server defaults.
    - `assembly`: `document` (default) or score-first window context order.
    - `generation_provider`, `generation_model`: Request-only model overrides.
        Selecting a provider requires a model.
    - `history`: Optional prior user/assistant pairs, oldest first, at most 20
        messages. Informs generation only; retrieval searches only `query`.

    ### Responses
    - **200**: Answer text, retrieved matches, and current-source citations.
        Insufficient evidence may produce an answer without citations.
    - **401**: Missing or invalid bearer token.
    - **422**: Invalid request, history, generation settings, or input budget.
    - **502**: Embedding or generation provider failure.

    This endpoint never reads or persists stored conversations; callers that keep
    their own history pass it in `history`.
    """
    try:
        return await generate_answer(
            request, settings=settings, storage=storage, history=request.history
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (EmbeddingError, GenerationError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
