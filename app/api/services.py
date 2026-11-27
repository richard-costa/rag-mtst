"""Shared answer orchestration and HTTP response conversion."""

from collections.abc import Sequence
from dataclasses import asdict, replace

from app.api.schemas.answers import AskResponse, CitationResponse, GenerationRequest
from app.api.schemas.search import SearchMatchResponse
from app.config import Settings
from app.generation import ConversationMessage, answer
from app.retrieval import SearchResult
from app.storage.database import Database


async def generate_answer(
    request: GenerationRequest,
    *,
    collection_id: str,
    settings: Settings,
    storage: Database,
    history: Sequence[ConversationMessage] = (),
) -> AskResponse:
    """Generate an API answer with request-scoped model settings.

    Args:
        request: Validated question, retrieval controls, and model overrides.
        collection_id: Collection whose sources may be retrieved.
        settings: Server defaults; never mutated.
        storage: Database handle for retrieving source passages.
        history: Ordered prior messages for generation context, empty by default.

    Returns:
        Answer text, retrieved matches, and current-source citations.

    Raises:
        ValueError: Request settings or the generation input budget are invalid.
        EmbeddingError: Retrieval embeddings could not be produced.
        GenerationError: The provider failed or returned an unusable answer.
    """

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
        collection_id=collection_id,
        limit=request.limit,
        method=request.method,
        window=request.window,
        assembly=request.assembly,
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
    """Convert a retrieval result into its HTTP response model.

    Args:
        match: Retrieved source passage with its diagnostic score.

    Returns:
        Search-match response preserving content, source identity, and score.
    """

    return SearchMatchResponse(
        source_id=match.source_id,
        source_title=match.source_title,
        chunk_index=match.chunk_index,
        content=match.content,
        score=match.score,
    )
