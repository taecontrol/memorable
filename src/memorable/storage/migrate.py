"""Cross-backend migration over Memorable storage ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from memorable.core.context import ApplicationContext
from memorable.core.models import Provenance, ProvenanceIntegrityError


@dataclass(frozen=True)
class MigrationSummary:
    """Per-kind counts copied by a migration run."""

    memory_spaces: int = 0
    entities: int = 0
    decisions: int = 0
    observations: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "memory_spaces": self.memory_spaces,
            "entities": self.entities,
            "decisions": self.decisions,
            "observations": self.observations,
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

    return MigrationSummary(
        memory_spaces=1,
        entities=entities,
        decisions=decisions,
        observations=observations,
    )
