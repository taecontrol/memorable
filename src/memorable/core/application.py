from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol

from memorable.core.models import Entity, MemorySpace, Provenance
from memorable.core.ports import EntityRepository, MemorySpaceRepository
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

    def __init__(
        self, repository: EntityRepository, profile: MemoryProfile
    ) -> None:
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


class InspectProvenanceService:
    """Application service that retrieves provenance for an Entity.

    Shared by CLI and MCP adapters.
    """

    def __init__(self, repository: EntityRepository) -> None:
        self._repository = repository

    def inspect(self, *, space: str, entity_id: str) -> Provenance | None:
        """Return the provenance for an Entity, or None if not found."""
        return self._repository.get_provenance(space=space, entity_id=entity_id)
