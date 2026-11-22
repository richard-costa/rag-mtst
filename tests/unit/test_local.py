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


def test_configuration_accepts_complete_settings(monkeypatch):
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: Settings(openai_api_key="key", generation_model="model"),
    )

    local._verify_configuration()


@pytest.mark.parametrize(
    "settings,message",
    [
        (Settings(database_url="postgresql://other/rag"), "default local database"),
        (
            Settings(
                embedding_provider="unknown",
                openai_api_key="key",
                generation_model="model",
            ),
            "RAG_EMBEDDING_PROVIDER",
        ),
        (
            Settings(
                openai_api_key="key",
                generation_provider="anthropic",
                generation_model="model",
            ),
            "ANTHROPIC_API_KEY",
        ),
        (
            Settings(generation_provider="ollama", generation_model="model"),
            "OPENAI_API_KEY for embeddings",
        ),
        (
            Settings(openai_api_key="key", generation_provider="unknown"),
            "RAG_GENERATION_PROVIDER",
        ),
    ],
)
def test_configuration_reports_invalid_settings(monkeypatch, settings, message):
    monkeypatch.setattr("app.config.get_settings", lambda: settings)

    with pytest.raises(local.LocalError, match=message):
        local._verify_configuration()


def test_configuration_requires_local_embedding_extra(monkeypatch):
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: Settings(embedding_provider="local", generation_model="model"),
    )

    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)

    with pytest.raises(local.LocalError, match="--extra local"):
        local._verify_configuration()


@pytest.mark.parametrize(
    "error,message",
    [(FileNotFoundError(), "not installed"), (PermissionError(), "permissions")],
)
def test_docker_failures_become_actionable_errors(
    monkeypatch, tmp_path, error, message
):
    _checkout(tmp_path, monkeypatch)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(local.subprocess, "run", fail)

    with pytest.raises(local.LocalError, match=message):
        local._docker("version")


@pytest.mark.parametrize(
    "returncode,stdout,ready",
    [
        (0, "healthy\n", True),
        (0, "starting\n", False),
        (0, "", False),
        (1, "healthy\n", False),
    ],
)
def test_database_readiness_requires_a_healthy_container(
    monkeypatch, returncode, stdout, ready
):
    monkeypatch.setattr(
        local,
        "_docker",
        lambda *a, **k: SimpleNamespace(returncode=returncode, stdout=stdout),
    )

    assert local._docker_ready() is ready


@pytest.mark.parametrize(
    "record,expected",
    [
        (json.dumps({"pid": 42, "token": "a" * 32}), (42, "a" * 32)),
        (json.dumps({"pid": 0, "token": "a" * 32}), None),
        (json.dumps({"pid": 42, "token": "short"}), None),
        ("not json", None),
        (None, None),
    ],
)
def test_worker_record_is_validated(monkeypatch, tmp_path, record, expected):
    _checkout(tmp_path, monkeypatch)
    runtime = local._state_dir()
    runtime.mkdir(parents=True)

    if record is not None:
        (runtime / "worker.json").write_text(record)

    assert local._worker_info() == expected


@pytest.mark.parametrize("marker,ready", [("a" * 32, True), ("b" * 32, False)])
def test_worker_readiness_requires_its_own_marker(monkeypatch, tmp_path, marker, ready):
    _checkout(tmp_path, monkeypatch)
    runtime = local._state_dir()
    runtime.mkdir(parents=True)
    (runtime / "ready").write_text(marker)
    monkeypatch.setattr(local, "_worker_alive", lambda info: True)

    assert local._worker_ready((42, "a" * 32)) is ready


def _prepare_start(monkeypatch, tmp_path, *, docker=None, migrated=0):
    _checkout(tmp_path, monkeypatch)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=fake\n")
    monkeypatch.setattr(local, "_verify_configuration", lambda: None)
    monkeypatch.setattr(local.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        local, "_docker", docker or (lambda *a, **k: SimpleNamespace(returncode=0))
    )

    monkeypatch.setattr(local, "_docker_ready", lambda: True)
    monkeypatch.setattr(
        local.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=migrated)
    )


@pytest.mark.parametrize(
    "failure,message",
    [
        ("docker", "Docker Compose is unavailable"),
        ("database", "PostgreSQL did not become healthy"),
        ("migration", "Database migration failed"),
    ],
)
def test_start_stops_at_the_first_failed_dependency(
    monkeypatch, tmp_path, failure, message
):
    def docker(*arguments, **kwargs):
        return SimpleNamespace(returncode=int(failure == "docker"))

    _prepare_start(
        monkeypatch, tmp_path, docker=docker, migrated=int(failure == "migration")
    )

    if failure == "database":
        monkeypatch.setattr(local, "_docker_ready", lambda: False)

    monkeypatch.setattr(
        local.subprocess,
        "Popen",
        lambda *a, **k: pytest.fail("The worker must not start"),
    )

    with pytest.raises(local.LocalError, match=message):
        local.start()


class _FakeWorker:
    pid = 4321

    def __init__(self, exit_code=None):
        self.exit_code = exit_code

    def poll(self):
        return self.exit_code


def test_start_launches_worker_and_waits_for_readiness(monkeypatch, tmp_path, capsys):
    _prepare_start(monkeypatch, tmp_path)
    launches = []

    def launch(command, **kwargs):
        launches.append(command)
        return _FakeWorker()

    readiness = iter([False, False, True])
    monkeypatch.setattr(local.subprocess, "Popen", launch)
    monkeypatch.setattr(local, "_worker_alive", lambda info: False)
    monkeypatch.setattr(local, "_worker_ready", lambda info: next(readiness))

    assert local.start() == 0
    record = json.loads((local._state_dir() / "worker.json").read_text())
    assert record["pid"] == 4321
    assert launches == [
        [local.sys.executable, "-m", "app.local", "worker", record["token"]]
    ]
    assert "Ingestion worker ready." in capsys.readouterr().out


@pytest.mark.parametrize(
    "alive,exit_code,timeout,message",
    [
        (True, None, 15, "running but not ready"),
        (False, 1, 15, "exited during startup"),
        (False, None, 0, "did not become ready"),
    ],
)
def test_start_reports_worker_startup_failures(
    monkeypatch, tmp_path, alive, exit_code, timeout, message
):
    _prepare_start(monkeypatch, tmp_path)
    monkeypatch.setattr(local, "START_TIMEOUT", timeout)
    monkeypatch.setattr(
        local.subprocess, "Popen", lambda *a, **k: _FakeWorker(exit_code)
    )

    monkeypatch.setattr(local, "_worker_alive", lambda info: alive)
    monkeypatch.setattr(local, "_worker_ready", lambda info: False)

    with pytest.raises(local.LocalError, match=message):
        local.start()


@pytest.mark.parametrize(
    "database,worker,code", [(True, True, 0), (True, False, 1), (False, True, 1)]
)
def test_status_reports_both_services(
    monkeypatch, tmp_path, capsys, database, worker, code
):
    _checkout(tmp_path, monkeypatch)
    monkeypatch.setattr(local, "_docker_ready", lambda: database)
    monkeypatch.setattr(local, "_worker_ready", lambda info: worker)

    assert local.status() == code
    output = capsys.readouterr().out
    assert f"PostgreSQL: {'ready' if database else 'stopped or unhealthy'}" in output
    assert f"Worker:     {'ready' if worker else 'stopped or unhealthy'}" in output


def test_status_treats_missing_docker_as_stopped(monkeypatch, tmp_path):
    _checkout(tmp_path, monkeypatch)

    def missing():
        raise local.LocalError("Docker is not installed")

    monkeypatch.setattr(local, "_docker_ready", missing)
    monkeypatch.setattr(local, "_worker_ready", lambda info: True)

    assert local.status() == 1


def _record_worker(monkeypatch, tmp_path):
    _checkout(tmp_path, monkeypatch)
    runtime = local._state_dir()
    runtime.mkdir(parents=True)
    (runtime / "worker.json").write_text(json.dumps({"pid": 4321, "token": "a" * 32}))
    monkeypatch.setattr(local.time, "sleep", lambda seconds: None)

    return runtime


def test_stop_terminates_live_worker_then_database(monkeypatch, tmp_path):
    runtime = _record_worker(monkeypatch, tmp_path)
    alive = iter([True, False])
    signals = []
    docker = []
    monkeypatch.setattr(local, "_worker_alive", lambda info: next(alive))
    monkeypatch.setattr(local.os, "kill", lambda *args: signals.append(args))
    monkeypatch.setattr(
        local,
        "_docker",
        lambda *a, **k: docker.append(a) or SimpleNamespace(returncode=0),
    )

    assert local.stop() == 0
    assert signals == [(4321, local.signal.SIGTERM)]
    assert docker == [("stop", "db")]
    assert not (runtime / "worker.json").exists()


def test_stop_reports_worker_that_does_not_exit(monkeypatch, tmp_path):
    _record_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(local, "STOP_TIMEOUT", 0)
    monkeypatch.setattr(local, "_worker_alive", lambda info: True)
    monkeypatch.setattr(local.os, "kill", lambda *args: None)
    monkeypatch.setattr(
        local, "_docker", lambda *a, **k: pytest.fail("Database must keep running")
    )

    with pytest.raises(local.LocalError, match="did not exit"):
        local.stop()


def test_stop_reports_database_failure(monkeypatch, tmp_path):
    _record_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(local, "_worker_alive", lambda info: False)
    monkeypatch.setattr(local, "_docker", lambda *a, **k: SimpleNamespace(returncode=1))

    with pytest.raises(local.LocalError, match="Could not stop PostgreSQL"):
        local.stop()


@pytest.mark.parametrize("confirmation", ["flag", "typed"])
def test_reset_removes_database_and_default_staging(
    monkeypatch, tmp_path, confirmation
):
    _checkout(tmp_path, monkeypatch)
    staging = tmp_path / ".rag-data" / "ingestion"
    (staging / "job").mkdir(parents=True)
    monkeypatch.setenv("RAG_DATA_DIR", str(tmp_path / ".rag-data"))
    monkeypatch.setattr("builtins.input", lambda prompt: "RESET")
    monkeypatch.setattr(local, "_worker_alive", lambda info: False)
    calls = []
    monkeypatch.setattr(
        local,
        "_docker",
        lambda *a, **k: calls.append(a) or SimpleNamespace(returncode=0),
    )

    assert local.reset(yes=confirmation == "flag") == 0
    assert calls == [("down", "--volumes")]
    assert not staging.exists()


def test_reset_preserves_custom_staging_path(monkeypatch, tmp_path, capsys):
    _checkout(tmp_path, monkeypatch)
    custom = tmp_path / "elsewhere"
    (custom / "ingestion").mkdir(parents=True)
    monkeypatch.setenv("RAG_DATA_DIR", str(custom))
    monkeypatch.setattr(local, "_worker_alive", lambda info: False)
    monkeypatch.setattr(local, "_docker", lambda *a, **k: SimpleNamespace(returncode=0))

    assert local.reset(yes=True) == 0
    assert (custom / "ingestion").exists()
    assert "Custom staging path was preserved" in capsys.readouterr().out


def test_reset_reports_database_removal_failure(monkeypatch, tmp_path):
    _checkout(tmp_path, monkeypatch)
    monkeypatch.setattr(local, "_worker_alive", lambda info: False)
    monkeypatch.setattr(local, "_docker", lambda *a, **k: SimpleNamespace(returncode=1))

    with pytest.raises(local.LocalError, match="Could not remove"):
        local.reset(yes=True)


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query):
        return None


def test_worker_child_marks_readiness_only_while_running(monkeypatch, tmp_path):
    _checkout(tmp_path, monkeypatch)
    runtime = local._state_dir()
    runtime.mkdir(parents=True)
    observed = []

    async def run():
        observed.append((runtime / "ready").read_text())

    monkeypatch.setattr(local, "load_environment", lambda: None)
    monkeypatch.setattr("psycopg.connect", lambda *a, **k: _Connection())
    monkeypatch.setattr(local, "_run_worker", run)

    assert local.worker_child("a" * 32) == 0
    assert observed == ["a" * 32]
    assert not (runtime / "ready").exists()


def test_worker_child_fails_without_database(monkeypatch, tmp_path):
    _checkout(tmp_path, monkeypatch)
    runtime = local._state_dir()
    runtime.mkdir(parents=True)

    def unavailable(*args, **kwargs):
        raise local.LocalError("database unavailable")

    monkeypatch.setattr(local, "load_environment", lambda: None)
    monkeypatch.setattr("psycopg.connect", unavailable)
    monkeypatch.setattr(
        local, "_run_worker", lambda: pytest.fail("Worker must not start")
    )

    assert local.worker_child("a" * 32) == 1
    assert not (runtime / "ready").exists()
