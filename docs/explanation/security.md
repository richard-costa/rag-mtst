# Security and data lifecycle

RAG-MTST is a **pre-release, trusted single-tenant backend**. An infrastructure
team should determine hosting, network ingress, TLS, secret management,
monitoring, backups, and retention. See [deploy](../how-to/deploy.md) for the
components a deployment needs.

## Trust boundary

The HTTP API accepts a **single shared bearer token** with read/write access to
one configured tenant. There are no per-user roles, revocation, caller-chosen
tenants, rate limits, or PostgreSQL row-level security. CLI/Python callers rely
on host/database access rather than the HTTP token. Token format and rotation are
described in [configuration](../reference/configuration.md#core-settings).

`/docs`, `/redoc`, and `/openapi.json` are public schema metadata endpoints;
protect them at your ingress if needed. Limit network access, apply TLS,
rotate/store keys appropriately, and consider cost/abuse limits before deployment.
Bind development servers to loopback.

## Provider data flow

Hosted embeddings send document chunks and search queries to the selected
provider. Hosted generation sends selected passages, questions, and optional
recent conversation history. Visual extraction sends page images. Provider
retention and spending policies are external; obtain permission and configure
provider-side controls before using private material.

Treat documents, model output, and history as untrusted. Structured citations
validate passage identifiers but **not** truth or prompt-injection immunity; see
[what citations establish](retrieval.md#what-citations-establish).

## Data lifecycle

- PostgreSQL holds source metadata, extracted chunks, embeddings, job states,
  conversations, and citation snapshots.
- Input files are **temporary staging data**, not an archive. Terminal inputs
  are removed; original files must be stored elsewhere.
- `sources.reference` is descriptive origin metadata (currently a filename),
  not a download link or unique identity.
- Reindexing is explicit and atomic. Failed replacement keeps earlier chunks.
- Citation snapshots persist independently of later reindexing or source deletion.
- Sources and conversations can be deleted through the
  [HTTP API](../reference/http.md#endpoints). Deleting a source removes its
  chunks and job history; it is refused while ingestion work is in progress.
  There is no automatic retention policy.
- Worker failure can leave pending jobs or staged files that need inspection.
  There is no general orphan-input sweep or automatic paid-job replay.

For a deployed system, coordinate database and pending staged-input backups;
restoring only the database cannot recover missing staged inputs. For local
development data, `rag stop` preserves everything and `rag reset` deletes the
local database; see [local lifecycle](../reference/cli.md#local-lifecycle).

## Reporting issues

Share sanitized IDs, job stages, timings, and safe error categories. Do not
publish document text, prompts, provider payloads, access tokens, or credentials
in issue reports.
