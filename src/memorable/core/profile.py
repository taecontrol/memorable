"""MemoryProfile loading and validation.

A MemoryProfile is the project-specific schema and policy that specializes
the universal memory kernel for one MemorySpace.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

SUPPORTED_VERSIONS = (1,)

# Kernel types that record declarations may extend
KERNEL_RECORD_TYPES = frozenset(
    {
        "MemoryRecord",
        "Decision",
        "Task",
        "Evidence",
        "Observation",
        "Measurement",
        "Event",
        "DerivedMemory",
    }
)


class ProfileValidationError(Exception):
    """Raised when a MemoryProfile contains invalid or missing information.

    Error messages use domain language only — no storage vocabulary.
    """


@dataclass(frozen=True)
class SpaceDeclaration:
    """Space identity declared in a MemoryProfile."""

    name: str
    description: str = ""


@dataclass(frozen=True)
class WritePolicy:
    """When agents may write automatically vs suggest vs require confirmation."""

    default: str = "auto"
    sensitive: str = "suggest"


@dataclass(frozen=True)
class EntityDeclaration:
    """A project-specific entity type declared in a MemoryProfile."""

    name: str


@dataclass(frozen=True)
class RelationDeclaration:
    """A project-specific relation type declared in a MemoryProfile."""

    name: str


@dataclass(frozen=True)
class RecordDeclaration:
    """A project-specific record type that extends a kernel type."""

    name: str
    extends: str = "MemoryRecord"


@dataclass(frozen=True)
class MemoryProfile:
    """Project-specific schema and policy for one MemorySpace.

    Specializes the universal memory kernel with domain-specific entity types,
    record types, write policies, and other project-level configuration.
    """

    version: int
    space: SpaceDeclaration
    write_policy: WritePolicy = field(default_factory=WritePolicy)
    entities: tuple[EntityDeclaration, ...] = ()
    relations: tuple[RelationDeclaration, ...] = ()
    records: tuple[RecordDeclaration, ...] = ()


def load_profile_from_yaml(yaml_text: str) -> MemoryProfile:
    """Parse a YAML string into a validated MemoryProfile.

    Raises ProfileValidationError with actionable messages when the profile
    is invalid or incomplete.
    """
    data = yaml.safe_load(yaml_text)
    if not isinstance(data, dict):
        raise ProfileValidationError(
            "MemoryProfile must be a YAML mapping, got empty or non-mapping content."
        )

    _validate_version(data)
    _validate_space(data)
    _validate_entities(data)
    _validate_records(data)

    space_data = data.get("space", {})
    space = SpaceDeclaration(
        name=space_data.get("name", ""),
        description=space_data.get("description", ""),
    )

    wp_data = data.get("write_policy", {})
    write_policy = WritePolicy(
        default=wp_data.get("default", "auto"),
        sensitive=wp_data.get("sensitive", "suggest"),
    )

    entities = tuple(
        EntityDeclaration(name=e["name"]) for e in data.get("entities", [])
    )

    records = tuple(
        RecordDeclaration(name=r["name"], extends=r.get("extends", "MemoryRecord"))
        for r in data.get("records", [])
    )

    return MemoryProfile(
        version=data["version"],
        space=space,
        write_policy=write_policy,
        entities=entities,
        records=records,
    )


def _validate_version(data: dict) -> None:
    if "version" not in data:
        raise ProfileValidationError(
            "MemoryProfile requires a 'version' field. Currently supported: version 1."
        )
    version = data["version"]
    if version not in SUPPORTED_VERSIONS:
        raise ProfileValidationError(
            f"MemoryProfile version {version} is not supported. "
            f"Supported versions: {sorted(SUPPORTED_VERSIONS)}."
        )


def _validate_space(data: dict) -> None:
    space_data = data.get("space")
    if not isinstance(space_data, dict) or not space_data.get("name"):
        raise ProfileValidationError(
            "MemoryProfile requires 'space.name' to identify the MemorySpace."
        )


def _validate_entities(data: dict) -> None:
    for i, entity in enumerate(data.get("entities", [])):
        if not isinstance(entity, dict) or not entity.get("name"):
            raise ProfileValidationError(
                f"Entity at position {i} must have a non-empty 'name'."
            )


def _validate_records(data: dict) -> None:
    for i, record in enumerate(data.get("records", [])):
        if not isinstance(record, dict) or not record.get("name"):
            raise ProfileValidationError(
                f"Record at position {i} must have a non-empty 'name'."
            )
        extends = record.get("extends", "MemoryRecord")
        if extends not in KERNEL_RECORD_TYPES:
            raise ProfileValidationError(
                f"Record '{record['name']}' extends '{extends}', "
                f"which is not a recognized kernel type. "
                f"Valid types: {sorted(KERNEL_RECORD_TYPES)}."
            )
