"""In-memory repository implementations.

These are used as placeholders until the real storage adapters are wired.
"""

from __future__ import annotations

from memorable.core.models import MemorySpace
from memorable.core.ports import MemorySpaceRepository


class InMemoryMemorySpaceRepository:
    """In-memory implementation of MemorySpaceRepository."""

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


def make_memory_space_repository() -> MemorySpaceRepository:
    """Create a MemorySpaceRepository (in-memory until Neo4j adapter is wired)."""
    return InMemoryMemorySpaceRepository()
