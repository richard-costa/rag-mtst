# Troubleshoot

Start with `uv run rag status` for the local stack, and `uv run rag job JOB_ID`
or `GET /jobs/{job_id}` for ingestion. When reporting an issue, follow the
[safe reporting guidance](../explanation/security.md#reporting-issues).

## Setup and local services

| Symptom | What to do |
| --- | --- |
| `uv` not found | Install uv and reopen your terminal so `PATH` is updated |
| `rag` by itself isn't found | Use `uv run rag`; plain `rag` is available when the project's `.venv` is active or after an optional tool installation |
| Docker unavailable | Start the Docker daemon/Desktop; confirm `docker compose version` works |
| `rag start` creates `.env` or reports missing settings | Expected on first run; fill in `OPENAI_API_KEY` and `RAG_GENERATION_MODEL`, then rerun |
| PostgreSQL won't start or is unhealthy | Check Docker service status and whether local port 5432 is already used; the manager owns the default local database only |
| Worker fails readiness | Run `uv run rag status`, then read `.rag-data/local-runtime/worker.log` |
| Migration did not reapply edits to the initial schema | Already-recorded revisions do not rerun automatically; plan schema changes explicitly |

Do not run `docker compose down --volumes` or global Docker pruning as a
diagnostic step. `rag reset` is for intentionally disposable data; see
[local lifecycle](../reference/cli.md#local-lifecycle).

## Ingestion

| Symptom | What to do |
| --- | --- |
| Job stays pending | Confirm the worker is running and ready, with the same tenant, database, and staging directory as the submitter |
| Job failed | Read the job error, fix the cause, and [resubmit the original](ingest.md#recover-failed-or-interrupted-jobs) |
| Native PDF scan yields no text | Configure [visual extraction](providers.md#enable-visual-extraction) explicitly; there is no OCR fallback |
| Office visual conversion fails | Check the optional converter; native parsing does not require it |
| Source deletion returns 409 | An ingestion job for the source is pending or running; wait for it to finish |

## Search and answers

| Symptom | What to do |
| --- | --- |
| No matching passages | Index a document first; a prior `rag reset` deletes the index |
| Vector results disappear after changing embedding model | [Reindex sources](ingest.md#replace-an-existing-index) into the new embedding space |
| More results than `limit` in window mode | Expected: `limit` counts seeds; see [search methods](../explanation/retrieval.md#search-methods) |
| Answer has no citations | An empty structured citation list is valid but leaves the answer uncited |
| Provider or model error (HTTP 502) | Verify key, model access, endpoint, network, timeouts, and billing configuration |

## HTTP and conversations

| Symptom | What to do |
| --- | --- |
| HTTP 401 | Send `Authorization: Bearer <RAG_API_KEY>`; do not log tokens |
| HTTP 409 on a conversation turn or deletion | One turn is active; wait instead of sending concurrent requests |
| Client times out on a conversation turn | [Read history before retrying](conversations.md#handle-overlap-and-uncertain-outcomes); the server may have committed |
