# ADR 0016: Uniform Live-Command Config Resolution

Date: 2026-05-30
Status: Accepted
Refines: ADR 0010

## Context

ADR 0010 introduced three-layer runtime configuration. Non-secret environment
overrides (e.g. the Neo4j URI supplied as a process variable) may or may not be
honoured depending on the command; secrets are always honoured.

This was applied inconsistently across live commands:

- `memorable doctor` and the MCP server resolved config with non-secret
  environment overrides honoured.
- `memorable init`, `memorable db start/stop`, and the other commands that act
  on a real runtime ignored non-secret environment overrides.

When automation supplied environment overrides, `doctor` diagnosed one runtime
while `init` acted on another. `doctor` could report on the Neo4j at the
override endpoint while `init` bootstrapped schema against the non-override
endpoint — the tool that diagnoses a problem pointed at a different runtime than
the tool that repairs it.

## Decision

Live-command config resolution is uniform. Every command that observes or acts
on a real runtime — `doctor`, the MCP server, `init`, the `db` container
commands, and any command that builds a production context — resolves config the
same way and honours non-secret environment overrides.

Exception: `memorable db status` ignores non-secret environment overrides. It
reports the file-resolved configuration and the source of each value; applying
process overrides there would report a runtime no command actually uses.

Secrets resolution is unchanged: secrets are always resolved from the
environment regardless of this policy.

## Consequences

Positive:

- `doctor` diagnoses exactly the runtime that `init` and the other live commands
  act on. Diagnosis and repair agree.
- Automation can drive every live command through environment overrides
  uniformly, without per-command surprises.

Negative:

- A stray environment override now influences more commands. Mitigated by
  `memorable db status`, which reports each value's source so an unexpected
  override is visible.

## Alternatives Considered

### Document the divergence instead of fixing it

Leave `init`/`db` ignoring overrides and document that `doctor` may diagnose a
different runtime. Rejected: it preserves the exact footgun this ADR removes — a
diagnostic that reports on a different runtime than its sibling commands use.

### Always honour overrides everywhere, with no exception

Honour non-secret environment overrides in every command without exception.
Rejected: `memorable db status` legitimately needs to report the file-resolved
configuration so an operator can see what is configured independent of any
process overrides.

## Reconsideration Trigger

Revisit if a future live command needs file-only resolution (like `db status`),
or if honouring overrides everywhere without exception becomes simpler than
maintaining the distinction.

## Amendment (2026-05-31): Live MemoryProfile Resolution

This ADR established uniform live resolution for runtime *config*. The same
policy now extends to the **MemoryProfile** (`.memorable/memory.yaml`).

### Context

The CLI already resolves the profile live: each command is a fresh process that
reads `memory.yaml` on startup. The MCP server does not — it is long-lived and
caches the parsed profile per MemorySpace for the life of the process, so it
never sees later edits to the file. The two config files in the same
`.memorable/` directory therefore behave inconsistently over MCP: `runtime.yaml`
is honoured per call (e.g. `doctor` resolves it live), while `memory.yaml` is
frozen at server start.

The visible failure: a Human/Agent declares a new Entity or Relation type in
`memory.yaml`, then asks the Agent to remember that type, and the write keeps
failing with an undeclared-type error until the server restarts. This breaks the
documented evolve loop (ADR-0002 amendment: edit YAML → undeclared-type error
invites evolution → retry succeeds); over MCP the retry never succeeds.

### Decision

The MemoryProfile is resolved **live per operation**, in parity with runtime
config. Every MCP tool call reads and validates `memory.yaml` (or the built-in
default) fresh; no profile is cached across operations.

- **No reload/force surface.** No `profile reload`, no `init --force`, no MCP
  reload tool. With live read there is nothing to reload, and `init` /
  `init_space` on an existing space stay no-ops that never overwrite a
  hand-edited profile (ADR-0002).
- **Per-call validation is a feature, not a cost** (ADR-0017). A malformed edit
  fails loud on the next call, giving the Agent a self-correction signal, rather
  than silently running on a stale-but-valid cached profile.
- **Within-operation consistency.** A tool call resolves the profile once at the
  start and uses that instance for the whole operation, so one operation never
  straddles two profile versions.
- **Live = read on demand.** No mtime tracking, watcher, or push-based refresh.
  One small read + parse per call is negligible next to the Neo4j round-trips and
  embedding calls in the same operation.

### Consequences

Positive: the evolve loop works over MCP without a restart; the two
`.memorable/` config files behave consistently; a bad profile edit fails loud
immediately.

Negative: a tiny read + parse on every tool call — negligible at agent/human
interaction pace.

The durable risk this guards against is reintroduction: any future caching of
the profile across operations — for instance alongside a reused storage
connection — would silently restore the stale-profile footgun and must be
treated as a regression.

### Reconsideration Trigger

Revisit with mtime-gated caching only if profile parsing ever becomes hot enough
to matter — and only on evidence of cost, not before. It is not hot at
agent/human interaction pace today.
