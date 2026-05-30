from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UniquenessConstraint:
    name: str
    label: str
    properties: tuple[str, ...]


EXPECTED_UNIQUENESS_CONSTRAINTS: tuple[UniquenessConstraint, ...] = (
    UniquenessConstraint("memory_space_name_unique", "MemorySpace", ("name",)),
    UniquenessConstraint("entity_space_id_unique", "Entity", ("space", "id")),
    UniquenessConstraint("decision_space_id_unique", "Decision", ("space", "id")),
    UniquenessConstraint("task_space_id_unique", "Task", ("space", "id")),
    UniquenessConstraint("observation_space_id_unique", "Observation", ("space", "id")),
    UniquenessConstraint("relation_space_id_unique", "Relation", ("space", "id")),
)


def expected_constraint_shapes() -> set[tuple[str, str, tuple[str, ...]]]:
    """Return expected Neo4j schema shapes without generated constraint names."""
    return {
        ("UNIQUENESS", constraint.label, constraint.properties)
        for constraint in EXPECTED_UNIQUENESS_CONSTRAINTS
    }


def create_uniqueness_constraint_cypher(constraint: UniquenessConstraint) -> str:
    """Return static Cypher for creating a known uniqueness constraint."""
    variable = constraint.label[0].lower()
    if len(constraint.properties) == 1:
        required = f"{variable}.{constraint.properties[0]}"
    else:
        required = ", ".join(
            f"{variable}.{property_name}" for property_name in constraint.properties
        )
        required = f"({required})"
    return (
        f"CREATE CONSTRAINT {constraint.name} "
        f"IF NOT EXISTS FOR ({variable}:{constraint.label}) "
        f"REQUIRE {required} IS UNIQUE"
    )
