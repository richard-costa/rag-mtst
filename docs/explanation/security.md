# Security and Data Lifecycle

## Trusted Single-Tenant Boundary

The API uses one shared bearer token, with read/write access to one configured
tenant. A tenant ID scopes data; it is not authenticated user identity. There are
no per-user roles, user revocation, caller-selected tenants, or PostgreSQL
row-level security. CLI and Python calls rely on host/database access instead
of the HTTP token.

This is a trusted single-tenant baseline, not an Internet-ready multi-user
authorization system. The operator owns TLS, reverse proxy, network restrictions,
secret distribution/rotation, supervision, backups, retention, and abuse/spending
controls. Compose alone does not supply those policies; its API port is published
beyond loopback. The database credentials in the example stack are development
credentials.

Schema endpoints `/docs`, `/redoc`, and `/openapi.json` are public metadata.
Restrict them at the proxy if the schema must be private. The local demo is a
loopback-only development frontend, not a login system. Its token stays in page
memory and provider credentials remain server-side.

## Provider and Model Trust

Hosted embeddings send document chunks and vector-search queries. Hosted
generation sends questions and selected source context; conversation answers can
also send recent history. Visual extraction sends page images. Obtain permission
and review provider retention before using sensitive material.

Local embeddings plus a separately managed local Ollama can avoid hosted
inference, but downloading weights still uses the network. OpenAI `store=False`
does not promise zero provider retention. Structured schemas constrain output
shape, not truth, safe interpretation, extraction fidelity, or injection immunity.

Treat source text, page images, prior messages, and model answers as untrusted.
Citation validation checks IDs and supplied text, not factual support. Empty
citations can be valid. No systematic general quality or adversarial certification
is implied by passing integration tests.

## Storage and Recovery

Indexed text, source metadata, vectors, job status, conversations, and citation
snapshots live in PostgreSQL. Original input files live temporarily under the
shared staging directory; they are not archived or stored as database blobs.
Source locators are descriptive, not download links.

- Keep your originals separately; terminal job inputs are deleted.
- Back up the database and staging inputs together when pending work must survive.
- Preserve staging paths across API/worker restarts; a durable job alone cannot
  recover a missing file.
- Failed reindexing leaves old searchable chunks intact; successful reindexing
  changes chunk IDs. Historical assistant citations remain saved snapshots.
- There are no public source/conversation deletion endpoints or automatic
  retention policy. Protect persistent data and backups accordingly.
- Cleanup retries terminal inputs, but there is no general orphan-file collector.
  Preserve uncertain submissions until acceptance is understood.

Pre-release schema changes live in the initial migration, not speculative upgrade
chains. An already-initialized database does not replay that revision. Agree an
explicit data-preserving change or deliberate disposable rebuild; never reset an
existing local database implicitly. Destructive downgrades belong only in
disposable tests.

## Failures, Retries, and Costs

Accepted jobs survive client disconnects while database and staged input remain.
The worker fails stale execution instead of automatically replaying paid work.
Generation retries are disabled; explicit reindexing and client retries can
repeat charges. Visual limits bound processing but are not a monetary ceiling.

Successful conversation pairs commit atomically, but a timeout at the client does
not prove server cancellation. Read history before retrying. There are no
idempotency keys, per-user quotas, or rate limiter.

Log job IDs, stages, timings, and safe categories, not payloads, prompts, keys,
credential-bearing URLs, or source images. Protect storage/backups and avoid
global Docker pruning or volume deletion as routine cleanup.