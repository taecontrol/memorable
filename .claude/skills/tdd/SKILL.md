---
name: tdd
description: >
  Drive test-driven development in Python using vertical slices (tracer bullets).
  One test, one implementation, repeat. Tests verify behavior through public
  interfaces — not implementation details. Use when the user asks to TDD,
  write tests first, do red-green-refactor, or says "tdd".
---

# Test-Driven Development

Drive implementation through vertical RED → GREEN → REFACTOR slices using
pytest, Memorable's domain language, and the project's existing test tooling.

## Philosophy

**Tests verify behavior through public interfaces, not implementation details.**
Code can change entirely; tests shouldn't break. A good test reads like a spec —
"memory record is retrievable after storage" tells you exactly what capability
exists. These tests survive refactors because they don't care about internals.

**Bad tests** mock internal collaborators, test private methods, or verify via
external means (querying a database directly instead of going through the
interface). Warning sign: your test breaks on refactor but behavior hasn't
changed.

See [tests.md](tests.md) for Python examples and [mocking.md](mocking.md) for
mocking guidelines.

## Anti-Pattern: Horizontal Slices

**DO NOT write all tests first, then all implementation.** This is horizontal
slicing — treating RED as "write all tests" and GREEN as "write all code."

This produces bad tests:

- Tests written in bulk test *imagined* behavior, not *actual* behavior
- You test the *shape* of things (data structures, signatures) not user-facing behavior
- Tests become insensitive to real changes
- You outrun your headlights, committing to test structure before understanding the implementation

**Correct approach**: Vertical slices via tracer bullets. One test → one
implementation → repeat. Each test responds to what you learned from the
previous cycle.

```
WRONG (horizontal):
  RED:   test1, test2, test3, test4, test5
  GREEN: impl1, impl2, impl3, impl4, impl5

RIGHT (vertical):
  RED→GREEN: test1→impl1
  RED→GREEN: test2→impl2
  RED→GREEN: test3→impl3
```

## Workflow

### 1. Planning

Before writing any code:

- Read `docs/ubiquitous-language.md` so test names and interfaces match
  Memorable's domain language.
- Read relevant ADRs in `docs/adr/` for the area being touched.
- Read existing tests and code in the affected module.

Then:

- [ ] Confirm with user what interface changes are needed
- [ ] Confirm which behaviors to test (prioritize — you can't test everything)
- [ ] Identify opportunities for [deep modules](deep-modules.md)
- [ ] Design interfaces for [testability](interface-design.md)
- [ ] List behaviors to test (not implementation steps)
- [ ] Get user approval on the plan

Ask: "What should the public interface look like? Which behaviors are most
important to test?"

### 2. Tracer Bullet

Write ONE test that confirms ONE thing about the system:

```
RED:   Write test for first behavior → uv run pytest path/to/test.py -k test_name → FAILS
GREEN: Write minimal code to pass   → uv run pytest path/to/test.py -k test_name → PASSES
```

Commit the RED test before writing the GREEN implementation when the issue
requires TDD commit order.

### 3. Incremental Loop

For each remaining behavior:

```
RED:   Write next test → fails
GREEN: Minimal code to pass → passes
```

Rules:

- One test at a time
- Only enough code to pass the current test
- Don't anticipate future tests
- Keep tests focused on observable behavior
- Run only the relevant test: `uv run pytest tests/path.py -k test_name -v`
- Run the full suite periodically: `uv run pytest tests/ -v --tb=short`

### 4. Refactor

After all tests pass, look for [refactor candidates](refactoring.md):

- [ ] Extract duplication
- [ ] Deepen modules (move complexity behind simple interfaces)
- [ ] Apply SOLID where natural
- [ ] Consider what new code reveals about existing code
- [ ] Run full suite after each refactor step: `uv run pytest tests/ -v`

**Never refactor while RED.** Get to GREEN first.

## Checklist Per Cycle

```
[ ] Test describes behavior, not implementation
[ ] Test uses public interface only
[ ] Test would survive internal refactor
[ ] Code is minimal for this test
[ ] No speculative features added
[ ] from __future__ import annotations present in new files
[ ] Type hints are honest and useful
```
