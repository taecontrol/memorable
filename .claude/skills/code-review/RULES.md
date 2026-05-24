# Review Rules

Evaluate every rule. Mark ✅, ❌, or 🟡 with a concrete note.

## Boundary & Architecture

1. **No duplicated policy across adapters.**
   CLI, MCP, and any other adapter must share application services, protocols,
   and builder functions from `core/` — not copy them. Look for identical
   Protocol classes, helper functions, or business logic repeated in separate
   adapter modules.

2. **Protocols and shared contracts live in core.**
   Any `Protocol`, base class, or contract type used by multiple adapters
   must be defined in `memorable.core`, not inside an adapter package.

3. **Domain behavior on domain objects; orchestration in application services.**
   Business rules belong on domain entities or domain services. Application
   services coordinate repositories, transactions, and external calls — they
   should not contain domain logic inline.

4. **Deep modules with stable interfaces over scattered helpers.**
   Prefer cohesive modules that hide complexity behind a narrow public API.
   Flag thin pass-through wrappers, one-liner utility files, or helper
   functions that just re-export internals.

5. **No invented product semantics.**
   Only introduce domain concepts that the issue or spec explicitly requires.
   Walking skeletons and tracer bullets should not smuggle in speculative
   domain modeling.

## Domain Language

6. **Core language in outputs, not storage vocabulary.**
   User-facing and agent-facing outputs must use Memorable's ubiquitous
   language (MemorySpace, MemoryProfile, MemoryRecord, Source, Provenance,
   Temporal Semantics). Storage terms like "node", "edge", "vertex",
   "relationship" must not leak outside storage adapters.

## Code Quality

7. **Lint and formatting pass.**
   `uv run ruff check src/ tests/` must report zero errors.

8. **Type hints are honest and useful.**
   Annotations should reflect actual runtime types. Flag `Any` used to
   silence errors, overly complex generics that obscure intent, or missing
   annotations on public API functions.

9. **`from __future__ import annotations` present.**
   Every Python file must include this import for Python 3.9 compatibility
   when using PEP 585/604 syntax (`dict[str, object]`, `X | None`).

10. **No unnecessary metaprogramming or inheritance.**
    Flag metaclasses, deep inheritance hierarchies, `__init_subclass__` magic,
    or dynamic class creation unless there is a clear, justified need.

11. **No dead or unreachable code.**
    Flag unreachable branches (e.g., code after `argparse` with
    `required=True`), unused imports, or commented-out code blocks.

## Testing

12. **Tests exist for changed behavior.**
    Every new or changed behavior must have at least one test covering the
    happy path. Missing coverage is ❌.

13. **TDD commit order when required.**
    If the issue has a `TDD` label or TDD rule, verify RED tests were
    committed before GREEN implementation. Check `git log --reverse`.

14. **External systems mocked at boundary.**
    Tests must not call real databases, APIs, or filesystems for unit tests.
    Mocks and stubs should be injected at the adapter boundary, not deep
    inside domain code.

15. **Regression tests for bug fixes.**
    If the change fixes a bug, there must be a test that would have caught
    the original bug. Missing regression test is ❌.
