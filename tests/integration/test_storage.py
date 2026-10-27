from __future__ import annotations

import asyncio
from io import StringIO
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from app.storage import conversations, documents, jobs
from app.storage.conversations import ConversationBusy, ConversationNotFound
from app.storage.records import ChunkInput

# ---------------------------------------------------------------------------
# Migration schema checks
# ---------------------------------------------------------------------------
# The initial migration must create all persisted entities and enable pgvector.


async def test_migrations_create_application_tables(database_url: str) -> None:
    connection = await psycopg.AsyncConnection.connect(database_url)
    async with connection:
        cursor = await connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            """
        )
        tables = {row[0] for row in await cursor.fetchall()}
        extension = await connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )
        extension_row = await extension.fetchone()
        vector_type = await connection.execute(
            """
            SELECT format_type(atttypid, atttypmod)
            FROM pg_attribute
            WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'
            """
        )
        vector_type_row = await vector_type.fetchone()
        search_column = await connection.execute(
            """
            SELECT format_type(atttypid, atttypmod), attgenerated
            FROM pg_attribute
            WHERE attrelid = 'chunks'::regclass AND attname = 'search_vector'
            """
        )
        search_column_row = await search_column.fetchone()
        search_index = await connection.execute(
            """
            SELECT access_method.amname
            FROM pg_class AS index_class
            JOIN pg_am AS access_method ON access_method.oid = index_class.relam
            WHERE index_class.oid = 'chunks_search_vector_idx'::regclass
            """
        )
        search_index_row = await search_index.fetchone()
        revision = await connection.execute("SELECT version_num FROM alembic_version")
        revision_row = await revision.fetchone()

    assert {
        "sources",
        "chunks",
        "ingestion_jobs",
        "ingestion_job_inputs",
        "conversations",
        "messages",
    } <= tables
    assert extension_row is not None
    assert extension_row[0] is True
    assert vector_type_row == ("vector",)
    assert search_column_row == ("tsvector", "s")
    assert search_index_row == ("gin",)
    assert revision_row == ("0001_initial",)


@pytest.mark.parametrize("scheme", ["postgresql", "postgresql+psycopg"])
def test_offline_migrations_accept_encoded_database_passwords(
    monkeypatch, scheme
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", f"{scheme}://rag:example%40password@127.0.0.1/rag"
    )
    output = StringIO()
    config = Config("alembic.ini", output_buffer=output)

    command.upgrade(config, "head", sql=True)

    sql = output.getvalue()
    assert "reference text NOT NULL" in sql
    assert "locator text" not in sql
    assert "CREATE TABLE chunks" in sql
    assert "embedding vector" in sql
    assert "metadata jsonb" in sql
    assert "GENERATED ALWAYS AS" in sql
    assert "USING gin (search_vector)" in sql
    assert "CREATE TABLE ingestion_job_inputs" in sql
    assert "input_path text" in sql
    assert "content bytea" not in sql
    assert "CREATE UNIQUE INDEX ingestion_jobs_active_source_idx" in sql


# ---------------------------------------------------------------------------
# Document record checks
# ---------------------------------------------------------------------------
# Source and chunk metadata round-trip through PostgreSQL records.


@pytest.mark.parametrize(
    ("source_type", "reference", "title"),
    [
        ("file", "/tmp/handbook.md", "handbook.md"),
        ("file", "handbook.md", "handbook.md"),
        (
            "url",
            "https://example.org/policies/handbook?lang=en#section",
            "https://example.org/policies/handbook?lang=en#section",
        ),
        ("url", "https://example.org/policies/", "https://example.org/policies/"),
    ],
)
async def test_document_records_preserve_metadata(
    storage, source_type, reference, title
) -> None:
    source = await documents.insert_source(
        storage,
        tenant_id="test-tenant",
        source_type=source_type,
        reference=reference,
        mime_type="text/markdown",
        content_hash="abc123",
    )
    await documents.replace_chunks(
        storage,
        tenant_id="test-tenant",
        source_id=source.id,
        chunks=[
            ChunkInput(
                content="first chunk",
                metadata={"headings": ["Setup"], "start_line": 3, "end_line": 3},
            ),
            ChunkInput(
                content="second chunk",
                metadata={"headings": ["Setup", "Authentication"]},
            ),
        ],
    )
    chunks = await documents.list_chunks(storage, "test-tenant")

    assert source.reference == reference
    assert source.title == title
    assert all(
        chunk.source_reference == reference and chunk.source_title == title
        for chunk in chunks
    )
    assert all(chunk.source_type == source_type for chunk in chunks)
    assert [chunk.content for chunk in chunks] == ["first chunk", "second chunk"]
    assert chunks[0].metadata == {
        "headings": ["Setup"],
        "start_line": 3,
        "end_line": 3,
    }
    assert chunks[1].metadata == {"headings": ["Setup", "Authentication"]}


async def test_conversation_turns_are_ordered_tenant_scoped_and_atomic(storage):
    conversation = await conversations.create_conversation(storage, "test-tenant")
    with pytest.raises(ConversationNotFound):
        await conversations.list_messages(storage, "other-tenant", conversation.id)
    with pytest.raises(ConversationNotFound):
        async with conversations.conversation_turn(
            storage, "other-tenant", conversation.id, "private"
        ):
            pytest.fail("Another tenant must not enter the turn")

    async with conversations.conversation_turn(
        storage, "test-tenant", conversation.id, "First question"
    ) as turn:
        assert turn.history == []
        turn.answer = "First answer [1]"
        turn.citations = [{"id": 1, "content": "An exact source snapshot"}]
    first = await conversations.list_messages(storage, "test-tenant", conversation.id)
    assert [message.sequence for message in first] == [1, 2]
    assert [message.role for message in first] == ["user", "assistant"]
    assert first[0].citations == []
    assert first[1].citations == [{"id": 1, "content": "An exact source snapshot"}]

    with pytest.raises(RuntimeError, match="generation failed"):
        async with conversations.conversation_turn(
            storage, "test-tenant", conversation.id, "Failed question"
        ) as turn:
            assert turn.history == first
            turn.answer = "Must not be committed"
            raise RuntimeError("generation failed")
    assert (
        await conversations.list_messages(storage, "test-tenant", conversation.id)
        == first
    )

    async with conversations.conversation_turn(
        storage, "test-tenant", conversation.id, "Next question"
    ) as turn:
        turn.answer = "Next answer"
    recent = await conversations.list_messages(
        storage, "test-tenant", conversation.id, limit=2
    )
    assert [message.sequence for message in recent] == [3, 4]
    assert (
        await conversations.list_messages(
            storage, "test-tenant", conversation.id, before=3
        )
        == first
    )


async def test_conversation_lock_rejects_overlap_but_allows_other_conversations(
    storage,
):
    conversation = await conversations.create_conversation(storage, "test-tenant")
    other = await conversations.create_conversation(storage, "test-tenant")
    with pytest.raises(asyncio.CancelledError):
        async with conversations.conversation_turn(
            storage, "test-tenant", conversation.id, "Cancelled question"
        ):
            with pytest.raises(ConversationBusy):
                async with conversations.conversation_turn(
                    storage, "test-tenant", conversation.id, "Overlapping question"
                ):
                    pytest.fail("Overlapping turns must not enter")
            async with conversations.conversation_turn(
                storage, "test-tenant", other.id, "Independent question"
            ) as turn:
                turn.answer = "Independent answer"
            assert (
                await conversations.list_messages(
                    storage, "test-tenant", conversation.id
                )
                == []
            )
            raise asyncio.CancelledError
    async with conversations.conversation_turn(
        storage, "test-tenant", conversation.id, "Retry"
    ) as turn:
        assert turn.history == []
        turn.answer = "The lock was released"


async def test_conversation_turn_history_is_bounded_without_reusing_sequence_numbers(
    storage,
):
    conversation = await conversations.create_conversation(storage, "test-tenant")
    for index in range(12):
        async with conversations.conversation_turn(
            storage, "test-tenant", conversation.id, f"Question {index}"
        ) as turn:
            assert len(turn.history) == min(index * 2, 20)
            if turn.history:
                assert turn.history[-1].sequence == index * 2
            turn.answer = f"Answer {index}"
    messages = await conversations.list_messages(
        storage, "test-tenant", conversation.id
    )
    assert [message.sequence for message in messages] == list(range(1, 25))


async def test_ingestion_job_inputs_are_atomic_durable_and_tenant_scoped(storage):
    source, job = await jobs.create_ingestion_job(
        storage,
        tenant_id="test-tenant",
        content_hash="queued",
        reference="queued.md",
        mime_type="text/markdown",
        input_path="/tmp/queued.md",
        source_name="queued.md",
        extraction_profile={"method": "parser"},
        configuration={"chunk_size": 180},
        reindex=False,
    )
    assert job is not None and job.status == "pending" and job.source_id == source.id
    assert await documents.list_chunks(storage, "test-tenant") == []
    assert await jobs.get_ingestion_job(storage, "test-tenant", job.id) == job
    assert await jobs.get_ingestion_job(storage, "other-tenant", job.id) is None
    queued_input = await jobs.get_ingestion_job_input(storage, "test-tenant", job.id)
    assert queued_input is not None
    assert queued_input.input_path == "/tmp/queued.md"
    assert queued_input.configuration == {"chunk_size": 180}
    assert not hasattr(queued_input, "content")
    assert await jobs.get_ingestion_job_input(storage, "other-tenant", job.id) is None

    with pytest.raises(psycopg.errors.CheckViolation):
        await jobs.create_ingestion_job(
            storage,
            tenant_id="test-tenant",
            content_hash="rollback",
            reference="bad.md",
            mime_type="text/markdown",
            input_path="/tmp/bad.md",
            source_name="",
            extraction_profile={},
            configuration={},
            reindex=False,
        )
    assert (
        await documents.get_source_by_content_hash(storage, "test-tenant", "rollback")
        is None
    )


async def test_ingestion_job_submissions_serialize_duplicates_and_reject_conflicts(
    storage,
):
    arguments = {
        "tenant_id": "test-tenant",
        "content_hash": "concurrent",
        "reference": "queued.md",
        "mime_type": "text/markdown",
        "input_path": "/tmp/queued.md",
        "source_name": "queued.md",
        "extraction_profile": {"method": "parser"},
        "configuration": {"chunk_size": 180},
        "reindex": False,
    }
    results = await asyncio.gather(
        *(jobs.create_ingestion_job(storage, **arguments) for _ in range(4))
    )
    assert len({source.id for source, _job in results}) == 1
    assert len({job.id for _source, job in results if job is not None}) == 1
    for changes in (
        {"configuration": {"chunk_size": 90}},
        {"extraction_profile": {"method": "visual"}},
        {"reindex": True},
    ):
        with pytest.raises(ValueError, match="active ingestion job"):
            await jobs.create_ingestion_job(storage, **{**arguments, **changes})
    other_source, other_job = await jobs.create_ingestion_job(
        storage, **{**arguments, "tenant_id": "other-tenant"}
    )
    assert other_source.id != results[0][0].id
    assert other_job is not None and other_job.id != results[0][1].id


async def test_ingestion_job_active_constraint_and_new_submission_after_failure(
    storage,
):
    arguments = {
        "tenant_id": "test-tenant",
        "content_hash": "retry",
        "reference": "queued.md",
        "mime_type": "text/markdown",
        "input_path": "/tmp/queued.md",
        "source_name": "queued.md",
        "extraction_profile": {"method": "parser"},
        "configuration": {"chunk_size": 180},
        "reindex": False,
    }
    source, job = await jobs.create_ingestion_job(storage, **arguments)
    assert job is not None
    with pytest.raises(psycopg.errors.UniqueViolation):
        async with storage.connection() as connection:
            await connection.execute(
                "INSERT INTO ingestion_jobs (id, source_id) VALUES (%s, %s)",
                (uuid4(), source.id),
            )
    async with storage.connection() as connection:
        await connection.execute(
            "UPDATE ingestion_jobs SET status = 'failed', finished_at = now() WHERE id = %s",
            (job.id,),
        )
    next_source, next_job = await jobs.create_ingestion_job(
        storage,
        **{**arguments, "configuration": {"chunk_size": 90}},
    )
    assert next_source == source
    assert next_job is not None and next_job.id != job.id
    first_input = await jobs.get_ingestion_job_input(storage, "test-tenant", job.id)
    next_input = await jobs.get_ingestion_job_input(storage, "test-tenant", next_job.id)
    assert first_input is not None and first_input.configuration == {"chunk_size": 180}
    assert next_input is not None and next_input.configuration == {"chunk_size": 90}


async def test_worker_claims_are_exclusive_and_stale_workers_cannot_commit(storage):
    source, submitted = await jobs.create_ingestion_job(
        storage,
        tenant_id="test-tenant",
        content_hash="claim",
        reference="claim.md",
        mime_type="text/markdown",
        input_path="/tmp/claim.md",
        source_name="claim.md",
        extraction_profile={"method": "parser"},
        configuration={},
        reindex=False,
    )
    assert submitted is not None
    assert await jobs.claim_ingestion_job(storage, "other-tenant") is None
    claims = await asyncio.gather(
        *(jobs.claim_ingestion_job(storage, "test-tenant") for _ in range(4))
    )
    claimed = [job for job in claims if job is not None]
    assert len(claimed) == 1
    job = claimed[0]
    assert job.id == submitted.id and job.attempts == 1 and job.claim_token is not None
    assert not await jobs.heartbeat_ingestion_job(
        storage, "other-tenant", job.id, job.claim_token
    )
    assert not await jobs.heartbeat_ingestion_job(
        storage, "test-tenant", job.id, uuid4()
    )
    assert await jobs.heartbeat_ingestion_job(
        storage, "test-tenant", job.id, job.claim_token
    )
    assert await jobs.update_ingestion_job_progress(
        storage,
        "test-tenant",
        job.id,
        job.claim_token,
        stage="embedding",
        processed=0,
        total=2,
    )
    assert (
        await jobs.fail_interrupted_ingestion_jobs(
            storage, "test-tenant", stale_seconds=60
        )
        == 0
    )
    async with storage.connection() as connection:
        await connection.execute(
            "UPDATE ingestion_jobs SET heartbeat_at = now() - interval '2 minutes' WHERE id = %s",
            (job.id,),
        )
    assert (
        await jobs.fail_interrupted_ingestion_jobs(
            storage, "other-tenant", stale_seconds=60
        )
        == 0
    )
    assert (
        await jobs.fail_interrupted_ingestion_jobs(
            storage, "test-tenant", stale_seconds=60
        )
        == 1
    )
    assert not await jobs.complete_ingestion_job(
        storage,
        "test-tenant",
        job,
        reference="stale.md",
        chunks=[ChunkInput("stale content", {})],
    )
    assert not await jobs.fail_ingestion_job(
        storage, "test-tenant", job.id, job.claim_token, error="late"
    )
    assert await documents.list_chunks(storage, "test-tenant") == []
    failed = await jobs.get_ingestion_job(storage, "test-tenant", job.id)
    assert (
        failed is not None and failed.status == "failed" and failed.claim_token is None
    )
    assert "resubmit explicitly" in (failed.error or "")
    assert await jobs.claim_ingestion_job(storage, "test-tenant") is None
    assert (
        await documents.get_source_by_content_hash(storage, "test-tenant", "claim")
        == source
    )


async def test_worker_completion_is_atomic_with_chunk_replacement(storage, monkeypatch):
    source, submitted = await jobs.create_ingestion_job(
        storage,
        tenant_id="test-tenant",
        content_hash="completion",
        reference="old.md",
        mime_type="text/markdown",
        input_path="/tmp/new.md",
        source_name="new.md",
        extraction_profile={"method": "parser"},
        configuration={},
        reindex=True,
    )
    await documents.replace_chunks(
        storage,
        tenant_id="test-tenant",
        source_id=source.id,
        chunks=[ChunkInput("old content", {})],
    )
    old_chunks = await documents.list_chunks(storage, "test-tenant")
    job = await jobs.claim_ingestion_job(storage, "test-tenant")
    assert submitted is not None and job is not None

    async def failed_insert(*args, **kwargs):
        raise RuntimeError("synthetic storage failure")

    with monkeypatch.context() as failed:
        failed.setattr(documents, "_insert_chunks", failed_insert)
        with pytest.raises(RuntimeError, match="synthetic storage failure"):
            await jobs.complete_ingestion_job(
                storage,
                "test-tenant",
                job,
                reference="new.md",
                chunks=[ChunkInput("new content", {})],
            )
    assert await documents.list_chunks(storage, "test-tenant") == old_chunks
    running = await jobs.get_ingestion_job(storage, "test-tenant", job.id)
    assert running is not None and running.status == "running"
    assert await jobs.complete_ingestion_job(
        storage,
        "test-tenant",
        job,
        reference="new.md",
        chunks=[ChunkInput("new content", {})],
    )
    completed = await jobs.get_ingestion_job(storage, "test-tenant", job.id)
    assert (
        completed is not None
        and completed.status == "completed"
        and completed.progress == 100
    )
    assert completed.processed == completed.total == 1
    assert [
        chunk.content for chunk in await documents.list_chunks(storage, "test-tenant")
    ] == ["new content"]
    assert not await jobs.complete_ingestion_job(
        storage, "test-tenant", job, reference="late.md", chunks=[]
    )


async def test_source_extraction_profile_is_consistent_and_tenant_scoped(storage):
    profile = {"method": "parser", "engine": "utf-8"}
    source = await documents.insert_source_with_chunks(
        storage,
        tenant_id="test-tenant",
        source_type="file",
        reference="profile.md",
        mime_type="text/markdown",
        content_hash="profile",
        chunks=[
            ChunkInput("first", {"extraction": profile}),
            ChunkInput("second", {"extraction": profile}),
        ],
    )
    assert (
        await documents.get_source_extraction_profile(storage, "test-tenant", source.id)
        == profile
    )
    assert (
        await documents.get_source_extraction_profile(
            storage, "another-tenant", source.id
        )
        is None
    )
    await documents.replace_chunks(
        storage,
        tenant_id="test-tenant",
        source_id=source.id,
        chunks=[ChunkInput("first", {"extraction": profile}), ChunkInput("second", {})],
    )
    assert (
        await documents.get_source_extraction_profile(storage, "test-tenant", source.id)
        is None
    )
    await documents.replace_chunks(
        storage, tenant_id="test-tenant", source_id=source.id, chunks=[]
    )
    assert (
        await documents.get_source_extraction_profile(storage, "test-tenant", source.id)
        is None
    )


@pytest.mark.parametrize(
    ("content", "query", "matches"),
    [
        ("Housing support documents", "HOUSING", True),
        ("Inscri\u00e7\u00e3o para habita\u00e7\u00e3o", "habita\u00e7\u00e3o", True),
        ("Moradia com housing support", "moradia housing", True),
        ("Housing support documents", "housing nonexistent", True),
        ("Housing support documents", "'housing' | !nonexistent", True),
        ("Housing support documents", "housing'); DROP TABLE chunks; --", True),
        ("Housing support documents", "unrelated", False),
        ("Housing support documents", "", False),
        ("Housing support documents", "!!!", False),
        ("Available houses", "house", False),
        ("habita\u00e7\u00e3o", "habitacao", False),
    ],
)
async def test_full_text_search_matches_without_language_detection(
    content, query, matches, storage
):
    source = await documents.insert_source_with_chunks(
        storage,
        tenant_id="test-tenant",
        source_type="file",
        reference="/tmp/multilingual.md",
        mime_type="text/markdown",
        content_hash="multilingual",
        chunks=[ChunkInput(content=content, metadata={"heading": "Original"})],
    )

    results = await documents.full_text_search(
        storage, tenant_id="test-tenant", query=query, limit=5
    )

    assert len(results) == int(matches)
    if matches:
        assert results[0].source_id == source.id
        assert results[0].content == content
        assert results[0].metadata == {"heading": "Original"}
        assert results[0].score > 0


async def test_full_text_search_ranks_limits_filters_tenants_and_updates_generated_text(
    storage,
):
    source = await documents.insert_source_with_chunks(
        storage,
        tenant_id="test-tenant",
        source_type="file",
        reference="/tmp/ranking.md",
        mime_type="text/markdown",
        content_hash="ranking",
        chunks=[
            ChunkInput("housing " + "unrelated " * 50, {}),
            ChunkInput("housing", {}),
            ChunkInput("housing", {}),
        ],
    )
    await documents.insert_source_with_chunks(
        storage,
        tenant_id="another-tenant",
        source_type="file",
        reference="/tmp/private.md",
        mime_type="text/markdown",
        content_hash="private",
        chunks=[ChunkInput("housing", {})],
    )

    results = await documents.full_text_search(
        storage, tenant_id="test-tenant", query="housing", limit=2
    )
    assert [chunk.chunk_index for chunk in results] == [1, 2]
    assert all(chunk.source_id == source.id for chunk in results)
    assert results[0].score == results[1].score
    assert (
        await documents.full_text_search(
            storage, tenant_id="empty", query="housing", limit=5
        )
        == []
    )

    await documents.replace_chunks(
        storage,
        tenant_id="test-tenant",
        source_id=source.id,
        chunks=[ChunkInput("newterm", {})],
    )
    assert (
        await documents.full_text_search(
            storage, tenant_id="test-tenant", query="housing", limit=5
        )
        == []
    )
    updated = await documents.full_text_search(
        storage, tenant_id="test-tenant", query="newterm", limit=5
    )
    assert [chunk.chunk_index for chunk in updated] == [0]


async def test_initial_migration_can_be_reversed_and_recreated(
    database_url, storage, monkeypatch
):
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config("alembic.ini")

    try:
        await asyncio.to_thread(command.downgrade, config, "base")
        async with storage.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT to_regclass('chunks') AS chunks, to_regclass('sources') AS sources,
                       to_regclass('ingestion_job_inputs') AS inputs,
                       to_regclass('ingestion_jobs') AS jobs
                """
            )
            assert await cursor.fetchone() == {
                "chunks": None,
                "sources": None,
                "inputs": None,
                "jobs": None,
            }
    finally:
        await asyncio.to_thread(command.upgrade, config, "head")

    source = await documents.insert_source_with_chunks(
        storage,
        tenant_id="test-tenant",
        source_type="file",
        reference="/tmp/recreated.md",
        mime_type="text/markdown",
        content_hash="recreated",
        chunks=[ChunkInput("Recreated housing content", {})],
    )
    results = await documents.full_text_search(
        storage, tenant_id="test-tenant", query="housing", limit=5
    )
    assert [chunk.source_id for chunk in results] == [source.id]
    queued_source, job = await jobs.create_ingestion_job(
        storage,
        tenant_id="test-tenant",
        content_hash="recreated",
        reference=source.reference,
        mime_type="text/markdown",
        input_path="/tmp/recreated.md",
        source_name="recreated.md",
        extraction_profile={"method": "parser"},
        configuration={},
        reindex=True,
    )
    assert queued_source == source and job is not None
    queued_input = await jobs.get_ingestion_job_input(storage, "test-tenant", job.id)
    assert queued_input is not None and queued_input.input_path == "/tmp/recreated.md"
