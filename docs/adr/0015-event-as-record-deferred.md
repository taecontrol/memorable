# ADR 0015: Event-As-Record Deferred; Lifecycle Transitions Stay Mutations In V1

Date: 2026-05-30
Status: Accepted

## Context

`Event` is in the Universal Memory Kernel list and in Accepted Language ("something that happened at a point or interval in time and matters to memory... a meeting, tool result, workflow run, task completion, correction, or lifecycle transition"). The charter lists events among the core things agents remember. It is not implemented as a stored record type; the implemented truth-bearing records are Decision, Observation, Task, and Relation.

The absence has a concrete consequence. Memory Review's listing primitive (`memorable_list_records`) can enumerate records by type, lifecycle state, and creation-time window, but it structurally cannot answer "what *changed* recently." Lifecycle transitions do not create new records:

- Correction updates a record's statement in place (ADR 0011).
- Supersession marks the old record `superseded` and links it to a replacement; the transition itself is an edit plus a link, not a standalone record.
- Invalidation and task completion set lifecycle state on the existing record.

So supersession, correction, invalidation, and completion-as-an-event are invisible to a primitive that lists records by creation time. A Human Owner asking "what did we change this week?" (as opposed to "what did we create this week?") cannot be answered in V1.

Closing that gap means promoting Event into a stored, queryable kernel record that captures a transition as its own first-class thing. That is a meaningful expansion of the temporal model, not a V1 tracer-bullet concern.

## Decision

Defer Event-as-record. V1 does not implement Event as a stored record type.

Lifecycle transitions in V1 remain mutations and links on existing records, consistent with ADR 0003 (append-first history) and ADR 0011 (correction updates in place):

- correction → in-place statement update + new provenance;
- supersession → old record marked `superseded` + link to replacement;
- invalidation / completion → lifecycle-state change on the existing record.

The forcing case for revisiting: when Memory Review must answer change questions ("what was superseded / corrected / invalidated / completed recently") rather than only creation questions, Event becomes a stored kernel record and transitions emit Events. Until that need is real, the limitation stands and is documented in the Memory Review language entry and the `list_records` design.

## Consequences

Positive:

- The V1 temporal model stays small: a fixed set of truth-bearing record types, transitions expressed as edits and links. No event log to write, index, or reconcile against current-state fields.
- The Memory Review limitation has a named home. Decision #3's documented gap points here instead of being an unexplained "can't do that."
- Consistent with the mutation-in-place stance already chosen for correction (ADR 0011); V1 does not split lifecycle modeling across two paradigms.

Negative:

- "What changed recently?" is unanswerable in V1. Memory Review answers creation, not transition.
- When Event lands, transition-emitting code (correct, supersede, invalidate, complete) must be retrofitted to also write Events, and retrieval/indexing must learn the new type. The retrofit cost is accepted in exchange for not building an event log before there is a query that needs it.

## Alternatives Considered

**Implement Event-as-record in V1**: would make transitions queryable immediately and close the Memory Review gap. Rejected: it expands the kernel and the temporal model (a second lifecycle paradigm alongside mutation-in-place) for a query the single current user has not yet needed. Premature for a tracer-bullet release.

**Candidate-language note only, no ADR**: would record that Event is still forming, but not capture the architectural commitment (lifecycle-as-mutation) or the forcing case. Rejected: the deferral is a real stance with a concrete downstream limitation, which is exactly what an ADR should hold. The `Lifecycle Event` candidate-language entry already covers the "name not settled" aspect.

**Model transitions as Events now but keep them out of retrieval**: store transition Events without indexing them. Rejected: writing a record type that nothing can retrieve is the inert-feature trap ADR 0014 rejected for write policy — build the type when a query consumes it.
