# Storage Module

Date: 2026-05-23
Status: Draft

## Purpose

The Storage module persists Memorable Core concepts and returns them without making storage technology part of the product language.

The first storage adapter is Neo4j, as accepted in ADR 0001 and ADR 0005.

## Owns

- `StoragePort` implementation.
- Neo4j connection behavior.
- Neo4j schema setup, indexes, constraints, and vector indexes where used.
- Translation between Memorable Core concepts and Neo4j storage structures.
- Storage-level transactions and retry behavior.
- Storage diagnostics needed by `memorable doctor`.
- Query primitives needed by Core and Retrieval.

## Does Not Own

- MemoryProfile semantics.
- Write Policy decisions.
- Lifecycle meaning.
- Current Truth and Point-In-Time Truth semantics, except where implementing queries specified by Core/Retrieval.
- Embedding generation.
- MCP or CLI output language.
- Runtime process management.

## Port

### StoragePort

The StoragePort should provide durable operations for:

- initializing storage for a MemorySpace;
- storing Episodes, Entities, MemoryRecords, Relations, lifecycle Events, and Supersession links;
- reading current records by MemorySpace and type;
- reading historical records by point in time;
- traversing Provenance;
- supporting graph expansion for Retrieval;
- supporting vector or text search primitives if the first implementation keeps those indexes in Neo4j.

## Adapters

### Neo4jStorageAdapter

The Neo4j adapter is the first StoragePort implementation.

It may use Neo4j nodes, relationships, labels, properties, constraints, full-text indexes, and vector indexes internally. Those choices are storage details and should not define Memorable Core language.

## Boundary Contract

- Every stored item is scoped by MemorySpace identity.
- Adapter writes preserve Provenance and temporal fields supplied by Core.
- Adapter writes do not silently overwrite truth-bearing history.
- Adapter query results are translated back into Core result shapes.
- Adapter diagnostics may mention Neo4j details, but normal product behavior should use Memorable language.

## Forbidden Leaks

- Do not expose Neo4j `Node` or `Relationship` as Entity or Relation APIs.
- Do not let Cypher query shape dictate Core model shape.
- Do not allow unscoped queries across MemorySpaces.
- Do not make Neo4j credentials or runtime paths part of MemoryProfile.

## Tests That Should Enforce This Boundary

- All storage writes include MemorySpace identity.
- Queries for one MemorySpace cannot return another MemorySpace's records.
- Superseded records remain stored and traversable as history.
- Provenance traversal works from records back to Episodes.
- Storage results use Core identifiers and domain fields, not raw Neo4j objects.

## Open Questions

- Should embeddings be stored in Neo4j vector indexes first, or through a separate vector index adapter?
- Which constraints and indexes are required for the first tracer bullet?
- How much query composition belongs in Storage versus Retrieval?
