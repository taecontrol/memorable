# Embeddings Module

Date: 2026-05-23
Status: Draft

## Purpose

The Embeddings module turns Indexable Text into Embeddings for semantic retrieval.

Embeddings support GraphRAG Retrieval, but they are derived retrieval infrastructure, not canonical memory.

## Owns

- Indexable Text generation rules where they are not owned by individual record types.
- Embedding provider abstraction.
- Embedding provider metadata.
- Embedding refresh decisions based on Indexable Text hash or version.
- Deterministic fake embeddings for tests.
- Local and remote provider configuration shape in collaboration with Runtime.

## Does Not Own

- MemoryRecord truth.
- Lifecycle state.
- Current Truth or Point-In-Time Truth.
- Storage mapping for canonical memory.
- MCP tool semantics.
- Remote-provider policy beyond exposing configuration and diagnostics.

## Port

### EmbeddingPort

The EmbeddingPort should provide:

- embedding creation for Indexable Text;
- provider and model metadata;
- dimensions;
- deterministic behavior for tests where configured;
- clear errors for missing local models or missing remote credentials.

## Adapters

Likely first adapters:

- deterministic fake embedding adapter for tests;
- local embedding adapter for local-first operation;
- explicit remote embedding adapter for opt-in use.

Remote providers require explicit configuration because memory content may leave the machine.

## Boundary Contract

- Embeddings are rebuildable from canonical memory and Indexable Text.
- Every Embedding is associated with MemorySpace identity and source record identity.
- Every Embedding records provider, model, dimensions, creation time, and Indexable Text hash or version.
- Embedding generation does not mutate canonical MemoryRecords.
- Embedding similarity can find candidates but cannot decide temporal truth.

## Forbidden Leaks

- Do not store provider secrets in MemoryProfile.
- Do not make provider-specific model names part of Core domain behavior.
- Do not treat an Embedding as Evidence or a MemoryRecord.
- Do not require remote embedding providers for default local operation.

## Tests That Should Enforce This Boundary

- Indexable Text changes cause embedding refresh.
- Fake embeddings make retrieval tests deterministic.
- Missing provider configuration fails with actionable diagnostics.
- Embedding metadata is stored or returned with enough detail to inspect and rebuild indexes.

## Open Questions

- Which local embedding provider should be the default?
- Should Indexable Text generation be owned by record types, Retrieval, or Embeddings?
- Should embedding storage live in Neo4j first or behind a separate vector index abstraction?
