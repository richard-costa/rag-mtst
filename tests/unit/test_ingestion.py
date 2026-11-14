from __future__ import annotations

from dataclasses import replace

import pytest

from app import ingestion
from app.config import Settings


@pytest.mark.parametrize(
    ("source_name", "content", "changes", "method"),
    [
        ("", b"text", {}, "parser"),
        ("..", b"text", {}, "parser"),
        ("empty.md", b"", {}, "parser"),
        ("unsupported.exe", b"text", {}, "parser"),
        ("valid.md", b"text", {}, "automatic"),
        ("valid.md", b"text", {"embedding_provider": "unsupported"}, "parser"),
        ("valid.md", b"text", {"chunk_size": 0}, "parser"),
        (
            "valid.md",
            b"text",
            {"openai_base_url": "https://private:key@example.com/v1"},
            "parser",
        ),
        (
            "valid.md",
            b"text",
            {"openai_base_url": "https://example.com/v1?api_key=private"},
            "parser",
        ),
    ],
)
async def test_enqueue_rejects_invalid_input_before_persistence(
    source_name,
    content,
    changes,
    method,
    tmp_path,
    monkeypatch,
):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid submissions must not access storage or stage input")

    monkeypatch.setattr(ingestion, "Database", unexpected)
    monkeypatch.setattr(ingestion, "_write_input", unexpected)
    settings = replace(Settings(data_dir=tmp_path / "data"), **changes)
    with pytest.raises(ValueError):
        await ingestion.enqueue_bytes(
            content,
            source_name=source_name,
            settings=settings,
            extraction_method=method,
        )
    assert not settings.data_dir.exists()


async def test_enqueue_removes_partial_input_when_staging_fails(tmp_path, monkeypatch):
    def partial_write(path, content):
        path.parent.mkdir(parents=True)
        path.write_bytes(content[:1])
        raise OSError("disk full")

    monkeypatch.setattr(ingestion, "_write_input", partial_write)
    monkeypatch.setattr(
        ingestion.jobs,
        "create_ingestion_job",
        lambda *a, **k: pytest.fail("A failed staging write must not create a job"),
    )
    settings = Settings(data_dir=tmp_path / "data")
    with pytest.raises(OSError, match="disk full"):
        await ingestion.enqueue_bytes(b"text", source_name="a.md", settings=settings)
    assert list((settings.data_dir / "ingestion").iterdir()) == []
