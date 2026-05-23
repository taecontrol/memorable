# Memorable Module Map

Date: 2026-05-23
Status: Draft

## Purpose

This document maps Memorable's first module boundaries.

It is a living architecture document, not an ADR. ADRs record decisions. This document records the current intended shape of the code and the rules that keep the modules honest as the implementation grows.

The organizing concept is **module boundary**:

- a Bounded Context owns domain language;
- a Module owns a coherent implementation responsibility;
- a Port is an interface a module defines because it needs a capability;
- an Adapter implements a port using a specific technology or protocol;
- a Contract is the behavioral promise a module or port must keep.

Memorable currently has one primary bounded context: **Memorable Core**.

## Dependency Rule

Dependencies should point toward Memorable's domain and application behavior.

Core domain concepts must not depend on Neo4j, MCP, CLI frameworks, Docker, embedding providers, Graphiti, or other infrastructure.

Adapters translate between Memorable language and external technology. They do not define product language.

```text
Interfaces / Runtime
        |
        v
Application / Retrieval
        |
        v
Memorable Core
        ^
        |
Storage and Embedding ports implemented by adapters
```

This diagram is conceptual. Actual package structure may differ, but dependency direction should preserve the same boundary.

## Modules

### Core

Core owns the Universal Memory Kernel, MemorySpace, MemoryProfile, MemoryRecord, Entity, Relation, Decision, Task, Evidence, Episode, Provenance, Temporal Semantics, Write Policy, Current Truth, Point-In-Time Truth, lifecycle operations, and profile validation.

See [core.md](/Users/guetteluis/Projects/personal/memorable/docs/architecture/modules/core.md).

### Storage

Storage owns persistence behind a StoragePort. The first adapter is Neo4j. Storage translates core concepts into storage structures and back.

See [storage.md](/Users/guetteluis/Projects/personal/memorable/docs/architecture/modules/storage.md).

### Retrieval

Retrieval owns GraphRAG orchestration: semantic candidates, graph expansion, temporal filtering, provenance-aware result assembly, and ranking. Retrieval does not own canonical truth.

See [retrieval.md](/Users/guetteluis/Projects/personal/memorable/docs/architecture/modules/retrieval.md).

### Embeddings

Embeddings owns Indexable Text to Embedding conversion and provider metadata. Embeddings are derived retrieval indexes, not memory.

See [embeddings.md](/Users/guetteluis/Projects/personal/memorable/docs/architecture/modules/embeddings.md).

### Interfaces

Interfaces owns human and agent entry points such as CLI and MCP. Interfaces translate requests into application behavior and translate results back into user-facing language.

See [interfaces.md](/Users/guetteluis/Projects/personal/memorable/docs/architecture/modules/interfaces.md).

### Runtime

Runtime owns local service setup, diagnostics, and machine-local configuration such as Neo4j process/container management and embedding provider configuration.

See [runtime.md](/Users/guetteluis/Projects/personal/memorable/docs/architecture/modules/runtime.md).

## Cross-Module Invariants

- Every write and query is scoped to a MemorySpace.
- Every truth-bearing MemoryRecord has Provenance.
- Meaningful lifecycle changes preserve Append-First History.
- Current Truth and Point-In-Time Truth are decided by Temporal Semantics, not vector rank.
- Embeddings and retrieval indexes are derived from canonical memory and can be rebuilt.
- Storage vocabulary stays inside storage modules and diagnostics.
- Runtime configuration stays out of MemoryProfile.
- MCP and CLI expose Memorable Core language, not adapter internals.

## When To Split Further

Split a module document when:

- a module has multiple serious adapters;
- a port needs compliance tests;
- operational details become large enough to distract from the module boundary;
- contributors need to implement new adapters independently.

Until then, keep the map small and update these module documents as implementation makes boundaries concrete.
