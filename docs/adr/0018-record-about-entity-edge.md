# ADR 0018: Records Link To The Entities They Are About

Date: 2026-05-30
Status: Accepted

## Context

A user built a real MemorySpace (triathlon training) by designing a `memory.yaml` from the docs, then diffed it against the source. ~95% of the content was records (daily logs, session results, decisions); a handful were Entities (the race, the phase, two devices). The carefully-designed entity schema did **no retrieval work**, because there is no way to connect a record to the Entity it is about.

Today the model links only:

- **record → record** via supersession;
- **Entity → Entity** via Relation (ADR-0012);
- record → provenance.

There is no record → Entity link. `remember_decision`/`remember_observation`/`remember_task` accept no `about`/`entities` parameter, and the UL's Relation entry explicitly forbids using Relation for it ("Do not use Relation to connect Entities to Records … those connections are handled by semantic retrieval and shared MemorySpace membership"). So the entity graph and the record corpus are two disconnected layers.

Two distinct problems follow, and both consume the same missing edge:

1. **Completeness (the forcing case).** A Human Owner or agent cannot ask "every record about Build 2" and trust the answer. Semantic search returns *similar* records, never a *complete* set, and silently misses records that don't share vocabulary. This is the prize: an exact, complete enumeration is a query semantic search structurally cannot guarantee.

2. **Retrieval quality.** GraphRAG graph-expansion (ADR-0007) is supposed to walk from a semantic hit to related memory. For records it can't reach "the Entity it is about" — no such edge exists. Worse, the current heuristic (`retrieval/service.py`, `_graph_expand`) expands every Decision/Observation/Task to **all** Entities in the space. That is not a starved graph; it is a noisy one — it trips ADR-0007's own reconsideration trigger, "graph expansion adds noise instead of improving agent context."

A cheaper alternative — free-form **tags** (`#build2`) — was rejected. For a *completeness* prize, fuzzy identity is fatal: "Build 2", "build-2", "Build2" fragment into three tags but one Entity. An Entity is a governed identity (declared type, enforced at write, carries provenance and Relations); a tag is ungoverned free text and an island. Completeness forces the Entity edge.

## Decision

Add an optional **"about" edge** from a MemoryRecord to one or more Entities. "About" is **membership/aboutness, not a truth-bearing claim**, and is deliberately distinct from Relation.

**Distinct from Relation, not a generalization of it.** A Relation is a truth-bearing claim between two Entities ("Build 2 `part_of` 10K race") that can be wrong and can be superseded as the claim evolves while both Entities persist. "About" asserts nothing that can evolve: a note is about what it is about. Generalizing Relation to allow a Record endpoint would smear two semantics together, gut the UL definition ("connection between two Entities"), and break the `relation_type` contract and `Relation.__post_init__`.

**Fields-free edge.** The edge carries no temporal or lifecycle fields — no `validity_time`, `invalidation_time`, `lifecycle_state`, `supersedes`, or `superseded_by`, and no provenance row of its own. All temporal weight stays on the record, which already has a `validity_time`. The edge is `(record_id, entity_id)` and nothing more. It is deep precisely because it is empty; this is the guardrail that keeps "about" from becoming Relation-with-extra-steps.

**Correctable, not superseded; hard remove.** A wrong edge was wrong from creation. Fixing it is correction (ADR-0011, in place), not a temporal chain. Correcting a mis-stapled edge hard-removes it — append-first history applies to truth claims whose evolution matters, not to membership. If a record's subject genuinely changed, that is a new record, not an evolving edge.

Correction applies uniformly to every correctable record kind that carries About — Decision, Observation, and Task (Relation has no About edge). Re-staple is **about-only by default**: the new statement is optional when `about` is supplied, because fixing a mis-stapled edge is a membership fix, not a statement correction. Supplying both corrects the statement and re-staples in one call; supplying neither is an error.

**Shape.**

- **Cardinality:** one record → many Entities (`about: [entity_ids]`). One Entity → many records falls out as the completeness query.
- **Direction:** record → Entity only. "Records about X" is answered by querying edges, not by a reverse list stored on the Entity.
- **Untyped:** a single "about" edge, no kinds of aboutness. Typed connections are Relations between Entities, not this.

**Enforcement: referential integrity only.** The target Entity must already exist or the write fails loud (`ValueError`), consistent with the Entity/Relation enforcement asymmetry and ADR-0017. There is no edge type to declare — governance happened once, when the Entity was created. An agent must `remember_entity` before stapling a record to it; that friction is the cost of the completeness prize.

**Agent surface: parameter, not primitive.** `about` is an optional parameter on `remember_decision`/`remember_observation`/`remember_task`, never its own `remember_about` tool. Correcting edges folds into the existing correction operation — including for Tasks, since the correction service is generic over record kind and needs no per-kind variant. The "what must I declare" contract is unchanged — still only entity types and relation types — and gains one referential rule.

**Retrieval contract — two consumers:**

- **Memory Review:** add an `about: entity_id` filter to the existing listing primitive (`memorable_list_records`). Not a standalone `records_for_entity` tool — that would violate the UL rule that Memory Review is one composable primitive, not a family of question-specific tools, and would lose the free combinations ("open tasks about Build 2," "decisions about Build 2 changed this month").
- **GraphRAG expansion:** delete the all-Entities heuristic. A record expands to the Entities it is about (plus its supersession chain); an Entity expands to records about it (plus its existing Relation traversal); a record with no `about` edges expands to no Entities. No fallback to "all entities," which would re-import the noise.

## Consequences

Positive:

- The completeness query becomes exact and complete, which semantic search cannot guarantee.
- The noisy all-Entities expansion is replaced by a precise signal; ADR-0007's noise trigger stops firing.
- The entity schema earns its keep: linked records retrieve better, giving agents a reason to use `about`.
- The kernel grows by one concept that is *simpler* than Relation (no type, no lifecycle), not a symmetric cost.
- Additive, optional, reversible. Records can still be written with no `about` edge; existing memory is unaffected.

Negative:

- Agents must create the Entity before linking — real authoring friction, accepted as the price of completeness.
- Until agents adopt `about`, graph expansion gets *quieter* (fewer Entities surface) before it gets *better*. Quiet-and-right is preferred over loud-and-noisy, but it is a behavior change.
- A second structural-write concept exists in the kernel, though it rides on existing record primitives rather than adding a new one.

## Alternatives Considered

**Free-form tags (wishlist #11).** Cheaper to author, no Entity to pre-create. Rejected: fuzzy string identity fragments the completeness query, tags are ungoverned (the silent-no-op footgun ADR-0017 fights), and a tag cannot also be a Relation endpoint. Convenience at the cost of the prize.

**Generalize Relation to allow a Record endpoint.** Reuses the ADR-0012 machinery. Rejected: conflates a truth-bearing claim with membership, breaks the "two Entities" definition and the `relation_type` contract, and would force a meaningless type onto every "about" edge.

**Give the edge temporal/lifecycle fields.** Would make aboutness "evolve over time." Rejected: aboutness has no independent timeline — the record already carries `validity_time`. A second clock with nothing to drive it; correction (hard remove) covers the only real change, a mistake.

**Standalone `records_for_entity` tool.** Direct, obvious. Rejected: violates the one-composable-primitive rule for Memory Review and loses filter combinations that fall out of extending the existing primitive.

**Append-first history on the edge.** Preserve removed edges as tombstones. Rejected: a mis-stapled note has no historical value once unstapled; append-first exists for truth claims, not membership. Gold-plating the completeness query will never read.

## Reconsideration Trigger

Revisit if:

- a need emerges for *typed* record→Entity connections (e.g. "measures" vs "mentions"), which would mean "about" was too flat;
- aboutness is found to genuinely change over time in a way correction cannot express, reopening the temporal-fields question;
- the referential-integrity-only rule proves too weak and `about` targets need profile-declared constraints.

## Implementation Notes

Added 2026-05-31 during #127 implementation (PR #142). These clarify consequences that surfaced while building; they do not change the decision.

- **`:Record` supertype label.** Every MemoryRecord (Decision, Observation, Task, Relation) is stored with a shared `:Record` label in addition to its type label, under a MemoryRecord-wide `record_space_id_unique` (space, id) constraint. The About edge and the `about` filter query the `:Record` supertype, so all record types are treated uniformly and record ids cannot collide across types. This is the storage realization of "MemoryRecord" as the supertype of the four record kinds.
- **Correcting an About edge rewrites the record's provenance.** Consistent with "fixing it is correction (ADR-0011, in place)": the edge carries no provenance of its own, so the correction trail lives on the record. An About-only correction (membership changed, statement unchanged) still replaces the record's provenance with the correction source, and reports equal old/new statements. This is intended, not a leak of Relation-style semantics onto the edge.
- **Pre-existing records are not back-labelled (known gap).** Records written before the `:Record` label landed carry only their type label, so they are invisible to About writes and queries — a re-staple `MATCH (record:Record …)` matches nothing and silently no-ops, which is a fail-loud violation (ADR-0017) reachable only on graphs that predate the feature. A one-shot `:Record` backfill migration (explicit, idempotent, outside the schema-DDL bootstrap) is required before About works on such a graph; deferred as a follow-up rather than smuggled into `ensure_all_constraints`. New records are unaffected.
