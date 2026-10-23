"""Cosine, full-text, hybrid retrieval, and neighboring chunk windows."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Literal
from uuid import UUID

from app.config import Settings, get_settings
from app.embeddings import embed_texts
from app.storage.database import Database
from app.storage.records import StoredChunk
from app.storage import documents


RetrievalMethod = Literal["cosine", "window", "lexical", "hybrid"]


# ---------------------------------------------------------------------------
# Retrieval result
# ---------------------------------------------------------------------------
# This value exposes the chunk fields needed by generation and transport adapters.

@dataclass(frozen=True, slots=True)
class SearchResult:
    source_id: str
    source_title: str
    source_locator: str
    chunk_index: int
    content: str
    score: float | None


# ---------------------------------------------------------------------------
# Retrieval entry point
# ---------------------------------------------------------------------------
# Adapters select a strategy here; query embeddings are generated only for vector search.

async def search(
    query: str,
    *,
    limit: int | None = None,
    method: RetrievalMethod | None = None,
    window: int | None = None,
    settings: Settings | None = None,
    storage: Database | None = None,
) -> list[SearchResult]:
    if not query.strip():
        raise ValueError("The search query must not be empty")

    active_settings = settings or get_settings()
    result_limit = limit if limit is not None else active_settings.retrieval_limit
    if result_limit <= 0:
        raise ValueError("limit must be greater than zero")
    selected_method = method if method is not None else active_settings.retrieval_method
    if selected_method not in {"cosine", "window", "lexical", "hybrid"}:
        raise ValueError("method must be 'cosine', 'window', 'lexical', or 'hybrid'")
    context_window = window if window is not None else active_settings.retrieval_window
    if context_window < 0:
        raise ValueError("window must be zero or greater")

    active_storage = storage or Database(active_settings.database_url)
    if selected_method == "lexical":
        return await search_lexical(
            query, limit=result_limit, settings=active_settings, storage=active_storage
        )
    if selected_method == "hybrid":
        return await search_hybrid(
            query, limit=result_limit, settings=active_settings, storage=active_storage
        )

    vectors = await embed_texts([query], settings=active_settings)
    if selected_method == "cosine":
        return await search_cosine(
            vectors[0], limit=result_limit, settings=active_settings, storage=active_storage
        )
    return await search_with_windows(
        vectors[0], limit=result_limit, window=context_window,
        settings=active_settings, storage=active_storage,
    )


# ---------------------------------------------------------------------------
# Cosine search
# ---------------------------------------------------------------------------
# Postgres ranks only the current tenant's vectors from the configured embedding space.

async def search_cosine(
    embedding: list[float], *, limit: int, settings: Settings, storage: Database
) -> list[SearchResult]:
    chunks = await documents.vector_search(storage,
        tenant_id=settings.tenant_id,
        embedding=embedding,
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model_name,
        limit=limit,
    )
    return [_search_result(chunk, score=chunk.score) for chunk in chunks]


# ---------------------------------------------------------------------------
# Window search
# ---------------------------------------------------------------------------
# Rank windows by their best seed and keep merged same-source context in document order.

async def search_with_windows(
    embedding: list[float], *, limit: int, window: int,
    settings: Settings, storage: Database,
) -> list[SearchResult]:
    seeds = await search_cosine(embedding, limit=limit, settings=settings, storage=storage)
    if window == 0:
        return seeds

    matches = {(seed.source_id, seed.chunk_index): seed for seed in seeds}
    windows = []
    for rank, seed in enumerate(seeds):
        windows.append((seed.source_id, seed.chunk_index - window, seed.chunk_index + window, rank))
        neighbors = await documents.get_chunk_window(storage,
            tenant_id=settings.tenant_id,
            source_id=UUID(seed.source_id),
            chunk_index=seed.chunk_index,
            window=window,
        )
        for chunk in neighbors:
            identity = (str(chunk.source_id), chunk.chunk_index)
            if identity not in matches:
                matches[identity] = _search_result(chunk, score=None)

    merged: list[tuple[str, int, int, int]] = []
    for source_id, start, end, rank in sorted(windows):
        if merged and merged[-1][0] == source_id and start <= merged[-1][2]:
            previous = merged[-1]
            merged[-1] = (source_id, previous[1], max(end, previous[2]), min(rank, previous[3]))
        else:
            merged.append((source_id, start, end, rank))
    return [
        match
        for source_id, start, end, rank in sorted(merged, key=lambda group: group[3])
        for match in sorted(
            (match for match in matches.values()
             if match.source_id == source_id and start <= match.chunk_index <= end),
            key=lambda match: match.chunk_index,
        )
    ]


# ---------------------------------------------------------------------------
# Lexical search
# ---------------------------------------------------------------------------
# Indexed language-neutral word matching needs no embedding provider.

async def search_lexical(
    query: str, *, limit: int, settings: Settings, storage: Database
) -> list[SearchResult]:
    if not _terms(query):
        raise ValueError("The search query must contain at least one word")
    chunks = await documents.full_text_search(storage,
        tenant_id=settings.tenant_id, query=query, limit=limit,
    )
    return [_search_result(chunk, score=chunk.score) for chunk in chunks]


# ---------------------------------------------------------------------------
# Hybrid retrieval
# ---------------------------------------------------------------------------
# Fuse rank positions; lexical and cosine scores do not share a meaningful scale.

async def search_hybrid(
    query: str, *, limit: int, settings: Settings, storage: Database
) -> list[SearchResult]:
    """Fuse equally weighted candidate lists with RRF constant 60, without windows."""
    if not _terms(query):
        raise ValueError("The search query must contain at least one word")
    candidate_limit = max(20, 4 * limit)
    vectors = await embed_texts([query], settings=settings)
    cosine = await search_cosine(
        vectors[0], limit=candidate_limit, settings=settings, storage=storage,
    )
    lexical = await search_lexical(
        query, limit=candidate_limit, settings=settings, storage=storage,
    )
    scores: dict[tuple[str, int], float] = {}
    matches: dict[tuple[str, int], SearchResult] = {}
    for ranking in (cosine, lexical):
        for rank, match in enumerate(ranking, start=1):
            identity = (match.source_id, match.chunk_index)
            scores[identity] = scores.get(identity, 0.0) + 1 / (60 + rank)
            matches.setdefault(identity, match)
    ordered = sorted(scores, key=lambda identity: (-scores[identity], *identity))
    return [replace(matches[identity], score=scores[identity]) for identity in ordered[:limit]]


# ---------------------------------------------------------------------------
# Future retrieval strategies
# ---------------------------------------------------------------------------
# These are extension points, not selectable strategies or silent fallbacks.


async def search_mmr(
    query: str, *, limit: int, settings: Settings, storage: Database
) -> list[SearchResult]:
    """Balance relevance and diversity with maximal marginal relevance."""
    raise NotImplementedError("MMR retrieval is not implemented yet")


async def search_multi_query(
    query: str, *, limit: int, settings: Settings, storage: Database
) -> list[SearchResult]:
    """Retrieve across query variants and combine their results."""
    raise NotImplementedError("Multi-query retrieval is not implemented yet")


# ---------------------------------------------------------------------------
# Result conversion and text normalization
# ---------------------------------------------------------------------------
# Context chunks deliberately have no relevance score; lexical terms ignore punctuation.

def _search_result(chunk: StoredChunk, *, score: float | None) -> SearchResult:
    return SearchResult(
        source_id=str(chunk.source_id),
        source_title=chunk.source_title,
        source_locator=chunk.source_locator,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        score=score,
    )


def _terms(text: str) -> list[str]:
    # Example: "Access_token, please!" becomes ["access", "token", "please"].
    return re.findall(r"[^\W_]+", text.casefold())
