# ADR 0023: Creation Time Is Clock-Sourced

Date: 2026-06-07
Status: Accepted
Extends: ADR 0003
References: ADR 0009

## Context

ADR 0003 defines Memorable's temporal record model with two independent time axes:

- **Validity Time** — when a remembered claim or state became true or applicable;
- **Creation Time** — when Memorable stored the memory, used for audit and write ordering.

In practice, the caller-supplied effective time has been used for both axes. That means a backdated memory also backdates Creation Time, so the audit axis does not exist as a distinct value. It also means Memory Review cannot honestly distinguish "what did I write in this window?" from "what became true in this window?"

This is drift from ADR 0003, not an open product gap. The model already says Creation Time and Validity Time are separate semantic slots. This decision records how Creation Time is sourced so the implementation and agent-facing behavior return to that model.

## Decision

Creation Time is stamped by Memorable from a system clock at the moment of the write. It is not the caller-supplied effective time.

The caller-supplied time is strictly Validity Time: when the remembered claim or state became true or applicable.

Creation Time is not caller-settable on ambient Agent or Human Owner writes. Everyday write surfaces provide no override for the audit timestamp.

Lifecycle writes that record new provenance, such as corrections, stamp Creation Time at the time of that write. Their effective time remains the caller-supplied Validity Time. Lifecycle transitions that do not record new provenance, such as invalidation and completion, are unaffected; they record validity or effective times only.

Memory Review windowing keys on Creation Time, as already documented. Making the axes distinct on write makes that contract honest. This decision does not introduce a selectable review axis for choosing between Validity Time and Creation Time.

Already-written records where Creation Time equals Validity Time are left as-is. They are not backfilled or rewritten. That equality is a documented degeneracy of pre-decision data. Rebuilding a store is preferred over rewriting data, because a data rewrite is less reversible than a rebuild.

The write-time clock must be substitutable so temporal behavior stays deterministic under test and auditable in design. This is a design constraint on the temporal model, not an ambient permission to set Creation Time through normal write surfaces.

## Relationship To Existing ADRs

This ADR extends ADR 0003 by specifying how Creation Time is sourced. It does not supersede ADR 0003; the shared temporal record model remains authoritative.

This ADR is consistent with ADR 0009. Capturing write time is temporal logic, so it belongs in domain behavior rather than storage adapters. Storage remains responsible for persistence, not for deciding temporal meaning.

## Consequences

Positive:

- Creation Time becomes a real audit and write-ordering axis.
- A Human Owner or Agent can backdate Validity Time without corrupting the audit trail.
- Memory Review can answer "what did I write this week?" distinctly from "what became true this week?"
- Corrections show both when the corrected claim is effective and when the correction was written.
- Existing records remain readable and are not silently changed.

Negative:

- The write path gains a time source where the caller-supplied effective time was previously the only time input.
- Pre-decision records may still show Creation Time equal to Validity Time, so historical audit interpretation must account for that degeneracy.
- Faithful replay of an older store's original Creation Times is not solved by everyday writes.

## Alternatives Considered

### Keep Creation Time and Validity Time conflated

Rejected. This violates ADR 0003 and makes the audit axis fictional. It prevents Memory Review from distinguishing write-order questions from validity questions.

### Caller-supplied Creation Time on ambient writes, gated by trust

Rejected for now. Giving everyday Agent or Human Owner write surfaces a way to set Creation Time places forgeable audit power on the normal path. A guarded override for faithful bulk import or restore is deferred to a future bulk import/export decision; this ADR does not foreclose that capability.

### Immutable Creation Time with no override ever

Coherent and left open as the default unless a future bulk import/export decision chooses otherwise. Validity Time alone can express when claims became true, but faithful replay of an existing store may require a separate decision.

### Backfill or rewrite existing data

Rejected. Rewriting already-written records is less reversible than rebuilding a local store and risks making audit history look more certain than it is. Existing equality between Creation Time and Validity Time is documented instead.

### Add a selectable Memory Review time axis now

Rejected for this decision. Memory Review remains keyed on Creation Time. If Agents need a separate "what became true in this window?" review mode, that should be decided deliberately later.

## Out Of Scope / Deferred

- A guarded Creation-Time override for faithful bulk import, export replay, or restore.
- A selectable Memory Review axis.
- Revisiting Episode identity derivation.
