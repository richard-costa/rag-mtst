from __future__ import annotations

from dataclasses import replace

import pytest

from app import retrieval
from app.retrieval import search
from app.storage import documents
from app.storage.records import ChunkInput

pytestmark = pytest.mark.usefixtures("deterministic_embeddings")


@pytest.mark.parametrize("method", ["cosine", "window", "lexical", "hybrid"])
async def test_retrieval_preserves_non_file_references(settings, storage, method):
    reference = "https://example.org/policies/handbook?lang=en#section"
    metadata = {
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model_name,
    }
    source = await documents.insert_source_with_chunks(
        storage,
        tenant_id=settings.tenant_id,
        source_type="url",
        reference=reference,
        mime_type="text/plain",
        content_hash="url-reference",
        chunks=[
            ChunkInput("token", metadata, embedding=[1.0, 1.0, 0.0]),
            ChunkInput("Neighboring context", metadata, embedding=[1.0, 0.0, 0.0]),
        ],
    )

    matches = await search(
        "token", method=method, limit=1, window=1, settings=settings, storage=storage
    )

    assert len(matches) == (2 if method == "window" else 1)
    assert all(match.source_id == str(source.id) for match in matches)
    assert all(
        match.source_reference == reference and match.source_title == reference
        for match in matches
    )
    if method == "window":
        assert matches[1].score is None


async def test_cosine_uses_direction_not_vector_length_and_filters_models(
    store_vectors, settings, storage
):
    source = await store_vectors(
        [
            [100.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [-1.0, -1.0, 0.0],
            None,
            [0.0, 0.0, 0.0],
        ]
    )
    await store_vectors([[1.0, 1.0, 0.0]], tenant_id="other-tenant")
    await store_vectors([[1.0, 1.0]], model="other-model")

    results = await search(
        "token", method="cosine", limit=10, settings=settings, storage=storage
    )

    assert [result.chunk_index for result in results] == [1, 0, 2]
    assert all(result.source_id == str(source.id) for result in results)
    assert [result.score for result in results] == pytest.approx([1.0, 2**-0.5, -1.0])


async def test_default_windows_deduplicate_overlap_and_keep_seed_scores(
    store_vectors, settings, storage
):
    source = await store_vectors(
        [
            [1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [1.0, 0.9, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
        ]
    )

    results = await search("token", limit=2, settings=settings, storage=storage)

    assert [result.chunk_index for result in results] == [0, 1, 2, 3, 4, 5]
    assert len({(result.source_id, result.chunk_index) for result in results}) == 6
    assert all(result.source_id == str(source.id) for result in results)
    assert results[2].score == pytest.approx(1.0)
    assert results[3].score is not None
    assert all(
        result.score is None for result in results if result.chunk_index not in {2, 3}
    )


@pytest.mark.parametrize("seed_index, expected", [(0, [0, 1, 2]), (4, [2, 3, 4])])
async def test_windows_stop_at_source_edges(
    store_vectors, settings, storage, seed_index, expected
):
    vectors = [[1.0, 0.0, 0.0] for index in range(5)]
    vectors[seed_index] = [1.0, 1.0, 0.0]
    source = await store_vectors(vectors)
    await store_vectors([[1.0, 0.0, 0.0]] * 5)

    results = await search("token", limit=1, settings=settings, storage=storage)

    assert [result.chunk_index for result in results] == expected
    assert all(result.source_id == str(source.id) for result in results)


@pytest.mark.parametrize(
    ("seed_indices", "expected"),
    [
        ([7, 1], [5, 6, 7, 8, 9, 0, 1, 2, 3]),
        ([7, 4], list(range(2, 10))),
        ([7, 1, 4], list(range(10))),
    ],
)
async def test_windows_prioritize_best_hit_and_merge_connected_context(
    store_vectors,
    settings,
    storage,
    seed_indices,
    expected,
):
    vectors = [[1.0, 0.0, 0.0] for index in range(10)]
    for rank, chunk_index in enumerate(seed_indices):
        vectors[chunk_index] = [1.0, 1.0 - rank / 10, 0.0]
    source = await store_vectors(vectors)

    results = await search(
        "token", limit=len(seed_indices), settings=settings, storage=storage
    )

    assert [result.chunk_index for result in results] == expected
    assert all(result.source_id == str(source.id) for result in results)
    assert {
        result.chunk_index for result in results if result.score is not None
    } == set(seed_indices)


async def test_windows_keep_identical_content_from_distinct_sources(
    store_vectors, settings, storage
):
    first = await store_vectors([[1.0, 1.0, 0.0], [1.0, 0.0, 0.0]])
    second = await store_vectors([[1.0, 1.0, 0.0], [1.0, 0.0, 0.0]])

    results = await search("token", limit=2, settings=settings, storage=storage)

    assert {(result.source_id, result.chunk_index) for result in results} == {
        (str(source.id), index) for source in [first, second] for index in [0, 1]
    }
    assert len(results) == 4


async def test_zero_window_matches_cosine_and_empty_tenant_returns_nothing(
    store_vectors, settings, storage
):
    await store_vectors([[1.0, 1.0, 0.0], [1.0, 0.0, 0.0]])
    cosine = await search(
        "token", method="cosine", limit=1, settings=settings, storage=storage
    )
    window = await search(
        "token", window=0, limit=1, settings=settings, storage=storage
    )
    empty = await search(
        "token", settings=replace(settings, tenant_id="empty"), storage=storage
    )

    assert window == cosine
    assert empty == []


async def test_window_query_cannot_read_another_tenants_source(
    store_vectors, settings, storage
):
    source = await store_vectors([[1.0, 1.0, 0.0]], tenant_id="other")
    assert (
        await documents.get_chunk_window(
            storage,
            tenant_id=settings.tenant_id,
            source_id=source.id,
            chunk_index=0,
            window=2,
        )
        == []
    )


async def test_hybrid_combines_vector_only_and_lexical_only_chunks_without_crossing_tenants(
    settings, storage
):
    metadata = {
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model_name,
    }
    source = await documents.insert_source_with_chunks(
        storage,
        tenant_id=settings.tenant_id,
        source_type="file",
        reference="/tmp/hybrid.md",
        mime_type="text/markdown",
        content_hash="hybrid",
        chunks=[
            ChunkInput("token", metadata, embedding=[1.0, 0.0, 0.0]),
            ChunkInput(
                "Semantic match without keyword", metadata, embedding=[1.0, 1.0, 0.0]
            ),
            ChunkInput("token token", {}, embedding=None),
        ],
    )
    await documents.insert_source_with_chunks(
        storage,
        tenant_id="another-tenant",
        source_type="file",
        reference="/tmp/private.md",
        mime_type="text/markdown",
        content_hash="private",
        chunks=[ChunkInput("token", metadata, embedding=[1.0, 1.0, 0.0])],
    )

    results = await search(
        "token", method="hybrid", limit=5, settings=settings, storage=storage
    )

    assert {match.chunk_index for match in results} == {0, 1, 2}
    assert all(match.source_id == str(source.id) for match in results)
    assert results[0].chunk_index == 0
    assert results[0].score == pytest.approx(1 / 61 + 1 / 62)
    assert all(match.score is not None for match in results)
    assert (
        await search(
            "token",
            method="hybrid",
            settings=replace(settings, tenant_id="empty"),
            storage=storage,
        )
        == []
    )


async def test_lexical_does_not_embed_or_scan_chunks_in_python(
    settings, storage, monkeypatch
):
    await documents.insert_source_with_chunks(
        storage,
        tenant_id=settings.tenant_id,
        source_type="file",
        reference="/tmp/lexical.md",
        mime_type="text/markdown",
        content_hash="lexical",
        chunks=[ChunkInput("Moradia and housing support", {})],
    )

    async def unexpected_call(*args, **kwargs):
        pytest.fail("Lexical search must use SQL without embedding or list_chunks")

    monkeypatch.setattr(retrieval, "embed_texts", unexpected_call)
    monkeypatch.setattr(documents, "list_chunks", unexpected_call)

    results = await search(
        "moradia unknown", method="lexical", settings=settings, storage=storage
    )
    assert [match.content for match in results] == ["Moradia and housing support"]
