# When to Mock

Mock at **system boundaries** only:

- External APIs (payment, email, LLM providers)
- Databases (prefer test fixtures or in-memory fakes when possible)
- Time / randomness
- File system (prefer `tmp_path` over mocks)
- Network calls

Don't mock:

- Your own classes or modules
- Internal collaborators
- Anything you control

## Designing for Mockability in Python

### 1. Use dependency injection

Pass external dependencies in rather than creating them internally:

```python
# Easy to test — inject the dependency
def retrieve_memories(query: str, *, store: MemoryStore) -> list[MemoryRecord]:
    return store.search(query)

# Hard to test — creates its own dependency
def retrieve_memories(query: str) -> list[MemoryRecord]:
    store = Neo4jMemoryStore(uri=os.environ["NEO4J_URI"])
    return store.search(query)
```

### 2. Use Protocols for boundaries

Define narrow `Protocol` types at system boundaries so tests can substitute
simple fakes without heavyweight mock libraries:

```python
from typing import Protocol

class MemoryStore(Protocol):
    def search(self, query: str) -> list[MemoryRecord]: ...
    def save(self, record: MemoryRecord) -> None: ...

# In tests — a simple fake, no mock library needed
class FakeMemoryStore:
    def __init__(self):
        self._records: list[MemoryRecord] = []

    def search(self, query: str) -> list[MemoryRecord]:
        return [r for r in self._records if query in r.content]

    def save(self, record: MemoryRecord) -> None:
        self._records.append(record)
```

### 3. Prefer specific interfaces over generic ones

```python
# GOOD: Each method is independently testable
class MemoryStore(Protocol):
    def get_record(self, record_id: str) -> MemoryRecord: ...
    def search(self, query: str) -> list[MemoryRecord]: ...
    def save(self, record: MemoryRecord) -> None: ...

# BAD: Generic execute requires conditional logic in fakes
class MemoryStore(Protocol):
    def execute(self, operation: str, **kwargs) -> Any: ...
```

### 4. Prefer `tmp_path` over filesystem mocks

```python
# GOOD: Real filesystem, isolated per test
def test_export_writes_file(tmp_path):
    output = tmp_path / "export.json"
    export_memories(records, output)
    assert output.read_text() == '...'

# BAD: Mocking open() is fragile
def test_export_writes_file(mocker):
    mock_open = mocker.patch("builtins.open", mocker.mock_open())
    export_memories(records, "export.json")
    mock_open.assert_called_once()
```
