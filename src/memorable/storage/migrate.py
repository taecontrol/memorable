"""Cross-backend migration over Memorable storage ports."""

from __future__ import annotations

from dataclasses import dataclass

from memorable.core.context import ApplicationContext
from memorable.core.models import ProvenanceIntegrityError


@dataclass(frozen=True)
class MigrationSummary:
    """Per-kind counts copied by a migration run."""

    memory_spaces: int = 0
    entities: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "memory_spaces": self.memory_spaces,
            "entities": self.entities,
        }


def migrate_memory_space(
    *,
    source: ApplicationContext,
    target: ApplicationContext,
    space: str,
) -> MigrationSummary:
    """Copy one MemorySpace and its Entities from source ports to target ports."""
    source_space = source.memory_space_repo.get_space(space)
    if source_space is None:
        raise ValueError(f"MemorySpace '{space}' not found in source.")

    if target.memory_space_repo.get_space(source_space.name) is not None:
        raise ValueError(
            f"Target MemorySpace '{source_space.name}' already exists; "
            "migration requires an empty target space."
        )

    entities = 0
    with target.atomic_write():
        target.memory_space_repo.create_space(source_space.name)

        source_entities = sorted(
            source.entity_repo.list_by_space(space),
            key=lambda e: e.id,
        )
        for entity in source_entities:
            provenance = source.entity_repo.get_provenance(space, entity.id)
            if provenance is None:
                raise ProvenanceIntegrityError(
                    f"Provenance missing for entity '{entity.id}' "
                    f"in MemorySpace '{space}'."
                )
            target.entity_repo.save(entity, provenance)
            entities += 1

    return MigrationSummary(memory_spaces=1, entities=entities)
