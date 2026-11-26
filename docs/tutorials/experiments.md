# Experiments: change one thing and observe it

Complete the [quickstart](quickstart.md). Use synthetic files in `docs/assets/experiments/`, keep originals, and expect real provider calls, possible charges and model-dependent results.

## Experiment 1: compare retrieval strategies

**Goal:** distinguish keyword matches, semantic matches, and neighboring
context. Start the local environment if it isn't running:

```bash
uv run rag start
uv run rag add docs/assets/experiments/support-policy.md
uv run rag add docs/assets/experiments/renewals.md
```

Now ask for the same fact four ways:

```bash
uv run rag search "refund eligibility" --method lexical --limit 3
uv run rag search "Can I get my money back?" --method cosine --limit 3
uv run rag search "refund eligibility" --method window --limit 3 --window 1
uv run rag search "refund eligibility" --method hybrid --limit 3
```

**Observe:** compare keyword matches, paraphrases, window neighbors (`context`), and fused ranks. Exact order is not guaranteed.

Try changing **one option at a time**, especially `--window 0` versus
`--window 2`, and compare the printed titles, chunk indices, and passages.

**Read the implementation:** `app/retrieval.py` selects strategies and
`app/storage/documents.py` performs PostgreSQL matching and neighbor reads.
For exact strategy semantics, including how `--limit` counts window seeds, see
[retrieval internals](../explanation/retrieval.md#search-methods).

## Experiment 2: change chunking

**Goal:** see how indexing choices affect the evidence available to retrieval.

1. Open `app/config.py`. The `Settings.chunk_size` default is a **soft
   word target**, currently 180, not a hard token boundary.
2. Open `app/chunking.py` to see heading sections and block packing.
3. Change the default to a smaller value such as `60` *for this experiment*.
4. Restart the host worker so it loads the changed Python code, then reindex:

```bash
uv run rag stop
uv run rag start
uv run rag add docs/assets/experiments/support-policy.md --reindex
uv run rag search "refund eligibility" --method window --limit 3
```

Compare chunk indices and passage boundaries with experiment 1. Structural
blocks (notably tables, code, and list items) can exceed the target. Chunk
boundaries may alter vector representations, result ranking, and context windows.

**Important:** changing code doesn't rewrite existing vectors. Reindex is
deliberate and may trigger more embeddings. Restore the original `chunk_size`,
restart, and **reindex again** when done. Do not invent a `RAG_CHUNK_SIZE`
environment variable; there isn't one.

## Experiment 3: modify the generation instructions

**Goal:** distinguish search behavior from answer behavior.

1. Search first and note the retrieved passages:
   `uv run rag search "refund eligibility" --method lexical`.
2. Open `app/generation.py`. Find the prompt assembly and system instructions.
3. Make a small, reversible wording change, such as asking for a **brief answer**
   while still requiring citation IDs from supplied sources.
4. Compare `rag ask` answers:

```bash
uv run rag ask "Who qualifies for a refund?" --method lexical --limit 3
```

CLI invocations load current host source code; you need not restart PostgreSQL
or the worker for a generation-only CLI edit. The retrieved passages should be
the same when query, strategy, and index are unchanged, though generated wording
can differ.

Do not bypass structured output or citation ID validation. The model returns
typed answer text plus IDs; a validated ID does not guarantee that an answer
is factually supported.

**Read:** `app/generation.py`, then `app/llm.py`.

## Experiment 4: switch model providers

Complete [local embeddings + Ollama setup](../how-to/providers.md#use-local-embeddings-and-ollama-answers), then use the `local` extra for all CLI commands:

```bash
uv run rag stop
uv run --extra local rag start
uv run --extra local rag add docs/assets/sample.md --reindex
uv run --extra local rag ask "When is the support desk open?"
```

New embedding models/spaces require **explicit reindexing**; changing only the
generation model generally does not. Compare the answer and retrieved passages
with your OpenAI results.

**Read:** [configuration](../reference/configuration.md) and the
[provider guide](../how-to/providers.md) for other supported combinations.

## Experiment 5: follow an ingestion job

Submit work without waiting:

```bash
uv run rag add docs/assets/experiments/renewals.md --reindex --no-wait
```

Use the returned UUID:

```bash
uv run rag job JOB_ID
```

You may see `pending`, `running` with extraction/chunking/embedding stages,
or `completed`; small files may finish before your first status poll. The
background worker owns execution, not the command that submitted the file.
`--no-wait` does not cancel the job.

**Read:** `app/ingestion.py`, `app/worker.py`, `app/storage/jobs.py`.
An interrupted worker does not automatically replay potentially paid work.

## Next

Learn [how the components connect](../explanation/overview.md), then follow the
[code map and test guide](../how-to/develop.md). `uv run rag stop` safely shuts down
the local stack without removing indexed data.
