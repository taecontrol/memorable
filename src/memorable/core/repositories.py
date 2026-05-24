"""In-memory repository implementations.

These are used as placeholders until the real storage adapters are wired.
"""

from __future__ import annotations

from datetime import datetime

from memorable.core.models import (
    Decision,
    DecisionProvenance,
    Entity,
    MemorySpace,
    Provenance,
    Task,
    TaskProvenance,
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


class InMemoryDecisionRepository:
    """In-memory implementation of DecisionRepository."""

    def __init__(self) -> None:
        self._decisions: dict[tuple[str, str], Decision] = {}
        self._provenance: dict[tuple[str, str], DecisionProvenance] = {}

    def save(self, decision: Decision, provenance: DecisionProvenance) -> None:
        key = (decision.space, decision.id)
        self._decisions[key] = decision
        self._provenance[key] = provenance

    def get(self, space: str, decision_id: str) -> Decision | None:
        return self._decisions.get((space, decision_id))

    def get_provenance(self, space: str, decision_id: str) -> DecisionProvenance | None:
        return self._provenance.get((space, decision_id))

    def get_current(self, space: str, decision_id: str) -> Decision | None:
        decision = self.get(space, decision_id)
        if decision is None:
            return None
        # Follow supersession chain
        while decision.superseded_by is not None:
            next_decision = self.get(space, decision.superseded_by)
            if next_decision is None:
                break
            decision = next_decision
        return decision

    def get_at(self, space: str, decision_id: str, at: datetime) -> Decision | None:
        decision = self.get(space, decision_id)
        if decision is None:
            return None
        # Walk the chain: find the decision whose validity_time <= at
        # and whose invalidation_time is None or > at
        current = decision
        while True:
            if current.invalidation_time is None or at < current.invalidation_time:
                return current
            # This decision was invalidated before `at`, follow the chain
            if current.superseded_by is None:
                return current
            next_decision = self.get(space, current.superseded_by)
            if next_decision is None:
                return current
            current = next_decision

    def get_history(self, space: str, decision_id: str) -> list[Decision]:
        decision = self.get(space, decision_id)
        if decision is None:
            return []
        chain = [decision]
        while decision.superseded_by is not None:
            next_decision = self.get(space, decision.superseded_by)
            if next_decision is None:
                break
            chain.append(next_decision)
            decision = next_decision
        return chain

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
        self._provenance: dict[tuple[str, str], TaskProvenance] = {}

    def save(self, task: Task, provenance: TaskProvenance) -> None:
        key = (task.space, task.id)
        self._tasks[key] = task
        self._provenance[key] = provenance

    def get(self, *, space: str, task_id: str) -> Task | None:
        return self._tasks.get((space, task_id))

    def get_provenance(self, *, space: str, task_id: str) -> TaskProvenance | None:
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

    def get_at(self, *, space: str, task_id: str, at: datetime) -> Task | None:
        task = self._tasks.get((space, task_id))
        if task is None:
            return None
        if at < task.validity_time:
            return None
        # If task is completed and as-of time is before completion, return as open
        if (
            task.lifecycle_state == "completed"
            and task.completion_time
            and at < task.completion_time
        ):
            return Task(
                id=task.id,
                title=task.title,
                space=task.space,
                lifecycle_state="open",
                validity_time=task.validity_time,
                completion_time=None,
                completion_event_id=None,
            )
        return task


def make_memory_space_repository() -> MemorySpaceRepository:
    """Create a MemorySpaceRepository (in-memory until Neo4j adapter is wired)."""
    return InMemoryMemorySpaceRepository()
