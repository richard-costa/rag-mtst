# Search and ask

Index a document first; see [ingest and manage sources](ingest.md). Retrieval
returns stored source text; asking additionally generates an answer from it.
How the methods differ is explained in
[retrieval and answers](../explanation/retrieval.md#search-methods).

## From the CLI

```bash
uv run rag search "support hours" --method lexical --limit 3
uv run rag search "When can I visit?" --method hybrid --limit 3
uv run rag ask "When is the support desk open?" --method lexical --limit 3
```

Omitted options use the [configured defaults](../reference/configuration.md#retrieval).
Lexical search makes no embedding call; cosine, window, and hybrid searches embed
the query. `ask` requires a configured generation model, even if no sources
match. It returns generated text, not a concatenation of excerpts. The CLI has no
provider/model override flags; configure its environment instead.

## Over HTTP

```bash
curl --fail-with-body http://127.0.0.1:8000/search \
  -H "Authorization: Bearer $RAG_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"support hours","method":"lexical","limit":3}'
```

Send the same JSON shape to `/ask` for a generated answer. `/ask` also accepts
`generation_provider` and `generation_model` to
[override the answer model for one request](providers.md#override-one-answer-request).
Field contracts are in the
[HTTP reference](../reference/http.md#search-and-answer-requests).

To keep question/answer history, use [conversations](conversations.md) instead
of `/ask`, or keep it in your own service and
[send it with each `/ask` request](conversations.md#keep-history-in-your-own-service).
