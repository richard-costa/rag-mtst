"""Stateless answer-generation endpoints."""

from fastapi import APIRouter, HTTPException

from app.api.dependencies import SettingsDependency, StorageDependency
from app.api.schemas import AskRequest, AskResponse
from app.api.services import generate_answer
from app.embeddings import EmbeddingError
from app.generation import GenerationError

router = APIRouter(tags=["answers"])


@router.post("/ask", response_model=AskResponse)
async def ask_source(
    request: AskRequest, settings: SettingsDependency, storage: StorageDependency
) -> AskResponse:
    try:
        return await generate_answer(request, settings=settings, storage=storage)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (EmbeddingError, GenerationError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
