# Retrieval Module

Date: 2026-05-23
Status: Draft

## Purpose

The Retrieval module assembles useful memory context for agents through GraphRAG Retrieval.

Retrieval combines semantic candidates, graph expansion, temporal filtering, provenance, and ranking. It does not own canonical memory or decide lifecycle truth independently from Core.

## Owns

- GraphRAG retrieval orchestration.
- Hybrid Retrieval strategy.
- Query interpretation for Current Truth and Point-In-Time Truth retrieval.
- Combining vector search, graph traversal, temporal filters, provenance, recency, and ranking.
- Context assembly for agent-facing results.
- Retrieval evaluation fixtures and quality checks.

## Does Not Own

- Canonical MemoryRecords.
- Lifecycle state transitions.
- Write Policy.
- MemoryProfile schema evolution.
- Embedding provider implementation.
- Neo4j storage mappings.
- MCP protocol mechanics.

## Ports And Collaborators

Retrieval should collaborate with:

- Core, for temporal semantics and result language.
- StoragePort, for vector/text search primitives and graph expansion.
- Embeddings, for query embeddings when semantic search is used.

Retrieval may define a higher-level application API such as `search_memory`, `current_truth`, or `point_in_time_truth`, but those APIs should return Core language and provenance-aware results.

## Boundary Contract

- Retrieval can rank candidates, but it cannot make superseded or completed records current.
- Retrieval must scope all searches to a MemorySpace.
- Retrieval must preserve enough provenance for users and agents to inspect why a result exists.
- Retrieval must distinguish current answers from historical answers.
- Retrieval should explain when historical records are included because they are relevant history.
- Retrieval should prefer useful context over raw graph dumps.

## Forbidden Leaks

- Do not expose vector distance as truth.
- Do not expose graph traversal mechanics as product language.
- Do not require agents to know whether results came from full-text search, vector search, or traversal.
- Do not let retrieval silently include remote provider behavior without runtime configuration.

## Tests That Should Enforce This Boundary

- A semantically similar superseded Decision is not returned as Current Truth.
- Point-In-Time Truth can return a record that is no longer current.
- Graph expansion includes related Entities, Relations, Episodes, and Supersession links when useful.
- Provenance is inspectable for retrieved results.
- Retrieval quality can be evaluated against stable fixtures.

## Open Questions

- What is the minimum ranking model for the first implementation?
- Should retrieval result assembly live in Core application services or a separate `retrieval` package?
- Which retrieval metrics should be tracked for fixture-based evaluation?
