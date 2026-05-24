"""Tests for MemorySpace domain model and repository port."""

from __future__ import annotations


def test_memory_space_has_name() -> None:
    """A MemorySpace must have a name that identifies the project boundary."""
    from memorable.core.models import MemorySpace

    space = MemorySpace(name="my-project")
    assert space.name == "my-project"


def test_memory_space_is_value_object() -> None:
    """Two MemorySpaces with the same name are equal."""
    from memorable.core.models import MemorySpace

    assert MemorySpace(name="alpha") == MemorySpace(name="alpha")
    assert MemorySpace(name="alpha") != MemorySpace(name="beta")


def test_memory_space_name_cannot_be_empty() -> None:
    """A MemorySpace must have a non-empty name."""
    import pytest

    from memorable.core.models import MemorySpace

    with pytest.raises(ValueError, match="name"):
        MemorySpace(name="")


def test_repository_port_defines_create_and_get() -> None:
    """The MemorySpaceRepository protocol must define create_space and get_space."""
    from memorable.core.ports import MemorySpaceRepository

    # Verify the protocol has the expected methods
    assert hasattr(MemorySpaceRepository, "create_space")
    assert hasattr(MemorySpaceRepository, "get_space")
    assert hasattr(MemorySpaceRepository, "exists")


def test_in_memory_repository_satisfies_port() -> None:
    """An in-memory implementation must satisfy the MemorySpaceRepository protocol."""
    from memorable.core.models import MemorySpace
    from memorable.core.ports import MemorySpaceRepository

    class InMemoryMemorySpaceRepository:
        def __init__(self) -> None:
            self._spaces: dict[str, MemorySpace] = {}

        def create_space(self, name: str) -> MemorySpace:
            space = MemorySpace(name=name)
            self._spaces[name] = space
            return space

        def get_space(self, name: str) -> MemorySpace | None:
            return self._spaces.get(name)

        def exists(self, name: str) -> bool:
            return name in self._spaces

    repo: MemorySpaceRepository = InMemoryMemorySpaceRepository()
    space = repo.create_space("test-project")
    assert space.name == "test-project"
    assert repo.exists("test-project")
    assert repo.get_space("test-project") == space
    assert repo.get_space("nonexistent") is None
    assert not repo.exists("nonexistent")
