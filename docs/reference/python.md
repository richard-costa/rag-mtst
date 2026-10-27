# Python API

Public feature functions are asynchronous unless noted. Await them in an async
application. `Settings` and a `Database` handle can be supplied explicitly;
`storage=` arguments take `app.storage.database.Database`. Omitted settings come
from the environment. No HTTP credential is required for direct calls.

## Feature Entry Points

| Module | Symbols | Contract |
| --- | --- | --- |
| `app.config` | `Settings`, `get_settings` | Immutable configuration; `Settings.from_environment()` reads exported variables |
| `app.ingestion` | `enqueue_file`, `enqueue_bytes` | Submit durable work; return `IngestionSubmission` |
| `app.ingestion` | `add_file`, `add_bytes` | Execute indexing directly; return `IngestionResult` |
| `app.retrieval` | `search` | Validate/select retrieval strategy; return a list of `SearchResult` |
| `app.generation` | `answer` | Retrieve and generate; return `Answer` |
| `app.worker` | `run_once`, `run_worker` | Execute at most one job, or poll until stopped |
| `app.api.main` | `create_app` | Synchronous FastAPI application factory; validates HTTP key at lifespan startup |
| `app.cli` | `main` | Synchronous console entry point; returns exit code |

## Ingestion

`enqueue_file(path, ...)` and `enqueue_bytes(content, source_name=..., ...)`
accept settings, storage, `reindex`, and `extraction_method`. An
`IngestionSubmission` contains `source` and nullable `job`: null means an
already-indexed matching source. Otherwise a separate worker is required.

`add_file` and `add_bytes` perform awaited extraction/embedding/index replacement
without a queue or permanent original-file archive. `IngestionResult` contains
`source`, `created`, and `chunk_count`; unchanged direct ingestion has
`created=False` and `chunk_count=0`. Reindex retains source identity.

## Retrieval and Generation

```python
from app.config import Settings
from app.generation import answer
from app.retrieval import search


async def inspect_sources():
    settings = Settings.from_environment()
    matches = await search("support hours", method="lexical", limit=3, settings=settings)
    result = await answer("When is the support desk open?", method="lexical", settings=settings)
    return matches, result
```

`SearchResult` contains `source_id`, `source_title`, `source_reference`,
`chunk_index`, `content`, and nullable `score`. `source_reference` is descriptive
origin metadata, currently a filename for ingested files. It is not necessarily
unique or accessible and does not instruct the backend to fetch a source.
File titles use the reference's basename; non-file titles retain the full
reference without filesystem parsing.

`Answer` contains `text`, `matches`, and `citations`; HTTP names
`text` as `answer`. `Citation` records the supplied passage and its source identity,
reference (`source_reference`), chunk index, and truncation flag. `EmbeddingError` and `GenerationError`
report handled provider failures.

`answer(..., history=messages)` accepts ordered `Message` records for bounded
generation context. Retrieval still uses only the question. History does not
supply citation evidence.

## Extraction and Chunking

| Module | Symbols | Contract |
| --- | --- | --- |
| `app.extraction` | `extract_source`, `get_extraction_profile` | Explicit `parser`/`visual` selection and duplicate-profile identity |
| `app.extraction.parser` | `ExtractedContent`, `ExtractedPage` | Extracted text/profile and optional ordered page/slide records |
| `app.chunking` | `chunk_markdown` | Structural Markdown chunks; explicit soft word budget |
| `app.embeddings` | `prepare_chunks_for_embedding`, `embed_texts` | Fit local chunks before embedding; reject oversized direct local inputs |

`ExtractedContent.from_pages` validates ordered contiguous one-based page/slide
records, including blanks. Passing pages into chunking preserves known body
provenance. Native parsing leaves unknown page numbers unset. Local token slices
inherit parent-body ranges rather than claiming exact slice pages.

## Storage and Conversations

`Database(database_url)` from `app.storage.database` owns connection setup and
cleanup. It is not a SQL gateway: storage operations are module functions that
take the database handle as their first argument.

| Module | Responsibility |
| --- | --- |
| `app.storage.records` | Source, chunk, job, conversation, message, and turn dataclasses |
| `app.storage.documents` | Source/chunk persistence, lexical/vector search, and chunk windows |
| `app.storage.jobs` | Durable job submission, claims, progress, failure, and atomic completion |
| `app.storage.conversations` | Conversation creation, history, locked turns, and conversation exceptions |

Ordinary indexing, search, and generation should use feature functions rather
than reimplement their SQL workflows. The conversation functions below belong
to `app.storage.conversations`:

- `create_conversation(database, tenant_id)` returns a new conversation.
- `list_messages(database, tenant_id, conversation_id, limit=50, before=None)` returns
  tenant-scoped, ascending sequence history from the selected page.
- `conversation_turn(database, tenant_id, conversation_id, question)` is an async context
  manager: it reserves the conversation and provides recent `history`. Generate
  an answer, then set `turn.answer` and `turn.citations` (citation dictionaries).
  Normal exit commits both messages; exceptions/cancellation roll back.
- `ConversationBusy` reports overlapping turns; `ConversationNotFound` covers
  missing and other-tenant conversations.

The transaction and database connection remain open during retrieval/generation.
There is no connection pool. See [architecture](../explanation/architecture.md)
and the source definitions for complete signatures and internal record fields.