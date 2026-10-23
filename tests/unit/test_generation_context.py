from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import tiktoken

from app import generation
from app.storage.records import Message


@pytest.fixture
def history_messages():
    def build(contents):
        conversation_id = uuid4()
        return [
            Message(
                id=uuid4(), conversation_id=conversation_id, sequence=index + 1,
                role="user" if index % 2 == 0 else "assistant", content=content,
                citations=[], created_at=datetime.now(timezone.utc),
            )
            for index, content in enumerate(contents)
        ]
    return build


@pytest.mark.parametrize("provider", ["openai", "deepseek", "ollama", "anthropic"])
async def test_context_budget_counts_tokens_and_keeps_exact_truncated_passage(
    generation_settings, passages, completion, provider,
):
    passages[0] = replace(passages[0], content='Habita\u00e7\u00e3o "quoted" <|endoftext|>\n' * 500)
    requests = completion("Use the supplied passage [1].")
    settings = replace(
        generation_settings, generation_input_tokens=600, generation_provider=provider,
        openai_api_key="key", deepseek_api_key="key", anthropic_api_key="key",
    )

    result = await generation.answer("Explain", settings=settings)

    payload = json.loads(requests[0].content)
    if provider == "anthropic":
        system = payload["system"]
        user = payload["messages"][0]["content"][0]["text"]
    elif provider == "openai":
        system = payload["instructions"]
        user = payload["input"][0]["content"][0]["text"]
    else:
        system, user = [message["content"] for message in payload["messages"]]
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = sum(len(encoding.encode(text, disallowed_special=())) for text in [system, user])
    if provider != "deepseek":
        tokens += len(encoding.encode(json.dumps(generation._AnswerResponse.model_json_schema(), ensure_ascii=False)))
    assert tokens + 64 <= settings.generation_input_tokens
    sources = json.loads(user)["sources"]
    assert len(sources) == 1
    assert sources[0]["content"]
    assert passages[0].content.startswith(sources[0]["content"])
    assert result.citations[0].content == sources[0]["content"]
    assert result.citations[0].truncated is True
    assert result.matches == passages


async def test_default_token_budget_keeps_evidence_beyond_old_character_limit(
    generation_settings, passages, completion,
):
    passages[:] = [
        replace(
            passages[0], chunk_index=index,
            content=f"Passage {index}. " + "Habitação popular e proteção de dados. " * 20,
        )
        for index in range(14)
    ]
    requests = completion("The final passage provides the evidence [14].", citations=[14])

    result = await generation.answer("What does the final passage say?", settings=generation_settings)

    payload = json.loads(requests[0].content)
    system, user = [message["content"] for message in payload["messages"]]
    assert len(system) + len(user) > 6000
    assert len(json.loads(user)["sources"]) == 14
    assert result.citations[0].chunk_index == 13
    assert result.citations[0].content == passages[-1].content
    assert result.citations[0].truncated is False


async def test_history_keeps_recent_complete_turns_as_untrusted_context(
    generation_settings, passages, completion, history_messages,
):
    history = history_messages([f"Previous message {index}" for index in range(24)])
    requests = completion()
    result = await generation.answer("What about booking?", settings=generation_settings, history=history)
    payload = json.loads(requests[0].content)
    prompt = json.loads(payload["messages"][1]["content"])
    assert prompt["history"] == [
        {"role": message.role, "content": message.content} for message in history[-20:]
    ]
    assert len(payload["messages"]) == 2
    assert prompt["question"] == "What about booking?"
    assert prompt["sources"][0]["content"] == passages[0].content
    assert [citation.source_id for citation in result.citations] == ["source-a", "source-b"]


async def test_history_budget_drops_whole_older_turns_and_preserves_source_space(
    generation_settings, passages, completion, history_messages,
):
    history = history_messages(["Old question " * 500, "Old answer " * 500, "Latest question", "Latest answer"])
    passages[0] = replace(passages[0], content='A long "source"\n' * 500)
    requests = completion("Use the current source [1].")
    settings = replace(generation_settings, generation_input_tokens=800)
    result = await generation.answer("Follow up", settings=settings, history=history)
    payload = json.loads(requests[0].content)
    system, user = [message["content"] for message in payload["messages"]]
    prompt = json.loads(user)
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = sum(len(encoding.encode(text)) for text in [system, user])
    tokens += len(encoding.encode(json.dumps(generation._AnswerResponse.model_json_schema(), ensure_ascii=False)))
    assert tokens + 64 <= settings.generation_input_tokens
    assert prompt["history"] == [
        {"role": message.role, "content": message.content} for message in history[-2:]
    ]
    assert prompt["sources"][0]["content"] == result.citations[0].content
    assert result.citations[0].truncated


async def test_history_citations_do_not_authorize_previous_source_ids(
    generation_settings, passages, completion, history_messages,
):
    history = history_messages(["Earlier question", "Earlier answer [99]."])
    completion("Reuse an earlier citation [99].", citations=[99])
    with pytest.raises(generation.GenerationError, match="invalid citations"):
        await generation.answer("Follow up", settings=generation_settings, history=history)


@pytest.mark.parametrize("budget", [1, 100])
async def test_unusable_prompt_budget_never_calls_provider(
    budget, generation_settings, passages, completion,
):
    requests = completion()
    with pytest.raises(ValueError, match="prompt budget"):
        await generation.answer("Question" * 100, settings=replace(generation_settings, generation_input_tokens=budget))
    assert requests == []
