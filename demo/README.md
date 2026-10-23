# Local RAG Frontend

This HTML, JavaScript, and CSS frontend uses the real FastAPI upload, job-status,
search, and ask endpoints. The optional `demo.server` ASGI wrapper serves both
the static assets and the API on one origin. The production `app.api` entry point,
backend wheel, and VM Docker image do not include the frontend.

It does not implement another ingestion/retrieval pipeline, invent answers, mock
providers, add conversation history, or silently fall back between providers.

## Run

From the repository root with Python 3.14+ and uv installed, complete the
[backend setup](../docs/how-to/run.md), including database migrations and a
separate worker. Export the same database, tenant, staging path, embedding, and
visual settings for the API and worker. Privately configure `RAG_API_KEY` and
provider credentials. These commands read exported settings, not `.env`:

```bash
uv sync --locked
uv run python -m app.worker
```

In another configured shell:

```bash
uv run uvicorn demo.server:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/demo/>. Use a different explicit port if occupied.
Use `.venv/bin/uv` if uv exists only in this environment. Preserve `--extra local`
on installation and run commands when using local embeddings. Ollama and its
models remain separately managed; there are no demo-only model defaults.

Hosted uploads/search/answers use real provider APIs and can incur charges.
Deleting local data cannot reverse provider-side processing or retention.

Enter the configured API token in the password field. It stays in page memory
and is sent in same-origin authorization headers, not URLs or browser storage.
Provider keys are never sent to the browser. Keep the server bound to loopback;
the token is not a user login or multi-user authorization system.

## Actual Behavior

- Document indexing accepts TXT, Markdown, PDF, DOCX, and PPTX. **Fast parser**
  selects native parsing without Office conversion or visual fallback.
- **Visual** explicitly selects the configured visual provider/model for
  PDF/DOCX/PPTX, requires Poppler, and also needs the optional Office converter
  for DOCX/PPTX. Starting Office alone does not enable it. Hosted page images
  leave the machine and may incur charges.
- Uploads automatically poll authoritative pending/running/completed/failed job
  status. Unchanged matching content returns without a new job. Missing or
  conflicting extraction profiles require explicit **Reindex unchanged content**;
  replacement may incur embedding charges again. Failed reindexing preserves
  previously searchable chunks.
- Search and Ask share one query and latest results. Retrieval uses backend
  defaults, including method, limit, and neighboring window.
- Answer provider/model choices affect that request only. Explicit providers
  require an explicit model. Blank choices use server defaults; model-only uses
  the configured provider. Switching providers uses its default endpoint.
  Account/model availability and credentials are backend requirements.
- Operations run sequentially in this page; controls remain disabled while an
  upload is being indexed. There are no tabs, history, restart, reset, pause, or
  cancellation controls.
- Window expansion can exceed the seed limit. Context neighbors retain null
  scores. Scores are not probabilities or comparable across methods.
- Ask is nonstreaming and stateless. It shows generated text, retrieved matches,
  and cited passages. Uncited answers are valid; a citation does not prove
  factual support. See [generation contracts](../docs/reference/http.md#search-and-answer-responses).
- Errors appear inline without automatic retries or provider fallback. Polling
  stops on a transport error; a job may still complete server-side. Retain its
  ID and inspect it with `rag job JOB_ID` or authenticated `GET /jobs/JOB_ID`.

## Ownership and Cleanup

The frontend owns no infrastructure. It uses the operator-configured database,
tenant, and temporary input directory. Indexed documents persist across browser
and API restarts. The worker removes terminal staged inputs; original files are
not permanently archived or stored as database blobs.

Ctrl+C stops only the API wrapper. It does not stop the separately launched
worker, remove containers/volumes, reset the database, or cancel accepted jobs.
Closing a browser tab clears that page's token/results but leaves backend work
and data intact. Stop services deliberately and preserve their data unless you
explicitly intend to delete it. Do not use global Docker pruning for cleanup.

## Tests

```bash
uv run pytest tests/unit/test_api.py tests/unit/test_demo.py -q
```

These checks verify API authentication, request-scoped model choices, allowlisted
local assets, and absence of demo routes in the deployed API. Backend integration
tests cover real queued ingestion and failure-safe replacement with synthetic
model boundaries. No paid calls are part of ordinary checks.