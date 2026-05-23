# ADR 0003: Model Truth-Bearing Memory As Temporal Records

Date: 2026-05-23
Status: Accepted

## Context

Memorable needs to remember more than the latest version of a note. Agents need to know what is current, what used to be true, what was superseded, what was completed, what was corrected, and why a memory exists.

The product must support questions like:

- What do we currently believe?
- What did we believe at a previous point in time?
- Which decision superseded this one?
- When did this task become completed?
- What source produced this evidence?
- Was this record corrected, invalidated, or merely replaced by a newer interpretation?

This requires a shared temporal model for truth-bearing memory.

## Decision

Represent truth-bearing memory with a shared temporal record model.

This model applies to records such as decisions, observations, evidence, relations, rules, derived summaries, and other project-specific record types. Specialized types can add their own fields and behavior, but they should share common temporal and provenance semantics.

The temporal record model should preserve these semantic slots:

- memory space: which project or workspace owns the record;
- record type: what kind of memory this is;
- provenance: where the record came from and who or what wrote it;
- creation time: when the memory record was stored;
- validity time: when the remembered claim or state became true or applicable;
- invalidation time: when the claim or state stopped being current, if applicable;
- lifecycle state: whether the record is current, completed, corrected, invalidated, ignored, superseded, or otherwise no longer active;
- uncertainty marker: optional uncertainty metadata when it changes how the memory should be used;
- supersession links: explicit relationships to prior or later records when one memory replaces, refines, contradicts, or invalidates another.

Exact property names and allowed lifecycle values belong in implementation specs. The durable decision is that these semantics exist and are shared across truth-bearing memory.

## Append-First History

Append-first history is the source of truth.

Changing a memory should normally create an event, correction, or replacement record rather than silently overwriting the old state. Current-state fields or indexes may be denormalized for fast reads, but they are read conveniences over historical memory.

Examples:

- A new decision supersedes an older decision.
- Completing a task creates a lifecycle event and updates the task's current read model.
- Correcting a measurement preserves the original sample and records the correction.
- Replacing a rule closes the prior rule's validity and links it to the replacement.

## Consequences

Positive:

- Agents can answer current and historical questions from the same model.
- Memory remains inspectable because transitions are explicit.
- Different project profiles can share temporal behavior even when their domain types differ.
- Storage adapters can optimize current reads without losing history.

Negative:

- Writes are more structured than simple notes.
- The core must define lifecycle operations clearly.
- Queries need to distinguish current-state reads from point-in-time reconstruction.

## Guardrails

- Do not erase old truth-bearing records just because they are no longer current.
- Do not put all temporal behavior into mutable properties on entities.
- Do not require uncertainty metadata when it adds no value.
- Do not expose provenance or lifecycle metadata as repetitive chat boilerplate.

