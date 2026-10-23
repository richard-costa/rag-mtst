from __future__ import annotations

import json
import re

import pytest
from anthropic import AsyncAnthropic
from httpx import AsyncClient, MockTransport, Response
from httpx2 import AsyncClient as AnthropicHTTPClient
from httpx2 import MockTransport as AnthropicTransport
from httpx2 import Response as AnthropicResponse
from openai import AsyncOpenAI

from app import generation, llm
from app.config import Settings
from app.retrieval import SearchResult


@pytest.fixture
def generation_settings():
    return Settings(generation_provider="ollama", generation_model="test-model")


@pytest.fixture
def passages(monkeypatch):
    matches = [
        SearchResult("source-a", "Housing", "/tmp/housing.md", 0, "Bring identification.", 0.9),
        SearchResult("source-b", "Booking", "/tmp/booking.md", 3, "Call to book.", None),
    ]

    async def search(*args, **kwargs):
        return matches

    monkeypatch.setattr(generation, "search", search)
    return matches


@pytest.fixture
def completion(monkeypatch, openai_response):
    requests = []

    def install(
        text="Bring identification [1]. Call to book [2].", *, status=200, finish="stop",
        choices="normal", citations=None, raw=None, refusal=None, response_changes=None,
    ):
        def respond(request):
            requests.append(request)
            native = request.url.path.endswith("/messages")
            response_type = AnthropicResponse if native else Response
            if status != 200:
                return response_type(status, json={"error": {"message": "private provider detail"}})
            references = citations if citations is not None else [int(value) for value in re.findall(r"\[([12])\]", text or "")]
            content = raw if raw is not None else json.dumps({"text": text, "citations": references})
            if native:
                return AnthropicResponse(200, json={
                    "id": "message", "type": "message", "role": "assistant", "model": "test-model",
                    "content": [{"type": "text", "text": content}],
                    "stop_reason": "end_turn" if finish == "stop" else finish, "stop_sequence": None,
                    "usage": {"input_tokens": 100, "output_tokens": 32},
                })
            if request.url.path.endswith("/responses"):
                body = openai_response(content, finish=finish, refusal=refusal)
                body.update(response_changes or {})
                return Response(200, json=body)
            return Response(200, json={
                "id": "completion", "object": "chat.completion", "created": 0,
                "model": "test-model", "choices": [{
                    "index": 0, "finish_reason": finish,
                    "message": {"role": "assistant", "content": content, "refusal": refusal},
                }] if choices == "normal" else choices,
            })

        def client(**kwargs):
            assert kwargs["max_retries"] == 0
            return AsyncOpenAI(**kwargs, http_client=AsyncClient(transport=MockTransport(respond)))

        def anthropic_client(**kwargs):
            assert kwargs["max_retries"] == 0
            return AsyncAnthropic(**kwargs, http_client=AnthropicHTTPClient(transport=AnthropicTransport(respond)))

        monkeypatch.setattr(llm, "AsyncOpenAI", client)
        monkeypatch.setattr(llm, "AsyncAnthropic", anthropic_client)
        return requests

    return install


@pytest.fixture
def vision_settings():
    return Settings(visual_model="vision-model", openai_api_key="private-vision-key")
