"""Indexable Text generation from domain objects.

Indexable Text is a derived text representation of a memory item
used for search and embeddings. It is NOT canonical memory.
"""

from __future__ import annotations

from memorable.core.models import Decision, Entity, Task


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


def indexable_text_for_task(task: Task) -> str:
    """Generate Indexable Text for a Task."""
    return (
        f"Task {task.id}: {task.title} "
        f"(lifecycle: {task.lifecycle_state}, space: {task.space})"
    )
