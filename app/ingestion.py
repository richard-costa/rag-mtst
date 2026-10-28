"""Async source-to-chunk ingestion."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from app.chunking import chunk_markdown
from app.config import Settings, get_settings
from app.embeddings import embed_texts, embedding_endpoint, prepare_chunks_for_embedding
from app.extraction import (
    extract_source,
    get_extraction_profile,
    validate_extraction_method,
)
from app.storage import documents, jobs
from app.storage.database import Database
from app.storage.records import ChunkInput, IngestionJob, Source

# ---------------------------------------------------------------------------
# Public ingestion result
# ---------------------------------------------------------------------------
# Return value shared by the API and CLI after an ingestion attempt.


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Result of a completed ingestion, including source and chunk count."""

    source: Source
    created: bool
    chunk_count: int


@dataclass(frozen=True, slots=True)
class IngestionSubmission:
    """Source and optional durable ingestion job returned at submission."""

    source: Source
    job: IngestionJob | None


async def enqueue_file(
    path: str | Path,
    *,
    settings: Settings | None = None,
    storage: Database | None = None,
    reindex: bool = False,
    extraction_method: str = "parser",
) -> IngestionSubmission:
    """Read a local file and submit it for durable background ingestion.

    Args:
        path: Input file path or staged input path.
        settings: Runtime settings for extraction, storage, or models.
        storage: Database handle; uses configured storage when omitted.
        reindex: Whether to replace content already indexed.
        extraction_method: Selected extraction strategy (parser or visual).

    Returns:
        Submitted source and optional queued job.
    """
    validate_extraction_method(extraction_method)
    source_path = Path(path)
    content = await asyncio.to_thread(source_path.read_bytes)
    return await enqueue_bytes(
        content,
        source_name=source_path.name,
        settings=settings,
        storage=storage,
        reindex=reindex,
        extraction_method=extraction_method,
    )


async def enqueue_bytes(
    content: bytes,
    *,
    source_name: str,
    settings: Settings | None = None,
    storage: Database | None = None,
    reindex: bool = False,
    extraction_method: str = "parser",
) -> IngestionSubmission:
    """Stage source bytes and enqueue an ingestion job when needed.

    Args:
        content: Original document bytes to extract or index.
        source_name: Original filename used to infer source type and title.
        settings: Runtime settings for extraction, storage, or models.
        storage: Database handle; uses configured storage when omitted.
        reindex: Whether to replace content already indexed.
        extraction_method: Selected extraction strategy (parser or visual).

    Returns:
        Submitted source and optional queued job.
    """
    validate_extraction_method(extraction_method)
    safe_name = Path(source_name).name
    if not safe_name.strip() or safe_name in {".", ".."}:
        raise ValueError("A source name is required")
    if not content:
        raise ValueError("The source is empty")
    active_settings = settings or get_settings()
    profile = get_extraction_profile(
        Path(safe_name).suffix,
        extraction_method=extraction_method,
        settings=active_settings,
    )
    if active_settings.chunk_size <= 0:
        raise ValueError("Chunk size must be greater than zero")
    configuration = {
        "chunk_size": active_settings.chunk_size,
        "chunk_group_adjacent": active_settings.chunk_group_adjacent,
        "embedding_provider": active_settings.embedding_provider,
        "embedding_model": active_settings.embedding_model_name,
        "embedding_base_url": embedding_endpoint(active_settings),
    }
    content_hash = sha256(content).hexdigest()
    active_storage = storage or Database(active_settings.database_url)
    job_id = uuid4()
    input_path = active_settings.data_dir / "ingestion" / str(job_id) / safe_name
    writing = asyncio.create_task(asyncio.to_thread(_write_input, input_path, content))
    try:
        await asyncio.shield(writing)
    except BaseException:
        await asyncio.gather(writing, return_exceptions=True)
        await asyncio.to_thread(_remove_input, input_path, active_settings)
        raise
    try:
        source, job = await jobs.create_ingestion_job(
            active_storage,
            tenant_id=active_settings.tenant_id,
            content_hash=content_hash,
            reference=safe_name,
            mime_type=mimetypes.guess_type(safe_name)[0],
            input_path=str(input_path),
            source_name=safe_name,
            extraction_profile=profile,
            configuration=configuration,
            reindex=reindex,
            job_id=job_id,
        )
    except BaseException:
        try:
            async with asyncio.timeout(5):
                accepted = await jobs.get_ingestion_job_input(
                    active_storage, active_settings.tenant_id, job_id
                )
        # Preserve staged input when database acceptance cannot be determined.
        except Exception:  # noqa: BLE001, S110
            pass
        else:
            if accepted is None:
                await asyncio.to_thread(_remove_input, input_path, active_settings)
        raise
    if job is None or job.id != job_id:
        await asyncio.to_thread(_remove_input, input_path, active_settings)
    return IngestionSubmission(source=source, job=job)


# ---------------------------------------------------------------------------
# Public ingestion operations
# ---------------------------------------------------------------------------
# These entry points orchestrate extraction, chunking, persistence, and deduplication.


async def add_file(
    path: str | Path,
    *,
    settings: Settings | None = None,
    storage: Database | None = None,
    reindex: bool = False,
    extraction_method: str = "parser",
) -> IngestionResult:
    """Read and index a local file synchronously within the caller.

    Args:
        path: Input file path or staged input path.
        settings: Runtime settings for extraction, storage, or models.
        storage: Database handle; uses configured storage when omitted.
        reindex: Whether to replace content already indexed.
        extraction_method: Selected extraction strategy (parser or visual).

    Returns:
        Persisted source and indexed-chunk count.
    """
    validate_extraction_method(extraction_method)
    source_path = Path(path)
    content = await asyncio.to_thread(source_path.read_bytes)
    return await add_bytes(
        content,
        source_name=source_path.name,
        settings=settings,
        storage=storage,
        reindex=reindex,
        extraction_method=extraction_method,
    )


async def add_bytes(
    content: bytes,
    *,
    source_name: str,
    settings: Settings | None = None,
    storage: Database | None = None,
    reindex: bool = False,
    extraction_method: str = "parser",
) -> IngestionResult:
    """Extract, embed, and persist supplied document bytes immediately.

    Args:
        content: Original document bytes to extract or index.
        source_name: Original filename used to infer source type and title.
        settings: Runtime settings for extraction, storage, or models.
        storage: Database handle; uses configured storage when omitted.
        reindex: Whether to replace content already indexed.
        extraction_method: Selected extraction strategy (parser or visual).

    Returns:
        Persisted source and indexed-chunk count.
    """
    validate_extraction_method(extraction_method)
    if not source_name:
        raise ValueError("A source name is required")

    suffix = Path(source_name).suffix
    active_settings = settings or get_settings()
    requested_profile = get_extraction_profile(
        suffix,
        extraction_method=extraction_method,
        settings=active_settings,
    )
    active_storage = storage or Database(active_settings.database_url)
    content_hash = sha256(content).hexdigest()
    existing = await documents.get_source_by_content_hash(
        active_storage,
        active_settings.tenant_id,
        content_hash,
    )
    if existing is not None and not reindex:
        indexed_profile = await documents.get_source_extraction_profile(
            active_storage,
            active_settings.tenant_id,
            existing.id,
        )
        if indexed_profile != requested_profile:
            raise ValueError(
                "The source has a different or unknown extraction profile; "
                "explicit reindexing is required (reindex=True)"
            )
        return IngestionResult(source=existing, created=False, chunk_count=0)

    embedded_chunks = await _prepare_chunks(
        content,
        source_name=source_name,
        settings=active_settings,
        extraction_method=extraction_method,
    )
    source = existing
    if source is None:
        source = await documents.insert_source_with_chunks(
            active_storage,
            tenant_id=active_settings.tenant_id,
            source_type="file",
            reference=Path(source_name).name,
            mime_type=mimetypes.guess_type(source_name)[0],
            content_hash=content_hash,
            chunks=embedded_chunks,
        )
    else:
        await documents.replace_chunks(
            active_storage,
            tenant_id=active_settings.tenant_id,
            source_id=source.id,
            chunks=embedded_chunks,
        )
    return IngestionResult(
        source=source, created=existing is None, chunk_count=len(embedded_chunks)
    )


async def _prepare_chunks(
    content: bytes,
    *,
    source_name: str,
    settings: Settings,
    extraction_method: str,
    progress: Callable[[str, int | None, int | None], Awaitable[None]] | None = None,
) -> list[ChunkInput]:
    """Extract, split, and embed source content with progress notifications.

    Args:
        content: Original document bytes to extract or index.
        source_name: Original filename used to infer source type and title.
        settings: Runtime settings for extraction, storage, or models.
        extraction_method: Selected extraction strategy (parser or visual).
        progress: Optional callback receiving stage, processed count, and total count.

    Returns:
        Extracted, chunked, and embedded source passages.
    """
    suffix = Path(source_name).suffix
    requested_profile = get_extraction_profile(
        suffix, extraction_method=extraction_method, settings=settings
    )
    if progress is not None:
        await progress("extracting", None, None)
    extracted = await extract_source(
        content,
        suffix,
        settings=settings,
        extraction_method=extraction_method,
    )
    if extracted.profile != requested_profile:
        raise ValueError(
            "Extracted content profile does not match the requested extraction profile"
        )
    if progress is not None:
        await progress("chunking", None, None)
    chunks = chunk_markdown(
        extracted.text,
        settings.chunk_size,
        group_adjacent=settings.chunk_group_adjacent,
        pages=extracted.pages,
    )
    if not chunks:
        raise ValueError("The source contains no searchable text")
    chunks = [
        replace(chunk, metadata={**chunk.metadata, "extraction": extracted.profile})
        for chunk in chunks
    ]
    chunks = await prepare_chunks_for_embedding(chunks, settings=settings)
    if progress is not None:
        await progress("embedding", 0, len(chunks))
    vectors = await embed_texts([chunk.content for chunk in chunks], settings=settings)
    embedded_chunks = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        embedded_chunks.append(
            replace(
                chunk,
                embedding=vector,
                metadata={
                    **chunk.metadata,
                    "embedding_provider": settings.embedding_provider,
                    "embedding_model": settings.embedding_model_name,
                },
            )
        )
    if progress is not None:
        await progress("storing", len(chunks), len(chunks))
    return embedded_chunks


async def process_ingestion_job(
    job: IngestionJob, *, settings: Settings, storage: Database
) -> None:
    """Process a claimed job and atomically persist its indexed chunks.

    Args:
        job: Claimed ingestion job with its configuration and input.
        settings: Runtime settings for extraction, storage, or models.
        storage: Database handle; uses configured storage when omitted.
    """
    if job.claim_token is None:
        raise ValueError("The ingestion job has not been claimed")
    queued = await jobs.get_ingestion_job_input(storage, settings.tenant_id, job.id)
    if queued is None:
        raise ValueError("The ingestion input is missing")
    if queued.input_path is None:
        raise ValueError("The ingestion input has been removed")
    input_path = Path(queued.input_path)
    if (
        input_path.parent.name != str(job.id)
        or input_path.resolve().parent.parent
        != (settings.data_dir / "ingestion").resolve()
    ):
        raise ValueError("The ingestion input is outside the job directory")
    content = await asyncio.to_thread(input_path.read_bytes)
    configuration = queued.configuration
    restored = replace(
        settings,
        chunk_size=configuration["chunk_size"],
        chunk_group_adjacent=configuration["chunk_group_adjacent"],
        embedding_provider=configuration["embedding_provider"],
        embedding_model=configuration["embedding_model"],
        openai_base_url=configuration["embedding_base_url"],
    )
    method = str(queued.extraction_profile["method"])
    if method == "visual":
        restored = replace(
            restored,
            visual_provider=str(queued.extraction_profile["engine"]),
            visual_model=str(queued.extraction_profile["model"]),
            visual_base_url=str(queued.extraction_profile["endpoint"]),
        )
    profile = get_extraction_profile(
        Path(queued.source_name).suffix, extraction_method=method, settings=restored
    )
    if profile != queued.extraction_profile:
        raise ValueError("The worker cannot reproduce the queued extraction profile")
    content_hash = sha256(content).hexdigest()
    source = await documents.get_source_by_content_hash(
        storage, settings.tenant_id, content_hash
    )
    if source is None or source.id != job.source_id:
        raise ValueError("The queued source identity does not match its original bytes")

    async def progress(stage: str, processed: int | None, total: int | None) -> None:
        """Report extraction or embedding progress for the active job claim.

        Args:
            stage: Current ingestion pipeline stage.
            processed: Number of items completed, if known.
            total: Total number of items, if known.
        """
        assert job.claim_token is not None
        if not await jobs.update_ingestion_job_progress(
            storage,
            settings.tenant_id,
            job.id,
            job.claim_token,
            stage=stage,
            processed=processed,
            total=total,
        ):
            raise RuntimeError("Ingestion job ownership was lost")

    chunks = await _prepare_chunks(
        content,
        source_name=queued.source_name,
        settings=restored,
        extraction_method=method,
        progress=progress,
    )
    if not await jobs.complete_ingestion_job(
        storage, settings.tenant_id, job, reference=queued.source_name, chunks=chunks
    ):
        raise RuntimeError("Ingestion job ownership was lost")


# ---------------------------------------------------------------------------
# Temporary queued inputs
# ---------------------------------------------------------------------------
# Inputs remain available only until their job reaches a terminal state.


def _write_input(path: Path, content: bytes) -> None:
    """Persist staged upload bytes with restricted filesystem permissions.

    Args:
        path: Input file path or staged input path.
        content: Original document bytes to extract or index.
    """
    path.parent.mkdir(parents=True, mode=0o700)
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _remove_input(path: Path, settings: Settings) -> None:
    """Remove a staged upload only when it is inside the ingestion directory.

    Args:
        path: Input file path or staged input path.
        settings: Runtime settings for extraction, storage, or models.
    """
    if path.resolve().parent.parent != (settings.data_dir / "ingestion").resolve():
        raise ValueError("The ingestion input is outside the staging directory")
    UUID(path.parent.name)
    try:
        shutil.rmtree(path.parent)
    except FileNotFoundError:
        pass


async def cleanup_ingestion_inputs(*, settings: Settings, storage: Database) -> None:
    """Remove staged files for jobs already finished.

    Args:
        settings: Runtime settings for extraction, storage, or models.
        storage: Database handle; uses configured storage when omitted.
    """
    for queued in await jobs.list_finished_ingestion_inputs(
        storage, settings.tenant_id
    ):
        assert queued.input_path is not None
        await asyncio.to_thread(_remove_input, Path(queued.input_path), settings)
        await jobs.clear_ingestion_input_path(
            storage, settings.tenant_id, queued.job_id, queued.input_path
        )
