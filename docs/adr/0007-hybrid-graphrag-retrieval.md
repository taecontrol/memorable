# ADR 0007: Require Hybrid GraphRAG Retrieval In The Tracer Bullet

Date: 2026-05-23
Status: Accepted

## Context

Memorable is not only a temporal graph store. It is a GraphRAG memory system for agents.

Agents need to retrieve useful project context reliably. If retrieval quality is weak, structured writes, provenance, and lifecycle semantics do not deliver their product value.

ADR 0001 chose direct Neo4j first instead of making Graphiti the core dependency. That decision keeps Memorable in control of agent-owned structured writes, but it does not remove the need for GraphRAG retrieval features inspired by systems like Graphiti:

- semantic similarity over remembered records;
- graph traversal from semantic hits;
- temporal filtering for current truth and point-in-time truth;
- provenance inspection;
- ranking and context assembly for agent use.

## Decision

The first tracer bullet must include hybrid GraphRAG retrieval.

Hybrid GraphRAG Retrieval means retrieval that combines:

- vector search over embeddings;
- graph expansion from retrieved records to related Entities, Relations, Episodes, supersession links, and lifecycle transitions;
- temporal filtering for Current Truth and Point-In-Time Truth;
- provenance-aware result explanation;
- ranking suitable for agent context assembly.

Embeddings are required for the tracer bullet. They are derived retrieval indexes, not canonical memory. The canonical memory remains structured MemoryRecords, Entities, Relations, Episodes, provenance, temporal validity, and lifecycle transitions.

Every embedded item must have enough metadata to make the derived index inspectable and refreshable:

- MemorySpace identity;
- source record identity;
- Indexable Text hash or version;
- embedding provider;
- embedding model;
- dimensions;
- creation time.

The first implementation must define an embedding provider abstraction. Tests may use deterministic fake embeddings. The runnable tracer bullet must use a real embedding provider so retrieval quality and operational behavior are tested early.

Local-first remains the default. Local embedding providers are preferred for default local operation. Remote embedding providers are allowed only by explicit configuration because memory content may leave the machine.

## Consequences

Positive:

- The tracer bullet proves Memorable's actual product shape, not only temporal storage.
- Retrieval quality becomes a first-order design concern.
- Embeddings and graph traversal can be evaluated together from the beginning.
- The direct Neo4j path is tested against the same class of retrieval expectations that made Graphiti attractive.

Negative:

- The first tracer bullet is larger and has more operational dependencies.
- Local embedding providers may require heavier setup or weaker retrieval quality than remote providers.
- The implementation must manage embedding refresh and index metadata earlier.
- Retrieval tests need deterministic fixtures to avoid brittle behavior.

## Guardrails

- Do not let embeddings become canonical memory.
- Do not let semantic ranking decide lifecycle truth. Current Truth and Point-In-Time Truth come from temporal semantics.
- Do not require remote embedding providers by default.
- Do not hide provenance behind ranked results.
- Do not make Graphiti vocabulary part of Memorable Core language.

## Alternatives Considered

### Temporal Core First, Embeddings Later

This would reduce the first implementation scope, but it would not prove the product's core value. Memorable must be useful as retrievable agent memory, not just as well-modeled storage.

### Graphiti As Retrieval Core

Graphiti already provides strong retrieval and maintenance features. ADR 0001 rejected using Graphiti as the core dependency because Memorable needs to own the write contract and temporal semantics. Graphiti can still be compared later as an adapter or retrieval influence.

### Vector Search Only

Vector search alone can find semantically similar records, but it does not satisfy Memorable's graph and temporal requirements. The retrieval contract must combine semantic candidates with graph context, lifecycle state, validity windows, and provenance.

## Reconsideration Trigger

Revisit this decision if:

- embedding setup makes the first tracer bullet impractical;
- Neo4j vector search cannot support the needed retrieval behavior;
- graph expansion adds noise instead of improving agent context;
- a Graphiti adapter materially improves retrieval quality while preserving Memorable's agent-owned structured write contract.
