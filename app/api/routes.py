"""HTTP routes and response conversion."""

from collections.abc import Sequence
from dataclasses import asdict, replace
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from app.api.schemas import (
    AskRequest,
    AskResponse,
    CitationResponse,
    ConversationResponse,
    ConversationTurnRequest,
    JobResponse,
    MessageResponse,
    SearchMatchResponse,
    SearchRequest,
    SourceResponse,
)
from app.config import Settings
from app.embeddings import EmbeddingError
from app.generation import GenerationError, answer
from app.ingestion import enqueue_bytes
from app.retrieval import SearchResult, search
from app.storage import conversations, jobs
from app.storage.conversations import ConversationBusy, ConversationNotFound
from app.storage.database import Database
from app.storage.records import Message


def create_router(settings: Settings, storage: Database) -> APIRouter:
    """Create API routes bound to the configured tenant and database.

    Args:
        settings: Configuration for this operation; defaults to the environment where supported.
        storage: Database handle; defaults to the configured database where supported.

    Returns:
        Configured API router.
    """
    router = APIRouter()

    @router.post("/sources/file", response_model=SourceResponse, status_code=202)
    async def add_source_file(
        file: Annotated[UploadFile, File(description="A supported document file")],
        reindex: bool = False,
        extraction_method: Literal["parser", "visual"] = "parser",
    ) -> SourceResponse | JSONResponse:
        """Upload a document for asynchronous indexing.

        **Inputs**
        - `file`: Uploaded PDF, Office document, Markdown, or text file.
        - `reindex`: Replace existing chunks when the content has already been indexed.
        - `extraction_method`: Use native parsing or visual extraction.

        **Responses**
        - `202`: Ingestion job created.
        - `200`: Source already indexed; no job created.
        - `422`: Invalid filename or ingestion parameters.
        """
        if not file.filename:
            raise HTTPException(status_code=422, detail="The uploaded file needs a filename")

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

    @router.get("/jobs/{job_id}", response_model=JobResponse)
    async def get_job(job_id: UUID) -> JobResponse:
        """Read ingestion-job status and progress.

        **Path parameter**
        - `job_id`: UUID returned when the source was submitted.

        **Responses**
        - `200`: Job information, including progress and status.
        - `404`: Job does not exist for the configured tenant.
        """
        job = await jobs.get_ingestion_job(storage, settings.tenant_id, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Ingestion job not found")
        fields = asdict(job)
        fields.pop("claim_token")
        fields["id"] = str(job.id)
        fields["source_id"] = str(job.source_id)
        return JobResponse(**fields)

    @router.post("/search", response_model=list[SearchMatchResponse])
    async def search_sources(request: SearchRequest) -> list[SearchMatchResponse]:
        """Search indexed source passages.

        **Request body**
        - `query`: Search text.
        - `method`, `limit`, `window`: Optional retrieval settings.

        **Responses**
        - `200`: Matching passages with scores.
        - `422`: Invalid search request.
        - `502`: Embedding provider failure.
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
        return [_search_match_response(match) for match in matches]

    async def generate_answer(request: AskRequest, history: Sequence[Message] = ()) -> AskResponse:
        """Generate a cited answer using the requested provider and conversation context.

        Args:
            request: Validated request payload.
            history: Prior conversation messages used as context.

        Returns:
            Answer with retrieved passages and citations.
        """
        if request.generation_provider is not None and request.generation_model is None:
            raise HTTPException(status_code=422, detail="Select a model for the requested answer provider")
        answer_settings = replace(
            settings,
            generation_provider=request.generation_provider or settings.generation_provider,
            generation_model=request.generation_model.strip() if request.generation_model is not None else settings.generation_model,
            generation_base_url=(
                None if request.generation_provider not in {None, settings.generation_provider}
                else settings.generation_base_url
            ),
        )
        try:
            result = await answer(
                request.query,
                limit=request.limit,
                method=request.method,
                window=request.window,
                settings=answer_settings,
                storage=storage,
                history=history,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except (EmbeddingError, GenerationError) as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        return AskResponse(
            answer=result.text,
            matches=[_search_match_response(match) for match in result.matches],
            citations=[CitationResponse(**asdict(citation)) for citation in result.citations],
        )

    @router.post("/ask", response_model=AskResponse)
    async def ask_source(request: AskRequest) -> AskResponse:
        """Generate an answer grounded in indexed passages.

        **Request body**
        - `query`: Question to answer.
        - `method`, `limit`, `window`: Optional retrieval settings.
        - `generation_provider`, `generation_model`: Optional model overrides.

        **Responses**
        - `200`: Answer, retrieved matches, and citations.
        - `422`: Invalid generation settings.
        - `502`: Retrieval or generation provider failure.
        """
        return await generate_answer(request)

    @router.post("/conversations", response_model=ConversationResponse, status_code=201)
    async def create_conversation() -> ConversationResponse:
        """Create an empty conversation.

        **Response**
        - `201`: Conversation ID and creation timestamps.
        """
        conversation = await conversations.create_conversation(storage, settings.tenant_id)
        return ConversationResponse(
            id=conversation.id, created_at=conversation.created_at, updated_at=conversation.updated_at,
        )

    @router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
    async def conversation_messages(
        conversation_id: UUID,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        before: Annotated[int | None, Query(ge=1)] = None,
    ) -> list[MessageResponse]:
        """List messages in an existing conversation.

        **Path parameter**
        - `conversation_id`: Conversation UUID.

        **Query parameters**
        - `limit`: Maximum number of messages (1–100).
        - `before`: Return messages older than this sequence number.

        **Responses**
        - `200`: Stored messages.
        - `404`: Conversation not found.
        """
        try:
            messages = await conversations.list_messages(storage,
                settings.tenant_id, conversation_id, limit=limit, before=before,
            )
        except ConversationNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return [MessageResponse(**asdict(message)) for message in messages]

    @router.post("/conversations/{conversation_id}/messages", response_model=AskResponse)
    async def conversation_answer(conversation_id: UUID, request: ConversationTurnRequest) -> AskResponse:
        """Generate and store the next conversation turn.

        **Path parameter**
        - `conversation_id`: Conversation UUID.

        **Request body**
        - `query`: Question to answer with the conversation's prior messages.

        **Responses**
        - `200`: Generated answer and citations; the turn is persisted.
        - `404`: Conversation not found.
        - `409`: Another turn is in progress.
        - `422` / `502`: Invalid request or provider failure.
        """
        try:
            async with conversations.conversation_turn(storage, settings.tenant_id, conversation_id, request.query) as turn:
                response = await generate_answer(request, history=turn.history)
                turn.answer = response.answer
                turn.citations = [citation.model_dump() for citation in response.citations]
        except ConversationNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ConversationBusy as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return response

    return router


def _search_match_response(match: SearchResult) -> SearchMatchResponse:
    """Convert a retrieval result into the public API schema.

    Args:
        match: Retrieved passage to convert.

    Returns:
        Public search-match representation.
    """
    return SearchMatchResponse(
        source_id=match.source_id,
        source_title=match.source_title,
        chunk_index=match.chunk_index,
        content=match.content,
        score=match.score,
    )
