# Choose model providers

Embedding, answer generation, and visual extraction are independent choices.
For the CLI, set provider values in private `.env` (loaded automatically)
or export them before starting the worker. Other host processes require
explicit environment loading. Exact defaults and endpoint precedence are in the
[configuration reference](../reference/configuration.md).

## Use OpenAI

Privately supply `OPENAI_API_KEY`, then:

```bash
export RAG_EMBEDDING_PROVIDER=openai
export RAG_GENERATION_PROVIDER=openai
export RAG_GENERATION_MODEL=gpt-4o-mini
```

The chat model is an example; use one available to your account. Embeddings
default to `text-embedding-3-small`. Answer generation uses the Responses API
with structured outputs; an endpoint override must support that API.

## Use local embeddings and Ollama answers

```bash
uv sync --extra local
export RAG_EMBEDDING_PROVIDER=local
export RAG_GENERATION_PROVIDER=ollama
export RAG_GENERATION_MODEL=qwen2.5:1.5b
export RAG_GENERATION_BASE_URL=http://127.0.0.1:11434/v1
```

Install/start Ollama separately and load a suitable model, for example:

```bash
ollama pull qwen2.5:1.5b
```

Use `uv run --extra local rag ...` for each CLI command in this configuration
and restart the worker with that extra after changing providers. Local embeddings download weights
on first use; Ollama manages its own model downloads and CPU/GPU use. The example
model is not a quality or hardware guarantee. This combination avoids hosted
inference, but initial downloads still use the network.

Ollama must support schema-constrained Chat Completions. Its cloud service does
not provide the structured-output path this application requires. For limited
context windows, configure Ollama's model/server `num_ctx` to accommodate prompt,
output, reasoning, and overhead; the backend does not set it.

## Use DeepSeek or Anthropic answers

Keep your embedding provider unchanged. Privately supply `DEEPSEEK_API_KEY`:

```bash
export RAG_GENERATION_PROVIDER=deepseek
export RAG_GENERATION_MODEL=deepseek-flash
```

Or privately supply `ANTHROPIC_API_KEY`:

```bash
export RAG_GENERATION_PROVIDER=anthropic
export RAG_GENERATION_MODEL=your-supported-model
```

Replace example model identifiers with models available at the selected endpoint.
DeepSeek uses JSON mode plus local schema validation. Anthropic uses its native
SDK and structured outputs, not its OpenAI compatibility endpoint. No path
silently switches provider or model on failure.

## Override one answer request

HTTP `/ask` and conversation turns accept `generation_provider` and
`generation_model`. Selecting a provider requires a model. A model-only override
uses the configured provider; switching providers drops the configured answer
endpoint override and uses the new provider's default endpoint.

These overrides do not mutate server settings, change embeddings, or reindex
documents. Credentials must already be available on the backend. The CLI has
no provider/model override flags; configure its environment instead.

## Enable visual extraction

1. Install Poppler (`poppler-utils` on Debian/Ubuntu) for host execution. Backend
   Docker images already include it.
2. Set `RAG_VISUAL_PROVIDER` and an explicit vision-capable `RAG_VISUAL_MODEL`;
   optionally set `RAG_VISUAL_BASE_URL`. Supply that provider's credential.
3. For DOCX/PPTX only, start the optional unoserver converter with
   `docker compose -p rag-mtst-local up -d office` when using `rag start`
   (the same Compose project as the local manager). For separate Compose
   deployments, use that deployment's project name. Configure host/port if needed.
4. Submit using `--extraction-method visual` or HTTP
   `?extraction_method=visual`. Reindex explicitly when changing an existing profile.

Visual extraction sends page images to the selected model. It has bounded
[processing limits](../reference/limits.md), not a dollar ceiling. Parser remains
the default; there is no automatic OCR or provider fallback.

## Change embedding models safely

After changing the embedding provider, model, or underlying embedding space,
explicitly [reindex relevant sources](ingest.md#replace-an-existing-index).
Vector search filters by provider/model tags, but tags do not identify endpoint
deployment or model revision changes. Ordinary duplicate adds do not rebuild
vectors. Reindex replaces previous vectors; it does not retain multiple versions.

Hosted providers receive document text, queries, or page images; see
[provider data flow](../explanation/security.md#provider-data-flow) before using
private material.