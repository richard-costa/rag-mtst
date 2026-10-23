# Run Tests

From the repository root:

```bash
uv sync --locked
uv run pytest tests/unit -q
```

Unit tests do not start a database. Choose the relevant test file or `-k`
expression during implementation rather than repeatedly running everything.
Generation checks are split between provider/configuration, context-budget, and
citation modules; low-level visual rendering checks are separate from visual
extraction/provider tests. Shared unit fixtures live in `tests/unit/conftest.py`.

## Test Database Workflows

With an accessible Docker daemon:

```bash
uv run pytest tests/integration -q
```

Choose a workflow file for a focused check:

| File under `tests/integration/` | Coverage |
| --- | --- |
| `test_storage.py` | Migrations, records, tenant isolation, job fencing, and transaction contracts |
| `test_ingestion.py` | Staging, submission, duplicate/reindex behavior, and failure preservation |
| `test_worker.py` | Durable inputs, heartbeats, cleanup, failures, and real-process supervision |
| `test_extraction.py` | Parser/Office workflows, explicit extraction profiles, and page provenance |
| `test_retrieval.py` | Lexical, exact cosine, neighboring-window, and hybrid retrieval |
| `test_api.py` | HTTP ingestion, status, retrieval, answers, and errors |
| `test_cli.py` | Submission, waiting, status, retrieval, and answer commands |
| `test_conversations.py` | Persisted history/citations, overlapping turns, failure, and cancellation |
| `test_live_models.py` | Explicit opt-in provider and local-model checks |

Testcontainers creates a disposable `pgvector/pgvector:pg17` database and applies
real migrations. Inputs use temporary directories. Normal tests mock model
boundaries: no paid calls, actual provider keys, Ollama, or model downloads are
required. These checks do not reset the application database.

Database fixtures live in `tests/integration/conftest.py`. Deterministic embeddings,
synthetic generation, and inline worker execution are separate opt-in fixtures;
real-process supervision tests retain the actual worker process boundary. Pytest
uses `--import-mode=importlib` so unit and integration files can share names.

For all code tests:

```bash
uv run pytest tests/unit tests/integration -q
```

For API and local-demo behavior only:

```bash
uv run pytest tests/unit/test_api.py tests/unit/test_demo.py -q
```

## Run Opt-in Model Checks

These are not normal test gates. Run only with explicit authorization for network
use, model downloads, hardware use, and any provider spending. Inspect the selected
test in `tests/integration/test_live_models.py` before running it. Use
`.venv/bin/python` after installing required extras
so a later uv command does not remove them.

| Check | Opt-in variable | Test selector | Requirements |
| --- | --- | --- | --- |
| Local Portuguese retrieval baseline | `RAG_RUN_LOCAL_BASELINE=1` | `portuguese_local_retrieval_baseline` | Docker, `local` extra, cached pinned MiniLM model |
| Local Ollama workflow | `RAG_RUN_OLLAMA_SMOKE=1` | `ollama_local_workflow` | Above, reachable Ollama with the selected model preloaded |
| Hosted generation | `RAG_RUN_HOSTED_GENERATION_SMOKE=1` | `hosted_generation_workflow` | Docker, private OpenAI and DeepSeek keys; two billable calls per provider |

For the cached local baseline:

```bash
uv sync --locked --extra local
env RAG_RUN_LOCAL_BASELINE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python -m pytest tests/integration/test_live_models.py \
  -k portuguese_local_retrieval_baseline -q -s
```

The pinned model revision is
`e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. Cache it deliberately before an offline
run. For Ollama, use `RAG_OLLAMA_SMOKE_BASE_URL` and optionally
`RAG_OLLAMA_SMOKE_MODEL`; the default model is `qwen2.5:1.5b`. Hosted model overrides
are `RAG_OPENAI_SMOKE_MODEL` and `RAG_DEEPSEEK_SMOKE_MODEL`, defaulting to
`gpt-6-luna` and `deepseek-flash`.

Smoke tests establish integration, not general extraction fidelity, answer
accuracy, citation support, or prompt-injection resistance. Keep shared caches
and unrelated Docker resources. Documentation verification is a separate
[MkDocs build](documentation.md).