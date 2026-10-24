# RAG-MTST documentation

RAG-MTST is a Python backend for indexing documents and building retrieval-
augmented answers with inspectable source passages. It is designed to be
integrated into other applications.

**New here?** Start with the [quickstart](quickstart.md). You need one local
`rag start` command to bring up PostgreSQL and a background ingestion worker;
the CLI lets you index, search, and ask without starting an HTTP server.

| Where to go | What you'll learn |
| --- | --- |
| [Quickstart](quickstart.md) | First working search and cited answer |
| [How it works](how-it-works.md) | Ingestion, retrieval, generation, persistence |
| [Experiments](experiments.md) | Compare retrieval, change chunking and prompts |
| [Development](development.md) | Code map, local development, tests, docs |
| [Operations](operations.md) | Services, deployment contract, safety and recovery |
| [CLI reference](reference/cli.md) | Exact commands and flags |
| [HTTP API](reference/http.md) | Integrate other applications |
| [Python API](reference/python.md) | Call feature functions directly |
| [Configuration](reference/configuration.md) | Provider and runtime settings |
| [Limits](reference/limits.md) | Format, extraction, worker, and model bounds |

An optional [browser demo](https://github.com/richard-costa/rag-mtst/blob/main/demo/README.md)
provides a visual way to inspect the same backend, but is **not** required to
use the CLI.

The project is pre-release, trusted single-tenant software, not a production
multi-user application. See [operations](operations.md) for its trust boundary.
