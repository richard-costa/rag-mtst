"""Worker polling and failure classification without a database."""

from __future__ import annotations

import asyncio

import psycopg
import pytest

from app import worker
from app.config import Settings
from app.embeddings import EmbeddingError


@pytest.mark.parametrize(
    "error,category",
    [
        (worker.JobExecutionError("provider"), "provider"),
        (asyncio.CancelledError(), "interrupted"),
        (TimeoutError(), "timeout"),
        (psycopg.OperationalError(), "database"),
        (EmbeddingError(), "provider"),
        (ValueError(), "input_or_configuration"),
        (RuntimeError(), "unexpected"),
    ],
)
def test_failures_map_to_stable_categories(error, category):
    assert worker._error_category(error) == category


async def test_worker_loop_survives_database_errors_and_stops_mid_job(
    monkeypatch, capsys
):
    stop = asyncio.Event()
    calls = 0
    cancelled = False

    async def run_once(**kwargs):
        nonlocal calls, cancelled
        calls += 1

        if calls == 1:
            raise psycopg.OperationalError("database unavailable")

        if calls == 2:
            return False

        stop.set()

        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise

    monkeypatch.setattr(worker, "run_once", run_once)
    monkeypatch.setattr(worker, "POLL_SECONDS", 0.01)

    async with asyncio.timeout(5):
        await worker.run_worker(settings=Settings(), stop_event=stop)

    assert calls == 3 and cancelled
    assert "Worker database operation failed" in capsys.readouterr().err
