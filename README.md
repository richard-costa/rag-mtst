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

## Quick Start — Local CLI

Use Docker for PostgreSQL only. The CLI and its background ingestion worker run
on your computer and share temporary input files directly. Requires Docker with
Compose, [uv](https://docs.astral.sh/uv/getting-started/installation/), and a
Linux/macOS or WSL shell. Run these commands from a source checkout.

Install the `rag` command once (ensure uv's tool directory is on your PATH):

```bash
uv tool install --editable .
```

Start the local environment:

```bash
rag start
```

On the first run, `rag start` creates a private `.env` template if needed.
Edit it to provide `OPENAI_API_KEY` and an available `RAG_GENERATION_MODEL`,
then run `rag start` again. It validates configuration, starts a dedicated local
PostgreSQL container, applies migrations, and starts the worker in the background.
`RAG_API_KEY` is only needed if you also run the HTTP API.

Once ready:

```bash
rag add docs/assets/sample.md
rag search "support hours"
rag ask "When is the support desk open?"
```

Indexing and hosted inference send document text to your configured provider and
may incur charges. Original files are not archived; keep your own copies.

```bash
rag status        # Show database and worker readiness
rag stop          # Stop local services; preserve indexed data
rag start         # Resume later
rag reset         # Confirm permanent deletion of local indexed data
```

The local manager requires an editable source checkout and manages only the
default local database. Other database setups, the full Docker stack, HTTP API,
and alternative providers are documented in [Run the backend](docs/how-to/run.md)
and [Provider setup](docs/how-to/providers.md). The optional
[browser demo](demo/README.md) is not part of the CLI quickstart.

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