"""In-memory repository implementations.

These are used as placeholders until the real storage adapters are wired.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from memorable.core.models import (
    Decision,
    Entity,
    MemorySpace,
    Observation,
    Provenance,
    ProvenanceIntegrityError,
    RecordProjection,
    Relation,
    Task,
)
from memorable.core.ports import TemporalRecord


class InMemoryTemporalRepository[T: TemporalRecord]:
    """Generic in-memory implementation of temporal record storage.

    Provides the shared temporal methods (get, mark_superseded, invalidate,
    correct, save_provenance, get_provenance, list_by_space) once, so that
    concrete repositories (Decision, Observation) inherit instead of
    duplicating the logic.

    The model type T must be a frozen dataclass with the standard temporal
    fields: id, space, statement, validity_time, invalidation_time,
    lifecycle_state, supersedes, superseded_by.
    """

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], T] = {}
        self._provenance: dict[tuple[str, str], Provenance] = {}

    def save_record(self, record: T, provenance: Provenance) -> None:
        """Store a temporal record and its provenance, keyed by (space, id)."""
        key = (record.space, record.id)
        self._records[key] = record
        self._provenance[key] = provenance

    def get(self, space: str, record_id: str) -> T | None:
        """Retrieve a temporal record by space and id, or None if not found."""
        return self._records.get((space, record_id))

    def get_provenance(self, space: str, record_id: str) -> Provenance | None:
        """Retrieve the provenance for a temporal record, or None."""
        return self._provenance.get((space, record_id))

    def list_by_space(self, space: str) -> list[T]:
        """Return all records in the given space."""
        return [record for (s, _), record in self._records.items() if s == space]

    def mark_superseded(
        self,
        space: str,
        record_id: str,
        superseded_by: str,
        invalidation_time: datetime,
    ) -> None:
        """Mark a temporal record as superseded by another."""
        key = (space, record_id)
        old = self._records.get(key)
        if old is None:
            return
        self._records[key] = replace(
            old,
            invalidation_time=invalidation_time,
            lifecycle_state="superseded",
            superseded_by=superseded_by,
        )

    def invalidate(
        self,
        space: str,
        record_id: str,
        invalidation_time: datetime,
    ) -> None:
        """Mark a temporal record as invalidated (no replacement)."""
        key = (space, record_id)
        old = self._records.get(key)
        if old is None:
            return
        self._records[key] = replace(
            old,
            invalidation_time=invalidation_time,
            lifecycle_state="invalidated",
        )

    def correct(
        self,
        space: str,
        record_id: str,
        new_statement: str,
    ) -> None:
        """Correct a temporal record's statement in place."""
        key = (space, record_id)
        old = self._records.get(key)
        if old is None:
            return
        self._records[key] = replace(
            old,
            statement=new_statement,
        )

    def save_provenance(
        self,
        space: str,
        record_id: str,
        provenance: Provenance,
    ) -> None:
        """Replace the provenance for a temporal record."""
        self._provenance[(space, record_id)] = provenance


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


class InMemoryDecisionRepository(InMemoryTemporalRepository[Decision]):
    """In-memory implementation of DecisionRepository.

    Inherits all temporal methods from InMemoryTemporalRepository.
    Only adds the save() signature required by the DecisionRepository protocol.
    """

    def save(self, decision: Decision, provenance: Provenance) -> None:
        self.save_record(decision, provenance)

    def list_projections_by_space(
        self,
        *,
        space: str,
        state: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
    ) -> list[RecordProjection]:
        projections: list[RecordProjection] = []
        for (record_space, _), decision in self._records.items():
            if record_space != space:
                continue
            if state is not None and decision.lifecycle_state != state:
                continue
            provenance = self._provenance.get((space, decision.id))
            if provenance is None:
                raise ProvenanceIntegrityError(
                    f"Provenance missing for decision '{decision.id}' "
                    f"in MemorySpace '{space}'."
                )
            if since is not None and provenance.creation_time < since:
                continue
            if until is not None and provenance.creation_time >= until:
                continue
            projections.append(
                RecordProjection(
                    id=decision.id,
                    type="decision",
                    label=decision.statement,
                    lifecycle_state=decision.lifecycle_state,
                    creation_time=provenance.creation_time,
                )
            )
        projections.sort(key=lambda p: (p.creation_time, p.id))
        return projections[:limit]


class InMemoryObservationRepository(InMemoryTemporalRepository[Observation]):
    """In-memory implementation of ObservationRepository.

    Inherits all temporal methods from InMemoryTemporalRepository.
    Only adds the save() signature required by the ObservationRepository protocol.
    """

    def save(self, observation: Observation, provenance: Provenance) -> None:
        self.save_record(observation, provenance)


class InMemoryRelationRepository(InMemoryTemporalRepository[Relation]):
    """In-memory implementation of RelationRepository.

    Inherits all temporal methods from InMemoryTemporalRepository.
    Adds save() for the RelationRepository protocol and list_by_entity()
    for graph expansion queries.
    """

    def save(self, relation: Relation, provenance: Provenance) -> None:
        self.save_record(relation, provenance)

    def list_by_entity(self, space: str, entity_id: str) -> list[Relation]:
        """Return all Relations where entity_id is source or target in the space."""
        return [
            record
            for (s, _), record in self._records.items()
            if s == space
            and (
                record.source_entity_id == entity_id
                or record.target_entity_id == entity_id
            )
        ]


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
