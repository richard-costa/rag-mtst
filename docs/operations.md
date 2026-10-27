# Operations, security, and recovery

RAG-MTST is a **pre-release, trusted single-tenant backend**. The local
`rag start` supervisor is a developer convenience, **not a deployment manager**.
An infrastructure team should determine hosting, network ingress, TLS,
secret management, monitoring, backups, and retention.

## What a deployment needs

| Component | Requirement |
| --- | --- |
| FastAPI service | Python runtime with `app.api.main:app`, HTTP shared-token configuration |
| Ingestion worker | A separate long-running `python -m app.worker` process |
| PostgreSQL | PostgreSQL 17 with pgvector and schema migrations |
| Staged input directory | Shared and accessible at the **same path** by API and worker |
| Configuration | Same database/tenant/staging settings for API and worker; provider credentials where needed |
| Optional converter | unoserver/LibreOffice for explicit visual DOCX/PPTX extraction |
| Optional frontend | The browser demo is development-only and not part of the backend artifact |

Build the **demo-free backend image** from the current multistage Dockerfile:

```bash
docker build --target app -t rag-mtst:backend .
```

The image alone does not run migrations, PostgreSQL, or the ingestion worker.
The included `compose.yaml` is a reference/full-stack Compose setup, **not a
hardened production deployment**. It currently publishes the API port on
`8000:8000` and uses example database credentials. Do not expose it directly
to untrusted networks. The local CLI manager selects just `db` from that
Compose file and uses its own Compose project name.

Within a container the API can listen on `0.0.0.0`; public access, reverse
proxy, HTTPS, and firewall policy are independent deployment decisions. This
repository does not prescribe them.

## Compose services

The reference Compose setup defines five services:

| Service | Role | Lifecycle |
| --- | --- | --- |
| `db` | PostgreSQL + pgvector, including the durable ingestion job queue | Long-running; stores database data in `postgres-data` |
| `migrate` | Runs `alembic upgrade head` | One-shot; waits for a healthy `db`, then exits after applying migrations |
| `app` | FastAPI HTTP API | Long-running; starts after `migrate` completes successfully |
| `worker` | Claims ingestion jobs and supervises per-job subprocesses | Long-running; starts after `migrate` completes successfully, in a separate container from `app` |
| `office` | unoserver/LibreOffice conversion for explicit visual DOCX/PPTX extraction | Optional long-running service; enabled through the `office` profile, not started by default |

Startup order is **healthy database -> successful migrations -> API and worker**.
The API and worker do not wait for each other. They share the application build
configuration and mount the `rag-data` volume at `/app/.rag-data` so both can
access staged inputs at the same path. Database data is stored separately in
`postgres-data`.

This differs from `rag start`, which starts only the Compose `db` service and
runs migrations and the worker on the host. See
[component boundaries](explanation/architecture.md#component-boundaries) for
the worker's process and container boundaries.

## Security boundary

The HTTP API accepts a **single shared bearer token** with access to one
configured tenant. There are no per-user roles, revocation, caller-chosen
tenants, rate limits, or PostgreSQL row-level security. CLI/Python callers rely
on host/database access rather than the HTTP token.

`/docs`, `/redoc`, and `/openapi.json` are public schema metadata endpoints;
protect them at your ingress if needed. Limit network access, apply TLS,
rotate/store keys appropriately, and consider cost/abuse limits before deployment.

Hosted embeddings send document chunks and search queries to the selected
provider. Hosted generation sends selected passages, questions, and optional
recent conversation history. Visual extraction sends page images. Provider
retention and spending policies are external. Treat documents, model output,
and history as untrusted; structured citations validate passage identifiers
but **not** truth or prompt-injection immunity.

## Data lifecycle

- PostgreSQL holds source metadata, extracted chunks, embeddings, job states,
  conversations, and citation snapshots.
- Input files are **temporary staging data**, not an archive. Terminal inputs
  are removed; original files must be stored elsewhere.
- Reindexing is explicit and atomic. Failed replacement keeps earlier chunks.
- Citation snapshots persist independently of later reindexing.
- Worker failure can leave pending jobs or staged files that need inspection.
  There is no general orphan-input sweep or automatic paid-job replay.
- No built-in source/conversation deletion API or automatic retention policy.

For a deployed system, coordinate database and pending staged-input backups;
restoring only the database cannot recover missing staged inputs.

### Local stop versus reset

```bash
uv run rag stop
```

Stops the **locally managed** host worker and PostgreSQL container. Indexed data,
conversations, originals, configuration, and model caches are preserved.

```bash
uv run rag reset
```

Requires typing `RESET`, stops local services and deletes the local Compose
project's database volumes and indexed content. It preserves originals,
`.env`, and model caches. Reset is for **intentionally disposable development
data**, not routine troubleshooting. `--yes` skips confirmation and is
therefore especially dangerous.

The local CLI manager owns the default database at `127.0.0.1:5432`. It is
not suitable for stopping or resetting externally managed services. Do not
run `docker compose down --volumes` or global Docker pruning as a diagnostic step.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `rag start` reports missing settings | Fill in `.env` with an available model and provider credential |
| Docker unavailable | Start Docker/confirm `docker compose version` |
| Database unhealthy | Check Docker service status and whether local port 5432 is already occupied |
| Worker not ready | `uv run rag status`, then `.rag-data/local-runtime/worker.log` |
| Job stays pending | Confirm worker readiness, matching tenant/database, and staged file |
| Job failed | `uv run rag job JOB_ID`; fix cause and explicitly resubmit original |
| HTTP 401 | Supply `Authorization: Bearer <RAG_API_KEY>`; do not log tokens |
| HTTP 409 for conversation | One turn is active; wait and avoid concurrent calls |
| HTTP 502 or model error | Check provider key, model, endpoint, timeouts, and response schema |
| Search empty after reset | Reindex originals: reset deliberately removed the index |
| Changing embedding model hides vector results | Reindex sources into the new embedding space |
| Search limit exceeded in window mode | Limit counts seed chunks; neighbors are additional |
| Missing citations | An empty structured citation list is allowed but leaves the answer uncited |
| Native PDF scan yields no text | Visual extraction must be configured explicitly; there is no OCR fallback |
| Office visual conversion fails | Check optional converter; native parsing does not require it |
| Client times out on conversation turn | Inspect history before retry; server may have committed |
| Migration did not reapply edits to initial schema | Already-recorded revisions do not automatically rerun; plan schema changes explicitly |

Check sanitized IDs, job stages, timings, and safe error categories. Do not
publish document text, prompts, provider payloads, access tokens, or credentials
in issue reports.

## Unimplemented product features

This is not a general-purpose document manager or multi-user chat service.
There is no source acquisition by URL, source deletion/listing API,
fine-grained identity management, automatic history-aware retrieval rewriting,
streaming, or quality guarantee for scans/tables/citations. For formats and
budgets see [limits](reference/limits.md). For interfaces see
[HTTP](reference/http.md) and [configuration](reference/configuration.md).
