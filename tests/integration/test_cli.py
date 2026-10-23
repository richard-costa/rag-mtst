from __future__ import annotations

import asyncio

import pytest

from app import ingestion
from app.cli import main
from app.storage import documents

pytestmark = pytest.mark.usefixtures("deterministic_embeddings", "cli_environment")


async def test_cli_submission_waiting_status_and_search(settings, storage, monkeypatch, capsys, run_cli):
    monkeypatch.delenv("RAG_API_KEY", raising=False)
    document = settings.data_dir.parent / "queued-cli.md"
    document.write_text("# CLI\n\nDurable CLI input with a retention policy.")
    assert await asyncio.to_thread(main, ["add", str(document), "--no-wait"]) == 0
    output = capsys.readouterr().out
    job_id = output.split("job ")[1].split(")")[0]
    assert await asyncio.to_thread(main, ["job", job_id]) == 0
    assert "pending" in capsys.readouterr().out
    assert await documents.list_chunks(storage, settings.tenant_id) == []
    assert await run_cli(["add", str(document)]) == 0
    assert "Added queued-cli.md" in capsys.readouterr().out
    assert await asyncio.to_thread(main, ["job", job_id]) == 0
    assert "completed" in capsys.readouterr().out
    assert await asyncio.to_thread(main, ["search", "retention"]) == 0
    assert "Durable CLI input" in capsys.readouterr().out


async def test_cli_waiting_returns_failure_without_exposing_provider_details(settings, monkeypatch, capsys, run_cli):
    document = settings.data_dir.parent / "failed-cli.md"
    document.write_text("A document whose provider fails.")

    async def fail_embedding(*args, **kwargs):
        raise RuntimeError("private provider payload")

    monkeypatch.setattr(ingestion, "embed_texts", fail_embedding)
    assert await run_cli(["add", str(document)]) == 1
    output = capsys.readouterr()
    assert "Ingestion failed" in output.err
    assert "private provider payload" not in output.err


@pytest.mark.usefixtures("deterministic_generation")
async def test_cli_selects_modes_and_prints_context(store_vectors, settings, storage, monkeypatch, capsys):
    await store_vectors([[1.0, 1.0, 0.0], [1.0, 0.0, 0.0]])

    assert await asyncio.to_thread(main, ["search", "token", "--limit", "1"]) == 0
    assert "context" in capsys.readouterr().out
    assert await asyncio.to_thread(main, ["search", "token", "--method", "cosine", "--limit", "1"]) == 0
    assert "context" not in capsys.readouterr().out
    assert await asyncio.to_thread(main, ["ask", "token", "--window", "0", "--limit", "1"]) == 0
    assert "chunk 0" in capsys.readouterr().out
    for command in ["search", "ask"]:
        assert await asyncio.to_thread(main, [command, "token", "--method", "hybrid", "--limit", "1"]) == 0
        output = capsys.readouterr().out
        assert "chunk 0" in output
        assert "context" not in output
