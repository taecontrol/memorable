# Good and Bad Tests

## Good Tests

**Integration-style**: test through real interfaces, not mocks of internal parts.

```python
# GOOD: Tests observable behavior through the public interface
def test_memory_record_is_retrievable_after_storage(memory_space):
    record = memory_space.store(content="project uses Neo4j", source="user")
    retrieved = memory_space.recall(record.id)
    assert retrieved.content == "project uses Neo4j"
```

Characteristics:

- Tests behavior callers care about
- Uses public API only
- Survives internal refactors
- Describes WHAT, not HOW
- One logical assertion per test
- Test name reads like a specification

## Bad Tests

**Implementation-detail tests**: coupled to internal structure.

```python
# BAD: Mocks an internal collaborator
def test_store_calls_repository_save(mocker):
    mock_repo = mocker.patch("memorable.core.storage.Repository.save")
    space = MemorySpace(repo=mock_repo)
    space.store(content="hello", source="user")
    mock_repo.save.assert_called_once()
```

Red flags:

- Mocking internal collaborators
- Testing private methods (`_build_query`, `__process`)
- Asserting on call counts or call order
- Test breaks when refactoring without behavior change
- Test name describes HOW not WHAT
- Verifying through external means instead of interface

```python
# BAD: Bypasses interface to verify via database
def test_store_saves_to_neo4j(neo4j_session):
    store(content="hello", source="user")
    result = neo4j_session.run("MATCH (n:Memory) RETURN n")
    assert result.single() is not None

# GOOD: Verifies through interface
def test_stored_record_is_recallable(memory_space):
    record = memory_space.store(content="hello", source="user")
    retrieved = memory_space.recall(record.id)
    assert retrieved.content == "hello"
```

## Pytest Conventions

- Use `pytest` style (functions, not `unittest.TestCase` classes)
- Use fixtures for setup, not `setUp`/`tearDown`
- Use `@pytest.mark.parametrize` for data-driven variants
- Use `tmp_path` fixture for filesystem tests
- Group related tests in the same file, not one-test-per-file
- Name test files `test_<module>.py`, name tests `test_<behavior>`
