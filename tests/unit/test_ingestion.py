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
