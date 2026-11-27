# HTTP API

Base URL in local examples: `http://127.0.0.1:8000`. All application operations
require `Authorization: Bearer <RAG_API_KEY>`. There is no streaming response
or per-user identity.

The running application serves exact schemas at `/openapi.json`, Swagger UI at
`/docs`, and ReDoc at `/redoc`. These schema routes are public; restrict them
at the proxy if necessary. See [running the API](../how-to/develop.md#run-the-api-alongside-the-local-manager) and
[configuration](configuration.md) for prerequisites.

OpenAPI schemas define exact types and validation constraints; endpoint docstrings supply descriptions.

## Collections

Every application route is under `/collections/{collection_id}`. A collection is
an opaque, case-sensitive label that partitions sources, chunks, jobs, and
conversations; it is created implicitly on first use. There is no collection
table, listing or management endpoint, or cross-collection search.

The ID must be nonempty, at most 255 characters, printable, without `/`, and
without leading/trailing whitespace; spaces, colons, and Unicode are allowed.
URL-encode the path segment (for example `Team A:1` becomes `Team%20A%3A1`). An
encoded slash (`%2F`) is decoded before routing and is not supported.
Authentication is checked first (401), then an unusable collection ID returns
422. IDs belonging to another collection return 404, like missing IDs.

The shared bearer token grants access to **every** collection. A collection is
not an authorization boundary: a gateway in front of the API must decide which
collection paths each caller may use. See
[trust boundary](../explanation/security.md#trust-boundary).

## Endpoints

| Method | Path | Success response |
| --- | --- | --- |
| POST | `/collections/{collection_id}/sources/file` | 202 `SourceResponse`, or 200 if unchanged |
| GET | `/collections/{collection_id}/sources` | 200 array of `SourceDetailsResponse` |
| GET | `/collections/{collection_id}/sources/{source_id}` | 200 `SourceDetailsResponse` |
| DELETE | `/collections/{collection_id}/sources/{source_id}` | 204, no body |
| GET | `/collections/{collection_id}/jobs/{job_id}` | 200 `JobResponse` |
| POST | `/collections/{collection_id}/search` | 200 array of `SearchMatchResponse` |
| POST | `/collections/{collection_id}/ask` | 200 `AskResponse` |
| POST | `/collections/{collection_id}/conversations` | 201 `ConversationResponse` |
| GET | `/collections/{collection_id}/conversations` | 200 array of `ConversationResponse` |
| GET | `/collections/{collection_id}/conversations/{conversation_id}` | 200 `ConversationResponse` |
| DELETE | `/collections/{collection_id}/conversations/{conversation_id}` | 204, no body |
| GET | `/collections/{collection_id}/conversations/{conversation_id}/messages` | 200 array of `MessageResponse` |
| POST | `/collections/{collection_id}/conversations/{conversation_id}/messages` | 200 `AskResponse` |

List endpoints share the same paging parameters:

| Parameter | Default | Contract |
| --- | --- | --- |
| `limit` | `50` | Integer from 1 through 100 |
| `offset` | `0` | Nonnegative number of items to skip |

## File upload

`POST /collections/{collection_id}/sources/file` accepts `multipart/form-data`
with a required `file` part and a filename. Its query parameters are:

| Parameter | Default | Values |
| --- | --- | --- |
| `reindex` | `false` | Boolean; explicitly replace an existing index |
| `extraction_method` | `parser` | `parser` or `visual` |

Supported extensions are `.txt`, `.md`, `.markdown`, `.pdf`, `.docx`, and `.pptx`.
Visual extraction supports only PDF/DOCX/PPTX. The document must yield searchable
text. There is no automatic visual fallback. See [formats and limits](limits.md).

See [HTTP upload example](../how-to/ingest.md#submit-through-http).

`SourceResponse` fields:

| Field | Meaning |
| --- | --- |
| `id` | Source ID |
| `status` | `pending`, `running`, or `unchanged` |
| `job_id` | Job UUID string, or null for unchanged content |
| `status_url` | Relative polling URL `/collections/{encoded collection}/jobs/{job_id}`, or null for unchanged content |

202 means accepted or a matching active job reused, not completed indexing.
200 means identical bytes in the same collection with a matching extraction profile;
no extraction or embedding call is made. OpenAPI declares the default 202;
the unchanged 200 is an additional runtime response.

Different bytes create another source, even with the same filename. Missing,
different, or mixed stored extraction profiles require explicit reindexing.
Conflicting active jobs return 422. Accepted extraction/provider failures are
reported by the job rather than by the upload response. Existing searchable
chunks survive a failed reindex.

## Source management

`GET /collections/{collection_id}/sources` lists the collection's sources newest
first, using the shared paging parameters.
`GET /collections/{collection_id}/sources/{source_id}` returns one source or 404.
`SourceDetailsResponse` fields:

| Field | Meaning |
| --- | --- |
| `id` | Source UUID |
| `source_type` | `file` or `url` |
| `title` | Display label derived from `reference` |
| `reference` | Descriptive origin metadata; see `source_reference` below |
| `mime_type` | Detected media type, or null |
| `chunk_count` | Currently indexed chunks; zero before the first index completes |
| `created_at`, `updated_at` | Timestamps |

Content hashes and collection IDs are not returned.

`DELETE /collections/{collection_id}/sources/{source_id}` returns 204 after
removing the source, its chunks, and its job history. It returns 404 for missing
or other-collection sources and 409 while a job for the source is pending or
running. Saved conversation citations are snapshots and are not changed.

## Job status

`GET /collections/{collection_id}/jobs/{job_id}` returns the collection's job or
404. IDs must be UUIDs.

`JobResponse` contains `id`, `source_id`, `status`, `stage`, `progress`,
`processed`, `total`, `attempts`, `error`, `created_at`, `started_at`,
`heartbeat_at`, and `finished_at`. Stage, progress/counters, error, and timestamps
other than creation may be null. Status is `pending`, `running`, `completed`, or
`failed`. Errors are sanitized; paths, settings, contents, credentials, and claim
tokens are not returned.

Poll with the same token; only the worker executes jobs. See [recovery](../how-to/ingest.md#recover-failed-or-interrupted-jobs) for terminal-input cleanup and failed jobs.

## Search and answer requests

`POST /collections/{collection_id}/search` accepts `SearchRequest`. `/ask`
accepts `AskRequest`, adding answer provider/model options and caller-supplied
history:

| Field | Default | Validation |
| --- | --- | --- |
| `query` | Required | Nonblank string |
| `limit` | Configured limit | Null or positive integer |
| `method` | Configured method | Null, `cosine`, `window`, `lexical`, or `hybrid` |
| `window` | Configured window | Null or nonnegative integer; used only by `window` |
| `assembly` | `document` | `document` or `score`; changes window ordering only |
| `generation_provider` | Configured provider | Ask/turn only: null, `openai`, `deepseek`, `ollama`, or `anthropic` |
| `generation_model` | Configured model | Ask/turn only: null or nonblank model name |
| `history` | `[]` | Ask only: at most 20 `{role, content}` messages, oldest first, as complete `user`/`assistant` pairs; content nonblank; no other fields |

Selecting a provider requires an explicit model. Override semantics are described
in [override one answer request](../how-to/providers.md#override-one-answer-request).

`history` lets a calling service that keeps its own conversation state supply
recent turns. It is untrusted generation context only: retrieval still uses only
`query`, history is never cited, and nothing is stored. It shares the
[history prompt budget](../explanation/retrieval.md#conversations-share-the-same-budget)
with stored conversations, so older turns may be omitted. A lone question,
wrong order, blank content, unknown roles, or extra fields return 422 before any
provider call.

See [HTTP search/ask example](../how-to/search.md#over-http). Lexical search does not call embeddings; the other methods do. Generation configuration is required even without matches.

## Search and answer responses

Each `SearchMatchResponse` contains:

| Field | Meaning |
| --- | --- |
| `source_id`, `source_title` | Source identity and title |
| `chunk_index` | Zero-based position within the source |
| `content` | Retrieved text |
| `score` | Number, or null for added window neighbors |

In window mode `limit` counts seeds, so more matches than `limit` can be returned.
`assembly: "score"` orders ranked seeds before their deduplicated neighbors;
the default `document` merges windows in document order. This also changes
which sources reach the generation input budget first. Ordering is described in
[search methods](../explanation/retrieval.md#search-methods). Scores from
different methods are not comparable probabilities.

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

`POST /collections/{collection_id}/conversations` takes no body.
`ConversationResponse` contains `id`, `created_at`, and `updated_at`. The
collection in the path owns the conversation; every turn retrieves only from
that collection.

`GET /collections/{collection_id}/conversations` lists the collection's
conversations most recently updated first, using the shared paging parameters.
`GET /collections/{collection_id}/conversations/{conversation_id}` returns one
conversation or 404.
`DELETE /collections/{collection_id}/conversations/{conversation_id}` returns
204 after removing the conversation and all its messages, 404 if missing, or 409
while a turn is running.

`POST /collections/{collection_id}/conversations/{conversation_id}/messages`
accepts `ConversationTurnRequest`: the same options as `/ask` except `history`,
with extra fields forbidden. The server owns turn history: clients cannot submit
`history`, `role`, system messages, or assistant messages. The response is
`AskResponse`.

One turn per conversation; overlap returns 409 even across API processes. Success (including no-sources answers) commits both messages atomically; failure/cancellation leaves history unchanged. Other conversations are independent. See [history semantics](../explanation/retrieval.md#conversations-share-the-same-budget).

`GET /collections/{collection_id}/conversations/{conversation_id}/messages`
parameters:

| Parameter | Default | Contract |
| --- | --- | --- |
| `limit` | `50` | Integer from 1 through 100 |
| `before` | None | Positive exclusive sequence cursor for older messages |

The newest page is returned in ascending sequence order. `MessageResponse`
contains `id`, `sequence`, `role` (`user` or `assistant`), `content`, `citations`,
and `created_at`. User citations are empty; assistant citations are stored
snapshots, unaffected by later reindexing. A new conversation has empty history.
Missing and other-collection conversation IDs both return 404.

There is no streaming, turn queue, or idempotency key.
Read history before retrying an uncertain request: a timeout does not prove that
the turn failed. See the [conversation guide](../how-to/conversations.md).

## Errors

| Status | Contract |
| --- | --- |
| 401 | Missing, malformed, or invalid bearer credentials; `WWW-Authenticate: Bearer` |
| 404 | Source, job, or conversation not found in the requested collection |
| 409 | Source has ingestion work in progress, or a conversation turn is running |
| 422 | Request validation (including an unusable collection ID) or handled input/configuration errors |
| 502 | Handled embedding/generation failures, including invalid generated output |
| 500 | Unhandled failures, including database/infrastructure errors |

Handled application errors use `{"detail":"..."}`; FastAPI validation errors use
an array under `detail`. Environment errors can prevent startup. Provider failures
do not trigger automatic generation retries or silent provider fallback. Client
retries can repeat billable work.