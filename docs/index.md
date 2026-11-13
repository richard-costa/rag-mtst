# RAG-MTST documentation

RAG-MTST is a Python backend for indexing documents and building retrieval-
augmented answers with inspectable source passages. It is designed to be
integrated into other applications.

**New here?** Start with the [quickstart](tutorials/quickstart.md). One local
`rag start` command brings up PostgreSQL and a background ingestion worker;
the CLI lets you index, search, and ask without starting an HTTP server.

The documentation has four sections.

## Tutorials: learn by doing

| Page | What you'll do |
| --- | --- |
| [Quickstart](tutorials/quickstart.md) | Index a sample, search it, and get a cited answer |
| [Experiments](tutorials/experiments.md) | Compare retrieval, change chunking and prompts, follow a job |

## How-to guides: complete a task

| Page | Task |
| --- | --- |
| [Ingest and manage sources](how-to/ingest.md) | Add, reindex, list, and delete documents |
| [Search and ask](how-to/search.md) | Retrieve passages and generate answers from the CLI or HTTP |
| [Use conversations](how-to/conversations.md) | Keep, page through, and delete question/answer history |
| [Choose model providers](how-to/providers.md) | Configure embeddings, answers, and visual extraction |
| [Develop and test](how-to/develop.md) | Find code, run the API, run tests, edit docs |
| [Deploy](how-to/deploy.md) | Deployment requirements and the Compose reference setup |
| [Troubleshoot](how-to/troubleshoot.md) | Diagnose common setup, job, HTTP, and model problems |

## Reference: look up exact contracts

| Page | Contents |
| --- | --- |
| [CLI](reference/cli.md) | Commands, flags, local lifecycle, exit codes |
| [HTTP API](reference/http.md) | Endpoints, request and response fields, errors |
| [Python API](reference/python.md) | Feature functions and storage modules |
| [Configuration](reference/configuration.md) | Environment variables and code defaults |
| [Formats, limits and scope](reference/limits.md) | Supported formats, processing bounds, unimplemented features |

## Explanation: understand the design

| Page | Topic |
| --- | --- |
| [How it works](explanation/overview.md) | The ingestion, retrieval, and generation flows at a glance |
| [Architecture and transactions](explanation/architecture.md) | Components, schema, consistency guarantees |
| [Extraction and indexing](explanation/indexing.md) | Source identity, extraction profiles, chunking, durable jobs |
| [Retrieval and answers](explanation/retrieval.md) | Search methods, prompt budget, citations, history |
| [Security and data lifecycle](explanation/security.md) | Trust boundary, provider data flow, what persists |

An optional [browser demo](https://github.com/richard-costa/rag-mtst/blob/main/demo/README.md)
provides a visual way to inspect the same backend, but is **not** required to
use the CLI.

The project is pre-release, trusted single-tenant software, not a production
multi-user application. See [security and data lifecycle](explanation/security.md)
for its trust boundary.
