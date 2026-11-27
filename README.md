# rag-mtst

Python RAG backend for indexing documents, retrieving passages and generating source-linked answers via CLI, Python or HTTP API. Uses PostgreSQL/pgvector and a separate durable ingestion worker. Original files are temporary inputs, not an archive.

Supports TXT, Markdown, PDF, DOCX and PPTX; optional visual extraction; OpenAI/local embeddings; lexical, cosine, window and hybrid retrieval; OpenAI, DeepSeek, Ollama and Anthropic generation.

## Quickstart: your first answer

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) outside `.venv` (Arch: `sudo pacman -S uv`), Python 3.14+ (uv manages it), Docker with Compose running, and an OpenAI API key. Linux, macOS and WSL supported; [Docker Buildx](https://docs.docker.com/build/buildx/) recommended.

```bash
git clone https://github.com/richard-costa/rag-mtst.git
cd rag-mtst
uv run rag start
```

On first use, set `OPENAI_API_KEY` and `RAG_GENERATION_MODEL` in the private `.env`, then repeat `rag start`. It starts PostgreSQL, migrations and the host worker, not the HTTP API or office converter.

```bash
uv run rag add docs/assets/sample.md
uv run rag search "support hours"
uv run rag ask "When is the support desk open?"
uv run rag stop
```

Expected answer: Mondays and Wednesdays, 09:00–12:00, with a `sample.md` reference. Hosted calls may incur charges; stopping preserves indexed data.

For scored matches before neighbors, use `--assembly score` with search/ask. See [retrieval ordering](docs/explanation/retrieval.md#search-methods). Alternatively, run `uv sync`, activate `.venv` with `source .venv/bin/activate` (Bash/zsh), then use `rag` directly.

## Visual extraction for DOCX/PPTX

Parser extraction is the default. To use a vision model, install Poppler (Arch: `sudo pacman -S poppler`), set `RAG_VISUAL_MODEL` and provider credentials, and start or restart the worker. Visual DOCX/PPTX additionally requires the office converter; PDFs do not.

```bash
docker compose -p rag-mtst-local up -d office
uv run rag add path/to/complex.docx --extraction-method visual
```

Use the actual Compose project name for independent deployments. Add `--reindex` for existing sources. Conversion may alter layout; page images are sent to the configured provider and may incur costs. See [provider setup](docs/how-to/providers.md#enable-visual-extraction) and [limits](docs/reference/limits.md#visual-extraction-bounds).

## Documentation

- [Quickstart](docs/tutorials/quickstart.md) — setup, expected outputs and local lifecycle.
- [Documentation index](docs/index.md) — tutorials, how-to guides, API/configuration references and architecture.
- [Browser demo](demo/README.md) — optional visual inspection.
- [Roadmap](ROADMAP.md) — future work.

## Project status

Pre-release, trusted backend with collection-scoped data. Each operation names an opaque collection (the CLI uses `--collection`, default `default`); collections partition data but are not an access-control boundary. The HTTP API has one shared bearer token for all collections, not per-user authorization. Do not expose directly to untrusted users; use an authenticating gateway to authorize collection access. Operators own networking, TLS, storage and access controls. Citations identify supplied passages, not correctness; representative extraction and answer quality remain unestablished. See [security and data lifecycle](docs/explanation/security.md).
