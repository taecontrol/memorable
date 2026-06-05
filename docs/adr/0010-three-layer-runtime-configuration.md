# ADR 0010: Three-Layer Runtime Configuration

Date: 2026-05-25
Status: Accepted
Refines: ADR 0005

## Context

ADR 0005 decided on a local Neo4j runtime behind the storage adapter and specified two workspace files:

- `.memorable/memory.yaml` (committed MemoryProfile)
- `.memorable/runtime.local.yaml` (local runtime config, gitignored)

As design progressed, three categories of runtime information emerged with different sharing requirements:

1. Project runtime decisions (Neo4j version, embedding provider, model choice) that all contributors should know about and that should be tracked in version history.
2. Machine-local overrides (custom port, alternative provider for local testing) that differ per developer.
3. Secrets (database passwords, API keys) that must never be committed.

A single gitignored file conflates project decisions with machine-local overrides and secrets. Contributors cannot tell what runtime configuration the project expects without asking. Configuration history is not tracked.

## Decision

Memorable uses a three-layer runtime configuration with clear separation:

```
.memorable/
  memory.yaml          # committed — domain (profile, entities, records, policies)
  runtime.yaml         # committed — project runtime defaults
  runtime.local.yaml   # gitignored — optional local overrides
  .env                 # gitignored — secrets (passwords, API keys)
```

### Resolution order

1. Read `runtime.yaml` as the base configuration.
2. Deep-merge `runtime.local.yaml` on top if it exists. Local values override project defaults.
3. Read secrets from `.env`. Secrets are referenced by convention in runtime YAML but never stored there.

### What goes where

`runtime.yaml` (committed) contains project runtime decisions:

```yaml
neo4j:
  uri: bolt://127.0.0.1:7687
  user: neo4j

docker:
  neo4j_version: "5.26"
  http_port: 7474
  bolt_port: 7687

embeddings:
  provider: openrouter
  model: text-embedding-3-small
```

`runtime.local.yaml` (gitignored) contains machine-local overrides:

```yaml
neo4j:
  uri: bolt://localhost:7688  # port 7687 is taken on my machine
```

`.env` (gitignored) contains secrets:

```
MEMORABLE_NEO4J_PASSWORD=memorable
MEMORABLE_OPENROUTER_KEY=sk-or-...
```

### When files are needed

- No `runtime.yaml`: use built-in defaults (bolt://127.0.0.1:7687, neo4j, etc.)
- No `runtime.local.yaml`: use `runtime.yaml` as-is
- No `.env`: read secrets from environment variables directly

A project can start with zero config files and add them as needs arise.

### CLI behavior

- `memorable db start` reads the resolved config (merged runtime + local) to determine Neo4j version and port, then runs the packaged Docker Compose template.
- `memorable db eject` copies the Docker Compose template to `.memorable/docker-compose.yml` for customization.
- `memorable db status` shows the resolved configuration and which file each value came from.
- Cloud Neo4j requires no special treatment: set a remote URI in `runtime.yaml` or `runtime.local.yaml`. `memorable db start/stop` are not applicable for cloud instances.

### Space identity

The MemorySpace name is defined in `memory.yaml` under `space.name`. CLI commands infer the space from the working directory by reading this file. An optional `--space` flag allows targeting a different space explicitly.

## Consequences

Positive:

- Project runtime decisions are tracked in version history.
- New contributors can see what the project expects without asking.
- Machine-local differences do not pollute shared configuration.
- Secrets are cleanly separated from non-secret configuration.
- The `.env` pattern is universally understood.
- Projects can start with zero configuration and add layers as needed.

Negative:

- Three potential configuration sources can make debugging harder. Mitigated by `memorable db status` showing resolved values and their sources.
- Developers must decide which layer a new setting belongs to.
- The deep-merge behavior must be well-defined for nested structures.

## Alternatives Considered

### Single Gitignored File For Everything

The original ADR 0005 approach. Simple, but project decisions are not shared or tracked. Contributors must ask or guess what configuration the project expects.

### Environment Variables Only

No config files at all; everything in env vars. Simple for CI, but poor developer ergonomics for many settings. No project-level documentation of expected configuration.

### Single Committed File With Secret References

One `runtime.yaml` that references env var names for secrets. Simpler than three layers, but does not handle machine-local overrides. Developers who need different ports or providers must use env vars for non-secret settings, which is awkward.

## Reconsideration Trigger

Revisit this decision if:

- The three layers cause frequent confusion about where a setting should go.
- A GUI or TUI configuration interface makes file-based config secondary.
- Team or multi-machine sync requires a different configuration distribution model.

## Amendment (2026-06-05): IPv4 loopback is the built-in local default

The built-in default local Neo4j URI is `bolt://127.0.0.1:7687` (IPv4 loopback)
rather than `bolt://localhost:7687`.

On some local setups (notably macOS Docker Desktop), `localhost` can resolve to
the IPv6 loopback before IPv4. A Bolt TCP handshake can appear to succeed while a
heavier read hangs or fails on a defunct connection, so diagnostics can report a
healthy runtime while search stalls. Pinning the default to IPv4 loopback keeps
the zero-config local runtime boring and reliable.

This amendment changes only the built-in default and its documentation:

- Existing `localhost` configurations remain accepted as local configuration.
- Explicit IPv4 loopback, explicit IPv6 loopback (`[::1]`), custom local ports,
  non-local hosts, and remote/cloud schemes are preserved exactly.
- Local/remote classification is unchanged: `localhost`, `127.0.0.1`, and `::1`
  are local; remote/cloud hosts are remote.
- `memorable db status` continues to report configured values and their sources
  (built-in, runtime.yaml, runtime.local.yaml, .env/environment).
