# RAG-MTST documentation

Start with the [quickstart](tutorials/quickstart.md). RAG-MTST is a Python RAG backend; the CLI needs only PostgreSQL and the ingestion worker, not an HTTP server. See [security and data lifecycle](explanation/security.md) before deploying this pre-release, trusted software. Data is partitioned into caller-named collections, but one shared API key accesses all of them.

## Tutorials: learn by doing

- [Quickstart](tutorials/quickstart.md): index, search and ask.
- [Experiments](tutorials/experiments.md): compare retrieval, chunking and prompts; inspect a job.

## How-to guides: complete a task

- [Ingest and manage sources](how-to/ingest.md)
- [Search and ask](how-to/search.md)
- [Use conversations](how-to/conversations.md)
- [Choose model providers](how-to/providers.md)
- [Develop and test](how-to/develop.md)
- [Deploy](how-to/deploy.md)
- [Troubleshoot](how-to/troubleshoot.md)

## Reference: look up exact contracts

- [CLI](reference/cli.md)
- [HTTP API](reference/http.md)
- [Python API](reference/python.md)
- [Configuration](reference/configuration.md)
- [Formats, limits and scope](reference/limits.md)

## Explanation: understand the design

- [How it works](explanation/overview.md)
- [Architecture and transactions](explanation/architecture.md)
- [Extraction and indexing](explanation/indexing.md)
- [Retrieval and answers](explanation/retrieval.md)
- [Security and data lifecycle](explanation/security.md)

Optional: [browser demo](https://github.com/richard-costa/rag-mtst/blob/main/demo/README.md).
