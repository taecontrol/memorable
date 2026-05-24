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
    memory and inspection workflows.
    """

    entity_id: str
    source_id: str
    episode_id: str
    writer: str
    reason: str
    creation_time: datetime
    validity_time: datetime
