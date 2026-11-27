# Decisions

## Collection identifiers are caller-chosen text

Every data operation is scoped by a `collection_id` that the caller chooses
(for example `/collections/team-a/ask` or `rag search --collection team-a`).
It is text rather than a UUID or integer because there is no `collections`
table: the server never creates a collection, so it cannot hand out a generated
ID. A collection exists once data uses its key.

This behaves like a name, or more precisely a caller-chosen key. The pattern is
common for data partitions: Pinecone namespaces, Qdrant and Chroma collection
names, S3 bucket names and Kubernetes namespaces. Text keeps it flexible, since
a caller can pass its own team UUID (`/collections/3f2a…`) or a readable name
(`/collections/team-a`).

### Trade-offs

- **No setup:** no create step; the caller just uses a key.
- **Typos aren't caught:** a misspelled key silently becomes a new, empty
  collection.
- **No renaming:** the key is stored on every row, so renaming means rewriting
  all of them.
- **No listing or metadata:** there is nothing to list and nowhere to keep a
  display name or owner.

### Alternative: a `collections` table

- `id uuid` is the primary key, plus a unique `name` and maybe an owner.
- A create endpoint (`POST /collections`) returns the UUID.
- Data rows reference it with a foreign key.
- Unknown IDs return 404, so typos are caught.
- Renaming only changes the `name` column.

That costs a table, create, list and delete endpoints, and a decision about
what deleting a non-empty collection should do. It was out of scope for the
first version.

### Guidance

If the gateway in front of this service already has its own team or project
IDs, keep the text key; consider renaming it `collection_key` or `collection`
so it doesn't read as a database ID. If this service should own collections,
the UUID table is the cleaner model.
