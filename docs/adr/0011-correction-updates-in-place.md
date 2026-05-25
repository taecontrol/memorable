# ADR 0011: Correction Updates Records In Place

Date: 2026-05-25
Status: Accepted

## Context

ADR 0003 establishes append-first history as the default: meaningful changes create a new event, correction, or replacement record rather than erasing the previous state. This works well for supersession, where both the old and new records were true at different times and point-in-time queries should return the old record for its validity window.

Correction is different. A corrected record was never true — it was a mistake. Preserving it as a separate record creates problems:

- Point-in-time queries must add branching logic to skip corrected records (they were never valid during their window).
- The graph accumulates dead-end records that were never true, cluttering retrieval.
- Agents may accidentally surface corrected records despite them being wrong.
- The distinction between "was true then" (supersession) and "was never true" (correction) is lost if both create new records with different lifecycle states.

The system currently maintains one Provenance entry per record. Changing this invariant to support correction history would require refactoring all repository ports, storage adapters, and temporal services across all existing record types.

## Decision

Correction updates the record's statement in place rather than creating a new record.

When an agent corrects a record:

1. The record's statement is updated to the corrected value.
2. The record's provenance is replaced with new provenance reflecting the correction source, writer, and reason.
3. The previous statement is captured in the new provenance's `reason` field (e.g., "Corrected from: 'API rate limit is 100/s'. Original was based on outdated docs.").
4. The record retains its original `id`, `space`, `validity_time`, and `lifecycle_state` (remains `current`).

Supersession continues to follow append-first semantics: a new record is created, and the old record is marked `superseded` with a link to its replacement.

The distinction:

- **Supersession**: the old record was true at the time. Create a new record. Old record remains visible in point-in-time queries for its validity window.
- **Correction**: the old record was never true. Update in place. No ghost record in the graph. Point-in-time queries return the corrected value.

## Consequences

Positive:

- Point-in-time queries remain simple: every visible record was believed true during its window.
- No orphaned "never true" records in retrieval indexes.
- One Provenance per record invariant is preserved. No refactoring of existing repository ports.
- The `reason` field on provenance provides a human-readable audit trail of what was corrected.
- Generic `memorable_correct` tool works the same way for all temporal record types.

Negative:

- Structured history of corrections is lost. Only the most recent correction reason is preserved, not a full chain of previous values.
- The original provenance (who first wrote the mistaken record) is overwritten. If tracing the source of mistakes matters, this information must be reconstructed from the reason text.
- This is a deliberate departure from ADR 0003's append-first default. Future contributors must understand that correction is the exception, not a general pattern for mutation.

## Alternatives Considered

**Append a new record with lifecycle_state "corrected"**: Consistent with ADR 0003 but creates dead-end records that were never true. Point-in-time queries need special logic to skip them. Complicates retrieval.

**Multiple provenance entries per record**: Would preserve full correction history in structured form. Requires refactoring all repository ports (`get_provenance` becomes `get_provenance_history`), all storage adapters, and all temporal services. Large scope for a feature that can start simple.

**Separate correction event records**: Store corrections as Event records that reference the corrected observation. Preserves audit history without changing the provenance model. But Event is not yet implemented, and this adds a dependency on another unbuilt record type.
