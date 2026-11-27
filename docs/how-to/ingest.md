# Ingest and manage sources

Complete the [quickstart](../tutorials/quickstart.md). CLI, API and worker must share database and staging path. Every source belongs to one collection: the CLI uses `--collection NAME` (default `default`) and HTTP uses the `/collections/{collection_id}` path prefix; one worker processes jobs from all collections. Keep originals; terminal inputs are removed. For local embeddings, use `uv run --extra local rag ...` consistently. Export `RAG_API_KEY` for curl; `.env` alone does not export shell variables.

## Submit through the CLI

```bash
uv run rag add docs/assets/sample.md
```

The command queues a durable job and waits for completion. To return immediately:

```bash
uv run rag add docs/assets/sample.md --no-wait
uv run rag job JOB_ID
```

Replace `JOB_ID` with the returned UUID. Ctrl+C stops waiting, not the queued
job.

## Submit through HTTP

```bash
curl --fail-with-body http://127.0.0.1:8000/collections/default/sources/file \
  -H "Authorization: Bearer $RAG_API_KEY" \
  -F 'file=@docs/assets/sample.md'
```

A new or matching active job returns 202 with `job_id` and `status_url`.
Poll that URL with the same bearer token until `completed` or `failed`:

```bash
curl --fail-with-body http://127.0.0.1:8000/collections/default/jobs/JOB_ID \
  -H "Authorization: Bearer $RAG_API_KEY"
```

An unchanged indexed source returns 200 with null job fields. The same bytes
are reused only when the extraction profile matches; otherwise reindex is required.
Changing a filename does not create a new identity; changing bytes does.
Identical bytes in another collection are indexed independently:

```bash
uv run rag add docs/assets/sample.md --collection team-a
```

## Replace an existing index

```bash
uv run rag add docs/assets/sample.md --reindex
```

Or upload with `?reindex=true`. Reindexing retains the source ID and atomically
replaces its chunks/vectors. It can repeat paid embedding calls. Failure leaves
previous chunks searchable; successful replacement changes chunk IDs.

Reindex after changing extraction profiles, chunking settings, or embedding space.
Existing indexes are never rebuilt automatically. Conflicting active submissions
are rejected rather than running two incompatible jobs for the same source.

## Process scans or page layouts

After [configuring a visual provider](providers.md#enable-visual-extraction):

```bash
uv run rag add document.pdf --extraction-method visual
```

For an already-indexed parser source, add `--reindex`. HTTP uses
`?extraction_method=visual&reindex=true` for deliberate replacement. Visual supports
PDF, DOCX, and PPTX; text/Markdown use the parser. Native parser errors never
trigger automatic visual extraction. See [formats and limits](../reference/limits.md).

## List, inspect, and delete sources

Source management is available over HTTP; the CLI has no list or delete command.

```bash
curl --fail-with-body 'http://127.0.0.1:8000/collections/default/sources?limit=20' \
  -H "Authorization: Bearer $RAG_API_KEY"
curl --fail-with-body http://127.0.0.1:8000/collections/default/sources/SOURCE_ID \
  -H "Authorization: Bearer $RAG_API_KEY"
```

Sources are listed newest first; see [fields and paging](../reference/http.md#source-management).

```bash
curl --fail-with-body -X DELETE http://127.0.0.1:8000/collections/default/sources/SOURCE_ID \
  -H "Authorization: Bearer $RAG_API_KEY"
```

204 means source, chunks and job history are deleted. For 409, wait for ingestion to finish. Saved citations remain unchanged. No undo: resubmit the original.

## Recover failed or interrupted jobs

Inspect `rag job JOB_ID` or authenticated `GET /collections/default/jobs/JOB_ID` and safe worker logs.
Fix the reported input, configuration, provider, or infrastructure issue, then
submit the original again explicitly. The worker does not automatically replay
interrupted work or retry generation. A stale heartbeat fails on a later worker
poll; with no worker running, pending jobs remain queued.