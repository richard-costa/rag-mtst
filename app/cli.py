"""Local command-line interface."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from pathlib import Path
import sys
from uuid import UUID

import psycopg

from app.config import get_settings
from app.embeddings import EmbeddingError
from app.generation import GenerationError, answer
from app.ingestion import enqueue_file
from app.retrieval import SearchResult, search
from app.storage.database import Database
from app.storage import jobs


# ---------------------------------------------------------------------------
# Synchronous command entry point
# ---------------------------------------------------------------------------
# The installed console script starts the asynchronous command workflow here.

def main(arguments: list[str] | None = None) -> int:
    try:
        return asyncio.run(_run(arguments))
    except KeyboardInterrupt:
        print("Stopped waiting; the submitted job remains available to the worker.", file=sys.stderr)
        return 130


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------
# Each command calls application modules directly rather than the HTTP API.

async def _run(arguments: list[str] | None = None) -> int:
    parser = _build_parser()
    namespace = parser.parse_args(arguments)
    settings = get_settings()
    if namespace.data_dir is not None:
        settings = replace(settings, data_dir=namespace.data_dir)

    try:
        if namespace.command == "add":
            result = await enqueue_file(
                namespace.source, settings=settings, reindex=namespace.reindex,
                extraction_method=namespace.extraction_method,
            )
            if result.job is None:
                print(f"{result.source.title} is already indexed.")
                return 0
            print(f"Queued {result.source.title} (job {result.job.id}).")
            if namespace.no_wait:
                return 0
            storage = Database(settings.database_url)
            previous = None
            while True:
                job = await jobs.get_ingestion_job(storage, settings.tenant_id, result.job.id)
                if job is None:
                    raise ValueError("The ingestion job was not found")
                progress = (job.status, job.stage, job.processed, job.total)
                if progress != previous:
                    counts = f" {job.processed}/{job.total}" if job.processed is not None and job.total is not None else ""
                    print(f"{job.status}: {job.stage or 'waiting for worker'}{counts}", file=sys.stderr)
                    previous = progress
                if job.status == "completed":
                    action = "Reindexed" if namespace.reindex else "Added"
                    print(f"{action} {result.source.title} ({job.total} chunks).")
                    return 0
                if job.status == "failed":
                    raise ValueError(job.error or "Ingestion failed")
                await asyncio.sleep(0.25)

        if namespace.command == "job":
            job = await jobs.get_ingestion_job(Database(settings.database_url), settings.tenant_id, namespace.job_id)
            if job is None:
                raise ValueError("The ingestion job was not found")
            print(f"{job.id}: {job.status} ({job.stage or 'waiting for worker'})")
            if job.error:
                print(job.error, file=sys.stderr)
            return int(job.status == "failed")

        if namespace.command == "search":
            _print_matches(
                await search(
                    namespace.query, limit=namespace.limit, method=namespace.method,
                    window=namespace.window, settings=settings,
                )
            )
            return 0

        if namespace.command == "ask":
            result = await answer(
                namespace.question,
                limit=namespace.limit,
                method=namespace.method,
                window=namespace.window,
                settings=settings,
            )
            print(result.text)
            if result.citations:
                print("\nReferences:")
                for citation in result.citations:
                    print(
                        f"[{citation.id}] {citation.source_title} "
                        f"(chunk {citation.chunk_index}, source {citation.source_id})"
                    )
            return 0
    except (OSError, ValueError, psycopg.Error, EmbeddingError, GenerationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    parser.error("A command is required")
    return 2


# ---------------------------------------------------------------------------
# Command-line parsing
# ---------------------------------------------------------------------------
# Argument parsing is kept separate from execution to make commands easy to test.

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag")
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Directory used for persisted source files.",
    )
    commands = parser.add_subparsers(dest="command")

    add_parser = commands.add_parser("add", help="Index a supported document file.")
    add_parser.add_argument("source", type=Path)
    add_parser.add_argument("--reindex", action="store_true", help="Replace existing chunks and embeddings.")
    add_parser.add_argument("--no-wait", action="store_true", help="Return after durable submission without waiting for the worker.")
    add_parser.add_argument("--extraction-method", choices=["parser", "visual"], default="parser", help="Document extraction method (default: parser).")

    job_parser = commands.add_parser("job", help="Inspect an ingestion job.")
    job_parser.add_argument("job_id", type=UUID)

    search_parser = commands.add_parser("search", help="Search indexed source chunks.")
    search_parser.add_argument("query")

    ask_parser = commands.add_parser("ask", help="Generate an answer grounded in retrieved sources.")
    ask_parser.add_argument("question")
    for command_parser in (search_parser, ask_parser):
        command_parser.add_argument("--limit", type=int, help="Number of matches (window: seed chunks).")
        command_parser.add_argument("--method", choices=["window", "cosine", "lexical", "hybrid"])
        command_parser.add_argument("--window", type=int, help="Neighbors on each side of a seed (default: 2).")
    return parser


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------
# Search results are rendered in one place for consistent CLI output.

def _print_matches(matches: list[SearchResult]) -> None:
    if not matches:
        print("No matching source chunks found.")
        return

    for match in matches:
        label = "context" if match.score is None else f"score {match.score:.2f}"
        print(f"{match.source_title} (chunk {match.chunk_index}, {label})")
        print(match.content)
        print()


    # ---------------------------------------------------------------------------
    # Direct module execution
    # ---------------------------------------------------------------------------
    # This supports `python -m app.cli` in addition to the installed `rag` command.

if __name__ == "__main__":
    raise SystemExit(main())
