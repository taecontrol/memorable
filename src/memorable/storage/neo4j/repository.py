"""Neo4j adapters for Memorable Core persistence.

All Neo4j-specific details (Cypher queries, constraints, node labels,
relationship types) are encapsulated here. The public interface uses
only domain language from Memorable Core.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from neo4j.exceptions import ConstraintError

from memorable.core.errors import DuplicateRecordError
from memorable.core.models import (
    Decision,
    Entity,
    ForgetTarget,
    MemorySpace,
    Observation,
    Provenance,
    ProvenanceIntegrityError,
    RecordProjection,
    Relation,
    Task,
)
from memorable.storage.neo4j.schema import (
    EXPECTED_UNIQUENESS_CONSTRAINTS,
    create_uniqueness_constraint_cypher,
    create_vector_index_cypher,
)


@runtime_checkable
class Neo4jDriver(Protocol):
    """Minimal driver interface expected by the Neo4j adapter."""

    def session(self) -> Any: ...


# --- Datetime helpers ---


def _to_iso(dt: datetime | None) -> str | None:
    """Convert a datetime to canonical UTC ISO 8601 string for storage, or None."""
    if dt is None:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("stored datetimes must be timezone-aware")
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def _from_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string back to a datetime, or None."""
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _raise_duplicate_record_if_existing(
    driver: Neo4jDriver,
    error: ConstraintError,
    *,
    record_kind: str,
    space: str,
    record_id: str,
) -> None:
    with driver.session() as session:
        result = session.run(
            "MATCH (record:Record {space: $space, id: $id}) "
            "RETURN record.id AS id LIMIT 1",
            space=space,
            id=record_id,
        )
        if result.single() is not None:
            raise DuplicateRecordError(
                record_kind=record_kind,
                space=space,
                record_id=record_id,
            ) from error
    raise error


def _list_projections_by_space(
    driver: Neo4jDriver,
    *,
    storage_label: str,
    label_property: str,
    record_type: str,
    space: str,
    state: str | None,
    since: datetime | None,
    until: datetime | None,
    limit: int,
    record_ids: set[str] | None = None,
) -> list[RecordProjection]:
    """Return one record type's projections filtered and ordered by Creation Time.

    The Provenance join, Creation-Time window, ordering, and limit are all
    pushed into the matching pipeline so only the returned rows are
    materialized — the store is never scanned in full. Neo4j sorts NULL last
    in ASC order, so a record whose Provenance join is missing still appears
    in the returned rows when no window bound is active and triggers the
    integrity check.
    """
    query = (
        f"MATCH (record:{storage_label} {{space: $space}}) "
        "WHERE ($record_ids IS NULL OR record.id IN $record_ids) "
        "  AND ($state IS NULL OR record.lifecycle_state = $state) "
        "OPTIONAL MATCH (p:Provenance)-[:PROVENANCE_OF]->(record) "
        "WITH record, p "
        "WHERE ($since IS NULL OR p.creation_time >= $since) "
        "  AND ($until IS NULL OR p.creation_time < $until) "
        "ORDER BY p.creation_time ASC, record.id ASC "
        "LIMIT $limit "
        f"RETURN record.id AS id, record.{label_property} AS label, "
        "       record.lifecycle_state AS lifecycle_state, "
        "       p.creation_time AS creation_time, "
        "       (p IS NOT NULL) AS has_provenance"
    )
    with driver.session() as session:
        result = session.run(
            query,
            space=space,
            state=state,
            since=_to_iso(since),
            until=_to_iso(until),
            limit=limit,
            record_ids=sorted(record_ids) if record_ids is not None else None,
        )
        projections: list[RecordProjection] = []
        for record in result:
            if not record["has_provenance"]:
                raise ProvenanceIntegrityError(
                    f"Provenance missing for {record_type} '{record['id']}' "
                    f"in MemorySpace '{space}'."
                )
            projections.append(
                RecordProjection(
                    id=record["id"],
                    type=record_type,
                    label=record["label"],
                    lifecycle_state=record["lifecycle_state"],
                    creation_time=_from_iso(record["creation_time"]),
                )
            )
        return projections


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
                "MERGE (e)<-[:PROVENANCE_OF]-(p:Provenance "
                "{record_kind: $record_kind}) "
                "SET p.record_id = $record_id, "
                "    p.source_id = $source_id, "
                "    p.episode_id = $episode_id, "
                "    p.writer = $writer, "
                "    p.reason = $reason, "
                "    p.creation_time = $creation_time, "
                "    p.validity_time = $validity_time",
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


# --- About adapter ---


class Neo4jAboutRepository:
    """Storage adapter that persists About links in Neo4j.

    Implements the AboutRepository protocol defined in core.ports. About is
    stored as a structural relationship from a MemoryRecord to an Entity; the
    relationship intentionally carries no properties.
    """

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    def link(self, space: str, record_id: str, entity_ids: list[str]) -> None:
        """Link a MemoryRecord to the Entities it is about."""
        with self._driver.session() as session:
            session.run(
                "MATCH (record:Record {space: $space, id: $record_id}) "
                "UNWIND $entity_ids AS entity_id "
                "MATCH (entity:Entity {space: $space, id: entity_id}) "
                "MERGE (record)-[:ABOUT]->(entity)",
                space=space,
                record_id=record_id,
                entity_ids=entity_ids,
            )

    def unlink(self, space: str, record_id: str) -> None:
        """Hard-remove all About links for a MemoryRecord."""
        with self._driver.session() as session:
            session.run(
                "MATCH (:Record {space: $space, id: $record_id})"
                "-[about:ABOUT]->(:Entity {space: $space}) "
                "DELETE about",
                space=space,
                record_id=record_id,
            )

    def entities_for_record(self, space: str, record_id: str) -> list[str]:
        """Return Entity ids linked from the MemoryRecord."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (:Record {space: $space, id: $record_id})"
                "-[:ABOUT]->(entity:Entity {space: $space}) "
                "RETURN entity.id AS entity_id "
                "ORDER BY entity.id ASC",
                space=space,
                record_id=record_id,
            )
            return [record["entity_id"] for record in result]

    def records_for_entity(self, space: str, entity_id: str) -> list[str]:
        """Return MemoryRecord ids linked to the Entity."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (record:Record {space: $space})"
                "-[:ABOUT]->(:Entity {space: $space, id: $entity_id}) "
                "RETURN record.id AS record_id "
                "ORDER BY record.id ASC",
                space=space,
                entity_id=entity_id,
            )
            return [record["record_id"] for record in result]


# --- Forget adapter ---


class Neo4jForgetRepository:
    """Storage adapter for Forget across Writable Record Types."""

    _RECORD_LABELS = {
        "decision": "Decision",
        "observation": "Observation",
        "task": "Task",
    }

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    def get_forget_target(
        self,
        *,
        space: str,
        record_id: str,
        record_kind: str,
    ) -> ForgetTarget | None:
        label = self._RECORD_LABELS.get(record_kind)
        if label is None:
            return None
        with self._driver.session() as session:
            result = session.run(
                f"MATCH (record:Record:{label} {{space: $space, id: $id}}) "
                "RETURN record.id AS id, record.space AS space, "
                "       record.supersedes AS supersedes, "
                "       record.superseded_by AS superseded_by",
                space=space,
                id=record_id,
            )
            record = result.single()
            if record is None:
                return None
            return ForgetTarget(
                id=record["id"],
                record_kind=record_kind,
                space=record["space"],
                supersedes=record["supersedes"],
                superseded_by=record["superseded_by"],
            )

    def forget_record(
        self,
        *,
        space: str,
        record_id: str,
        record_kind: str,
    ) -> None:
        label = self._RECORD_LABELS.get(record_kind)
        if label is None:
            return
        with self._driver.session() as session:
            session.run(
                f"MATCH (record:Record:{label} {{space: $space, id: $id}}) "
                "OPTIONAL MATCH (provenance:Provenance)"
                "-[provenance_link:PROVENANCE_OF]->(record) "
                "OPTIONAL MATCH (record)-[about:ABOUT]->(:Entity {space: $space}) "
                "WITH record, "
                "     collect(DISTINCT provenance) AS provenances, "
                "     collect(DISTINCT provenance_link) AS provenance_links, "
                "     collect(DISTINCT about) AS about_links "
                "FOREACH (link IN about_links | DELETE link) "
                "FOREACH (link IN provenance_links | DELETE link) "
                "FOREACH (provenance IN provenances | DELETE provenance) "
                "DELETE record",
                space=space,
                id=record_id,
            )


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
        try:
            with self._driver.session() as session:
                session.run(
                    "CREATE (d:Record:Decision {"
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
        except ConstraintError as e:
            _raise_duplicate_record_if_existing(
                self._driver,
                e,
                record_kind="decision",
                space=decision.space,
                record_id=decision.id,
            )

    def get(self, space: str, record_id: str) -> Decision | None:
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
                id=record_id,
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

    def get_provenance(self, space: str, record_id: str) -> Provenance | None:
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
                id=record_id,
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

    def list_projections_by_space(
        self,
        *,
        space: str,
        state: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        record_ids: set[str] | None = None,
    ) -> list[RecordProjection]:
        """Return Decision projections filtered and ordered by Creation Time."""
        return _list_projections_by_space(
            self._driver,
            storage_label="Decision",
            label_property="statement",
            record_type="decision",
            space=space,
            state=state,
            since=since,
            until=until,
            limit=limit,
            record_ids=record_ids,
        )

    def mark_superseded(
        self,
        space: str,
        record_id: str,
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
                id=record_id,
                superseded_by=superseded_by,
                invalidation_time=_to_iso(invalidation_time),
                lifecycle_state="superseded",
            )

    def invalidate(
        self,
        space: str,
        record_id: str,
        invalidation_time: datetime,
    ) -> None:
        """Mark a Decision as invalidated (no replacement)."""
        with self._driver.session() as session:
            session.run(
                "MATCH (d:Decision {space: $space, id: $id}) "
                "SET d.invalidation_time = $invalidation_time, "
                "    d.lifecycle_state = $lifecycle_state",
                space=space,
                id=record_id,
                invalidation_time=_to_iso(invalidation_time),
                lifecycle_state="invalidated",
            )

    def correct(
        self,
        space: str,
        record_id: str,
        new_statement: str,
    ) -> None:
        """Correct a Decision's statement in place."""
        with self._driver.session() as session:
            session.run(
                "MATCH (d:Decision {space: $space, id: $id}) "
                "SET d.statement = $statement",
                space=space,
                id=record_id,
                statement=new_statement,
            )

    def save_provenance(
        self,
        space: str,
        record_id: str,
        provenance: Provenance,
    ) -> None:
        """Replace the provenance for a Decision."""
        with self._driver.session() as session:
            session.run(
                "MATCH (p:Provenance)-[:PROVENANCE_OF]"
                "->(d:Decision {space: $space, id: $id}) "
                "SET p.record_id = $record_id, "
                "    p.record_kind = $record_kind, "
                "    p.source_id = $source_id, "
                "    p.episode_id = $episode_id, "
                "    p.writer = $writer, "
                "    p.reason = $reason, "
                "    p.creation_time = $creation_time, "
                "    p.validity_time = $validity_time",
                space=space,
                id=record_id,
                record_id=provenance.record_id,
                record_kind=provenance.record_kind,
                source_id=provenance.source_id,
                episode_id=provenance.episode_id,
                writer=provenance.writer,
                reason=provenance.reason,
                creation_time=_to_iso(provenance.creation_time),
                validity_time=_to_iso(provenance.validity_time),
            )


# --- Observation adapter ---


class Neo4jObservationRepository:
    """Storage adapter that persists Observations in Neo4j.

    Implements the ObservationRepository protocol defined in core.ports.
    Uses CREATE for append-only semantics.
    """

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    def save(self, observation: Observation, provenance: Provenance) -> None:
        """Persist an Observation with its provenance record.

        Uses CREATE for append-only semantics. Provenance is stored as
        a separate node linked via PROVENANCE_OF.
        """
        try:
            with self._driver.session() as session:
                session.run(
                    "CREATE (o:Record:Observation {"
                    "  space: $space, id: $id, statement: $statement, "
                    "  validity_time: $validity_time, "
                    "  invalidation_time: $invalidation_time, "
                    "  lifecycle_state: $lifecycle_state, "
                    "  supersedes: $supersedes, "
                    "  superseded_by: $superseded_by"
                    "}) "
                    "WITH o "
                    "CREATE (p:Provenance {"
                    "  record_id: $record_id, record_kind: $record_kind, "
                    "  source_id: $source_id, episode_id: $episode_id, "
                    "  writer: $writer, reason: $reason, "
                    "  creation_time: $creation_time, "
                    "  validity_time: $prov_validity_time"
                    "}) "
                    "CREATE (p)-[:PROVENANCE_OF]->(o)",
                    space=observation.space,
                    id=observation.id,
                    statement=observation.statement,
                    validity_time=_to_iso(observation.validity_time),
                    invalidation_time=_to_iso(observation.invalidation_time),
                    lifecycle_state=observation.lifecycle_state,
                    supersedes=observation.supersedes,
                    superseded_by=observation.superseded_by,
                    record_id=provenance.record_id,
                    record_kind=provenance.record_kind,
                    source_id=provenance.source_id,
                    episode_id=provenance.episode_id,
                    writer=provenance.writer,
                    reason=provenance.reason,
                    creation_time=_to_iso(provenance.creation_time),
                    prov_validity_time=_to_iso(provenance.validity_time),
                )
        except ConstraintError as e:
            _raise_duplicate_record_if_existing(
                self._driver,
                e,
                record_kind="observation",
                space=observation.space,
                record_id=observation.id,
            )

    def get(self, space: str, record_id: str) -> Observation | None:
        """Retrieve an Observation by space and id, or None if not found."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (o:Observation {space: $space, id: $id}) "
                "RETURN o.id AS id, o.statement AS statement, "
                "       o.space AS space, "
                "       o.validity_time AS validity_time, "
                "       o.invalidation_time AS invalidation_time, "
                "       o.lifecycle_state AS lifecycle_state, "
                "       o.supersedes AS supersedes, "
                "       o.superseded_by AS superseded_by",
                space=space,
                id=record_id,
            )
            record = result.single()
            if record is None:
                return None
            return Observation(
                id=record["id"],
                statement=record["statement"],
                space=record["space"],
                validity_time=_from_iso(record["validity_time"]),
                invalidation_time=_from_iso(record["invalidation_time"]),
                lifecycle_state=record["lifecycle_state"],
                supersedes=record["supersedes"],
                superseded_by=record["superseded_by"],
            )

    def get_provenance(self, space: str, record_id: str) -> Provenance | None:
        """Retrieve the provenance for an Observation, or None if not found."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (p:Provenance)-[:PROVENANCE_OF]"
                "->(o:Observation {space: $space, id: $id}) "
                "RETURN p.record_id AS record_id, p.record_kind AS record_kind, "
                "       p.source_id AS source_id, p.episode_id AS episode_id, "
                "       p.writer AS writer, p.reason AS reason, "
                "       p.creation_time AS creation_time, "
                "       p.validity_time AS validity_time",
                space=space,
                id=record_id,
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

    def list_by_space(self, space: str) -> list[Observation]:
        """Return all observations in the given space."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (o:Observation {space: $space}) "
                "RETURN o.id AS id, o.statement AS statement, "
                "       o.space AS space, "
                "       o.validity_time AS validity_time, "
                "       o.invalidation_time AS invalidation_time, "
                "       o.lifecycle_state AS lifecycle_state, "
                "       o.supersedes AS supersedes, "
                "       o.superseded_by AS superseded_by",
                space=space,
            )
            return [
                Observation(
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

    def list_projections_by_space(
        self,
        *,
        space: str,
        state: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        record_ids: set[str] | None = None,
    ) -> list[RecordProjection]:
        """Return Observation projections filtered and ordered by Creation Time."""
        return _list_projections_by_space(
            self._driver,
            storage_label="Observation",
            label_property="statement",
            record_type="observation",
            space=space,
            state=state,
            since=since,
            until=until,
            limit=limit,
            record_ids=record_ids,
        )

    def mark_superseded(
        self,
        space: str,
        record_id: str,
        superseded_by: str,
        invalidation_time: datetime,
    ) -> None:
        """Mark an Observation as superseded by another."""
        with self._driver.session() as session:
            session.run(
                "MATCH (o:Observation {space: $space, id: $id}) "
                "SET o.superseded_by = $superseded_by, "
                "    o.invalidation_time = $invalidation_time, "
                "    o.lifecycle_state = $lifecycle_state",
                space=space,
                id=record_id,
                superseded_by=superseded_by,
                invalidation_time=_to_iso(invalidation_time),
                lifecycle_state="superseded",
            )

    def invalidate(
        self,
        space: str,
        record_id: str,
        invalidation_time: datetime,
    ) -> None:
        """Mark an Observation as invalidated (no replacement)."""
        with self._driver.session() as session:
            session.run(
                "MATCH (o:Observation {space: $space, id: $id}) "
                "SET o.invalidation_time = $invalidation_time, "
                "    o.lifecycle_state = $lifecycle_state",
                space=space,
                id=record_id,
                invalidation_time=_to_iso(invalidation_time),
                lifecycle_state="invalidated",
            )

    def correct(
        self,
        space: str,
        record_id: str,
        new_statement: str,
    ) -> None:
        """Correct an Observation's statement in place."""
        with self._driver.session() as session:
            session.run(
                "MATCH (o:Observation {space: $space, id: $id}) "
                "SET o.statement = $statement",
                space=space,
                id=record_id,
                statement=new_statement,
            )

    def save_provenance(
        self,
        space: str,
        record_id: str,
        provenance: Provenance,
    ) -> None:
        """Replace the provenance for an Observation."""
        with self._driver.session() as session:
            session.run(
                "MATCH (p:Provenance)-[:PROVENANCE_OF]"
                "->(o:Observation {space: $space, id: $id}) "
                "SET p.record_id = $record_id, "
                "    p.record_kind = $record_kind, "
                "    p.source_id = $source_id, "
                "    p.episode_id = $episode_id, "
                "    p.writer = $writer, "
                "    p.reason = $reason, "
                "    p.creation_time = $creation_time, "
                "    p.validity_time = $validity_time",
                space=space,
                id=record_id,
                record_id=provenance.record_id,
                record_kind=provenance.record_kind,
                source_id=provenance.source_id,
                episode_id=provenance.episode_id,
                writer=provenance.writer,
                reason=provenance.reason,
                creation_time=_to_iso(provenance.creation_time),
                validity_time=_to_iso(provenance.validity_time),
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
        try:
            with self._driver.session() as session:
                session.run(
                    "CREATE (t:Record:Task {"
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
        except ConstraintError as e:
            _raise_duplicate_record_if_existing(
                self._driver,
                e,
                record_kind="task",
                space=task.space,
                record_id=task.id,
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

    def save_provenance(
        self,
        *,
        space: str,
        task_id: str,
        provenance: Provenance,
    ) -> None:
        """Replace the provenance for a Task."""
        with self._driver.session() as session:
            session.run(
                "MATCH (p:Provenance)-[:PROVENANCE_OF]"
                "->(t:Task {space: $space, id: $id}) "
                "SET p.record_id = $record_id, "
                "    p.record_kind = $record_kind, "
                "    p.source_id = $source_id, "
                "    p.episode_id = $episode_id, "
                "    p.writer = $writer, "
                "    p.reason = $reason, "
                "    p.creation_time = $creation_time, "
                "    p.validity_time = $validity_time",
                space=space,
                id=task_id,
                record_id=provenance.record_id,
                record_kind=provenance.record_kind,
                source_id=provenance.source_id,
                episode_id=provenance.episode_id,
                writer=provenance.writer,
                reason=provenance.reason,
                creation_time=_to_iso(provenance.creation_time),
                validity_time=_to_iso(provenance.validity_time),
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

    def list_projections_by_space(
        self,
        *,
        space: str,
        state: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        record_ids: set[str] | None = None,
    ) -> list[RecordProjection]:
        """Return Task projections filtered and ordered by Creation Time."""
        return _list_projections_by_space(
            self._driver,
            storage_label="Task",
            label_property="title",
            record_type="task",
            space=space,
            state=state,
            since=since,
            until=until,
            limit=limit,
            record_ids=record_ids,
        )


# --- Relation adapter ---


class Neo4jRelationRepository:
    """Storage adapter that persists Relations in Neo4j.

    Implements the RelationRepository and TemporalRecordRepository protocols
    defined in core.ports. Uses CREATE for append-only semantics and
    structural edges (:FROM, :TO) to connect to endpoint Entity nodes.
    """

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    def save(self, relation: Relation, provenance: Provenance) -> None:
        """Persist a Relation with structural edges and provenance.

        Uses MATCH to find existing Entity nodes and CREATE for the Relation
        node, structural edges (:FROM, :TO), and Provenance. If either
        endpoint Entity does not exist in Neo4j, the MATCH produces zero
        rows and no Relation is created. The application service validates
        entity existence before calling save().
        """
        with self._driver.session() as session:
            session.run(
                "MATCH (src:Entity {space: $space, id: $source_entity_id}) "
                "MATCH (tgt:Entity {space: $space, id: $target_entity_id}) "
                "CREATE (r:Record:Relation {"
                "  space: $space, id: $id, "
                "  source_entity_id: $source_entity_id, "
                "  target_entity_id: $target_entity_id, "
                "  relation_type: $relation_type, "
                "  statement: $statement, "
                "  validity_time: $validity_time, "
                "  invalidation_time: $invalidation_time, "
                "  lifecycle_state: $lifecycle_state, "
                "  supersedes: $supersedes, "
                "  superseded_by: $superseded_by"
                "}) "
                "CREATE (r)-[:FROM]->(src) "
                "CREATE (r)-[:TO]->(tgt) "
                "WITH r "
                "CREATE (p:Provenance {"
                "  record_id: $record_id, record_kind: $record_kind, "
                "  source_id: $source_id, episode_id: $episode_id, "
                "  writer: $writer, reason: $reason, "
                "  creation_time: $creation_time, "
                "  validity_time: $prov_validity_time"
                "}) "
                "CREATE (p)-[:PROVENANCE_OF]->(r)",
                space=relation.space,
                id=relation.id,
                source_entity_id=relation.source_entity_id,
                target_entity_id=relation.target_entity_id,
                relation_type=relation.relation_type,
                statement=relation.statement,
                validity_time=_to_iso(relation.validity_time),
                invalidation_time=_to_iso(relation.invalidation_time),
                lifecycle_state=relation.lifecycle_state,
                supersedes=relation.supersedes,
                superseded_by=relation.superseded_by,
                record_id=provenance.record_id,
                record_kind=provenance.record_kind,
                source_id=provenance.source_id,
                episode_id=provenance.episode_id,
                writer=provenance.writer,
                reason=provenance.reason,
                creation_time=_to_iso(provenance.creation_time),
                prov_validity_time=_to_iso(provenance.validity_time),
            )

    def get(self, space: str, record_id: str) -> Relation | None:
        """Retrieve a Relation by space and id, or None if not found."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (r:Relation {space: $space, id: $id}) "
                "RETURN r.id AS id, "
                "       r.source_entity_id AS source_entity_id, "
                "       r.target_entity_id AS target_entity_id, "
                "       r.relation_type AS relation_type, "
                "       r.statement AS statement, "
                "       r.space AS space, "
                "       r.validity_time AS validity_time, "
                "       r.invalidation_time AS invalidation_time, "
                "       r.lifecycle_state AS lifecycle_state, "
                "       r.supersedes AS supersedes, "
                "       r.superseded_by AS superseded_by",
                space=space,
                id=record_id,
            )
            record = result.single()
            if record is None:
                return None
            return Relation(
                id=record["id"],
                source_entity_id=record["source_entity_id"],
                target_entity_id=record["target_entity_id"],
                relation_type=record["relation_type"],
                statement=record["statement"],
                space=record["space"],
                validity_time=_from_iso(record["validity_time"]),
                invalidation_time=_from_iso(record["invalidation_time"]),
                lifecycle_state=record["lifecycle_state"],
                supersedes=record["supersedes"],
                superseded_by=record["superseded_by"],
            )

    def get_provenance(self, space: str, record_id: str) -> Provenance | None:
        """Retrieve the provenance for a Relation, or None if not found."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (p:Provenance)-[:PROVENANCE_OF]"
                "->(r:Relation {space: $space, id: $id}) "
                "RETURN p.record_id AS record_id, p.record_kind AS record_kind, "
                "       p.source_id AS source_id, p.episode_id AS episode_id, "
                "       p.writer AS writer, p.reason AS reason, "
                "       p.creation_time AS creation_time, "
                "       p.validity_time AS validity_time",
                space=space,
                id=record_id,
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

    def list_by_space(self, space: str) -> list[Relation]:
        """Return all relations in the given space."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (r:Relation {space: $space}) "
                "RETURN r.id AS id, "
                "       r.source_entity_id AS source_entity_id, "
                "       r.target_entity_id AS target_entity_id, "
                "       r.relation_type AS relation_type, "
                "       r.statement AS statement, "
                "       r.space AS space, "
                "       r.validity_time AS validity_time, "
                "       r.invalidation_time AS invalidation_time, "
                "       r.lifecycle_state AS lifecycle_state, "
                "       r.supersedes AS supersedes, "
                "       r.superseded_by AS superseded_by",
                space=space,
            )
            return [
                Relation(
                    id=record["id"],
                    source_entity_id=record["source_entity_id"],
                    target_entity_id=record["target_entity_id"],
                    relation_type=record["relation_type"],
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

    def list_projections_by_space(
        self,
        *,
        space: str,
        state: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        record_ids: set[str] | None = None,
    ) -> list[RecordProjection]:
        """Return Relation projections filtered and ordered by Creation Time."""
        return _list_projections_by_space(
            self._driver,
            storage_label="Relation",
            label_property="statement",
            record_type="relation",
            space=space,
            state=state,
            since=since,
            until=until,
            limit=limit,
            record_ids=record_ids,
        )

    def mark_superseded(
        self,
        space: str,
        record_id: str,
        superseded_by: str,
        invalidation_time: datetime,
    ) -> None:
        """Mark a Relation as superseded by another."""
        with self._driver.session() as session:
            session.run(
                "MATCH (r:Relation {space: $space, id: $id}) "
                "SET r.superseded_by = $superseded_by, "
                "    r.invalidation_time = $invalidation_time, "
                "    r.lifecycle_state = $lifecycle_state",
                space=space,
                id=record_id,
                superseded_by=superseded_by,
                invalidation_time=_to_iso(invalidation_time),
                lifecycle_state="superseded",
            )

    def list_by_entity(self, space: str, entity_id: str) -> list[Relation]:
        """Return all Relations where entity_id is source or target.

        Uses graph traversal via :FROM and :TO edges rather than
        property scanning.
        """
        with self._driver.session() as session:
            result = session.run(
                "MATCH (e:Entity {space: $space, id: $entity_id})"
                "<-[:FROM|TO]-(r:Relation {space: $space}) "
                "RETURN r.id AS id, "
                "       r.source_entity_id AS source_entity_id, "
                "       r.target_entity_id AS target_entity_id, "
                "       r.relation_type AS relation_type, "
                "       r.statement AS statement, "
                "       r.space AS space, "
                "       r.validity_time AS validity_time, "
                "       r.invalidation_time AS invalidation_time, "
                "       r.lifecycle_state AS lifecycle_state, "
                "       r.supersedes AS supersedes, "
                "       r.superseded_by AS superseded_by",
                space=space,
                entity_id=entity_id,
            )
            return [
                Relation(
                    id=record["id"],
                    source_entity_id=record["source_entity_id"],
                    target_entity_id=record["target_entity_id"],
                    relation_type=record["relation_type"],
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

    def invalidate(
        self,
        space: str,
        record_id: str,
        invalidation_time: datetime,
    ) -> None:
        """Mark a Relation as invalidated (no replacement)."""
        with self._driver.session() as session:
            session.run(
                "MATCH (r:Relation {space: $space, id: $id}) "
                "SET r.invalidation_time = $invalidation_time, "
                "    r.lifecycle_state = $lifecycle_state",
                space=space,
                id=record_id,
                invalidation_time=_to_iso(invalidation_time),
                lifecycle_state="invalidated",
            )

    def correct(
        self,
        space: str,
        record_id: str,
        new_statement: str,
    ) -> None:
        """Correct a Relation's statement in place."""
        with self._driver.session() as session:
            session.run(
                "MATCH (r:Relation {space: $space, id: $id}) "
                "SET r.statement = $statement",
                space=space,
                id=record_id,
                statement=new_statement,
            )

    def save_provenance(
        self,
        space: str,
        record_id: str,
        provenance: Provenance,
    ) -> None:
        """Replace the provenance for a Relation."""
        with self._driver.session() as session:
            session.run(
                "MATCH (p:Provenance)-[:PROVENANCE_OF]"
                "->(r:Relation {space: $space, id: $id}) "
                "SET p.record_id = $record_id, "
                "    p.record_kind = $record_kind, "
                "    p.source_id = $source_id, "
                "    p.episode_id = $episode_id, "
                "    p.writer = $writer, "
                "    p.reason = $reason, "
                "    p.creation_time = $creation_time, "
                "    p.validity_time = $validity_time",
                space=space,
                id=record_id,
                record_id=provenance.record_id,
                record_kind=provenance.record_kind,
                source_id=provenance.source_id,
                episode_id=provenance.episode_id,
                writer=provenance.writer,
                reason=provenance.reason,
                creation_time=_to_iso(provenance.creation_time),
                validity_time=_to_iso(provenance.validity_time),
            )


# --- Schema bootstrap ---


def ensure_all_constraints(
    driver: Neo4jDriver,
    *,
    vector_dimensions: int = 384,
) -> None:
    """Create expected Neo4j uniqueness constraints and vector index.

    Idempotent — uses IF NOT EXISTS so repeated calls are safe.
    """
    with driver.session() as session:
        for constraint in EXPECTED_UNIQUENESS_CONSTRAINTS:
            session.run(create_uniqueness_constraint_cypher(constraint))
        session.run(create_vector_index_cypher(dimensions=vector_dimensions))
