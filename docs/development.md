# Develop and integrate RAG-MTST

This project uses Python 3.14+, uv, FastAPI, PostgreSQL 17/pgvector, Alembic,
and a separate ingestion worker. The **CLI calls feature functions directly**;
it does not call HTTP endpoints. Start with the [quickstart](quickstart.md)
before modifying internals.

## Choose your entry point

This is the **single code ownership map**. Conceptual pages explain behavior;
this table tells you where to make a change.

| Responsibility | Module(s) |
| --- | --- |
| CLI arguments and output | `app/cli.py` |
| Local lifecycle (`start/status/stop/reset`) | `app/local.py` |
| Defaults and environment parsing | `app/config.py` |
| FastAPI factory, lifespan and router registration | `app/api/main.py` |
| HTTP authentication and application resources | `app/api/dependencies.py` |
| Source, job, search, answer and conversation endpoints | `app/api/routers/` |
| Shared API answer orchestration and response conversion | `app/api/services.py` |
| HTTP request and response models | `app/api/schemas.py` |
| Ingestion submission, staging and deduplication | `app/ingestion.py` |
| Job execution, child supervision and heartbeats | `app/worker.py` |
| Native/visual document extraction | `app/extraction/` |
| Section-aware chunking and provenance | `app/chunking.py` |
| Hosted/local embeddings and input fitting | `app/embeddings.py` |
| Retrieval strategies and windows | `app/retrieval.py` |
| Prompt budgets, history and citation validation | `app/generation.py` |
| Model client and provider-specific output | `app/llm.py` |
| Database handle and shared records | `app/storage/database.py`, `app/storage/records.py` |
| Chunk persistence, lexical/vector queries | `app/storage/documents.py` |
| Job claims, fencing, atomic completion | `app/storage/jobs.py` |
| Conversation history and transactions | `app/storage/conversations.py` |
| PostgreSQL schema and migrations | `migrations/` |
| Optional visual teaching interface | `demo/` |

### HTTP package boundaries

Each feature module under `app/api/routers/` declares a module-level `APIRouter`:
`sources.py`, `jobs.py`, `search.py`, `answers.py`, and `conversations.py`.
Search and answer generation are separate API concerns; `/ask` is not a retrieval
endpoint. `main.py` registers these routers directly and applies shared bearer
authentication. The ASGI entry point remains `app.api.main:app`.

`create_app(settings)` stores that application's settings and `Database` handle
on `application.state`. Routes receive them through the `SettingsDependency` and
`StorageDependency` aliases in `dependencies.py`, using FastAPI's `Depends` and
`Annotated`. Tests can replace `get_api_settings` and `get_storage` through
`application.dependency_overrides`; separate application instances do not share
configuration or database handles. The HTTP tenant still comes from server
settings, not request headers.

Routers translate application errors to HTTP responses and do not import other
routers. Both `/ask` and conversation turns call `services.generate_answer` with
explicit settings, storage, and optional history. This API-specific helper selects
request-scoped generation settings and constructs response models; it does not
replace `app.generation.answer`. Simple endpoints call feature or storage
functions directly. Domain modules do not depend on FastAPI or HTTP schemas.

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

## Architecture constraints

Maintain the guarantees described in
[architecture and transactions](explanation/architecture.md):
worker ownership fencing, atomic reindexing, explicit tenant scope, and
conversation transaction boundaries. See
[indexing internals](explanation/indexing.md) and
[retrieval internals](explanation/retrieval.md) before changing those workflows.
These guides describe **why** the boundaries matter; the table above shows
**where** to make changes.

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
