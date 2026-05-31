from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from heapq import heappop, heappush
from typing import Protocol

from memorable.core.models import (
    Decision,
    Entity,
    MemorySpace,
    Observation,
    Provenance,
    RecordProjection,
    Relation,
    Task,
)
from memorable.core.ports import (
    AboutRepository,
    DecisionRepository,
    EntityRepository,
    MemorySpaceRepository,
    ObservationRepository,
    RelationRepository,
    TaskRepository,
    TemporalRecord,
    TemporalRecordRepository,
)
from memorable.core.profile import MemoryProfile, load_profile_from_yaml
from memorable.core.temporal import make_episode_id


class UndeclaredTypeError(ValueError):
    """Raised when a write names an Entity or Relation type the MemoryProfile
    does not declare.

    Subclasses ``ValueError`` so existing ``except ValueError`` handlers and
    message-matching tests keep working. The MCP boundary uses the type (rather
    than the message wording) to decide that this error is fixable by evolving
    the MemoryProfile, and so should carry the memorable_guide("profiles") hint.
    """


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
            raise UndeclaredTypeError(
                f"Entity type '{entity_type}' is not declared in the "
                f"MemoryProfile for space '{self._profile.space.name}'. "
                f"Declared types: {sorted(declared_names)}. "
                "Evolve the MemoryProfile before remembering this Entity type."
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


class AboutLinker:
    """Application service that owns About write behavior."""

    def __init__(
        self,
        *,
        entity_repo: EntityRepository,
        about_repo: AboutRepository,
    ) -> None:
        self._entity_repo = entity_repo
        self._about_repo = about_repo

    def link(self, *, space: str, record_id: str, entity_ids: list[str]) -> None:
        """Link a MemoryRecord to existing Entities it is about.

        Raises ValueError if any target Entity is missing. No About links are
        written unless every target exists.
        """
        self.verify_targets(space=space, entity_ids=entity_ids)
        self._about_repo.link(space, record_id, entity_ids)

    def restaple(self, *, space: str, record_id: str, entity_ids: list[str]) -> None:
        """Replace all About links for a MemoryRecord after verification."""
        self.verify_targets(space=space, entity_ids=entity_ids)
        self._about_repo.unlink(space, record_id)
        self._about_repo.link(space, record_id, entity_ids)

    def verify_targets(self, *, space: str, entity_ids: list[str]) -> None:
        """Raise if any About target Entity does not exist."""
        for entity_id in entity_ids:
            if self._entity_repo.get(space, entity_id) is None:
                raise ValueError(
                    f"About target Entity '{entity_id}' not found "
                    f"in MemorySpace '{space}'. Create the Entity before "
                    "linking a MemoryRecord to it."
                )


def _link_about(
    about_linker: AboutLinker | None,
    *,
    space: str,
    record_id: str,
    about: list[str] | None,
) -> None:
    if not about:
        return
    if about_linker is None:
        raise ValueError("AboutLinker is required to write About links.")
    about_linker.link(space=space, record_id=record_id, entity_ids=about)


def _verify_about_targets(
    about_linker: AboutLinker | None,
    *,
    space: str,
    about: list[str] | None,
) -> None:
    if not about:
        return
    if about_linker is None:
        raise ValueError("AboutLinker is required to write About links.")
    about_linker.verify_targets(space=space, entity_ids=about)


@dataclass(frozen=True)
class RememberDecisionResult:
    """Result of remembering a Decision with provenance."""

    decision: Decision
    provenance: Provenance


class RememberDecisionService:
    """Application service that persists a Decision with provenance.

    Decision is a kernel record type: part of the universal memory kernel and
    writable without any MemoryProfile declaration. A profile ``records:`` entry
    extending Decision (e.g. ``ArchitectureDecision extends Decision``) is an
    optional specialization that enriches the type label; it is never a
    precondition for writing the base kernel type.

    This is deliberately asymmetric with Entity and Relation, which are
    project-specific by definition (there is no universal Entity or Relation
    type) and therefore must be declared in the MemoryProfile.

    When supersedes is provided, marks the old decision as superseded.
    """

    def __init__(
        self,
        repository: DecisionRepository,
        profile: MemoryProfile,
        about_linker: AboutLinker | None = None,
    ) -> None:
        self._repository = repository
        self._profile = profile
        self._about_linker = about_linker

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
        about: list[str] | None = None,
    ) -> RememberDecisionResult:
        """Create provenance and persist the Decision.

        Decision is a kernel record type, so no profile declaration is required.
        """
        _verify_about_targets(self._about_linker, space=space, about=about)

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
                record_id=supersedes,
                superseded_by=decision_id,
                invalidation_time=at,
            )

        _link_about(
            self._about_linker,
            space=space,
            record_id=decision_id,
            about=about,
        )

        return RememberDecisionResult(decision=decision, provenance=provenance)


@dataclass(frozen=True)
class RememberObservationResult:
    """Result of remembering an Observation with provenance."""

    observation: Observation
    provenance: Provenance


class RememberObservationService:
    """Application service that persists an Observation with provenance.

    Observation is a kernel record type: part of the universal memory kernel and
    writable without any MemoryProfile declaration. A profile ``records:`` entry
    extending Observation is an optional specialization, never a precondition for
    writing the base kernel type.

    This is deliberately asymmetric with Entity and Relation, which are
    project-specific by definition and must be declared in the MemoryProfile.

    When supersedes is provided, marks the old observation as superseded.
    """

    def __init__(
        self,
        repository: ObservationRepository,
        profile: MemoryProfile,
        about_linker: AboutLinker | None = None,
    ) -> None:
        self._repository = repository
        self._profile = profile
        self._about_linker = about_linker

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
        about: list[str] | None = None,
    ) -> RememberObservationResult:
        """Create provenance and persist the Observation.

        Observation is a kernel record type, so no profile declaration is required.
        """
        _verify_about_targets(self._about_linker, space=space, about=about)

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
                record_id=supersedes,
                superseded_by=observation_id,
                invalidation_time=at,
            )

        _link_about(
            self._about_linker,
            space=space,
            record_id=observation_id,
            about=about,
        )

        return RememberObservationResult(observation=observation, provenance=provenance)


@dataclass(frozen=True)
class RememberRelationResult:
    """Result of remembering a Relation with provenance."""

    relation: Relation
    provenance: Provenance


class RememberRelationService:
    """Application service that validates and persists a Relation with provenance.

    Validates that (1) the relation type is declared in the MemoryProfile,
    (2) both source and target Entities exist in the space, and
    (3) source and target are different entities.
    When supersedes is provided, marks the old relation as superseded.
    """

    def __init__(
        self,
        relation_repo: RelationRepository,
        entity_repo: EntityRepository,
        profile: MemoryProfile,
    ) -> None:
        self._relation_repo = relation_repo
        self._entity_repo = entity_repo
        self._profile = profile

    def remember(
        self,
        *,
        space: str,
        relation_id: str,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
        statement: str,
        source_id: str,
        at: datetime,
        writer: str = "agent:memorable",
        reason: str = "",
        supersedes: str | None = None,
    ) -> RememberRelationResult:
        """Validate inputs, create provenance, persist.

        Raises ValueError if:
        - relation type is not declared in the MemoryProfile
        - source or target Entity does not exist in the space
        - source and target are the same entity
        """
        # Validate relation type
        declared_names = {r.name for r in self._profile.relations}
        if relation_type not in declared_names:
            raise UndeclaredTypeError(
                f"Relation type '{relation_type}' is not declared in the "
                f"MemoryProfile for space '{self._profile.space.name}'. "
                f"Declared types: {sorted(declared_names)}. "
                "Evolve the MemoryProfile before remembering this Relation type."
            )

        # Validate self-relation
        if source_entity_id == target_entity_id:
            raise ValueError(
                f"Cannot create a self-relation: source and target are both "
                f"'{source_entity_id}'."
            )

        # Validate source entity exists
        source_entity = self._entity_repo.get(space, source_entity_id)
        if source_entity is None:
            raise ValueError(
                f"Relation source Entity '{source_entity_id}' not found "
                f"in MemorySpace '{space}'."
            )

        # Validate target entity exists
        target_entity = self._entity_repo.get(space, target_entity_id)
        if target_entity is None:
            raise ValueError(
                f"Relation target Entity '{target_entity_id}' not found "
                f"in MemorySpace '{space}'."
            )

        relation = Relation(
            id=relation_id,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relation_type=relation_type,
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
            record_id=relation_id,
            record_kind="relation",
            source_id=source_id,
            episode_id=episode_id,
            writer=writer,
            reason=reason,
            creation_time=at,
            validity_time=at,
        )

        self._relation_repo.save(relation, provenance)

        if supersedes is not None:
            self._relation_repo.mark_superseded(
                space=space,
                record_id=supersedes,
                superseded_by=relation_id,
                invalidation_time=at,
            )

        return RememberRelationResult(relation=relation, provenance=provenance)


class CurrentTruthService:
    """Application service that follows supersession chain to find the current record.

    Works with any repository satisfying TemporalRecordRepository: the returned
    record must have id, superseded_by, and lifecycle_state attributes.
    """

    def __init__(self, repository: TemporalRecordRepository) -> None:
        self._repository = repository

    def current(self, *, space: str, record_id: str) -> TemporalRecord | None:
        """Return the current record, following the supersession chain."""
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
        self,
        *,
        space: str,
        record_id: str,
        at: datetime,
    ) -> TemporalRecord | None:
        """Return the record that was valid at the given time."""
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
                f"Record '{record_id}' is already invalidated in MemorySpace '{space}'."
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


@dataclass(frozen=True)
class CorrectResult:
    """Result of correcting a temporal record's statement in place."""

    record_id: str
    space: str
    old_statement: str
    new_statement: str


class CorrectService:
    """Generic application service that corrects any temporal record in place.

    Correction means the old statement was never true — it was a mistake.
    The record's statement is updated in place, and provenance is replaced
    with new provenance reflecting the correction source.

    Works with any repository satisfying TemporalRecordRepository.
    """

    def __init__(
        self,
        repository: TemporalRecordRepository,
        about_linker: AboutLinker | None = None,
    ) -> None:
        self._repository = repository
        self._about_linker = about_linker

    def correct(
        self,
        *,
        space: str,
        record_id: str,
        new_statement: str,
        record_kind: str,
        source: str,
        writer: str,
        at: datetime,
        reason: str = "",
        about: list[str] | None = None,
    ) -> CorrectResult:
        """Correct a temporal record's statement in place.

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
                f"in MemorySpace '{space}'. Cannot correct an invalidated record."
            )

        old_statement = record.statement

        if about is not None:
            if self._about_linker is None:
                raise ValueError("AboutLinker is required to correct About links.")
            self._about_linker.restaple(
                space=space,
                record_id=record_id,
                entity_ids=about,
            )

        self._repository.correct(
            space=space,
            record_id=record_id,
            new_statement=new_statement,
        )

        # Build correction provenance
        episode_id = make_episode_id(source, at)
        if reason:
            provenance_reason = f"Corrected from: '{old_statement}'. Reason: {reason}."
        else:
            provenance_reason = f"Corrected from: '{old_statement}'."

        provenance = Provenance(
            record_id=record_id,
            record_kind=record_kind,
            source_id=source,
            episode_id=episode_id,
            writer=writer,
            reason=provenance_reason,
            creation_time=at,
            validity_time=at,
        )
        self._repository.save_provenance(
            space=space,
            record_id=record_id,
            provenance=provenance,
        )

        return CorrectResult(
            record_id=record_id,
            space=space,
            old_statement=old_statement,
            new_statement=new_statement,
        )


class CorrectTaskService:
    """Application service for correcting Task About membership."""

    def __init__(
        self,
        *,
        repository: TaskRepository,
        about_linker: AboutLinker,
    ) -> None:
        self._repository = repository
        self._about_linker = about_linker

    def correct(
        self,
        *,
        space: str,
        task_id: str,
        new_statement: str,
        source: str,
        writer: str,
        at: datetime,
        reason: str = "",
        about: list[str] | None = None,
    ) -> CorrectResult:
        task = self._repository.get(space=space, task_id=task_id)
        if task is None:
            raise ValueError(f"Task '{task_id}' not found in MemorySpace '{space}'.")
        if about is None:
            raise ValueError(
                "Task correction through memorable_correct currently supports "
                "About re-staple only; pass about to replace Task About links."
            )
        if new_statement != task.title:
            raise ValueError(
                "Task title correction is not supported by memorable_correct; "
                "pass the existing Task title as new_statement when re-stapling About."
            )

        self._about_linker.restaple(space=space, record_id=task_id, entity_ids=about)

        episode_id = make_episode_id(source, at)
        if reason:
            provenance_reason = f"Corrected from: '{task.title}'. Reason: {reason}."
        else:
            provenance_reason = f"Corrected from: '{task.title}'."
        self._repository.save_provenance(
            space=space,
            task_id=task_id,
            provenance=Provenance(
                record_id=task_id,
                record_kind="task",
                source_id=source,
                episode_id=episode_id,
                writer=writer,
                reason=provenance_reason,
                creation_time=at,
                validity_time=at,
            ),
        )

        return CorrectResult(
            record_id=task_id,
            space=space,
            old_statement=task.title,
            new_statement=task.title,
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
    """Application service that persists a Task with provenance.

    Task is a kernel record type: part of the universal memory kernel and
    writable without any MemoryProfile declaration. A profile ``records:`` entry
    extending Task is an optional specialization, never a precondition for
    writing the base kernel type.

    This is deliberately asymmetric with Entity and Relation, which are
    project-specific by definition and must be declared in the MemoryProfile.
    """

    def __init__(
        self,
        repository: TaskRepository,
        profile: MemoryProfile,
        about_linker: AboutLinker | None = None,
    ) -> None:
        self._repository = repository
        self._profile = profile
        self._about_linker = about_linker

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
        about: list[str] | None = None,
    ) -> RememberTaskResult:
        """Create provenance and persist the Task.

        Task is a kernel record type, so no profile declaration is required.
        """
        _verify_about_targets(self._about_linker, space=space, about=about)

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

        _link_about(
            self._about_linker,
            space=space,
            record_id=task_id,
            about=about,
        )

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


class ListRecordsService:
    """Deep query service that lists MemoryRecords in a MemorySpace.

    Memory Review's listing primitive. Fans across every MemoryRecord type
    (Decision, Observation, Relation, Task), asking each repository for bounded
    RecordProjection rows that already include Provenance Creation Time. Results
    are merged by Creation Time and capped by ``limit``.

    Entities are excluded by construction: an Entity is not a MemoryRecord, has
    no Lifecycle State, and cannot satisfy the projection. ``entity`` is
    therefore not a valid ``type`` filter.
    """

    # The MemoryRecord types Memory Review can list. Entity is deliberately
    # absent: it is not a MemoryRecord and has no Lifecycle State.
    RECORD_TYPES = ("decision", "observation", "relation", "task")

    def __init__(
        self,
        *,
        decision_repo: DecisionRepository,
        observation_repo: ObservationRepository,
        relation_repo: RelationRepository,
        task_repo: TaskRepository,
        about_repo: AboutRepository | None = None,
    ) -> None:
        self._decision_repo = decision_repo
        self._observation_repo = observation_repo
        self._relation_repo = relation_repo
        self._task_repo = task_repo
        self._about_repo = about_repo

    def list_records(
        self,
        *,
        space: str,
        type: str | None = None,
        state: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        about: str | None = None,
        limit: int = 50,
    ) -> list[RecordProjection]:
        """List MemoryRecords in the space as projections, ordered by Creation Time.

        When ``type`` is given, only records of that MemoryRecord type are
        listed; when ``None``, every MemoryRecord type is listed. When ``state``
        is given, only records whose Lifecycle State matches are listed (e.g.
        ``open``, ``current``, ``completed``, ``superseded``, ``invalidated``);
        when ``None``, records in any state are listed.

        ``since`` and ``until`` bound Provenance Creation Time as a half-open
        window ``[since, until)``: ``since`` is an inclusive lower bound and
        ``until`` an exclusive upper bound. Either bound may be omitted;
        omitting both lists records of any Creation Time.

        When ``about`` is given, only records linked to that Entity by About are
        listed. All filters (``type``, ``state``, ``since``, ``until``,
        ``about``) combine with AND. Returns at most ``limit`` projections
        (default 50).

        Raises:
            ValueError: if ``type`` is not a listable MemoryRecord type (e.g.
                ``entity`` or an unknown value) — a bad-caller-input error.
            ProvenanceIntegrityError: if a listed record's Provenance join is
                missing — a store invariant violation, not a caller error.
        """
        if type is not None and type not in self.RECORD_TYPES:
            raise ValueError(
                f"Record type '{type}' cannot be listed by Memory Review. "
                f"Valid types: {list(self.RECORD_TYPES)} (or omit for all). "
                f"Entities are not MemoryRecords and are excluded."
            )

        record_ids: set[str] | None = None
        if about is not None:
            if self._about_repo is None:
                raise ValueError("AboutRepository is required for an about filter.")
            record_ids = set(self._about_repo.records_for_entity(space, about))
            if not record_ids:
                return []

        repos = (
            ("decision", self._decision_repo),
            ("observation", self._observation_repo),
            ("relation", self._relation_repo),
            ("task", self._task_repo),
        )
        streams: list[list[RecordProjection]] = []
        heap: list[tuple[datetime, str, str, int, int]] = []

        for record_type, repo in repos:
            if type is not None and record_type != type:
                continue
            stream = repo.list_projections_by_space(
                space=space,
                state=state,
                since=since,
                until=until,
                limit=limit,
                record_ids=record_ids,
            )
            if not stream:
                continue
            stream_index = len(streams)
            streams.append(stream)
            first = stream[0]
            heappush(heap, (first.creation_time, first.id, first.type, stream_index, 0))

        projections: list[RecordProjection] = []
        while heap and len(projections) < limit:
            _, _, _, stream_index, projection_index = heappop(heap)
            projection = streams[stream_index][projection_index]
            projections.append(projection)

            next_index = projection_index + 1
            if next_index < len(streams[stream_index]):
                next_projection = streams[stream_index][next_index]
                heappush(
                    heap,
                    (
                        next_projection.creation_time,
                        next_projection.id,
                        next_projection.type,
                        stream_index,
                        next_index,
                    ),
                )

        return projections


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
