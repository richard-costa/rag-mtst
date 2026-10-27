from __future__ import annotations

import json
from dataclasses import replace

import pytest

from app import generation, llm


@pytest.mark.parametrize(("provider", "url", "token"), [
    ("openai", "https://api.openai.com/v1/responses", "openai-secret"),
    ("deepseek", "https://api.deepseek.com/chat/completions", "deepseek-secret"),
    ("ollama", "http://127.0.0.1:11434/v1/chat/completions", "ollama"),
    ("anthropic", "https://api.anthropic.com/v1/messages", "anthropic-secret"),
])
async def test_generation_routes_providers_and_preserves_citation_provenance(
    provider, url, token, generation_settings, passages, completion,
):
    requests = completion()
    settings = replace(
        generation_settings, generation_provider=provider,
        openai_api_key="openai-secret", deepseek_api_key="deepseek-secret", anthropic_api_key="anthropic-secret",
    )

    result = await generation.answer("What should I do?", settings=settings)

    assert result.text == "Bring identification [1]. Call to book [2]."
    assert result.matches == passages
    assert [(citation.id, citation.source_id, citation.chunk_index) for citation in result.citations] == [
        (1, "source-a", 0), (2, "source-b", 3),
    ]
    assert result.citations[0].content == passages[0].content
    assert result.citations[0].source_reference == "/tmp/housing.md"
    assert result.citations[0].truncated is False
    assert len(requests) == 1
    assert str(requests[0].url) == url
    assert requests[0].headers["authorization"] == f"Bearer {token}"
    payload = json.loads(requests[0].content)
    assert payload["model"] == "test-model"
    token_parameter = "max_output_tokens" if provider == "openai" else "max_tokens"
    assert payload[token_parameter] == 4000
    system = llm.system_prompt(generation._SYSTEM_PROMPT, generation._AnswerResponse, provider)
    if provider == "anthropic":
        assert payload["system"] == system
        assert payload["output_config"]["format"]["schema"]["required"] == ["text", "citations"]
        user = payload["messages"][0]["content"][0]["text"]
    elif provider == "openai":
        assert payload["store"] is False
        assert "previous_response_id" not in payload and "conversation" not in payload
        assert payload["instructions"] == system
        assert payload["text"]["format"]["type"] == "json_schema"
        assert payload["text"]["format"]["strict"] is True
        assert payload["text"]["format"]["schema"]["required"] == ["text", "citations"]
        user = payload["input"][0]["content"][0]["text"]
    else:
        assert payload["stream"] is False
        assert payload["messages"][0] == {"role": "system", "content": system}
        assert payload["response_format"]["type"] == ("json_object" if provider == "deepseek" else "json_schema")
        user = payload["messages"][1]["content"]
    assert json.loads(user) == {
        "question": "What should I do?",
        "sources": [{"id": 1, "content": passages[0].content}, {"id": 2, "content": passages[1].content}],
    }


@pytest.mark.parametrize(("text", "finish"), [
    ("", "stop"),
    (None, "stop"),
    ("Incomplete [1]", "length"),
    ("Filtered [1]", "content_filter"),
])
async def test_invalid_generation_is_not_returned_as_an_answer(
    text, finish, generation_settings, passages, completion,
):
    completion(text, finish=finish)
    with pytest.raises(generation.GenerationError):
        await generation.answer("Question", settings=generation_settings)


@pytest.mark.parametrize("changes", [
    {"status": "failed", "error": {"code": "server_error", "message": "private provider detail"}},
    {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
    {"status": "incomplete", "incomplete_details": {"reason": "content_filter"}},
    {"output": []},
    {"error": {"code": "server_error", "message": "private provider detail"}},
    {"incomplete_details": {"reason": "max_output_tokens"}},
])
async def test_unusable_openai_responses_are_rejected_without_fallback(
    changes, generation_settings, passages, completion,
):
    requests = completion(response_changes=changes)
    settings = replace(generation_settings, generation_provider="openai", openai_api_key="key")
    with pytest.raises(generation.GenerationError) as error:
        await generation.answer("Question", settings=settings)
    assert "private provider detail" not in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize("failure", ["incomplete_message", "mixed_refusal"])
async def test_openai_rejects_unusable_messages_even_with_parsed_output(
    failure, generation_settings, passages, completion, openai_response,
):
    body = openai_response(json.dumps({"text": "Supported [1].", "citations": [1]}))
    message = body["output"][0]
    if failure == "incomplete_message":
        message["status"] = "incomplete"
    else:
        message["content"].append({"type": "refusal", "refusal": "private provider detail"})
    requests = completion(response_changes=body)
    settings = replace(generation_settings, generation_provider="openai", openai_api_key="key")
    with pytest.raises(generation.GenerationError, match="filtered or incomplete") as error:
        await generation.answer("Question", settings=settings)
    assert "private provider detail" not in str(error.value)
    assert len(requests) == 1


async def test_openai_reads_typed_message_after_reasoning_output(
    generation_settings, passages, completion, openai_response,
):
    body = openai_response(json.dumps({"text": "Supported [1].", "citations": [1]}))
    body["output"].insert(0, {"id": "reasoning", "type": "reasoning", "summary": []})
    requests = completion(response_changes=body)
    settings = replace(generation_settings, generation_provider="openai", openai_api_key="key")
    result = await generation.answer("Question", settings=settings)
    assert result.text == "Supported [1]."
    assert [citation.id for citation in result.citations] == [1]
    assert len(requests) == 1


@pytest.mark.parametrize("provider", ["openai", "deepseek", "ollama", "anthropic"])
@pytest.mark.parametrize("raw", [
    "private malformed JSON", '{"text":"private missing citations"}',
    '{"text":"private wrong type","citations":["1"]}',
    '{"text":"private extra field","citations":[],"extra":true}',
])
async def test_invalid_provider_records_are_sanitized_without_fallback(
    provider, raw, generation_settings, passages, completion,
):
    requests = completion(raw=raw)
    settings = replace(
        generation_settings, generation_provider=provider, openai_api_key="key",
        deepseek_api_key="key", anthropic_api_key="key",
    )
    with pytest.raises(generation.GenerationError) as error:
        await generation.answer("Question", settings=settings)
    assert "private" not in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize("provider", ["openai", "deepseek", "ollama", "anthropic"])
async def test_provider_failure_does_not_leak_details_or_fall_back(
    generation_settings, passages, completion, provider,
):
    requests = completion(status=503)
    settings = replace(
        generation_settings, generation_provider=provider, openai_api_key="key",
        deepseek_api_key="key", anthropic_api_key="key",
    )
    with pytest.raises(generation.GenerationError, match="generation API request failed") as caught:
        await generation.answer("Question", settings=settings)
    assert "private provider detail" not in str(caught.value)
    assert len(requests) == 1


async def test_no_matches_does_not_call_generation(generation_settings, passages, completion):
    passages.clear()
    requests = completion()
    result = await generation.answer("Question", settings=generation_settings)
    assert result.matches == result.citations == []
    assert "could not find" in result.text
    assert requests == []


@pytest.mark.parametrize("choices", [[], None, "malformed"])
async def test_malformed_completion_choices_are_provider_errors(
    choices, generation_settings, passages, completion,
):
    completion(choices=choices)
    with pytest.raises(generation.GenerationError):
        await generation.answer("Question", settings=generation_settings)


@pytest.mark.parametrize(("changes", "message"), [
    ({"generation_provider": "other"}, "RAG_GENERATION_PROVIDER"),
    ({"generation_model": None}, "RAG_GENERATION_MODEL"),
    ({"generation_model": "  "}, "RAG_GENERATION_MODEL"),
    ({"generation_provider": "openai"}, "OPENAI_API_KEY"),
    ({"generation_provider": "deepseek"}, "DEEPSEEK_API_KEY"),
    ({"generation_provider": "anthropic"}, "ANTHROPIC_API_KEY"),
    ({"generation_input_tokens": 0}, "positive"),
    ({"generation_max_tokens": 0}, "positive"),
    ({"generation_timeout_seconds": 0}, "positive"),
])
async def test_generation_rejects_invalid_configuration_before_calling_providers(
    changes, message, generation_settings, passages, completion,
):
    requests = completion()
    with pytest.raises(ValueError, match=message):
        await generation.answer("Question", settings=replace(generation_settings, **changes))
    assert requests == []


async def test_generation_endpoint_override_does_not_change_embedding_settings(
    generation_settings, passages, completion,
):
    requests = completion()
    settings = replace(
        generation_settings, generation_provider="openai", openai_api_key="key",
        generation_base_url="https://generation.example/v1",
        openai_base_url="https://embeddings.example/v1",
    )
    await generation.answer("Question", settings=settings)
    assert str(requests[0].url) == "https://generation.example/v1/responses"
    assert settings.openai_base_url == "https://embeddings.example/v1"
