"""Indexable Text generation from domain objects.

Indexable Text is a derived text representation of a memory item
used for search and embeddings. It is NOT canonical memory.
"""

from __future__ import annotations

from memorable.core.models import Decision, Entity, Observation, Relation, Task


def indexable_text_for_entity(entity: Entity) -> str:
    """Generate Indexable Text for an Entity."""
    return (
        f"Entity {entity.id}: {entity.name} "
        f"(type: {entity.entity_type}, space: {entity.space})"
    )


def indexable_text_for_decision(decision: Decision) -> str:
    """Generate Indexable Text for a Decision."""
    return (
        f"Decision {decision.id}: {decision.statement} "
        f"(lifecycle: {decision.lifecycle_state}, space: {decision.space})"
    )


def indexable_text_for_observation(observation: Observation) -> str:
    """Generate Indexable Text for an Observation."""
    return (
        f"Observation {observation.id}: {observation.statement} "
        f"(lifecycle: {observation.lifecycle_state}, space: {observation.space})"
    )


def indexable_text_for_relation(relation: Relation) -> str:
    """Generate Indexable Text for a Relation."""
    return (
        f"Relation {relation.id}: [{relation.relation_type}] "
        f"{relation.statement} "
        f"(source: {relation.source_entity_id}, "
        f"target: {relation.target_entity_id}, "
        f"lifecycle: {relation.lifecycle_state}, space: {relation.space})"
    )


def indexable_text_for_task(task: Task) -> str:
    """Generate Indexable Text for a Task."""
    return (
        f"Task {task.id}: {task.title} "
        f"(lifecycle: {task.lifecycle_state}, space: {task.space})"
    )
