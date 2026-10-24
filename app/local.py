"""Local CLI lifecycle: Docker PostgreSQL and a host-side ingestion worker.

This module is for development from an editable source checkout. Deployment uses
its own processes/images and does not depend on this supervisor.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parent.parent
PROJECT = "rag-mtst-local"
DEFAULT_DATABASE_URL = "postgresql://rag:rag@127.0.0.1:5432/rag"
START_TIMEOUT = 15
STOP_TIMEOUT = 20


class LocalError(RuntimeError):
    """A user-actionable local environment failure."""


def _checkout(root: Path | None = None) -> Path:
    root = root or ROOT
    if not (root / "compose.yaml").is_file() or not (root / "alembic.ini").is_file():
        raise LocalError("Local management needs a source checkout. Install with: uv tool install --editable .")
    return root


def _state_dir(root: Path | None = None) -> Path:
    root = root or ROOT
    return root / ".rag-data" / "local-runtime"


def load_environment(root: Path | None = None) -> None:
    """Load project .env for CLI commands; existing exported variables win."""
    root = root or ROOT
    path = root / ".env"
    if path.is_file():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            name, separator, value = line.partition("=")
            name = name.strip()
            if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise LocalError(f"Invalid .env assignment on line {number}")
            value = value.strip()
            if value.startswith(('"', "'")):
                quote = value[0]
                if len(value) < 2 or value[-1] != quote:
                    raise LocalError(f"Invalid quoted .env value on line {number}")
                value = value[1:-1]
            else:
                value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
            os.environ.setdefault(name, value)
    if (root / "compose.yaml").is_file():
        configured = Path(os.environ.get("RAG_DATA_DIR") or ".rag-data").expanduser()
        os.environ["RAG_DATA_DIR"] = str(
            (configured if configured.is_absolute() else root / configured).resolve()
        )


def _verify_configuration() -> None:
    from app.config import get_settings

    settings = get_settings()
    missing: list[str] = []
    if settings.database_url != DEFAULT_DATABASE_URL:
        raise LocalError(
            "rag start manages the default local database only. Remove DATABASE_URL "
            "from .env (or use the manual setup for an external database)."
        )
    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            missing.append("OPENAI_API_KEY (for embeddings)")
    elif settings.embedding_provider == "local":
        from importlib.util import find_spec
        if find_spec("sentence_transformers") is None:
            raise LocalError(
                "Local embeddings need the optional dependencies. Install with: "
                "uv tool install --editable '.[local]'"
            )
    else:
        raise LocalError("RAG_EMBEDDING_PROVIDER must be 'openai' or 'local'")

    if not settings.generation_model:
        missing.append("RAG_GENERATION_MODEL (for answers)")
    providers = {
        "openai": settings.openai_api_key,
        "deepseek": settings.deepseek_api_key,
        "anthropic": settings.anthropic_api_key,
        "ollama": "local",
    }
    if settings.generation_provider not in providers:
        raise LocalError("Invalid RAG_GENERATION_PROVIDER; see docs/how-to/providers.md")
    if settings.generation_provider != "ollama" and not providers[settings.generation_provider]:
        variable = {"openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}[settings.generation_provider]
        if not any(item.startswith(variable) for item in missing):
            missing.append(variable + " (for answers)")
    if missing:
        raise LocalError("Missing configuration in .env:\n  - " + "\n  - ".join(missing))


def _docker(*arguments: str, capture: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["docker", "compose", "-p", PROJECT, "-f", str(_checkout() / "compose.yaml"), *arguments]
    try:
        return subprocess.run(
            command, cwd=ROOT, text=True, capture_output=capture, check=False,
        )
    except FileNotFoundError as error:
        raise LocalError("Docker is not installed. Install Docker with Compose, then retry.") from error
    except OSError as error:
        raise LocalError("Could not run Docker Compose. Check Docker installation and permissions.") from error


def _docker_ready() -> bool:
    listing = _docker("ps", "--status", "running", "-q", "db")
    if listing.returncode != 0 or not listing.stdout.strip():
        return False
    container_id = listing.stdout.strip().splitlines()[0]
    try:
        health = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_id],
            text=True, capture_output=True, check=False,
        )
    except OSError:
        return False
    return health.returncode == 0 and health.stdout.strip() == "healthy"


def _worker_info(root: Path | None = None) -> tuple[int, str] | None:
    try:
        record = json.loads((_state_dir(root) / "worker.json").read_text(encoding="utf-8"))
        pid, token = record["pid"], record["token"]
        if isinstance(pid, int) and pid > 0 and isinstance(token, str) and len(token) == 32:
            return pid, token
    except (FileNotFoundError, ValueError, KeyError, TypeError, OSError):
        pass
    return None


def _worker_alive(info: tuple[int, str] | None) -> bool:
    if info is None:
        return False
    pid, token = info
    try:
        # The token distinguishes our worker from a recycled PID or another Python process.
        result = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "args="],
            text=True, capture_output=True, check=False,
        )
        return result.returncode == 0 and "app.local" in result.stdout and token in result.stdout
    except OSError:
        return False


def _worker_ready(info: tuple[int, str] | None, root: Path | None = None) -> bool:
    if not _worker_alive(info):
        return False
    try:
        return (_state_dir(root) / "ready").read_text(encoding="utf-8").strip() == info[1]
    except OSError:
        return False


@contextmanager
def _lock(root: Path | None = None):
    root = root or ROOT
    if os.name != "posix":
        raise LocalError("The local worker manager requires Linux, macOS, or WSL.")
    import fcntl

    directory = _state_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "manager.lock").open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _clean_stale_record(root: Path | None = None) -> None:
    (_state_dir(root) / "worker.json").unlink(missing_ok=True)
    (_state_dir(root) / "ready").unlink(missing_ok=True)


def start() -> int:
    root = _checkout()
    if not (root / ".env").exists():
        template = root / ".env.example"
        if not template.is_file():
            raise LocalError("Missing .env.example; cannot prepare local configuration")
        destination = root / ".env"
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(template.read_text(encoding="utf-8"))
        raise LocalError("Created .env. Fill in your provider key and RAG_GENERATION_MODEL, then run rag start again.")
    _verify_configuration()
    with _lock():
        print("Checking Docker...")
        available = _docker("version")
        if available.returncode != 0:
            raise LocalError("Docker Compose is unavailable. Start Docker and verify docker compose version.")
        print("Starting PostgreSQL...")
        database = _docker("up", "-d", "--wait", "db")
        if database.returncode != 0 or not _docker_ready():
            raise LocalError("PostgreSQL did not become healthy. Check the local Docker Compose database.")
        print("PostgreSQL ready.")
        print("Applying migrations...")
        migrated = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", "head"],
            cwd=root, env=os.environ.copy(), capture_output=True, text=True, check=False,
        )
        if migrated.returncode != 0:
            raise LocalError("Database migration failed. Check the database connection and migration configuration.")
        print("Migrations complete.")
        if _worker_ready(_worker_info()):
            print("Ingestion worker already running.")
        else:
            if _worker_alive(_worker_info()):
                raise LocalError("Worker is running but not ready. See .rag-data/local-runtime/worker.log")
            _clean_stale_record()
            token = uuid4().hex
            directory = _state_dir()
            with (directory / "worker.log").open("a", encoding="utf-8") as log:
                process = subprocess.Popen(
                    [sys.executable, "-m", "app.local", "worker", token],
                    cwd=root, env=os.environ.copy(), stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                )
            (directory / "worker.json").write_text(
                json.dumps({"pid": process.pid, "token": token}), encoding="utf-8"
            )
            for _ in range(START_TIMEOUT * 10):
                if _worker_ready((process.pid, token)):
                    break
                if process.poll() is not None:
                    raise LocalError("Worker exited during startup. See .rag-data/local-runtime/worker.log")
                time.sleep(0.1)
            else:
                raise LocalError("Worker did not become ready. See .rag-data/local-runtime/worker.log")
            print("Ingestion worker ready.")
    print("\nReady! Try:")
    print("  rag add docs/assets/sample.md")
    print('  rag ask "When is the support desk open?"')
    return 0


def status() -> int:
    _checkout()
    try:
        database = _docker_ready()
    except LocalError:
        database = False
    worker = _worker_ready(_worker_info())
    print(f"PostgreSQL: {'ready' if database else 'stopped or unhealthy'}")
    print(f"Worker:     {'ready' if worker else 'stopped or unhealthy'}")
    return 0 if database and worker else 1


def _stop_worker() -> None:
    info = _worker_info()
    if not _worker_alive(info):
        _clean_stale_record()
        print("Worker already stopped.")
        return
    assert info is not None
    pid, token = info
    print("Stopping ingestion worker...")
    os.kill(pid, signal.SIGTERM)
    for _ in range(STOP_TIMEOUT * 10):
        if not _worker_alive((pid, token)):
            _clean_stale_record()
            print("Worker stopped.")
            return
        time.sleep(0.1)
    raise LocalError("Worker did not exit in time. Check .rag-data/local-runtime/worker.log")


def stop() -> int:
    _checkout()
    with _lock():
        _stop_worker()
        print("Stopping PostgreSQL (preserving indexed data)...")
        result = _docker("stop", "db")
        if result.returncode != 0:
            raise LocalError("Could not stop PostgreSQL. Check Docker Compose status.")
    print("Stopped. Indexed data and model caches were preserved.")
    return 0


def reset(*, yes: bool = False) -> int:
    root = _checkout()
    if not yes:
        print("This deletes the local Docker database and all indexed data/conversations.")
        print("Original documents and shared model caches are not deleted.")
        if input("Type RESET to continue: ").strip() != "RESET":
            print("Cancelled.")
            return 1
    with _lock():
        _stop_worker()
        result = _docker("down", "--volumes")
        if result.returncode != 0:
            raise LocalError("Could not remove local database volume. Check Docker Compose status.")
        from app.config import get_settings
        staged = get_settings().data_dir / "ingestion"
        safe = (root / ".rag-data" / "ingestion").resolve()
        if staged.resolve() == safe:
            shutil.rmtree(safe, ignore_errors=True)
        else:
            print("Custom staging path was preserved; remove it manually if necessary.")
    print("Local database reset. Run rag start to initialize a fresh one.")
    return 0


async def _run_worker() -> None:
    from app.worker import run_worker

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for selected_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(selected_signal, stop_event.set)
    await run_worker(stop_event=stop_event)


def worker_child(token: str) -> int:
    """Internal subprocess entry; never called through public CLI arguments."""
    load_environment()
    try:
        import psycopg
        from app.config import get_settings

        with psycopg.connect(get_settings().database_url, connect_timeout=5) as connection:
            connection.execute("SELECT 1")
        ready = _state_dir() / "ready"
        ready.write_text(token, encoding="utf-8")
        try:
            asyncio.run(_run_worker())
        finally:
            if ready.exists() and ready.read_text(encoding="utf-8") == token:
                ready.unlink(missing_ok=True)
        return 0
    except Exception:
        import logging
        logging.exception("Local ingestion worker failed")
        return 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "worker" and re.fullmatch(r"[0-9a-f]{32}", sys.argv[2]):
        raise SystemExit(worker_child(sys.argv[2]))
    raise SystemExit("This module is managed through the rag CLI")
