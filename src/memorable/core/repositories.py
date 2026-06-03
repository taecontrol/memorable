"""In-memory repository implementations.

These are used as placeholders until the real storage adapters are wired.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from memorable.core.errors import DuplicateRecordError
from memorable.core.models import (
    Decision,
    Entity,
    ForgetTarget,
    MemorySpace,
    Observation,
    Provenance,
    ProvenanceIntegrityError,
    RecordProjection,
    Relation,
    Task,
)
from memorable.core.ports import TemporalRecord


@dataclass(frozen=True)
class _ProjectionCandidate:
    """A state-filtered record paired with its Provenance join status.

    ``creation_time`` is None when the Provenance join is missing.
    """

    id: str
    type: str
    label: str
    lifecycle_state: str
    creation_time: datetime | None
    has_provenance: bool


def _bounded_projections(
    candidates: list[_ProjectionCandidate],
    space: str,
    since: datetime | None,
    until: datetime | None,
    limit: int,
) -> list[RecordProjection]:
    """Apply the half-open Creation-Time window, order, limit, and integrity check.

    Mirrors the pushed-down Neo4j query semantics: a record with no
    Creation Time (missing Provenance join) is dropped whenever a window
    bound is active, candidates sort by ``(creation_time, id)`` with missing
    Creation Time sorting last, and integrity is scoped to returned rows only.
    """
    windowed = [
        candidate
        for candidate in candidates
        if not (
            (
                since is not None
                and (candidate.creation_time is None or candidate.creation_time < since)
            )
            or (
                until is not None
                and (
                    candidate.creation_time is None or candidate.creation_time >= until
                )
            )
        )
    ]
    windowed.sort(
        key=lambda c: (c.creation_time is None, c.creation_time or datetime.min, c.id)
    )
    selected = windowed[:limit]
    for candidate in selected:
        if not candidate.has_provenance:
            raise ProvenanceIntegrityError(
                f"Provenance missing for {candidate.type} '{candidate.id}' "
                f"in MemorySpace '{space}'."
            )
    return [
        RecordProjection(
            id=candidate.id,
            type=candidate.type,
            label=candidate.label,
            lifecycle_state=candidate.lifecycle_state,
            creation_time=candidate.creation_time,
        )
        for candidate in selected
    ]


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

    def __init__(self, record_keys: set[tuple[str, str]] | None = None) -> None:
        self._records: dict[tuple[str, str], T] = {}
        self._provenance: dict[tuple[str, str], Provenance] = {}
        self._record_keys = record_keys if record_keys is not None else set()

    def save_record(
        self,
        record: T,
        provenance: Provenance,
        *,
        record_kind: str | None = None,
    ) -> None:
        """Store a temporal record and its provenance, keyed by (space, id)."""
        key = (record.space, record.id)
        if record_kind is not None and key in self._record_keys:
            raise DuplicateRecordError(
                record_kind=record_kind,
                space=record.space,
                record_id=record.id,
            )
        self._records[key] = record
        self._provenance[key] = provenance
        if record_kind is not None:
            self._record_keys.add(key)

    def get(self, space: str, record_id: str) -> T | None:
        """Retrieve a temporal record by space and id, or None if not found."""
        return self._records.get((space, record_id))

    def evict(self, space: str, record_id: str) -> None:
        """Erase a record from all in-memory structures it inhabits.

        Storage-context eviction: drops the record, its provenance, and its
        uniqueness key together so the multi-structure invariant stays intact.
        Used only by the ForgetRepository adapter.
        """
        key = (space, record_id)
        self._records.pop(key, None)
        self._provenance.pop(key, None)
        self._record_keys.discard(key)

    def get_provenance(self, space: str, record_id: str) -> Provenance | None:
        """Retrieve the provenance for a temporal record, or None."""
        return self._provenance.get((space, record_id))

    def list_by_space(self, space: str) -> list[T]:
        """Return all records in the given space."""
        return [record for (s, _), record in self._records.items() if s == space]

    def _list_record_projections_by_space(
        self,
        *,
        space: str,
        state: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        record_ids: set[str] | None,
        record_type: str,
        label: Callable[[T], str],
    ) -> list[RecordProjection]:
        candidates: list[_ProjectionCandidate] = []
        for (record_space, _), record in self._records.items():
            if record_space != space:
                continue
            if record_ids is not None and record.id not in record_ids:
                continue
            if state is not None and record.lifecycle_state != state:
                continue
            provenance = self._provenance.get((space, record.id))
            creation_time = provenance.creation_time if provenance else None
            candidates.append(
                _ProjectionCandidate(
                    id=record.id,
                    type=record_type,
                    label=label(record),
                    lifecycle_state=record.lifecycle_state,
                    creation_time=creation_time,
                    has_provenance=provenance is not None,
                )
            )
        return _bounded_projections(candidates, space, since, until, limit)

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

    def evict(self, space: str, entity_id: str) -> None:
        """Erase an Entity and its provenance from in-memory storage.

        Storage-context eviction used only by the ForgetRepository adapter.
        """
        key = (space, entity_id)
        self._entities.pop(key, None)
        self._provenance.pop(key, None)

    def get_provenance(self, space: str, entity_id: str) -> Provenance | None:
        return self._provenance.get((space, entity_id))

    def list_by_space(self, space: str) -> list[Entity]:
        """Return all entities in the given space."""
        return [entity for (s, _), entity in self._entities.items() if s == space]


class InMemoryAboutRepository:
    """In-memory implementation of AboutRepository."""

    def __init__(self) -> None:
        self._links: set[tuple[str, str, str]] = set()

    def link(self, space: str, record_id: str, entity_ids: list[str]) -> None:
        for entity_id in entity_ids:
            self._links.add((space, record_id, entity_id))

    def unlink(self, space: str, record_id: str) -> None:
        self._links = {
            link
            for link in self._links
            if not (link[0] == space and link[1] == record_id)
        }

    def unlink_entity(self, space: str, entity_id: str) -> None:
        """Drop every About link pointing at the given Entity in the space.

        Storage-context eviction used only by the ForgetRepository adapter.
        """
        self._links = {
            link
            for link in self._links
            if not (link[0] == space and link[2] == entity_id)
        }

    def entities_for_record(self, space: str, record_id: str) -> list[str]:
        return sorted(
            entity_id
            for link_space, link_record_id, entity_id in self._links
            if link_space == space and link_record_id == record_id
        )

    def records_for_entity(self, space: str, entity_id: str) -> list[str]:
        return sorted(
            record_id
            for link_space, record_id, link_entity_id in self._links
            if link_space == space and link_entity_id == entity_id
        )


class InMemoryDecisionRepository(InMemoryTemporalRepository[Decision]):
    """In-memory implementation of DecisionRepository.

    Inherits all temporal methods from InMemoryTemporalRepository.
    Only adds the save() signature required by the DecisionRepository protocol.
    """

    def save(self, decision: Decision, provenance: Provenance) -> None:
        self.save_record(decision, provenance, record_kind="decision")

    def list_projections_by_space(
        self,
        *,
        space: str,
        state: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        record_ids: set[str] | None = None,
    ) -> list[RecordProjection]:
        return self._list_record_projections_by_space(
            space=space,
            state=state,
            since=since,
            until=until,
            limit=limit,
            record_ids=record_ids,
            record_type="decision",
            label=lambda decision: decision.statement,
        )


class InMemoryObservationRepository(InMemoryTemporalRepository[Observation]):
    """In-memory implementation of ObservationRepository.

    Inherits all temporal methods from InMemoryTemporalRepository.
    Only adds the save() signature required by the ObservationRepository protocol.
    """

    def save(self, observation: Observation, provenance: Provenance) -> None:
        self.save_record(observation, provenance, record_kind="observation")

    def list_projections_by_space(
        self,
        *,
        space: str,
        state: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        record_ids: set[str] | None = None,
    ) -> list[RecordProjection]:
        return self._list_record_projections_by_space(
            space=space,
            state=state,
            since=since,
            until=until,
            limit=limit,
            record_ids=record_ids,
            record_type="observation",
            label=lambda observation: observation.statement,
        )


class InMemoryRelationRepository(InMemoryTemporalRepository[Relation]):
    """In-memory implementation of RelationRepository.

    Inherits all temporal methods from InMemoryTemporalRepository.
    Adds save() for the RelationRepository protocol and list_by_entity()
    for graph expansion queries.
    """

    def save(self, relation: Relation, provenance: Provenance) -> None:
        self.save_record(relation, provenance)

    def list_projections_by_space(
        self,
        *,
        space: str,
        state: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        record_ids: set[str] | None = None,
    ) -> list[RecordProjection]:
        return self._list_record_projections_by_space(
            space=space,
            state=state,
            since=since,
            until=until,
            limit=limit,
            record_ids=record_ids,
            record_type="relation",
            label=lambda relation: relation.statement,
        )

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

    def __init__(self, record_keys: set[tuple[str, str]] | None = None) -> None:
        self._tasks: dict[tuple[str, str], Task] = {}
        self._provenance: dict[tuple[str, str], Provenance] = {}
        self._record_keys = record_keys if record_keys is not None else set()

    def save(self, task: Task, provenance: Provenance) -> None:
        key = (task.space, task.id)
        if key in self._record_keys:
            raise DuplicateRecordError(
                record_kind="task",
                space=task.space,
                record_id=task.id,
            )
        self._tasks[key] = task
        self._provenance[key] = provenance
        self._record_keys.add(key)

    def list_by_space(self, space: str) -> list[Task]:
        """Return all tasks in the given space."""
        return [task for (s, _), task in self._tasks.items() if s == space]

    def list_projections_by_space(
        self,
        *,
        space: str,
        state: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        record_ids: set[str] | None = None,
    ) -> list[RecordProjection]:
        candidates: list[_ProjectionCandidate] = []
        for (record_space, _), task in self._tasks.items():
            if record_space != space:
                continue
            if record_ids is not None and task.id not in record_ids:
                continue
            if state is not None and task.lifecycle_state != state:
                continue
            provenance = self._provenance.get((space, task.id))
            creation_time = provenance.creation_time if provenance else None
            candidates.append(
                _ProjectionCandidate(
                    id=task.id,
                    type="task",
                    label=task.title,
                    lifecycle_state=task.lifecycle_state,
                    creation_time=creation_time,
                    has_provenance=provenance is not None,
                )
            )
        return _bounded_projections(candidates, space, since, until, limit)

    def get(self, *, space: str, task_id: str) -> Task | None:
        return self._tasks.get((space, task_id))

    def evict(self, *, space: str, task_id: str) -> None:
        """Erase a Task from all in-memory structures it inhabits.

        Storage-context eviction: drops the task, its provenance, and its
        uniqueness key together so the multi-structure invariant stays intact.
        Used only by the ForgetRepository adapter.
        """
        key = (space, task_id)
        self._tasks.pop(key, None)
        self._provenance.pop(key, None)
        self._record_keys.discard(key)

    def get_provenance(self, *, space: str, task_id: str) -> Provenance | None:
        return self._provenance.get((space, task_id))

    def save_provenance(
        self,
        *,
        space: str,
        task_id: str,
        provenance: Provenance,
    ) -> None:
        self._provenance[(space, task_id)] = provenance

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


class InMemoryForgetRepository:
    """In-memory adapter for Forget."""

    def __init__(
        self,
        *,
        entity_repo: InMemoryEntityRepository,
        decision_repo: InMemoryDecisionRepository,
        observation_repo: InMemoryObservationRepository,
        relation_repo: InMemoryRelationRepository,
        task_repo: InMemoryTaskRepository,
        about_repo: InMemoryAboutRepository,
    ) -> None:
        self._entity_repo = entity_repo
        self._decision_repo = decision_repo
        self._observation_repo = observation_repo
        self._relation_repo = relation_repo
        self._task_repo = task_repo
        self._about_repo = about_repo

    def get_forget_target(
        self,
        *,
        space: str,
        record_id: str,
        record_kind: str,
    ) -> ForgetTarget | None:
        if record_kind == "decision":
            record = self._decision_repo.get(space, record_id)
        elif record_kind == "observation":
            record = self._observation_repo.get(space, record_id)
        elif record_kind == "task":
            record = self._task_repo.get(space=space, task_id=record_id)
        else:
            return None
        if record is None:
            return None
        return ForgetTarget(
            id=record_id,
            record_kind=record_kind,
            space=space,
            supersedes=getattr(record, "supersedes", None),
            superseded_by=getattr(record, "superseded_by", None),
        )

    def forget_record(
        self,
        *,
        space: str,
        record_id: str,
        record_kind: str,
    ) -> None:
        if record_kind == "decision":
            self._decision_repo.evict(space, record_id)
        elif record_kind == "observation":
            self._observation_repo.evict(space, record_id)
        elif record_kind == "task":
            self._task_repo.evict(space=space, task_id=record_id)
        self._about_repo.unlink(space, record_id)

    def entity_exists(self, *, space: str, entity_id: str) -> bool:
        return self._entity_repo.get(space, entity_id) is not None

    def forget_entity(self, *, space: str, entity_id: str) -> None:
        self._entity_repo.evict(space, entity_id)

        relations = list(self._relation_repo.list_by_entity(space, entity_id))
        for relation in relations:
            self._relation_repo.evict(space, relation.id)

        self._about_repo.unlink_entity(space, entity_id)
