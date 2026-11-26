# Choose model providers

Choose embedding, generation and visual providers independently. Set private `.env` for the CLI or export before starting the worker; other host processes need explicit environment loading. See [configuration](../reference/configuration.md) for defaults and endpoint precedence.

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

1. Install [Poppler](https://pdf2image.readthedocs.io/en/latest/installation.html#installing-poppler)
   on the host (`poppler-utils` on Debian/Ubuntu). Backend Docker images
   already include it.
2. Set `RAG_VISUAL_PROVIDER` and an explicit vision-capable `RAG_VISUAL_MODEL`;
   optionally set `RAG_VISUAL_BASE_URL`. Supply that provider's credential.
3. `rag start` launches PostgreSQL and the host worker first. For
   image-based extraction of DOCX/PPTX, start the optional converter separately with
   `docker compose -p rag-mtst-local up -d office`. The `-p` value matches
   the local manager's Compose project. For independent deployments, use their
   project name or omit `-p` for the Compose default. Configure host/port if needed.
4. Submit using `--extraction-method visual` or HTTP
   `?extraction_method=visual`. Reindex explicitly when changing an existing profile.

Visual extraction sends page images to the selected model. It has bounded
[processing limits](../reference/limits.md), not a dollar ceiling. Parser remains
the default; there is no automatic OCR or provider fallback.

## Change embedding models safely

After changing embedding space (provider/model/deployment/revision), explicitly [reindex](ingest.md#replace-an-existing-index). Duplicate adds do not rebuild vectors; provider/model tags cannot identify revision or deployment changes.

Hosted providers receive document text, queries, or page images; see
[provider data flow](../explanation/security.md#provider-data-flow) before using
private material.