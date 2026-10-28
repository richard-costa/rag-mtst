"""Conversation creation, history and answer endpoints."""

from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.api.dependencies import SettingsDependency, StorageDependency
from app.api.schemas import (
    AskResponse,
    ConversationResponse,
    ConversationTurnRequest,
    MessageResponse,
)
from app.api.services import generate_answer
from app.embeddings import EmbeddingError
from app.generation import GenerationError
from app.storage import conversations
from app.storage.conversations import ConversationBusy, ConversationNotFound

router = APIRouter(tags=["conversations"])


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    settings: SettingsDependency, storage: StorageDependency
) -> ConversationResponse:
    conversation = await conversations.create_conversation(storage, settings.tenant_id)
    return ConversationResponse(
        id=conversation.id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageResponse],
)
async def conversation_messages(
    conversation_id: UUID,
    settings: SettingsDependency,
    storage: StorageDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: Annotated[int | None, Query(ge=1)] = None,
) -> list[MessageResponse]:
    try:
        messages = await conversations.list_messages(
            storage,
            settings.tenant_id,
            conversation_id,
            limit=limit,
            before=before,
        )
    except ConversationNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return [MessageResponse(**asdict(message)) for message in messages]


@router.post("/conversations/{conversation_id}/messages", response_model=AskResponse)
async def conversation_answer(
    conversation_id: UUID,
    request: ConversationTurnRequest,
    settings: SettingsDependency,
    storage: StorageDependency,
) -> AskResponse:
    try:
        async with conversations.conversation_turn(
            storage, settings.tenant_id, conversation_id, request.query
        ) as turn:
            response = await generate_answer(
                request, settings=settings, storage=storage, history=turn.history
            )
            turn.answer = response.answer
            turn.citations = [citation.model_dump() for citation in response.citations]
    except ConversationNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ConversationBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (EmbeddingError, GenerationError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return response
