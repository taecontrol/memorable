from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol

from memorable.core.models import (
    Decision,
    Entity,
    MemorySpace,
    Observation,
    Provenance,
    Task,
)
from memorable.core.ports import (
    DecisionRepository,
    EntityRepository,
    MemorySpaceRepository,
    ObservationRepository,
    TaskRepository,
    TemporalRecord,
    TemporalRecordRepository,
)
from memorable.core.profile import MemoryProfile, load_profile_from_yaml
from memorable.core.temporal import make_episode_id


@dataclass(frozen=True)
class DiagnosticStatus:
    product: str
    memory_space_scope: str
    service: str
    core_language: tuple[str, ...]

    def as_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["core_language"] = list(self.core_language)
        return payload


class StatusService(Protocol):
    """Contract for any service that returns a Memorable Core diagnostic payload."""

    def status(self) -> dict[str, object]: ...


def build_status_payload(
    service: StatusService | None = None,
) -> dict[str, object]:
    """Build a diagnostic payload using the given service or a default."""
    diagnostic_service = service or DiagnosticService()
    return diagnostic_service.status()


class DiagnosticService:
    """Application service shared by human and agent-facing adapters."""

    def status(self) -> dict[str, object]:
        return DiagnosticStatus(
            product="Memorable",
            memory_space_scope="project",
            service="diagnostics",
            core_language=(
                "MemorySpace",
                "MemoryProfile",
                "MemoryRecord",
                "Source",
                "Provenance",
                "Temporal Semantics",
            ),
        ).as_payload()


@dataclass(frozen=True)
class InitResult:
    """Result of initializing a MemorySpace from a MemoryProfile."""

    space: MemorySpace
    profile: MemoryProfile
    already_existed: bool


class InitService:
    """Application service that initializes a MemorySpace from a MemoryProfile.

    Shared by CLI and MCP adapters — both use the same validation and
    initialization logic.
    """

    def __init__(self, repository: MemorySpaceRepository) -> None:
        self._repository = repository

    def initialize(self, profile_yaml: str) -> InitResult:
        """Load, validate, and initialize a MemorySpace from profile YAML.

        Raises ProfileValidationError if the profile is invalid.
        """
        profile = load_profile_from_yaml(profile_yaml)
        space_name = profile.space.name

        existing = self._repository.get_space(space_name)
        if existing is not None:
            return InitResult(space=existing, profile=profile, already_existed=True)

        space = self._repository.create_space(space_name)
        return InitResult(space=space, profile=profile, already_existed=False)


@dataclass(frozen=True)
class RememberEntityResult:
    """Result of remembering an Entity with provenance."""

    entity: Entity
    provenance: Provenance


class RememberEntityService:
    """Application service that validates and persists an Entity with provenance.

    Shared by CLI and MCP adapters — both use the same validation and
    persistence logic.
    """

    def __init__(self, repository: EntityRepository, profile: MemoryProfile) -> None:
        self._repository = repository
        self._profile = profile

    def remember(
        self,
        *,
        space: str,
        entity_id: str,
        entity_type: str,
        name: str,
        source_id: str,
        at: datetime,
        writer: str = "agent:memorable",
        reason: str = "",
    ) -> RememberEntityResult:
        """Validate entity type against MemoryProfile, create provenance, persist.

        Raises ValueError if the entity type is not declared in the profile.
        """
        declared_names = {e.name for e in self._profile.entities}
        if entity_type not in declared_names:
            raise ValueError(
                f"Entity type '{entity_type}' is not declared in the "
                f"MemoryProfile for space '{self._profile.space.name}'. "
                f"Declared types: {sorted(declared_names)}."
            )

        entity = Entity(
            id=entity_id,
            entity_type=entity_type,
            name=name,
            space=space,
        )

        episode_id = make_episode_id(source_id, at)

        provenance = Provenance(
            record_id=entity_id,
            record_kind="entity",
            source_id=source_id,
            episode_id=episode_id,
            writer=writer,
            reason=reason,
            creation_time=at,
            validity_time=at,
        )

        self._repository.save(entity, provenance)

        return RememberEntityResult(entity=entity, provenance=provenance)


@dataclass(frozen=True)
class RememberDecisionResult:
    """Result of remembering a Decision with provenance."""

    decision: Decision
    provenance: Provenance


class RememberDecisionService:
    """Application service that validates and persists a Decision with provenance.

    Validates that the MemoryProfile has at least one record that extends Decision.
    When supersedes is provided, marks the old decision as superseded.
    """

    def __init__(self, repository: DecisionRepository, profile: MemoryProfile) -> None:
        self._repository = repository
        self._profile = profile

    def remember(
        self,
        *,
        space: str,
        decision_id: str,
        statement: str,
        source_id: str,
        at: datetime,
        writer: str = "agent:memorable",
        reason: str = "",
        supersedes: str | None = None,
    ) -> RememberDecisionResult:
        """Validate record type against MemoryProfile, create provenance, persist.

        Raises ValueError if the profile has no record type extending Decision.
        """
        has_decision_record = any(
            r.extends == "Decision" for r in self._profile.records
        )
        if not has_decision_record:
            raise ValueError(
                f"No record type extending Decision is declared in the "
                f"MemoryProfile for space '{self._profile.space.name}'. "
                f"Add a record with 'extends: Decision' to your profile."
            )

        decision = Decision(
            id=decision_id,
            statement=statement,
            space=space,
            validity_time=at,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=supersedes,
            superseded_by=None,
        )

        episode_id = make_episode_id(source_id, at)

        provenance = Provenance(
            record_id=decision_id,
            record_kind="decision",
            source_id=source_id,
            episode_id=episode_id,
            writer=writer,
            reason=reason,
            creation_time=at,
            validity_time=at,
        )

        self._repository.save(decision, provenance)

        if supersedes is not None:
            self._repository.mark_superseded(
                space=space,
                decision_id=supersedes,
                superseded_by=decision_id,
                invalidation_time=at,
            )

        return RememberDecisionResult(decision=decision, provenance=provenance)


@dataclass(frozen=True)
class RememberObservationResult:
    """Result of remembering an Observation with provenance."""

    observation: Observation
    provenance: Provenance


class RememberObservationService:
    """Application service that validates and persists an Observation with provenance.

    Validates that the MemoryProfile has at least one record that extends Observation.
    When supersedes is provided, marks the old observation as superseded.
    """

    def __init__(
        self,
        repository: ObservationRepository,
        profile: MemoryProfile,
    ) -> None:
        self._repository = repository
        self._profile = profile

    def remember(
        self,
        *,
        space: str,
        observation_id: str,
        statement: str,
        source_id: str,
        at: datetime,
        writer: str = "agent:memorable",
        reason: str = "",
        supersedes: str | None = None,
    ) -> RememberObservationResult:
        """Validate record type against MemoryProfile, create provenance, persist.

        Raises ValueError if the profile has no record type extending Observation.
        """
        has_observation_record = any(
            r.extends == "Observation" for r in self._profile.records
        )
        if not has_observation_record:
            raise ValueError(
                f"No record type extending Observation is declared in the "
                f"MemoryProfile for space '{self._profile.space.name}'. "
                f"Add a record with 'extends: Observation' to your profile."
            )

        observation = Observation(
            id=observation_id,
            statement=statement,
            space=space,
            validity_time=at,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=supersedes,
            superseded_by=None,
        )

        episode_id = make_episode_id(source_id, at)

        provenance = Provenance(
            record_id=observation_id,
            record_kind="observation",
            source_id=source_id,
            episode_id=episode_id,
            writer=writer,
            reason=reason,
            creation_time=at,
            validity_time=at,
        )

        self._repository.save(observation, provenance)

        if supersedes is not None:
            self._repository.mark_superseded(
                space=space,
                observation_id=supersedes,
                superseded_by=observation_id,
                invalidation_time=at,
            )

        return RememberObservationResult(observation=observation, provenance=provenance)


class CurrentTruthService:
    """Application service that follows supersession chain to find the current record.

    Works with any repository satisfying TemporalRecordRepository: the returned
    record must have id, superseded_by, and lifecycle_state attributes.
    """

    def __init__(self, repository: TemporalRecordRepository) -> None:
        self._repository = repository

    def current(self, *, space: str, record_id: str) -> TemporalRecord | None:
        """Return the current record, following the supersession chain."""
        # Positional call: DecisionRepository.get() uses 'decision_id' while
        # TemporalRecordRepository uses 'record_id'. Positional avoids mismatch.
        record = self._repository.get(space, record_id)
        if record is None:
            return None
        visited: set[str] = {record.id}
        while record.superseded_by is not None:
            if record.superseded_by in visited:
                break
            visited.add(record.superseded_by)
            next_record = self._repository.get(space, record.superseded_by)
            if next_record is None:
                break
            record = next_record
        return record


class PointInTimeTruthService:
    """Application service that returns the record valid at a specific time.

    Works with any repository satisfying TemporalRecordRepository: the returned
    record must have id, superseded_by, invalidation_time, and lifecycle_state.
    """

    def __init__(self, repository: TemporalRecordRepository) -> None:
        self._repository = repository

    def at(
        self, *, space: str, record_id: str, at: datetime,
    ) -> TemporalRecord | None:
        """Return the record that was valid at the given time."""
        # Positional call: avoids keyword name mismatch across repositories.
        record = self._repository.get(space, record_id)
        if record is None:
            return None
        visited: set[str] = {record.id}
        current = record
        while True:
            if current.invalidation_time is None or at < current.invalidation_time:
                return current
            if current.superseded_by is None:
                return current
            if current.superseded_by in visited:
                return current
            visited.add(current.superseded_by)
            next_record = self._repository.get(space, current.superseded_by)
            if next_record is None:
                return current
            current = next_record


class InspectHistoryService:
    """Return the full supersession chain for a temporal record.

    Works with any repository satisfying TemporalRecordRepository:
    the returned records must have id and superseded_by attributes.
    """

    def __init__(self, repository: TemporalRecordRepository) -> None:
        self._repository = repository

    def history(self, *, space: str, record_id: str) -> list[TemporalRecord]:
        """Return the supersession chain starting from the given record."""
        # Positional call: avoids keyword name mismatch across repositories.
        record = self._repository.get(space, record_id)
        if record is None:
            return []
        chain = [record]
        visited: set[str] = {record.id}
        while record.superseded_by is not None:
            if record.superseded_by in visited:
                break
            visited.add(record.superseded_by)
            next_record = self._repository.get(space, record.superseded_by)
            if next_record is None:
                break
            chain.append(next_record)
            record = next_record
        return chain


# Backward-compatibility alias for code that imports the old name.
InspectDecisionHistoryService = InspectHistoryService


@dataclass(frozen=True)
class InvalidateResult:
    """Result of invalidating a temporal record."""

    record_id: str
    space: str
    lifecycle_state: str
    invalidation_time: datetime


class InvalidateService:
    """Generic application service that marks any temporal record as invalidated.

    Invalidation means the claim stopped being true without a successor.
    No replacement record is created. Sets lifecycle_state to "invalidated"
    and records the invalidation_time.

    Works with any repository satisfying TemporalRecordRepository.
    """

    def __init__(self, repository: TemporalRecordRepository) -> None:
        self._repository = repository

    def invalidate(
        self,
        *,
        space: str,
        record_id: str,
        at: datetime,
    ) -> InvalidateResult:
        """Invalidate a temporal record.

        Raises ValueError if the record is not found or already invalidated.
        """
        record = self._repository.get(space, record_id)
        if record is None:
            raise ValueError(
                f"Record '{record_id}' not found in MemorySpace '{space}'."
            )
        if record.lifecycle_state == "invalidated":
            raise ValueError(
                f"Record '{record_id}' is already invalidated "
                f"in MemorySpace '{space}'."
            )

        self._repository.invalidate(
            space=space,
            record_id=record_id,
            invalidation_time=at,
        )

        return InvalidateResult(
            record_id=record_id,
            space=space,
            lifecycle_state="invalidated",
            invalidation_time=at,
        )


class InspectProvenanceService:
    """Application service that retrieves provenance for an Entity.

    Shared by CLI and MCP adapters.
    """

    def __init__(self, repository: EntityRepository) -> None:
        self._repository = repository

    def inspect(self, *, space: str, entity_id: str) -> Provenance | None:
        """Return the provenance for an Entity, or None if not found."""
        return self._repository.get_provenance(space=space, entity_id=entity_id)


@dataclass(frozen=True)
class RememberTaskResult:
    """Result of remembering a Task with provenance."""

    task: Task
    provenance: Provenance


class RememberTaskService:
    """Application service that validates and persists a Task with provenance.

    Validates that the MemoryProfile has at least one record that extends Task.
    """

    def __init__(self, repository: TaskRepository, profile: MemoryProfile) -> None:
        self._repository = repository
        self._profile = profile

    def remember(
        self,
        *,
        space: str,
        task_id: str,
        title: str,
        source_id: str,
        at: datetime,
        writer: str = "agent:memorable",
        reason: str = "",
    ) -> RememberTaskResult:
        """Validate record type against MemoryProfile, create provenance, persist.

        Raises ValueError if the profile has no record type extending Task.
        """
        has_task_record = any(r.extends == "Task" for r in self._profile.records)
        if not has_task_record:
            raise ValueError(
                f"No record type extending Task is declared in the "
                f"MemoryProfile for space '{self._profile.space.name}'. "
                f"Add a record with 'extends: Task' to your profile."
            )

        task = Task(
            id=task_id,
            title=title,
            space=space,
            lifecycle_state="open",
            validity_time=at,
            completion_time=None,
            completion_event_id=None,
        )

        episode_id = make_episode_id(source_id, at)

        provenance = Provenance(
            record_id=task_id,
            record_kind="task",
            source_id=source_id,
            episode_id=episode_id,
            writer=writer,
            reason=reason,
            creation_time=at,
            validity_time=at,
        )

        self._repository.save(task, provenance)

        return RememberTaskResult(task=task, provenance=provenance)


@dataclass(frozen=True)
class CompleteTaskResult:
    """Result of completing a Task."""

    task: Task
    event_id: str
    completion_time: datetime


class CompleteTaskService:
    """Application service that completes a Task by appending a completion event.

    Uses append-first semantics: the original task is updated, not deleted.
    """

    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    def complete(
        self,
        *,
        space: str,
        task_id: str,
        at: datetime,
        source_id: str = "",
        writer: str = "agent:memorable",
        reason: str = "",
    ) -> CompleteTaskResult:
        """Complete a Task. Raises ValueError if not found or already completed."""
        task = self._repository.get(space=space, task_id=task_id)
        if task is None:
            raise ValueError(f"Task '{task_id}' not found in MemorySpace '{space}'.")
        if task.lifecycle_state == "completed":
            raise ValueError(f"Task '{task_id}' is already completed.")

        # Derive a deterministic event ID so completion events are
        # idempotent-safe and traceable back to the task they closed.
        # Format: event:complete-task:<task-suffix>
        task_suffix = task_id.split(":", 1)[-1] if ":" in task_id else task_id
        event_id = f"event:complete-task:{task_suffix}"

        self._repository.complete(
            space=space,
            task_id=task_id,
            completion_time=at,
            completion_event_id=event_id,
        )

        completed = self._repository.get(space=space, task_id=task_id)
        return CompleteTaskResult(task=completed, event_id=event_id, completion_time=at)


class InspectTaskService:
    """Application service that inspects task lifecycle at current or as-of time."""

    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    def inspect(
        self,
        *,
        space: str,
        task_id: str,
        as_of: datetime | None = None,
    ) -> Task | None:
        """Return the Task state, optionally at a specific point in time."""
        task = self._repository.get(space=space, task_id=task_id)
        if task is None:
            return None
        if as_of is None:
            return task
        # Temporal projection: validate visibility and reconstruct state
        if as_of < task.validity_time:
            return None
        if (
            task.lifecycle_state == "completed"
            and task.completion_time
            and as_of < task.completion_time
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
