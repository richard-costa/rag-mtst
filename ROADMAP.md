# Roadmap

Future work and open questions for the pre-release, trusted single-tenant backend. Current capabilities: [README](README.md) and [docs](docs/index.md). No committed release dates.

## Next priorities

- Improve first-run reliability and test the local lifecycle across supported
  Linux/macOS/WSL environments and fresh checkouts.
- Make retrieval and answer quality measurable with representative synthetic
  and consented evaluation data; distinguish extraction, retrieval, and
  generation errors.
- Simplify code where demonstrated complexity or duplication obstructs
  maintenance, while retaining worker fencing, atomic reindexing, tenant
  isolation, and citation safeguards.

## Quality and retrieval research

- Benchmark tables, scans, charts, and Office conversion fidelity.
- Measure multilingual relevance, hallucinations, citation support, latency,
  token use, and operating cost.
- Evaluate reranking, MMR, multi-query retrieval, and hybrid window approaches
  **before** introducing new retrieval modes.

## Product and integration gaps

- Define source listing/removal, retention, and versioning semantics.
- Improve follow-up retrieval: history currently influences generation, not
  the query used to retrieve new passages.
- Evaluate URL acquisition and safe source identity.
- Consider streaming and improved conversation lifecycle controls.
- Design per-user authorization and isolation before untrusted multi-user use.

## Operations and model lifecycle

- Add API liveness and readiness endpoints (database reachable, schema
  migrated) and a worker health signal usable by container orchestrators.
- Emit sanitized, structured logs on stdout/stderr for container log
  collection.
- Define graceful SIGTERM shutdown: the API drains in-flight requests; the
  worker stops claiming jobs and finishes or explicitly fails the current job
  within a configurable grace period.
- Document deployment requirements for operators: API and worker share the
  staging path, connection-pooler compatibility (for example PgBouncer modes),
  and database connections held during conversation turns.
- Better sanitized observability and carefully scoped retries.
- Model revision tracking, embedding migration, and hosted token fitting.
- Introduce pooling, batching, or approximate vector indexes only when
  measured workloads justify them.
- Leave deployment networking, hosting, secret distribution, and backup
  architecture to the eventual infrastructure design.

## Open investigations

- Direct provider-managed PDF input versus current application-managed
  extraction and provenance.
- Docling extraction quality versus additional dependency and compute cost.
- In-process local embeddings (sentence-transformers) versus an
  OpenAI-compatible local embedding server (Ollama, llama.cpp, vLLM).

Passing integration tests does not certify factual correctness, citation support,
visual extraction fidelity, or resistance to malicious source content.
