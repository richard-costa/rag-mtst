# Use Conversations

Use the authenticated HTTP API to retain successful question/answer pairs.
`/ask` stays stateless; the CLI and demo have no conversation interface.
Configure generation and index relevant material before starting.

## 1. Create a Conversation

```bash
curl --fail-with-body -X POST http://127.0.0.1:8000/conversations \
  -H "Authorization: Bearer $RAG_API_KEY"
```

The 201 response contains an `id`. Use it in place of `CONVERSATION_ID` below.
There is no create-request body, user identity, or client-selected tenant.

## 2. Submit a Question

```bash
curl --fail-with-body http://127.0.0.1:8000/conversations/CONVERSATION_ID/messages \
  -H "Authorization: Bearer $RAG_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"When is the support desk open?","method":"lexical","limit":3}'
```

The response contains `answer`, retrieved `matches`, and `citations`. Submit
another question to the same URL for history-aware generation. Use explicit
questions: retrieval sees only the current query, not a history-rewritten query.
For example, ask "Where is the support desk?", not just "Where is it?".

You may use the same retrieval and provider/model options as `/ask`. Submit only
questions and supported options: client-supplied `role`, assistant messages, and
other extra fields are rejected.

## 3. Read or Page Through History

```bash
curl --fail-with-body 'http://127.0.0.1:8000/conversations/CONVERSATION_ID/messages?limit=50' \
  -H "Authorization: Bearer $RAG_API_KEY"
```

Messages are returned in ascending `sequence` order, newest page first. To fetch
an older page, use `before` equal to the smallest sequence from the previous page;
for example `?limit=50&before=51`. The cursor is exclusive. Allowed limits are
1 through 100; the default is 50. Citation numbers belong to each answer, not
the whole conversation.

## Handle Overlap and Uncertain Outcomes

Only one turn may run per conversation. A concurrent turn returns 409 immediately;
wait for the active turn before submitting another. Other conversations can run
independently. Missing and other-tenant IDs both return 404.

Handled failures and task cancellation leave no partial turn: the user and
assistant messages commit together. A client timeout does not prove cancellation.
Read history before retrying; an already-committed turn can otherwise be duplicated
and billed again. There are no idempotency keys, automatic retries, turn queue,
streaming, conversation listing, or deletion endpoints.

Generation uses at most ten recent complete turns within one third of the prompt
budget. History is context, never citation evidence. Saved assistant citations
retain their exact passage snapshots even after source reindexing.