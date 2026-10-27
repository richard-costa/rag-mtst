"""Local CLI lifecycle checks without Docker or paid provider calls."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import local
from app.config import Settings


def _checkout(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    (tmp_path / "alembic.ini").write_text("[alembic]\n")
    (tmp_path / ".env.example").write_text("OPENAI_API_KEY=\nRAG_GENERATION_MODEL=\n")
    monkeypatch.setattr(local, "ROOT", tmp_path)


def test_env_loader_preserves_exported_values_and_anchors_staging(
    monkeypatch, tmp_path
):
    _checkout(tmp_path, monkeypatch)
    (tmp_path / ".env").write_text(
        "# Comment\nOPENAI_API_KEY=from-file\nRAG_GENERATION_MODEL='some-model'\n"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "from-shell")
    monkeypatch.delenv("RAG_GENERATION_MODEL", raising=False)
    monkeypatch.delenv("RAG_DATA_DIR", raising=False)
    local.load_environment()
    assert local.os.environ["OPENAI_API_KEY"] == "from-shell"
    assert local.os.environ["RAG_GENERATION_MODEL"] == "some-model"
    assert local.os.environ["RAG_DATA_DIR"] == str(tmp_path / ".rag-data")


def test_env_loader_reports_invalid_lines(monkeypatch, tmp_path):
    _checkout(tmp_path, monkeypatch)
    (tmp_path / ".env").write_text("invalid line")
    with pytest.raises(local.LocalError, match="line 1"):
        local.load_environment()


def test_start_creates_private_env_template_and_stops_before_docker(
    monkeypatch, tmp_path
):
    _checkout(tmp_path, monkeypatch)
    monkeypatch.setattr(
        local, "_docker", lambda *a, **k: pytest.fail("Docker should not start")
    )
    with pytest.raises(local.LocalError, match="Created .env"):
        local.start()
    assert (tmp_path / ".env").read_text() == (tmp_path / ".env.example").read_text()


def test_configuration_identifies_missing_provider_values(monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: Settings())
    with pytest.raises(local.LocalError, match="OPENAI_API_KEY") as err:
        local._verify_configuration()
    assert "RAG_GENERATION_MODEL" in str(err.value)


def test_start_reuses_ready_worker_and_runs_migrations(monkeypatch, tmp_path, capsys):
    _checkout(tmp_path, monkeypatch)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=fake\nRAG_GENERATION_MODEL=fake\n")
    monkeypatch.setattr(local, "_verify_configuration", lambda: None)
    calls = []

    def fake_docker(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="ok")

    monkeypatch.setattr(local, "_docker", fake_docker)
    monkeypatch.setattr(local, "_docker_ready", lambda: True)
    monkeypatch.setattr(local, "_worker_info", lambda: (123, "a" * 32))
    monkeypatch.setattr(local, "_worker_ready", lambda record: True)
    monkeypatch.setattr(
        local.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0)
    )
    assert local.start() == 0
    assert ("up", "-d", "--wait", "db") in calls
    assert "Ingestion worker already running" in capsys.readouterr().out


def test_stop_ignores_stale_pid_and_preserves_db(monkeypatch, tmp_path):
    _checkout(tmp_path, monkeypatch)
    runtime = local._state_dir()
    runtime.mkdir(parents=True)
    (runtime / "worker.json").write_text(json.dumps({"pid": 999999, "token": "a" * 32}))
    monkeypatch.setattr(local, "_worker_alive", lambda info: False)
    monkeypatch.setattr(
        local.os, "kill", lambda *args: pytest.fail("must not signal unrelated PID")
    )
    calls = []
    monkeypatch.setattr(
        local,
        "_docker",
        lambda *a, **k: calls.append(a) or SimpleNamespace(returncode=0),
    )
    assert local.stop() == 0
    assert calls == [("stop", "db")]
    assert not (runtime / "worker.json").exists()


def test_reset_requires_explicit_confirmation(monkeypatch, tmp_path):
    _checkout(tmp_path, monkeypatch)
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    monkeypatch.setattr(
        local, "_docker", lambda *a, **k: pytest.fail("reset must not touch Docker")
    )
    assert local.reset() == 1


def test_worker_identity_requires_matching_launch_token(monkeypatch):
    monkeypatch.setattr(
        local.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="python -m app.local worker " + "b" * 32
        ),
    )
    assert not local._worker_alive((1234, "a" * 32))
    assert local._worker_alive((1234, "b" * 32))
