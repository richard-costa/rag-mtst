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