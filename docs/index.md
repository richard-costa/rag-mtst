# rag-mtst

rag-mtst turns documents into searchable passages and generates source-cited
answers. It provides a Python API, command-line client, HTTP API, durable
ingestion worker, and an optional local browser demo. PostgreSQL with pgvector
stores documents, jobs, vectors, and conversations.

The project is pre-release. Its shared-token API is intended for a trusted,
single-tenant deployment, not a public multi-user service. Implemented workflows
are not a guarantee of extraction accuracy, retrieval relevance, or answer quality.

## Start Here

| Your goal | Read |
| --- | --- |
| Learn by indexing and searching a sample | [Your first search](tutorials/first-search.md) |
| Deploy, configure, or operate the backend | [How-to guides](how-to/run.md) |
| Look up settings, endpoints, or limits | [Configuration](reference/configuration.md), [HTTP API](reference/http.md), [CLI](reference/cli.md), [formats and limits](reference/limits.md) |
| Understand the design | [Architecture](explanation/architecture.md), [indexing](explanation/indexing.md), [retrieval](explanation/retrieval.md), [security](explanation/security.md) |

The documentation follows [Diataxis](https://diataxis.fr/map/): tutorials teach
through a guided exercise; how-to guides solve specific tasks; reference records
contracts; explanation describes why the system behaves as it does.

## Capabilities

- Extract TXT, Markdown, textual PDF, DOCX, and PPTX locally; optionally transcribe
  PDF or Office page images through an explicitly selected vision model.
- Search by cosine similarity, neighboring windows, lexical terms, or hybrid fusion.
- Use OpenAI or local embeddings independently of OpenAI, DeepSeek, Ollama, or
  Anthropic answer generation.
- Keep successful conversation turns and their citation snapshots, with bounded
  history supplied to subsequent answers.
- Reindex atomically: failed replacement leaves previously indexed content searchable.

For planned work, see the [roadmap](https://github.com/richard-costa/rag-mtst/blob/main/ROADMAP.md).