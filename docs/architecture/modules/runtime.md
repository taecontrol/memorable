# Runtime Module

Date: 2026-05-23
Status: Draft

## Purpose

The Runtime module manages local service setup, configuration, and diagnostics.

Runtime makes local-first operation practical without letting machine-specific details become Memorable Core language.

## Owns

- Resolving workspace-local `.memorable` paths.
- Reading and writing machine-local runtime configuration.
- Starting, stopping, or checking local Neo4j where Memorable manages it.
- Detecting user-supplied local Neo4j configuration.
- Embedding provider runtime diagnostics.
- Credential reference handling.
- `doctor` checks for local services, indexes, provider configuration, and common setup problems.

## Does Not Own

- MemoryProfile semantics.
- MemoryRecord lifecycle.
- GraphRAG ranking.
- Storage schema mapping.
- MCP tool semantics.
- Canonical memory.

## Configuration Boundary

Project memory configuration and runtime configuration are separate:

```text
.memorable/
  memory.yaml             # committed MemoryProfile
  runtime.local.yaml      # local runtime config, gitignored
```

`memory.yaml` describes memory shape and policy.

`runtime.local.yaml` describes local machine choices such as Neo4j URI, credential reference, embedding provider, and model configuration.

## Boundary Contract

- Runtime config does not define domain language.
- Runtime config is local by default and should not be committed.
- Remote Neo4j and remote embedding providers require explicit configuration.
- Runtime diagnostics explain setup state without mutating memory unless the command is explicitly a setup command.
- Runtime commands call storage and embedding setup through adapters, not through Core domain shortcuts.

## Forbidden Leaks

- Do not put Neo4j URI, credentials, Docker volume names, ports, or embedding API keys in MemoryProfile.
- Do not hide remote persistence behind default configuration.
- Do not make local runtime choices visible as Core concepts.
- Do not require Docker as the only possible local Neo4j path.

## Tests That Should Enforce This Boundary

- `memory.yaml` can be validated without runtime config.
- Runtime config is required before connecting to user-supplied services.
- Remote providers fail closed unless explicitly enabled.
- `doctor` can report missing Neo4j and missing embedding provider configuration.
- Runtime setup does not write canonical memory records.

## Open Questions

- Should `runtime.local.yaml` be created by `memorable init` or by `memorable runtime start`?
- Should Memorable manage Neo4j through Docker first, or only diagnose/connect to an existing local instance in the first slice?
- Where should credentials be stored or referenced on each operating system?
