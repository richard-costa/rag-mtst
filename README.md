# rag-mtst

Async Python backend for document ingestion, passage retrieval, and source-cited
answers. FastAPI and a local CLI share PostgreSQL 17, pgvector, full-text search,
and a durable ingestion worker.

- Native TXT, Markdown, PDF, DOCX, and PPTX parsing; optional visual extraction.
- Hosted or local embeddings; cosine, window, lexical, and hybrid retrieval.
- OpenAI, DeepSeek, Ollama, or Anthropic answers with validated citation IDs.
- Tenant-scoped conversations and atomic, failure-safe reindexing.

Pre-release, trusted single-tenant software. The HTTP API requires a shared bearer
token; public deployment needs additional network, TLS, and abuse controls.
Original files are temporary inputs, not a permanent archive. Citations do not
guarantee factual accuracy; representative answer/extraction quality is unproven.

## Quick Start

Use Docker only for PostgreSQL; run the CLI and ingestion worker locally.
Requires Python 3.14+ with pip, Docker with Compose, and a source checkout.
The commands below use a Linux or macOS shell. Run them from the repository root.

### 1. Install and Configure

```bash
pip install uv
uv sync --locked --no-dev
cp -n .env.example .env
```

If your Python installation prevents installing uv with pip, use the
[alternative installation method](#install-uv).

Set these values in your private `.env` file:

```dotenv
OPENAI_API_KEY=your-openai-api-key
RAG_GENERATION_MODEL=your-chosen-openai-answer-model
```

Choose an answer model available to your OpenAI account. Do not commit credentials.
The CLI uses the database directly and needs neither an HTTP server nor an app
access token.

### 2. Start the Database and Worker

In the first terminal, start PostgreSQL and open a shell with the project
environment and configuration loaded:

```bash
docker compose up -d --wait db
uv run --env-file .env --no-dev "$SHELL"
```

Inside that new shell, initialize the database and start the worker:

```bash
alembic upgrade head
python -m app.worker
```

Leave this terminal running. Initial migrations are a setup step, not something
needed before every question.

### 3. Add Your Document and Ask Questions

Open another terminal at the repository root and prepare its environment once:

```bash
uv run --env-file .env --no-dev "$SHELL"
```

Inside that new shell, replace the example path with your own document:

```bash
rag add "/path/to/your/document.pdf"
rag ask "What are the main points of this document?"
```

`rag add` waits until indexing finishes. TXT, Markdown, DOCX, and PPTX are also
supported. Answers can include source references; later questions search all
indexed documents, not just the most recent upload.

To retrieve passages without generating an answer:

```bash
rag search "deadlines"
```

Hosted indexing and answers send document text to the provider and may incur
charges. Keep your original documents separately; inputs are deleted after
processing.

### Later Sessions and Other Setups

For later sessions, keep the database and worker running and prepare each new
CLI terminal with the shell command above. Installation and initial migrations
do not need repeating. There is no single CLI command that starts the database,
runs migrations, and launches the worker.

For the complete Docker stack or detailed host setup, see
[Run the backend](docs/how-to/run.md). For other model providers, see
[Provider setup](docs/how-to/providers.md). The
[first-search tutorial](docs/tutorials/first-search.md) offers a separate disposable
local exercise without paid model calls.

### Install uv

Host Python workflows and local documentation previews need uv on your machine;
the Compose stack already includes it. On Linux or macOS, use Astral's installer:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new terminal so the updated `PATH` takes effect, then check `uv --version`.
For Windows, package managers, or inspecting the installer before running it,
see the [official installation guide](https://docs.astral.sh/uv/getting-started/installation/).

## Documentation

English Markdown, organized around the [Diataxis map](https://diataxis.fr/map/):

| Need | Documentation |
| --- | --- |
| Learn | [Your first search](docs/tutorials/first-search.md) |
| Complete a task | [Run the backend](docs/how-to/run.md), [providers](docs/how-to/providers.md), [ingestion](docs/how-to/ingest.md), [conversations](docs/how-to/conversations.md), [tests](docs/how-to/test.md) |
| Look up a contract | [Configuration](docs/reference/configuration.md), [HTTP API](docs/reference/http.md), [CLI](docs/reference/cli.md), [Python API](docs/reference/python.md), [limits](docs/reference/limits.md), [troubleshooting](docs/reference/troubleshooting.md) |
| Understand the design | [Architecture](docs/explanation/architecture.md), [indexing](docs/explanation/indexing.md), [retrieval](docs/explanation/retrieval.md), [security](docs/explanation/security.md) |

Preview locally:

```bash
uv sync --locked --group docs
uv run --group docs mkdocs serve --dev-addr 127.0.0.1:8002
```

Open <http://127.0.0.1:8002>. Build with
`uv run --group docs mkdocs build --strict`. See
[documentation maintenance](docs/how-to/documentation.md) for diagram and preview details.

Optional [local browser demo](demo/README.md), available from a source checkout
only. Planned work lives in [ROADMAP.md](ROADMAP.md).