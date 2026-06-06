"""Domain models for Memorable Core."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MemorySpace:
    """Project-scoped memory boundary.

    A MemorySpace owns records, entities, provenance, profile rules,
    and temporal history for one project or workspace.
    """

    name: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("MemorySpace name must not be empty")


@dataclass(frozen=True)
class Entity:
    """A remembered thing with identity inside a MemorySpace.

    Entities are named domain things that memory can refer to over time,
    such as a project, component, API, or stakeholder.
    """

    id: str
    entity_type: str
    name: str
    space: str

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Entity id must not be empty")
        if not self.name:
            raise ValueError("Entity name must not be empty")


@dataclass(frozen=True)
class Source:
    """Where a memory came from.

    Answers "where did this memory come from?" with provenance origins
    such as a conversation, file, tool result, or test fixture.
    """

    id: str
    category: str


@dataclass(frozen=True)
class Episode:
    """A provenance event or source occurrence that produced memory.

    Source names the origin category or object.
    Episode names the specific occurrence.
    """

    id: str
    source_id: str
    timestamp: datetime


@dataclass(frozen=True)
class Provenance:
    """The recorded explanation of where a memory came from and why it is believed.

    Every memory write preserves provenance. Provenance belongs in stored
    memory and inspection workflows. The record_id identifies the owning
    record, and record_kind distinguishes the record type (entity, decision,
    or task).
    """

    record_id: str
    record_kind: str
    source_id: str
    episode_id: str
    writer: str
    reason: str
    creation_time: datetime
    validity_time: datetime


class ProvenanceIntegrityError(Exception):
    """Raised when a MemoryRecord exists but its Provenance join is missing."""


@dataclass(frozen=True)
class RecordProjection:
    """A compact, type-agnostic view of a MemoryRecord for Memory Review.

    ``type`` is the kernel kind; ``record_type`` is the optional Record Subtype.
    """

    id: str
    type: str
    label: str
    lifecycle_state: str
    creation_time: datetime
    record_type: str | None = None


@dataclass(frozen=True)
class ForgetTarget:
    """A scoped MemoryRecord target that may be erased by Forget."""

    id: str
    record_kind: str
    space: str
    supersedes: str | None
    superseded_by: str | None


@dataclass(frozen=True)
class Decision:
    """A remembered choice with temporal validity and supersession links.

    Decisions preserve rationale, provenance, temporal validity,
    and explicit supersession relationships.
    """

    id: str
    statement: str
    space: str
    validity_time: datetime
    invalidation_time: datetime | None
    lifecycle_state: str
    supersedes: str | None
    superseded_by: str | None
    record_type: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Decision id must not be empty")
        if not self.statement:
            raise ValueError("Decision statement must not be empty")


@dataclass(frozen=True)
class Observation:
    """A remembered assertion with temporal validity and supersession links.

    Observations are flexible fallback records for assertions that do not
    naturally fit as a Decision, Task, or Measurement. They carry the same
    temporal and supersession semantics as Decision.
    """

    id: str
    statement: str
    space: str
    validity_time: datetime
    invalidation_time: datetime | None
    lifecycle_state: str
    supersedes: str | None
    superseded_by: str | None
    record_type: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Observation id must not be empty")
        if not self.statement:
            raise ValueError("Observation statement must not be empty")


@dataclass(frozen=True)
class Task:
    """A remembered work item with lifecycle state and temporal validity.

    Tasks track open/completed lifecycle transitions with append-first
    completion events rather than deletion.
    """

    id: str
    title: str
    space: str
    lifecycle_state: str  # "open" or "completed"
    validity_time: datetime
    completion_time: datetime | None
    completion_event_id: str | None
    record_type: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Task id must not be empty.")
        if not self.title:
            raise ValueError("Task title must not be empty.")


@dataclass(frozen=True)
class Relation:
    """A typed, directed, temporal connection between two Entities.

    Relations are directed connections in the memory graph. They carry the same
    temporal and supersession semantics as Decision and Observation, enabling
    current truth, point-in-time truth, invalidation, correction, and
    provenance on connections between Entities.
    """

    id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    statement: str
    space: str
    validity_time: datetime
    invalidation_time: datetime | None
    lifecycle_state: str
    supersedes: str | None
    superseded_by: str | None

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "source_entity_id",
            "target_entity_id",
            "relation_type",
            "statement",
            "space",
        ):
            if not getattr(self, field_name):
                raise ValueError(f"Relation {field_name} must not be empty")
        if self.source_entity_id == self.target_entity_id:
            raise ValueError(
                "Relation must not be a self-relation "
                f"(source and target are both '{self.source_entity_id}')"
            )
