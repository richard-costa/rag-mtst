# Deploy

The local `rag start` supervisor is a developer convenience, **not a deployment
manager**. This page lists what a deployment must provide; the trust boundary
and data responsibilities are in
[security and data lifecycle](../explanation/security.md).

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

The image alone does not run PostgreSQL, migrations or the worker. `compose.yaml` is a reference setup, not hardened: it publishes `8000:8000` with example database credentials. Do not expose directly to untrusted networks. Containers may listen on `0.0.0.0`; operators own ingress, HTTPS and firewall policy.

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

`rag start` uses a dedicated Compose project for `db` and runs migrations/worker on the host. See [component boundaries](../explanation/architecture.md#component-boundaries) and [container addresses](../reference/configuration.md#container-addresses).

## Before exposing the API

Review the [trust boundary](../explanation/security.md#trust-boundary): one shared
bearer token, public schema routes, and no rate limits. Put TLS, network access
control, and cost/abuse limits in front of the service. When something fails,
use [troubleshooting](troubleshoot.md).
