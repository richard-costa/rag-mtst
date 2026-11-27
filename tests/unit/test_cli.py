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
    assert submit.call_args.kwargs["collection_id"] == "default"


@pytest.mark.parametrize(
    "arguments,command,keywords",
    [
        (["start"], "start", {}),
        (["status"], "status", {}),
        (["stop"], "stop", {}),
        (["reset"], "reset", {"yes": False}),
        (["reset", "--yes"], "reset", {"yes": True}),
    ],
)
async def test_lifecycle_commands_delegate_to_local_management(
    monkeypatch, arguments, command, keywords
):
    calls = []
    monkeypatch.setattr(cli.local, "load_environment", lambda: None)
    monkeypatch.setattr(cli.local, command, lambda **kwargs: calls.append(kwargs) or 7)

    assert await cli._run(arguments) == 7
    assert calls == [keywords]


async def test_missing_command_is_a_usage_error(monkeypatch):
    monkeypatch.setattr(cli.local, "load_environment", lambda: None)

    with pytest.raises(SystemExit) as error:
        await cli._run([])

    assert error.value.code == 2


def _job(status, error=None):
    return SimpleNamespace(
        id="job-id",
        status=status,
        stage=None,
        processed=None,
        total=None,
        error=error,
    )


@pytest.mark.parametrize(
    "job,code,stderr",
    [
        (None, 1, "error: The ingestion job was not found"),
        (_job("failed", "Ingestion failed; resubmit."), 1, "Ingestion failed"),
        (_job("completed"), 0, ""),
    ],
)
async def test_job_command_reports_status_and_failures(
    monkeypatch, capsys, job, code, stderr
):
    monkeypatch.setattr(cli.local, "load_environment", lambda: None)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    monkeypatch.setattr(cli.jobs, "get_ingestion_job", AsyncMock(return_value=job))

    assert await cli._run(["job", "00000000-0000-0000-0000-000000000001"]) == code
    assert stderr in capsys.readouterr().err


async def test_add_reports_a_job_that_disappears_while_waiting(monkeypatch, capsys):
    monkeypatch.setattr(cli.local, "load_environment", lambda: None)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    monkeypatch.setattr(
        cli,
        "enqueue_file",
        AsyncMock(
            return_value=SimpleNamespace(
                source=SimpleNamespace(title="sample.md"),
                job=SimpleNamespace(id="job-id"),
            )
        ),
    )

    monkeypatch.setattr(cli.jobs, "get_ingestion_job", AsyncMock(return_value=None))

    assert await cli._run(["add", "sample.md"]) == 1
    assert "The ingestion job was not found" in capsys.readouterr().err


async def test_search_without_matches_says_so(monkeypatch, capsys):
    monkeypatch.setattr(cli.local, "load_environment", lambda: None)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    monkeypatch.setattr(cli, "search", AsyncMock(return_value=[]))

    assert await cli._run(["search", "anything"]) == 0
    assert capsys.readouterr().out == "No matching source chunks found.\n"


def test_interrupted_wait_leaves_the_job_queued(monkeypatch, capsys):
    def interrupted(coroutine):
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.asyncio, "run", interrupted)

    assert cli.main(["add", "sample.md"]) == 130
    assert "remains available to the worker" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["search", "ask"])
async def test_cli_forwards_window_assembly(monkeypatch, command):
    monkeypatch.setattr(cli.local, "load_environment", lambda: None)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings())
    backend = AsyncMock(
        return_value=[]
        if command == "search"
        else SimpleNamespace(text="ok", citations=[])
    )

    monkeypatch.setattr(cli, "search" if command == "search" else "answer", backend)

    assert (
        await cli._run(
            [
                command,
                "question",
                "--method",
                "window",
                "--assembly",
                "score",
                "--collection",
                "team-a",
            ]
        )
        == 0
    )
    assert backend.call_args.kwargs["assembly"] == "score"
    assert backend.call_args.kwargs["collection_id"] == "team-a"
