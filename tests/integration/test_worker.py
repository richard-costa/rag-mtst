from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread

import pytest

from app import ingestion, worker
from app.retrieval import search
from app.storage import documents, jobs

pytestmark = pytest.mark.usefixtures('deterministic_embeddings')


@pytest.mark.usefixtures("inline_worker")
async def test_worker_indexes_durable_input_using_saved_settings(settings, storage):
    content = b"# Worker\n\nUse an access token for authentication."
    submitted = await ingestion.enqueue_bytes(content, source_name="worker.md", settings=settings, storage=storage)
    assert submitted.job is not None
    assert await worker.run_once(settings=replace(settings, chunk_size=500, embedding_model="changed"), storage=storage)
    completed = await jobs.get_ingestion_job(storage, settings.tenant_id, submitted.job.id)
    assert completed is not None and completed.status == "completed" and completed.attempts == 1
    chunks = await documents.list_chunks(storage, settings.tenant_id)
    assert chunks and all(chunk.metadata["embedding_model"] == settings.embedding_model_name for chunk in chunks)
    assert chunks[0].source_reference == "worker.md"
    queued_input = await jobs.get_ingestion_job_input(storage, settings.tenant_id, submitted.job.id)
    assert queued_input is not None and queued_input.input_path is None
    assert not list((settings.data_dir / "ingestion").iterdir())
    assert not await worker.run_once(settings=settings, storage=storage)


@pytest.mark.usefixtures("inline_worker")
async def test_worker_recovery_cleans_abandoned_input_files(settings, storage):
    submitted = await ingestion.enqueue_bytes(
        b"Interrupted input", source_name="interrupted.md", settings=settings, storage=storage,
    )
    assert submitted.job is not None
    queued = await jobs.get_ingestion_job_input(storage, settings.tenant_id, submitted.job.id)
    assert queued is not None and queued.input_path is not None
    staged = Path(queued.input_path)
    claimed = await jobs.claim_ingestion_job(storage, settings.tenant_id)
    assert claimed is not None
    async with storage.connection() as connection:
        await connection.execute(
            "UPDATE ingestion_jobs SET heartbeat_at = now() - interval '2 minutes' WHERE id = %s",
            (claimed.id,),
        )
    assert not await worker.run_once(settings=settings, storage=storage)
    assert not staged.exists() and not staged.parent.exists()
    cleaned = await jobs.get_ingestion_job_input(storage, settings.tenant_id, claimed.id)
    assert cleaned is not None and cleaned.input_path is None
    assert await documents.list_chunks(storage, settings.tenant_id) == []


@pytest.mark.usefixtures("inline_worker")
@pytest.mark.parametrize("missing", [False, True])
async def test_worker_rejects_unavailable_or_changed_input_without_replacing_chunks(settings, storage, missing):
    content = b"Keep the existing indexed content."
    await ingestion.add_bytes(content, source_name="original.md", settings=settings, storage=storage)
    before = await documents.list_chunks(storage, settings.tenant_id)
    submitted = await ingestion.enqueue_bytes(
        content, source_name="original.md", settings=settings, storage=storage, reindex=True,
    )
    assert submitted.job is not None
    queued = await jobs.get_ingestion_job_input(storage, settings.tenant_id, submitted.job.id)
    assert queued is not None and queued.input_path is not None
    staged = Path(queued.input_path)
    if missing:
        staged.unlink()
    else:
        staged.write_bytes(b"Different bytes")
    assert await worker.run_once(settings=settings, storage=storage)
    failed = await jobs.get_ingestion_job(storage, settings.tenant_id, submitted.job.id)
    assert failed is not None and failed.status == "failed"
    assert await documents.list_chunks(storage, settings.tenant_id) == before
    assert not staged.parent.exists()


@pytest.mark.usefixtures("inline_worker")
async def test_worker_failure_preserves_index_and_does_not_replay(settings, storage, monkeypatch, caplog):
    content = b"# Keep\n\nPreviously indexed content."
    await ingestion.add_bytes(content, source_name="keep.md", settings=settings, storage=storage)
    before = await documents.list_chunks(storage, settings.tenant_id)
    submitted = await ingestion.enqueue_bytes(
        content, source_name="keep.md", settings=settings, storage=storage, reindex=True,
    )

    async def fail_embedding(*args, **kwargs):
        raise RuntimeError("private-secret provider payload")

    monkeypatch.setattr(ingestion, "embed_texts", fail_embedding)
    monkeypatch.setattr(worker.logger, "disabled", False)
    caplog.set_level("WARNING", logger=worker.__name__)
    assert await worker.run_once(settings=settings, storage=storage)
    assert submitted.job is not None
    failed = await jobs.get_ingestion_job(storage, settings.tenant_id, submitted.job.id)
    assert failed is not None and failed.status == "failed"
    assert "private-secret" not in (failed.error or "")
    assert "private-secret" not in caplog.text
    assert f"job_id={submitted.job.id}" in caplog.text
    assert "stage=embedding" in caplog.text and "error_category=unexpected" in caplog.text
    queued_input = await jobs.get_ingestion_job_input(storage, settings.tenant_id, submitted.job.id)
    assert queued_input is not None and queued_input.input_path is None
    assert not list((settings.data_dir / "ingestion").iterdir())
    assert await documents.list_chunks(storage, settings.tenant_id) == before
    matches = await search("Previously", method="lexical", settings=settings, storage=storage)
    assert matches and matches[0].source_id == str(submitted.source.id)
    assert matches[0].content == before[0].content
    assert not await worker.run_once(settings=settings, storage=storage)


@pytest.mark.usefixtures("inline_worker")
async def test_worker_heartbeats_during_inference_and_shutdown_fails_without_replay(settings, storage, monkeypatch):
    submitted = await ingestion.enqueue_bytes(b"Long running input", source_name="long.md", settings=settings, storage=storage)
    heartbeats = asyncio.Event()
    original = jobs.heartbeat_ingestion_job
    count = 0

    async def heartbeat(*args):
        nonlocal count
        result = await original(*args)
        count += 1
        if count >= 2:
            heartbeats.set()
        return result

    async def slow_embedding(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(jobs, "heartbeat_ingestion_job", heartbeat)
    monkeypatch.setattr(worker, "HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(ingestion, "embed_texts", slow_embedding)
    running = asyncio.create_task(worker.run_once(settings=settings, storage=storage))
    try:
        await asyncio.wait_for(heartbeats.wait(), timeout=5)
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
    assert submitted.job is not None
    failed = await jobs.get_ingestion_job(storage, settings.tenant_id, submitted.job.id)
    assert failed is not None and failed.status == "failed"
    assert not await worker.run_once(settings=settings, storage=storage)


@pytest.mark.parametrize("shutdown", [False, True])
async def test_worker_force_stops_an_unresponsive_child(settings, storage, monkeypatch, tmp_path, shutdown, caplog):
    content = b"Previously indexed original bytes."
    await ingestion.add_bytes(content, source_name="bounded.md", settings=settings, storage=storage)
    previous_chunks = await documents.list_chunks(storage, settings.tenant_id)
    submitted = await ingestion.enqueue_bytes(
        content, source_name="bounded.md", settings=settings, storage=storage, reindex=True,
    )
    ready = tmp_path / "child-ready"
    command = (
        "import os, signal, time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"Path({str(ready)!r}).write_text(str(os.getpid())); time.sleep(60)"
    )
    spawn = asyncio.create_subprocess_exec
    children = []

    async def spawn_blocked(*arguments, **kwargs):
        process = await spawn(sys.executable, "-c", command, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn_blocked)
    monkeypatch.setattr(worker, "JOB_TIMEOUT_SECONDS", 30 if shutdown else 1)
    monkeypatch.setattr(worker, "SHUTDOWN_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(worker.logger, "disabled", False)
    caplog.set_level("WARNING", logger=worker.__name__)
    running = asyncio.create_task(worker.run_once(settings=settings, storage=storage))
    try:
        async with asyncio.timeout(5):
            while not ready.exists():
                await asyncio.sleep(0.01)
        if shutdown:
            running.cancel()
        async with asyncio.timeout(3):
            outcome = (await asyncio.gather(running, return_exceptions=True))[0]
        assert isinstance(outcome, asyncio.CancelledError) if shutdown else outcome is True
        assert children and children[0].returncode == -signal.SIGKILL
        with pytest.raises(ProcessLookupError):
            os.kill(children[0].pid, 0)
        assert submitted.job is not None
        failed = await jobs.get_ingestion_job(storage, settings.tenant_id, submitted.job.id)
        assert failed is not None and failed.status == "failed"
        assert "error_category=interrupted" in caplog.text if shutdown else "error_category=timeout" in caplog.text
        assert await documents.list_chunks(storage, settings.tenant_id) == previous_chunks
        assert not await worker.run_once(settings=settings, storage=storage)
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
        for process in children:
            if process.returncode is None:
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()


async def test_restarted_worker_fails_interrupted_work_without_replaying_paid_requests(settings, storage):
    entered = Event()
    release = Event()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(payload["input"])
            if any("Interrupted ingestion" in text for text in payload["input"]):
                entered.set()
                release.wait(timeout=15)
            body = json.dumps({"data": [
                {"index": index, "embedding": [1.0, 0.0, 0.0], "object": "embedding"}
                for index in range(len(payload["input"]))
            ]}).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except BrokenPipeError:
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    serving = Thread(target=server.serve_forever, daemon=True)
    serving.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/v1"
    settings = replace(settings, openai_api_key="synthetic-worker-key", openai_base_url=endpoint)
    environment = {
        **os.environ, "DATABASE_URL": settings.database_url,
        "RAG_TENANT_ID": settings.tenant_id, "RAG_DATA_DIR": str(settings.data_dir),
        "OPENAI_API_KEY": "synthetic-worker-key", "OPENAI_BASE_URL": endpoint,
    }
    processes = []
    try:
        first = await ingestion.enqueue_bytes(
            b"Interrupted ingestion", source_name="interrupted.md", settings=settings, storage=storage,
        )
        processes.append(subprocess.Popen(
            [sys.executable, "-m", "app.worker"], env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        ))
        assert await asyncio.to_thread(entered.wait, 10)
        child_pids = subprocess.check_output(
            ["ps", "--ppid", str(processes[0].pid), "-o", "pid="], text=True,
        ).split()
        assert len(child_pids) == 1
        processes[0].kill()
        await asyncio.to_thread(processes[0].wait, 10)
        child_state = Path(f"/proc/{child_pids[0]}/stat")
        async with asyncio.timeout(5):
            while child_state.exists():
                try:
                    state = child_state.read_text().split(") ", 1)[1].split()[0]
                except FileNotFoundError:
                    break
                if state == "Z":
                    break
                await asyncio.sleep(0.01)
        release.set()
        assert first.job is not None
        async with storage.connection() as connection:
            await connection.execute(
                "UPDATE ingestion_jobs SET heartbeat_at = now() - interval '2 minutes' WHERE id = %s",
                (first.job.id,),
            )
        second = await ingestion.enqueue_bytes(
            b"A separate pending job", source_name="pending.md", settings=settings, storage=storage,
        )
        processes.append(subprocess.Popen(
            [sys.executable, "-m", "app.worker"], env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        ))
        assert second.job is not None
        async with asyncio.timeout(15):
            while True:
                completed = await jobs.get_ingestion_job(storage, settings.tenant_id, second.job.id)
                if completed is not None and completed.status in {"completed", "failed"}:
                    assert completed.status == "completed", completed.error
                    break
                await asyncio.sleep(0.05)
        failed = await jobs.get_ingestion_job(storage, settings.tenant_id, first.job.id)
        assert failed is not None and failed.status == "failed" and failed.attempts == 1
        assert len(requests) == 2
        assert sum(any("Interrupted ingestion" in text for text in batch) for batch in requests) == 1
        assert all(chunk.source_id == second.source.id for chunk in await documents.list_chunks(storage, settings.tenant_id))
    finally:
        release.set()
        for process in processes:
            if process.poll() is None:
                process.terminate()
            await asyncio.to_thread(process.wait, 10)
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        serving.join(timeout=5)
