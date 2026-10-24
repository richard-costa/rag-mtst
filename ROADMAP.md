# Roadmap

RAG-MTST is a **pre-release, trusted single-tenant RAG backend**. It already
supports durable file ingestion, structured chunking, hosted/local embeddings,
four retrieval strategies, source-linked generation, an HTTP API, a CLI, and
bounded persisted conversations. These capabilities are described in the
[README](README.md) and [documentation](docs/index.md), not repeated here.

This roadmap tracks **future work and open questions** rather than historical
completed-task checklists. No release dates are committed.

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

Passing integration tests does not certify factual correctness, citation support,
visual extraction fidelity, or resistance to malicious source content.
