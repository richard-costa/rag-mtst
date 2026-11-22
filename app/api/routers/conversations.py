"""Conversation management, history and answer endpoints."""

from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.dependencies import SettingsDependency, StorageDependency
from app.api.schemas.answers import AskResponse
from app.api.schemas.conversations import (
    ConversationResponse,
    ConversationTurnRequest,
    MessageResponse,
)
from app.api.services import generate_answer
from app.embeddings import EmbeddingError
from app.generation import GenerationError
from app.storage import conversations
from app.storage.conversations import ConversationBusy, ConversationNotFound
from app.storage.records import Conversation

router = APIRouter(tags=["conversations"])


def _conversation_response(conversation: Conversation) -> ConversationResponse:
    """Convert a stored conversation into its HTTP response.

    Args:
        conversation: Stored conversation record.

    Returns:
        Public conversation identifiers and timestamps.
    """
    return ConversationResponse(
        id=conversation.id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


@router.get(
    "/conversations",
    response_model=list[ConversationResponse],
    summary="List conversations",
)
async def list_conversations(
    settings: SettingsDependency,
    storage: StorageDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ConversationResponse]:
    """List a page of tenant conversations, most recently updated first.

    ### Parameters
    - `limit`: Maximum conversations, from 1 to 100; defaults to 50.
    - `offset`: Number of conversations to skip; defaults to 0.

    ### Responses
    - **200**: Conversation IDs and creation/update timestamps.
    - **401**: Missing or invalid bearer token.
    - **422**: Invalid pagination parameters.
    """
    items = await conversations.list_conversations(
        storage, settings.tenant_id, limit=limit, offset=offset
    )
    return [_conversation_response(conversation) for conversation in items]


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    summary="Read a conversation",
)
async def get_conversation(
    conversation_id: UUID, settings: SettingsDependency, storage: StorageDependency
) -> ConversationResponse:
    """Read the identifiers and timestamps of a tenant-owned conversation.

    ### Parameter
    - `conversation_id`: Conversation UUID.

    ### Responses
    - **200**: Conversation ID and creation/update timestamps.
    - **401**: Missing or invalid bearer token.
    - **404**: Conversation is missing or belongs to another tenant.
    - **422**: Invalid conversation UUID.
    """
    conversation = await conversations.get_conversation(
        storage, settings.tenant_id, conversation_id
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _conversation_response(conversation)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=204,
    summary="Delete a conversation",
)
async def delete_conversation(
    conversation_id: UUID, settings: SettingsDependency, storage: StorageDependency
) -> Response:
    """Delete a conversation and all of its messages.

    ### Parameter
    - `conversation_id`: Conversation UUID.

    ### Responses
    - **204**: Conversation and messages deleted.
    - **401**: Missing or invalid bearer token.
    - **404**: Conversation is missing or belongs to another tenant.
    - **409**: A turn currently holds the conversation lock.
    - **422**: Invalid conversation UUID.
    """
    try:
        await conversations.delete_conversation(
            storage, settings.tenant_id, conversation_id
        )
    except ConversationNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ConversationBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(status_code=204)


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=201,
    summary="Create a conversation",
)
async def create_conversation(
    settings: SettingsDependency, storage: StorageDependency
) -> ConversationResponse:
    """Create an empty conversation for the server-configured tenant.

    No request body is required.

    ### Responses
    - **201**: Conversation ID and creation/update timestamps.
    - **401**: Missing or invalid bearer token.
    """
    conversation = await conversations.create_conversation(storage, settings.tenant_id)
    return _conversation_response(conversation)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageResponse],
    summary="List conversation messages",
)
async def conversation_messages(
    conversation_id: UUID,
    settings: SettingsDependency,
    storage: StorageDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: Annotated[int | None, Query(ge=1)] = None,
) -> list[MessageResponse]:
    """Read a page of persisted messages in ascending sequence order.

    ### Parameters
    - `conversation_id`: Conversation UUID.
    - `limit`: Maximum messages, from 1 to 100; defaults to 50. The newest page
      is selected unless `before` is supplied.
    - `before`: Exclusive sequence cursor for reading older messages.

    ### Responses
    - **200**: Stored user/assistant messages with saved citation snapshots.
    - **401**: Missing or invalid bearer token.
    - **404**: Conversation is missing or belongs to another tenant.
    - **422**: Invalid UUID or pagination parameters.
    """
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


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=AskResponse,
    summary="Generate a conversation turn",
)
async def conversation_answer(
    conversation_id: UUID,
    request: ConversationTurnRequest,
    settings: SettingsDependency,
    storage: StorageDependency,
) -> AskResponse:
    """Generate an answer and atomically persist the user/assistant turn.

    ### Request
    - `conversation_id`: Conversation UUID in the path.
    - `query`: Nonblank question. Prior messages inform generation, but retrieval
        searches only this question.
    - `method`, `limit`, `window`: Optional retrieval settings.
    - `assembly`: `document` (default) or score-first window context order.
    - `generation_provider`, `generation_model`: Request-only model overrides;
        selecting a provider requires a model. Unknown body fields are rejected.

    ### Responses
    - **200**: Answer, retrieved matches, and current-source citations.
    - **401**: Missing or invalid bearer token.
    - **404**: Conversation is missing or belongs to another tenant.
    - **409**: Another turn already holds the conversation lock.
    - **422**: Invalid request, generation settings, or input budget.
    - **502**: Embedding or generation provider failure.

    Failed or cancelled turns leave no partial messages in history.
    """
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
