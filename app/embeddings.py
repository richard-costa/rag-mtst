"""Shared embedding generation for ingestion and retrieval."""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import replace
from functools import lru_cache
from math import isfinite
from typing import Any
from urllib.parse import urlsplit

from openai import APIError, AsyncOpenAI

from app.config import Settings, get_settings
from app.storage.records import ChunkInput

# ---------------------------------------------------------------------------
# Embedding operation
# ---------------------------------------------------------------------------
# Both providers return one finite, nonzero vector per input, in input order.


class EmbeddingError(RuntimeError):
    """An embedding provider could not complete the request."""


def embedding_endpoint(settings: Settings) -> str | None:
    """Resolve the configured embedding service endpoint.

    Args:
        settings: Configuration for this operation; defaults to the environment where supported.

    Returns:
        Embedding service URL, or ``None`` for local embeddings.
    """
    if settings.embedding_provider == "local":
        return None
    if settings.embedding_provider != "openai":
        raise ValueError("RAG_EMBEDDING_PROVIDER must be 'openai' or 'local'")
    endpoint = settings.openai_base_url or "https://api.openai.com/v1"
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "The embedding endpoint must be an HTTP(S) URL without credentials, query, or fragment"
        )
    return endpoint


async def prepare_chunks_for_embedding(
    chunks: list[ChunkInput], *, settings: Settings | None = None
) -> list[ChunkInput]:
    """Split chunks that exceed a local model's input limit.

    Args:
        chunks: Input chunks to process.
        settings: Configuration for this operation; defaults to the environment where supported.

    Returns:
        Chunks that fit the chosen embedding model.
    """
    active_settings = settings or get_settings()
    if not chunks or active_settings.embedding_provider != "local":
        return chunks
    return await asyncio.to_thread(_prepare_local_chunks, chunks, active_settings)


async def embed_texts(
    texts: list[str], *, settings: Settings | None = None
) -> list[list[float]]:
    """Embed texts with the selected hosted or local embedding provider.

    Args:
        texts: Input texts to embed.
        settings: Configuration for this operation; defaults to the environment where supported.

    Returns:
        One vector per input text.
    """
    active_settings = settings or get_settings()
    endpoint = embedding_endpoint(active_settings)
    if not texts:
        return []

    if active_settings.embedding_provider == "local":
        vectors = await asyncio.to_thread(_embed_local, texts, active_settings)
    else:
        vectors = await _embed_openai(texts, active_settings, base_url=endpoint)

    _validate_vectors(vectors, len(texts))
    return vectors


# ---------------------------------------------------------------------------
# Hosted embeddings
# ---------------------------------------------------------------------------
# Bounded batches avoid the API's input-count limit for larger documents.


async def _embed_openai(
    texts: list[str], settings: Settings, *, base_url: str | None
) -> list[list[float]]:
    """Call the OpenAI-compatible embeddings API and validate its vectors.

    Args:
        texts: Input texts to embed.
        settings: Configuration for this operation; defaults to the environment where supported.
        base_url: Optional service URL override.

    Returns:
        Embedding vectors in input order.
    """
    if not settings.openai_api_key:
        raise ValueError("Set OPENAI_API_KEY or select RAG_EMBEDDING_PROVIDER=local")

    vectors = []
    try:
        async with AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=base_url,
            timeout=30.0,
            max_retries=2,
        ) as client:
            for start in range(0, len(texts), 128):
                response = await client.embeddings.create(
                    model=settings.embedding_model_name,
                    input=texts[start : start + 128],
                    encoding_format="float",
                )
                ordered = sorted(response.data, key=lambda item: item.index)
                vectors.extend(item.embedding for item in ordered)
    except APIError as error:
        raise EmbeddingError("The embedding API request failed") from error
    return vectors


# ---------------------------------------------------------------------------
# Optional local embeddings
# ---------------------------------------------------------------------------
# Model loading and CPU inference stay off the event loop; models are reused.


@lru_cache(maxsize=1)
def _load_local_model(model_name: str) -> Any:
    """Load and cache a local sentence-transformer model.

    Args:
        model_name: Identifier of the local embedding model.

    Returns:
        Loaded sentence-transformer model.
    """
    try:
        module = importlib.import_module("sentence_transformers")
    except ImportError as error:
        raise ValueError("Local embeddings require: uv sync --extra local") from error
    return module.SentenceTransformer(model_name, device="cpu", trust_remote_code=False)


def _embed_local(texts: list[str], settings: Settings) -> list[list[float]]:
    """Compute embeddings locally and validate the output vectors.

    Args:
        texts: Input texts to embed.
        settings: Configuration for this operation; defaults to the environment where supported.

    Returns:
        Local embedding vectors in input order.
    """
    try:
        model = _load_local_model(settings.embedding_model_name)
        for index, text in enumerate(texts):
            token_count = _local_token_count(model, text)
            if token_count > model.max_seq_length:
                raise ValueError(
                    f"Local embedding input {index} uses {token_count} tokens; "
                    f"model {settings.embedding_model_name} allows {model.max_seq_length}. "
                    "Prepare document chunks before embedding, or shorten the search query."
                )
        return model.encode(
            texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False
        ).tolist()
    except (OSError, RuntimeError) as error:
        raise EmbeddingError(
            "The local embedding model could not load or encode"
        ) from error


def _local_token_count(model: Any, text: str) -> int:
    """Count model input tokens, including any configured prompt.

    Args:
        model: Loaded local embedding model.
        text: Input text to process.

    Returns:
        Input token count.
    """
    prompt = model.prompts.get(model.default_prompt_name, "") or ""
    normalized = (prompt + text).strip()
    if model._first_module().do_lower_case:
        normalized = normalized.lower()
    return len(
        model.tokenizer(
            normalized,
            truncation=False,
            add_special_tokens=True,
        )["input_ids"]
    )


def _prepare_local_chunks(
    chunks: list[ChunkInput], settings: Settings
) -> list[ChunkInput]:
    """Split oversized chunks into model-fitting text slices.

    Args:
        chunks: Input chunks to process.
        settings: Configuration for this operation; defaults to the environment where supported.

    Returns:
        Model-fitting chunks with preserved provenance.
    """
    try:
        model = _load_local_model(settings.embedding_model_name)
    except (OSError, RuntimeError) as error:
        raise EmbeddingError("The local embedding model could not load") from error
    if not isinstance(model.max_seq_length, int) or model.max_seq_length <= 0:
        raise ValueError(
            "The local embedding model must define a positive max_seq_length"
        )

    prepared = []
    for parent_index, chunk in enumerate(chunks):
        if _local_token_count(model, chunk.content) <= model.max_seq_length:
            prepared.append(chunk)
            continue
        for split_index, (start, end) in enumerate(
            _local_text_spans(chunk.content, model)
        ):
            prepared.append(
                replace(
                    chunk,
                    content=chunk.content[start:end],
                    embedding=None,
                    metadata={
                        **chunk.metadata,
                        "parent_chunk_index": parent_index,
                        "split_index": split_index,
                        "start_char": start,
                        "end_char": end,
                        **(
                            {
                                "source_pages": {
                                    **chunk.metadata["source_pages"],
                                    "scope": "parent_body",
                                }
                            }
                            if "source_pages" in chunk.metadata
                            else {}
                        ),
                    },
                )
            )
    return prepared


def _local_text_spans(text: str, model: Any) -> list[tuple[int, int]]:
    """Find token-fitting slices without losing original source characters.

    Args:
        text: Input text to process.
        model: Loaded local embedding model.

    Returns:
        Start/end offsets of the fitting slices.
    """
    spans = []
    start = 0
    while start < len(text):
        lower = start
        upper = min(start + model.max_seq_length, len(text))
        while _local_token_count(model, text[start:upper]) <= model.max_seq_length:
            lower = upper
            if upper == len(text):
                break
            upper = min(start + 2 * (upper - start), len(text))
        while lower + 1 < upper:
            middle = (lower + upper) // 2
            if _local_token_count(model, text[start:middle]) <= model.max_seq_length:
                lower = middle
            else:
                upper = middle
        end = lower
        if end == start:
            raise ValueError(
                "The local embedding model cannot fit a source character with its "
                "prompt and special tokens; select a model with a larger sequence limit."
            )
        if end < len(text):
            piece = text[start:end]
            boundary = piece.rfind("\n") + 1
            if not boundary:
                boundary = next(
                    (
                        index + 1
                        for index in range(len(piece) - 1, -1, -1)
                        if piece[index].isspace()
                    ),
                    0,
                )
            if (
                boundary
                and _local_token_count(model, piece[:boundary]) <= model.max_seq_length
            ):
                end = start + boundary
        spans.append((start, end))
        start = end
    return spans


# ---------------------------------------------------------------------------
# Vector validation
# ---------------------------------------------------------------------------
# Zero or malformed vectors do not have a useful cosine similarity.


def _validate_vectors(vectors: list[list[float]], expected_count: int) -> None:
    """Check the count, dimensions, and finiteness of embedding vectors.

    Args:
        vectors: Embedding vectors to validate.
        expected_count: Expected number of vectors.
    """
    if len(vectors) != expected_count:
        raise EmbeddingError("The embedding provider returned the wrong vector count")
    dimension = len(vectors[0])
    for vector in vectors:
        if (
            not vector
            or len(vector) != dimension
            or not all(isfinite(value) for value in vector)
            or not any(value != 0 for value in vector)
        ):
            raise EmbeddingError("The embedding provider returned an invalid vector")
