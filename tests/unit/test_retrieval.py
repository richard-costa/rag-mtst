from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from app import retrieval
from app.config import Settings
from app.embeddings import EmbeddingError
from app.retrieval import (
    SearchResult,
    search,
    search_hybrid,
    search_mmr,
    search_multi_query,
)
from app.storage.database import Database


@pytest.mark.parametrize(
    ("query", "options", "message"),
    [
        ("   ", {}, "query must not be empty"),
        ("text", {"limit": 0}, "limit must be greater"),
        ("text", {"limit": -1}, "limit must be greater"),
        ("text", {"window": -1}, "window must be zero"),
        ("text", {"method": "unknown"}, "method must be"),
    ],
)
async def test_search_rejects_invalid_inputs_before_embedding_or_sql(
    query, options, message
):
    with pytest.raises(ValueError, match=message):
        await search(query, settings=Settings(), **options)


@pytest.mark.parametrize("strategy", [search_mmr, search_multi_query])
async def test_future_strategies_are_explicit_stubs(strategy):
    settings = Settings()

    with pytest.raises(NotImplementedError, match="not implemented yet"):
        await strategy(
            "text", limit=5, settings=settings, storage=Database(settings.database_url)
        )


@pytest.mark.parametrize(
    ("cosine_ids", "lexical_ids", "expected"),
    [
        ([("a", 0), ("a", 1)], [("a", 1), ("a", 2)], [("a", 1), ("a", 0), ("a", 2)]),
        ([("b", 0), ("b", 1)], [("a", 0), ("a", 1)], [("a", 0), ("b", 0), ("a", 1)]),
        ([], [("a", 0), ("a", 1)], [("a", 0), ("a", 1)]),
        ([("a", 0), ("a", 1)], [], [("a", 0), ("a", 1)]),
        ([], [], []),
        ([("b", 0)], [("a", 0)], [("a", 0), ("b", 0)]),
        ([("a", 0), ("a", 1)], [("a", 1), ("a", 0)], [("a", 0), ("a", 1)]),
    ],
)
async def test_hybrid_fuses_ranks_not_raw_scores(
    cosine_ids, lexical_ids, expected, monkeypatch
):
    calls = []
    settings = Settings()
    storage = Database(settings.database_url)

    def matches(identities, scale):
        return [
            SearchResult(
                source_id=source_id,
                source_title="same.md",
                source_reference="/tmp/same.md",
                chunk_index=chunk_index,
                content="Identical text from separate chunks",
                score=scale * (index + 1),
            )
            for index, (source_id, chunk_index) in enumerate(identities)
        ]

    cosine_matches = matches(cosine_ids, 1000)
    lexical_matches = matches(lexical_ids, 0.00001)

    async def embed(texts, **kwargs):
        calls.append(("embed", texts))
        return [[1.0, 0.0]]

    async def cosine(embedding, *, limit, **kwargs):
        assert embedding == [1.0, 0.0]
        calls.append(("cosine", limit))
        return cosine_matches

    async def lexical(query, *, limit, **kwargs):
        assert query == "query"
        calls.append(("lexical", limit))
        return lexical_matches

    monkeypatch.setattr(retrieval, "embed_texts", embed)
    monkeypatch.setattr(retrieval, "search_cosine", cosine)
    monkeypatch.setattr(retrieval, "search_lexical", lexical)

    results = await search(
        "query", method="hybrid", limit=3, settings=settings, storage=storage
    )

    assert [(match.source_id, match.chunk_index) for match in results] == expected
    assert calls == [("embed", ["query"]), ("cosine", 20), ("lexical", 20)]
    assert len({(match.source_id, match.chunk_index) for match in results}) == len(
        results
    )

    for match in results:
        identity = (match.source_id, match.chunk_index)
        expected_score = sum(
            1 / (60 + identities.index(identity) + 1)
            for identities in [cosine_ids, lexical_ids]
            if identity in identities
        )

        assert match.score == pytest.approx(expected_score)

    assert [match.score for match in cosine_matches] == [
        1000 * (index + 1) for index in range(len(cosine_ids))
    ]


async def test_hybrid_expands_candidate_budget_and_returns_only_requested_limit(
    monkeypatch,
):
    limits = []

    async def embed(*args, **kwargs):
        return [[1.0]]

    async def candidates(*args, limit, **kwargs):
        limits.append(limit)
        return [
            SearchResult("source", "title", "/tmp/title", index, "text", 1.0)
            for index in range(limit)
        ]

    monkeypatch.setattr(retrieval, "embed_texts", embed)
    monkeypatch.setattr(retrieval, "search_cosine", candidates)
    monkeypatch.setattr(retrieval, "search_lexical", candidates)
    settings = Settings()

    results = await search_hybrid(
        "query", limit=6, settings=settings, storage=Database(settings.database_url)
    )

    assert limits == [24, 24]
    assert len(results) == 6


async def test_hybrid_does_not_silently_fall_back_after_provider_failure(monkeypatch):
    async def fail(*args, **kwargs):
        raise EmbeddingError("provider unavailable")

    monkeypatch.setattr(retrieval, "embed_texts", fail)

    with pytest.raises(EmbeddingError, match="provider unavailable"):
        await search("query", method="hybrid", settings=Settings())


@pytest.mark.parametrize("method", ["lexical", "hybrid"])
async def test_keyword_methods_reject_punctuation_before_embedding_or_sql(method):
    with pytest.raises(ValueError, match="at least one word"):
        await search("!!!", method=method, settings=Settings())


async def test_window_score_assembly_prioritizes_seeds_and_deduplicates(monkeypatch):
    source = "00000000-0000-0000-0000-000000000001"
    seeds = [
        SearchResult(source, "doc", "doc", 6, "text-6", 0.9),
        SearchResult(source, "doc", "doc", 4, "text-4", 0.4),
    ]

    async def cosine(*args, **kwargs):
        return seeds

    async def neighbors(*args, chunk_index, window, **kwargs):
        return [
            SimpleNamespace(
                source_id=UUID(source),
                source_title="doc",
                source_reference="doc",
                chunk_index=index,
                content=f"text-{index}",
            )
            for index in range(max(0, chunk_index - window), chunk_index + window + 1)
        ]

    monkeypatch.setattr(retrieval, "search_cosine", cosine)
    monkeypatch.setattr(retrieval.documents, "get_chunk_window", neighbors)
    settings = Settings()
    storage = Database(settings.database_url)
    kwargs = dict(limit=2, window=2, settings=settings, storage=storage)

    default = await retrieval.search_with_windows([1.0], **kwargs)
    scored = await retrieval.search_with_windows([1.0], assembly="score", **kwargs)

    assert [item.chunk_index for item in default] == [2, 3, 4, 5, 6, 7, 8]
    assert [item.chunk_index for item in scored] == [6, 5, 7, 8, 4, 2, 3]
    assert [item.score for item in scored if item.score is not None] == [0.9, 0.4]


async def test_search_rejects_unknown_assembly():
    with pytest.raises(ValueError, match="assembly must be"):
        await search("text", assembly="unknown", settings=Settings())
