# Choose Model Providers

Embedding, answer generation, and visual extraction are independent choices.
Set exported variables in each process that needs them, or use private Compose
configuration. Exact defaults and endpoint precedence are in the
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

## Use Local Embeddings and Ollama Answers

```bash
uv sync --locked --extra local
export RAG_EMBEDDING_PROVIDER=local
export RAG_GENERATION_PROVIDER=ollama
export RAG_GENERATION_MODEL=qwen2.5:1.5b
export RAG_GENERATION_BASE_URL=http://127.0.0.1:11434/v1
```

Install/start Ollama separately and load a suitable model, for example:

```bash
ollama pull qwen2.5:1.5b
```

Keep `--extra local` on uv sync/run commands. Local embeddings download weights
on first use; Ollama manages its own model downloads and CPU/GPU use. The example
model is not a quality or hardware guarantee. This combination avoids hosted
inference, but initial downloads still use the network.

Ollama must support schema-constrained Chat Completions. Its cloud service does
not provide the structured-output path this application requires. For limited
context windows, configure Ollama's model/server `num_ctx` to accommodate prompt,
output, reasoning, and overhead; the backend does not set it.

## Use DeepSeek or Anthropic Answers

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

## Override One Answer Request

HTTP `/ask` and conversation turns accept `generation_provider` and
`generation_model`. Selecting a provider requires a model. A model-only override
uses the configured provider; switching providers drops the configured answer
endpoint override and uses the new provider's default endpoint.

These overrides do not mutate server settings, change embeddings, or reindex
documents. Credentials must already be available on the backend. The CLI has
no provider/model override flags; configure its environment instead.

## Enable Visual Extraction

1. Install Poppler (`poppler-utils` on Debian/Ubuntu) for host execution. Backend
   Docker images already include it.
2. Set `RAG_VISUAL_PROVIDER` and an explicit vision-capable `RAG_VISUAL_MODEL`;
   optionally set `RAG_VISUAL_BASE_URL`. Supply that provider's credential.
3. For DOCX/PPTX only, start the optional unoserver converter with
   `docker compose up -d office` and configure its host/port if needed.
4. Submit using `--extraction-method visual` or HTTP
   `?extraction_method=visual`. Reindex explicitly when changing an existing profile.

Visual extraction sends page images to the selected model. It has bounded
[processing limits](../reference/limits.md), not a dollar ceiling. Parser remains
the default; there is no automatic OCR or provider fallback.

## Change Embedding Models Safely

After changing the embedding provider, model, or underlying embedding space,
explicitly [reindex relevant sources](ingest.md#replace-an-existing-index).
Vector search filters by provider/model tags, but tags do not identify endpoint
deployment or model revision changes. Ordinary duplicate adds do not rebuild
vectors. Reindex replaces previous vectors; it does not retain multiple versions.

Hosted embeddings send document text and vector-search queries; hosted answers
send questions and selected context. Obtain permission and configure provider-side
retention and spending controls before using private material.