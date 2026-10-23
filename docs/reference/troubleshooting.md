# Troubleshooting

| Symptom | Check or action |
| --- | --- |
| API fails startup with `RAG_API_KEY` error | Supply a private nonempty ASCII token without whitespace; host commands do not load `.env` |
| HTTP 401 | Send `Authorization: Bearer <token>`; update clients after key rotation |
| Database connection refused | Check readiness, `DATABASE_URL`, and host versus container addresses |
| Job remains `pending` | Run a worker with the same database, tenant, staging path, and required credentials |
| Job is `failed` | Inspect `rag job JOB_ID` and safe worker logs; fix the cause and resubmit the original explicitly |
| Duplicate upload requires reindex | The stored extraction profile is absent, different, or mixed; use explicit reindex, not a fallback |
| Missing answer model or HTTP 422 | Configure an explicit generation model; a request selecting a provider must also select a model |
| HTTP 502 | Check provider credentials, model availability, endpoint compatibility, timeouts, and invalid/incomplete typed output |
| Local dependency import fails | Install and keep `--extra local` on uv sync/run commands |
| Vector results disappear after a model change | Use matching provider/model tags and explicitly reindex relevant sources |
| Lexical results are surprising | Terms are OR-combined with PostgreSQL `simple`; no stemming, accent folding, translation, or stopword removal |
| Search returns more than its limit | Window limit counts seeds, not added neighbors |
| No citations in an answer | Empty structured citations are valid but leave the answer uncited; inline references are not parsed or cross-checked |
| Visual PDF tools are missing | Install Poppler on the host; images include it |
| Visual Office conversion fails | Start/configure the optional unoserver service and verify reachability; native parsing does not use it |
| Conversation returns 409 | A turn is running; wait rather than retrying in parallel |
| Job/conversation returns 404 | Verify ID and configured tenant; other-tenant data is deliberately indistinguishable from missing data |
| A conversation request timed out | Read history before retrying; the original may have committed and incurred a provider charge |
| `upgrade head` does not apply a changed initial schema | Pre-release edits to an already-recorded revision are not reapplied; agree an explicit data-preserving plan before changing the database |

## Investigate Without Exposing Data

Use job IDs, stages, elapsed times, sanitized categories, and provider availability
to narrow the failure. Do not publish `.env`, authorization headers, source text,
page images, prompts, or credential-bearing URLs. Avoid `docker compose config`
without `--quiet` when it could print substituted secrets.

There is no general orphan-input collector, automatic ingestion replay, or
generation fallback. Preserve existing data and inputs while determining whether
a submission was accepted. Do not use a database reset, volume deletion, global
Docker pruning, or repeated paid calls as a diagnostic shortcut.