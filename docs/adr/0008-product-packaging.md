# ADR 0008: Package Memorable As A Python CLI And MCP Server

Date: 2026-05-23
Status: Accepted

## Context

Memorable's primary users are agents, but humans own the memory. The product needs two surfaces:

- an agent-facing MCP server for reading and writing memory;
- a human-operable CLI for initialization, diagnostics, runtime management, search, inspection, review, and correction.

The product is local-first by default and uses local Neo4j as the first storage runtime. The first implementation is Python, and retrieval quality requires embedding and GraphRAG dependencies.

Packaging must make the tracer bullet easy to run without turning Memorable into a Docker-only appliance or a library that users must assemble themselves.

## Decision

Package Memorable first as a Python CLI application that also exposes an MCP server.

The first package should provide commands shaped like:

```bash
uvx memorable init
uvx memorable doctor
uvx memorable runtime start
uvx memorable tracer run
uvx memorable search "How does Memorable expose memory to agents?"
uvx memorable mcp
```

For regular use, users can install the tool persistently:

```bash
uv tool install memorable
memorable init
memorable mcp
```

The package contains the first implementation of:

- Memorable Core;
- the Neo4j storage adapter;
- GraphRAG retrieval and embedding abstractions;
- the MCP server;
- the human CLI;
- runtime diagnostics.

Neo4j remains a runtime dependency, not something bundled into the Python package. Memorable may manage a local Neo4j container through `memorable runtime start`, and it may also connect to a user-supplied local Neo4j instance.

The CLI owns product workflow. Docker or other runtime mechanisms are implementation details of local runtime management unless the user explicitly chooses to operate them directly.

## Consequences

Positive:

- Users can try Memorable with `uvx` before installing it permanently.
- The same package can serve humans and agents.
- Python retrieval dependencies remain close to the core.
- The CLI can provide diagnostics before MCP startup fails mysteriously.
- Docker can be used for Neo4j without making Docker Compose the primary product interface.

Negative:

- Python packaging and optional dependencies must be carefully managed.
- Users still need a working local runtime for Neo4j and embeddings.
- A future desktop app or container appliance will require an additional packaging layer.

## Alternatives Considered

### Docker Compose Appliance First

A Compose stack could bundle the MCP server, Neo4j, and optional embedding services. This is more reproducible, but it makes project-local workflows, path mapping, debugging, and rapid iteration heavier. It is better as a later stable distribution.

### Library-Only Package

A library-only package would be simple for developers, but Memorable needs a product surface. Users and agents need `init`, `doctor`, `runtime`, `search`, `inspect`, and `mcp` workflows.

### Desktop App First

A desktop app could eventually provide the best human review and correction experience. It is too early because the core model, retrieval behavior, and runtime story are not proven.

### MCP Server Only

An MCP-only package would serve agents but leave humans without a clear way to initialize, inspect, diagnose, and correct memory. Human ownership requires an explicit human-facing surface.

## Reconsideration Trigger

Revisit this decision if:

- Python CLI installation becomes the dominant adoption barrier;
- Docker-managed runtime becomes reliable enough that an appliance distribution is simpler for most users;
- human review and correction workflows require a richer interface than CLI can reasonably provide;
- agents need a long-running local service instead of launching an MCP command per integration.
