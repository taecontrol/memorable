"""Record Subtype validation for Memorable Core."""

from __future__ import annotations

from memorable.core.errors import UndeclaredTypeError
from memorable.core.profile import MemoryProfile

_KERNEL_KIND_LABELS = {
    "decision": "Decision",
    "observation": "Observation",
    "task": "Task",
}


def validate_record_subtype(
    *,
    profile: MemoryProfile,
    kernel_kind: str,
    candidate: str | None,
) -> str | None:
    """Validate an optional Record Subtype against a MemoryProfile."""
    if candidate is None:
        return None

    expected_extends = _KERNEL_KIND_LABELS.get(kernel_kind, kernel_kind)
    declarations = {record.name: record for record in profile.records}
    declaration = declarations.get(candidate)
    if declaration is None:
        declared_names = sorted(declarations)
        raise UndeclaredTypeError(
            f"Record Subtype '{candidate}' is not declared in the "
            f"MemoryProfile for space '{profile.space.name}'. "
            f"Declared Record Subtypes: {declared_names}."
        )
    if declaration.extends != expected_extends:
        matching_names = sorted(
            record.name
            for record in profile.records
            if record.extends == expected_extends
        )
        raise UndeclaredTypeError(
            f"Record Subtype '{candidate}' extends {declaration.extends}, "
            f"not {expected_extends}. "
            f"Declared {expected_extends} Record Subtypes: {matching_names}."
        )
    return candidate
