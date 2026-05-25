"""Repository ports for Memorable Core.

These protocols define the contracts that storage adapters must satisfy.
They use domain language exclusively — no storage vocabulary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from memorable.core.models import (
    Decision,
    Entity,
    MemorySpace,
    Provenance,
    Task,
)


@runtime_checkable
class TemporalRecord(Protocol):
    """Structural protocol for objects returned by TemporalRecordRepository.

    Any object with these attributes (e.g. Decision) satisfies this protocol,
    giving callers typed access to temporal fields without coupling to a
    concrete record type.
    """

    id: str
    statement: str
    space: str
    validity_time: datetime
    invalidation_time: datetime | None
    lifecycle_state: str
    supersedes: str | None
    superseded_by: str | None


@runtime_checkable
class TemporalRecordRepository(Protocol):
    """Shared surface for repositories that hold temporal records with supersession.

    Any repository whose records carry superseded_by, lifecycle_state, and
    invalidation_time can satisfy this protocol, enabling generic temporal
    services (CurrentTruth, PointInTimeTruth, InspectHistory) to operate
    across record types.
    """

    def get(self, space: str, record_id: str) -> TemporalRecord | None:
        """Retrieve a temporal record by space and id, or None if not found."""
        ...

    def mark_superseded(
        self,
        space: str,
        record_id: str,
        superseded_by: str,
        invalidation_time: datetime,
    ) -> None:
        """Mark a temporal record as superseded by another."""
        ...


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

    def list_by_space(self, space: str) -> list[Entity]:
        """Return all entities in the given space."""
        ...


class DecisionRepository(Protocol):
    """Port for Decision persistence with provenance."""

    def save(self, decision: Decision, provenance: Provenance) -> None:
        """Persist a Decision with its provenance record."""
        ...

    def get(self, space: str, decision_id: str) -> Decision | None:
        """Retrieve a Decision by space and id, or None if not found."""
        ...

    def get_provenance(self, space: str, decision_id: str) -> Provenance | None:
        """Retrieve the provenance for a Decision, or None if not found."""
        ...

    def list_by_space(self, space: str) -> list[Decision]:
        """Return all decisions in the given space."""
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


class TaskRepository(Protocol):
    """Port for Task persistence with provenance."""

    def save(self, task: Task, provenance: Provenance) -> None:
        """Persist a Task with its provenance record."""
        ...

    def get(self, *, space: str, task_id: str) -> Task | None:
        """Retrieve a Task by space and id, or None if not found."""
        ...

    def get_provenance(self, *, space: str, task_id: str) -> Provenance | None:
        """Retrieve the provenance for a Task, or None if not found."""
        ...

    def complete(
        self,
        *,
        space: str,
        task_id: str,
        completion_time: datetime,
        completion_event_id: str,
    ) -> None:
        """Record a completion event on a Task (append-first, not delete)."""
        ...

    def list_by_space(self, space: str) -> list[Task]:
        """Return all tasks in the given space."""
        ...
