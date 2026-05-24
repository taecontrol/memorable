"""Repository ports for Memorable Core.

These protocols define the contracts that storage adapters must satisfy.
They use domain language exclusively — no storage vocabulary.
"""

from __future__ import annotations

from typing import Protocol

from memorable.core.models import MemorySpace


class MemorySpaceRepository(Protocol):
    """Port for MemorySpace persistence."""

    def create_space(self, name: str) -> MemorySpace:
        """Create and persist a new MemorySpace."""
        ...

    def get_space(self, name: str) -> MemorySpace | None:
        """Retrieve a MemorySpace by name, or None if it does not exist."""
        ...

    def exists(self, name: str) -> bool:
        """Check whether a MemorySpace with the given name exists."""
        ...
