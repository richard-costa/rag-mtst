# CLI

The installed `rag` command and `python -m app.cli` call application functions
directly. They do not use HTTP or require `RAG_API_KEY`. They do require database,
provider, and shared-input access appropriate to the operation.

```text
rag [--data-dir PATH] COMMAND
```

`--data-dir` overrides the staging directory and must precede the subcommand.
It must resolve to the worker's shared input path; it is not an original-file
archive. Run `rag --help` or `rag COMMAND --help` for installed argument help.

## Local lifecycle

Install from a source checkout with `uv tool install --editable .` to make `rag`
available in your shell. The CLI automatically reads the checkout's `.env`,
without overriding variables already exported in the shell. Relative staging
paths are resolved against the checkout, so the local worker and CLI agree.

| Command | Behavior |
| --- | --- |
| `rag start` | Check configuration, start only PostgreSQL in Docker, apply migrations, launch a host worker, and wait for readiness |
| `rag status` | Report local PostgreSQL and background worker readiness |
| `rag stop` | Stop the background worker and local PostgreSQL; keep database contents and model caches |
| `rag reset` | Stop services and delete the local Compose project's database volumes after typing `RESET` |
| `rag reset --yes` | Same destructive reset without prompting; use only deliberately |

Local lifecycle management requires Docker Compose and Linux, macOS, or WSL. It
manages the default database at `127.0.0.1:5432` and uses a dedicated Compose
project name; it does not launch the HTTP API and it does not manage deployed
services. The first `rag start` creates an `.env` template if missing and asks
you to provide credentials/model settings before starting services. Worker logs
are under `.rag-data/local-runtime/worker.log`. A noneditable wheel installation
still supports ordinary CLI commands but cannot manage this checkout's services.

## Commands

| Command | Purpose | Options |
| --- | --- | --- |
| `rag add FILE` | Queue ingestion; wait by default | `--reindex`, `--no-wait`, `--extraction-method parser\|visual` |
| `rag job JOB_ID` | Inspect one tenant-scoped ingestion job | UUID argument |
| `rag search QUERY` | Print retrieved passages | `--limit N`, `--method METHOD`, `--window N` |
| `rag ask QUESTION` | Generate text and print recognized references | Same retrieval options as search |

`METHOD` is `cosine`, `window`, `lexical`, or `hybrid`. Omitted retrieval options
use [configuration defaults](configuration.md#retrieval). Limit must be positive;
window must be nonnegative. Window limit counts seeds, not expanded neighbors.
Quote multiword queries and paths containing spaces.

## Ingestion

`add` stages input and submits a durable job. A separate worker must run even
when the CLI waits. `--no-wait` returns after submission. An indexed matching
source reports already indexed without extraction/embedding. `--reindex`
deliberately replaces chunks and embeddings; failure preserves the old index.
`--extraction-method` defaults to `parser`; `visual` requires configured tools
and a vision model.

`job` prints status/stage and any sanitized error. It returns a failure code
for a failed job, but pending/running/completed jobs return success. Ctrl+C
while adding stops the wait, not the accepted job.

## Search and Answers

Search prints source title, zero-based chunk index, score or `context`, and
content. No matches prints a no-matches message. Ask prints generated text and,
when present, recognized references with source and chunk identity. There is no
CLI conversation command or provider/model override flag; set the environment.

## Exit Codes

| Code | Meaning |
| --- | --- |
| `0` | Success, unchanged input, successful submission, or a nonfailed inspected job |
| `1` | Handled I/O, input/configuration, database, embedding, generation, or job failure |
| `2` | Argument parsing error or missing command |
| `130` | Interrupted while waiting; accepted work remains available to the worker |