# Develop and test

Complete the [quickstart](../tutorials/quickstart.md) before modifying internals.

## Choose your entry point

Code ownership map:

| Responsibility | Module(s) |
| --- | --- |
| CLI arguments and output | `app/cli.py` |
| Local lifecycle (`start/status/stop/reset`) | `app/local.py` |
| Defaults and environment parsing | `app/config.py` |
| FastAPI factory and lifespan | `app/api/main.py` |
| Central HTTP router registration | `app/api/router.py` |
| HTTP authentication and application resources | `app/api/dependencies.py` |
| Source, job, search, answer and conversation endpoints | `app/api/routers/` |
| Shared API answer orchestration and response conversion | `app/api/services.py` |
| HTTP request and response models | `app/api/schemas/` |
| Ingestion submission, staging and deduplication | `app/ingestion.py` |
| Job execution, child supervision and heartbeats | `app/worker.py` |
| Native/visual document extraction | `app/extraction/` |
| Section-aware chunking and provenance | `app/chunking.py` |
| Hosted/local embeddings and input fitting | `app/embeddings.py` |
| Retrieval strategies and windows | `app/retrieval.py` |
| Prompt budgets, history and citation validation | `app/generation.py` |
| Model client and provider-specific output | `app/llm.py` |
| Database handle and shared records | `app/storage/database.py`, `app/storage/records.py` |
| Source listing/deletion, chunk persistence, lexical/vector queries | `app/storage/documents.py` |
| Job claims, fencing, atomic completion | `app/storage/jobs.py` |
| Conversation management, history and transactions | `app/storage/conversations.py` |
| PostgreSQL schema and migrations | `migrations/` |
| Optional visual teaching interface | `demo/` |

### HTTP package boundaries

Each feature module under `app/api/routers/` declares a module-level `APIRouter`:
`sources.py`, `jobs.py`, `search.py`, `answers.py`, and `conversations.py`.
Search and answer generation are separate API concerns; `/ask` is not a retrieval
endpoint. `router.py` registers these routers centrally under the
`/collections/{collection_id}` prefix with the `get_collection_id` validation
dependency; `main.py` includes that router and applies shared bearer authentication. The ASGI entry point remains `app.api.main:app`.

`create_app(settings)` stores that application's settings and `Database` handle
on `application.state`. Routes receive them through the `SettingsDependency` and
`StorageDependency` aliases in `dependencies.py`, using FastAPI's `Depends` and
`Annotated`. Tests can replace `get_api_settings` and `get_storage` through
`application.dependency_overrides`; separate application instances do not share
configuration or database handles. Routes receive the validated collection
through `CollectionDependency`; there is no server-wide collection setting.

Routers translate application errors to HTTP responses and do not import other
routers. Both `/ask` and conversation turns call `services.generate_answer` with
explicit settings, storage, and optional history. This API-specific helper selects
request-scoped generation settings and constructs response models; it does not
replace `app.generation.answer`. Simple endpoints call feature or storage
functions directly. Domain modules do not depend on FastAPI or HTTP schemas.

## Local development workflow

Use the [quickstart](../tutorials/quickstart.md) for the local stack. Run `uv sync` if your editor needs dependencies in advance. Restart the worker (`rag stop` then `rag start`) after changes to worker, chunking, extraction or embeddings. Existing documents are not automatically reindexed.

For direct Python feature calls, use the [Python reference](../reference/python.md).
To connect another application over HTTP, use the [HTTP reference](../reference/http.md).

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

**Important:** the API uses one shared token for all collections. It is not
a public multi-user application; bind a development server to loopback. See the
[trust boundary](../explanation/security.md#trust-boundary).

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
[architecture and transactions](../explanation/architecture.md):
worker ownership fencing, atomic reindexing, explicit collection scope, and
conversation transaction boundaries. See
[indexing internals](../explanation/indexing.md) and
[retrieval internals](../explanation/retrieval.md) before changing those workflows.

## Optional push checks

Local Ruff automation is opt-in and works with any Git host. Cloning the
repository or installing dependencies does not activate hooks. To enable it
in your checkout:

```bash
uv run pre-commit install --hook-type pre-push
```

Before each push, the hook fixes import ordering, formats changed Python files,
and checks lint across the repository. It does not run on commits. Other lint
rules report findings without automatically changing code; unsafe fixes are
disabled. Markdown files are excluded from Ruff checks and formatting.

If files change, the push stops: review and commit those changes, then push again.
Unresolved lint findings also stop the push and require review. The hook never
creates or amends commits. Its isolated Ruff environment is downloaded on first
use and reused afterward; no GitHub service is required.

To disable the hook in your checkout:

```bash
uv run pre-commit uninstall --hook-type pre-push
```

## Documentation

Edit Markdown under `docs/`, with navigation defined in `mkdocs.yml`. Pages are
grouped as tutorials (`docs/tutorials/`), task guides (`docs/how-to/`), exact
contracts (`docs/reference/`), and design explanations (`docs/explanation/`).
State each fact on the page that owns it and link to it elsewhere. Keep the
README and quickstart aligned with **verified commands**, but avoid copying
reference pages into introductory content.

```bash
uv run --group docs mkdocs serve --dev-addr 127.0.0.1:8002
uv run --group docs mkdocs build --strict
```

Strict builds check navigation and links, not Mermaid execution; preview diagrams in a browser. Keep samples synthetic and private documents/credentials out of Git.

### Docstring conventions

Use concise Google-style docstrings for application functions, classes, and
helpers, including demo and migration code. Document parameters with `Args:`,
results with `Returns:` or `Yields:`, and important failure contracts with
`Raises:` where relevant. Describe actual values, defaults, collection scope, and
side effects rather than repeating type annotations. A single summary line is
enough for a simple no-argument function with no additional contract.

FastAPI endpoint handlers use Markdown docstrings instead: explain inputs,
responses, and important behavior under headings and lists. Set a concise route
`summary` for Swagger UI. Let the docstring supply the OpenAPI description;
an explicit decorator `description` overrides it. Keep detailed retrieval-order
and score semantics intact, and do not claim new runtime behavior in docs.
