"""MemoryProfile loading and validation.

A MemoryProfile is the project-specific schema that specializes the universal
memory kernel for one MemorySpace.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from memorable.core.attributes import SUPPORTED_ATTRIBUTE_TYPES, AttributeDeclaration

SUPPORTED_VERSIONS = (1,)
TOP_LEVEL_KEYS = frozenset({"version", "space", "entities", "relations", "records"})
SPACE_KEYS = frozenset({"name", "description"})
ENTITY_KEYS = frozenset({"name", "description", "attributes"})
ATTRIBUTE_KEYS = frozenset({"name", "type"})
RELATION_KEYS = frozenset({"name", "description"})
RECORD_KEYS = frozenset({"name", "extends", "description"})
TARGET_DESIGN_KEYS = frozenset({"metrics", "workflows", "common_queries"})

WRITABLE_RECORD_TYPES = frozenset({"Decision", "Observation", "Task"})


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
class EntityDeclaration:
    """A project-specific entity type declared in a MemoryProfile."""

    name: str
    description: str = ""
    attributes: tuple[AttributeDeclaration, ...] = ()


@dataclass(frozen=True)
class RelationDeclaration:
    """A project-specific relation type declared in a MemoryProfile."""

    name: str
    description: str = ""


@dataclass(frozen=True)
class RecordDeclaration:
    """A project-specific record type that extends a kernel type."""

    name: str
    extends: str
    description: str = ""


@dataclass(frozen=True)
class MemoryProfile:
    """Project-specific schema for one MemorySpace.

    Specializes the universal memory kernel with domain-specific entity types,
    record types, relation types, and other project-level configuration.
    """

    version: int
    space: SpaceDeclaration
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
    _validate_top_level_keys(data)
    _validate_space(data)
    _validate_entities(data)
    _validate_relations(data)
    _validate_records(data)

    space_data = data.get("space", {})
    space = SpaceDeclaration(
        name=space_data.get("name", ""),
        description=space_data.get("description", ""),
    )

    entities = tuple(
        EntityDeclaration(
            name=e["name"],
            description=e.get("description", ""),
            attributes=tuple(
                AttributeDeclaration(name=attribute["name"], type=attribute["type"])
                for attribute in e.get("attributes", [])
            ),
        )
        for e in data.get("entities", [])
    )

    relations = tuple(
        RelationDeclaration(name=r["name"], description=r.get("description", ""))
        for r in data.get("relations", [])
    )

    records = tuple(
        RecordDeclaration(
            name=r["name"],
            extends=r["extends"],
            description=r.get("description", ""),
        )
        for r in data.get("records", [])
    )

    return MemoryProfile(
        version=data["version"],
        space=space,
        entities=entities,
        relations=relations,
        records=records,
    )


def profile_summary(profile: MemoryProfile) -> dict[str, object]:
    """Return the shared inspect/MCP summary for a MemoryProfile."""
    return {
        "space_name": profile.space.name,
        "description": profile.space.description,
        "entity_count": len(profile.entities),
        "record_count": len(profile.records),
        "relation_count": len(profile.relations),
        "entities": [
            {
                "name": entity.name,
                "description": entity.description,
                "attributes": [
                    {"name": attribute.name, "type": attribute.type}
                    for attribute in entity.attributes
                ],
            }
            for entity in profile.entities
        ],
        "relations": [
            {"name": relation.name, "description": relation.description}
            for relation in profile.relations
        ],
        "records": [
            {
                "name": record.name,
                "extends": record.extends,
                "description": record.description,
            }
            for record in profile.records
        ],
    }


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


def _validate_top_level_keys(data: dict) -> None:
    _validate_allowed_keys(data, TOP_LEVEL_KEYS, "MemoryProfile")


def _validate_allowed_keys(
    data: dict, allowed_keys: frozenset[str], location: str
) -> None:
    for key in data:
        if key in allowed_keys:
            continue
        _raise_unknown_key(key, location)


def _raise_unknown_key(key: object, location: str) -> None:
    if key == "write_policy":
        raise ProfileValidationError(
            "Write Policy was removed from MemoryProfile v1 by ADR-0014; "
            "delete 'write_policy' from the profile."
        )
    if key in TARGET_DESIGN_KEYS:
        raise ProfileValidationError(
            f"'{key}' is a target-design key from the ADR-0002 sketch, "
            "but it is not yet parsed by MemoryProfile v1."
        )
    raise ProfileValidationError(
        f"{location} has unrecognized key '{key}' for MemoryProfile v1."
    )


def _validate_space(data: dict) -> None:
    space_data = data.get("space")
    if not isinstance(space_data, dict) or not space_data.get("name"):
        raise ProfileValidationError(
            "MemoryProfile requires 'space.name' to identify the MemorySpace."
        )
    _validate_allowed_keys(space_data, SPACE_KEYS, "MemoryProfile space")


def _validate_entities(data: dict) -> None:
    for i, entity in enumerate(data.get("entities", [])):
        if not isinstance(entity, dict) or not entity.get("name"):
            raise ProfileValidationError(
                f"Entity at position {i} must have a non-empty 'name'."
            )
        _validate_allowed_keys(
            entity, ENTITY_KEYS, f"Entity declaration at position {i}"
        )
        attributes = entity.get("attributes", [])
        if not isinstance(attributes, list):
            raise ProfileValidationError(
                f"Entity '{entity['name']}' attributes must be a list of "
                "Attribute declarations."
            )
        for attribute_position, attribute in enumerate(attributes):
            location = (
                f"Attribute declaration at position {attribute_position} "
                f"on Entity '{entity['name']}'"
            )
            if not isinstance(attribute, dict) or not attribute.get("name"):
                raise ProfileValidationError(
                    f"{location} must have a non-empty 'name'."
                )
            _validate_allowed_keys(attribute, ATTRIBUTE_KEYS, location)
            attribute_type = attribute.get("type")
            if attribute_type not in SUPPORTED_ATTRIBUTE_TYPES:
                raise ProfileValidationError(
                    f"Attribute '{attribute.get('name')}' has unsupported type "
                    f"'{attribute_type}' for MemoryProfile v1. "
                    f"Supported Attribute types: {list(SUPPORTED_ATTRIBUTE_TYPES)}."
                )


def _validate_relations(data: dict) -> None:
    for i, relation in enumerate(data.get("relations", [])):
        if not isinstance(relation, dict) or not relation.get("name"):
            raise ProfileValidationError(
                f"Relation at position {i} must have a non-empty 'name'."
            )
        _validate_allowed_keys(
            relation, RELATION_KEYS, f"Relation declaration at position {i}"
        )


def _validate_records(data: dict) -> None:
    for i, record in enumerate(data.get("records", [])):
        if not isinstance(record, dict) or not record.get("name"):
            raise ProfileValidationError(
                f"Record at position {i} must have a non-empty 'name'."
            )
        _validate_allowed_keys(
            record, RECORD_KEYS, f"Record declaration at position {i}"
        )
        if "extends" not in record:
            raise ProfileValidationError(
                f"Record '{record['name']}' must declare 'extends' as one of "
                f"{sorted(WRITABLE_RECORD_TYPES)}."
            )
        extends = record["extends"]
        if extends not in WRITABLE_RECORD_TYPES:
            raise ProfileValidationError(
                f"Record '{record['name']}' extends '{extends}', "
                f"but records may only extend one of: {sorted(WRITABLE_RECORD_TYPES)}."
            )
