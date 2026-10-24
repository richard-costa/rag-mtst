# Architecture

rag-mtst is an async Python application with a PostgreSQL-backed ingestion queue.
HTTP and CLI are adapters over the same feature modules; the CLI does not make
HTTP requests. A separate worker performs durable ingestion. There is no external
queue service, ORM model layer, or service/repository framework.

```mermaid
---
config:
    flowchart:
        useMaxWidth: false
---
flowchart TB
    http[HTTP client] --> api[FastAPI]
    cli[Local CLI] --> submission[Ingestion submission]
    api --> submission
    submission --> queue[(PostgreSQL job queue)]
    submission --> staging[Shared input directory]
    queue --> worker[Ingestion worker]
    staging --> worker
    worker --> indexing[Extraction, chunking, and embeddings]
    indexing --> documents[(PostgreSQL + pgvector)]
    api --> retrieval[Retrieval]
    cli --> retrieval
    documents -->|Ranked chunk windows| retrieval
    retrieval --> context[Bounded context]
    context --> generation[Answer generation]
    generation --> answer[Answer + citations]
```

The API and worker must see the same staging directory at the same path. Only
temporary inputs live there; indexed content lives in the database. Direct Python
indexing functions can execute synchronously within an awaited workflow instead
of submitting a job.

## Ownership

| Module | Responsibility |
| --- | --- |
| `app/api/main.py` | Application factory, authentication, lifespan, and router registration |
| `app/api/routes.py` | HTTP endpoints, feature calls, status translation, and conversation orchestration |
| `app/api/schemas.py` | HTTP request/response models |
| `app/cli.py` | Arguments, direct feature calls, terminal output |
| `app/config.py` | Immutable settings and environment parsing |
| `app/ingestion.py` | Content identity, staging/submission, indexing orchestration |
| `app/worker.py` | Atomic claims, child-process supervision, heartbeats, cleanup |
| `app/extraction/` | Native parsing or explicit page-image transcription; Office conversion when needed |
| `app/chunking.py` | Markdown blocks, sections, packing, provenance |
| `app/embeddings.py` | Hosted/local inference and local token fitting |
| `app/retrieval.py` | Strategy selection, neighboring windows, hybrid fusion |
| `app/generation.py` | Bounded prompts, history, answer/citation validation |
| `app/llm.py` | SDK clients and provider-specific structured-output paths |
| `app/storage/database.py` | Database handle and connection lifecycle |
| `app/storage/records.py` | Shared persistence dataclasses |
| `app/storage/documents.py` | Source/chunk SQL, lexical/vector search, and chunk windows |
| `app/storage/jobs.py` | Job SQL, ownership fencing, and atomic indexing completion |
| `app/storage/conversations.py` | Conversation/history SQL and locked turn transactions |
| `migrations/` | Explicit Alembic schema definitions |

Storage operations are module functions taking a `Database` handle first, not
methods on a shared SQL gateway. Transaction owners keep their boundaries explicit:
job completion inserts chunks on its existing connection, and conversation turns
hold their connection through answer generation. The package split adds no
connection pool or persistence framework.

## Persistence Model

| Table | Stored information |
| --- | --- |
| `sources` | Tenant-scoped content hash, descriptive locator, source identity |
| `chunks` | Indexed text, metadata, vector, generated lexical search vector |
| `ingestion_jobs` | Durable state, progress, ownership, heartbeats, errors |
| `ingestion_job_inputs` | Temporary input paths and nonsecret queued settings |
| `conversations` | Tenant ownership and conversation timestamps |
| `messages` | Ordered user/assistant text and immutable citation snapshots |

```mermaid
---
config:
    er:
        useMaxWidth: true
---
erDiagram
    direction TB
    sources ||..o{ chunks : contains
    sources ||..o{ ingestion_jobs : tracks
    ingestion_jobs ||--o| ingestion_job_inputs : has
    conversations ||..o{ messages : contains

    sources {
        uuid id PK
        text tenant_id
        text type
        text locator
        text mime_type
        text content_hash
        timestamptz created_at
        timestamptz updated_at
    }
    chunks {
        uuid id PK
        text tenant_id
        uuid source_id FK
        integer chunk_index
        integer page_number
        text content
        tsvector search_vector "generated"
        vector embedding
        jsonb metadata
        timestamptz created_at
    }
    ingestion_jobs {
        uuid id PK
        uuid source_id FK
        text status
        text stage
        integer progress
        integer processed
        integer total
        integer attempts
        text error
        timestamptz created_at
        timestamptz started_at
        timestamptz heartbeat_at
        timestamptz finished_at
        uuid claim_token
    }
    ingestion_job_inputs {
        uuid job_id PK, FK
        text input_path "temporary file path"
        text source_name
        jsonb extraction_profile
        jsonb configuration
        boolean reindex
    }
    conversations {
        uuid id PK
        text tenant_id
        timestamptz created_at
        timestamptz updated_at
    }
    messages {
        uuid id PK
        uuid conversation_id FK
        integer sequence
        text role
        text content
        jsonb citations "saved snapshots"
        timestamptz created_at
    }
```

The diagram shows all tables and columns; `PK` marks primary keys and `FK`
foreign keys. Each child row belongs to one parent, and all foreign keys use
`ON DELETE CASCADE`. A job can have at most one input record, whose file path
is cleared after terminal-input cleanup.

Composite uniqueness applies to `sources(tenant_id, content_hash)`,
`chunks(source_id, chunk_index)`, and `messages(conversation_id, sequence)`.
A partial unique index also permits only one pending or running job per source.
Citation snapshots are JSONB, not foreign keys to current sources or chunks,
so reindexing does not rewrite past evidence. Nullability, defaults, and check
constraints are defined in `migrations/versions/0001_initial.py`.

Original files are temporary filesystem inputs, not stored in PostgreSQL.
The database stores extracted text chunks, embeddings, and metadata. A locator
is descriptive, not a download endpoint or permanent file path. Unconstrained
pgvector columns allow embeddings of different dimensions; provider/model tags
in metadata separate vector spaces. There is no automatic model revision
tracking or historical embedding index.

`chunks.search_vector` uses PostgreSQL `pg_catalog.simple` and a GIN index;
inserts/replacements update it automatically. Vector search is exact, with no
approximate vector index. Connections are short-lived and unpooled, except that
conversation turns retain a connection and transaction through generation.

## Transaction Boundaries

Indexing prepares the complete replacement before a transaction replaces chunks
and completes the owned job. This protects old search results from failed
reindexing. Claim tokens fence stale workers from committing another owner's job.

A conversation uses a tenant-scoped row lock with immediate conflict detection.
It holds that lock through retrieval/generation and commits the question, answer,
and citation snapshots together. Failures roll back both messages. This is simple
cross-process coordination, but long provider requests also occupy a database
connection and keep that conversation locked.

```mermaid
---
config:
    sequence:
        useMaxWidth: false
---
sequenceDiagram
    actor Client
    participant API
    participant DB as PostgreSQL
    participant Answer as Retrieval and generation
    Client->>API: Submit conversation question
    API->>DB: Begin transaction and lock conversation NOWAIT
    Note over API,DB: Missing returns 404 and busy returns 409
    DB-->>API: Recent message history
    Note over API,DB: Connection and lock remain held
    API->>Answer: Current question + recent history
    alt Answer succeeds
        Answer-->>API: Answer + citation snapshots
        API->>DB: Insert both messages and commit
        API-->>Client: Answer, matches, and citations
    else Generation fails or task is cancelled
        API->>DB: Roll back without saving either message
    end
```

The diagram follows a turn that acquires the lock. A client timeout is not proof
of task cancellation: the server may still commit. Read history before retrying
an uncertain request; see [conversation recovery](../how-to/conversations.md#handle-overlap-and-uncertain-outcomes).

See [indexing](indexing.md), [retrieval and answers](retrieval.md), and
[security and data lifecycle](../operations.md) for the behavior behind these boundaries.