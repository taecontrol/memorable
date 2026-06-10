# ADR 0025: SQLite Embedded Storage Backend, Co-Equal With Neo4j

> Renumbered from a duplicate "ADR 0021" — that number belongs to Record Subtype As Optional On-Record Label.

Date: 2026-06-07
Status: Accepted
Refines: ADR 0001, ADR 0005

## Context

ADR 0001 builds Memorable's temporal core directly on Neo4j behind a storage adapter boundary. ADR 0005 makes a local Neo4j runtime the default and explicitly defers embedded/file-based storage, because the goal then was to prove the temporal-graph and GraphRAG shape, not to minimize setup.

That shape is now proven. The storage adapter boundary holds: nine domain-language repository ports plus a `RetrievalIndex` port, with a working in-memory adapter used in tests. The ports speak Entity, Relation, About, MemoryRecord, Provenance, Current Truth, and Point-In-Time Truth — no storage vocabulary leaks. Graph traversal in the live retrieval path is shallow: 1-hop Relation lookups, About key-lookups, and supersession chains walked in application code, not deep Cypher.

The operational cost of Neo4j has become the dominant adoption friction. Neo4j requires a running server or container. `pip install memorable-kg` does not yield a working system; the user must provision and run a database daemon first. This contradicts the local-first, low-friction posture Memorable wants for project-scoped agent memory, and it is precisely the property ADR 0005's "Embedded Or File-Based Storage First" alternative set aside for later.

The forces:

- The product wants `pip install` / `uvx` to yield a working memory system with no separate server or daemon.
- The temporal-graph and GraphRAG shape is already validated against Neo4j and must be preserved unchanged.
- The storage ports are backend-neutral; a second backend is one adapter package, not a core rewrite. An in-memory adapter already proves the ports are not Neo4j-shaped.
- Existing Neo4j users and the remote / shared-memory path must not be abandoned.
- An embedded backend must satisfy every capability the Neo4j backend satisfies: MemorySpace isolation, About many-to-many, Point-In-Time Truth including open-ended (`invalidation_time IS NULL`) ranges, atomic Forget cascade, provenance, append-first history, and DB-side ordered/paginated Memory Review.
- The realistic per-MemorySpace ceiling is on the order of 10k retrievable items, so a heavyweight engine is not required for scale.

Embedded-store research (graph-native engines, vector stores, and SQLite) settled on SQLite as the most durable embedded option whose relational core covers the whole model; the rejected alternatives are recorded below.

## Decision

Add a SQLite storage backend as a co-equal implementation of the storage ports, and make it the default storage runtime. Neo4j remains a fully supported, selectable backend.

SQLite is an embedded, in-process, single-file database. The SQLite backend stores the whole MemorySpace — Entities, Decisions, Observations, Tasks, Relations, About links, provenance, and derived Embeddings — in one `.memorable/memory.db` file, with no server or daemon.

Mapping to the existing model:

- typed records (Entity / Decision / Observation / Task) → typed rows carrying every temporal field verbatim (`id`, `validity_time`, `invalidation_time`, `lifecycle_state`, `supersedes`, `superseded_by`);
- Relation, per ADR 0012, → a row with foreign-key columns referencing source and target Entity (ADR 0012 explicitly anticipated this SQLite mapping);
- About (record↔Entity many-to-many) → a junction table supporting `records_for_entity` and `entities_for_record`;
- Current Truth and Point-In-Time Truth → SQL predicates over the temporal fields, including open-ended ranges via `invalidation_time IS NULL`;
- Forget cascade (ADR 0019) → foreign keys with `ON DELETE CASCADE`, executed in one transaction;
- Memory Review → DB-side `ORDER BY` + `LIMIT` / `OFFSET`.

Storage vocabulary (SQL, tables, PRAGMA) stays inside the SQLite adapter. Core and agent-facing language stays in domain terms.

### Backend selection and default

Backend choice is a runtime-configuration concern (ADR 0010 layering), not a MemoryProfile concern, and defaults to SQLite. `runtime.local.yaml` selects the backend and, for SQLite, the database file path; selecting Neo4j requires explicit configuration. Default configuration must never select a remote or server backend implicitly.

### Connection invariants

SQLite enforces foreign keys only when `PRAGMA foreign_keys = ON` is set per connection. The adapter must set it on every connection; without it the Forget cascade silently fails to behave like the Neo4j backend. The adapter uses WAL mode and a busy timeout so that one-shot CLI processes and a long-lived MCP process can share the same `.db` file (single writer, concurrent readers), consistent with ADR 0020's note that CLI and MCP may run in different processes.

### Shared port-conformance suite

Because Neo4j and SQLite are co-equal, the behavioral contract of the ports is written once as a shared conformance suite and run against every adapter — in-memory, Neo4j, and SQLite — in CI. The suite asserts the invariants temporal semantics and migration depend on, in particular:

- `save` round-trips a record in any lifecycle state, preserving identity and every temporal field verbatim (no id regeneration, no lifecycle reset);
- `list_by_space` returns records in all lifecycle states (not just Current Truth);
- Forget erases atomically and cascades to referencing Relations and About edges;
- About is symmetric across `records_for_entity` / `entities_for_record`;
- Point-In-Time ranges include open-ended validity (`invalidation_time IS NULL`).

This turns "the ports are backend-neutral" from an assertion into a tested invariant.

### Cross-backend migration

Provide a cross-backend copy operation implemented generically over the storage ports rather than as backend-specific code. The migrator accepts source and target port sets, so tests and adapter conformance checks can exercise any source/target pair directly, including in-memory contexts.

Expose that operation through the user-facing command `memorable migrate --from <backend> --to <backend>` for persistent runtime backends only: `sqlite` and `neo4j`. The CLI resolves each selected backend through runtime configuration and does not expose the in-memory test adapter as a selectable backend.

Migration:

- reads every record in every lifecycle state via `list_by_space` and writes via `save`, preserving identity and temporal fields;
- copies About links and provenance;
- copies derived Embeddings verbatim (no re-embedding) so migration carries no Embedding-Provider dependency;
- replays Task completion via `complete()` after `save`, because completion is an append-first event, not a stored field mutation;
- writes in referential order (spaces → entities → records → relations → About → embeddings).

Migration is never forced: existing Neo4j users keep selecting Neo4j. The command exists for users who choose to move data between persistent runtime backends, and its fidelity rests on the round-trip contract the conformance suite guards.

## Consequences

Positive:

- `pip install` / `uvx memorable-kg` yields a working memory system with no server or daemon; the default is embedded SQLite.
- The temporal-graph / GraphRAG model is unchanged; only a new adapter is added behind existing ports.
- Neo4j stays first-class for users who want it and for the remote / shared-memory path.
- The shared conformance suite protects both backends and migration fidelity with one set of behavioral tests.
- A single portable file makes project memory easy to inspect, back up, move, and delete.

Negative:

- Two co-equal backends carry ongoing maintenance and CI cost: a Neo4j container plus the SQLite backend, both run against the full conformance suite on every change.
- SQLite's single-writer model requires WAL + busy-timeout discipline for concurrent CLI/MCP access; write concurrency is weaker than a server.
- The Forget cascade depends on a per-connection PRAGMA that is off by default — a footgun the adapter must handle and the conformance suite must guard.
- The migration command adds scope and its own test surface, and its fidelity depends on the round-trip contract holding for every adapter.

## Alternatives Considered

### Keep local Neo4j as the only runtime (status quo, ADR 0005)

Rejected: it leaves the server/daemon requirement that is now the dominant adoption friction, and the temporal-graph shape it was protecting is already proven.

### Replace Neo4j entirely with SQLite

Rejected: it discards working, tested code and the remote / shared-memory escape hatch for no benefit, and weakens the proof that the ports are backend-neutral. Co-equal backends keep the abstraction honest.

### A graph-native embedded engine (KùzuDB, LadybugDB, DuckDB, CozoDB, …)

Rejected after research. KùzuDB is archived; CozoDB is effectively unmaintained; LadybugDB is a six-month-old single-maintainer Kùzu fork that reintroduces the exact abandonment risk this migration exists to escape; DuckDB is an OLAP column-store doing OLTP single-row mutations, with an experimental vector half and no cascade delete. SQLite's relational/temporal core is the most durable embedded database available, and Memorable's live traversal is shallow enough that a graph engine is not required — cheap foreign-key lookups suffice.

### A separate embedded vector store as the canonical backend (e.g. Chroma)

Rejected: a vector store is not a graph/relational store. As a canonical backend it forces dummy-vector junction rows for About, sentinel epochs because it cannot query NULL (breaking Point-In-Time Truth), a non-atomic Forget cascade, and application-side ordering for Memory Review — and its one strength is moot because Memorable owns Embedding generation (ADR 0013). The vector-index decision is made separately in ADR 0026.

## Reconsideration Trigger

Revisit if:

- maintaining two co-equal backends in CI costs more than the embedded default is worth, suggesting demotion of one;
- SQLite's write-concurrency model proves inadequate for real CLI / MCP usage;
- per-MemorySpace size grows far beyond the ~10k ceiling and relational scans dominate latency;
- a durable, well-maintained embedded graph engine appears that satisfies the temporal, provenance, Forget, and retrieval contracts with less total cost than SQLite plus its application-side traversal.
