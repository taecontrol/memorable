"""Repository ports for Memorable Core.

These protocols define the contracts that storage adapters must satisfy.
They use domain language exclusively — no storage vocabulary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from memorable.core.models import (
    Decision,
    DecisionProvenance,
    Entity,
    MemorySpace,
    Provenance,
)


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


class EntityRepository(Protocol):
    """Port for Entity persistence with provenance."""

    def save(self, entity: Entity, provenance: Provenance) -> None:
        """Persist an Entity with its provenance record."""
        ...

    def get(self, space: str, entity_id: str) -> Entity | None:
        """Retrieve an Entity by space and id, or None if not found."""
        ...

    def get_provenance(self, space: str, entity_id: str) -> Provenance | None:
        """Retrieve the provenance for an Entity, or None if not found."""
        ...


class DecisionRepository(Protocol):
    """Port for Decision persistence with provenance and temporal queries."""

    def save(self, decision: Decision, provenance: DecisionProvenance) -> None:
        """Persist a Decision with its provenance record."""
        ...

    def get(self, space: str, decision_id: str) -> Decision | None:
        """Retrieve a Decision by space and id, or None if not found."""
        ...

    def get_provenance(self, space: str, decision_id: str) -> DecisionProvenance | None:
        """Retrieve the provenance for a Decision, or None if not found."""
        ...

    def get_current(self, space: str, decision_id: str) -> Decision | None:
        """Follow supersession chain to find the current Decision."""
        ...

    def get_at(self, space: str, decision_id: str, at: datetime) -> Decision | None:
        """Return the Decision that was valid at the given time."""
        ...

    def get_history(self, space: str, decision_id: str) -> list[Decision]:
        """Return the supersession chain starting from the given Decision."""
        ...

    def mark_superseded(
        self,
        space: str,
        decision_id: str,
        superseded_by: str,
        invalidation_time: datetime,
    ) -> None:
        """Mark a Decision as superseded by another."""
        ...
