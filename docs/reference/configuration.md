# Configuration

`Settings.from_environment()` reads the process environment. The **rag CLI**
automatically loads the checkout's `.env` without overriding exported
variables; other host Python processes (including uvicorn and Alembic) should
load it with `uv run --env-file .env ...`. Compose uses `.env` for
interpolation. Environment parsing errors can prevent startup.

## Starter Values

The default OpenAI workflow needs only the three entries in `.env.example`:

| Variable | Purpose |
| --- | --- |
| `RAG_API_KEY` | App access token, required for HTTP but not direct CLI calls |
| `OPENAI_API_KEY` | OpenAI credential for embeddings and answers |
| `RAG_GENERATION_MODEL` | Explicit answer model; no application default |

The remaining environment settings are optional connection details, data scope,
or model choices. Internal processing limits stay in code. See
[quickstart](../quickstart.md) for startup commands and
[provider setup](../how-to/providers.md) for alternatives to OpenAI.

## Core Settings

| Variable | Default | Contract |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://rag:rag@127.0.0.1:5432/rag` | Development credentials; PostgreSQL with pgvector |
| `RAG_TENANT_ID` | `default` | Server-configured data scope, not caller identity |
| `RAG_DATA_DIR` | `.rag-data` | Shared temporary inputs under `ingestion/`; same path for submitter and worker |
| `RAG_API_KEY` | None | Required at HTTP startup; nonempty ASCII without whitespace |
| `RAG_OFFICE_HOST` | `127.0.0.1` | Optional unoserver converter; not native parsing |
| `RAG_OFFICE_PORT` | `2003` | Positive converter port |

HTTP clients send `Authorization: Bearer <token>`. Swagger's **Authorize** accepts
the token alone. CLI/Python calls do not require the HTTP credential. The key
grants read/write access to the one configured tenant, with no per-user roles.
Rotate by replacing it, restarting the API, and updating all clients; there is no
overlapping-key rotation. See [security](../operations.md#security-boundary).

## Retrieval

These are `Settings` code defaults, not environment variables:

| Field | Default | Contract |
| --- | --- | --- |
| `retrieval_method` | `window` | `cosine`, `window`, `lexical`, or `hybrid` |
| `retrieval_limit` | `10` | Positive; counts seed chunks for window search |
| `retrieval_window` | `2` | Nonnegative; neighbors on each side, only for `window` |

HTTP requests and CLI flags (`--method`, `--limit`, `--window`) can override them
for one operation. Window results may exceed the limit. Tenant scope is never
selected by an HTTP request.

Window search groups each seed with its neighbors in document order. Overlapping
windows from the same source are merged, with each chunk included only once.
Groups are prioritized by their best-ranked seed, rather than putting all seeds
before their neighbors.

## Embeddings

| Variable | Default | Contract |
| --- | --- | --- |
| `RAG_EMBEDDING_PROVIDER` | `openai` | `openai` or `local` |
| `RAG_EMBEDDING_MODEL` | Empty | Empty selects the provider default |
| `OPENAI_API_KEY` | None | Required for OpenAI embeddings or generation |
| `OPENAI_BASE_URL` | Standard OpenAI endpoint | OpenAI-compatible endpoint override |

Default OpenAI embeddings use `text-embedding-3-small` (1536 dimensions). Default
local embeddings use `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
(384 dimensions). Local inference needs the `local` extra; its weights download
on first use. The selected tokenizer determines the input limit (128 for the
tested default-model revision), not a global word count.

Vector retrieval filters provider/model tags. These tags do not distinguish
deployment or revision changes. Reindex deliberately after changing embedding
space. Hosted input-token limits are not enforced locally; local ingestion fits
chunks losslessly and oversized direct queries fail before inference.

## Answer Generation

| Variable | Default | Contract |
| --- | --- | --- |
| `RAG_GENERATION_PROVIDER` | `openai` | `openai`, `deepseek`, `ollama`, or `anthropic` |
| `RAG_GENERATION_MODEL` | None | Explicit chat model required; no application default |
| `RAG_GENERATION_BASE_URL` | Empty | Answer-only endpoint override |
| `DEEPSEEK_API_KEY` | None | Required for DeepSeek |
| `ANTHROPIC_API_KEY` | None | Required for Anthropic |

Generation settings are independent of embeddings. They are required for answers
and conversation turns, including when retrieval finds no matches. HTTP
provider/model overrides affect one request only.

| Provider | Endpoint when no answer override is supplied | Structured-output path |
| --- | --- | --- |
| `openai` | `OPENAI_BASE_URL`, then standard OpenAI | Responses `responses.parse`, `text_format`, `max_output_tokens`, `store=False` |
| `deepseek` | `https://api.deepseek.com` | Chat Completions JSON mode with schema instructions and local validation; `max_tokens` |
| `ollama` | `http://127.0.0.1:11434/v1` | Chat Completions `chat.completions.parse`, `response_format`, `max_tokens`; no real API key |
| `anthropic` | Native Anthropic SDK default | `messages.parse`, `output_format`, `max_tokens` |

All providers validate typed output and reject extra fields. Empty, incomplete,
refused, or invalid output fails; there is no provider fallback. OpenAI endpoint
overrides must support `/v1/responses` and structured outputs. `store=False`
disables stored response state, not all provider retention. Anthropic's OpenAI
compatibility endpoint is not used.

## Visual Extraction

| Variable | Default | Contract |
| --- | --- | --- |
| `RAG_VISUAL_PROVIDER` | `openai` | Same four providers as generation |
| `RAG_VISUAL_MODEL` | None | Explicit vision-capable model required for visual use |
| `RAG_VISUAL_BASE_URL` | Empty | Visual-only override; otherwise provider default, including `OPENAI_BASE_URL` for OpenAI |

Visual extraction reuses the selected provider's credential and structured-output
path, with `{markdown, blank}` page results rather than `{text, citations}`
answers. Model and endpoint image support are prerequisites, not inferred from
their names. Parser-only use needs no visual configuration.

Host visual extraction needs Poppler's `pdfinfo` and `pdftoppm` on `PATH`; backend
images include them. Visual DOCX/PPTX also needs unoserver. Internal bounds are
listed in [formats and limits](limits.md), not configured through extra variables.

## Internal Processing Defaults

These fields live in `app.config.Settings` and are not read from environment
variables. Normal setup does not need to change them; Python callers can pass
explicit settings when needed.

| Field | Default | Meaning |
| --- | --- | --- |
| `chunk_size` | `180` | Soft word budget; local embedding token fitting still applies |
| `chunk_group_adjacent` | `True` | Combine adjacent blocks within the same section when they fit |
| `generation_input_tokens` | `8000` | Estimated input-token budget, including instructions, question, history, evidence, schema, and formatting reserve |
| `generation_max_tokens` | `4000` | Separate output bound, including model reasoning |
| `generation_timeout_seconds` | `180` | Provider timeout; no automatic generation retries |

Input tokens are estimated locally with `tiktoken` and its `cl100k_base` encoding.
The budget reserves 64 tokens for request formatting and counts the response
schema separately unless it is already part of the system instructions. Provider
tokenizers and request formats can differ, so this is not an exact provider-side
token count. Select a model whose context window accommodates both the input and
output allowances; the application does not infer context capacity from its name.

## Container Addresses

| Resource | Host process | Compose application |
| --- | --- | --- |
| PostgreSQL | `127.0.0.1:5432` | `db:5432` |
| Optional Office converter | `127.0.0.1:2003` | `office:2003` |
| Temporary inputs | `.rag-data` by default | `/app/.rag-data` in shared `rag-data` |
| Host Ollama | `http://127.0.0.1:11434/v1` | `http://host.docker.internal:11434/v1`, if reachable |

Container loopback is not the host. Compose supplies a host-gateway mapping;
Ollama must listen on a reachable, appropriately restricted interface. Never
publicly expose an unauthenticated model endpoint.

`RAG_DOCKER_TARGET` is Compose-only: `app` by default, or `app-local` for local
embedding dependencies. Rebuild after changing it. Ollama generation by itself
does not require `app-local`.