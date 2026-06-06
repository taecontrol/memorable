"""Storage-free validation for typed durable Attributes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class AttributeDeclaration:
    """A typed durable Attribute declared on a MemoryProfile type."""

    name: str
    type: str


class AttributeValidationError(ValueError):
    """Raised when provided Attribute values do not match a declaration."""


SUPPORTED_ATTRIBUTE_TYPES = ("string",)


def validate_attribute_values(
    declared_attributes: Sequence[AttributeDeclaration],
    provided_values: Mapping[str, object] | None,
) -> dict[str, str]:
    """Validate provided Attribute values against a declared Attribute schema."""
    if provided_values is None:
        return {}

    declared_by_name = {attribute.name: attribute for attribute in declared_attributes}
    validated: dict[str, str] = {}
    for name, value in provided_values.items():
        if name not in declared_by_name:
            raise AttributeValidationError(
                f"Attribute '{name}' is not declared. "
                f"Declared Attributes: {sorted(declared_by_name)}."
            )
        if declared_by_name[name].type not in SUPPORTED_ATTRIBUTE_TYPES:
            raise AttributeValidationError(
                f"Attribute '{name}' has unsupported type "
                f"'{declared_by_name[name].type}'. "
                f"Supported Attribute types: {list(SUPPORTED_ATTRIBUTE_TYPES)}."
            )
        if not isinstance(value, str):
            raise AttributeValidationError(
                f"Attribute '{name}' must be a string value."
            )
        validated[name] = value
    return validated
