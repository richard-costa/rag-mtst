"""Conversation history and atomic question/reply transactions."""

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from app.storage.database import Database
from app.storage.records import Conversation, ConversationTurn, Message


class ConversationNotFound(LookupError):
    """The conversation does not exist in the requested tenant.
    """


class ConversationBusy(RuntimeError):
    """Another turn is already using the conversation.
    """


async def create_conversation(database: Database, tenant_id: str) -> Conversation:
    """Insert a new tenant-scoped conversation.

    Args:
        database: PostgreSQL database handle.
        tenant_id: Tenant identifier used to scope the operation.

    Returns:
        Result of the operation.
    """
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
            INSERT INTO conversations (id, tenant_id)
            VALUES (%s, %s)
            RETURNING *
            """,
            (uuid4(), tenant_id),
        )
        row = await cursor.fetchone()
    assert row is not None
    return Conversation(**row)


@asynccontextmanager
async def conversation_turn(
    database: Database,
    tenant_id: str,
    conversation_id: UUID,
    question: str,
) -> AsyncGenerator[ConversationTurn]:
    """Lock one conversation and commit a successful question-and-answer pair.

    Args:
        database: PostgreSQL database handle.
        tenant_id: Tenant identifier used to scope the operation.
        conversation_id: Identifier of the conversation.
        question: Question to record before generating a response.

    Yields:
        Result of the operation.
    """
    async with database.connection() as connection:
        try:
            cursor = await connection.execute(
                "SELECT id FROM conversations WHERE tenant_id = %s AND id = %s FOR UPDATE NOWAIT",
                (tenant_id, conversation_id),
            )
        except psycopg.errors.LockNotAvailable as error:
            raise ConversationBusy("A turn is already active for this conversation") from error
        if await cursor.fetchone() is None:
            raise ConversationNotFound("Conversation not found")
        history = await _conversation_messages(connection, conversation_id, limit=20)
        turn = ConversationTurn(history=history)
        yield turn
        if turn.answer is None:
            raise ValueError("The conversation turn has no answer")
        sequence = history[-1].sequence + 1 if history else 1
        await connection.execute(
            """
            INSERT INTO messages (id, conversation_id, sequence, role, content, citations)
            VALUES (%s, %s, %s, 'user', %s, '[]'::jsonb),
                   (%s, %s, %s, 'assistant', %s, %s)
            """,
            (uuid4(), conversation_id, sequence, question,
             uuid4(), conversation_id, sequence + 1, turn.answer, Jsonb(turn.citations)),
        )
        await connection.execute(
            "UPDATE conversations SET updated_at = clock_timestamp() WHERE id = %s",
            (conversation_id,),
        )


async def list_messages(
    database: Database, tenant_id: str, conversation_id: UUID, *, limit: int = 50, before: int | None = None,
) -> list[Message]:
    """Retrieve conversation messages using a descending sequence cursor.

    Args:
        database: PostgreSQL database handle.
        tenant_id: Tenant identifier used to scope the operation.
        conversation_id: Identifier of the conversation.
        limit: Maximum number of matching passages.
        before: Sequence number used as an exclusive pagination cursor.

    Returns:
        Result of the operation.
    """
    if not 1 <= limit <= 100:
        raise ValueError("History limit must be between 1 and 100")
    async with database.connection() as connection:
        cursor = await connection.execute(
            "SELECT id FROM conversations WHERE tenant_id = %s AND id = %s",
            (tenant_id, conversation_id),
        )
        if await cursor.fetchone() is None:
            raise ConversationNotFound("Conversation not found")
        return await _conversation_messages(connection, conversation_id, limit=limit, before=before)


async def _conversation_messages(
    connection: psycopg.AsyncConnection[dict[str, Any]], conversation_id: UUID,
    *, limit: int, before: int | None = None,
) -> list[Message]:
    """Read the requested message page using an existing connection.

    Args:
        connection: Existing asynchronous PostgreSQL connection.
        conversation_id: Identifier of the conversation.
        limit: Maximum number of matching passages.
        before: Sequence number used as an exclusive pagination cursor.

    Returns:
        Result of the operation.
    """
    cursor = await connection.execute(
        """
        SELECT * FROM messages
        WHERE conversation_id = %s AND (%s::integer IS NULL OR sequence < %s)
        ORDER BY sequence DESC LIMIT %s
        """,
        (conversation_id, before, before, limit),
    )
    return [Message(**row) for row in reversed(await cursor.fetchall())]
