"""In-memory repository implementations.

These are used as placeholders until the real storage adapters are wired.
"""

from __future__ import annotations

from datetime import datetime

from memorable.core.models import (
    Decision,
    Entity,
    MemorySpace,
    Provenance,
    Task,
)
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


class InMemoryEntityRepository:
    """In-memory implementation of EntityRepository."""

    def __init__(self) -> None:
        self._entities: dict[tuple[str, str], Entity] = {}
        self._provenance: dict[tuple[str, str], Provenance] = {}

    def save(self, entity: Entity, provenance: Provenance) -> None:
        key = (entity.space, entity.id)
        self._entities[key] = entity
        self._provenance[key] = provenance

    def get(self, space: str, entity_id: str) -> Entity | None:
        return self._entities.get((space, entity_id))

    def get_provenance(self, space: str, entity_id: str) -> Provenance | None:
        return self._provenance.get((space, entity_id))

    def list_by_space(self, space: str) -> list[Entity]:
        """Return all entities in the given space."""
        return [entity for (s, _), entity in self._entities.items() if s == space]


class InMemoryDecisionRepository:
    """In-memory implementation of DecisionRepository."""

    def __init__(self) -> None:
        self._decisions: dict[tuple[str, str], Decision] = {}
        self._provenance: dict[tuple[str, str], Provenance] = {}

    def save(self, decision: Decision, provenance: Provenance) -> None:
        key = (decision.space, decision.id)
        self._decisions[key] = decision
        self._provenance[key] = provenance

    def get(self, space: str, decision_id: str) -> Decision | None:
        return self._decisions.get((space, decision_id))

    def get_provenance(self, space: str, decision_id: str) -> Provenance | None:
        return self._provenance.get((space, decision_id))

    def list_by_space(self, space: str) -> list[Decision]:
        """Return all decisions in the given space."""
        return [decision for (s, _), decision in self._decisions.items() if s == space]

    def mark_superseded(
        self,
        space: str,
        decision_id: str,
        superseded_by: str,
        invalidation_time: datetime,
    ) -> None:
        key = (space, decision_id)
        old = self._decisions.get(key)
        if old is None:
            return
        # Replace with updated frozen dataclass via object.__setattr__ workaround
        updated = Decision(
            id=old.id,
            statement=old.statement,
            space=old.space,
            validity_time=old.validity_time,
            invalidation_time=invalidation_time,
            lifecycle_state="superseded",
            supersedes=old.supersedes,
            superseded_by=superseded_by,
        )
        self._decisions[key] = updated


class InMemoryTaskRepository:
    """In-memory implementation of TaskRepository."""

    def __init__(self) -> None:
        self._tasks: dict[tuple[str, str], Task] = {}
        self._provenance: dict[tuple[str, str], Provenance] = {}

    def save(self, task: Task, provenance: Provenance) -> None:
        key = (task.space, task.id)
        self._tasks[key] = task
        self._provenance[key] = provenance

    def list_by_space(self, space: str) -> list[Task]:
        """Return all tasks in the given space."""
        return [task for (s, _), task in self._tasks.items() if s == space]

    def get(self, *, space: str, task_id: str) -> Task | None:
        return self._tasks.get((space, task_id))

    def get_provenance(self, *, space: str, task_id: str) -> Provenance | None:
        return self._provenance.get((space, task_id))

    def complete(
        self,
        *,
        space: str,
        task_id: str,
        completion_time: datetime,
        completion_event_id: str,
    ) -> None:
        key = (space, task_id)
        old = self._tasks.get(key)
        if old is None:
            return
        updated = Task(
            id=old.id,
            title=old.title,
            space=old.space,
            lifecycle_state="completed",
            validity_time=old.validity_time,
            completion_time=completion_time,
            completion_event_id=completion_event_id,
        )
        self._tasks[key] = updated


def make_memory_space_repository() -> MemorySpaceRepository:
    """Create a MemorySpaceRepository (in-memory until Neo4j adapter is wired)."""
    return InMemoryMemorySpaceRepository()
