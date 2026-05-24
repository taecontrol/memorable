from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol

from memorable.core.models import (
    Decision,
    DecisionProvenance,
    Entity,
    MemorySpace,
    Provenance,
    Task,
    TaskProvenance,
)
from memorable.core.ports import (
    DecisionRepository,
    EntityRepository,
    MemorySpaceRepository,
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
            entity_id=entity_id,
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
    provenance: DecisionProvenance


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

        provenance = DecisionProvenance(
            decision_id=decision_id,
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


class CurrentTruthService:
    """Application service that follows supersession chain to find current Decision."""

    def __init__(self, repository: DecisionRepository) -> None:
        self._repository = repository

    def current(self, *, space: str, decision_id: str) -> Decision | None:
        """Return the current Decision, following supersession chain."""
        return self._repository.get_current(space=space, decision_id=decision_id)


class PointInTimeTruthService:
    """Application service that returns the Decision valid at a specific time."""

    def __init__(self, repository: DecisionRepository) -> None:
        self._repository = repository

    def at(self, *, space: str, decision_id: str, at: datetime) -> Decision | None:
        """Return the Decision that was valid at the given time."""
        return self._repository.get_at(space=space, decision_id=decision_id, at=at)


class InspectDecisionHistoryService:
    """Application service that returns the full supersession chain for a Decision."""

    def __init__(self, repository: DecisionRepository) -> None:
        self._repository = repository

    def history(self, *, space: str, decision_id: str) -> list[Decision]:
        """Return the supersession chain starting from the given Decision."""
        return self._repository.get_history(space=space, decision_id=decision_id)


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
    provenance: TaskProvenance


class RememberTaskService:
    """Application service that validates and persists a Task with provenance.

    Validates that the MemoryProfile has at least one record that extends Task.
    """

    def __init__(self, repository: object, profile: MemoryProfile) -> None:
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

        provenance = TaskProvenance(
            task_id=task_id,
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

    def __init__(self, repository: object) -> None:
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

        # Build event id from task id suffix
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

    def __init__(self, repository: object) -> None:
        self._repository = repository

    def inspect(
        self,
        *,
        space: str,
        task_id: str,
        as_of: datetime | None = None,
    ) -> Task | None:
        """Return the Task state, optionally at a specific point in time."""
        if as_of is not None:
            return self._repository.get_at(space=space, task_id=task_id, at=as_of)
        return self._repository.get(space=space, task_id=task_id)
