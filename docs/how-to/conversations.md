# Use conversations

Use the authenticated HTTP API to retain successful question/answer pairs.
`/ask` never stores anything; a service that keeps its own history can
[pass it to `/ask`](#keep-history-in-your-own-service) instead. The CLI and demo
have no conversation interface. Configure generation and index relevant material
before starting.

## 1. Create a conversation

```bash
curl --fail-with-body -X POST http://127.0.0.1:8000/collections/default/conversations \
  -H "Authorization: Bearer $RAG_API_KEY"
```

The 201 response contains an `id`. Use it in place of `CONVERSATION_ID` below.
There is no create-request body or user identity. The conversation belongs to
the collection in the path (`default` here); every turn retrieves only from that
collection, so use the same collection for all its requests. URL-encode other
collection IDs (for example `Team%20A%3A1`).

## 2. Submit a question

```bash
curl --fail-with-body http://127.0.0.1:8000/collections/default/conversations/CONVERSATION_ID/messages \
  -H "Authorization: Bearer $RAG_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"When is the support desk open?","method":"lexical","limit":3}'
```

The response contains `answer`, retrieved `matches`, and `citations`. Submit
another question to the same URL for history-aware generation. Use explicit
questions: retrieval sees only the current query, not a history-rewritten query.
For example, ask "Where is the support desk?", not just "Where is it?".

You may use the same retrieval and provider/model options as `/ask`. Submit only
questions and supported options: client-supplied `history`, `role`, assistant
messages, and other extra fields are rejected.

## 3. Read or page through history

```bash
curl --fail-with-body 'http://127.0.0.1:8000/collections/default/conversations/CONVERSATION_ID/messages?limit=50' \
  -H "Authorization: Bearer $RAG_API_KEY"
```

The newest page arrives in ascending `sequence` order. Use its smallest sequence as the exclusive `before` cursor for older pages (e.g. `?limit=50&before=51`). Citation numbers are per answer. See [paging contract](../reference/http.md#conversations).

## 4. List and delete conversations

```bash
curl --fail-with-body 'http://127.0.0.1:8000/collections/default/conversations?limit=20' \
  -H "Authorization: Bearer $RAG_API_KEY"
curl --fail-with-body -X DELETE http://127.0.0.1:8000/collections/default/conversations/CONVERSATION_ID \
  -H "Authorization: Bearer $RAG_API_KEY"
```

Conversations in the collection are listed most recently updated first; page
with `limit` and `offset`. `GET /collections/default/conversations/CONVERSATION_ID`
returns one conversation's timestamps. Deletion returns 204 and removes all messages; it returns 409 while
a turn is running. There is no undo.

## Handle overlap and uncertain outcomes

Only one turn may run per conversation. A concurrent turn returns 409 immediately;
wait for the active turn before submitting another. Other conversations can run
independently. Missing IDs and IDs from another collection both return 404.

Handled failures and task cancellation leave no partial turn: the user and
assistant messages commit together. A client timeout does not prove cancellation.
Read history before retrying; an already-committed turn can otherwise be duplicated
and billed again. There are no idempotency keys, automatic retries, turn queue,
or streaming.

See [history budget and citation semantics](../explanation/retrieval.md#conversations-share-the-same-budget).

## Keep history in your own service

If the calling service already stores its users' conversations, skip the
conversation endpoints and send recent turns with each `/ask` request:

```bash
curl --fail-with-body http://127.0.0.1:8000/collections/default/ask \
  -H "Authorization: Bearer $RAG_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"Is the support desk open on weekends?",
       "history":[{"role":"user","content":"When is the support desk open?"},
                  {"role":"assistant","content":"Weekdays from 9 to 17."}]}'
```

Send at most 20 messages, oldest first, as complete user/assistant pairs. The
backend does not store the history, lock anything, or keep citations for it;
your service owns ordering, concurrency, and persistence. Retrieval still sees
only `query`, so keep follow-up questions explicit. Field rules are in the
[HTTP reference](../reference/http.md#search-and-answer-requests).