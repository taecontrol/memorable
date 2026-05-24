"""Tests for Neo4j MemorySpace adapter.

Unit tests use a fake driver to verify adapter logic without Neo4j.
Integration tests (marked with @pytest.mark.integration) need a running Neo4j.
"""

from __future__ import annotations

import pytest


def test_adapter_implements_repository_port() -> None:
    """Neo4jMemorySpaceRepository must satisfy the MemorySpaceRepository protocol."""
    from memorable.storage.neo4j.repository import Neo4jMemorySpaceRepository

    # Structural check: the class has the required methods
    assert hasattr(Neo4jMemorySpaceRepository, "create_space")
    assert hasattr(Neo4jMemorySpaceRepository, "get_space")
    assert hasattr(Neo4jMemorySpaceRepository, "exists")


def test_adapter_create_space_returns_memory_space() -> None:
    """create_space must return a MemorySpace domain object, not a storage artifact."""
    from memorable.core.models import MemorySpace
    from memorable.storage.neo4j.repository import Neo4jMemorySpaceRepository

    repo = Neo4jMemorySpaceRepository(driver=FakeDriver())
    space = repo.create_space("test-project")

    assert isinstance(space, MemorySpace)
    assert space.name == "test-project"


def test_adapter_get_space_returns_none_when_missing() -> None:
    """get_space must return None for a non-existent MemorySpace."""
    from memorable.storage.neo4j.repository import Neo4jMemorySpaceRepository

    repo = Neo4jMemorySpaceRepository(driver=FakeDriver())
    assert repo.get_space("nonexistent") is None


def test_adapter_exists_reflects_created_spaces() -> None:
    """exists must return True after create_space and False before."""
    from memorable.storage.neo4j.repository import Neo4jMemorySpaceRepository

    repo = Neo4jMemorySpaceRepository(driver=FakeDriver())
    assert not repo.exists("my-project")
    repo.create_space("my-project")
    assert repo.exists("my-project")


def test_adapter_does_not_expose_storage_vocabulary() -> None:
    """The adapter's public interface must not use Node, Edge, label, or Cypher."""
    import inspect

    from memorable.storage.neo4j.repository import Neo4jMemorySpaceRepository

    # Check method names don't use storage vocabulary
    public_methods = [
        name for name in dir(Neo4jMemorySpaceRepository) if not name.startswith("_")
    ]
    storage_terms = {"node", "edge", "label", "relationship", "cypher"}
    for method_name in public_methods:
        assert method_name.lower() not in storage_terms, (
            f"Public method '{method_name}' uses storage vocabulary"
        )

    # Check method signatures don't use storage vocabulary in parameter names
    for method_name in public_methods:
        method = getattr(Neo4jMemorySpaceRepository, method_name)
        if callable(method):
            sig = inspect.signature(method)
            for param_name in sig.parameters:
                if param_name == "self":
                    continue
                for term in storage_terms:
                    assert term not in param_name.lower(), (
                        f"Parameter '{param_name}' in "
                        f"'{method_name}' uses storage vocabulary"
                    )


def test_adapter_create_duplicate_raises() -> None:
    """Creating a MemorySpace that already exists should raise ValueError."""
    from memorable.storage.neo4j.repository import Neo4jMemorySpaceRepository

    repo = Neo4jMemorySpaceRepository(driver=FakeDriver())
    repo.create_space("dup")
    with pytest.raises(ValueError, match="already exists"):
        repo.create_space("dup")


# --- Fake driver for unit tests ---


class FakeResult:
    def __init__(self, records: list[dict] | None = None) -> None:
        self._records = records or []

    def single(self) -> dict | None:
        return self._records[0] if self._records else None


class FakeSession:
    def __init__(self) -> None:
        self._spaces: dict[str, dict] = {}

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def run(self, query: str, **params: object) -> FakeResult:
        # Simple simulation of Neo4j behavior for testing adapter logic
        if "MERGE" in query or "CREATE" in query:
            name = params.get("name", "")
            if "MERGE" in query:
                # MERGE behavior: create if not exists
                if name not in self._spaces:
                    self._spaces[str(name)] = {"name": name}
                return FakeResult([self._spaces[str(name)]])
            else:
                self._spaces[str(name)] = {"name": name}
                return FakeResult([self._spaces[str(name)]])
        elif "MATCH" in query:
            name = params.get("name", "")
            space = self._spaces.get(str(name))
            if space:
                return FakeResult([space])
            return FakeResult()
        return FakeResult()


class FakeDriver:
    def __init__(self) -> None:
        self._session = FakeSession()

    def session(self, **kwargs: object) -> FakeSession:
        return self._session
