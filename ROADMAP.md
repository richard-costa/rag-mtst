# Roadmap

The basic single-tenant RAG workflow is implemented: ingest documents, index,
search, answer with citations, and persist bounded conversations. The next priority
is cognitive simplification, not more features. Later work is grouped by area
rather than assigned release dates.

Completed implementation does not establish representative extraction or answer
accuracy. Shared bearer authentication is not per-user or tenant authorization.
This is a working backend and local demo, not a complete multi-user product:
self-service source/conversation lifecycle controls and quality certification
remain outside the implemented baseline.

## Next: Cognitive Simplification

Make the existing system easier to understand, explain, and change without
weakening its isolation, transaction, citation, or worker-safety guarantees.

- [ ] Identify unnecessary context and repeated lookup in upload/indexing,
  search/answer, and conversation workflows.
- [ ] Simplify demonstrated problems in naming, control flow, decision ownership,
  duplication, or indirection.
- [ ] Assess remaining test overlap while retaining distinct failure coverage;
  measure any claimed runtime improvement.

## Later: Unscheduled

### Extraction and Answer Quality

A small three-document native/visual answer baseline has been compared. It does
not establish representative quality; document-context effects on retrieval and
the broader workloads below remain follow-ups.

- [ ] Evaluate representative charts, tables, scans, and Office layouts against
  their sources; distinguish conversion errors from extraction errors.
- [ ] Measure multilingual retrieval relevance, answer correctness, citation
  support, omissions, hallucinations, latency, usage, and resource footprint.
- [ ] Evaluate MMR, multi-query, reranking, thresholds, and hybrid search with
  neighboring windows against those workloads before expanding retrieval.

### Acquisition, Access, and Conversations

- [ ] Improve retrieval for ambiguous follow-up questions; history currently
  informs generation, while retrieval uses only the latest question.
- [ ] Add URL acquisition with normalized source identity and safe replacement
  and reindexing rules.
- [ ] Add per-user authentication and tenant authorization before untrusted
  multi-user use; consider database row-level security where justified.
- [ ] Assess conversation lifecycle controls and streaming independently of
  persisted ingestion-job progress and the existing nonstreaming turn workflow.
- [ ] Define self-service source listing/removal and retention with deliberate
  data-lifecycle semantics before treating the backend as a complete product.

### Model Lifecycle and Operations

- [ ] Enforce hosted embedding token limits, track model/version profiles, and
  support managed re-embedding and embedding-space migrations.
- [ ] Improve sanitized structured logging and workflow-specific bounded retry
  policies without silently changing current provider behavior.
- [ ] Add pooling, batching, approximate indexes, or partitioning when measured
  latency, throughput, or storage needs justify them.

## Investigations

- **Direct OpenAI PDF inputs:** compare provider-managed processing with
  application-controlled files, messages, and page rendering.
- **Docling:** compare extraction quality against its extra dependencies,
  models, and CPU/RAM footprint before adoption.

## Done

- [x] **Backend foundation:** async PostgreSQL/pgvector storage, migrations,
  tenant-scoped sources/chunks, HTTP API, direct CLI, and Compose deployment.
- [x] **Safe ingestion and chunking:** temporary file inputs, hash deduplication,
  explicit reindexing, atomic replacement, structural Markdown provenance,
  section grouping, and lossless local embedding token fitting.
- [x] **Durable ingestion:** PostgreSQL jobs, shared temporary inputs, supervised
  worker processes, fenced completion, bounded execution, heartbeats, status
  polling, CLI waiting, and terminal input cleanup. No automatic job replay.
- [x] **Embeddings and retrieval:** OpenAI and optional local embeddings;
  lexical, exact cosine, neighboring-window, and RRF hybrid search. Window groups
  preserve document order, merge overlaps, and retain best-hit priority.
- [x] **Answer generation:** bounded source context, cited-source mapping,
  typed responses, explicit OpenAI/DeepSeek/Ollama/Anthropic paths, and OpenAI
  Responses integration. Internal token budgets and authoritative structured
  citations do not require duplicated inline markers.
- [x] **Minimal default setup:** app token, OpenAI key, and explicit answer model;
  optional connection/provider settings, code-owned processing defaults,
  centralized embedding endpoint decisions, and aligned host/Compose guidance.
- [x] **Native extraction:** TXT/Markdown decoding and AnyDoc PDF/DOCX/PPTX
  parsing, with no Office server required for native parsing.
- [x] **Visual extraction:** explicitly selected, bounded page-image processing,
  optional Office rendering, independent model settings, extraction profiles,
  and page/slide provenance. No automatic parser/visual fallback.
- [x] **API protection:** shared bearer authentication and demo secret isolation.
- [x] **Local demo:** real HTML/JavaScript upload, polling, search, and ask;
  request-scoped answer models, without service restarts or data resets.
- [x] **Conversations:** tenant-scoped HTTP creation, ordered history, bounded
  history-aware answers, per-turn citation snapshots, and atomic successful
  question/reply pairs. Concurrent turns are rejected; `/ask` stays stateless.
- [x] **Focused test consolidation:** merged repeated HTTP/CLI ingestion setup,
  grouped integration scenarios by workflow, and separated generation context,
  citations, and visual rendering unit checks. Shared fixtures and explicit stubs
  preserve real-process worker and database-integrity coverage.
- [x] **Ownership boundaries:** separated API wiring/routes/schemas and storage
  connections/records/document/job/conversation SQL. Atomic indexing completion
  and locked conversation turns retain their transaction boundaries.
- [x] **Documentation:** English Markdown organized into Diataxis tutorials,
  how-to guides, reference, and explanation, with Mermaid architecture, job,
  answer-flow, and conversation-transaction diagrams. No diagram export step
  or Node dependencies are required.
- [x] **Documentation and onboarding review:** clearer storage and citation
  wording, consistent environment-loading examples, uv installation instructions,
  and a roadmap with planned work first and completed milestones last.
- [x] **Verification:** focused unit and database integration coverage; strict
  MkDocs builds validate documentation navigation, links, and anchors. Mermaid
  diagrams also have browser rendering and narrow-screen layout checks.