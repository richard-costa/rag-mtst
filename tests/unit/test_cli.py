"""CLI argument validation without local service side effects."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import cli
from app.config import Settings


@pytest.mark.parametrize("command", ["start", "status", "stop", "reset"])
async def test_lifecycle_rejects_data_dir_before_loading_environment(
    command, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(
        cli.local,
        "load_environment",
        lambda: pytest.fail("Invalid arguments must not load configuration"),
    )
    with pytest.raises(SystemExit) as error:
        await cli._run(["--data-dir", str(tmp_path), command])
    assert error.value.code == 2
    assert "RAG_DATA_DIR" in capsys.readouterr().err


async def test_add_preserves_explicit_staging_override(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.local, "load_environment", lambda: None)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    submit = AsyncMock(
        return_value=SimpleNamespace(
            source=SimpleNamespace(title="sample.md"), job=None
        )
    )
    monkeypatch.setattr(cli, "enqueue_file", submit)
    assert await cli._run(["--data-dir", str(tmp_path), "add", "sample.md"]) == 0
    assert submit.call_args.kwargs["settings"].data_dir == tmp_path
