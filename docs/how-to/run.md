# Run the Backend

Compose is the shortest way to start the complete stack: database, migrations,
HTTP API, and ingestion worker. It requires Docker with Compose; Python and uv
run inside the application containers.

Use host Python processes if you already have PostgreSQL/pgvector and want to run
the application directly. For a disposable local exercise without paid model
calls, use the [tutorial](../tutorials/first-search.md).

## Configure the Environment

Run commands from the repository root. Create a private `.env` file from the
template, without overwriting an existing file:

```bash
cp -n .env.example .env
```

For the default OpenAI workflow, fill in these three values:

| Variable | What to supply |
| --- | --- |
| `RAG_API_KEY` | A private random app access token, separate from provider credentials |
| `OPENAI_API_KEY` | Your OpenAI credential for embeddings and answers |
| `RAG_GENERATION_MODEL` | An available answer model chosen explicitly |

The app access token must be nonempty ASCII without whitespace. Generate it
privately with a password manager or `openssl rand -hex 32`. HTTP clients use the
same token. Direct CLI commands do not need this token or a running HTTP server.

Starting the stack does not call a model. Indexing and asking questions with
hosted models may cost money and send document text to the provider. To use
different providers, follow [provider setup](providers.md); the extra settings
are optional, not part of the default setup.

Do not put keys in tracked files, URLs, screenshots, or logs. Compose reads
`.env` for substitution. Host commands below load it explicitly with
`uv run --env-file .env`; Python does not load the file itself. Existing exported
variables take precedence, so keep them consistent with the file.

The `curl` examples read `$RAG_API_KEY` from your calling shell. Set that variable
privately to the same app token before using them; loading `.env` through Compose
or uv does not export its values into your shell.

## Option A: Compose

After filling in `.env`:

```bash
docker compose config --quiet
docker compose up --build
```

Compose starts `db`, the one-shot `migrate` service, `app`, and `worker`. The last
two use the same settings and wait for migrations; migrations wait for database
readiness. Persistent database data uses `postgres-data`; temporary queued inputs
use the shared `rag-data` volume. `config --quiet` checks Compose configuration,
not credentials or service availability. The API validates its access token when
it starts.

- API: <http://127.0.0.1:8000>.
- Interactive HTTP reference: <http://127.0.0.1:8000/docs>.
- Host database: `127.0.0.1:5432`; application containers use `db:5432`.

The API port is published beyond loopback. Restrict network access; add a reverse
proxy and TLS before remote use. The supplied database credentials are for local
development, not an Internet-facing installation.

For local embeddings, set `RAG_DOCKER_TARGET=app-local` together with
`RAG_EMBEDDING_PROVIDER=local`, then rebuild. Ollama remains an external service;
see [container addresses](../reference/configuration.md#container-addresses).

For visual Office extraction, add the optional converter:

```bash
docker compose --profile office up --build
```

Native parsing and visual PDF do not need this service. The app does not wait
for Office readiness; starting Office does not select visual extraction.

## Option B: Host Processes

Requirements: Python 3.14+, [uv](#install-uv),
reachable PostgreSQL 17 with pgvector available, and a shared writable input
directory.

### Install uv

For host execution, install uv before running the project commands. On Linux
or macOS, use Astral's standalone installer:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new terminal so the updated `PATH` takes effect, then verify installation:

```bash
uv --version
```

See the [official installation guide](https://docs.astral.sh/uv/getting-started/installation/)
for Windows, package-manager alternatives, and inspecting the installer before
running it. Compose-only users do not need a host uv installation.

### Install and Start the Application

The defaults connect to `127.0.0.1:5432/rag` with the local development credentials,
use tenant `default`, and stage inputs in `.rag-data`. Add `DATABASE_URL`,
`RAG_TENANT_ID`, or `RAG_DATA_DIR` to `.env` only when these defaults do not fit
your setup. Use an absolute staging path if processes run from different working
directories.

```bash
uv sync --locked --no-dev
uv run --env-file .env --no-dev alembic upgrade head
uv run --env-file .env --no-dev alembic current
```

The migration role must be able to create the schema and enable the `vector`
extension, or an administrator must enable the extension first. A separately
configured runtime role does not need extension-installation privileges.

Start these commands in separate terminals at the repository root. Both load the
same `.env` file:

```bash
uv run --env-file .env --no-dev python -m app.worker
```

```bash
uv run --env-file .env --no-dev uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

For local embeddings, add `--extra local` to installation and subsequent uv run
commands. API, CLI, and worker must share `DATABASE_URL`, `RAG_TENANT_ID`, and
the same `RAG_DATA_DIR` path. Pending inputs must remain available to the worker.
Use the same command prefix for the CLI:

```bash
uv run --env-file .env --no-dev rag search "support hours" --method lexical
```

Search needs indexed documents. The CLI uses the database directly and needs
neither the HTTP server nor its key.

The API refuses startup without a valid `RAG_API_KEY`; startup does not certify
database, provider, or converter availability. Check the configured workflows
before relying on the deployment. Use process supervision, not `--reload`, for
long-running operation.

## Open the Local Demo

From a source checkout, replace the host API command with:

```bash
uv run --env-file .env --no-dev uvicorn demo.server:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/demo/> and enter the configured API token. It stays
in page memory; provider keys stay on the backend. Keep the wrapper on loopback.
It uses the real database, worker, and providers, not a sandbox. Uploads persist
and hosted operations may cost money. The demo supports stateless answers, not
conversation history, and is excluded from the backend wheel and Docker image.

## Stop or Recover Services

Ctrl+C stops a host process, not the other services or accepted jobs. To stop
Compose, preserving volumes:

```bash
docker compose down
```

Include `--profile office` if you started that profile. Do not add `--volumes`
or run global pruning as routine cleanup.

Back up the database and staged inputs together if pending work must survive.
Keep originals separately: completed and failed inputs are deleted. Pre-release
schema changes are folded into `0001_initial`; `upgrade head` does not reapply
an already-recorded revision. Never reset an existing database implicitly.
See [data lifecycle](../explanation/security.md#storage-and-recovery).