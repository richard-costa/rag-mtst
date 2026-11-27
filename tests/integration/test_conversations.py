from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest

from app import generation
from app.collection import DEFAULT_COLLECTION
from app.storage import conversations

pytestmark = pytest.mark.usefixtures(
    "deterministic_embeddings", "deterministic_generation"
)


async def test_conversation_api_persists_ordered_history_and_current_citations(
    store_vectors, settings, storage, deterministic_generation, api_client
):
    source = await store_vectors([[1.0, 1.0, 0.0]])

    async with api_client() as client:
        created = await client.post("/conversations")

        assert created.status_code == 201
        assert set(created.json()) == {"id", "created_at", "updated_at"}
        history_url = f"/conversations/{created.json()['id']}/messages"
        assert (await client.get(history_url)).json() == []

        for body in ({"query": " "}, {"query": "token", "role": "system"}):
            assert (await client.post(history_url, json=body)).status_code == 422

        first = await client.post(
            history_url, json={"query": "token", "generation_model": "request-model"}
        )

        assert first.status_code == 200
        assert first.json()["citations"][0]["source_id"] == str(source.id)
        assert deterministic_generation[0]["model"] == "request-model"
        history = (await client.get(history_url)).json()
        assert [message["sequence"] for message in history] == [1, 2]
        assert [message["role"] for message in history] == ["user", "assistant"]
        assert history[0]["content"] == "token" and history[0]["citations"] == []
        assert history[1]["content"] == first.json()["answer"]
        assert history[1]["citations"] == first.json()["citations"]

        follow_up = await client.post(
            history_url, json={"query": "What about the token?"}
        )

        assert follow_up.status_code == 200
        prompt = json.loads(deterministic_generation[1]["messages"][1]["content"])
        assert prompt["history"] == [
            {"role": message["role"], "content": message["content"]}
            for message in history
        ]

        recent = await client.get(history_url, params={"limit": 2})
        assert [message["sequence"] for message in recent.json()] == [3, 4]
        assert (await client.get(history_url, params={"before": 3})).json() == history
        assert (await client.get(history_url, params={"limit": 101})).status_code == 422
        assert (
            await client.get(f"/conversations/{uuid4()}/messages")
        ).status_code == 404

        async with api_client(collection="other-collection") as other:
            assert (await other.get(history_url)).status_code == 404
            assert (
                await other.post(history_url, json={"query": "token"})
            ).status_code == 404

        assert len(deterministic_generation) == 2

        stateless = await client.post("/ask", json={"query": "token"})
        assert stateless.status_code == 200
        assert "history" not in json.loads(
            deterministic_generation[-1]["messages"][1]["content"]
        )
        assert len((await client.get(history_url)).json()) == 4


async def test_ask_uses_caller_history_without_storing_it(
    store_vectors, deterministic_generation, api_client
):
    await store_vectors([[1.0, 1.0, 0.0]])
    history = [
        {"role": "user", "content": "What is required?"},
        {"role": "assistant", "content": "A token."},
    ]

    async with api_client() as client:
        answered = await client.post(
            "/ask", json={"query": "What about the token?", "history": history}
        )

        assert answered.status_code == 200
        prompt = json.loads(deterministic_generation[-1]["messages"][1]["content"])
        assert prompt["history"] == history
        assert prompt["question"] == "What about the token?"
        assert (await client.get("/conversations")).json() == []


async def test_conversations_are_listed_and_read_within_the_collection(
    settings, api_client
):
    async with api_client() as client:
        created = (await client.post("/conversations")).json()

        listed = await client.get("/conversations")
        assert listed.status_code == 200 and listed.json() == [created]
        read = await client.get(f"/conversations/{created['id']}")
        assert read.status_code == 200 and read.json() == created
        assert (await client.get(f"/conversations/{uuid4()}")).status_code == 404

        invalid_turn = await client.post(
            f"/conversations/{created['id']}/messages",
            json={"query": "token", "generation_provider": "deepseek"},
        )

        assert invalid_turn.status_code == 422
        assert (
            await client.get(f"/conversations/{created['id']}/messages")
        ).json() == []

        invalid_search = await client.post(
            "/search", json={"query": "!!!", "method": "lexical"}
        )

        assert invalid_search.status_code == 422

    async with api_client(collection="other-collection") as other:
        assert (await other.get("/conversations")).json() == []
        assert (await other.get(f"/conversations/{created['id']}")).status_code == 404


async def test_conversation_api_rejects_overlap_and_failed_turns_leave_no_history(
    store_vectors, settings, storage, monkeypatch, api_client
):
    await store_vectors([[1.0, 1.0, 0.0]])
    conversation = await conversations.create_conversation(storage, DEFAULT_COLLECTION)
    history_url = f"/conversations/{conversation.id}/messages"
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_answer(*args, **kwargs):
        entered.set()
        await release.wait()

        return await generation.answer(*args, **kwargs)

    monkeypatch.setattr("app.api.services.answer", blocked_answer)

    async with api_client() as client:
        pending = asyncio.create_task(client.post(history_url, json={"query": "token"}))

        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            overlapping = await client.post(history_url, json={"query": "token"})
            assert overlapping.status_code == 409
            assert (await client.get(history_url)).json() == []
            release.set()
            assert (await asyncio.wait_for(pending, timeout=5)).status_code == 200

        finally:
            release.set()
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

        before = (await client.get(history_url)).json()

        async def fail_answer(*args, **kwargs):
            raise generation.GenerationError("Generation failed")

        monkeypatch.setattr("app.api.services.answer", fail_answer)
        assert (
            await client.post(history_url, json={"query": "token"})
        ).status_code == 502
        assert (await client.get(history_url)).json() == before

        monkeypatch.setattr("app.api.services.answer", generation.answer)
        assert (
            await client.post(history_url, json={"query": "token"})
        ).status_code == 200
        assert [
            message["sequence"] for message in (await client.get(history_url)).json()
        ] == [1, 2, 3, 4]

        before_cancel = (await client.get(history_url)).json()
        monkeypatch.setattr("app.api.services.answer", blocked_answer)
        entered.clear()
        release.clear()
        pending = asyncio.create_task(
            client.post(history_url, json={"query": "Cancelled turn"})
        )

        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

        assert (await client.get(history_url)).json() == before_cancel

        monkeypatch.setattr("app.api.services.answer", generation.answer)
        assert (
            await client.post(history_url, json={"query": "token"})
        ).status_code == 200
