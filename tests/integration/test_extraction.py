from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import ClassVar

import pytest
from httpx import ASGITransport, AsyncClient

from app import embeddings, ingestion, retrieval, worker
from app.api.main import create_app
from app.chunking import chunk_markdown
from app.cli import main
from app.embeddings import EmbeddingError
from app.ingestion import add_file
from app.retrieval import search
from app.storage import documents
from app.storage.records import ChunkInput

pytestmark = pytest.mark.usefixtures("deterministic_embeddings")


@pytest.mark.parametrize(
    "body",
    [
        "Ordinary text. " * 60 + "\nTAILMARKER retention",
        "```python\n" + "print('keep this code')\n" * 30 + "TAILMARKER retention\n```",
        "| Name | Value |\n| --- | --- |\n"
        + "| housing | guaranteed |\n" * 30
        + "| TAILMARKER | retention |",
        "- " + "Long list item. " * 60 + "\n  TAILMARKER retention",
    ],
)
async def test_local_overflow_persists_every_piece_and_retrieves_the_tail(
    body, settings, storage, monkeypatch
):
    settings = replace(settings, embedding_provider="local", chunk_size=1000)
    text = "# Housing\n\n" + body
    original_chunks = chunk_markdown(text, settings.chunk_size)
    assert len(original_chunks) == 1
    encoded = []

    class LocalModel:
        max_seq_length = 66
        default_prompt_name = None
        prompts: ClassVar[dict[str, str]] = {}

        def _first_module(self):
            return SimpleNamespace(do_lower_case=False)

        def tokenizer(self, text, *, truncation, add_special_tokens):
            assert truncation is False
            assert add_special_tokens is True
            return {"input_ids": [101, *list(text), 102]}

        def encode(self, texts, **kwargs):
            encoded.extend(texts)
            vectors = [
                [1.0, float("TAILMARKER" in text.strip()[:64]), 0.0] for text in texts
            ]
            return SimpleNamespace(tolist=lambda: vectors)

    model = LocalModel()
    monkeypatch.setattr(embeddings, "_load_local_model", lambda name: model)
    monkeypatch.setattr(ingestion, "embed_texts", embeddings.embed_texts)
    monkeypatch.setattr(retrieval, "embed_texts", embeddings.embed_texts)

    result = await ingestion.add_bytes(
        text.encode("utf-8"),
        source_name="overflow.md",
        settings=settings,
        storage=storage,
    )
    chunks = await documents.list_chunks(storage, settings.tenant_id)
    assert result.chunk_count == len(chunks) == len(encoded) > 1
    assert "".join(chunk.content for chunk in chunks) == original_chunks[0].content
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert encoded == [chunk.content for chunk in chunks]
    for chunk in chunks:
        assert (
            len(
                model.tokenizer(
                    chunk.content.strip(),
                    truncation=False,
                    add_special_tokens=True,
                )["input_ids"]
            )
            <= model.max_seq_length
        )
        assert chunk.metadata["headings"] == ["Housing"]
        assert chunk.metadata["parent_chunk_index"] == 0
        assert chunk.metadata["split_index"] == chunk.chunk_index
        assert chunk.metadata["embedding_provider"] == "local"
        assert chunk.metadata["embedding_model"] == settings.embedding_model_name
        assert chunk.metadata["extraction"] == {
            "method": "parser",
            "format": "md",
            "engine": "utf-8",
            "errors": "replace",
        }
        assert (
            original_chunks[0].content[
                chunk.metadata["start_char"] : chunk.metadata["end_char"]
            ]
            == chunk.content
        )

    matches = await search(
        "TAILMARKER", method="cosine", limit=1, settings=settings, storage=storage
    )
    assert len(matches) == 1
    assert "TAILMARKER" in matches[0].content
    assert matches[0].source_id == str(result.source.id)
    assert matches[0].score == pytest.approx(1.0)

    duplicate = await ingestion.add_bytes(
        text.encode("utf-8"),
        source_name="overflow.md",
        settings=settings,
        storage=storage,
    )
    assert duplicate.created is False
    assert duplicate.source.id == result.source.id
    assert duplicate.chunk_count == 0
    assert await documents.list_chunks(storage, settings.tenant_id) == chunks

    def fail_encode(*args, **kwargs):
        raise RuntimeError("inference failed")

    monkeypatch.setattr(model, "encode", fail_encode)
    with pytest.raises(EmbeddingError, match="could not load or encode"):
        await ingestion.add_bytes(
            text.encode("utf-8"),
            source_name="overflow.md",
            reindex=True,
            settings=settings,
            storage=storage,
        )
    assert await documents.list_chunks(storage, settings.tenant_id) == chunks


@pytest.mark.usefixtures("inline_worker")
async def test_native_office_upload_persists_searchable_chunks(
    settings, storage, monkeypatch, office_document
) -> None:
    from app.extraction import parser

    def reject_conversion(*args, **kwargs):
        pytest.fail("Native Office ingestion must not invoke conversion")

    monkeypatch.setattr(parser, "_convert_office_to_pdf", reject_conversion)
    content = office_document(".docx")
    source_name = "native.docx"
    transport = ASGITransport(app=create_app(settings))
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {settings.api_key}"},
    ) as client:
        uploaded = await client.post(
            "/sources/file", files={"file": (source_name, content)}
        )
        assert uploaded.status_code == 202
        assert await worker.run_once(settings=settings, storage=storage)
        source_id = uploaded.json()["id"]
        chunks = await documents.list_chunks(storage, settings.tenant_id)
        assert any("| Bricks | 42 |" in chunk.content for chunk in chunks)
        assert any(chunk.metadata["headings"] == ["Native heading"] for chunk in chunks)
        assert chunks[0].source_reference == source_name
        assert not list((settings.data_dir / "ingestion").iterdir())

        matches = await client.post(
            "/search", json={"query": "Bricks", "method": "lexical"}
        )
        assert matches.status_code == 200
        assert matches.json()[0]["source_id"] == source_id


@pytest.mark.parametrize(
    "stored_profile", [None, {"method": "parser", "engine": "outdated"}]
)
async def test_extraction_profile_conflict_requires_explicit_reindex(
    settings, storage, monkeypatch, stored_profile
):
    from app.extraction import get_extraction_profile

    content = b"Previously indexed searchable text."
    original = await ingestion.add_bytes(
        content, source_name="profile.md", settings=settings, storage=storage
    )
    await documents.replace_chunks(
        storage,
        tenant_id=settings.tenant_id,
        source_id=original.source.id,
        chunks=[ChunkInput("Old searchable text", {"extraction": stored_profile})],
    )
    old_chunks = await documents.list_chunks(storage, settings.tenant_id)

    def reject_extraction(*args, **kwargs):
        pytest.fail("Profile conflicts must fail before parsing or inference")

    with monkeypatch.context() as blocked:
        blocked.setattr(ingestion, "extract_source", reject_extraction)
        with pytest.raises(ValueError, match="explicit reindexing is required"):
            await ingestion.add_bytes(
                content, source_name="profile.md", settings=settings, storage=storage
            )
    assert await documents.list_chunks(storage, settings.tenant_id) == old_chunks
    assert original.source.reference == "profile.md"

    reindexed = await ingestion.add_bytes(
        content,
        source_name="profile.md",
        settings=settings,
        storage=storage,
        reindex=True,
    )
    assert reindexed.source.id == original.source.id
    assert await documents.get_source_extraction_profile(
        storage,
        settings.tenant_id,
        original.source.id,
    ) == get_extraction_profile(".md")
    duplicate = await ingestion.add_bytes(
        content, source_name="profile.md", settings=settings, storage=storage
    )
    assert duplicate.created is False and duplicate.chunk_count == 0


@pytest.mark.usefixtures("inline_worker")
async def test_explicit_extraction_selection_and_profile_conflicts_through_http_and_cli(
    settings, storage, monkeypatch, run_cli
):
    from app.extraction import get_extraction_profile

    content = b"Profile-aware searchable document."
    files = {"file": ("profile.md", content, "text/markdown")}
    async with AsyncClient(
        transport=ASGITransport(app=create_app(settings)),
        base_url="http://test",
        headers={"Authorization": f"Bearer {settings.api_key}"},
    ) as client:
        first = await client.post("/sources/file?extraction_method=parser", files=files)
        assert first.status_code == 202
        assert await worker.run_once(settings=settings, storage=storage)
        source = await documents.get_source_by_content_hash(
            storage, settings.tenant_id, ingestion.sha256(content).hexdigest()
        )
        assert source is not None
        for method in ("Visual", "unknown", "Parser"):
            rejected = await client.post(
                "/sources/file", params={"extraction_method": method}, files=files
            )
            assert rejected.status_code == 422
            with pytest.raises(ValueError, match="Unsupported extraction method"):
                await ingestion.add_bytes(
                    content,
                    source_name="profile.md",
                    settings=settings,
                    storage=storage,
                    extraction_method=method,
                )
        with pytest.raises(ValueError, match="Unsupported extraction method"):
            await add_file(
                "missing-file.md", settings=settings, extraction_method="unknown"
            )

        await documents.replace_chunks(
            storage,
            tenant_id=settings.tenant_id,
            source_id=source.id,
            chunks=[ChunkInput("Searchable text without an extraction profile", {})],
        )
        unprofiled = await client.post(
            "/sources/file?extraction_method=parser", files=files
        )
        assert unprofiled.status_code == 422
        assert "explicit reindexing is required" in unprofiled.json()["detail"]

        document = settings.data_dir.parent / "profile.md"
        document.write_bytes(content)
        monkeypatch.setenv("DATABASE_URL", settings.database_url)
        monkeypatch.setenv("RAG_DATA_DIR", str(settings.data_dir))
        monkeypatch.setenv("RAG_TENANT_ID", settings.tenant_id)
        assert (
            await asyncio.to_thread(
                main, ["add", str(document), "--extraction-method", "parser"]
            )
            == 1
        )
        assert (
            await run_cli(
                ["add", str(document), "--extraction-method", "parser", "--reindex"]
            )
            == 0
        )
        assert await documents.get_source_extraction_profile(
            storage, settings.tenant_id, source.id
        ) == get_extraction_profile(".md")
        reused = await client.post(
            "/sources/file?extraction_method=parser", files=files
        )
        assert reused.status_code == 200
        assert reused.json() == {
            "id": str(source.id),
            "status": "unchanged",
            "job_id": None,
            "status_url": None,
        }


@pytest.mark.usefixtures("inline_worker")
async def test_visual_http_cli_deduplication_and_failed_reindex_preserve_data(
    settings,
    storage,
    monkeypatch,
    vision_reply,
    pdf_document,
):
    settings = replace(
        settings, visual_model="vision-model", openai_api_key="synthetic-key"
    )
    document = pdf_document(("First", "", "Table"))
    pages = [
        {"markdown": "# Inventory", "blank": False},
        {"markdown": "", "blank": True},
        {
            "markdown": "| Material | Count |\n|---|---|\n| Bricks | 42 |",
            "blank": False,
        },
    ]
    requests = vision_reply(pages)
    async with AsyncClient(
        transport=ASGITransport(app=create_app(settings)),
        base_url="http://test",
        headers={"Authorization": f"Bearer {settings.api_key}"},
    ) as client:
        files = {"file": ("visual.pdf", document, "application/pdf")}
        uploaded = await client.post(
            "/sources/file?extraction_method=visual", files=files
        )
        assert uploaded.status_code == 202, uploaded.text
        assert await worker.run_once(settings=settings, storage=storage)
        chunks = await documents.list_chunks(storage, settings.tenant_id)
        assert chunks and all(
            chunk.metadata["extraction"]["method"] == "visual" for chunk in chunks
        )
        assert any(chunk.metadata["source_pages"]["end"] == 3 for chunk in chunks)
        assert len(requests) == 3
        repeated = await client.post(
            "/sources/file?extraction_method=visual", files=files
        )
        assert repeated.status_code == 200 and repeated.json()["status"] == "unchanged"
        assert len(requests) == 3
        parsed = await client.post(
            "/sources/file?extraction_method=parser", files=files
        )
        assert parsed.status_code == 422 and "reindex" in parsed.json()["detail"]

        path = settings.data_dir.parent / "visual.pdf"
        path.write_bytes(document)
        for name, value in {
            "DATABASE_URL": settings.database_url,
            "RAG_DATA_DIR": str(settings.data_dir),
            "RAG_TENANT_ID": settings.tenant_id,
            "RAG_VISUAL_MODEL": "vision-model",
        }.items():
            monkeypatch.setenv(name, value)
        assert (
            await asyncio.to_thread(
                main, ["add", str(path), "--extraction-method", "visual"]
            )
            == 0
        )
        assert len(requests) == 3
        monkeypatch.setenv("RAG_VISUAL_MODEL", "other-vision-model")
        assert (
            await asyncio.to_thread(
                main, ["add", str(path), "--extraction-method", "visual"]
            )
            == 1
        )
        assert len(requests) == 3

        vision_reply([], status=400)
        failed = await client.post(
            "/sources/file?extraction_method=visual&reindex=true", files=files
        )
        assert failed.status_code == 202
        assert await worker.run_once(settings=settings, storage=storage)
        assert (await client.get(failed.json()["status_url"])).json()[
            "status"
        ] == "failed"
        assert await documents.list_chunks(storage, settings.tenant_id) == chunks
        assert not list((settings.data_dir / "ingestion").iterdir())


@pytest.mark.parametrize("kind", ["page", "slide"])
@pytest.mark.parametrize("group_adjacent", [False, True])
async def test_paged_extraction_preserves_body_ranges_and_profiles_in_storage(
    settings, storage, monkeypatch, kind, group_adjacent
):
    from app.extraction import ExtractedContent, ExtractedPage, get_extraction_profile

    profile = get_extraction_profile(".pdf")
    extracted = ExtractedContent.from_pages(
        (
            ExtractedPage(1, "# Shared heading\n\nFirst body.", kind),
            ExtractedPage(2, "", kind),
            ExtractedPage(3, "Second body.", kind),
        ),
        format="pdf",
        profile=profile,
    )

    async def extract(*args, **kwargs):
        return extracted

    monkeypatch.setattr(ingestion, "extract_source", extract)
    settings = replace(settings, chunk_size=100, chunk_group_adjacent=group_adjacent)
    result = await ingestion.add_bytes(
        b"synthetic page source",
        source_name="pages.pdf",
        settings=settings,
        storage=storage,
    )
    chunks = await documents.list_chunks(storage, settings.tenant_id)
    assert result.chunk_count == len(chunks) == (1 if group_adjacent else 2)
    for chunk in chunks:
        assert chunk.metadata["extraction"] == profile
        assert chunk.metadata["headings"] == ["Shared heading"]
        assert chunk.metadata["source_pages"]["kind"] == kind
        assert chunk.metadata["source_pages"]["scope"] == "body"
    assert chunks[0].metadata["source_pages"]["start"] == 1
    assert chunks[-1].metadata["source_pages"]["end"] == 3
    assert (
        await documents.get_source_extraction_profile(
            storage, settings.tenant_id, result.source.id
        )
        == profile
    )
