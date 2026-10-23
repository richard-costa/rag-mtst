"""Create the RAG schema with model-dependent vector dimensions and JSONB metadata."""

from __future__ import annotations

from alembic import op


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Initial schema creation
# ---------------------------------------------------------------------------
# The first migration creates the shared tenant-scoped RAG tables and indexes.

def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        """
        CREATE TABLE sources (
            id uuid PRIMARY KEY,
            tenant_id text NOT NULL,
            type text NOT NULL CHECK (type IN ('file', 'url')),
            locator text NOT NULL,
            mime_type text,
            content_hash text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, content_hash)
        )
        """
    )
    op.execute("CREATE INDEX sources_tenant_id_idx ON sources (tenant_id)")

    op.execute(
        """
        CREATE TABLE chunks (
            id uuid PRIMARY KEY,
            tenant_id text NOT NULL,
            source_id uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            chunk_index integer NOT NULL,
            page_number integer,
            content text NOT NULL,
            search_vector tsvector GENERATED ALWAYS AS (
                to_tsvector('pg_catalog.simple'::regconfig, content)
            ) STORED,
            embedding vector,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (source_id, chunk_index)
        )
        """
    )
    op.execute("CREATE INDEX chunks_tenant_id_idx ON chunks (tenant_id)")
    op.execute("CREATE INDEX chunks_source_id_idx ON chunks (source_id)")
    op.execute("CREATE INDEX chunks_search_vector_idx ON chunks USING gin (search_vector)")

    op.execute(
        """
        CREATE TABLE ingestion_jobs (
            id uuid PRIMARY KEY,
            source_id uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'completed', 'failed')),
            stage text,
            progress integer CHECK (progress BETWEEN 0 AND 100),
            processed integer,
            total integer,
            attempts integer NOT NULL DEFAULT 0,
            error text,
            created_at timestamptz NOT NULL DEFAULT now(),
            started_at timestamptz,
            heartbeat_at timestamptz,
            finished_at timestamptz,
            claim_token uuid,
            CHECK ((status = 'running') = (claim_token IS NOT NULL))
        )
        """
    )
    op.execute("CREATE INDEX ingestion_jobs_source_id_idx ON ingestion_jobs (source_id)")
    op.execute("CREATE INDEX ingestion_jobs_status_idx ON ingestion_jobs (status)")

    op.execute(
        """
        CREATE TABLE ingestion_job_inputs (
            job_id uuid PRIMARY KEY REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
            input_path text CHECK (input_path <> ''),
            source_name text NOT NULL CHECK (source_name <> ''),
            extraction_profile jsonb NOT NULL
                CHECK (jsonb_typeof(extraction_profile) = 'object'),
            configuration jsonb NOT NULL
                CHECK (jsonb_typeof(configuration) = 'object'),
            reindex boolean NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ingestion_jobs_active_source_idx
        ON ingestion_jobs (source_id)
        WHERE status IN ('pending', 'running')
        """
    )

    op.execute(
        """
        CREATE TABLE conversations (
            id uuid PRIMARY KEY,
            tenant_id text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX conversations_tenant_id_idx ON conversations (tenant_id)")

    op.execute(
        """
        CREATE TABLE messages (
            id uuid PRIMARY KEY,
            conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            sequence integer NOT NULL CHECK (sequence > 0),
            role text NOT NULL CHECK (role IN ('user', 'assistant')),
            content text NOT NULL,
            citations jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (conversation_id, sequence)
        )
        """
    )


# ---------------------------------------------------------------------------
# Schema rollback
# ---------------------------------------------------------------------------
# Tables are removed in dependency order so foreign-key constraints do not block rollback.

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS conversations")
    op.execute("DROP TABLE IF EXISTS ingestion_job_inputs")
    op.execute("DROP TABLE IF EXISTS ingestion_jobs")
    op.execute("DROP TABLE IF EXISTS chunks")
    op.execute("DROP TABLE IF EXISTS sources")
