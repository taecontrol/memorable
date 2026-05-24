"""Domain models for Memorable Core."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemorySpace:
    """Project-scoped memory boundary.

    A MemorySpace owns records, entities, provenance, profile rules,
    and temporal history for one project or workspace.
    """

    name: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("MemorySpace name must not be empty")
