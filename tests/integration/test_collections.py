from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient

from app import worker
from app.api.main import create_app
from app.storage import documents

pytestmark = pytest.mark.usefixtures(
    "deterministic_embeddings", "deterministic_generation", "inline_worker"
)

_ALPHA = "alpha"
_BETA = "Beta team:2"
_DOCUMENT = ("shared.md", b"# Shared\n\nAn access token is required.")
_PRIVATE = ("private.md", b"# Private\n\nRetention lasts thirty days.")


async def _upload(client, document):
    uploaded = await client.post("/sources/file", files={"file": document})
    assert uploaded.status_code == 202

    return uploaded.json()


async def test_one_worker_indexes_identical_content_separately_per_collection(
    settings, storage, api_client
):
    async with (
        api_client(collection=_ALPHA) as alpha,
        api_client(collection="beta") as beta,
    ):
        first = await _upload(alpha, _DOCUMENT)
        second = await _upload(beta, _DOCUMENT)

        assert first["id"] != second["id"]
        assert first["job_id"] != second["job_id"]

        assert await worker.run_once(settings=settings, storage=storage)
        assert await worker.run_once(settings=settings, storage=storage)
        assert not await worker.run_once(settings=settings, storage=storage)

        for client, submitted in [(alpha, first), (beta, second)]:
            job = await client.get(f"/jobs/{submitted['job_id']}")
            assert job.status_code == 200 and job.json()["status"] == "completed"

        alpha_chunks = await documents.list_chunks(storage, _ALPHA)
        beta_chunks = await documents.list_chunks(storage, "beta")
        assert alpha_chunks and len(alpha_chunks) == len(beta_chunks)
        assert {str(chunk.source_id) for chunk in alpha_chunks} == {first["id"]}
        assert {str(chunk.source_id) for chunk in beta_chunks} == {second["id"]}

        duplicate = await beta.post("/sources/file", files={"file": _DOCUMENT})
        assert duplicate.status_code == 200
        assert duplicate.json()["id"] == second["id"]


async def test_collections_cannot_read_or_delete_each_others_data(
    settings, storage, api_client
):
    async with (
        api_client(collection=_ALPHA) as alpha,
        api_client(collection=_BETA) as beta,
    ):
        source = await _upload(alpha, _PRIVATE)
        assert await worker.run_once(settings=settings, storage=storage)
        conversation = (await alpha.post("/conversations")).json()

        source_path = f"/sources/{source['id']}"
        job_path = f"/jobs/{source['job_id']}"
        conversation_path = f"/conversations/{conversation['id']}"

        for path in [source_path, job_path, conversation_path]:
            assert (await beta.get(path)).status_code == 404
            assert (await alpha.get(path)).status_code == 200

        assert (await beta.get(f"{conversation_path}/messages")).status_code == 404
        assert (
            await beta.post(f"{conversation_path}/messages", json={"query": "days"})
        ).status_code == 404
        assert (await beta.get("/sources")).json() == []
        assert (await beta.get("/conversations")).json() == []

        assert (await beta.delete(source_path)).status_code == 404
        assert (await beta.delete(conversation_path)).status_code == 404
        assert (await alpha.get(source_path)).status_code == 200
        assert (await alpha.get(conversation_path)).status_code == 200

        query = {"query": "retention", "method": "hybrid"}
        assert (await beta.post("/search", json=query)).json() == []
        answer = (await beta.post("/ask", json=query)).json()
        assert answer["matches"] == answer["citations"] == []

        matches = (await alpha.post("/search", json=query)).json()
        assert matches and {match["source_id"] for match in matches} == {source["id"]}

        assert (await alpha.delete(source_path)).status_code == 204
        assert (await alpha.delete(conversation_path)).status_code == 204


async def test_collection_paths_still_require_the_api_key(settings):
    path = f"/collections/{_ALPHA}/sources"

    async with AsyncClient(
        transport=ASGITransport(app=create_app(settings)), base_url="http://test"
    ) as client:
        assert (await client.get(path)).status_code == 401
        assert (
            await client.get(path, headers={"Authorization": "Bearer wrong"})
        ).status_code == 401
        assert (
            await client.get(
                path, headers={"Authorization": f"Bearer {settings.api_key}"}
            )
        ).status_code == 200


async def test_chunks_cannot_belong_to_a_different_collection_than_their_source(
    storage, store_vectors, database_url
):
    source = await store_vectors([[1.0, 0.0, 0.0]], collection_id=_ALPHA)

    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await connection.execute(
                "INSERT INTO chunks (id, collection_id, source_id, chunk_index, content)"
                " VALUES (%s, %s, %s, 99, 'leak')",
                (uuid4(), "beta", source.id),
            )

    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            await connection.execute(
                "INSERT INTO conversations (id, collection_id) VALUES (%s, '')",
                (uuid4(),),
            )
