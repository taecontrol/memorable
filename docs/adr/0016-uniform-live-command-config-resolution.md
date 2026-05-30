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
