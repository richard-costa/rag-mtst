"""PostgreSQL-backed ingestion execution with claim fencing and heartbeats."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import asdict
import json
import logging
import os
from pathlib import Path
import signal
import sys
from time import monotonic
from uuid import UUID

import psycopg

from app.config import Settings, get_settings
from app.embeddings import EmbeddingError
from app.ingestion import cleanup_ingestion_inputs, process_ingestion_job
from app.storage.database import Database
from app.storage.records import IngestionJob
from app.storage import jobs


POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 5.0
STALE_SECONDS = 60
JOB_TIMEOUT_SECONDS = 900
SHUTDOWN_GRACE_SECONDS = 5
DATABASE_TIMEOUT_SECONDS = 5
logger = logging.getLogger(__name__)
ERROR_EXIT_CODES = {"unexpected": 1, "provider": 2, "database": 3, "input_or_configuration": 4}


class JobExecutionError(RuntimeError):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


def _error_category(error: BaseException) -> str:
    if isinstance(error, JobExecutionError):
        return error.category
    if isinstance(error, asyncio.CancelledError):
        return "interrupted"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, psycopg.Error):
        return "database"
    if isinstance(error, EmbeddingError):
        return "provider"
    if isinstance(error, ValueError):
        return "input_or_configuration"
    return "unexpected"


async def _log_outcome(settings: Settings, storage: Database, job: IngestionJob, started: float, category: str) -> None:
    current = None
    try:
        async with asyncio.timeout(DATABASE_TIMEOUT_SECONDS):
            current = await jobs.get_ingestion_job(storage, settings.tenant_id, job.id)
    except (psycopg.Error, TimeoutError):
        pass
    stage = current.stage if current is not None else "unknown"
    if stage not in {"extracting", "chunking", "embedding", "storing", "completed"}:
        stage = "unknown"
    if current is not None and current.status == "completed":
        category = "none"
    logger.log(
        logging.INFO if category == "none" else logging.WARNING,
        "job_id=%s stage=%s elapsed_seconds=%.3f error_category=%s",
        job.id, stage, monotonic() - started, category,
    )


async def _execute_job(job: IngestionJob, *, settings: Settings, storage: Database) -> None:
    configuration = asdict(settings)
    configuration["data_dir"] = str(settings.data_dir)
    payload = json.dumps({
        "settings": configuration, "job_id": str(job.id), "claim_token": str(job.claim_token),
    }).encode() + b"\n"
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.worker", "--execute-job",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
    )
    try:
        assert process.stdin is not None
        process.stdin.write(payload)
        await process.stdin.drain()
        exit_code = await process.wait()
        if exit_code != 0:
            category = next((name for name, code in ERROR_EXIT_CODES.items() if code == exit_code), "unexpected")
            raise JobExecutionError(category)
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=SHUTDOWN_GRACE_SECONDS)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await asyncio.wait_for(process.wait(), timeout=SHUTDOWN_GRACE_SECONDS)
            finally:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
        if process.stdin is not None:
            process.stdin.close()


async def _execute_child() -> int:
    reader = asyncio.StreamReader()
    transport, _protocol = await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer,
    )
    processing = None
    parent_closed = None
    try:
        payload = json.loads(await reader.readline())
        configuration = payload["settings"]
        configuration["data_dir"] = Path(configuration["data_dir"])
        settings = Settings(**configuration)
        storage = Database(settings.database_url)
        job = await jobs.get_ingestion_job(storage, settings.tenant_id, UUID(payload["job_id"]))
        if job is None or job.status != "running" or str(job.claim_token) != payload["claim_token"]:
            return ERROR_EXIT_CODES["unexpected"]
        processing = asyncio.create_task(process_ingestion_job(job, settings=settings, storage=storage))
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, processing.cancel)
        parent_closed = asyncio.create_task(reader.read(1))
        done, _pending = await asyncio.wait((processing, parent_closed), return_when=asyncio.FIRST_COMPLETED)
        if parent_closed in done:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        await processing
        return 0
    except Exception as error:
        return ERROR_EXIT_CODES.get(_error_category(error), ERROR_EXIT_CODES["unexpected"])
    finally:
        if parent_closed is not None:
            parent_closed.cancel()
            await asyncio.gather(parent_closed, return_exceptions=True)
        transport.close()


async def run_once(*, settings: Settings, storage: Database) -> bool:
    async with asyncio.timeout(DATABASE_TIMEOUT_SECONDS):
        await jobs.fail_interrupted_ingestion_jobs(storage, settings.tenant_id, stale_seconds=STALE_SECONDS)
        await cleanup_ingestion_inputs(settings=settings, storage=storage)
        job = await jobs.claim_ingestion_job(storage, settings.tenant_id)
    if job is None:
        return False
    assert job.claim_token is not None
    started = monotonic()
    category = "none"

    async def heartbeat() -> None:
        while True:
            assert job.claim_token is not None
            async with asyncio.timeout(DATABASE_TIMEOUT_SECONDS):
                if not await jobs.heartbeat_ingestion_job(storage, settings.tenant_id, job.id, job.claim_token):
                    raise RuntimeError("Ingestion job ownership was lost")
            await asyncio.sleep(HEARTBEAT_SECONDS)

    processing = asyncio.create_task(_execute_job(job, settings=settings, storage=storage))
    keeping_alive = asyncio.create_task(heartbeat())
    try:
        async with asyncio.timeout(JOB_TIMEOUT_SECONDS):
            done, _pending = await asyncio.wait((processing, keeping_alive), return_when=asyncio.FIRST_COMPLETED)
            if processing in done:
                await processing
            else:
                await keeping_alive
    except BaseException as error:
        category = _error_category(error)
        processing.cancel()
        try:
            async with asyncio.timeout(DATABASE_TIMEOUT_SECONDS):
                await jobs.fail_ingestion_job(storage,
                    settings.tenant_id, job.id, job.claim_token,
                    error="Worker interrupted; resubmit explicitly." if category == "interrupted"
                    else "Ingestion timed out; resubmit explicitly." if category == "timeout"
                    else "Ingestion failed; check the source and worker configuration before resubmitting.",
                )
        except (psycopg.Error, TimeoutError):
            pass
        finally:
            await asyncio.gather(processing, return_exceptions=True)
        if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise
    finally:
        keeping_alive.cancel()
        await asyncio.gather(keeping_alive, return_exceptions=True)
        try:
            async with asyncio.timeout(DATABASE_TIMEOUT_SECONDS):
                await cleanup_ingestion_inputs(settings=settings, storage=storage)
        except (OSError, ValueError, psycopg.Error, TimeoutError):
            logger.warning("job_id=%s stage=cleanup error_category=cleanup", job.id)
        await _log_outcome(settings, storage, job, started, category)
    return True


async def run_worker(*, settings: Settings | None = None, stop_event: asyncio.Event | None = None) -> None:
    active_settings = settings or get_settings()
    storage = Database(active_settings.database_url)
    stop = stop_event or asyncio.Event()
    stopping = asyncio.create_task(stop.wait())
    try:
        while not stop.is_set():
            iteration = asyncio.create_task(run_once(settings=active_settings, storage=storage))
            try:
                done, _pending = await asyncio.wait((iteration, stopping), return_when=asyncio.FIRST_COMPLETED)
                if stopping in done:
                    iteration.cancel()
                    await asyncio.gather(iteration, return_exceptions=True)
                    break
                worked = await iteration
            except (psycopg.Error, TimeoutError):
                print("Worker database operation failed; waiting before the next poll.", file=sys.stderr)
                worked = False
            finally:
                if not iteration.done():
                    iteration.cancel()
                    await asyncio.gather(iteration, return_exceptions=True)
            if not worked:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
                except TimeoutError:
                    pass
    finally:
        stopping.cancel()
        await asyncio.gather(stopping, return_exceptions=True)


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for selected_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(selected_signal, stop.set)
    await run_worker(stop_event=stop)


if __name__ == "__main__":
    if sys.argv[1:] == ["--execute-job"]:
        raise SystemExit(asyncio.run(_execute_child()))
    asyncio.run(_main())
