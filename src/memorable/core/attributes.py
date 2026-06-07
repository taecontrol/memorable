"""Storage-free validation for typed durable Attributes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite


@dataclass(frozen=True)
class AttributeDeclaration:
    """A typed durable Attribute declared on a MemoryProfile type."""

    name: str
    type: str


class AttributeValidationError(ValueError):
    """Raised when provided Attribute values do not match a declaration."""


SUPPORTED_ATTRIBUTE_TYPES = ("string", "number", "date", "list[string]")
AttributeValue = str | int | float | date | list[str]


def copy_attribute_values(
    values: Mapping[str, AttributeValue],
) -> dict[str, AttributeValue]:
    """Copy Attribute values so Entities do not share mutable list values."""
    copied: dict[str, AttributeValue] = {}
    for name, value in values.items():
        if isinstance(value, list):
            copied[name] = list(value)
        else:
            copied[name] = value
    return copied


def serialize_attribute_values(values: Mapping[str, object]) -> dict[str, object]:
    """Return JSON-compatible Attribute values for CLI and MCP surfaces."""
    serialized: dict[str, object] = {}
    for name, value in values.items():
        if isinstance(value, datetime):
            serialized[name] = value.isoformat()
        elif isinstance(value, date):
            serialized[name] = value.isoformat()
        elif isinstance(value, list):
            serialized[name] = list(value)
        else:
            serialized[name] = value
    return serialized


def validate_attribute_filter_values(
    declared_attribute_sets: Sequence[Sequence[AttributeDeclaration]],
    provided_values: Mapping[str, object] | None,
) -> dict[str, AttributeValue]:
    """Validate Attribute filter values across declared Entity schemas."""
    if not provided_values:
        return {}

    all_declared = [
        attribute
        for declared_attributes in declared_attribute_sets
        for attribute in declared_attributes
    ]
    filter_declarations: list[AttributeDeclaration] = []
    for name in provided_values:
        matching = [attribute for attribute in all_declared if attribute.name == name]
        if not matching:
            declared_names = sorted({attribute.name for attribute in all_declared})
            raise AttributeValidationError(
                f"Attribute filter '{name}' is not declared. "
                f"Declared Attributes: {declared_names}."
            )
        matching_types = sorted({attribute.type for attribute in matching})
        if len(matching_types) > 1:
            raise AttributeValidationError(
                f"Attribute filter '{name}' is ambiguous because it is declared "
                f"with conflicting types {matching_types} and search has no "
                "Entity type scope to choose one."
            )
        filter_declarations.append(
            AttributeDeclaration(name=name, type=matching_types[0])
        )

    return validate_attribute_values(filter_declarations, provided_values)


def validate_attribute_values(
    declared_attributes: Sequence[AttributeDeclaration],
    provided_values: Mapping[str, object] | None,
) -> dict[str, AttributeValue]:
    """Validate provided Attribute values against a declared Attribute schema."""
    if provided_values is None:
        return {}

    declared_by_name = {attribute.name: attribute for attribute in declared_attributes}
    validated: dict[str, AttributeValue] = {}
    for name, value in provided_values.items():
        if name not in declared_by_name:
            raise AttributeValidationError(
                f"Attribute '{name}' is not declared. "
                f"Declared Attributes: {sorted(declared_by_name)}."
            )
        attribute_type = declared_by_name[name].type
        if attribute_type not in SUPPORTED_ATTRIBUTE_TYPES:
            raise AttributeValidationError(
                f"Attribute '{name}' has unsupported type "
                f"'{attribute_type}'. "
                f"Supported Attribute types: {list(SUPPORTED_ATTRIBUTE_TYPES)}."
            )
        if attribute_type == "string":
            validated[name] = _validate_string_attribute(name, value)
            continue
        if attribute_type == "number":
            validated[name] = _validate_number_attribute(name, value)
            continue
        if attribute_type == "date":
            validated[name] = _validate_date_attribute(name, value)
            continue
        if attribute_type == "list[string]":
            validated[name] = _validate_list_string_attribute(name, value)
            continue
        raise AttributeValidationError(
            f"Attribute '{name}' has unsupported type '{attribute_type}'. "
            f"Supported Attribute types: {list(SUPPORTED_ATTRIBUTE_TYPES)}."
        )
    return validated


def _validate_string_attribute(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise AttributeValidationError(f"Attribute '{name}' must be a string value.")
    return value


def _validate_number_attribute(name: str, value: object) -> int | float:
    if isinstance(value, bool):
        raise AttributeValidationError(f"Attribute '{name}' must be a number value.")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise AttributeValidationError(
                f"Attribute '{name}' must be a finite number value."
            )
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise AttributeValidationError(
                f"Attribute '{name}' must be a number value."
            )
        try:
            if all(marker not in text for marker in (".", "e", "E")):
                return int(text)
            parsed = float(text)
        except ValueError as exc:
            raise AttributeValidationError(
                f"Attribute '{name}' must be a number value."
            ) from exc
        if not isfinite(parsed):
            raise AttributeValidationError(
                f"Attribute '{name}' must be a finite number value."
            )
        return parsed
    raise AttributeValidationError(f"Attribute '{name}' must be a number value.")


def _validate_date_attribute(name: str, value: object) -> date:
    if isinstance(value, datetime):
        raise AttributeValidationError(f"Attribute '{name}' must be an ISO date value.")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise AttributeValidationError(
                f"Attribute '{name}' must be an ISO date value."
            ) from exc
    raise AttributeValidationError(f"Attribute '{name}' must be an ISO date value.")


def _validate_list_string_attribute(name: str, value: object) -> list[str]:
    if not isinstance(value, list):
        raise AttributeValidationError(
            f"Attribute '{name}' must be a list[string] value."
        )
    for item in value:
        if not isinstance(item, str):
            raise AttributeValidationError(
                f"Attribute '{name}' must be a list[string] value."
            )
    return list(value)
