# Memorable Ubiquitous Language

Date: 2026-05-23

## Purpose

This document defines the shared language for Memorable Core.

It is not a complete Domain-Driven Design model. It is a pragmatic language contract for product docs, core code, project memory profiles, schemas, and agent-facing tools. It borrows the useful part of DDD: use the same words for the same ideas inside a clear boundary.

The goal is to reduce ambiguity, keep the model simple enough to use, and prevent storage or integration vocabulary from accidentally becoming the product language.

## Scope

The primary bounded context is **Memorable Core**.

Memorable Core owns the language for:

- memory spaces;
- project memory profiles;
- structured memory records;
- entities, relations, decisions, tasks, evidence, events, observations, measurements, and derived memories;
- provenance and sources;
- temporal validity and lifecycle transitions;
- review, correction, supersession, invalidation, and generated views;
- retrieval contracts such as current truth, point-in-time truth, and GraphRAG retrieval.

Supporting contexts include:

- MCP agent interface;
- Neo4j storage adapter;
- embedding providers and retrieval indexes;
- optional Graphiti adapter or comparison spike;
- Markdown, reports, summaries, reviews, and other generated views.

Supporting contexts translate to and from Memorable Core. They do not define the core product language.

## Update Workflow

Update this document when a core domain term is introduced, renamed, split, merged, or made authoritative by product docs, ADRs, schemas, core code, or MCP tools.

Do not update this document for storage-only implementation details unless those details affect product language or agent-facing behavior.

Use these sections as the workflow:

- Add stable terms to **Accepted Language** when they should be used in product docs, core code, schemas, and MCP tools.
- Add still-forming terms to **Candidate Language** when the concept seems useful but the name or meaning is not stable yet.
- Add misleading, overloaded, deprecated, or infrastructure-leaky terms to **Avoided Language** with a preferred replacement.

During design and code review, check whether new names match this document. If a name does not match, either rename the code/docs or update this document intentionally.

## Accepted Language

### Memorable

Memorable is a project-scoped memory system for agents.

Use this term for the product as a whole. Memorable lets agents remember decisions, observations, tasks, evidence, events, and context so humans do not have to repeat themselves or maintain Markdown files as the source of truth.

Do not use this term for a specific storage adapter, database schema, or MCP server alone.

### Agent

An Agent is a software actor that reads from and writes to Memorable on behalf of a user or workflow.

Agents are the primary users of Memorable. They decide what is worth remembering, subject to the project memory profile and write policy.

Do not use Agent to mean the human owner.

### Human Owner

A Human Owner is the person who owns, reviews, corrects, and benefits from a memory space.

Humans own the memory. Agents may write memory, but humans must be able to inspect what was remembered, why it was remembered, what is current, what is stale, and how to correct it.

### MemorySpace

A MemorySpace is the project-scoped memory boundary for a workspace or folder.

Use MemorySpace when referring to the container that owns records, entities, provenance, profile rules, and temporal history for one project or workspace.

Do not use MemorySpace for a global undifferentiated memory. Shared or global memory may exist later, but it is not the default.

Example: the `memorable` workspace has its own MemorySpace.

### MemoryProfile

A MemoryProfile is the project-specific schema and policy that specializes the universal memory kernel for one MemorySpace.

As a target design it defines domain-specific entity types, record types, relation types, metric keys, workflows, write policies, sensitive categories, lifecycle rules, and common queries. **The current build parses only a subset:** `version`, `space.{name,description}`, `entity/relation/record` declarations (each `name` plus `description`, and `extends` on records). Every other key is rejected at load time rather than silently ignored (ADR-0017). Metric keys, workflows, write policies (removed by ADR-0014), sensitive categories, lifecycle rules, and common queries are not yet part of the parsed schema.

The first representation is `.memorable/memory.yaml`.

Do not use MemoryProfile as a generic user preference file.

### Universal Memory Kernel

The Universal Memory Kernel is the small set of memory concepts Memorable always understands across projects.

It includes concepts such as MemorySpace, MemoryProfile, Source, Episode, Entity, MemoryRecord, Evidence, Observation, Measurement, Event, Relation, Decision, Task, and DerivedMemory.

Project memory profiles specialize the kernel; they do not replace it.

The kernel names a vocabulary, not all of which is writable yet. Distinguish:

- **Writable Record Types** — kernel record types that have a write path today: Decision, Observation, and Task. A MemoryProfile `records:` declaration may only extend a Writable Record Type.
- **Structural kernel types** — Entity and Relation, written through their own primitives and enforced against the MemoryProfile.
- **Kernel Vocabulary (not yet writable)** — Evidence, Measurement, Event, and DerivedMemory. These are accepted language and part of the kernel concept set, but have no model, repository, or write path in the current build. They are not valid `extends` targets. Each is marked below.

See ADR-0017 (fail-loud profile validation) for the rule that profiles fail to load when they extend a non-writable type or declare unknown keys.

### MemoryRecord

A MemoryRecord is a structured, truth-bearing unit of memory.

Use MemoryRecord for records that carry shared temporal and provenance semantics. Decisions, observations, evidence, relations, rules, derived summaries, and project-specific records can all be MemoryRecords or specializations of MemoryRecord.

Do not use MemoryRecord for every database row, graph node, or generated Markdown paragraph.

### Writable Record Type

A Writable Record Type is a kernel record type that has a write path in the current build: Decision, Observation, and Task.

Use Writable Record Type when stating the contract for MemoryProfile `records:` declarations. A custom record type may only `extends` a Writable Record Type; extending a non-writable Kernel Vocabulary term (Evidence, Measurement, Event, DerivedMemory) or a structural type (Entity, Relation) fails profile validation.

This term names a moving line, not a permanent one. When a Kernel Vocabulary term gains a write path, it becomes a Writable Record Type and a valid `extends` target. The distinction exists so the language and the build stay honest about what an agent can actually write today.

Do not confuse a Writable Record Type with the broader Universal Memory Kernel vocabulary, which also names concepts that are accepted language but not yet writable.

### Entity

An Entity is a remembered thing with identity inside a MemorySpace.

Use Entity for named domain things that memory can refer to over time, such as a project, component, API, storage adapter, stakeholder, race, or training phase.

Do not confuse a Memorable Entity with a Neo4j node or Graphiti `EntityNode`. A storage node may store a Memorable Entity, but the storage shape is not the domain concept.

Correct: "Memorable is an Entity remembered in the project MemorySpace."

Avoid: "Every Neo4j node is a Memorable Entity."

### Relation

A Relation is a directed, typed connection between two Entities in a MemorySpace.

A Relation has a source Entity, a target Entity, a relation type, and a statement describing the connection in natural language. Relations carry full temporal validity, provenance, and lifecycle semantics: they can be superseded, invalidated, and corrected, just like Decisions and Observations.

Relation types are declared in the MemoryProfile. An agent cannot create a Relation with a type not declared in the profile.

Use Relation for domain connections between Entities that Memorable should reason over and that semantic search alone cannot reliably recover: dependencies, ownership, succession, and other structural relationships.

Do not use Relation as a synonym for every storage edge. Do not use Relation to connect Records (Decisions, Tasks, Observations) to the Entities they are about; that connection is the **About** edge (see below), which is membership, not a truth-bearing claim. Relation is reserved for truth-bearing claims between two Entities.

### About

An About edge is an optional, untyped link from a MemoryRecord to one or more Entities it concerns.

About expresses membership or aboutness, not a truth-bearing claim. "This observation is about Build 2" asserts nothing that can become false over time; it simply records which Entities the record concerns. This is the distinction from Relation: a Relation is a claim between two Entities that can be superseded as the claim evolves; an About edge cannot be superseded, only corrected.

An About edge carries no temporal or lifecycle fields of its own — no validity time, invalidation time, lifecycle state, or supersession links. All temporal weight stays on the record, which already has its own validity time. The edge is membership and nothing more.

About is correctable, not superseded. A wrong edge was wrong from creation; fixing it hard-removes the edge (append-first history is for truth claims, not membership). If a record's subject genuinely changed, that is a new record, not an evolving edge.

About is a parameter on the record write primitives (`remember_decision`, `remember_observation`, `remember_task`), not a primitive of its own. Cardinality is one record to many Entities; direction is record to Entity only. The target Entity must already exist or the write fails loud; there is no edge type to declare.

Use About to attach records to the Entities they concern so retrieval can expand from a record to its Entities (and from an Entity to its records) and so Memory Review can list every record about an Entity. Do not use About for connections between two Entities; use Relation. Do not give About a type or a lifecycle; if a connection needs either, it is a Relation, not an About edge.

See ADR-0018 (records link to the entities they are about).

### Observation

An Observation is an assertion remembered by Memorable that may not naturally fit as a Relation, Decision, Task, or Measurement.

Use Observation as a flexible fallback when the memory is useful but the project profile does not yet define a more specific record type.

Do not turn every memory into an Observation when a clearer accepted term exists.

### Evidence

Evidence is a memory record or source-backed claim that supports why something is believed.

**Kernel Vocabulary, not yet writable.** Evidence has no model, repository, or write path in the current build and is not a valid `extends` target. Use Observation as the fallback until Evidence becomes a Writable Record Type.

Use Evidence when the important thing is support, substantiation, or the basis for belief. Evidence should preserve provenance.

Do not use Evidence for a decision itself. A decision may be supported by Evidence.

### Decision

A Decision is a remembered choice that affects future behavior, design, architecture, product direction, or workflow.

Use Decision for choices that need to remain inspectable, explainable, and possibly superseded later.

A Decision should preserve rationale, provenance, temporal validity, and supersession links when replaced or refined.

### Task

A Task is a remembered commitment, follow-up, or piece of work with a lifecycle.

Tasks may be open, completed, reopened, superseded, invalidated, or otherwise transitioned according to lifecycle rules.

Do not erase a completed task. Completion is a lifecycle transition, not deletion.

### Event

An Event is something that happened at a point or interval in time and matters to memory.

**Kernel Vocabulary, not yet writable.** Event has no model, repository, or write path in the current build and is not a valid `extends` target (see ADR-0015, which defers Event-as-record). Lifecycle transitions remain mutations on existing records in V1.

Use Event for happenings such as a meeting, tool result, workflow run, task completion, correction, or lifecycle transition.

Do not use Event for a durable state that remains true over time; use a temporal MemoryRecord with validity semantics.

### Measurement

A Measurement is a recorded value with a metric key, unit, scale when relevant, provenance, and time.

**Kernel Vocabulary, not yet writable.** Measurement has no model, repository, or write path in the current build and is not a valid `extends` target. Do not steer numeric memory toward Measurement yet; record it as an Observation until Measurement becomes a Writable Record Type.

Use Measurement for quantitative memory such as benchmark results, training metrics, or ratings.

Corrections to measurements should preserve the original sample and record the correction.

### DerivedMemory

DerivedMemory is memory produced by summarizing, analyzing, or transforming other memory.

**Kernel Vocabulary, not yet writable.** DerivedMemory has no model, repository, or write path in the current build and is not a valid `extends` target. Use Observation as the fallback until DerivedMemory becomes a Writable Record Type.

Use DerivedMemory for generated summaries, weekly reviews, project briefs, architecture logs, or other records whose basis should be traceable to source records.

Do not treat a generated Markdown artifact as canonical memory unless its contents are written back as structured memory.

### Source

A Source is where a memory came from.

Use Source for provenance origins such as a conversation, file, meeting, tool result, user instruction, generated analysis, or other input.

Do not use Source as a vague synonym for "data." It answers "where did this memory come from?"

### Episode

An Episode is a provenance event or source occurrence that produced memory.

Use Episode when the system needs to represent a specific conversation turn, file ingestion, meeting, tool result, or other occurrence that generated one or more records.

Source names the origin category or object. Episode names the occurrence.

### Provenance

Provenance is the recorded explanation of where a memory came from and why it is believed.

Every memory write should preserve provenance. Provenance belongs in stored memory and inspection workflows; it should not become repetitive chat boilerplate.

### Temporal Semantics

Temporal Semantics are the rules that let Memorable represent what was true then, what is true now, what changed, and why.

Time is part of the domain model, not incidental metadata.

Use Temporal Semantics when discussing current truth, historical truth, validity windows, lifecycle transitions, supersession, correction, invalidation, completion, and point-in-time reconstruction.

### Validity Time

Validity Time is when a remembered claim, state, or rule became true or applicable in the domain.

Do not confuse Validity Time with Creation Time. A record can be stored today about something that became true last week.

### Creation Time

Creation Time is when Memorable stored the memory record.

Use Creation Time for audit and ordering of writes. Use Validity Time for when the remembered claim became true or applicable.

### Invalidation Time

Invalidation Time is when a remembered claim, state, or rule stopped being current.

Use Invalidation Time when a claim becomes false, no longer applies, is replaced, or is closed by a later lifecycle transition.

### Lifecycle State

Lifecycle State is the current state of a MemoryRecord or Task according to the domain lifecycle.

Examples include current, completed, corrected, invalidated, ignored, superseded, and reopened. Exact allowed values belong in implementation specs and profile rules.

Do not model lifecycle only as mutable free text.

### Supersession

Supersession is the explicit relationship where one memory replaces, refines, contradicts, or invalidates another.

Use Supersession when history should show that a later record changed how an earlier record should be used.

Do not silently overwrite the old memory.

### Correction

Correction is a lifecycle operation that preserves an earlier mistaken memory and records the corrected memory or corrected interpretation.

Use Correction when the prior record was wrong or misleading.

Do not use Correction for normal evolution where a new decision intentionally replaces an older one; use Supersession unless the earlier record was erroneous.

### Current Truth

Current Truth is what Memorable presently believes is active, valid, or applicable in a MemorySpace.

Use Current Truth for queries that should exclude superseded, invalidated, completed, or no longer applicable memory unless those records are relevant as history.

### Point-In-Time Truth

Point-In-Time Truth is what Memorable believed or what was valid at a specific time.

Use Point-In-Time Truth for historical reconstruction and "as of" questions.

### GraphRAG Retrieval

GraphRAG Retrieval is retrieval that combines semantic similarity, graph context, temporal filtering, and provenance to assemble useful memory context for agents.

Use GraphRAG Retrieval when discussing Memorable's retrieval model as a whole. It should preserve the distinction between finding relevant candidates and deciding what is current or historically valid.

Do not use GraphRAG Retrieval to imply hidden extraction, hidden contradiction handling, or LLM-owned write policy. Agents still write structured memory intentionally.

### Hybrid Retrieval

Hybrid Retrieval is the retrieval strategy that combines multiple signals such as embeddings, text search, graph traversal, temporal filters, provenance, recency, and ranking.

Use Hybrid Retrieval when discussing the mechanics of finding and ranking memory. GraphRAG Retrieval is the product retrieval model; Hybrid Retrieval is one implementation strategy for that model.

### Indexable Text

Indexable Text is a derived text representation of a memory item used for search and embeddings.

Use Indexable Text for the text generated from MemoryRecords, Entities, Relations, Events, or other retrievable memory items. It should include enough domain language to support retrieval without exposing storage details.

Indexable Text is not canonical memory. If the source memory changes, Indexable Text can be regenerated.

### Embedding

An Embedding is a vector representation derived from Indexable Text for semantic retrieval.

Use Embedding for retrieval index data that can be refreshed or rebuilt from canonical memory. Embeddings should preserve metadata such as MemorySpace identity, source record identity, Indexable Text hash or version, provider, model, dimensions, and creation time.

Do not treat an Embedding as a MemoryRecord or as evidence of truth. Semantic similarity finds candidates; Temporal Semantics decide whether memory is current, historical, superseded, completed, or invalidated.

### Embedding Provider

An Embedding Provider is the local or remote service or library that creates Embeddings from Indexable Text.

Use Embedding Provider for provider configuration, runtime diagnostics, and retrieval adapter behavior. Local providers are preferred by default. Remote providers require explicit configuration because memory content may leave the machine.

### Append-First History

Append-First History is the rule that meaningful changes normally create a new event, correction, or replacement record instead of erasing the previous state.

Current-state fields or indexes may exist for fast reads, but they are conveniences over preserved history.

### Write Policy

Write Policy defines when agents may write memory automatically, when they should suggest memory, and when they need human confirmation.

Use Write Policy for default auto writes, sensitive categories, and project-specific memory rules.

### Sensitive Category

A Sensitive Category is a class of memory that requires stricter write behavior.

Use Sensitive Category in MemoryProfile rules when certain memory should be suggested or confirmed rather than written automatically.

### Generated View

A Generated View is a human-readable artifact produced from memory.

Examples include Markdown summaries, weekly reviews, project briefs, architecture logs, meeting recaps, reports, and review documents.

Generated Views are outputs or views of memory. They are not the canonical memory store unless their contents are intentionally ingested back into structured memory.

### Memory Review

Memory Review is the inspection workflow that lets a Human Owner answer "what is open?" and "what did we do recently?" inside a MemorySpace by asking an Agent, which calls a deterministic listing primitive on Memorable.

Memory Review is a first-class product workflow, not a UI surface. The first version exposes one MCP primitive that the Agent composes through multiple calls with different filters (record type, lifecycle state, time window, and the Entity a record is about — see About). Memory Review is not a family of question-specific tools; "every record about an Entity" is a filter on the listing primitive, not a standalone tool.

The Human Owner is not expected to browse Memorable directly. Memory Review is exposed primarily through the MCP interface so Agents can answer state questions reliably without falling back to semantic search. A CLI surface for Memory Review may exist later but is not required for the first version.

Memory Review answers state questions (what is open, what changed recently). Use GraphRAG Retrieval for similarity questions and Current Truth for point-in-time questions. Memory Review in the first version does not surface lifecycle transitions (supersession, correction, invalidation, task completion as distinct events); promoting Event into a first-class record is the forcing case for closing that gap in a later version.

## Candidate Language

### Lifecycle Event

Lifecycle Event may be useful for representing transitions such as completion, reopening, correction, invalidation, and supersession.

Keep this term candidate until the implementation decides whether lifecycle transitions are modeled as Events, specialized MemoryRecords, edges, or another structure.

### SchemaType

SchemaType may be useful for project-scoped type registry entries that define allowed entity, relation, observation, decision, task, or record types.

Keep this term candidate until the MemoryProfile schema is specified.

### Confidence

Confidence may be useful as uncertainty metadata for memory records.

Use uncertainty only when it changes how memory should be used. Do not force fake precision into every record.

### Retrieval Contract

Retrieval Contract may be useful for the core API promises around search, current truth, point-in-time truth, provenance traversal, recent writes, and generated views.

Keep this term candidate until the core interface is specified.

### Common Query

Common Query may be useful for named project queries in a MemoryProfile, such as current decisions, open questions, recent changes, or risk signals.

Keep this term candidate until profile query behavior is designed.

## Avoided Language

### Note

Avoid using Note as the generic product term for stored memory.

Preferred terms: MemoryRecord, Observation, Evidence, Decision, Task, Generated View.

Reason: Memorable is not a note-taking app, and "note" blurs structured memory with human-authored documents.

### Markdown Store

Avoid describing Markdown as the memory store.

Preferred terms: Generated View, Markdown output, human-readable artifact.

Reason: Markdown is a view or output of memory, not the canonical storage model.

### Global Memory

Avoid implying that Memorable is one global undifferentiated memory.

Preferred term: MemorySpace.

Reason: memory is project-scoped by default.

### Hidden Extraction

Avoid describing Memorable as a hidden LLM extraction pipeline.

Preferred terms: agent-owned structured write, intentional memory write, write policy.

Reason: agents should intentionally decide what to remember and how to structure it.

### Node

Avoid using Node as a core domain term.

Preferred terms: Entity, MemoryRecord, or storage node depending on meaning.

Reason: Node is storage vocabulary in graph databases and can obscure the domain concept.

### Edge

Avoid using Edge as a core domain term.

Preferred terms: Relation, Supersession, provenance link, lifecycle transition, or storage edge depending on meaning.

Reason: Edge is graph storage vocabulary. Memorable Core should name domain relationships.

Exception: "About edge" is an accepted compound term — it names the specific domain concept of record→Entity membership (see the About entry and ADR-0018), not generic storage-edge vocabulary. Still avoid bare "node/edge" graph-storage language for domain relationships.

### Fact

Avoid using Fact when the memory may be uncertain, superseded, contextual, or time-bound.

Preferred terms: MemoryRecord, Observation, Evidence, Relation, Current Truth, or Point-In-Time Truth.

Reason: "Fact" can imply timeless certainty. Memorable needs provenance, uncertainty when useful, and temporal validity.

### Review Surface

Avoid using Review Surface as a product term.

Preferred term: Memory Review.

Reason: "Surface" is UI vocabulary that hides what the workflow actually does. Memory Review names the human-facing inspection workflow regardless of whether it is exposed through CLI, MCP, or a future UI.

### Activity Feed

Avoid using Activity Feed as a product term.

Preferred terms: Memory Review, recent writes (as a Memory Review operation).

Reason: "Activity Feed" implies a chronological stream of UI events. Memorable's recent-writes operation is a Memory Review query over MemoryRecords with Creation Time ordering, not a feed.

## Supporting Context Translation Notes

### MCP

MCP is the first agent-facing interface, not the product model.

MCP tools should expose Memorable Core language. Tool names, inputs, and outputs should use terms such as MemorySpace, MemoryProfile, MemoryRecord, Decision, Task, Evidence, Current Truth, Point-In-Time Truth, Provenance, Correction, Supersession, and Generated View.

Do not expose raw storage terms through MCP unless the tool is explicitly diagnostic.

### Neo4j

Neo4j is the first storage adapter.

Neo4j nodes and relationships may store Memorable Entities, MemoryRecords, Relations, provenance links, and lifecycle transitions. However, Neo4j Node and Relationship are storage vocabulary, not Memorable Core language.

Use storage-specific terms inside adapter implementation and translation docs. Use core language in product docs, schemas, and agent-facing tools.

### Retrieval Indexes And Embeddings

Retrieval indexes and Embeddings are derived retrieval infrastructure.

They may be stored in Neo4j vector indexes, local files, external vector stores, or provider-specific caches. Those storage choices do not define Memorable Core language.

Use Indexable Text, Embedding, Embedding Provider, GraphRAG Retrieval, and Hybrid Retrieval in product docs, schemas, specs, and agent-facing behavior. Keep provider-specific vocabulary inside retrieval adapter implementation unless it affects user-facing configuration or behavior.

### Graphiti

Graphiti is an optional future adapter or comparison spike.

Graphiti terms such as `EntityNode`, `EntityEdge`, `EpisodicNode`, `group_id`, `valid_at`, `invalid_at`, and `expired_at` may influence storage mapping or adapter design. They should not replace Memorable Core terms.

Use Graphiti vocabulary only when discussing the Graphiti adapter, migration, or comparison research.

### Markdown And Documents

Markdown files, reports, summaries, reviews, and documents are Generated Views unless their contents are intentionally written back as structured memory.

Do not treat a document edit as a memory update unless an agent ingests the change into Memorable through an intentional write.
