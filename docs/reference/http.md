# HTTP API

Base URL in local examples: `http://127.0.0.1:8000`. All application operations
require `Authorization: Bearer <RAG_API_KEY>`. There is no tenant header,
streaming response, or per-user identity.

The running application serves exact schemas at `/openapi.json`, Swagger UI at
`/docs`, and ReDoc at `/redoc`. These schema routes are public; restrict them
at the proxy if necessary. See [running the API](../development.md#run-the-api-alongside-the-local-manager) and
[configuration](configuration.md) for prerequisites.

Operations are grouped by feature and have concise summaries with Markdown
descriptions of inputs, responses, and workflow guarantees. These descriptions
come from endpoint docstrings; schema fields remain the source for exact types
and validation constraints.

## Endpoints

| Method | Path | Success response |
| --- | --- | --- |
| POST | `/sources/file` | 202 `SourceResponse`, or 200 if unchanged |
| GET | `/jobs/{job_id}` | 200 `JobResponse` |
| POST | `/search` | 200 array of `SearchMatchResponse` |
| POST | `/ask` | 200 `AskResponse` |
| POST | `/conversations` | 201 `ConversationResponse` |
| GET | `/conversations/{conversation_id}/messages` | 200 array of `MessageResponse` |
| POST | `/conversations/{conversation_id}/messages` | 200 `AskResponse` |

## File Upload

`POST /sources/file` accepts `multipart/form-data` with a required `file` part
and a filename. Its query parameters are:

| Parameter | Default | Values |
| --- | --- | --- |
| `reindex` | `false` | Boolean; explicitly replace an existing index |
| `extraction_method` | `parser` | `parser` or `visual` |

Supported extensions are `.txt`, `.md`, `.markdown`, `.pdf`, `.docx`, and `.pptx`.
Visual extraction supports only PDF/DOCX/PPTX. The document must yield searchable
text. There is no automatic visual fallback. See [formats and limits](limits.md).

```bash
curl --fail-with-body http://127.0.0.1:8000/sources/file \
  -H "Authorization: Bearer $RAG_API_KEY" \
  -F 'file=@docs/assets/sample.md'
```

`SourceResponse` fields:

| Field | Meaning |
| --- | --- |
| `id` | Source ID |
| `status` | `pending`, `running`, or `unchanged` |
| `job_id` | Job UUID string, or null for unchanged content |
| `status_url` | Relative polling URL, or null for unchanged content |

202 means accepted or a matching active job reused, not completed indexing.
200 means identical tenant-scoped bytes with a matching extraction profile;
no extraction or embedding call is made. OpenAPI declares the default 202;
the unchanged 200 is an additional runtime response.

Different bytes create another source, even with the same filename. Missing,
different, or mixed stored extraction profiles require explicit reindexing.
Conflicting active jobs return 422. Accepted extraction/provider failures are
reported by the job rather than by the upload response. Existing searchable
chunks survive a failed reindex.

## Job Status

`GET /jobs/{job_id}` returns the tenant-scoped job or 404. IDs must be UUIDs.

`JobResponse` contains `id`, `source_id`, `status`, `stage`, `progress`,
`processed`, `total`, `attempts`, `error`, `created_at`, `started_at`,
`heartbeat_at`, and `finished_at`. Stage, progress/counters, error, and timestamps
other than creation may be null. Status is `pending`, `running`, `completed`, or
`failed`. Errors are sanitized; paths, settings, contents, credentials, and claim
tokens are not returned.

Poll the supplied URL with the same bearer token. A separate worker executes
jobs; polling does not execute them. Terminal input files are removed and failed
jobs are not automatically retried. See [recovery](../how-to/ingest.md#recover-failed-or-interrupted-jobs).

## Search and Answer Requests

`POST /search` accepts `SearchRequest`. `/ask` accepts `AskRequest`, adding
answer provider/model options:

| Field | Default | Validation |
| --- | --- | --- |
| `query` | Required | Nonblank string |
| `limit` | Configured limit | Null or positive integer |
| `method` | Configured method | Null, `cosine`, `window`, `lexical`, or `hybrid` |
| `window` | Configured window | Null or nonnegative integer; used only by `window` |
| `generation_provider` | Configured provider | Ask/turn only: null, `openai`, `deepseek`, `ollama`, or `anthropic` |
| `generation_model` | Configured model | Ask/turn only: null or nonblank model name |

Selecting a provider requires an explicit model. A model-only override keeps the
configured provider. Switching providers uses the new provider's default endpoint,
not the configured answer endpoint override. Overrides do not change server
settings, retrieval, stored embeddings, or server-side credentials.

```bash
curl --fail-with-body http://127.0.0.1:8000/search \
  -H "Authorization: Bearer $RAG_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"support hours","method":"lexical","limit":3}'
```

Use `/ask` with the same JSON shape to request a generated answer. Lexical search
does not call embeddings; the other methods do. Answer generation needs valid
provider/model configuration even when there are no matches.

## Search and Answer Responses

Each `SearchMatchResponse` contains:

| Field | Meaning |
| --- | --- |
| `source_id`, `source_title` | Source identity and title |
| `chunk_index` | Zero-based position within the source |
| `content` | Retrieved text |
| `score` | Number, or null for added window neighbors |

Window `limit` counts seeds; with window two, up to `5 * limit` matches can be
returned before overlap. Results group each seed with its neighbors in document
order, merge overlapping same-source windows, and prioritize groups by their
best-ranked seed. Scores from different methods are not comparable probabilities.

`AskResponse` contains `answer` (text), `matches` (all original retrieval results),
and `citations` (recognized references to passages actually supplied to the model).
Each `CitationResponse` contains `id`, `source_id`, `source_title`,
`source_reference`, `chunk_index`, `content`, and `truncated`.

`source_reference` is descriptive origin metadata, such as a filename, URL, or
external record identifier. It is not necessarily unique or accessible, and the
backend does not use it to fetch the source. Current file ingestion supplies the
filename. `source_title` is a computed display label: file references use their
basename, while non-file references are preserved in full. This metadata contract
does not imply URL or other connector ingestion is implemented.

Citation IDs must refer to supplied passages. Unknown IDs or empty answer text
cause 502. The structured citation list is authoritative; inline references are
optional and are not parsed or cross-checked. Empty citations are valid, leaving
the answer uncited. A citation does not verify factual support.

`matches` can exceed the bounded model context. Citation `content` is the exact
supplied passage; the final passage can be shortened and marked `truncated`.
With no matches, the answer is a fixed English no-sources message and empty
arrays, without a generation call, after generation configuration is validated.

## Conversations

`POST /conversations` takes no body. `ConversationResponse` contains `id`,
`created_at`, and `updated_at`. The configured tenant owns the conversation.

`POST /conversations/{conversation_id}/messages` accepts
`ConversationTurnRequest`: the same options as `/ask`, but with extra fields
forbidden. Clients cannot submit `role`, system messages, or assistant history.
The response is `AskResponse`.

One turn runs per conversation; overlap returns 409 immediately, including across
API processes. The successful user/assistant pair commits atomically. Handled
failures and cancellation leave history unchanged. A successful no-sources
response is saved. Other conversations can run independently.

Generation considers at most ten complete recent turns within one third of the
existing prompt budget. History is untrusted context, not source evidence.
Retrieval uses only the current query. There is no history rewriting or summary.

`GET /conversations/{conversation_id}/messages` parameters:

| Parameter | Default | Contract |
| --- | --- | --- |
| `limit` | `50` | Integer from 1 through 100 |
| `before` | None | Positive exclusive sequence cursor for older messages |

The newest page is returned in ascending sequence order. `MessageResponse`
contains `id`, `sequence`, `role` (`user` or `assistant`), `content`, `citations`,
and `created_at`. User citations are empty; assistant citations are stored
snapshots, unaffected by later reindexing. A new conversation has empty history.
Missing and other-tenant conversation IDs both return 404.

There is no listing/deletion endpoint, streaming, turn queue, or idempotency key.
Read history before retrying an uncertain request: a timeout does not prove that
the turn failed. See the [conversation guide](../how-to/conversations.md).

## Errors

| Status | Contract |
| --- | --- |
| 401 | Missing, malformed, or invalid bearer credentials; `WWW-Authenticate: Bearer` |
| 404 | Job or conversation not found in the configured tenant |
| 409 | A turn is already running for the conversation |
| 422 | Request validation or handled input/configuration errors |
| 502 | Handled embedding/generation failures, including invalid generated output |
| 500 | Unhandled failures, including database/infrastructure errors |

Handled application errors use `{"detail":"..."}`; FastAPI validation errors use
an array under `detail`. Environment errors can prevent startup. Provider failures
do not trigger automatic generation retries or silent provider fallback. Client
retries can repeat billable work.