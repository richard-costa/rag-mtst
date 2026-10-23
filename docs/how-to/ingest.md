# Ingest and Reindex Documents

Start a [configured backend and worker](run.md) first. API, CLI, and worker must
share the database, tenant, and staging path. Keep a separate copy of originals:
the backend removes temporary inputs after completion or failure.

The CLI examples load the private `.env` file from the run guide. If you followed
the disposable tutorial and exported settings instead, omit `--env-file .env`.
Keep `--extra local` on uv commands when using local embeddings. HTTP examples
also need `RAG_API_KEY` set privately in the calling shell; a `.env` file alone
does not export it.

## Submit Through the CLI

```bash
uv run --env-file .env rag add docs/assets/sample.md
```

The command queues a durable job and waits for completion. To return immediately:

```bash
uv run --env-file .env rag add docs/assets/sample.md --no-wait
uv run --env-file .env rag job JOB_ID
```

Replace `JOB_ID` with the returned UUID. Ctrl+C stops waiting, not the queued
job.

## Submit Through HTTP

```bash
curl --fail-with-body http://127.0.0.1:8000/sources/file \
  -H "Authorization: Bearer $RAG_API_KEY" \
  -F 'file=@docs/assets/sample.md'
```

A new or matching active job returns 202 with `job_id` and `status_url`.
Poll that URL with the same bearer token until `completed` or `failed`:

```bash
curl --fail-with-body http://127.0.0.1:8000/jobs/JOB_ID \
  -H "Authorization: Bearer $RAG_API_KEY"
```

An unchanged indexed source returns 200 with null job fields. The same bytes
are reused only when the extraction profile matches; otherwise reindex is required.
Changing a filename does not create a new identity; changing bytes does.

## Replace an Existing Index

```bash
uv run --env-file .env rag add docs/assets/sample.md --reindex
```

Or upload with `?reindex=true`. Reindexing retains the source ID and atomically
replaces its chunks/vectors. It can repeat paid embedding calls. Failure leaves
previous chunks searchable; successful replacement changes chunk IDs.

Reindex after changing extraction profiles, chunking settings, or embedding space.
Existing indexes are never rebuilt automatically. Conflicting active submissions
are rejected rather than running two incompatible jobs for the same source.

## Process Scans or Page Layouts

After [configuring a visual provider](providers.md#enable-visual-extraction):

```bash
uv run --env-file .env rag add document.pdf --extraction-method visual
```

For an already-indexed parser source, add `--reindex`. HTTP uses
`?extraction_method=visual&reindex=true` for deliberate replacement. Visual supports
PDF, DOCX, and PPTX; text/Markdown use the parser. Native parser errors never
trigger automatic visual extraction. See [formats and limits](../reference/limits.md).

## Search and Ask

```bash
uv run --env-file .env rag search "support hours" --method lexical --limit 3
uv run --env-file .env rag search "When can I visit?" --method hybrid --limit 3
uv run --env-file .env rag ask "When is the support desk open?" --method lexical --limit 3
```

Lexical search makes no embedding call. Cosine, window, and hybrid searches use
query embeddings. `ask` requires a configured generation model, even if no sources
match. It returns generated text, not a concatenation of excerpts.

For HTTP, send JSON to `/search` or `/ask`; see the
[request reference](../reference/http.md#search-and-answer-requests).

## Recover Failed or Interrupted Jobs

Inspect `rag job JOB_ID` or authenticated `GET /jobs/JOB_ID` and safe worker logs.
Fix the reported input, configuration, provider, or infrastructure issue, then
submit the original again explicitly. The worker does not automatically replay
interrupted work or retry generation. A stale heartbeat fails on a later worker
poll; with no worker running, pending jobs remain queued.