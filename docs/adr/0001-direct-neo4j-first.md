# ADR 0001: Build The Temporal Core Directly On Neo4j First

Date: 2026-05-23
Status: Accepted

## Context

Memorable needs a temporal graph memory model for agents. It must represent current truth, historical truth, completed tasks, superseded decisions, corrected evidence, provenance, and project-scoped memory spaces.

Graphiti was evaluated as a possible layer over Neo4j. It provides real value:

- graph namespacing;
- episode and provenance conventions;
- entity and edge models;
- temporal edge fields such as `valid_at`, `invalid_at`, `expired_at`, and `created_at`;
- hybrid retrieval with semantic search, full-text search, graph traversal, and reranking;
- deduplication, contradiction handling, timestamp extraction, summaries, and community/saga concepts;
- multiple storage backends and existing service/MCP examples.

Those features are valuable, especially the temporal and provenance shape.

The mismatch is write-policy ownership. Memorable's product direction is that agents intentionally decide what to store and how to structure it. The memory system should validate, persist, retrieve, and explain those writes. It should not primarily depend on a hidden LLM extraction and maintenance pipeline to decide entities, facts, contradictions, timestamps, or invalidations.

Graphiti's high-level ingestion APIs are centered on extraction and maintenance. Manual triplet writes can accept structured nodes and edges, but still enter maintenance paths that may perform deduplication, contradiction detection, attribute extraction, timestamp extraction, embedding generation, and invalidation behavior. Lower-level CRUD can bypass more of this, but then Memorable would mostly be borrowing model classes and drivers while implementing its own semantics anyway.

## Decision

Build Memorable's core temporal memory model directly on Neo4j first.

Keep a storage adapter boundary from the beginning:

- `memorable-core` owns domain types, temporal semantics, profile validation, provenance, and retrieval contracts.
- `memorable-mcp` exposes the core through MCP.
- `storage/neo4j` is the first implementation.
- `storage/graphiti` may be built later as a proof of concept or adapter if it improves retrieval or temporal behavior without taking write-policy ownership away from Memorable.

The direct Neo4j implementation must still borrow the useful ideas from Graphiti-style temporal graphs:

- project/workspace isolation;
- first-class source/provenance records;
- explicit validity windows;
- append-first lifecycle events;
- supersession and invalidation links;
- current-state queries;
- point-in-time reconstruction;
- hybrid retrieval where useful.

## Consequences

Positive:

- Memorable controls the agent-facing write contract.
- Temporal behavior is explicit and inspectable.
- Project profiles and schema validation belong to Memorable.
- Local-first operation is easier to reason about.
- The product is not shaped around another library's ingestion assumptions.
- Future CLI and HTTP APIs can share the same core model.

Negative:

- Memorable must implement more storage and retrieval behavior itself.
- Hybrid search, deduplication, and temporal query ergonomics are not free.
- The first prototype must prove that direct Neo4j temporal operations are simple enough.

## Reconsideration Trigger

Reconsider Graphiti as an implementation if a direct Neo4j prototype makes any of these awkward, fragile, or too expensive:

- decision supersession and invalidation;
- task completion and reopening;
- evidence correction;
- point-in-time reconstruction;
- provenance traversal;
- high-quality retrieval over semantic, full-text, graph, temporal, and source filters.

Adopting Graphiti later requires proof that it materially improves retrieval or temporal maintenance while preserving Memorable's agent-owned structured write contract.

