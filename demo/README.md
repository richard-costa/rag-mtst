# Optional visual demo

The browser demo is a **learning aid**, not the recommended first-use path
and not a production frontend. It uses the same real FastAPI upload, job,
search, and answer endpoints as other clients. No mocks or second RAG pipeline.

**Start with the [CLI quickstart](../docs/quickstart.md).** Once the database
and host worker are ready, you can use the demo to inspect them visually.

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
the backend defaults. Scores are method-specific, not probabilities.

Hosted model operations are real and may incur charges. Visual extraction
must be configured explicitly and can send page images to a provider.

It does not support conversation history, user accounts, document lifecycle
management, or local service startup/shutdown.

Ctrl+C stops **only the demo server**. To stop PostgreSQL and the host worker,
run `uv run rag stop`. Indexed data persists until an explicit reset.

## Related documentation

- [What the system does](../docs/how-it-works.md)
- [Compare retrieval from the CLI](../docs/experiments.md)
- [HTTP API reference](../docs/reference/http.md)
- [Security and data lifecycle](../docs/operations.md)

The demo is excluded from the standard backend Python wheel and Docker image.
Do not expose this development interface to untrusted public users.
