"""Source, chunk, and search SQL."""

from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg
from pgvector import Vector
from psycopg.types.json import Jsonb

from app.storage.database import Database
from app.storage.records import ChunkInput, ScoredChunk, Source, StoredChunk


async def get_source_by_content_hash(
    database: Database,
    tenant_id: str,
    content_hash: str,
) -> Source | None:
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
            SELECT id, tenant_id, type AS source_type, reference, mime_type,
                   content_hash, created_at, updated_at
            FROM sources
            WHERE tenant_id = %s AND content_hash = %s
            """,
            (tenant_id, content_hash),
        )
        row = await cursor.fetchone()
    return Source(**row) if row is not None else None


async def get_source_extraction_profile(
    database: Database,
    tenant_id: str,
    source_id: UUID,
) -> dict[str, Any] | None:
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
            SELECT metadata->'extraction' AS profile
            FROM chunks
            WHERE tenant_id = %s AND source_id = %s
            GROUP BY metadata->'extraction'
            LIMIT 2
            """,
            (tenant_id, source_id),
        )
        rows = await cursor.fetchall()
    if len(rows) == 1 and isinstance(rows[0]["profile"], dict):
        return rows[0]["profile"]
    return None


async def insert_source(
    database: Database,
    *,
    tenant_id: str,
    source_type: Literal["file", "url"],
    reference: str,
    mime_type: str | None,
    content_hash: str,
) -> Source:
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
            INSERT INTO sources (id, tenant_id, type, reference, mime_type, content_hash)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, tenant_id, type AS source_type, reference, mime_type,
                      content_hash, created_at, updated_at
            """,
            (uuid4(), tenant_id, source_type, reference, mime_type, content_hash),
        )
        row = await cursor.fetchone()
    assert row is not None
    return Source(**row)


async def insert_source_with_chunks(
    database: Database,
    *,
    tenant_id: str,
    source_type: Literal["file", "url"],
    reference: str,
    mime_type: str | None,
    content_hash: str,
    chunks: list[ChunkInput],
) -> Source:
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
            INSERT INTO sources (id, tenant_id, type, reference, mime_type, content_hash)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, tenant_id, type AS source_type, reference, mime_type,
                      content_hash, created_at, updated_at
            """,
            (uuid4(), tenant_id, source_type, reference, mime_type, content_hash),
        )
        row = await cursor.fetchone()
        assert row is not None
        source = Source(**row)
        await _insert_chunks(connection, tenant_id, source.id, chunks)
    return source


async def replace_chunks(
    database: Database,
    *,
    tenant_id: str,
    source_id: UUID,
    chunks: list[ChunkInput],
) -> None:
    async with database.connection() as connection:
        await connection.execute(
            "DELETE FROM chunks WHERE source_id = %s",
            (source_id,),
        )
        await _insert_chunks(connection, tenant_id, source_id, chunks)


async def _insert_chunks(
    connection: psycopg.AsyncConnection[dict[str, Any]],
    tenant_id: str,
    source_id: UUID,
    chunks: list[ChunkInput],
) -> None:
    for index, chunk in enumerate(chunks):
        await connection.execute(
            """
            INSERT INTO chunks (
                id, tenant_id, source_id, chunk_index, page_number,
                content, embedding, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid4(),
                tenant_id,
                source_id,
                index,
                chunk.page_number,
                chunk.content,
                Vector(chunk.embedding) if chunk.embedding is not None else None,
                Jsonb(chunk.metadata),
            ),
        )


async def list_chunks(database: Database, tenant_id: str) -> list[StoredChunk]:
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
              SELECT chunks.id, chunks.source_id, sources.type AS source_type,
                  sources.reference AS source_reference,
                  chunks.chunk_index, chunks.content, chunks.metadata
            FROM chunks
            JOIN sources ON sources.id = chunks.source_id
            WHERE chunks.tenant_id = %s
            ORDER BY sources.created_at, chunks.chunk_index
            """,
            (tenant_id,),
        )
        rows = await cursor.fetchall()
    return [
        StoredChunk(
            id=row["id"],
            source_id=row["source_id"],
            source_type=row["source_type"],
            source_reference=row["source_reference"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            metadata=row["metadata"],
        )
        for row in rows
    ]


async def full_text_search(
    database: Database,
    *,
    tenant_id: str,
    query: str,
    limit: int,
) -> list[ScoredChunk]:
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
            WITH search_query AS (
                SELECT to_tsquery(
                    'pg_catalog.simple'::regconfig,
                    string_agg(quote_literal(term), ' | ')
                ) AS terms
                FROM unnest(tsvector_to_array(
                    to_tsvector('pg_catalog.simple'::regconfig, %s)
                )) AS parsed(term)
            )
                 SELECT chunks.id, chunks.source_id, sources.type AS source_type,
                     sources.reference AS source_reference,
                   chunks.chunk_index, chunks.content, chunks.metadata,
                   ts_rank_cd(chunks.search_vector, search_query.terms, 2) AS score
            FROM chunks
            JOIN sources ON sources.id = chunks.source_id
                        AND sources.tenant_id = chunks.tenant_id
            CROSS JOIN search_query
            WHERE chunks.tenant_id = %s
              AND chunks.search_vector @@ search_query.terms
            ORDER BY score DESC, chunks.source_id, chunks.chunk_index
            LIMIT %s
            """,
            (query, tenant_id, limit),
        )
        rows = await cursor.fetchall()
    return [ScoredChunk(**row) for row in rows]


async def vector_search(
    database: Database,
    *,
    tenant_id: str,
    embedding: list[float],
    embedding_provider: str,
    embedding_model: str,
    limit: int,
) -> list[ScoredChunk]:
    vector = Vector(embedding)
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
                 SELECT chunks.id, chunks.source_id, sources.type AS source_type,
                     sources.reference AS source_reference,
                   chunks.chunk_index, chunks.content, chunks.metadata,
                   1 - (chunks.embedding <=> %s::vector) AS score
            FROM chunks
            JOIN sources ON sources.id = chunks.source_id
                        AND sources.tenant_id = chunks.tenant_id
            WHERE chunks.tenant_id = %s
              AND chunks.embedding IS NOT NULL
              AND vector_norm(chunks.embedding) > 0
              AND chunks.metadata->>'embedding_provider' = %s
              AND chunks.metadata->>'embedding_model' = %s
            ORDER BY chunks.embedding <=> %s::vector,
                     chunks.source_id, chunks.chunk_index
            LIMIT %s
            """,
            (vector, tenant_id, embedding_provider, embedding_model, vector, limit),
        )
        rows = await cursor.fetchall()
    return [ScoredChunk(**row) for row in rows]


async def get_chunk_window(
    database: Database,
    *,
    tenant_id: str,
    source_id: UUID,
    chunk_index: int,
    window: int,
) -> list[StoredChunk]:
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
                 SELECT chunks.id, chunks.source_id, sources.type AS source_type,
                     sources.reference AS source_reference,
                   chunks.chunk_index, chunks.content, chunks.metadata
            FROM chunks
            JOIN sources ON sources.id = chunks.source_id
                        AND sources.tenant_id = chunks.tenant_id
            WHERE chunks.tenant_id = %s AND chunks.source_id = %s
              AND chunks.chunk_index BETWEEN %s AND %s
            ORDER BY chunks.chunk_index
            """,
            (tenant_id, source_id, chunk_index - window, chunk_index + window),
        )
        rows = await cursor.fetchall()
    return [StoredChunk(**row) for row in rows]
