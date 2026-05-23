# Interfaces Module

Date: 2026-05-23
Status: Draft

## Purpose

The Interfaces module exposes Memorable to agents and humans.

The first interfaces are:

- MCP server for agents;
- CLI for human operation, diagnostics, search, review, and runtime commands.

Interfaces translate requests into application behavior and translate results into user-facing Memorable language. They do not define the product model.

## Owns

- MCP tool names, request schemas, and response schemas.
- CLI commands and terminal output.
- Human-readable errors for invalid requests and runtime problems.
- Mapping between interface payloads and Core/application calls.
- Command flows such as `init`, `doctor`, `runtime start`, `search`, and `mcp`.

## Does Not Own

- Core domain concepts.
- Storage mapping.
- Retrieval ranking behavior.
- Embedding provider implementation.
- Runtime process internals beyond invoking Runtime module behavior.
- MemoryProfile semantics.

## Adapters

### MCP Adapter

The MCP adapter exposes agent-facing tools over Core and Retrieval behavior.

It should use Memorable Core language in tool names, inputs, and outputs. It should not expose Neo4j or provider internals except through explicit diagnostic tools.

### CLI Adapter

The CLI adapter exposes human-facing workflows.

It should support initialization, diagnostics, local runtime operations, search, inspection, review, and MCP startup. It may show operational details when the user explicitly asks for diagnostics.

## Boundary Contract

- Interfaces do not invent new domain semantics.
- Interface schemas map to Core and Retrieval behavior.
- Normal outputs use Memorable language.
- Diagnostic outputs may mention adapter/runtime details when useful.
- MCP tools should avoid repetitive provenance boilerplate while keeping provenance inspectable.
- CLI commands should make local-first behavior visible and controllable.

## Forbidden Leaks

- Do not expose raw Neo4j objects in MCP results.
- Do not make CLI flags the source of MemoryProfile semantics.
- Do not silently configure remote storage or remote embedding providers.
- Do not let MCP-specific assumptions enter Core.

## Tests That Should Enforce This Boundary

- MCP responses use Core language and stable schemas.
- CLI search and MCP search return equivalent domain results for the same query.
- Diagnostic commands can reveal runtime details without changing memory.
- Invalid input fails before storage mutation.

## Open Questions

- Which MCP tools are required for the first public interface?
- Should CLI and MCP share request/response schema classes directly?
- How much review and correction workflow belongs in CLI before a richer UI exists?
