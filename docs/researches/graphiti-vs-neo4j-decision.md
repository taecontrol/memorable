# Graphiti vs Direct Neo4j Research Memo

Date: 2026-05-23

## Recommendation

Build Memorable's core memory model directly against Neo4j first, behind a storage adapter boundary. Do not make Graphiti the core dependency yet.

This recommendation only holds if Memorable treats temporal graph semantics as a first-class product requirement from the first prototype. Decisions become stale, tasks complete, assumptions get contradicted, and facts may be true for one interval and false later. Memorable should not start with a flat "latest notes" store and hope to add time later.

Graphiti should remain a candidate adapter or comparison spike, not the source of truth for Memorable's domain model. The main reason is that Memorable wants agent-owned, explicit, structured memory writes. Graphiti's strongest value is its LLM-centered ingestion and maintenance pipeline: extracting nodes and facts from episodes, resolving duplicates, extracting timestamps and attributes, and invalidating contradicted facts. If the agent already owns those choices, Graphiti becomes less of a memory model and more of a convenience library with behaviors we may need to bypass or constrain.

The architecture should therefore be:

- `memorable-core`: domain types, validation, schema registry, provenance, temporal semantics, retrieval contracts.
- `memorable-mcp`: MCP adapter over the core.
- `storage/neo4j`: first implementation.
- `storage/graphiti`: optional proof-of-concept only if its retrieval or temporal maintenance materially outperforms the direct adapter.

If the direct Neo4j prototype cannot make temporal invalidation, completion, supersession, and point-in-time queries feel simple and inspectable, Graphiti deserves a much stronger look.

## Current Graphiti Facts Checked

Graphiti latest release checked: `v0.29.1`, released on 2026-05-21.

Sources:

- Graphiti repository README: https://github.com/getzep/graphiti
- Graphiti releases: https://github.com/getzep/graphiti/releases
- Adding episodes docs: https://help.getzep.com/graphiti/core-concepts/adding-episodes
- Custom entity and edge types docs: https://help.getzep.com/graphiti/core-concepts/custom-entity-and-edge-types
- Graph namespacing docs: https://help.getzep.com/graphiti/core-concepts/graph-namespacing
- Searching docs: https://help.getzep.com/graphiti/working-with-data/searching
- CRUD docs: https://help.getzep.com/graphiti/working-with-data/crud-operations
- Adding fact triples docs: https://help.getzep.com/graphiti/working-with-data/adding-fact-triples
- Source inspected on `main`:
  - https://github.com/getzep/graphiti/blob/main/graphiti_core/graphiti.py
  - https://github.com/getzep/graphiti/blob/main/graphiti_core/nodes.py
  - https://github.com/getzep/graphiti/blob/main/graphiti_core/edges.py
  - https://github.com/getzep/graphiti/blob/main/graphiti_core/utils/maintenance/node_operations.py
  - https://github.com/getzep/graphiti/blob/main/graphiti_core/utils/maintenance/edge_operations.py
  - https://github.com/getzep/graphiti/blob/main/graphiti_core/search/search.py
  - https://github.com/getzep/graphiti/blob/main/graphiti_core/search/search_filters.py

## What Graphiti Adds Over Neo4j

Graphiti packages several useful layers on top of the graph database:

- Data conventions: `EpisodicNode`, `EntityNode`, `EntityEdge`, `CommunityNode`, sagas, `MENTIONS`, `RELATES_TO`, `HAS_EPISODE`, and `NEXT_EPISODE`.
- Namespacing: `group_id` is carried on nodes and edges for isolated graphs.
- Temporal fields: entity edges carry `valid_at`, `invalid_at`, `expired_at`, `reference_time`, `created_at`, and episode provenance.
- Provenance: episodes are first-class nodes and extracted entities are linked back to source episodes.
- Retrieval: hybrid search across semantic embeddings, full-text/BM25, BFS graph traversal, RRF/MMR/cross-encoder/node-distance reranking, and filters by labels, edge types, dates, UUIDs, and properties.
- Maintenance: LLM-assisted node deduplication, edge deduplication, contradiction detection, timestamp extraction, attribute extraction, node summaries, communities, and saga summaries.
- Backends and tooling: Neo4j plus FalkorDB, Kuzu, and Neptune drivers, an MCP server, a FastAPI service, and index/constraint setup helpers.

Those are real features. The question is whether Memorable wants them as policy, or wants them as optional implementation details.

## Temporal Semantics Are Core

The temporal graph shape is not a secondary feature. It is probably the heart of Memorable.

Memorable needs to represent:

- "This was true then."
- "This is current now."
- "This was superseded by a later decision."
- "This task was open, then completed."
- "This assumption was contradicted."
- "This source produced this claim at this time."
- "As of this date, what did the project believe?"

The direct Neo4j design should borrow the best ideas from Graphiti's shape:

- every fact-like edge has `valid_at`, `invalid_at`, `created_at`, and optional `expired_at`;
- every stored memory has source provenance through an `Episode` or source event;
- supersession/invalidation is modeled explicitly, not by overwriting old records;
- current-state queries filter for unexpired facts, decisions, and tasks;
- historical queries can reconstruct state at a reference time;
- task completion and decision invalidation are graph events, not destructive updates.

The key difference is policy ownership. Graphiti can infer invalidation with LLM maintenance. Memorable should let the agent or user explicitly decide when a decision is invalidated, a task is completed, or a fact is superseded, then store that temporal transition clearly.

## What Is Coupled To LLM Extraction Or LLM Maintenance

`add_episode` is the central Graphiti ingestion path. It takes text, message, or JSON episode content; retrieves previous episodes; calls extraction prompts for nodes; resolves nodes; extracts edges; resolves edges; extracts attributes and summaries; then saves the results. Custom entity and edge types are Pydantic schemas that guide that extraction/classification process. They are not primarily a dynamic agent-authored schema registry.

The manual `add_triplet` API does accept explicit `EntityNode` and `EntityEdge` objects, which is the closest match to agent-owned structured writes. However, it still:

- generates embeddings;
- resolves missing source/target nodes through Graphiti node deduplication;
- searches existing related edges;
- calls `resolve_extracted_edge`, which can use the LLM for duplicate detection, contradiction detection, custom attributes, and timestamp extraction;
- saves invalidated edges when the resolver decides newer facts supersede older facts.

So `add_triplet` is not a pure "write exactly this graph mutation" API. It is a structured entry point into Graphiti's maintenance pipeline.

Lower-level CRUD exists on nodes and edges, and direct `save()` calls can bypass most of the LLM path. But if Memorable uses those directly, it is mostly borrowing Graphiti's model classes and drivers while implementing its own memory semantics anyway.

## Can Graphiti Accept Fully Structured Writes?

Partly.

Good fit:

- Explicit fact triples using `add_triplet`.
- Explicit node and edge objects using lower-level CRUD.
- Arbitrary attributes on `EntityNode.attributes` and `EntityEdge.attributes`.
- Project/workspace isolation via `group_id`.
- Search filters over labels, edge names, temporal fields, and properties.

Not a clean fit:

- Deterministic writes where the agent, not Graphiti, owns dedupe and contradiction policy.
- Dynamic per-project schema governed by Memorable rather than Pydantic classes passed into extraction calls.
- Claims, decisions, tasks, observations, confidence, and provenance as first-class product concepts unless Memorable maps them onto Graphiti's generic entity/edge conventions.
- Avoiding LLM calls during write maintenance while still using Graphiti's higher-level APIs.

## Dynamic Schema Implications

Graphiti custom types are useful when Graphiti is extracting from text/JSON. They let developers prescribe domain types and attributes with Pydantic models, and Graphiti can evolve by adding new attributes later.

For Memorable, the schema is likely more fluid:

- each workspace may have its own memory vocabulary;
- agents may propose new entity/relation/claim types;
- humans may need to inspect and constrain those schemas;
- validation should happen before storage, not inside an extraction prompt.

That points toward a Memorable-owned schema registry. Even if the storage is flexible, the system should validate memory writes through a project schema layer so the graph does not quietly become a pile of ad hoc labels and properties.

## What We Lose By Skipping Graphiti Initially

- A ready-made temporal graph shape.
- A ready-made hybrid retrieval stack.
- LLM-assisted deduplication and contradiction handling.
- Episode provenance conventions.
- Entity and edge embedding plumbing.
- Community and saga summaries.
- Existing MCP/API examples and multi-backend support.

The biggest real loss is Graphiti's already-worked temporal/provenance shape. Memorable should not casually re-invent this. The direct Neo4j path must deliberately implement a small, Graphiti-inspired temporal model before expanding into broader memory features.

The second biggest loss is retrieval infrastructure. Rebuilding basic Neo4j full-text/vector search plus simple graph traversal is manageable, but Graphiti's retrieval recipes and rerankers are a meaningful head start.

Automatic invalidation is a mixed loss. For Memorable, LLM-driven invalidation may be a product risk unless the agent explicitly requested it and provenance is visible. But explicit invalidation, completion, and supersession are absolutely required.

## What We Gain By Going Direct

- Clear control over the write contract.
- No hidden extraction or mutation policy.
- A schema designed around agent memory, not generic context graph ingestion.
- Easier inspectability: every claim, task, decision, source, confidence, and temporal assertion can be explicit.
- Easier local-first operation and debugging.
- Lower risk of being shaped by Graphiti's API and release churn.

## Proposed Core Data Model

Start with a small graph model:

- `MemorySpace`: one per workspace/project.
- `Episode`: provenance event, source conversation/file/meeting/tool call, authoring agent, timestamps, optional raw content hash.
- `Entity`: named thing, typed by project schema, with attributes.
- `Relation`: typed edge between entities, with fact text, attributes, provenance, confidence, validity window, and supersession state.
- `Observation`: assertion that may or may not be represented as an entity-to-entity relation.
- `Decision`: user or project decision with rationale, status, provenance, validity window, and supersession links.
- `Task`: commitment/follow-up with status transitions, assignee, due dates, completion time, and provenance.
- `SchemaType`: project-scoped type registry for entities, relations, observations, decisions, and tasks.

Temporal state should be append-first. Completing a task or invalidating a decision should create an event/edge that closes the prior validity window and preserves the previous state for history.

Use Graphiti-compatible field ideas where they help future migration: `uuid`, `group_id`/`space_id`, `created_at`, `valid_at`, `invalid_at`, `expired_at`, `source_episode_id`, `confidence`, and human-readable fact text.

## Smallest Useful Prototype

Build a narrow comparison using the same memory writes and queries in two adapters.

Inputs:

1. Add entity `Memorable`.
2. Add decision: "Memorable uses one memory namespace per workspace by default."
3. Add relation: "Memorable exposes memory through MCP first."
4. Add superseding decision: "Graphiti is optional behind a storage adapter, direct Neo4j is first implementation."
5. Add task: "Build the MCP adapter."
6. Complete that task.
7. Query by semantic text, graph traversal, recency, provenance, "current truth", and "truth as of timestamp".

Direct Neo4j adapter should prove:

- deterministic structured writes with no LLM calls;
- first-class provenance and confidence;
- explicit temporal validity and supersession;
- decision invalidation and task completion as historical graph transitions;
- point-in-time reconstruction for decisions, tasks, and relations;
- basic full-text/vector/graph retrieval;
- easy human inspection with Cypher.

Graphiti adapter spike should prove or fail:

- can use `add_triplet` without unwanted LLM mutation, or document exactly where LLM calls happen;
- can preserve Memorable-specific concepts without awkward flattening;
- can retrieve better context than the direct adapter for the same writes;
- can respect project-level schema constraints;
- can keep source/provenance and "why this was stored" visible.

Success criterion for adopting Graphiti: it must materially improve retrieval or temporal maintenance without taking write-policy ownership away from the agent/Memorable core.

## Decision

For now: direct Neo4j first, storage adapter boundary always, Graphiti POC only after the core write contract is defined.

This keeps Memorable honest. If Graphiti later proves valuable, it can be an implementation behind Memorable's interfaces. If it does not, the project still has a clean memory model rather than a half-bypassed extraction engine.
