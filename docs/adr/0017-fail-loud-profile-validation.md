# ADR 0017: Fail-Loud Profile Validation

Date: 2026-05-30
Status: Accepted

## Context

A user designed a `memory.yaml` from the public docs (`README.md` + `docs/ubiquitous-language.md`), validated it, reported success, and only discovered by reading the source that most of it did nothing. The profile parser (`src/memorable/core/profile.py`) reads `version`, `space.{name,description}`, `entities[].name`, `relations[].name`, and `records[].{name,extends}` — and **silently drops everything else**. Two concrete traps follow:

- **Unknown keys are dropped.** `description:` on an entity, a `write_policy:` block, `metrics:`/`workflows:`/`common_queries:` (all present in ADR-0002's provisional sketch) parse to nothing with no error. "I added a block" and "I imagined a block" are indistinguishable.
- **`extends` validates against names with no write path.** `KERNEL_RECORD_TYPES` lists `Measurement`, `Event`, `Evidence`, and `DerivedMemory`, so `extends: Measurement` passes validation — but there is no model, repository, or write tool for any of them. The docs actively steer numeric memory toward Measurement, so a reader declares it, it validates, and nothing can ever be written as it.

Memorable is an MCP server for coding agents. A silent no-op gives an agent **no feedback signal to self-correct**: it confidently builds a schema on sand and reports success. ADR-0014 (write policy removed) chose, at the time, to let a stray `write_policy:` key be "tolerated and silently ignored on load." That conservative choice predates fail-loud as a stated policy and is the same failure mode the feedback indicts.

This is in tension with two ADR-0002 guardrails — "profiles can evolve" and "a missing type should not block useful memory." Both still hold: profile *evolution* is governed by the `version` field (a v1 parser rejecting an unknown v1 key is correct; new keys ship under a later version), and the "missing type" guardrail is about *writes* falling back to Observation, not about accepting a profile *declaration* that does nothing. Rejecting a bad declaration at load time blocks no memory write.

## Decision

Profile loading fails loud. A profile that declares something the build cannot honor does not load; it raises `ProfileValidationError` with an actionable, domain-language message.

Three rules, all enforced in `load_profile_from_yaml`:

1. **Reject unknown keys**, top-level and per-entry, version-gated. The v1 allowed-key set is:
   - top-level: `version`, `space`, `entities`, `relations`, `records`
   - `space`: `name`, `description`
   - `entities[]` / `relations[]`: `name`, `description`
   - `records[]`: `name`, `extends`, `description`

   Any other key fails validation. Known-dead keys get a targeted message: `write_policy` → "removed in v1 (ADR-0014); remove this block"; `metrics`/`workflows`/`common_queries` → "part of the target design but not yet a parsed key (ADR-0002 sketch)". Forward-compatible additions arrive by bumping `version`, not by silent tolerance.

2. **`extends` is required and must name a Writable Record Type.** Valid set: `Decision`, `Observation`, `Task`. The previous default of `MemoryRecord` is removed (`MemoryRecord` has no write path), and structural `Relation` is not a valid `extends` target from a `records:` declaration. Extending a non-writable Kernel Vocabulary term (`Measurement`, `Event`, `Evidence`, `DerivedMemory`) fails with a message naming the writable alternatives.

3. **`description` is stored on entity, relation, and record declarations.** It is parsed, kept on the declaration, and surfaced in `inspect`/MCP profile output, exactly as `space.description` already is. It is **type documentation, not instance retrieval input** — it is not wired into Indexable Text for entity instances or records in this change; doing so is a separate write-path decision. The docs must not claim otherwise.

These rest on a language distinction ratified here and added to the ubiquitous language: **Writable Record Type** (Decision/Observation/Task — has a write path today) versus the broader **Universal Memory Kernel vocabulary**, which also names not-yet-writable concepts (Evidence, Measurement, Event, DerivedMemory). The line moves: when a vocabulary term gains a write path it becomes a Writable Record Type and a valid `extends` target.

### Amends ADR-0014

ADR-0014 decided a stray `write_policy:` key is "tolerated and silently ignored on load (no parse failure)." This ADR reverses that clause: `write_policy` is now rejected at load with a message pointing to ADR-0014. The rest of ADR-0014 (removal of the dataclass, parsing, and inspect/MCP surfaces) stands. Rationale: silent tolerance is the exact footgun fail-loud exists to remove, and an error that says "this was removed, delete it" is more helpful than a silent drop.

### Supersedes ADR-0002's provisional sketch

ADR-0002's "Initial Profile Shape" YAML is a provisional sketch that shows `write_policy`, `metrics`, `workflows`, and `common_queries`, and uses `extends: Evidence` / `extends: DerivedMemory` / `extends: MemoryRecord`. Under this ADR every one of those would now fail validation. The sketch is annotated as superseded for parsing purposes; the durable part of ADR-0002 (a profile specializes the kernel; the YAML schema evolves) is unchanged.

## Consequences

Positive:

- Agents get a self-correction signal. A bad profile produces an actionable error instead of a false success, which is worth more to agent usability than any prose edit.
- The docs and the build can be reconciled to one honest contract: declare only what the build can honor.
- `description` stops being silently discarded on the declarations authors most want to document.

Negative:

- Existing hand-written profiles that carry a now-rejected key (`write_policy` from the old scaffold, or any speculative block) will fail to load until the key is removed. The error message says exactly what to delete, and the current scaffold no longer emits `write_policy`, so blast radius is small at v0.0.x.
- `extends` becoming required and `MemoryRecord`/`Relation`/non-writable targets becoming invalid breaks profiles that used them. This is intentional: those declarations never produced a writable type.

## Guardrails

- Validation failures use domain language only — no storage vocabulary — and name the fix.
- The allowed-key set is versioned. Growing the schema means a new `version`, not loosening rejection.
- `description` storage is type documentation. Wiring it into retrieval is a separate, later decision and must not be implied as done.
