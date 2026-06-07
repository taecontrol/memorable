# ADR 0022: Typed Durable Attributes On Types

Date: 2026-06-06
Status: Accepted
Refines: ADR 0002, ADR 0017, ADR 0021

## Context

A MemoryProfile can declare custom Entity types such as `Reference` or `Person`, and ADR-0017 makes those declarations fail loud when they contain keys the current profile version cannot honor. Today a declared Entity type can carry only `name` and `description`. There is no schema slot for stable structured values such as a Reference URL, medium, publication date, or aliases.

Without a declared slot, Agents must flatten those values into Entity names, statements, Source/provenance text, or generated summaries. That loses queryability and makes a valid project schema less honest than it appears: the Human Owner can name a type but cannot give that type durable structure.

This is the same profile-honesty gap closed one layer down by Record Subtypes (ADR-0021). A valid type declaration should have operational effect. The Entity slice is independent; after the post-#206 record-subtype Attribute follow-up, the same Attribute schema and validator will attach to declared Record Subtypes as well.

The change must not become a back door around Memorable's temporal core. Product principle 6 says time is part of the model, not incidental metadata. Attributes are useful only if they stay durable and do not absorb mutable status, temporal state, or kind/subtype information that belongs elsewhere.

## Decision

An **Attribute** is a typed, declared, durable value on a declared type.

Entity type declarations gain an optional `attributes:` schema in the MemoryProfile. A declaration is an ordered collection of Attribute declarations, each with `name` and `type`:

```yaml
entities:
  - name: Reference
    attributes:
      - name: url
        type: string
      - name: medium
        type: string
```

Record Subtypes reuse the same Attribute schema and validator after the post-#206 follow-up. The YAML key is `attributes:` and the domain term is **Attribute**. Any earlier informal wording about `fields:` for typed custom structure, including the #206/Record Subtype follow-up discussion, is superseded.

### Durable-only boundary

Attributes describe stable facts about the Entity or declared type instance. They are changeable only by Correction or by an explicit Attribute-changing write path; they are never silently mutable current state. Re-remembering an Entity without Attributes must not wipe existing Attributes.

Routing rules are load-bearing:

- mutable status goes to Lifecycle State;
- when a claim became true goes to Validity Time;
- what kind of thing something is goes to `entity_type` for Entities or Record Subtype for records;
- values that genuinely vary over time, such as a person's role in an organization, go to a Relation.

The write path must not absorb those concerns as Attributes.

### Attribute schema and validation

The v1 Attribute type set is:

- `string`
- `number`
- `date`
- `list[string]`

All Attributes are optional in v1. There is no `required` flag and no defaults. Widening the allowed type set is a profile-versioned change; a parser must not silently loosen validation for the same profile version.

Profile loading follows ADR-0017: an unknown Attribute type fails loud with a domain-language error naming the allowed types, and unknown keys under an Attribute declaration fail loud instead of being ignored.

Write and filter paths use one storage-free Attribute schema validator. The validator takes a declared Attribute schema plus provided values and either returns validated/coerced values or raises a domain error. It rejects undeclared Attribute names, rejects values whose shape does not match the declared type, and accepts omitted declared Attributes.

### Storage boundary

Attributes persist as native graph node properties inside the Neo4j adapter. Any naming, prefixing, encoding, or collision avoidance is a storage concern hidden inside that adapter.

Core ports, services, CLI, MCP, and product docs expose only the domain contract: a type may carry optional typed Attributes, and Entities can be filtered by Attribute equality. They must not expose Neo4j property vocabulary as the domain model.

### Retrieval boundary

Attributes are surfaced wherever an Entity is read back, and they are usable as equality filters in retrieval/search. Attribute filters are profile-aware and validated against declared Attribute schemas.

Attributes are not embedded into Indexable Text in v1 and do not require an Embedding or Indexable Text version change. They are canonical typed values that retrieval can surface and filter by, not derived retrieval prose.

### Relationship to existing ADRs

This ADR specializes ADR-0002: a MemoryProfile specializes the universal kernel by declaring project-specific structure. Attributes are one such project-specific structure.

This ADR reuses ADR-0017: profile validation fails loud for unknown keys, unknown Attribute types, and declarations the current profile version cannot honor.

This ADR builds on ADR-0021: Record Subtype gives records a declared schema anchor; the post-#206 Attribute follow-up reuses this ADR's schema and validator for those subtypes.

## Consequences

Positive:

- Declared Entity types can carry real durable structure instead of forcing Agents to flatten values into prose or provenance.
- Agents can query Entities by declared Attribute equality, such as `medium = video`.
- Profile validation remains honest: unsupported Attribute shapes fail at load or write time instead of becoming silent no-ops.
- The same Attribute schema and validator become the foundation for Record Subtype Attributes after the post-#206 follow-up.
- Storage vocabulary stays contained in the adapter while agent-facing surfaces use MemoryProfile, Entity, Record Subtype, and Attribute language.

Negative:

- Write services, storage adapters, retrieval results, CLI, MCP, and inspect/profile output must all preserve and surface one more piece of Entity structure.
- Profile evolution has data consequences: renaming or deleting an Attribute affects future writes and filters over existing Entities.
- Attribute filters must account for ambiguous declarations, such as the same Attribute name on multiple Entity types with incompatible types, and fail loud rather than guessing.

Guardrails:

- Do not model mutable current state as an Attribute.
- Do not model time-varying values as Attributes; use Relation.
- Do not treat Attributes as Source/provenance text, generated Markdown, Indexable Text, or Neo4j properties in core language.
- Do not introduce new Attribute types without a profile version change.

## Alternatives Considered

### Free-form key/value bag

Let Agents attach arbitrary key/value pairs to Entities without declaring them in the MemoryProfile.

Rejected. This would let mutable status and temporal state bypass Lifecycle State, Validity Time, Relation, and Correction. It would also recreate the schema-less notes product Memorable explicitly is not, and it would undo ADR-0017's fail-loud profile honesty.

### First-class temporal Attribute claims / graph EAV

Model every Attribute value as its own temporal claim with its own validity, provenance, and lifecycle semantics.

Rejected for v1. This is powerful, but it is heavy and over-engineered for durable values such as URL, ISO date, medium, and aliases. The alternative is still valuable because it names the temporal case: if a value genuinely varies over time, it is not an Attribute in this ADR and should be modeled as a Relation or another temporal MemoryRecord.

### Generated per-type Pydantic models and dynamic tooling

Generate runtime models and per-type tool schemas from each MemoryProfile declaration.

Rejected. This has the most moving parts and is the least reversible. It expands the agent surface every time a profile changes and repeats the dynamic-tooling alternative rejected for Record Subtypes in ADR-0021. The current need is a stable kernel plus declared, validated Attributes, not generated tools or new model classes per project type.
