from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace

from httpx import AsyncClient, MockTransport, Response
import pytest

from app import embeddings
from app.chunking import chunk_markdown
from app.config import Settings
from app.extraction import ExtractedContent, ExtractedPage
from app.storage.records import ChunkInput


@pytest.fixture
def local_model(monkeypatch):
    def tokenize(text, *, truncation, add_special_tokens):
        assert truncation is False
        assert add_special_tokens is True
        return {"input_ids": [101, *list(text), 102]}

    model = SimpleNamespace(
        max_seq_length=34,
        tokenizer=tokenize,
        default_prompt_name=None,
        prompts={"document": "passage: "},
        _first_module=lambda: SimpleNamespace(do_lower_case=False),
    )
    monkeypatch.setattr(embeddings, "_load_local_model", lambda name: model)
    return model


@pytest.mark.parametrize("text", [
    "Primeira frase. " * 12 + "Habita\u00e7\u00e3o digna para todos.",
    "```python\n" + "print('preserve all code')\n" * 8 + "```",
    "| Name | Value |\n| --- | --- |\n" + "| housing | guaranteed |\n" * 8,
    "- " + "A long list item with nested content. " * 8,
    "\u4f4f\u5b85\U0001f3e0" * 40,
    "A" * 150 + "  \n\t",
])
async def test_local_chunk_preparation_preserves_all_text_and_provenance(text, local_model):
    chunks = chunk_markdown("# Housing\n\n" + text, chunk_size=1000)
    assert len(chunks) == 1
    original = chunks[0]

    prepared = await embeddings.prepare_chunks_for_embedding(
        chunks, settings=Settings(embedding_provider="local"),
    )

    assert len(prepared) > 1
    assert "".join(chunk.content for chunk in prepared) == original.content
    offset = 0
    for split_index, chunk in enumerate(prepared):
        assert chunk.content
        assert len(local_model.tokenizer(
            chunk.content.strip(), truncation=False, add_special_tokens=True,
        )["input_ids"]) <= local_model.max_seq_length
        assert chunk.metadata == {
            **original.metadata,
            "parent_chunk_index": 0,
            "split_index": split_index,
            "start_char": offset,
            "end_char": offset + len(chunk.content),
        }
        assert original.content[chunk.metadata["start_char"]:chunk.metadata["end_char"]] == chunk.content
        offset += len(chunk.content)
    assert "parent_chunk_index" not in original.metadata


async def test_local_chunk_preparation_keeps_fitting_chunks_and_page_numbers(local_model):
    fitting = ChunkInput("x" * 32, {"heading": "Title"}, page_number=3)
    oversized = ChunkInput("z" * 70, {"heading": "Other"}, page_number=4)
    chunks = [fitting, oversized, fitting]

    prepared = await embeddings.prepare_chunks_for_embedding(
        chunks, settings=Settings(embedding_provider="local"),
    )

    assert prepared[0] is fitting
    assert prepared[-1] is fitting
    assert all(chunk.page_number == 4 for chunk in prepared[1:-1])
    assert all(chunk.metadata["parent_chunk_index"] == 1 for chunk in prepared[1:-1])


async def test_local_page_ranges_are_explicitly_inherited_from_parent_body(local_model):
    extracted = ExtractedContent.from_pages((
        ExtractedPage(1, "# Heading\n\n" + "First body. " * 8),
        ExtractedPage(2, "Second body. " * 8),
    ), format="pdf", profile={"method": "test"})
    chunks = chunk_markdown(extracted.text, 1000, pages=extracted.pages)
    chunks = [replace(chunk, metadata={**chunk.metadata, "extraction": extracted.profile}) for chunk in chunks]
    assert len(chunks) == 1
    prepared = await embeddings.prepare_chunks_for_embedding(chunks, settings=Settings(embedding_provider="local"))

    assert len(prepared) > 1
    assert "".join(chunk.content for chunk in prepared) == chunks[0].content
    for chunk in prepared:
        assert chunk.metadata["source_pages"] == {"kind": "page", "start": 1, "end": 2, "scope": "parent_body"}
        assert chunk.metadata["extraction"] == extracted.profile
        assert chunk.metadata["parent_chunk_index"] == 0
        assert chunk.page_number is None
    assert chunks[0].metadata["source_pages"]["scope"] == "body"


async def test_local_chunk_preparation_accounts_for_default_prompt(local_model):
    local_model.default_prompt_name = "document"
    original = ChunkInput("x" * 32, {})

    prepared = await embeddings.prepare_chunks_for_embedding(
        [original], settings=Settings(embedding_provider="local"),
    )

    assert len(prepared) > 1
    assert "".join(chunk.content for chunk in prepared) == original.content
    assert all(len(local_model.tokenizer(
        "passage: " + chunk.content, truncation=False, add_special_tokens=True,
    )["input_ids"]) <= local_model.max_seq_length for chunk in prepared)


async def test_hosted_and_empty_preparation_do_not_load_a_local_model(monkeypatch):
    def unexpected_load(name):
        pytest.fail("No local model should be loaded")

    monkeypatch.setattr(embeddings, "_load_local_model", unexpected_load)
    chunks = [ChunkInput("long text " * 100, {})]
    assert await embeddings.prepare_chunks_for_embedding(chunks, settings=Settings()) is chunks
    assert await embeddings.prepare_chunks_for_embedding(
        [], settings=Settings(embedding_provider="local"),
    ) == []


@pytest.mark.parametrize(("text", "first_piece"), [
    ("first line\n" + "x" * 40, "first line\n"),
    ("first words " + "x" * 40, "first words "),
    ("x" * 33, "x" * 32),
])
async def test_local_overflow_prefers_lines_then_whitespace_then_characters(text, first_piece, local_model):
    prepared = await embeddings.prepare_chunks_for_embedding(
        [ChunkInput(text, {})], settings=Settings(embedding_provider="local"),
    )

    assert prepared[0].content == first_piece
    assert "".join(chunk.content for chunk in prepared) == text


async def test_local_token_measurement_matches_normalization(local_model):
    measured = []
    local_model._first_module = lambda: SimpleNamespace(do_lower_case=True)

    def tokenize(text, **kwargs):
        measured.append(text)
        return {"input_ids": [1, 2, 3]}

    local_model.tokenizer = tokenize
    local_model.default_prompt_name = "document"
    assert embeddings._local_token_count(local_model, "  TEXT  ") == 3
    assert measured == ["passage:   text"]


async def test_unprepared_local_overflow_is_rejected_before_inference(local_model):
    def unexpected_encode(*args, **kwargs):
        pytest.fail("Oversized input must not reach inference")

    local_model.encode = unexpected_encode
    with pytest.raises(ValueError, match=r"input 0 uses 35 tokens.*allows 34"):
        await embeddings.embed_texts(["x" * 33], settings=Settings(embedding_provider="local"))


@pytest.mark.parametrize("limit", [None, 0, -1])
async def test_local_preparation_requires_a_real_positive_model_limit(limit, local_model):
    local_model.max_seq_length = limit
    with pytest.raises(ValueError, match="positive max_seq_length"):
        await embeddings.prepare_chunks_for_embedding(
            [ChunkInput("hello", {})], settings=Settings(embedding_provider="local"),
        )


async def test_local_preparation_cannot_silently_drop_an_unencodable_character(local_model):
    local_model.max_seq_length = 2
    with pytest.raises(ValueError, match="cannot fit a source character"):
        await embeddings.prepare_chunks_for_embedding(
            [ChunkInput("x", {})], settings=Settings(embedding_provider="local"),
        )


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("openai", "text-embedding-3-small"),
        ("local", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
    ],
)
def test_provider_defaults_and_model_override(provider, model) -> None:
    settings = Settings(embedding_provider=provider)
    assert settings.embedding_model_name == model
    assert replace(settings, embedding_model="another-model").embedding_model_name == "another-model"


@pytest.mark.parametrize("endpoint", [
    "ftp://example.com/v1",
    "https:///v1",
    "https://private@example.com/v1",
    "https://private:key@example.com/v1",
    "https://example.com/v1?api_key=private",
    "https://example.com/v1#private",
])
async def test_invalid_embedding_endpoint_is_rejected_before_creating_a_client(monkeypatch, endpoint) -> None:
    def unexpected_client(**kwargs):
        pytest.fail("Invalid settings must not create an embedding client")

    monkeypatch.setattr(embeddings, "AsyncOpenAI", unexpected_client)
    settings = Settings(openai_api_key="test-key", openai_base_url=endpoint)

    with pytest.raises(ValueError, match="embedding endpoint"):
        await embeddings.embed_texts(["text"], settings=settings)


@pytest.mark.parametrize("base_url", [None, "http://embeddings.test/v1"])
async def test_openai_batches_and_restores_input_order(monkeypatch, base_url) -> None:
    requests = []
    request_urls = []
    monkeypatch.setenv("OPENAI_BASE_URL", "http://unexpected.test/v1")

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        request_urls.append(str(request.url))
        return Response(200, json={
            "data": [
                {"index": index, "embedding": [float(text), 1.0], "object": "embedding"}
                for index, text in reversed(list(enumerate(body["input"])))
            ],
            "model": body["model"],
            "object": "list",
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        })

    client_class = embeddings.AsyncOpenAI
    monkeypatch.setattr(
        embeddings,
        "AsyncOpenAI",
        lambda **kwargs: client_class(
            **kwargs, http_client=AsyncClient(transport=MockTransport(respond))
        ),
    )
    settings = Settings(openai_api_key="test-key", openai_base_url=base_url)
    vectors = await embeddings.embed_texts([str(index) for index in range(130)], settings=settings)

    assert vectors == [[float(index), 1.0] for index in range(130)]
    assert [len(body["input"]) for body in requests] == [128, 2]
    assert all(body["model"] == "text-embedding-3-small" for body in requests)
    assert request_urls == [f"{base_url or 'https://api.openai.com/v1'}/embeddings"] * 2


async def test_local_model_encodes_without_api_credentials(local_model) -> None:
    calls = []

    def encode(texts, **kwargs):
        calls.append((texts, kwargs))
        return SimpleNamespace(tolist=lambda: [[1.0, 0.0], [0.0, 1.0]])

    local_model.encode = encode
    vectors = await embeddings.embed_texts(["ola", "hello"], settings=Settings(embedding_provider="local"))

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert calls[0][0] == ["ola", "hello"]
    assert calls[0][1]["normalize_embeddings"] is True


async def test_empty_input_needs_no_credentials() -> None:
    assert await embeddings.embed_texts([], settings=Settings()) == []


async def test_missing_openai_key_is_actionable() -> None:
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        await embeddings.embed_texts(["hello"], settings=Settings())


async def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="RAG_EMBEDDING_PROVIDER"):
        await embeddings.embed_texts(["hello"], settings=Settings(embedding_provider="unknown"))


@pytest.mark.parametrize("vectors", [[], [[]], [[0.0, 0.0]], [[float("nan")]], [[float("inf")]], [[1.0], [1.0, 2.0]]])
def test_invalid_vectors_are_rejected(vectors) -> None:
    with pytest.raises(embeddings.EmbeddingError):
        embeddings._validate_vectors(vectors, 2 if len(vectors) == 2 else 1)
