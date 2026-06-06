# Refactor Candidates

After the TDD cycle, with all tests GREEN, look for:

- **Duplication** → Extract function, base class, or shared fixture
- **Long functions** → Break into private helpers (keep tests on public interface)
- **Shallow modules** → Combine or deepen
- **Feature envy** → Move logic to where the data lives
- **Primitive obsession** → Introduce value objects, dataclasses, or Enums
- **Existing code** the new code reveals as problematic
- **Missing type hints** → Add annotations on public API
- **Stringly-typed interfaces** → Replace with Enum or Literal types
