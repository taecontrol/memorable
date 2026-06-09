"""Cross-backend migration over Memorable storage ports."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from memorable.core.context import ApplicationContext
from memorable.core.models import Provenance, ProvenanceIntegrityError, Task


@dataclass(frozen=True)
class MigrationSummary:
    """Per-kind counts copied by a migration run."""

    memory_spaces: int = 0
    entities: int = 0
    decisions: int = 0
    observations: int = 0
    tasks: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "memory_spaces": self.memory_spaces,
            "entities": self.entities,
            "decisions": self.decisions,
            "observations": self.observations,
            "tasks": self.tasks,
        }


class _MigratableRecord(Protocol):
    id: str


class _MigratableRepository[T: _MigratableRecord](Protocol):
    def list_by_space(self, space: str) -> list[T]: ...

    def get_provenance(self, space: str, record_id: str) -> Provenance | None: ...

    def save(self, record: T, provenance: Provenance) -> None: ...


def _copy_records_with_provenance[T: _MigratableRecord](
    *,
    source_repo: _MigratableRepository[T],
    target_repo: _MigratableRepository[T],
    space: str,
    kind: str,
) -> int:
    copied = 0
    source_records = sorted(
        source_repo.list_by_space(space),
        key=lambda record: record.id,
    )
    for record in source_records:
        provenance = source_repo.get_provenance(space, record.id)
        if provenance is None:
            raise ProvenanceIntegrityError(
                f"Provenance missing for {kind} '{record.id}' in MemorySpace '{space}'."
            )
        target_repo.save(record, provenance)
        copied += 1
    return copied


def _copy_tasks_with_completion_replay(
    *,
    source: ApplicationContext,
    target: ApplicationContext,
    space: str,
) -> int:
    copied = 0
    source_tasks = sorted(
        source.task_repo.list_by_space(space),
        key=lambda task: task.id,
    )
    for task in source_tasks:
        provenance = source.task_repo.get_provenance(space=space, task_id=task.id)
        if provenance is None:
            raise ProvenanceIntegrityError(
                f"Provenance missing for task '{task.id}' in MemorySpace '{space}'."
            )
        if task.lifecycle_state == "completed":
            _save_task_for_completion_replay(
                target=target,
                task=task,
                provenance=provenance,
            )
        else:
            target.task_repo.save(task, provenance)
        copied += 1
    return copied


def _save_task_for_completion_replay(
    *,
    target: ApplicationContext,
    task: Task,
    provenance: Provenance,
) -> None:
    if task.completion_time is None or task.completion_event_id is None:
        raise ValueError(f"Completed Task '{task.id}' is missing completion metadata.")
    target.task_repo.save(
        replace(
            task,
            lifecycle_state="open",
            completion_time=None,
            completion_event_id=None,
        ),
        provenance,
    )
    target.task_repo.complete(
        space=task.space,
        task_id=task.id,
        completion_time=task.completion_time,
        completion_event_id=task.completion_event_id,
    )


def migrate_memory_space(
    *,
    source: ApplicationContext,
    target: ApplicationContext,
    space: str,
) -> MigrationSummary:
    """Copy one MemorySpace from source ports to target ports."""
    source_space = source.memory_space_repo.get_space(space)
    if source_space is None:
        raise ValueError(f"MemorySpace '{space}' not found in source.")

    if target.memory_space_repo.get_space(source_space.name) is not None:
        raise ValueError(
            f"Target MemorySpace '{source_space.name}' already exists; "
            "migration requires an empty target space."
        )

    with target.atomic_write():
        target.memory_space_repo.create_space(source_space.name)

        entities = _copy_records_with_provenance(
            source_repo=source.entity_repo,
            target_repo=target.entity_repo,
            space=space,
            kind="entity",
        )
        decisions = _copy_records_with_provenance(
            source_repo=source.decision_repo,
            target_repo=target.decision_repo,
            space=space,
            kind="decision",
        )
        observations = _copy_records_with_provenance(
            source_repo=source.observation_repo,
            target_repo=target.observation_repo,
            space=space,
            kind="observation",
        )
        tasks = _copy_tasks_with_completion_replay(
            source=source,
            target=target,
            space=space,
        )

    return MigrationSummary(
        memory_spaces=1,
        entities=entities,
        decisions=decisions,
        observations=observations,
        tasks=tasks,
    )
