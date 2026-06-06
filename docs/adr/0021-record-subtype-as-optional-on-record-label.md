# ADR 0021: Record Subtype As Optional On-Record Label

Date: 2026-06-06
Status: Accepted
Refines: ADR 0002, ADR 0017

## Context

Project MemoryProfiles can declare custom record types under `records:`, such as `Episode extends Observation`, `Pattern extends Observation`, `Commitment extends Task`, or `ArchitectureDecision extends Decision`.

ADR-0017 made profile validation fail loud: unknown keys are rejected, and a `records:` declaration must extend a Writable Record Type (`Decision`, `Observation`, or `Task`). That closed the first silent-no-op trap, where a Human Owner could write profile shape that the current build ignored.

A second gap remains: a valid `records:` declaration still does not affect writes or reads. The profile parses, validates, and appears in inspect output, but an Agent can only write the three kernel record kinds. There is no place on a MemoryRecord saying "this Observation is an Episode," and there is no filter for "show me Episodes." The declaration is valid but inert.

That gap matters for migration. A v0 vault can contain kinds like `Episode`, `Pattern`, and `Commitment`, but the current write model collapses them into generic `Observation` or `Task`. The original kind can survive only as free text in provenance or statement text, so it cannot round-trip as structured memory and cannot be queried as a declared kind.

This is the same honesty problem ADR-0017 addressed, one layer deeper: Memorable should not accept a project schema declaration that has no operational effect.

## Decision

A MemoryRecord whose kernel kind is `Decision`, `Observation`, or `Task` may carry an optional **Record Subtype** label.

The label stores the name of a declared `records:` entry from the active MemoryProfile. It says that a kernel record is a project-specific specialization of that kernel kind: an `Episode` is still an `Observation`; a `Commitment` is still a `Task`; an `ArchitectureDecision` is still a `Decision`.

Record Subtype is selected at write time and validated against the MemoryProfile before persisting:

1. `None` is always valid on a non-supersession write and means a plain kernel record.
2. A non-empty subtype must match a declared `records[].name`.
3. The matched declaration's `extends` value must equal the kernel kind being written.

When a supersession write omits `record_type`, the successor inherits the predecessor's Record Subtype to preserve the chain's declared kind. That inherited subtype is validated against the active MemoryProfile before the successor is persisted. If the active profile has removed, renamed, or moved that subtype to a different `extends`, the supersession write fails loud instead of persisting an undeclared Record Subtype.

Kernel record writes remain valid without any profile declaration. This preserves the deliberate asymmetry with Entity and Relation writes: Entity and Relation types must be declared, while Decision, Observation, and Task remain universal kernel write paths that can be used immediately.

When present, the subtype is stored on the record, returned by read surfaces that materialize the record, and exposed as a filter in Memory Review, GraphRAG search, and truth reads. Filtering by subtype is an AND filter with the kernel record kind and other retrieval/listing filters; records without that subtype do not match.

This decision does not create generated per-subtype kernel record kinds or dynamic tools. The public model stays a small kernel plus an optional on-record label. Storage may realize the label however an adapter chooses, but core and agent-facing language is Record Subtype, not storage labels or tags.

## Consequences

Positive:

- Declared `records:` types become real: they affect writes, reads, and subtype-scoped retrieval instead of only validation and inspect output.
- v0 migration can preserve original record kinds such as `Episode`, `Pattern`, and `Commitment` as structured memory instead of flattening them into prose or provenance.
- The change is additive. Existing plain Decision, Observation, and Task writes still work with no profile declaration and no subtype.
- The MemoryProfile contract becomes more honest and closes the ADR-0017 valid-declaration no-op gap.
- This provides the stable anchor for feedback #2: custom typed fields can later attach schema and values to the same declared `records:` entry and on-record subtype label.

Negative:

- Write services and adapters must validate and persist one more record attribute across Decision, Observation, and Task.
- Retrieval and Memory Review must distinguish kernel record kind from Record Subtype so filters stay composable and errors stay understandable.
- Profile evolution now has data consequences: renaming or deleting a declared record subtype can affect future writes and filters over existing subtyped records. Superseding an existing subtyped record also requires the inherited subtype to remain declared for the same kernel kind, or the writer must choose a currently valid subtype.

## Alternatives Considered

### Option B: Generated per-type record kinds and dynamic tools

Generate separate record kinds or agent tools for each declared `records:` entry, such as `remember_episode` or `remember_commitment`.

Rejected. This is premature and hard to reverse. It expands the agent surface every time a profile changes, complicates MCP/tool discovery, and blurs the stable universal kernel. The current need is to preserve and filter a declared subtype, not to create a new lifecycle model or tool per subtype.

### Option C: Provenance or side-tag annotation

Store the original kind as provenance text, a tag, or another side annotation outside the MemoryRecord's own attributes.

Rejected. The subtype describes what the record is inside the project schema. Modeling it as provenance or a side tag puts a record attribute in the wrong place, makes validation weak or impossible, and repeats the silent-no-op failure mode ADR-0017 was designed to remove.

## Guardrails

- Record Subtype is optional; missing subtype never blocks non-supersession kernel Decision, Observation, or Task writes.
- Record Subtype must be profile-declared and must extend the kernel kind being written, including when inherited from a predecessor during supersession.
- Record Subtype is not a custom field system. Typed fields are a later additive layer on the same `records:` declaration.
- Do not infer a subtype from statement text or provenance. The Agent selects it explicitly at write time; supersession inheritance only carries the predecessor's already-declared subtype forward as lifecycle preservation.
- Keep storage vocabulary inside storage adapters. Core docs, schemas, services, CLI, and MCP surfaces should use Record Subtype / `record_type` language.
