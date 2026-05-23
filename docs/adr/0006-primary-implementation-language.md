# ADR 0006: Use Python As The Primary Implementation Language

Date: 2026-05-23
Status: Accepted

## Context

Memorable is a project-scoped memory system for agents. Its first implementation must prove:

- agent-owned structured memory writes;
- temporal MemoryRecords with provenance and lifecycle transitions;
- local Neo4j storage through an adapter boundary;
- GraphRAG retrieval with embeddings, graph expansion, temporal filtering, and provenance inspection;
- an MCP-first agent interface;
- human-operable CLI workflows for initialization, diagnostics, review, and search.

The language choice affects more than syntax. It shapes retrieval experiments, schema validation, packaging, MCP ergonomics, future Graphiti comparison, and how quickly the project can learn from a tracer bullet.

## Decision

Use Python as the primary implementation language for the first implementation.

The first implementation should include:

- `memorable-core` in Python;
- `memorable-mcp` in Python;
- `storage/neo4j` in Python using the official Neo4j Python driver;
- retrieval and embedding provider abstractions in Python;
- Pydantic or an equivalent validation library for structured schemas and tool contracts;
- pytest for behavior and integration tests;
- a Python CLI package as the first user-facing distribution.

Python is the primary implementation language. This does not require every future component to be Python. Future adapters, user interfaces, or local services may use other languages when evidence justifies the added boundary.

## Rationale

Retrieval quality is a core product risk. Memorable is not useful if agents cannot reliably retrieve the right memory at the right time.

Python best supports the first implementation because it has strong ecosystem support for:

- embedding providers;
- rerankers;
- local model experimentation;
- retrieval evaluation harnesses;
- Graphiti comparison or adapter spikes;
- Pydantic-style structured validation;
- Neo4j integration;
- MCP server implementation;
- fast iteration on GraphRAG behavior.

TypeScript remains attractive for JSON tool contracts and agent-facing APIs, but Memorable's first serious risk is retrieval reliability, not MCP ergonomics. Python better matches that risk.

## Consequences

Positive:

- Retrieval and embedding work can use the strongest available ecosystem.
- Graphiti comparison remains technically close without letting Graphiti own the domain model.
- Pydantic-style schemas fit MemoryProfile and structured write validation.
- One language can cover core, Neo4j adapter, retrieval, CLI, and MCP for the first implementation.

Negative:

- JavaScript and TypeScript agent tooling will cross a process boundary through MCP rather than sharing types directly.
- Python packaging must be handled carefully to keep install and runtime setup simple.
- Future browser or desktop UI work will likely require a second language boundary.

## Alternatives Considered

### TypeScript

TypeScript is strong for MCP ergonomics, JSON-shaped contracts, and shared tool types. It was the strongest alternative when the primary risk appeared to be agent tool contracts.

It is not the first choice after making GraphRAG retrieval quality a required tracer bullet behavior. Python is better for retrieval research, local model work, reranking, and Graphiti comparison.

### Go

Go is strong for local daemons, single binaries, and operational clarity. It is less ergonomic for early schema evolution, retrieval experimentation, and AI ecosystem integration.

### Rust

Rust is strong for correctness and local binary distribution. It adds too much friction before Memorable's model and retrieval behavior are proven.

### Early Polyglot Architecture

A TypeScript MCP layer with a Python retrieval/core service, or similar split, would let each ecosystem do what it does best. It also adds packaging, testing, error handling, and local runtime complexity too early.

## Reconsideration Trigger

Revisit this decision if:

- Python packaging becomes the dominant barrier to user adoption;
- MCP implementation in Python proves materially weaker than expected;
- a single local binary becomes the main product constraint;
- TypeScript or another runtime clearly outperforms Python for the retrieval architecture Memorable needs;
- Graphiti is rejected and retrieval needs become simple enough that MCP/tool ergonomics dominate again.
