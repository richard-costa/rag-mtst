from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Generator
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient, MockTransport, Response
from openai import AsyncOpenAI
from testcontainers.community.postgres import PostgresContainer

from app import ingestion, llm, retrieval, worker
from app.cli import main
from app.config import Settings, get_settings
from app.storage import documents
from app.storage.database import Database
from app.storage.records import ChunkInput

_TABLES = "messages, conversations, ingestion_jobs, chunks, sources"


def _sqlalchemy_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture(scope="session")
def database_url() -> Generator[str]:
    with PostgresContainer("pgvector/pgvector:pg17", driver=None) as postgres:
        url = postgres.get_connection_url()
        original_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        try:
            alembic = Config("alembic.ini")
            alembic.set_main_option("sqlalchemy.url", _sqlalchemy_url(url))
            command.upgrade(alembic, "head")
        finally:
            if original_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = original_database_url
        yield url


@pytest.fixture
def settings(database_url: str, tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        database_url=database_url,
        api_key="integration-test-key",
        tenant_id="test-tenant",
        chunk_size=10,
        retrieval_limit=5,
        generation_provider="ollama",
        generation_model="test-model",
    )


@pytest.fixture
def storage(settings: Settings) -> Database:
    return Database(settings.database_url)


async def _truncate(database_url: str) -> None:
    connection = await psycopg.AsyncConnection.connect(database_url)
    async with connection:
        await connection.execute(f"TRUNCATE {_TABLES} CASCADE")


@pytest.fixture(autouse=True)
async def clean_database(database_url: str):
    await _truncate(database_url)
    yield
    await _truncate(database_url)


@pytest.fixture
def deterministic_embeddings(monkeypatch):
    async def embed(texts, *, settings):
        vectors = []
        for text in texts:
            normalized = text.casefold()
            authentication = "token" in normalized or "authenticat" in normalized
            vectors.append(
                [1.0, float(authentication), float("retention" in normalized)]
            )
        return vectors

    monkeypatch.setattr(ingestion, "embed_texts", embed)
    monkeypatch.setattr(retrieval, "embed_texts", embed)


@pytest.fixture
def inline_worker(monkeypatch):
    async def execute_inline(job, *, settings, storage):
        await ingestion.process_ingestion_job(job, settings=settings, storage=storage)

    monkeypatch.setattr(worker, "_execute_job", execute_inline)


@pytest.fixture
def deterministic_generation(monkeypatch):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return Response(
            200,
            json={
                "id": "test-answer",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "text": "Generated grounded answer [1].",
                                    "citations": [1],
                                }
                            ),
                        },
                    }
                ],
            },
        )

    def client(**kwargs):
        return AsyncOpenAI(
            **kwargs, http_client=AsyncClient(transport=MockTransport(respond))
        )

    monkeypatch.setattr(llm, "AsyncOpenAI", client)
    monkeypatch.setenv("RAG_GENERATION_PROVIDER", "ollama")
    monkeypatch.setenv("RAG_GENERATION_MODEL", "test-model")
    return requests


@pytest.fixture
def cli_environment(settings, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("RAG_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("RAG_TENANT_ID", settings.tenant_id)


@pytest.fixture
def run_cli(inline_worker):
    async def run(arguments):
        stop = asyncio.Event()
        running = asyncio.create_task(
            worker.run_worker(settings=get_settings(), stop_event=stop)
        )
        try:
            return await asyncio.to_thread(main, arguments)
        finally:
            stop.set()
            await running

    return run


@pytest.fixture
def store_vectors(storage, settings):
    async def store(vectors, *, tenant_id=None, model=None):
        tenant_id = tenant_id or settings.tenant_id
        source = await documents.insert_source(
            storage,
            tenant_id=tenant_id,
            source_type="file",
            reference="/tmp/vectors.md",
            mime_type="text/markdown",
            content_hash=str(uuid4()),
        )
        await documents.replace_chunks(
            storage,
            tenant_id=tenant_id,
            source_id=source.id,
            chunks=[
                ChunkInput(
                    content=f"chunk {index}",
                    embedding=vector,
                    metadata={
                        "embedding_provider": settings.embedding_provider,
                        "embedding_model": model or settings.embedding_model_name,
                    },
                )
                for index, vector in enumerate(vectors)
            ],
        )
        return source

    return store
