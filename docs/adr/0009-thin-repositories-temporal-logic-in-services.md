# ADR 0009: Thin Repositories With Temporal Logic In Domain Services

Date: 2026-05-25
Status: Accepted

## Context

ADR 0001 decided to build Memorable's temporal core directly on Neo4j behind a storage adapter boundary. The first implementation used in-memory repositories that contain temporal logic: supersession chain-walking, point-in-time projection, and history reconstruction.

The Neo4j prototype proved that the temporal model works end-to-end against real storage. However, it revealed a strategic problem: the temporal logic is duplicated across repository implementations. The in-memory repository walks supersession chains in Python. The Neo4j repository does the same thing, reading from Neo4j instead of a dict. If these implementations ever diverge in behavior, unit tests pass (they exercise in-memory) while production breaks (it runs Neo4j).

This matters because:

- Temporal semantics are Memorable's core differentiator. Correctness must be proven by tests that run on every commit, not just integration tests that require a running database.
- Adding a future backend (SQLite, another graph store) would mean reimplementing temporal logic again, with the same divergence risk.
- The repository ports define seven methods for DecisionRepository, three of which contain temporal logic. The more logic in the adapter, the harder it is to trust any single adapter implementation.

## Decision

Repositories are thin persistence adapters. They implement only CRUD operations: save, get, list, and update properties. They do not contain temporal logic.

Temporal logic lives in domain services. Services such as CurrentTruthService and PointInTimeTruthService own chain-walking, point-in-time projection, lifecycle transitions, and history reconstruction. They compose thin repository calls to implement these operations.

The repository port protocols are simplified to:

- save: persist a record with provenance
- get: retrieve by space and id
- get_provenance: retrieve provenance for a record
- list_by_space: return all records in a space
- mark_superseded: update supersession and invalidation properties on a stored record

Temporal query methods (get_current, get_at, get_history) move out of the repository port and into domain services.

## Consequences

Positive:

- Temporal logic has one implementation, tested without a running database.
- In-memory tests prove the same logic that runs in production.
- Adding a new storage backend requires only CRUD correctness, not temporal semantics.
- Repository adapters become almost impossible to get wrong: save properties, read properties, filter by space.
- The SQLite future backend (or any other) becomes trivial to add.

Negative:

- Temporal queries cannot be pushed to the database as optimized queries. Chain-walking happens in Python with multiple repository calls instead of a single Cypher path traversal.
- For long supersession chains or large-scale temporal queries, this may be slower than database-native traversal.

## Alternatives Considered

### Keep Temporal Logic In Repositories

Each adapter reimplements get_current, get_at, get_history. This allows database-native optimizations (Cypher path queries for chains) but forces integration tests against a real database to prove correctness. Two implementations of the same logic is a maintenance burden that grows with every new backend.

### Repository Contract Tests

Write a shared test suite that both in-memory and Neo4j repositories must pass. This ensures behavioral equivalence without moving logic out of the repos. However, it still requires maintaining two implementations and running integration tests for the contract to hold. The duplication remains.

## Reconsideration Trigger

Revisit this decision if:

- Supersession chains grow long enough that Python chain-walking becomes a measurable performance bottleneck.
- Temporal queries need database-native features (graph path traversal, temporal indexes) that cannot be efficiently expressed as multiple CRUD calls.
- A query pattern emerges that is too expensive to express without pushing logic into the storage layer.

In those cases, specific hot-path queries can be pushed down to the repository as optimized methods without reverting the general principle.
