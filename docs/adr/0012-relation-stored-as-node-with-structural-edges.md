# ADR 0012: Relation Stored As Node With Structural Edges

Date: 2026-05-26
Status: Accepted

## Context

Relation is the first domain concept in Memorable that is inherently a graph edge — it connects two Entities. The existing temporal record types (Decision, Observation, Task) are standalone records stored as Neo4j nodes. Relation needs the same temporal lifecycle (supersession, invalidation, correction, provenance) but also needs to participate in graph traversal for retrieval.

Three storage designs were considered:

1. **Pure node** — Relation stored as a node with `source_entity_id` and `target_entity_id` as string properties. No Neo4j relationships. Graph queries use property scans.
2. **Node with structural edges** — Relation stored as a node with temporal properties, plus native Neo4j relationships `(:Entity)<-[:FROM]-(:Relation)-[:TO]->(:Entity)` for graph traversal.
3. **Native Neo4j relationship** — Relation stored as a Neo4j relationship between Entity nodes, with temporal properties on the relationship.

Design 3 was eliminated because Neo4j relationships cannot support supersession links (relationship pointing to another relationship), provenance attachment requires intermediate nodes, and the TemporalRecordRepository protocol cannot address relationships by application-level ID. This would require a parallel temporal system just for Relations.

The choice between Design 1 and Design 2 hinges on whether Relations should use Neo4j's graph capabilities for traversal.

## Decision

Store Relations as Neo4j nodes with structural edges to their endpoint Entity nodes (Design 2).

The Relation domain model has `source_entity_id` and `target_entity_id` as plain string fields. The repository port has the same shape as Decision and Observation. The difference is entirely in the Neo4j adapter: on write, it creates the Relation node plus `[:FROM]` and `[:TO]` relationships connecting it to the source and target Entity nodes.

The in-memory repository (used in tests) stores Relations as plain objects and filters by properties. A future SQLite adapter would use foreign keys. Each adapter translates endpoint references into its native structure.

## Consequences

Positive:

- Graph expansion uses native Neo4j traversal instead of property scans, which is what Neo4j was chosen for (ADR 0001).
- The Relation node carries full temporal semantics: lifecycle state, validity time, supersession links, provenance. All generic temporal services (CurrentTruth, PointInTime, InspectHistory, Invalidate, Correct) work unchanged.
- The structural edges are a storage adapter concern. The domain model, repository ports, application services, and in-memory tests do not know about them.
- Adding a non-graph storage backend (SQLite) does not require graph structure — the adapter translates endpoint IDs into its native join model.

Negative:

- The Neo4j adapter for Relations is slightly more complex than for Decision or Observation: it creates a node plus two relationships on write instead of just a node.
- Relations have a different Neo4j storage shape than other temporal records. This is appropriate (Relations are graph edges; Decisions are not) but means the adapter is not a uniform pattern across all record types.

## Alternatives Considered

### Pure Node (Design 1)

Store endpoint IDs as string properties with no Neo4j relationships. Graph queries would use `WHERE r.source_entity_id = $id OR r.target_entity_id = $id` instead of native traversal. This is simpler and perfectly consistent with Decision and Observation storage, but it uses a graph database without using the graph for the one concept that is inherently a graph edge.

### Native Relationship (Design 3)

Store Relations as Neo4j relationships between Entity nodes. Most natural for graph queries, but fundamentally incompatible with Memorable's temporal record model: no supersession links between relationships, no provenance attachment, no TemporalRecordRepository compatibility.
