# Your First Search

In this exercise you will start a disposable database, index a synthetic document,
search its text, and confirm that duplicate submissions do not rebuild the index.
You will use local embeddings and lexical search, with no paid model calls.

## Prerequisites

- A repository checkout, Python 3.14+, [uv](https://docs.astral.sh/uv/), and Docker.
- An accessible Docker daemon, a free port 55432, and sufficient disk space for
  the database image, CPU PyTorch, and a small embedding model.
- Network access for the initial dependency, image, and model downloads.

If uv is not installed, follow [Install uv](../how-to/run.md#install-uv) before
continuing.

Run commands from the repository root. Examples use POSIX-style shell syntax;
fish also accepts the `export NAME=value` assignments shown here. If uv is installed
only inside this checkout, replace `uv` with `.venv/bin/uv`.

## 1. Install and Configure

```bash
uv sync --locked --extra local
export DATABASE_URL=postgresql://rag:rag@127.0.0.1:55432/rag
export RAG_TENANT_ID=first-search
export RAG_DATA_DIR=.rag-first-search
export RAG_EMBEDDING_PROVIDER=local
```

The first embedding operation downloads
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. Subsequent runs
reuse its cache. Keep `--extra local` on the uv commands in this exercise.
Host commands do not load `.env` automatically.

## 2. Start the Exercise Database

Check that the container name and port below are unused. Do not substitute an
existing database: cleanup will remove this exercise's database.

```bash
docker run --rm -d --name rag-mtst-first-search \
  -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=rag -e POSTGRES_PASSWORD=rag -e POSTGRES_DB=rag \
  pgvector/pgvector:pg17
docker exec rag-mtst-first-search pg_isready -U rag -d rag
```

Repeat the readiness command until it reports accepting connections, then:

```bash
uv run --extra local alembic upgrade head
uv run --extra local alembic current
```

The current revision should be `0001_initial`.

## 3. Start the Worker

Open another terminal at the repository root and repeat the four `export`
assignments from step 1. Start the worker and leave it running:

```bash
uv run --extra local python -m app.worker
```

The CLI submits ingestion jobs; it does not process them. Both terminals must use
the same database, tenant, and staging directory.

## 4. Index and Search

In the first terminal:

```bash
uv run --extra local rag add docs/assets/sample.md
uv run --extra local rag search "support hours" --method lexical --limit 3
```

The add command reports a queued job, waits for the worker, and then reports
completion. Search prints matching passages with their source titles and
zero-based chunk indices. Read the passage about support hours.

```bash
uv run --extra local rag add docs/assets/sample.md
```

The second add reports that the document is already indexed. Identical bytes
with the same extraction profile reuse the source without another embedding call.

## 5. Clean Up Only This Exercise

Stop the worker with Ctrl+C, then:

```bash
docker stop rag-mtst-first-search
rm -rf .rag-first-search
```

The container's `--rm` option removes its disposable database storage. Keep shared
model caches and unrelated Docker resources. Close the exercise terminals to
discard their exported configuration.

## Next Steps

- [Choose providers](../how-to/providers.md) to generate your first answer.
- [Run the backend](../how-to/run.md) to use the HTTP API or local demo.
- [Ingest and reindex documents](../how-to/ingest.md) to work with your own files.
- [Understand retrieval](../explanation/retrieval.md) before comparing search methods.