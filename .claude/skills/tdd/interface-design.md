# Interface Design for Testability

Good interfaces make testing natural.

## 1. Accept dependencies, don't create them

```python
# Testable — dependency is injected
def process_memories(query: str, *, store: MemoryStore) -> list[MemoryRecord]:
    return store.search(query)

# Hard to test — creates its own dependency
def process_memories(query: str) -> list[MemoryRecord]:
    store = Neo4jMemoryStore()
    return store.search(query)
```

## 2. Return results, don't produce side effects

```python
# Testable — returns a value you can assert on
def rank_memories(records: list[MemoryRecord], query: str) -> list[MemoryRecord]:
    return sorted(records, key=lambda r: relevance(r, query), reverse=True)

# Hard to test — mutates input in place
def rank_memories(records: list[MemoryRecord], query: str) -> None:
    records.sort(key=lambda r: relevance(r, query), reverse=True)
```

## 3. Small surface area

- Fewer methods = fewer tests needed
- Fewer params = simpler test setup
- Use keyword-only arguments (`*`) for optional configuration
- Use dataclasses or typed dicts for complex parameter groups

```python
# Good — small surface, keyword-only config
def store_memory(
    content: str,
    *,
    source: str,
    profile: MemoryProfile | None = None,
) -> MemoryRecord: ...

# Avoid — too many positional params
def store_memory(
    content, source, profile, space_id, tags, timestamp, provenance
) -> MemoryRecord: ...
```

## 4. Use Protocols at boundaries

Define narrow Protocol types for external dependencies. This makes faking
trivial and keeps tests fast:

```python
class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...

# Test fake — no mock library needed
class FakeEmbedder:
    def embed(self, text: str) -> list[float]:
        return [0.0] * 128
```
