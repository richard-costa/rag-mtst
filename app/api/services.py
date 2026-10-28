"""Shared answer orchestration and HTTP response conversion."""

from collections.abc import Sequence
from dataclasses import asdict, replace

from app.api.schemas import (
    AskRequest,
    AskResponse,
    CitationResponse,
    SearchMatchResponse,
)
from app.config import Settings
from app.generation import answer
from app.retrieval import SearchResult
from app.storage.database import Database
from app.storage.records import Message


async def generate_answer(
    request: AskRequest,
    *,
    settings: Settings,
    storage: Database,
    history: Sequence[Message] = (),
) -> AskResponse:
    if request.generation_provider is not None and request.generation_model is None:
        raise ValueError("Select a model for the requested answer provider")
    answer_settings = replace(
        settings,
        generation_provider=request.generation_provider or settings.generation_provider,
        generation_model=request.generation_model.strip()
        if request.generation_model is not None
        else settings.generation_model,
        generation_base_url=(
            None
            if request.generation_provider not in {None, settings.generation_provider}
            else settings.generation_base_url
        ),
    )
    result = await answer(
        request.query,
        limit=request.limit,
        method=request.method,
        window=request.window,
        settings=answer_settings,
        storage=storage,
        history=history,
    )
    return AskResponse(
        answer=result.text,
        matches=[search_match_response(match) for match in result.matches],
        citations=[
            CitationResponse(**asdict(citation)) for citation in result.citations
        ],
    )


def search_match_response(match: SearchResult) -> SearchMatchResponse:
    return SearchMatchResponse(
        source_id=match.source_id,
        source_title=match.source_title,
        chunk_index=match.chunk_index,
        content=match.content,
        score=match.score,
    )
