from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app import generation, ingestion, llm, retrieval, worker
from app.api.main import create_app
from app.cli import main
from app.embeddings import EmbeddingError
from app.storage import documents

pytestmark = pytest.mark.usefixtures(
    "deterministic_embeddings", "deterministic_generation"
)


@pytest.mark.usefixtures("inline_worker")
async def test_api_upload_status_search_and_ask_are_tenant_scoped(settings, storage):
    transport = ASGITransport(app=create_app(settings))
    headers = {"Authorization": f"Bearer {settings.api_key}"}
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=headers
    ) as client:
        files = {"file": ("queued.md", b"# Queued\n\nAn access token is required.")}
        uploaded = await client.post("/sources/file", files=files)
        assert uploaded.status_code == 202
        submission = uploaded.json()
        assert submission["status"] == "pending" and submission["job_id"]
        assert await documents.list_chunks(storage, settings.tenant_id) == []
        repeated = await client.post("/sources/file", files=files)
        assert repeated.status_code == 202 and repeated.json() == submission
        pending = await client.get(submission["status_url"])
        assert pending.status_code == 200 and pending.json()["status"] == "pending"
        assert "claim_token" not in pending.json() and "content" not in pending.json()
        assert (await client.get(f"/jobs/{uuid4()}")).status_code == 404
        other_transport = ASGITransport(
            app=create_app(replace(settings, tenant_id="other-tenant"))
        )
        async with AsyncClient(
            transport=other_transport, base_url="http://test", headers=headers
        ) as other:
            assert (await other.get(submission["status_url"])).status_code == 404
        assert await worker.run_once(settings=settings, storage=storage)
        completed = await client.get(submission["status_url"])
        assert (
            completed.json()["status"] == "completed"
            and completed.json()["progress"] == 100
        )
        matches = await client.post("/search", json={"query": "access token"})
        assert matches.status_code == 200
        assert (
            len(matches.json())
            == len(await documents.list_chunks(storage, settings.tenant_id))
            > 0
        )
        assert all(match["source_id"] == submission["id"] for match in matches.json())
        answer = await client.post("/ask", json={"query": "How do I authenticate?"})
        assert answer.status_code == 200
        assert answer.json()["answer"] == "Generated grounded answer [1]."
        assert "access token" in answer.json()["citations"][0]["content"]
        assert answer.json()["citations"][0]["source_id"] == submission["id"]
        assert answer.json()["citations"][0]["source_reference"] == "queued.md"
        assert "source_locator" not in answer.json()["citations"][0]
        duplicate = await client.post("/sources/file", files=files)
        assert duplicate.status_code == 200 and duplicate.json() == {
            "id": submission["id"],
            "status": "unchanged",
            "job_id": None,
            "status_url": None,
        }


async def test_api_selects_cosine_windows_lexical_and_hybrid(
    store_vectors, settings, storage
):
    await store_vectors(
        [
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [1.0, 0.0, 0.0],
        ]
    )
    transport = ASGITransport(app=create_app(settings))
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {settings.api_key}"},
    ) as client:
        cosine = await client.post(
            "/search", json={"query": "token", "limit": 1, "method": "cosine"}
        )
        window = await client.post("/search", json={"query": "token", "limit": 1})
        lexical = await client.post(
            "/search", json={"query": "chunk 0", "method": "lexical", "limit": 1}
        )
        hybrid = await client.post(
            "/search", json={"query": "chunk 0", "method": "hybrid", "limit": 1}
        )
        hybrid_answer = await client.post(
            "/ask", json={"query": "chunk 0", "method": "hybrid", "limit": 1}
        )
        answer = await client.post("/ask", json={"query": "token", "limit": 1})
        invalid = await client.post("/search", json={"query": "token", "window": -1})

    assert (
        cosine.status_code
        == window.status_code
        == lexical.status_code
        == answer.status_code
        == 200
    )
    assert [match["chunk_index"] for match in cosine.json()] == [1]
    assert [match["chunk_index"] for match in window.json()] == [0, 1, 2]
    assert [match["score"] for match in window.json()] == [
        None,
        pytest.approx(1.0),
        None,
    ]
    assert lexical.json()[0]["chunk_index"] == 0
    assert hybrid.status_code == hybrid_answer.status_code == 200
    assert len(hybrid.json()) == 1
    assert hybrid.json()[0]["chunk_index"] == 0
    assert hybrid.json()[0]["score"] == pytest.approx(2 / 61)
    assert hybrid_answer.json()["matches"] == hybrid.json()
    assert hybrid_answer.json()["answer"] == "Generated grounded answer [1]."
    assert hybrid_answer.json()["citations"][0]["chunk_index"] == 0
    assert (
        hybrid_answer.json()["citations"][0]["source_id"]
        == hybrid.json()[0]["source_id"]
    )
    assert answer.json()["matches"] == window.json()
    assert answer.json()["answer"] == "Generated grounded answer [1]."
    assert answer.json()["citations"][0]["chunk_index"] == 0
    assert invalid.status_code == 422


@pytest.mark.usefixtures("inline_worker")
async def test_api_reindex_status_and_embedding_failure(settings, storage, monkeypatch):
    transport = ASGITransport(app=create_app(settings))
    files = {"file": ("notes.md", b"A short document.", "text/markdown")}
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {settings.api_key}"},
    ) as client:
        first = await client.post("/sources/file", files=files)
        assert await worker.run_once(settings=settings, storage=storage)
        duplicate = await client.post("/sources/file", files=files)
        reindexed = await client.post("/sources/file?reindex=true", files=files)
        assert await worker.run_once(settings=settings, storage=storage)

        async def fail(texts, *, settings):
            raise EmbeddingError("provider unavailable")

        monkeypatch.setattr(retrieval, "embed_texts", fail)
        failed = await client.post("/search", json={"query": "document"})
        failed_answer = await client.post("/ask", json={"query": "document"})
        failed_hybrid = await client.post(
            "/search", json={"query": "document", "method": "hybrid"}
        )
        failed_hybrid_answer = await client.post(
            "/ask", json={"query": "document", "method": "hybrid"}
        )
        before_failure = await documents.list_chunks(storage, settings.tenant_id)
        monkeypatch.setattr(ingestion, "embed_texts", fail)
        failed_reindex = await client.post("/sources/file?reindex=true", files=files)
        assert failed_reindex.status_code == 202
        assert await worker.run_once(settings=settings, storage=storage)
        failed_job = await client.get(failed_reindex.json()["status_url"])
        assert (
            await documents.list_chunks(storage, settings.tenant_id) == before_failure
        )
        lexical = await client.post(
            "/search", json={"query": "document", "method": "lexical"}
        )

    assert first.status_code == reindexed.status_code == 202
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "unchanged"
    assert reindexed.json()["status"] == "pending"
    assert reindexed.json()["id"] == first.json()["id"]
    assert failed.status_code == failed_answer.status_code == 502
    assert failed_job.json()["status"] == "failed"
    assert failed_hybrid.status_code == failed_hybrid_answer.status_code == 502
    assert lexical.status_code == 200
    assert len(lexical.json()) == 1
    assert lexical.json()[0]["source_id"] == first.json()["id"]
    assert lexical.json()[0]["content"] == before_failure[0].content


async def test_generation_empty_sources_configuration_and_provider_errors(
    store_vectors,
    settings,
    storage,
    monkeypatch,
    capsys,
    deterministic_generation,
):
    async with AsyncClient(
        transport=ASGITransport(app=create_app(settings)),
        base_url="http://test",
        headers={"Authorization": f"Bearer {settings.api_key}"},
    ) as client:
        empty = await client.post("/ask", json={"query": "token"})
        assert empty.status_code == 200
        assert empty.json()["matches"] == empty.json()["citations"] == []
        assert deterministic_generation == []

        await store_vectors([[1.0, 1.0, 0.0]])

        def fail(**kwargs):
            raise generation.GenerationError("generation unavailable")

        monkeypatch.setattr(llm, "AsyncOpenAI", fail)
        failed = await client.post("/ask", json={"query": "token"})
        assert failed.status_code == 502
        assert failed.json()["detail"] == "generation unavailable"

    missing_model = create_app(replace(settings, generation_model=None))
    async with AsyncClient(
        transport=ASGITransport(app=missing_model),
        base_url="http://test",
        headers={"Authorization": f"Bearer {settings.api_key}"},
    ) as client:
        invalid = await client.post("/ask", json={"query": "token"})
        assert invalid.status_code == 422
        assert "RAG_GENERATION_MODEL" in invalid.json()["detail"]

    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("RAG_TENANT_ID", settings.tenant_id)
    assert await asyncio.to_thread(main, ["ask", "token"]) == 1
    output = capsys.readouterr()
    assert "generation unavailable" in output.err
    assert "Most relevant excerpt" not in output.out
