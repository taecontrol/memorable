# Core Module

Date: 2026-05-23
Status: Draft

## Purpose

The Core module owns Memorable's product model and domain invariants.

Core should make memory writes, temporal behavior, provenance, lifecycle transitions, profile validation, and retrieval contracts understandable without knowing how Neo4j, MCP, Docker, or embedding providers work.

## Owns

- MemorySpace identity and scoping rules.
- MemoryProfile loading, validation, and profile semantics.
- Universal Memory Kernel concepts.
- MemoryRecord and specializations such as Decision, Task, Evidence, Observation, Measurement, Event, and DerivedMemory.
- Entity and Relation semantics.
- Episode, Source, and Provenance.
- Temporal Semantics: Creation Time, Validity Time, Invalidation Time, Current Truth, and Point-In-Time Truth.
- Lifecycle operations such as supersede, correct, invalidate, complete, and reopen.
- Write Policy and Sensitive Category enforcement.
- Domain result shapes used by interfaces and retrieval.

## Does Not Own

- Neo4j labels, relationships, Cypher, indexes, constraints, or vector index setup.
- Embedding provider APIs, model downloads, API keys, or provider-specific metadata beyond the core Embedding language.
- MCP protocol mechanics.
- CLI argument parsing and terminal output.
- Local service startup, Docker, ports, volumes, or credentials.
- Graphiti classes or ingestion behavior.

## Ports

Core or the application layer should define ports for capabilities required to preserve core behavior:

- `StoragePort`: durable temporal memory storage and retrieval primitives.
- `ClockPort`: deterministic time for writes, lifecycle transitions, and tests.
- `IdPort`: deterministic identity generation when useful for fixtures and tests.

Embedding generation may be a port owned by the Embeddings module rather than Core. Core should not need to know how an Embedding Provider works.

## Boundary Contract

- Core accepts and returns Memorable language.
- Core validates MemoryProfile constraints before writes reach storage.
- Core requires MemorySpace scope for every write and query.
- Core requires Provenance for every truth-bearing MemoryRecord.
- Core models lifecycle changes as append-first operations.
- Core distinguishes Creation Time from Validity Time.
- Core makes supersession, correction, invalidation, completion, and reopening explicit.
- Core treats Embeddings and Indexable Text as derived retrieval data, not canonical memory.

## Forbidden Leaks

- Do not expose Neo4j `Node`, `Relationship`, label, index, or Cypher concepts through Core APIs.
- Do not expose Graphiti `EntityNode`, `EntityEdge`, `EpisodicNode`, or `group_id` as Core concepts.
- Do not put runtime settings such as Neo4j URI, credentials, ports, or embedding API keys into MemoryProfile.
- Do not let semantic similarity determine lifecycle state or temporal truth.

## Tests That Should Enforce This Boundary

- MemorySpace is required for writes and queries.
- MemoryRecord writes fail without Provenance.
- Supersession preserves the prior Decision and changes Current Truth.
- Task completion preserves history and removes the Task from open current reads.
- Point-In-Time Truth differs correctly before and after lifecycle transitions.
- Storage adapter test doubles can satisfy Core tests without Neo4j vocabulary.

## Open Questions

- Which lifecycle states are universal and which are profile-specific?
- Which retrieval result shapes belong in Core versus Retrieval?
- How much MemoryProfile schema validation belongs in Core before implementation proves the profile shape?
