from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app import ingestion
from app.ingestion import add_file
from app.retrieval import search
from app.storage import documents, jobs
from app.storage.database import Database
from app.storage.records import ChunkInput

pytestmark = pytest.mark.usefixtures("deterministic_embeddings")


async def test_enqueue_stages_shared_files_without_inference(
    settings, storage, monkeypatch
):
    def unexpected(*args, **kwargs):
        pytest.fail("Submission must not extract, embed, or persist an archive file")

    monkeypatch.setattr(ingestion, "extract_source", unexpected)
    monkeypatch.setattr(ingestion, "embed_texts", unexpected)
    settings = replace(
        settings,
        openai_api_key="private-openai",
        anthropic_api_key="private-anthropic",
        deepseek_api_key="private-deepseek",
        api_key="private-api",
    )
    document = settings.data_dir.parent / "queued.md"
    document.write_bytes(b"# Queued\n\nOriginal document.")
    submitted = await ingestion.enqueue_file(
        document, settings=settings, storage=storage
    )
    document.unlink()

    assert submitted.job is not None and submitted.job.status == "pending"
    restarted_storage = Database(settings.database_url)
    queued_input = await jobs.get_ingestion_job_input(
        restarted_storage, settings.tenant_id, submitted.job.id
    )
    assert queued_input is not None
    assert queued_input.input_path is not None
    staged = Path(queued_input.input_path)
    assert staged.read_bytes() == b"# Queued\n\nOriginal document."
    assert not hasattr(queued_input, "content")
    assert queued_input.source_name == "queued.md"
    assert queued_input.extraction_profile == {
        "method": "parser",
        "format": "md",
        "engine": "utf-8",
        "errors": "replace",
    }
    assert queued_input.configuration == {
        "chunk_size": settings.chunk_size,
        "chunk_group_adjacent": True,
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-small",
        "embedding_base_url": "https://api.openai.com/v1",
    }
    assert "private-" not in json.dumps(queued_input.configuration)
    assert queued_input.reindex is False
    assert await documents.list_chunks(restarted_storage, settings.tenant_id) == []
    assert not settings.source_dir.exists()

    duplicate = await ingestion.enqueue_bytes(
        staged.read_bytes(),
        source_name="renamed.md",
        settings=replace(settings, openai_api_key="rotated"),
        storage=restarted_storage,
    )
    assert duplicate.job == submitted.job
    with pytest.raises(ValueError, match="active ingestion job"):
        await ingestion.enqueue_bytes(
            staged.read_bytes(),
            source_name="queued.md",
            settings=replace(settings, chunk_size=50),
            storage=storage,
        )
    assert [
        path for path in (settings.data_dir / "ingestion").rglob("*") if path.is_file()
    ] == [staged]


async def test_enqueue_failure_removes_its_staged_file(settings, storage, monkeypatch):
    async def fail_enqueue(database, **kwargs):
        assert Path(kwargs["input_path"]).read_bytes() == b"Temporary input"
        raise ValueError("Synthetic enqueue rejection")

    monkeypatch.setattr(jobs, "create_ingestion_job", fail_enqueue)
    with pytest.raises(ValueError, match="Synthetic enqueue rejection"):
        await ingestion.enqueue_bytes(
            b"Temporary input",
            source_name="rejected.md",
            settings=settings,
            storage=storage,
        )
    assert not list((settings.data_dir / "ingestion").iterdir())


async def test_enqueue_existing_source_requires_explicit_profile_change_and_preserves_chunks(
    settings, storage
):
    content = b"# Existing\n\nKeep the indexed content."
    indexed = await ingestion.add_bytes(
        content, source_name="existing.md", settings=settings, storage=storage
    )
    original_chunks = await documents.list_chunks(storage, settings.tenant_id)
    duplicate = await ingestion.enqueue_bytes(
        content, source_name="existing.md", settings=settings, storage=storage
    )
    assert duplicate.source == indexed.source and duplicate.job is None

    await documents.replace_chunks(
        storage,
        tenant_id=settings.tenant_id,
        source_id=indexed.source.id,
        chunks=[
            ChunkInput("Keep this old profile", {"extraction": {"method": "different"}})
        ],
    )
    with pytest.raises(ValueError, match="explicit reindexing"):
        await ingestion.enqueue_bytes(
            content, source_name="existing.md", settings=settings, storage=storage
        )
    before_reindex = await documents.list_chunks(storage, settings.tenant_id)
    submitted = await ingestion.enqueue_bytes(
        content,
        source_name="existing.md",
        settings=settings,
        storage=storage,
        reindex=True,
    )
    assert submitted.source == indexed.source
    assert submitted.job is not None and submitted.job.status == "pending"
    assert await documents.list_chunks(storage, settings.tenant_id) == before_reindex
    assert indexed.source.reference == "existing.md"
    assert original_chunks[0].source_id == before_reindex[0].source_id


async def test_ingests_deduplicates_and_searches_a_markdown_file(
    settings, storage
) -> None:
    document = settings.data_dir.parent / "handbook.md"
    document.write_text(
        "# Authentication\n\nUse an access token to authenticate every request.",
        encoding="utf-8",
    )

    first = await add_file(document, settings=settings, storage=storage)
    duplicate = await add_file(document, settings=settings, storage=storage)
    results = await search("access token", settings=settings, storage=storage)

    assert first.created is True
    assert first.chunk_count == 1
    assert first.source.reference == "handbook.md"
    assert duplicate.created is False
    assert duplicate.source.id == first.source.id
    assert len(results) == 1
    assert results[0].source_id == str(first.source.id)
    assert "access token" in results[0].content


async def test_reindex_replaces_embeddings_and_preserves_source_identity(
    settings, storage
):
    document = settings.data_dir.parent / "notes.md"
    document.write_text("Some text for embedding.", encoding="utf-8")
    first = await add_file(document, settings=settings, storage=storage)
    old_chunks = await documents.list_chunks(storage, settings.tenant_id)
    changed_settings = replace(settings, embedding_model="another-model")

    unchanged = await add_file(document, settings=changed_settings, storage=storage)
    assert unchanged.chunk_count == 0
    reindexed = await add_file(
        document, reindex=True, settings=changed_settings, storage=storage
    )
    new_chunks = await documents.list_chunks(storage, settings.tenant_id)

    assert reindexed.source.id == first.source.id == unchanged.source.id
    assert reindexed.created is False
    assert new_chunks[0].id != old_chunks[0].id
    assert new_chunks[0].metadata["embedding_model"] == "another-model"
    assert await search("text", settings=settings, storage=storage) == []
    assert len(await search("text", settings=changed_settings, storage=storage)) == 1


async def test_chunk_insert_failure_rolls_back_new_source_and_preserves_reindex(
    settings, storage, monkeypatch
):
    document = settings.data_dir.parent / "notes.md"
    document.write_text("Original searchable text.", encoding="utf-8")
    original = await add_file(document, settings=settings, storage=storage)
    original_chunks = await documents.list_chunks(storage, settings.tenant_id)
    insert_chunks = documents._insert_chunks

    async def fail_insert_chunks(*args, **kwargs):
        raise RuntimeError("chunk insert failed")

    monkeypatch.setattr(documents, "_insert_chunks", fail_insert_chunks)
    new_content = b"New source text."
    with pytest.raises(RuntimeError, match="chunk insert failed"):
        await ingestion.add_bytes(
            new_content,
            source_name="new.md",
            settings=settings,
            storage=storage,
        )
    with pytest.raises(RuntimeError, match="chunk insert failed"):
        await add_file(document, reindex=True, settings=settings, storage=storage)

    assert (
        await documents.get_source_by_content_hash(
            storage,
            settings.tenant_id,
            ingestion.sha256(new_content).hexdigest(),
        )
        is None
    )
    assert await documents.list_chunks(storage, settings.tenant_id) == original_chunks

    monkeypatch.setattr(documents, "_insert_chunks", insert_chunks)
    retried = await ingestion.add_bytes(
        new_content,
        source_name="new.md",
        settings=settings,
        storage=storage,
    )

    assert retried.created is True
    assert retried.chunk_count == 1
    assert original.source.id != retried.source.id
