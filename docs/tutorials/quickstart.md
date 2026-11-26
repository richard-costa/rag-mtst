# Quickstart: index, search, ask

Recommended first-use path: index a document, search, and generate a cited answer. No HTTP API or demo needed.

## Before you begin

- A Linux, macOS, or WSL terminal.
- [uv](https://docs.astral.sh/uv/getting-started/installation/).
  The project uses Python 3.14+; uv can install a compatible interpreter.
- Docker with the Compose plugin, installed and **running**.
- An OpenAI API key with access to an answer model. Hosted requests may incur charges.
- A source checkout of this repository.

No separate `uv sync`, `pip install`, `uv tool install`, or virtualenv activation
is needed. `uv run` prepares the project's environment automatically.

## 1. Get the project

```bash
git clone https://github.com/richard-costa/rag-mtst.git
cd rag-mtst
```

All subsequent commands run from the repository root.

## 2. Start the local environment

```bash
uv run rag start
```

**First time only:** the command may create a private `.env` template and ask
you to fill in required configuration. Open `.env` and set:

```dotenv
OPENAI_API_KEY=your-private-openai-key
RAG_GENERATION_MODEL=your-available-openai-model
```

Keep the values private; do not commit `.env`. Choose an answer model available
to your account. `RAG_API_KEY` is for the **HTTP server only** and is not needed
for the direct CLI. You can leave it unset while learning the CLI.

Run `uv run rag start` again. A successful run ends with messages like:

```text
PostgreSQL ready.
Migrations complete.
Ingestion worker ready.
```

`rag start` runs PostgreSQL/pgvector in Docker, applies migrations and starts the host worker. Both CLI and worker use the local staging directory.

The first build/download and the first model request can take longer than
subsequent runs.

## 3. Index the sample document

```bash
uv run rag add docs/assets/sample.md
```

The command stages the input and queues a durable job. It waits until the worker
has extracted, chunked, embedded, and indexed the document. Expect progress
through `pending`, `running`, and `completed`, and a final message similar to:

```text
Added sample.md (1 chunks).
```

Repeating an unchanged add normally reports that the source is already indexed.
This is **not** a permanent file backup; keep the original document yourself.

## 4. Search the index

```bash
uv run rag search "support hours"
```

You should see the title `sample.md`, a chunk number, and its supporting text.
The default `window` retrieval uses embeddings to find relevant chunks and
includes nearby chunks when available.

## 5. Ask a question

```bash
uv run rag ask "When is the support desk open?"
```

Expect an answer based on the sample: **Mondays and Wednesdays, 09:00–12:00**,
followed by a reference to `sample.md`. The model's exact wording is not fixed.

References identify supplied passages, not verified conclusions. See [how it works](../explanation/overview.md).

## 6. Stop, resume, or inspect

```bash
uv run rag status
uv run rag stop
```

`rag stop` stops the background worker and local PostgreSQL container. Indexed
data, conversations, originals, `.env`, and model caches remain available. To
resume later:

```bash
uv run rag start
```

**Only for a deliberate fresh start**, `uv run rag reset` deletes the local
database, indexed content, and conversations after confirmation. See
[local lifecycle](../reference/cli.md#local-lifecycle) before using it.

## If something goes wrong

See [troubleshooting](../how-to/troubleshoot.md) and [local lifecycle](../reference/cli.md#local-lifecycle) for the source-checkout and database requirements. For API or production services, see [deploy](../how-to/deploy.md).

## Next steps

- [How it works](../explanation/overview.md) — understand the design.
- [Experiments](experiments.md) — start tinkering.
- [Ingest and manage sources](../how-to/ingest.md) — reindex, list, and delete documents.
- [CLI reference](../reference/cli.md) — options for `add`, `search`, `ask`, and jobs.
- [Optional visual demo](https://github.com/richard-costa/rag-mtst/blob/main/demo/README.md) — see the same pipeline in a browser.
