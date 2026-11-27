# Proposal: Collections instead of tenants

**Status:** Implemented.

## Goal

Keep RAG-MTST a small, reusable RAG backend that can be integrated into existing infrastructure through HTTP, CLI or Python. It should organize indexed knowledge without imposing an organization's identity model or requiring a separate deployment for each data scope.

## Design decisions

- Replace `tenant_id` with `collection_id`. A collection is a logical group of indexed sources, not a customer, organization, user or authorization boundary.
- Support multiple collections in one deployment, sharing the API, ingestion worker, PostgreSQL and staging infrastructure.
- Do not introduce users, organizations, memberships, roles or a separate namespace/tenant abstraction. Integrators decide how their own entities map to collections.
- Keep the current shared HTTP bearer token as a temporary service-to-service authentication mechanism. Do not build a user authentication system for this handoff.

## Collection model

For the initial implementation, prefer a single nonempty, opaque text collection identifier per source and per operation. Create collections implicitly on first ingestion; avoid a collections table, administrative CRUD endpoints, many-to-many membership or cross-collection retrieval until a concrete requirement justifies them.

| Entity | Proposed scope |
| --- | --- |
| Source | Belongs to one collection; deduplicate by collection and content hash. |
| Chunk | Inherits the source's collection; retrieval is restricted to that collection. |
| Ingestion job | Inherits the source's collection; workers process jobs from all collections. |
| Conversation | Belongs to one collection; every turn retrieves from that collection. |
| Message and citation snapshot | Inherits conversation scope; preserve existing persistence semantics. |

Binding conversations to a collection is a proposed simplicity trade-off, not a requirement that conversations must always be stored. Keep the existing stateless answer API for integrators who manage their own conversations.

HTTP requests and Python calls should explicitly identify the relevant collection for scoped operations. The CLI can use a `--collection` option with a documented `default` for local convenience. Remove the server-wide `RAG_TENANT_ID` setting; a CLI default must not restrict the API or worker to a single collection. Exact HTTP parameter placement and CLI syntax can be finalized during implementation.

Missing or out-of-scope resource IDs should retain existing not-found behavior. Never silently search every collection.

## Security and integration

A collection is a data-selection mechanism, not proof of permission. With the shared bearer token, every authenticated HTTP caller is trusted to access every collection. The integrating backend or gateway must authenticate end users, authorize collection access, and prevent unauthorized collection selection.

FastAPI supplies authentication primitives and dependency injection, but does not automatically implement identity management, access policies or data isolation. Retain service-level authentication and explicit collection filtering in RAG-MTST. Keep the authentication dependency replaceable so the eventual infrastructure can integrate its preferred credentials and policies.

Do not expose the service directly to untrusted clients under the shared-key model. CLI/Python access relies on trusted host/database access. The infrastructure team owns network access, TLS, credential management, rate limits, monitoring and deployment topology. Independent tenant authorization or database-enforced isolation would require an additional design and is not a guarantee of this proposal.

## Implementation and handoff

1. Replace tenant terminology in configuration, storage records, schema, queries, API/CLI/Python interfaces, demo and documentation. Existing installations are not in use, so backward compatibility for the old identifier is not required. Document a development database reset or explicit migration; never reset data automatically.
2. Make the collection explicit at the operation boundary. Preserve scoped source deduplication, retrieval, conversation transactions and resource lookups. Ensure source/chunk collection consistency in storage; retain useful indexes without redundant abstractions.
3. Remove fixed-tenant worker filtering. Resolve the collection from the claimed job's source, carry that scope through processing and cleanup, and preserve claim fencing, atomic reindexing and temporary-file lifecycle guarantees.
4. Add integration tests with two collections: identical content can be indexed separately; search and answers cannot retrieve the other collection; source/job/conversation access and deletion remain scoped; one worker can process jobs in both collections; authentication still rejects missing/invalid keys.
5. Update the README, configuration, security, architecture, deployment and API/CLI references. Run the existing lint, unit and PostgreSQL integration checks plus a two-collection smoke test.

## Non-goals

No identity provider, user database, organization management, RBAC, collection ACLs, tenant administration, mandatory per-collection deployment or new infrastructure components. Keep the existing RAG pipeline and operational guarantees intact.

## References

- [Current architecture](docs/explanation/architecture.md)
- [Current security model](docs/explanation/security.md)
- [Configuration](docs/reference/configuration.md)
- [HTTP API](docs/reference/http.md)
