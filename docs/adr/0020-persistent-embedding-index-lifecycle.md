# ADR 0020: Persistent Embedding Index Lifecycle

Date: 2026-06-04
Status: Accepted
Refines: ADR 0007, ADR 0013

## Context

Memorable's product charter makes retrieval part of the product model, not a later convenience. ADR 0007 requires Hybrid GraphRAG Retrieval: semantic similarity over Embeddings, graph expansion, temporal filtering, and provenance-aware explanation. ADR 0013 made `fastembed` the default local Embedding Provider so semantic search works without a remote service.

The current tracer-bullet retrieval implementation proves the shape but not the operational model. `HybridRetrievalService.search()` rebuilds an in-memory index before every search. Rebuild lists every Entity, Decision, Task, Observation, and Relation in the MemorySpace, regenerates Indexable Text, calls the configured Embedding Provider for each item, and stores each result in a fresh `InMemoryEmbeddingIndex`.

That is correct enough for small tests, but it makes every read do index maintenance work. Search cost scales with MemorySpace size rather than with the query. With a remote Embedding Provider this means one network call per remembered item on every search; even with local `fastembed`, the system repeats CPU work for every query. The personal-space feedback for 0.0.4/0.0.5 surfaced this as the dominant performance problem: ~200 remembered items made searches take minutes with a remote provider and seconds with local `fastembed`.

There is already a Neo4j vector index named `memorable_embeddings_vector`, and `doctor` validates its presence and dimensions. Current search does not populate or query that index. Memorable therefore validates retrieval infrastructure that the live retrieval path ignores.

The forces:

- Search latency must not scale by re-embedding the whole MemorySpace on every read.
- CLI and MCP calls may run in different processes, so process-local caches are not a product-grade retrieval index.
- Embeddings are derived retrieval infrastructure, not canonical memory. They can be regenerated from Indexable Text.
- Semantic similarity finds candidates only. Current Truth and Point-In-Time Truth stay owned by temporal semantics.
- Local-first remains the default, and remote Embedding Providers remain explicit. A remote provider must not be called once per stored item on every query.
- Forget is hard erasure. Derived Embeddings for forgotten memory must not survive the thing they represent.

## Decision

Maintain a persistent Embedding index instead of rebuilding an in-memory index during search.

Production retrieval will store Embeddings in Neo4j and use the existing `memorable_embeddings_vector` vector index for semantic candidate search. The search path embeds the query once, asks the persistent index for candidates, then keeps the existing GraphRAG phases: graph expansion, temporal filtering, ranking, and provenance-aware result building.

Search must not create, refresh, or backfill Embeddings. Search is a read operation over canonical memory plus derived retrieval indexes. If the index is absent or stale, the system must fail loudly or direct the operator to reindex; it must not silently rebuild the whole MemorySpace as part of search.

### Retrieval index boundary

Introduce a retrieval-owned index port rather than scattering Neo4j vector queries through application services. The port should be narrow and testable:

- upsert an Embedding for a source item;
- delete Embeddings for a source item;
- search a MemorySpace by query vector and return semantic candidates with `source_id`, `source_kind`, and score;
- support full rebuild/backfill through a maintenance operation.

The production adapter is Neo4j-backed. Tests may use an in-memory adapter. Neo4j-specific vocabulary and Cypher stay inside the storage adapter; core and agent-facing language stays in terms of Embeddings, Indexable Text, MemorySpace, Entity, Relation, MemoryRecord, and retrieval candidates.

### Indexed content and metadata

The persistent index covers every retrievable item kind currently used by GraphRAG Retrieval:

- Entity;
- Decision;
- Task;
- Observation;
- Relation.

Each stored Embedding must preserve the metadata ADR 0007 requires:

- MemorySpace identity;
- source item id;
- source kind;
- Indexable Text hash or version;
- Embedding Provider;
- Embedding model;
- dimensions;
- creation or update time;
- vector.

Search must only use Embeddings compatible with the active runtime Embedding settings: provider, model, and dimensions. Provider or dimension changes are handled by explicit reindexing, not by mixing incompatible vectors.

The index includes superseded, invalidated, and completed records. They remain useful for Point-In-Time Truth, provenance context, and supersession explanation. Semantic ranking does not decide whether they are current; temporal filtering still includes or excludes them according to the requested mode.

### Index lifecycle

Index maintenance moves to write and maintenance paths:

- remembering an Entity, Decision, Task, Observation, or Relation upserts its Embedding;
- correction upserts the corrected item's Embedding when its Indexable Text changes;
- supersession, invalidation, and task completion upsert affected records whose Indexable Text changes because lifecycle state changed;
- Forget deletes Embeddings for erased items, including Relations erased by an Entity-forget cascade;
- a full reindex/backfill command rebuilds derived Embeddings for a MemorySpace, especially after upgrade, provider/model/dimension changes, or Indexable Text version changes.

Index maintenance is synchronous and fail-loud in V1. Silent stale indexes are worse than a visible operational error. Because Embeddings are derived, the repair path is explicit reindexing.

Schema bootstrap stays create-if-absent; `init` must never drop or recreate the vector index. Provider, model, or dimension drift is repaired only by explicit `reindex`, never by making bootstrap destructive.

## Consequences

Positive:

- Search cost becomes one query Embedding plus vector search, not one Embedding per stored item.
- CLI and MCP search share the same durable retrieval index across processes.
- The existing Neo4j vector index becomes part of the live retrieval path rather than a checked-but-unused artifact.
- The read path becomes simpler: search reads retrieval candidates and applies graph/temporal/provenance logic.
- Embeddings stay derived and regenerable; canonical memory remains Entity, Relation, MemoryRecord, provenance, temporal validity, and lifecycle state.
- Forget's erasure promise is preserved by deleting derived Embeddings for erased memory.

Negative:

- Writes and lifecycle transitions now carry indexing work, so they can be slower or fail for Embedding Provider/index reasons.
- Index staleness becomes an explicit operational concern. The system needs reindex and diagnostics instead of relying on read-time rebuild freshness.
- Existing MemorySpaces need a backfill/reindex step after this change; otherwise search cannot find older memory through the persistent index.
- Provider/model/dimension changes require a deliberate rebuild of derived Embeddings.
- The implementation must keep in-memory tests and Neo4j production behavior aligned behind the new port.

## Alternatives Considered

### Keep read-time in-memory rebuild

This is the current tracer-bullet behavior. It is simple and fresh, but it makes every search do O(MemorySpace size) Embedding work and ignores the persistent vector index. It fails the real personal-space workload and gets worse as memory becomes more useful.

### Incremental in-memory cache

The service could keep `InMemoryEmbeddingIndex`, build it once, and update it on writes. This is a smaller implementation change and works for a long-lived MCP process.

Rejected because it does not work for one-shot CLI commands, does not share state across processes, still leaves the Neo4j vector index unused, and creates cache invalidation failure modes without giving Memorable a durable retrieval index.

### Lazy persisted indexing during search

Search could detect missing or stale Embeddings, build only what is missing, persist them, then query the vector index.

Rejected for V1 because it keeps index maintenance in the read path, makes the first search after a change unpredictably slow, and turns a user-facing read into a storage mutation. It is useful as a migration convenience only if made explicit, not as the core search contract.

### Store vectors directly on canonical memory nodes

Vectors could be stored as properties on Entity/Decision/Task/Observation/Relation nodes instead of separate Embedding records.

Rejected because it mixes derived retrieval data into canonical memory storage, makes multiple provider/model/dimension versions harder to manage, and contradicts the existing `Embedding`-label vector index shape. Separate Embedding records keep the derived-index boundary visible.

### External vector database

A separate vector store could own Embeddings.

Rejected for now. Neo4j is already the local storage runtime, the vector index already exists, and adding another service would violate the current local-first operational simplicity.

## Reconsideration Trigger

Revisit this decision if:

- synchronous write-time indexing makes normal memory writes too slow or unreliable;
- Neo4j vector search cannot meet retrieval quality or latency needs at expected MemorySpace sizes;
- index freshness failures become common despite fail-loud diagnostics and reindexing;
- multiple Embeddings per source item become necessary for chunking or multimodal retrieval;
- an external vector store materially improves retrieval while preserving Memorable's local-first posture and core temporal semantics.
