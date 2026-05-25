"""Neo4j adapters for Memorable Core persistence.

All Neo4j-specific details (Cypher queries, constraints, node labels,
relationship types) are encapsulated here. The public interface uses
only domain language from Memorable Core.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from memorable.core.models import Decision, Entity, MemorySpace, Provenance, Task


@runtime_checkable
class Neo4jDriver(Protocol):
    """Minimal driver interface expected by the Neo4j adapter."""

    def session(self) -> Any: ...


# --- Datetime helpers ---


def _to_iso(dt: datetime | None) -> str | None:
    """Convert a datetime to ISO 8601 string for storage, or None."""
    if dt is None:
        return None
    return dt.isoformat()


def _from_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string back to a datetime, or None."""
    if value is None:
        return None
    return datetime.fromisoformat(value)


# --- MemorySpace adapter ---


class Neo4jMemorySpaceRepository:
    """Storage adapter that persists MemorySpaces in Neo4j.

    Implements the MemorySpaceRepository protocol defined in core.ports.
    """

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    def create_space(self, name: str) -> MemorySpace:
        """Create and persist a new MemorySpace.

        Raises ValueError if a MemorySpace with the given name already exists.
        """
        space = MemorySpace(name=name)  # validates name

        with self._driver.session() as session:
            # Check existence first
            result = session.run(
                "MATCH (s:MemorySpace {name: $name}) RETURN s.name AS name",
                name=name,
            )
            if result.single() is not None:
                raise ValueError(f"MemorySpace '{name}' already exists")

            # Create the node
            session.run(
                "CREATE (s:MemorySpace {name: $name}) RETURN s.name AS name",
                name=name,
            )

        return space

    def get_space(self, name: str) -> MemorySpace | None:
        """Retrieve a MemorySpace by name, or None if it does not exist."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (s:MemorySpace {name: $name}) RETURN s.name AS name",
                name=name,
            )
            record = result.single()
            if record is None:
                return None
            return MemorySpace(name=record["name"])

    def exists(self, name: str) -> bool:
        """Check whether a MemorySpace with the given name exists."""
        return self.get_space(name) is not None

    def ensure_constraints(self) -> None:
        """Create Neo4j uniqueness constraints and indexes.

        This is an infrastructure concern — called during setup,
        not during normal domain operations.
        """
        with self._driver.session() as session:
            session.run(
                "CREATE CONSTRAINT memory_space_name_unique "
                "IF NOT EXISTS FOR (s:MemorySpace) "
                "REQUIRE s.name IS UNIQUE"
            )


# --- Entity adapter ---


class Neo4jEntityRepository:
    """Storage adapter that persists Entities in Neo4j.

    Implements the EntityRepository protocol defined in core.ports.
    Uses MERGE on (space, id) for idempotent upsert semantics.
    """

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    def save(self, entity: Entity, provenance: Provenance) -> None:
        """Persist an Entity with its provenance record.

        Uses MERGE so re-saving the same entity updates its properties.
        Provenance is stored as a separate node linked via PROVENANCE_OF.
        """
        with self._driver.session() as session:
            session.run(
                "MERGE (e:Entity {space: $space, id: $id}) "
                "SET e.entity_type = $entity_type, e.name = $name "
                "WITH e "
                "MERGE (p:Provenance "
                "{record_id: $record_id, record_kind: $record_kind}) "
                "SET p.source_id = $source_id, "
                "    p.episode_id = $episode_id, "
                "    p.writer = $writer, "
                "    p.reason = $reason, "
                "    p.creation_time = $creation_time, "
                "    p.validity_time = $validity_time "
                "MERGE (p)-[:PROVENANCE_OF]->(e)",
                space=entity.space,
                id=entity.id,
                entity_type=entity.entity_type,
                name=entity.name,
                record_id=provenance.record_id,
                record_kind=provenance.record_kind,
                source_id=provenance.source_id,
                episode_id=provenance.episode_id,
                writer=provenance.writer,
                reason=provenance.reason,
                creation_time=_to_iso(provenance.creation_time),
                validity_time=_to_iso(provenance.validity_time),
            )

    def get(self, space: str, entity_id: str) -> Entity | None:
        """Retrieve an Entity by space and id, or None if not found."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (e:Entity {space: $space, id: $id}) "
                "RETURN e.id AS id, e.entity_type AS entity_type, "
                "       e.name AS name, e.space AS space",
                space=space,
                id=entity_id,
            )
            record = result.single()
            if record is None:
                return None
            return Entity(
                id=record["id"],
                entity_type=record["entity_type"],
                name=record["name"],
                space=record["space"],
            )

    def get_provenance(self, space: str, entity_id: str) -> Provenance | None:
        """Retrieve the provenance for an Entity, or None if not found."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (p:Provenance)-[:PROVENANCE_OF]"
                "->(e:Entity {space: $space, id: $id}) "
                "RETURN p.record_id AS record_id, p.record_kind AS record_kind, "
                "       p.source_id AS source_id, p.episode_id AS episode_id, "
                "       p.writer AS writer, p.reason AS reason, "
                "       p.creation_time AS creation_time, "
                "       p.validity_time AS validity_time",
                space=space,
                id=entity_id,
            )
            record = result.single()
            if record is None:
                return None
            return Provenance(
                record_id=record["record_id"],
                record_kind=record["record_kind"],
                source_id=record["source_id"],
                episode_id=record["episode_id"],
                writer=record["writer"],
                reason=record["reason"],
                creation_time=_from_iso(record["creation_time"]),
                validity_time=_from_iso(record["validity_time"]),
            )

    def list_by_space(self, space: str) -> list[Entity]:
        """Return all entities in the given space."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (e:Entity {space: $space}) "
                "RETURN e.id AS id, e.entity_type AS entity_type, "
                "       e.name AS name, e.space AS space",
                space=space,
                id="",
            )
            return [
                Entity(
                    id=record["id"],
                    entity_type=record["entity_type"],
                    name=record["name"],
                    space=record["space"],
                )
                for record in result
            ]


# --- Decision adapter ---


class Neo4jDecisionRepository:
    """Storage adapter that persists Decisions in Neo4j.

    Implements the DecisionRepository protocol defined in core.ports.
    Uses CREATE for append-only semantics.
    """

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    def save(self, decision: Decision, provenance: Provenance) -> None:
        """Persist a Decision with its provenance record.

        Uses CREATE for append-only semantics. Provenance is stored as
        a separate node linked via PROVENANCE_OF.
        """
        with self._driver.session() as session:
            session.run(
                "CREATE (d:Decision {"
                "  space: $space, id: $id, statement: $statement, "
                "  validity_time: $validity_time, "
                "  invalidation_time: $invalidation_time, "
                "  lifecycle_state: $lifecycle_state, "
                "  supersedes: $supersedes, "
                "  superseded_by: $superseded_by"
                "}) "
                "WITH d "
                "CREATE (p:Provenance {"
                "  record_id: $record_id, record_kind: $record_kind, "
                "  source_id: $source_id, episode_id: $episode_id, "
                "  writer: $writer, reason: $reason, "
                "  creation_time: $creation_time, "
                "  validity_time: $prov_validity_time"
                "}) "
                "CREATE (p)-[:PROVENANCE_OF]->(d)",
                space=decision.space,
                id=decision.id,
                statement=decision.statement,
                validity_time=_to_iso(decision.validity_time),
                invalidation_time=_to_iso(decision.invalidation_time),
                lifecycle_state=decision.lifecycle_state,
                supersedes=decision.supersedes,
                superseded_by=decision.superseded_by,
                record_id=provenance.record_id,
                record_kind=provenance.record_kind,
                source_id=provenance.source_id,
                episode_id=provenance.episode_id,
                writer=provenance.writer,
                reason=provenance.reason,
                creation_time=_to_iso(provenance.creation_time),
                prov_validity_time=_to_iso(provenance.validity_time),
            )

    def get(self, space: str, decision_id: str) -> Decision | None:
        """Retrieve a Decision by space and id, or None if not found."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (d:Decision {space: $space, id: $id}) "
                "RETURN d.id AS id, d.statement AS statement, "
                "       d.space AS space, "
                "       d.validity_time AS validity_time, "
                "       d.invalidation_time AS invalidation_time, "
                "       d.lifecycle_state AS lifecycle_state, "
                "       d.supersedes AS supersedes, "
                "       d.superseded_by AS superseded_by",
                space=space,
                id=decision_id,
            )
            record = result.single()
            if record is None:
                return None
            return Decision(
                id=record["id"],
                statement=record["statement"],
                space=record["space"],
                validity_time=_from_iso(record["validity_time"]),
                invalidation_time=_from_iso(record["invalidation_time"]),
                lifecycle_state=record["lifecycle_state"],
                supersedes=record["supersedes"],
                superseded_by=record["superseded_by"],
            )

    def get_provenance(self, space: str, decision_id: str) -> Provenance | None:
        """Retrieve the provenance for a Decision, or None if not found."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (p:Provenance)-[:PROVENANCE_OF]"
                "->(d:Decision {space: $space, id: $id}) "
                "RETURN p.record_id AS record_id, p.record_kind AS record_kind, "
                "       p.source_id AS source_id, p.episode_id AS episode_id, "
                "       p.writer AS writer, p.reason AS reason, "
                "       p.creation_time AS creation_time, "
                "       p.validity_time AS validity_time",
                space=space,
                id=decision_id,
            )
            record = result.single()
            if record is None:
                return None
            return Provenance(
                record_id=record["record_id"],
                record_kind=record["record_kind"],
                source_id=record["source_id"],
                episode_id=record["episode_id"],
                writer=record["writer"],
                reason=record["reason"],
                creation_time=_from_iso(record["creation_time"]),
                validity_time=_from_iso(record["validity_time"]),
            )

    def list_by_space(self, space: str) -> list[Decision]:
        """Return all decisions in the given space."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (d:Decision {space: $space}) "
                "RETURN d.id AS id, d.statement AS statement, "
                "       d.space AS space, "
                "       d.validity_time AS validity_time, "
                "       d.invalidation_time AS invalidation_time, "
                "       d.lifecycle_state AS lifecycle_state, "
                "       d.supersedes AS supersedes, "
                "       d.superseded_by AS superseded_by",
                space=space,
                id="",
            )
            return [
                Decision(
                    id=record["id"],
                    statement=record["statement"],
                    space=record["space"],
                    validity_time=_from_iso(record["validity_time"]),
                    invalidation_time=_from_iso(record["invalidation_time"]),
                    lifecycle_state=record["lifecycle_state"],
                    supersedes=record["supersedes"],
                    superseded_by=record["superseded_by"],
                )
                for record in result
            ]

    def mark_superseded(
        self,
        space: str,
        decision_id: str,
        superseded_by: str,
        invalidation_time: datetime,
    ) -> None:
        """Mark a Decision as superseded by another."""
        with self._driver.session() as session:
            session.run(
                "MATCH (d:Decision {space: $space, id: $id}) "
                "SET d.superseded_by = $superseded_by, "
                "    d.invalidation_time = $invalidation_time, "
                "    d.lifecycle_state = $lifecycle_state",
                space=space,
                id=decision_id,
                superseded_by=superseded_by,
                invalidation_time=_to_iso(invalidation_time),
                lifecycle_state="superseded",
            )


# --- Task adapter ---


class Neo4jTaskRepository:
    """Storage adapter that persists Tasks in Neo4j.

    Implements the TaskRepository protocol defined in core.ports.
    Uses CREATE for append-only semantics.
    """

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    def save(self, task: Task, provenance: Provenance) -> None:
        """Persist a Task with its provenance record.

        Uses CREATE for append-only semantics. Provenance is stored as
        a separate node linked via PROVENANCE_OF.
        """
        with self._driver.session() as session:
            session.run(
                "CREATE (t:Task {"
                "  space: $space, id: $id, title: $title, "
                "  lifecycle_state: $lifecycle_state, "
                "  validity_time: $validity_time, "
                "  completion_time: $completion_time, "
                "  completion_event_id: $completion_event_id"
                "}) "
                "WITH t "
                "CREATE (p:Provenance {"
                "  record_id: $record_id, record_kind: $record_kind, "
                "  source_id: $source_id, episode_id: $episode_id, "
                "  writer: $writer, reason: $reason, "
                "  creation_time: $creation_time, "
                "  validity_time: $prov_validity_time"
                "}) "
                "CREATE (p)-[:PROVENANCE_OF]->(t)",
                space=task.space,
                id=task.id,
                title=task.title,
                lifecycle_state=task.lifecycle_state,
                validity_time=_to_iso(task.validity_time),
                completion_time=_to_iso(task.completion_time),
                completion_event_id=task.completion_event_id,
                record_id=provenance.record_id,
                record_kind=provenance.record_kind,
                source_id=provenance.source_id,
                episode_id=provenance.episode_id,
                writer=provenance.writer,
                reason=provenance.reason,
                creation_time=_to_iso(provenance.creation_time),
                prov_validity_time=_to_iso(provenance.validity_time),
            )

    def get(self, *, space: str, task_id: str) -> Task | None:
        """Retrieve a Task by space and id, or None if not found."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (t:Task {space: $space, id: $id}) "
                "RETURN t.id AS id, t.title AS title, "
                "       t.space AS space, "
                "       t.lifecycle_state AS lifecycle_state, "
                "       t.validity_time AS validity_time, "
                "       t.completion_time AS completion_time, "
                "       t.completion_event_id AS completion_event_id",
                space=space,
                id=task_id,
            )
            record = result.single()
            if record is None:
                return None
            return Task(
                id=record["id"],
                title=record["title"],
                space=record["space"],
                lifecycle_state=record["lifecycle_state"],
                validity_time=_from_iso(record["validity_time"]),
                completion_time=_from_iso(record["completion_time"]),
                completion_event_id=record["completion_event_id"],
            )

    def get_provenance(self, *, space: str, task_id: str) -> Provenance | None:
        """Retrieve the provenance for a Task, or None if not found."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (p:Provenance)-[:PROVENANCE_OF]"
                "->(t:Task {space: $space, id: $id}) "
                "RETURN p.record_id AS record_id, p.record_kind AS record_kind, "
                "       p.source_id AS source_id, p.episode_id AS episode_id, "
                "       p.writer AS writer, p.reason AS reason, "
                "       p.creation_time AS creation_time, "
                "       p.validity_time AS validity_time",
                space=space,
                id=task_id,
            )
            record = result.single()
            if record is None:
                return None
            return Provenance(
                record_id=record["record_id"],
                record_kind=record["record_kind"],
                source_id=record["source_id"],
                episode_id=record["episode_id"],
                writer=record["writer"],
                reason=record["reason"],
                creation_time=_from_iso(record["creation_time"]),
                validity_time=_from_iso(record["validity_time"]),
            )

    def complete(
        self,
        *,
        space: str,
        task_id: str,
        completion_time: datetime,
        completion_event_id: str,
    ) -> None:
        """Record a completion event on a Task (append-first, not delete)."""
        with self._driver.session() as session:
            session.run(
                "MATCH (t:Task {space: $space, id: $id}) "
                "SET t.lifecycle_state = $lifecycle_state, "
                "    t.completion_time = $completion_time, "
                "    t.completion_event_id = $completion_event_id",
                space=space,
                id=task_id,
                lifecycle_state="completed",
                completion_time=_to_iso(completion_time),
                completion_event_id=completion_event_id,
            )

    def list_by_space(self, space: str) -> list[Task]:
        """Return all tasks in the given space."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (t:Task {space: $space}) "
                "RETURN t.id AS id, t.title AS title, "
                "       t.space AS space, "
                "       t.lifecycle_state AS lifecycle_state, "
                "       t.validity_time AS validity_time, "
                "       t.completion_time AS completion_time, "
                "       t.completion_event_id AS completion_event_id",
                space=space,
                id="",
            )
            return [
                Task(
                    id=record["id"],
                    title=record["title"],
                    space=record["space"],
                    lifecycle_state=record["lifecycle_state"],
                    validity_time=_from_iso(record["validity_time"]),
                    completion_time=_from_iso(record["completion_time"]),
                    completion_event_id=record["completion_event_id"],
                )
                for record in result
            ]


# --- Schema bootstrap ---


def ensure_all_constraints(driver: Neo4jDriver) -> None:
    """Create composite uniqueness constraints for all record types.

    Idempotent — uses IF NOT EXISTS so repeated calls are safe.
    Creates constraints on (space, id) for Entity, Decision, and Task,
    plus the existing MemorySpace name uniqueness constraint.
    """
    with driver.session() as session:
        session.run(
            "CREATE CONSTRAINT memory_space_name_unique "
            "IF NOT EXISTS FOR (s:MemorySpace) "
            "REQUIRE s.name IS UNIQUE"
        )
        session.run(
            "CREATE CONSTRAINT entity_space_id_unique "
            "IF NOT EXISTS FOR (e:Entity) "
            "REQUIRE (e.space, e.id) IS UNIQUE"
        )
        session.run(
            "CREATE CONSTRAINT decision_space_id_unique "
            "IF NOT EXISTS FOR (d:Decision) "
            "REQUIRE (d.space, d.id) IS UNIQUE"
        )
        session.run(
            "CREATE CONSTRAINT task_space_id_unique "
            "IF NOT EXISTS FOR (t:Task) "
            "REQUIRE (t.space, t.id) IS UNIQUE"
        )
