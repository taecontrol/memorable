# ADR 0024: SQLite Atomic Record And Embedding Writes

Date: 2026-06-08
Status: Accepted
Refines: ADR 0020, ADR 0022

## Context

ADR 0020 requires persistent Embedding maintenance to be synchronous and
fail-loud. A write that changes Indexable Text must update the derived
Embedding before the write path reports success; silent staleness is repaired by
explicit `reindex`, not hidden read-time rebuilding.

ADR 0022 further requires the SQLite backend's canonical memory and derived
Embedding to live in the same database and the same transaction. That is what
keeps the embedded store honest: an Agent should not observe a canonical record
without its vector, or a vector without its canonical record.

The SQLite backend introduced in #237 self-committed repository writes by using
the Python `sqlite3` connection context manager inside each repository method.
The write-time indexing path then upserted the Embedding after the canonical
write returned. That ordering left two failure modes:

- the canonical record committed, then Embedding upsert failed, leaving search
  stale until `reindex` repaired the derived index;
- a vector could be written in the same operation scope, then a later canonical
  write failed, leaving an orphan vector.

Embeddings remain derived and rebuildable, so a missing Embedding is
recoverable. Atomicity is still required because ADR 0022 promises the SQLite
backend commits the canonical record and its Embedding together.

## Decision

The SQLite adapter owns a unit-of-work seam for write paths that update both
canonical memory and derived Embeddings.

A SQLite write scope is opened by the live write path. SQLite repositories and
the SQLite RetrievalIndex enlist in that scope through the shared SQLite handle.
When enlisted, they execute their writes without self-committing. The scope
commits once after canonical memory and Embedding maintenance both succeed, and
rolls back both when either side fails.

Outside an explicit write scope, repository and RetrievalIndex methods keep
their existing self-contained behavior: one method call writes and commits its
own change. This preserves adapter ergonomics for tests, maintenance commands,
and code paths that do not compose canonical memory with Embedding upsert.

The seam stays inside the SQLite composition. The `RetrievalIndex` port is
unchanged, and callers still ask the normal write path to remember, correct,
invalidate, complete, or otherwise update memory. The SQLite production context
provides the atomic write scope; the in-memory and Neo4j contexts keep the
existing no-op scope, so their transaction models do not change.

## Consequences

Positive:

- On SQLite, a remembered record and its Embedding commit together.
- If canonical memory fails, any enlisted Embedding upsert rolls back with it.
- If Embedding maintenance fails, the canonical record rolls back with it.
- Index maintenance remains synchronous and fail-loud; there is no silent stale
  success and no compensation/cleanup path.
- The repository and RetrievalIndex ports remain unchanged.
- Neo4j keeps its existing driver/session transaction model; no SQLite unit of
  work leaks into the Neo4j adapter.

Negative:

- SQLite repositories no longer own the final commit when called inside the
  write scope, so adapter authors must use the shared handle's write helper for
  future write methods.
- A combined record+Embedding write holds SQLite's single writer for the full
  Embedding maintenance step. WAL still permits concurrent readers, but writes
  remain serialized.
- Fail-loud Embedding Provider or vector-index errors now abort the SQLite
  canonical write rather than leaving a recoverable-but-stale record behind.

## Alternatives Considered

### Reorder Only

Rejected. Writing the Embedding before the canonical record merely swaps the
failure mode from "record missing Embedding" to "orphan Embedding". Writing the
Embedding after the canonical record still leaves the record committed because
repositories self-commit. Ordering cannot provide atomicity without moving the
transaction boundary.

### Post-Hoc Compensation Or Orphan Cleanup

Rejected. Deleting a record after Embedding failure, or scanning for orphan
Embeddings later, is reconciliation rather than atomicity. It adds a new repair
surface and still leaves observable partial states between the failure and the
cleanup.

### Savepoints Per Adapter Method

Considered. Savepoints would let nested repository/index calls roll back their
own work without committing the outer scope. They are useful when independent
sub-operations need partial recovery. This write path needs all-or-nothing
behavior, so a single outer transaction is simpler: inner methods enlist and the
outer scope commits or rolls back once.
