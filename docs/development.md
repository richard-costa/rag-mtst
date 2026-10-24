# Develop and integrate RAG-MTST

This project uses Python 3.14+, uv, FastAPI, PostgreSQL 17/pgvector, Alembic,
and a separate ingestion worker. The **CLI calls feature functions directly**;
it does not call HTTP endpoints. Start with the [quickstart](quickstart.md)
before modifying internals.

## Choose your entry point

| Change or investigate | Start here |
| --- | --- |
| CLI arguments and output | `app/cli.py` |
| Local `start/status/stop/reset` supervisor | `app/local.py` |
| Shared settings/defaults | `app/config.py` |
| HTTP app/authentication and routes | `app/api/main.py`, `app/api/routes.py` |
| File submission/content identity | `app/ingestion.py` |
| Worker claims, supervision, cleanup | `app/worker.py` |
| TXT/Markdown/PDF/Office extraction | `app/extraction/` |
| Section-aware chunking | `app/chunking.py` |
| Embedding providers/token fitting | `app/embeddings.py` |
| Retrieval and ranked windows | `app/retrieval.py`, `app/storage/documents.py` |
| Context budgets and citations | `app/generation.py` |
| Generation provider adapters | `app/llm.py` |
| SQL, jobs, transactions | `app/storage/`, `migrations/` |
| Optional visual interface | `demo/` |

## Local development workflow

`uv run` prepares the project environment automatically. You may run
`uv sync` explicitly if your editor needs the dependencies installed beforehand.

```bash
uv run rag start
uv run rag add docs/assets/sample.md
uv run rag search "support hours"
uv run rag stop
```

The host CLI and worker share `.rag-data` by default. The local supervisor
runs PostgreSQL in Docker; it does **not** start the API or demo. Changes to
worker, chunking, extraction, or embedding implementation require restarting
the worker (`rag stop` then `rag start`). They do not automatically reindex
existing documents.

For direct Python feature calls, use the [Python reference](reference/python.md).
To connect another application over HTTP, use the [HTTP reference](reference/http.md).

## Run the API alongside the local manager

First run `uv run rag start`. Configure a strong `RAG_API_KEY` in `.env` in
addition to model credentials. In another shell, from the repository root:

```bash
uv run --env-file .env uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

The API and host worker now share the same local PostgreSQL and staging directory.
The API's `/docs` and `/openapi.json` provide the OpenAPI schema.

To use the optional educational browser interface **instead of** the plain API
process, see [demo instructions](https://github.com/richard-costa/rag-mtst/blob/main/demo/README.md).
Do not start two servers on port 8000 simultaneously. Stop the server with
Ctrl+C; stop the worker/database separately with `uv run rag stop`.

**Important:** the API uses one shared token for a configured tenant. It is not
a public multi-user application; bind a development server to loopback.

## Unit and integration tests

```bash
uv run pytest tests/unit -q
uv run pytest tests/integration -q
```

Unit tests mock model boundaries and need no database. Integration tests use
Testcontainers to create a **disposable** pgvector/PostgreSQL instance and
apply real migrations; Docker must be available. Normal tests make no paid
model requests and do not reset your local application database.

Focused examples:

```bash
uv run pytest tests/unit/test_chunking.py -q
uv run pytest tests/integration/test_retrieval.py -q
uv run pytest tests/unit/test_local.py -q
```

Integration suites cover ingestion, worker supervision, extraction,
retrieval, storage, HTTP, conversations, and CLI behavior. Explicit opt-in
live-model smoke tests are under `tests/integration/test_live_models.py`;
inspect their environment flags and costs before running them. Do not add
billable tests to default CI.

## Deeper architecture constraints

The code is intentionally a small set of feature modules and explicit SQL,
not a framework of services/repositories or an additional queue server.

- **Durable jobs:** job state, staged input identity, and nonsecret settings
  are committed to PostgreSQL. The worker claims jobs with a token and
  heartbeat. Stale jobs fail rather than automatically replay paid work.
- **Atomic replacement:** full replacement chunks are prepared first;
  committing indexed chunks and the owning job is atomic. A failed reindex
  preserves previously searchable text.
- **Tenant scoping:** source, job, conversation, and retrieval operations
  use a configured tenant. This is **not** per-user authentication.
- **Conversation transactions:** a turn holds a row lock while generating,
  committing the question, response, and citation snapshots together.
  A concurrent turn gets 409; a client timeout doesn't prove server cancellation.
- **Citation snapshots:** previous conversation evidence is stored by value;
  reindexing doesn't rewrite it.
- **No permanent input archive:** stage files are removed when jobs terminate;
  back up original files yourself.

More precise implementation descriptions and diagrams are retained in
[architecture internals](explanation/architecture.md),
[indexing internals](explanation/indexing.md), and
[retrieval internals](explanation/retrieval.md).

## Documentation

Edit Markdown under `docs/`, with navigation defined in `mkdocs.yml`. Keep
the README and quickstart aligned with **verified commands**, but avoid copying
entire reference pages into introductory content.

```bash
uv run --group docs mkdocs serve --dev-addr 127.0.0.1:8002
uv run --group docs mkdocs build --strict
```

The strict build checks navigation and links. Preview Mermaid diagrams in a
browser: MkDocs does not execute Mermaid at build time. Keep synthetic samples
and never commit provider keys or source documents with private content.
