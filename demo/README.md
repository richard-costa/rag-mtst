# Optional visual demo

Learning aid using the real FastAPI backend; no mock pipeline or production frontend. Complete the [CLI quickstart](../docs/tutorials/quickstart.md) first.

## Run

In the repo root, set a private `RAG_API_KEY` in `.env` (the direct CLI
doesn't need this HTTP token). Ensure `uv run rag start` has already succeeded.

In a separate terminal:

```bash
uv run --env-file .env uvicorn demo.server:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/demo/>. Enter the **application API token**, not
your OpenAI/provider key. The token stays in page memory and is sent in the
same-origin bearer header; provider credentials remain server-side. Keep the
demo server on localhost.

The demo supports document upload, extraction mode selection, indexing status,
search, stateless question answering, and citation inspection. Expand
**Retrieval settings** to compare window, cosine, lexical, and hybrid search
or change the result limit and neighboring window size. Unset options use
the backend defaults. Scores are method-specific, not probabilities. The
**Collection** field (default `default`) selects which collection uploads,
searches, and answers use; it matches the CLI's `--collection`.

Hosted calls may incur charges; explicit visual extraction sends page images to the configured provider.

It does not support conversation history, user accounts, document lifecycle
management, or local service startup/shutdown.

Ctrl+C stops only the demo. `uv run rag stop` stops PostgreSQL and worker without deleting indexed data.

## Related documentation

- [What the system does](../docs/explanation/overview.md)
- [Compare retrieval from the CLI](../docs/tutorials/experiments.md)
- [HTTP API reference](../docs/reference/http.md)
- [Security and data lifecycle](../docs/explanation/security.md)

The demo is excluded from the standard backend Python wheel and Docker image.
Do not expose this development interface to untrusted public users.
