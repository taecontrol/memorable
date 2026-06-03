# ADR 0019: Forget — The Sanctioned Exception To Append-First History

Date: 2026-06-03
Status: Accepted

## Context

Memorable's temporal model is append-first (Append-First History; ADR 0003): meaningful change creates a new event, correction, or replacement record rather than erasing the previous state. The lifecycle operations all honor this:

- **invalidate** — the claim is no longer true; the record stays, marked invalidated.
- **supersede** — the claim was true then and is replaced now; both records stay, linked.
- **correct** — the claim was never true; ADR 0011 updates it in place, but the record node still persists with the same id.

None of these erase. There is deliberately no removal path for a record, and Entities have no removal path at all. The 0.0.3 feedback (finding #7) surfaced the cost: when a Human Owner or Agent exercises Memorable — testing writes, trying entity/relation declarations, generating scratch records — that test and scratch memory accumulates permanently in the MemorySpace with no cleanup path short of resetting the whole space. PRD #157 records the demand: surgical, per-id removal, not a whole-space reset.

This is a genuinely different need from every existing lifecycle operation. invalidate/supersede/correct all answer "how did this true-at-some-point memory evolve?" The cleanup need answers "this should never have been remembered at all — remove it as if it never happened." Expressing that with a lifecycle transition would be a lie: a `forgotten` lifecycle state is a tombstone, which is soft-delete, which preserves the very thing the Human wants gone.

The forces:

- **Cleanup is real and per-id.** The Human Owner explicitly chose surgical per-record/per-entity deletion over a space-level reset.
- **Append-first integrity is load-bearing.** It is the reason point-in-time queries are trustworthy and history is safe. Erasure is in direct tension with it.
- **Entities are connected.** An Entity is the endpoint of Relations (ADR 0012) and the target of About edges (ADR 0018). Those cannot meaningfully outlive the Entity.
- **Two actors, two trust levels.** A CLI puts erasure in the Human Owner's hands ("Humans own the memory"). An MCP tool hands the same erasure to Agents — the actor append-first was partly designed to keep honest.

## Decision

Introduce **Forget**: an explicit hard delete, addressed by id and scoped to one MemorySpace, that erases a target and its provenance as if it had never been remembered. Forget is ratified as the **single sanctioned exception to Append-First History**.

### Forget is erasure, not a lifecycle transition

Forget removes the target node. It is not a new lifecycle state and creates no tombstone. The contrast is the whole point:

| Operation | Meaning | History |
| --- | --- | --- |
| invalidate | "no longer true" | preserved (record stays, marked) |
| supersede | "replaced by newer truth" | preserved (both records, linked) |
| correct | "was wrong" | record persists in place (ADR 0011) |
| **forget** | **"should never have been remembered at all"** | **erased — nothing remains** |

invalidate/supersede/correct are how true-at-some-point memory evolves. Forget is how memory that should not exist is removed. Keeping Forget **explicitly named, separately surfaced, and ADR-ratified is precisely what keeps the rest of the model honestly append-first** — erasure is a walled-off, deliberate act, not a general mutation capability leaking into normal operations.

This is the second, more severe departure from pure append-first. ADR 0011 was the first (correct mutates in place, but the record persists). The gradient is now explicit: `correct` (mutate in place, record survives) ≺ `forget` (erase, record gone). Future contributors must read both as exceptions, not patterns.

### Authoritative term: `Forget`

`Forget` is chosen over `Delete`/`Purge` for the Remember/Forget symmetry — it is the deliberate antonym of the write operation and reads as a memory act, not a storage act. It is added to `docs/ubiquitous-language.md` as Candidate Language (the decision is ratified here; the term stays candidate until it has a write path), contrasted with invalidate/correct/supersede.

### Entity-deletion cascade

Forgetting an Entity **cascades**:

- The Entity node is removed.
- Every **Relation** with that Entity as source or target is removed in full — the Relation node, its provenance, and its structural edges (ADR 0012) — including Relations that sit in their own supersession chains (see Supersession chains below). A Relation to a non-existent Entity violates Relation's own "connection between two Entities" invariant; it cannot meaningfully survive its endpoint.
- Every **About edge** targeting that Entity is removed (ADR 0018). This removes the *edge only*. The records on the other end are independent memory and **survive** — they simply lose one membership edge.

The destructive reach is stated plainly: **forgetting an Entity erases truth-bearing Relations, not just the Entity.** This is the cost of cascade and is accepted because the motivating use case is test/scratch cleanup, where refuse-and-list-dependents (the safer alternative) is tedious friction with no payoff. The About-edge cascade carries no philosophical cost — ADR 0018 already hard-removes About edges when wrong, so removing them when their target is forgotten is consistent.

### Record-forget scope

Forgetting a record (Decision, Observation, Task) removes:

- the record node,
- its provenance,
- its outgoing About edges (the membership edges *from* that record).

It does **not** touch the Entities the record was about — those are independent and survive. Removing the About edges removes membership, not the Entities.

### Supersession chains — refuse, fail loud

Direct record-forget **refuses** when the target participates in a supersession chain — it supersedes another record or is superseded by one. The error names the chain (what the target supersedes, what supersedes the target) and directs the Human to resolve it first. Forget does not strip pointers, strand a predecessor, or relink the chain.

The rationale: a record woven into a supersession chain is by definition *evolved real history* — the opposite of the test/scratch memory Forget exists to clean up. Stranding a predecessor (left `superseded` with no successor, invisible to Current Truth) or dangling a successor's back-pointer would silently corrupt lifecycle state, against the fail-loud posture (ADR 0017, #162). And unlike a Relation whose endpoint Entity is gone, a stranded predecessor is still valid history — it was true in its window — so it is not a meaningless dependent that may be erased. Refusing keeps the surgical path honest: if the Human truly wants chained records gone, they forget the chain members deliberately.

This refusal is scoped to **direct record-forget**. The Entity-forget cascade is the explicitly-destructive path and erases referencing Relations wholesale, including any that sit in their own supersession chains — the Entity is gone, so those Relations are structurally invalid regardless of chain membership.

### Invariants

- **Fail loud on miss.** Forgetting an id absent from the space raises an actionable domain error ("nothing to forget in this space with that id"), never a silent no-op. Consistent with fail-loud profile validation (ADR 0017) and the duplicate-id domain error (#162).
- **Single-space confinement.** Forget addresses `(space, id)`. It can only erase within the named MemorySpace; cross-space erasure is impossible by construction. An identically-id'd record in another space is untouched.

### Surfaces

- **CLI is in scope** (`memorable forget …`), reflecting "Humans own the memory" and making the destructive act a human-driven one.
- **MCP is exposed, ungated** (`memorable_forget_*`), giving full Remember/Forget symmetry. This is the highest-trust-cost surface: an Agent can erase memory with no confirmation, and via the Entity cascade a single call can remove an Entity plus every Relation and About edge touching it.

The trust cost is accepted because three guardrails bound it: Forget is **id-addressed** (no wildcards or bulk erasure), **single-space confined**, and **fail-loud**. These are what make ungated MCP tolerable rather than reckless; if any were absent, MCP exposure would be reckless. The cheap walk-back, if the Entity cascade proves dangerous in practice, is to gate Entity-forget alone while leaving record-forget ungated.

### Storage

The destructive delete lives behind a core port, implemented in both the Neo4j adapter and the in-memory adapter (for testability). The destructive Cypher stays inside the storage context; core and agent-facing language say "forget," not "DETACH DELETE."

## Consequences

Positive:

- The cleanup need is met surgically and per-id, without a whole-space reset.
- Append-first stays honest *because* erasure is one named, walled-off, ratified exception rather than an ambient mutation capability. The exception is documented next to the rule it breaks.
- The cascade keeps the graph referentially valid: no Relation survives a missing endpoint, no About edge survives a missing target.
- Remember/Forget symmetry gives Agents a complete test-exercise loop (write, then clean up) without space resets.

Negative:

- **Forgetting an Entity erases truth-bearing Relations and their history.** This is the largest blast radius in the system, and via ungated MCP it is reachable by the non-human actor with no confirmation. Accepted, bounded by the three guardrails, with a known walk-back.
- **No undo.** Forget is erasure; soft-delete, recycle-bin, and recovery are explicitly out of scope. A mistaken Forget is unrecoverable.
- **Forget refuses on records in a supersession chain.** Cleaning up a record that turns out to be woven into real history takes an explicit extra step (resolve or forget the chain members first). Accepted as the cost of never silently corrupting lifecycle state.
- A third departure-from-default now exists in the temporal model (after correct-in-place); contributors must hold "invalidate/supersede/correct preserve, forget erases" clearly.

## Alternatives Considered

**Refuse-and-list-dependents on Entity forget.** Forgetting an Entity with Relations or About edges fails and lists the dependents for the Human to remove first. Safer — no surprise erasure of Relations — but tedious for the test-cleanup use case that motivated this, turning one cleanup into a manual dependency walk. Rejected in favor of cascade, with the destructiveness documented.

**Name it `Delete` or `Purge`.** Blunter about permanence, which has merit for a destructive op. Rejected for `Forget` because the Remember/Forget symmetry makes it a memory act in the product's own language, and the ubiquitous-language contrast with invalidate/correct/supersede carries the "this is different and dangerous" weight without leaking storage vocabulary.

**Soft-delete / `forgotten` lifecycle state (tombstone).** Reversible, audit-friendly. Rejected because it preserves exactly what the Human wants gone — scratch and test memory would still pollute the space and retrieval — and it is append-first by another name, not the erasure the need calls for. Recovery of forgotten memory is a non-goal.

**CLI-only, defer MCP.** Most conservative on trust posture; keeps erasure in human hands. Rejected here in favor of ungated MCP for full symmetry and the agent-testing loop, accepting the trust cost under the three guardrails. The reversal path (gate or remove MCP exposure) is cheap if needed.

**Whole-space reset / bulk purge.** Simpler to build than per-id removal. Rejected by the Human Owner directly: the need is surgical removal of a specific record or Entity, not nuking the space.

## Reconsideration Trigger

Revisit if:

- the Entity cascade erasing Relations proves too destructive in practice — the walk-back is to gate Entity-forget (refuse-and-list, or a confirmation) while leaving record-forget ungated;
- ungated MCP erasure causes real loss of non-scratch memory — gate or withdraw the MCP surface;
- refusing on supersession chains proves too restrictive for real cleanup — revisit with explicit chain-repair (relink/revive) semantics or an opt-in cascade-the-chain flag;
- a recovery/undo need emerges that erasure cannot serve — reopen the soft-delete question deliberately, as a new exception, not by widening Forget.
