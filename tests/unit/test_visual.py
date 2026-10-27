from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import pytest

from app.chunking import chunk_markdown
from app.extraction import extract_source, visual


async def test_visual_uses_real_images_and_keeps_blank_page_order(
    vision_reply, vision_settings, pdf_document
):
    requests = vision_reply(
        [
            {"markdown": "# First page", "blank": False},
            {"markdown": "", "blank": True},
            {
                "markdown": "| Material | Count |\n|---|---|\n| Bricks | 42 |",
                "blank": False,
            },
        ]
    )
    result = await visual.extract_with_visual(
        pdf_document(("First", "", "Table")),
        ".pdf",
        settings=vision_settings,
    )

    assert [page.number for page in result.pages] == [1, 2, 3]
    assert result.pages[1].text == ""
    assert result.text == "\n\n".join(page.text for page in result.pages)
    assert result.profile["model"] == "vision-model"
    assert "version" not in result.profile
    for number, request in enumerate(requests, start=1):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["Authorization"] == "Bearer private-vision-key"
        payload = json.loads(request.content)
        assert payload["model"] == "vision-model"
        assert payload["max_output_tokens"] == visual.MAX_OUTPUT_TOKENS
        assert payload["store"] is False
        response_format = payload["text"]["format"]
        assert response_format["type"] == "json_schema"
        assert response_format["strict"] is True
        schema = response_format["schema"]
        assert schema["required"] == ["markdown", "blank"]
        assert schema["additionalProperties"] is False
        assert schema["properties"]["markdown"]["type"] == "string"
        assert schema["properties"]["blank"]["type"] == "boolean"
        assert payload["instructions"] == visual._SYSTEM_PROMPT
        parts = payload["input"][0]["content"]
        assert [part["type"] for part in parts] == ["input_text", "input_image"]
        assert json.loads(parts[0]["text"])["page"] == number
        image = base64.b64decode(parts[1]["image_url"].split(",", 1)[1], validate=True)
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
    context = json.loads(
        json.loads(requests[1].content)["input"][0]["content"][0]["text"]
    )
    assert context["previous_page_excerpt"] == "# First page"


async def test_visual_heading_continuations_keep_chunk_hierarchy(
    vision_reply, vision_settings, pdf_document
):
    first_page = "# Installation\n\nOverview.\n\n## Database\n\nDatabase settings."
    second_page = "Continued database settings.\n\n# Operations\n\nRuntime settings."
    requests = vision_reply(
        [
            {"markdown": first_page, "blank": False},
            {"markdown": second_page, "blank": False},
        ]
    )
    result = await extract_source(
        pdf_document(("Installation", "Operations")),
        ".pdf",
        settings=vision_settings,
        extraction_method="visual",
    )

    chunks = chunk_markdown(result.text, chunk_size=200, pages=result.pages)

    assert [chunk.metadata["headings"] for chunk in chunks] == [
        ["Installation"],
        ["Installation", "Database"],
        ["Operations"],
    ]
    assert chunks[1].metadata["source_pages"] == {
        "kind": "page",
        "start": 1,
        "end": 2,
        "scope": "body",
    }
    assert "Continued database settings." in chunks[1].content
    assert chunks[2].page_number == 2
    context = json.loads(
        json.loads(requests[1].content)["input"][0]["content"][0]["text"]
    )
    assert context["previous_page_excerpt"] == first_page


@pytest.mark.parametrize(
    "page, finish, usage",
    [
        ({"markdown": "", "blank": False}, "stop", True),
        ({"markdown": "invented", "blank": True}, "stop", True),
        ({"markdown": "partial", "blank": False}, "length", True),
        ({"markdown": "filtered", "blank": False}, "content_filter", True),
        ({"markdown": "missing usage", "blank": False}, "stop", False),
        ({"markdown": 123, "blank": False}, "stop", True),
        ({"markdown": "text", "blank": "false"}, "stop", True),
        ({"markdown": "text", "blank": False, "extra": "unexpected"}, "stop", True),
        ({"markdown": "missing blank"}, "stop", True),
        ("invalid record", "stop", True),
    ],
)
async def test_unusable_visual_output_is_rejected(
    vision_reply, vision_settings, pdf_document, page, finish, usage
):
    requests = vision_reply([page], finish=finish, usage=usage)
    with pytest.raises(ValueError):
        await visual.extract_with_visual(
            pdf_document(), ".pdf", settings=vision_settings
        )
    assert len(requests) == 1


async def test_structured_validation_errors_are_sanitized(
    vision_reply, vision_settings, pdf_document
):
    requests = vision_reply([None], raw="private malformed provider content")
    with pytest.raises(ValueError, match="invalid response record") as error:
        await visual.extract_with_visual(
            pdf_document(), ".pdf", settings=vision_settings
        )
    assert "private malformed provider content" not in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "provider, endpoint",
    [
        ("openai", "https://api.openai.com/v1/responses"),
        ("deepseek", "https://api.deepseek.com/chat/completions"),
        ("ollama", "http://127.0.0.1:11434/v1/chat/completions"),
        ("anthropic", "https://api.anthropic.com/v1/messages"),
    ],
)
async def test_visual_provider_paths_share_page_model(
    vision_reply,
    vision_settings,
    pdf_document,
    provider,
    endpoint,
):
    requests = vision_reply([{"markdown": "# Provider page", "blank": False}])
    settings = replace(
        vision_settings,
        visual_provider=provider,
        deepseek_api_key="deepseek-key",
        anthropic_api_key="anthropic-key",
    )
    result = await visual.extract_with_visual(pdf_document(), ".pdf", settings=settings)
    assert result.pages[0].text == "# Provider page"
    assert result.profile["engine"] == provider
    assert len(requests) == 1
    assert str(requests[0].url) == endpoint
    payload = json.loads(requests[0].content)
    if provider == "anthropic":
        assert requests[0].headers["authorization"] == "Bearer anthropic-key"
        assert payload["output_config"]["format"]["schema"]["required"] == [
            "markdown",
            "blank",
        ]
        assert (
            payload["messages"][0]["content"][1]["source"]["media_type"] == "image/png"
        )
    elif provider == "openai":
        assert payload["store"] is False
        assert payload["text"]["format"]["schema"]["required"] == ["markdown", "blank"]
        assert payload["input"][0]["content"][1]["type"] == "input_image"
    else:
        assert payload["response_format"]["type"] == (
            "json_object" if provider == "deepseek" else "json_schema"
        )
        assert payload["messages"][1]["content"][1]["type"] == "image_url"
        if provider == "deepseek":
            assert (
                '"required": ["markdown", "blank"]' in payload["messages"][0]["content"]
            )
    assert (
        payload["max_output_tokens" if provider == "openai" else "max_tokens"]
        == visual.MAX_OUTPUT_TOKENS
    )


async def test_structured_refusal_is_rejected_without_retry(
    vision_reply, vision_settings, pdf_document
):
    requests = vision_reply([None], refusal="private provider refusal")
    with pytest.raises(ValueError, match="filtered or incomplete") as error:
        await visual.extract_with_visual(
            pdf_document(), ".pdf", settings=vision_settings
        )
    assert "private provider refusal" not in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize("tokens", [0, visual.MAX_OUTPUT_TOKENS + 1])
async def test_structured_output_still_requires_valid_usage(
    vision_reply, vision_settings, pdf_document, tokens
):
    requests = vision_reply([{"markdown": "Text", "blank": False}], tokens=tokens)
    with pytest.raises(ValueError, match="output-token usage"):
        await visual.extract_with_visual(
            pdf_document(), ".pdf", settings=vision_settings
        )
    assert len(requests) == 1


async def test_visual_budget_is_reserved_before_next_call(
    monkeypatch, vision_reply, vision_settings, pdf_document
):
    monkeypatch.setattr(visual, "DOCUMENT_OUTPUT_TOKENS", visual.MAX_OUTPUT_TOKENS)
    requests = vision_reply(
        [{"markdown": "First", "blank": False}], tokens=visual.MAX_OUTPUT_TOKENS
    )
    with pytest.raises(ValueError, match="output-token budget"):
        await visual.extract_with_visual(
            pdf_document(("First", "Second")), ".pdf", settings=vision_settings
        )
    assert len(requests) == 1


@pytest.mark.parametrize("provider", ["openai", "deepseek", "ollama", "anthropic"])
async def test_provider_errors_are_sanitized_and_not_retried(
    vision_reply, vision_settings, pdf_document, provider
):
    requests = vision_reply([], status=400)
    settings = replace(
        vision_settings,
        visual_provider=provider,
        deepseek_api_key="key",
        anthropic_api_key="key",
    )
    with pytest.raises(ValueError, match="API request failed") as error:
        await visual.extract_with_visual(pdf_document(), ".pdf", settings=settings)
    assert "private provider detail" not in str(error.value)
    assert len(requests) == 1


async def test_visual_endpoint_is_independent_of_generation(
    vision_reply, vision_settings, pdf_document
):
    requests = vision_reply([{"markdown": "Text", "blank": False}])
    settings = replace(
        vision_settings,
        visual_base_url="http://127.0.0.1:9876/v1",
        openai_base_url="https://embeddings.example/v1",
        generation_base_url="https://answers.example/v1",
    )
    result = await visual.extract_with_visual(pdf_document(), ".pdf", settings=settings)
    assert str(requests[0].url) == "http://127.0.0.1:9876/v1/responses"
    assert result.profile["endpoint"] == "http://127.0.0.1:9876/v1"
    assert "private-vision-key" not in json.dumps(result.profile)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://private-key@example.com/v1",
        "https://example.com/v1?api_key=private-key",
        "https://example.com/v1#private-key",
        "ftp://example.com",
        "https://[invalid",
    ],
)
def test_visual_profile_does_not_store_credentials(vision_settings, endpoint):
    with pytest.raises(ValueError) as error:
        visual.get_extraction_profile(
            ".pdf", replace(vision_settings, visual_base_url=endpoint)
        )
    assert "private-key" not in str(error.value)


async def test_oversized_source_is_rejected_before_rendering(
    monkeypatch, vision_settings
):
    monkeypatch.setattr(visual, "MAX_SOURCE_BYTES", 2)
    with pytest.raises(ValueError, match="20 MiB"):
        await visual.extract_with_visual(b"large", ".pdf", settings=vision_settings)


async def test_visual_timeout_cleans_up(
    monkeypatch, vision_reply, vision_settings, pdf_document
):
    async def block(source, number, directory):
        await asyncio.Event().wait()

    vision_reply([])
    monkeypatch.setattr(visual, "_render_page", block)
    monkeypatch.setattr(visual, "DOCUMENT_TIMEOUT_SECONDS", 0.1)
    with pytest.raises(ValueError, match="timed out"):
        await visual.extract_with_visual(
            pdf_document(), ".pdf", settings=vision_settings
        )


async def test_all_blank_visual_document_is_not_indexable(
    vision_reply, vision_settings, pdf_document
):
    vision_reply([{"markdown": "", "blank": True}])
    with pytest.raises(ValueError, match="no searchable content"):
        await visual.extract_with_visual(
            pdf_document(("",)), ".pdf", settings=vision_settings
        )


async def test_malformed_pdf_fails_without_model_calls(vision_reply, vision_settings):
    requests = vision_reply([])
    with pytest.raises(ValueError, match="tool failed"):
        await visual.extract_with_visual(b"not a pdf", ".pdf", settings=vision_settings)
    assert not requests


@pytest.mark.parametrize(
    "changes, suffix, content, message",
    [
        ({"visual_model": None}, ".pdf", b"pdf", "RAG_VISUAL_MODEL"),
        ({"visual_model": " "}, ".pdf", b"pdf", "RAG_VISUAL_MODEL"),
        ({"openai_api_key": None}, ".pdf", b"pdf", "OPENAI_API_KEY"),
        ({}, ".txt", b"text", "only PDF"),
        ({}, ".pdf", b"", "nonempty source"),
    ],
)
async def test_invalid_visual_input_fails_before_rendering(
    monkeypatch, vision_settings, changes, suffix, content, message
):
    renderer = AsyncMock(side_effect=AssertionError("Must not render"))
    monkeypatch.setattr(visual, "_page_count", renderer)
    with pytest.raises(ValueError, match=message):
        await visual.extract_with_visual(
            content, suffix, settings=replace(vision_settings, **changes)
        )
    renderer.assert_not_awaited()


async def test_visual_pdf_does_not_need_office(
    monkeypatch, vision_reply, vision_settings, pdf_document
):
    converter = Mock(side_effect=AssertionError("PDF must not use Office"))
    monkeypatch.setattr(visual, "_convert_office_to_pdf", converter)
    vision_reply([{"markdown": "PDF text", "blank": False}])
    await visual.extract_with_visual(pdf_document(), ".pdf", settings=vision_settings)
    converter.assert_not_called()


async def test_facade_selects_visual_without_parser_fallback(
    monkeypatch, vision_reply, vision_settings, pdf_document
):
    parser = Mock(
        side_effect=AssertionError("Visual extraction must not call the parser")
    )
    monkeypatch.setattr("app.extraction.parser.extract_with_parser", parser)
    requests = vision_reply([], status=400)
    with pytest.raises(ValueError, match="API request failed"):
        await extract_source(
            pdf_document(), ".pdf", settings=vision_settings, extraction_method="visual"
        )
    assert len(requests) == 1
    parser.assert_not_called()


@pytest.mark.parametrize("suffix, kind", [(".docx", "page"), (".pptx", "slide")])
async def test_visual_office_conversion_retains_page_kind(
    monkeypatch, vision_reply, vision_settings, pdf_document, suffix, kind
):
    converter = Mock(return_value=pdf_document())
    monkeypatch.setattr(visual, "_convert_office_to_pdf", converter)
    vision_reply([{"markdown": "Office table", "blank": False}])
    result = await visual.extract_with_visual(
        b"office", suffix, settings=vision_settings
    )
    assert result.pages[0].kind == kind
    converter.assert_called_once_with(b"office", suffix, host="127.0.0.1", port=2003)
