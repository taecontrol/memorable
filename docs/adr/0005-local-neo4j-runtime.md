# ADR 0005: Use A Local Neo4j Runtime Behind The Storage Adapter

Date: 2026-05-23
Status: Accepted

## Context

ADR 0001 decides that Memorable builds its temporal core directly on Neo4j first, behind a storage adapter boundary.

That decision does not specify how local-first Neo4j works for users and agents. Without a runtime decision, implementation details can leak into the domain model:

- a MemoryProfile could accidentally contain machine-specific storage settings;
- agents could rely on raw Neo4j concepts instead of Memorable Core language;
- different workspaces could be mixed without clear MemorySpace isolation;
- local and remote storage behavior could become ambiguous;
- credentials and runtime state could be committed by mistake.

Memorable's trust posture is local-first by default. A human owner should be able to inspect and control where project memory lives. Cloud or remote storage may exist later, but it must be explicit.

## Decision

Memorable uses a local Neo4j runtime as the first storage runtime.

Memorable Core does not start, stop, or configure Neo4j directly. Core talks to a storage adapter through Memorable concepts such as MemorySpace, MemoryProfile, MemoryRecord, Entity, Relation, Episode, Provenance, Current Truth, and Point-In-Time Truth.

The Neo4j storage adapter owns Neo4j-specific schema setup, indexes, constraints, connection behavior, and translation between Memorable Core and Neo4j storage structures.

The local runtime contract is:

- local Neo4j is the default storage runtime;
- remote Neo4j requires explicit configuration;
- MemorySpace isolation is required for every write and query;
- a single local Neo4j instance may store multiple MemorySpaces, isolated by MemorySpace identity;
- per-project Neo4j databases or per-project containers may be added later, but are not required for the first implementation;
- runtime configuration is separate from the MemoryProfile;
- credentials and local runtime state are never committed intentionally;
- Neo4j storage vocabulary stays inside the storage adapter and runtime documentation.

The first workspace files are:

```text
.memorable/
  memory.yaml             # committed MemoryProfile
  runtime.local.yaml      # local runtime config, gitignored
```

`memory.yaml` describes the project memory shape and policy. `runtime.local.yaml` describes machine-local runtime choices such as Neo4j URI, credential reference, embedding provider, and model configuration.

## Consequences

Positive:

- Memorable keeps a clear boundary between domain semantics and storage operations.
- Local-first behavior is explicit and inspectable.
- Users can choose managed local Neo4j or connect to an existing local instance.
- MemorySpace isolation can be tested as part of the tracer bullet.
- Remote storage cannot happen accidentally through default configuration.

Negative:

- Users need Neo4j available locally, either managed by Memorable or supplied by the user.
- The runtime layer must handle diagnostics, credentials, ports, and setup errors.
- The first implementation must define adapter setup behavior before higher-level memory features can be trusted.

## Alternatives Considered

### One Neo4j Container Per MemorySpace

This gives strong physical isolation and simple cleanup, but creates port management, startup, and resource overhead. It is heavier than needed for the first implementation.

### One Neo4j Database Per MemorySpace

This gives stronger separation inside Neo4j, but adds database management concerns early. MemorySpace identity filtering is enough for the first tracer bullet.

### Embedded Or File-Based Storage First

This reduces setup friction, but does not test the temporal graph and GraphRAG shape that Memorable is intentionally building.

### Remote Neo4j First

This would simplify local dependencies for some users, but conflicts with the local-first trust posture. Remote storage remains an explicit future option.

## Reconsideration Trigger

Revisit this decision if:

- MemorySpace filtering proves too risky or hard to enforce;
- local Neo4j setup dominates user friction;
- Neo4j vector or graph retrieval behavior does not support the GraphRAG tracer bullet;
- a different local graph store can satisfy temporal, provenance, and retrieval requirements with less operational burden.
