"""Durable ingestion jobs and atomic index completion."""

from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from app.storage import documents
from app.storage.database import Database
from app.storage.records import ChunkInput, IngestionJob, IngestionJobInput, Source


async def create_ingestion_job(
    database: Database,
    *,
    tenant_id: str,
    content_hash: str,
    reference: str,
    mime_type: str | None,
    input_path: str,
    source_name: str,
    extraction_profile: dict[str, Any],
    configuration: dict[str, Any],
    reindex: bool,
    job_id: UUID | None = None,
) -> tuple[Source, IngestionJob | None]:
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
            INSERT INTO sources (id, tenant_id, type, reference, mime_type, content_hash)
            VALUES (%s, %s, 'file', %s, %s, %s)
            ON CONFLICT (tenant_id, content_hash) DO NOTHING
            """,
            (uuid4(), tenant_id, reference, mime_type, content_hash),
        )
        cursor = await connection.execute(
            """
            SELECT id, tenant_id, type AS source_type, reference, mime_type,
                   content_hash, created_at, updated_at
            FROM sources
            WHERE tenant_id = %s AND content_hash = %s
            FOR UPDATE
            """,
            (tenant_id, content_hash),
        )
        source_row = await cursor.fetchone()
        assert source_row is not None
        source = Source(**source_row)
        cursor = await connection.execute(
            """
            SELECT * FROM ingestion_jobs
            WHERE source_id = %s AND status IN ('pending', 'running')
            """,
            (source.id,),
        )
        active_job = await cursor.fetchone()
        if active_job is not None:
            cursor = await connection.execute(
                "SELECT * FROM ingestion_job_inputs WHERE job_id = %s",
                (active_job["id"],),
            )
            active_input = await cursor.fetchone()
            if (
                active_input is None
                or active_input["extraction_profile"] != extraction_profile
                or active_input["configuration"] != configuration
                or active_input["reindex"] != reindex
            ):
                raise ValueError(
                    "The source already has an active ingestion job with different settings"
                )
            return source, IngestionJob(**active_job)

        cursor = await connection.execute(
            "SELECT metadata->'extraction' AS profile FROM chunks "
            "WHERE source_id = %s AND tenant_id = %s "
            "GROUP BY metadata->'extraction'",
            (source.id, tenant_id),
        )
        profiles = await cursor.fetchall()
        if profiles and not reindex:
            if len(profiles) != 1 or profiles[0]["profile"] != extraction_profile:
                raise ValueError(
                    "The source has a different or unknown extraction profile; explicit reindexing is required"
                )
            return source, None

        job_id = job_id or uuid4()
        cursor = await connection.execute(
            "INSERT INTO ingestion_jobs (id, source_id) VALUES (%s, %s) RETURNING *",
            (job_id, source.id),
        )
        row = await cursor.fetchone()
        await connection.execute(
            """
            INSERT INTO ingestion_job_inputs (
                job_id, input_path, source_name, extraction_profile, configuration, reindex
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                job_id,
                input_path,
                source_name,
                Jsonb(extraction_profile),
                Jsonb(configuration),
                reindex,
            ),
        )
    assert row is not None
    return source, IngestionJob(**row)


async def get_ingestion_job(
    database: Database, tenant_id: str, job_id: UUID
) -> IngestionJob | None:
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
            SELECT ingestion_jobs.* FROM ingestion_jobs
            JOIN sources ON sources.id = ingestion_jobs.source_id
            WHERE ingestion_jobs.id = %s AND sources.tenant_id = %s
            """,
            (job_id, tenant_id),
        )
        row = await cursor.fetchone()
    return IngestionJob(**row) if row is not None else None


async def get_ingestion_job_input(
    database: Database, tenant_id: str, job_id: UUID
) -> IngestionJobInput | None:
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
            SELECT ingestion_job_inputs.* FROM ingestion_job_inputs
            JOIN ingestion_jobs ON ingestion_jobs.id = ingestion_job_inputs.job_id
            JOIN sources ON sources.id = ingestion_jobs.source_id
            WHERE ingestion_jobs.id = %s AND sources.tenant_id = %s
            """,
            (job_id, tenant_id),
        )
        row = await cursor.fetchone()
    return IngestionJobInput(**row) if row is not None else None


async def claim_ingestion_job(
    database: Database, tenant_id: str
) -> IngestionJob | None:
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
            WITH candidate AS (
                SELECT jobs.id FROM ingestion_jobs AS jobs
                JOIN sources ON sources.id = jobs.source_id
                WHERE sources.tenant_id = %s AND jobs.status = 'pending'
                ORDER BY jobs.created_at, jobs.id
                FOR UPDATE OF jobs SKIP LOCKED
                LIMIT 1
            )
            UPDATE ingestion_jobs AS jobs
            SET status = 'running', stage = 'extracting', attempts = attempts + 1,
                started_at = now(), heartbeat_at = now(), claim_token = %s
            FROM candidate WHERE jobs.id = candidate.id
            RETURNING jobs.*
            """,
            (tenant_id, uuid4()),
        )
        row = await cursor.fetchone()
    return IngestionJob(**row) if row is not None else None


async def list_finished_ingestion_inputs(
    database: Database, tenant_id: str
) -> list[IngestionJobInput]:
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
            SELECT inputs.* FROM ingestion_job_inputs AS inputs
            JOIN ingestion_jobs AS jobs ON jobs.id = inputs.job_id
            JOIN sources ON sources.id = jobs.source_id
            WHERE sources.tenant_id = %s AND jobs.status IN ('completed', 'failed')
              AND inputs.input_path IS NOT NULL
            ORDER BY jobs.finished_at, jobs.id LIMIT 100
            """,
            (tenant_id,),
        )
        rows = await cursor.fetchall()
    return [IngestionJobInput(**row) for row in rows]


async def clear_ingestion_input_path(
    database: Database, tenant_id: str, job_id: UUID, input_path: str
) -> None:
    async with database.connection() as connection:
        await connection.execute(
            """
            UPDATE ingestion_job_inputs AS inputs SET input_path = NULL
            FROM ingestion_jobs AS jobs, sources
            WHERE inputs.job_id = jobs.id AND sources.id = jobs.source_id
              AND sources.tenant_id = %s AND jobs.id = %s
              AND jobs.status IN ('completed', 'failed') AND inputs.input_path = %s
            """,
            (tenant_id, job_id, input_path),
        )


async def heartbeat_ingestion_job(
    database: Database, tenant_id: str, job_id: UUID, claim_token: UUID
) -> bool:
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
            UPDATE ingestion_jobs AS jobs SET heartbeat_at = now()
            FROM sources WHERE sources.id = jobs.source_id AND sources.tenant_id = %s
              AND jobs.id = %s AND jobs.status = 'running' AND jobs.claim_token = %s
            """,
            (tenant_id, job_id, claim_token),
        )
    return cursor.rowcount == 1


async def update_ingestion_job_progress(
    database: Database,
    tenant_id: str,
    job_id: UUID,
    claim_token: UUID,
    *,
    stage: str,
    processed: int | None = None,
    total: int | None = None,
) -> bool:
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
            UPDATE ingestion_jobs AS jobs
            SET stage = %s, processed = %s, total = %s
            FROM sources WHERE sources.id = jobs.source_id AND sources.tenant_id = %s
              AND jobs.id = %s AND jobs.status = 'running' AND jobs.claim_token = %s
            """,
            (stage, processed, total, tenant_id, job_id, claim_token),
        )
    return cursor.rowcount == 1


async def fail_ingestion_job(
    database: Database,
    tenant_id: str,
    job_id: UUID,
    claim_token: UUID,
    *,
    error: str,
) -> bool:
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
            UPDATE ingestion_jobs AS jobs
            SET status = 'failed', error = %s, finished_at = now(), claim_token = NULL
            FROM sources WHERE sources.id = jobs.source_id AND sources.tenant_id = %s
              AND jobs.id = %s AND jobs.status = 'running' AND jobs.claim_token = %s
            """,
            (error, tenant_id, job_id, claim_token),
        )
    return cursor.rowcount == 1


async def fail_interrupted_ingestion_jobs(
    database: Database, tenant_id: str, *, stale_seconds: int
) -> int:
    if stale_seconds <= 0:
        raise ValueError("Stale heartbeat timeout must be greater than zero")
    async with database.connection() as connection:
        cursor = await connection.execute(
            """
            UPDATE ingestion_jobs AS jobs
            SET status = 'failed', error = 'Worker interrupted; resubmit explicitly.',
                finished_at = now(), claim_token = NULL
            FROM sources WHERE sources.id = jobs.source_id AND sources.tenant_id = %s
              AND jobs.status = 'running'
              AND jobs.heartbeat_at < now() - (%s * interval '1 second')
            """,
            (tenant_id, stale_seconds),
        )
    return cursor.rowcount


async def complete_ingestion_job(
    database: Database,
    tenant_id: str,
    job: IngestionJob,
    *,
    reference: str,
    chunks: list[ChunkInput],
) -> bool:
    async with database.connection() as connection:
        cursor = await connection.execute(
            "SELECT id FROM sources WHERE tenant_id = %s AND id = %s FOR UPDATE",
            (tenant_id, job.source_id),
        )
        if await cursor.fetchone() is None:
            return False
        cursor = await connection.execute(
            """
            SELECT id FROM ingestion_jobs
            WHERE id = %s AND source_id = %s AND status = 'running' AND claim_token = %s
            FOR UPDATE
            """,
            (job.id, job.source_id, job.claim_token),
        )
        if await cursor.fetchone() is None:
            return False
        await connection.execute(
            "DELETE FROM chunks WHERE source_id = %s", (job.source_id,)
        )
        await documents._insert_chunks(connection, tenant_id, job.source_id, chunks)
        await connection.execute(
            "UPDATE sources SET reference = %s, updated_at = now() WHERE id = %s",
            (reference, job.source_id),
        )
        await connection.execute(
            """
            UPDATE ingestion_jobs SET status = 'completed', stage = 'completed',
                progress = 100, processed = %s, total = %s, finished_at = now(),
                claim_token = NULL WHERE id = %s
            """,
            (len(chunks), len(chunks), job.id),
        )
    return True
