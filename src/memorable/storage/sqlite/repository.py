"""SQLite adapters for Memorable Core persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from typing import Any

from memorable.core.attributes import AttributeValue
from memorable.core.errors import DuplicateRecordError
from memorable.core.models import (
    Decision,
    Entity,
    MemorySpace,
    Observation,
    Provenance,
    ProvenanceIntegrityError,
    RecordProjection,
    Relation,
    Task,
)
from memorable.storage.sqlite.connection import SQLiteHandle

_DATE_ATTRIBUTE_MARKER = "date"


def _to_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("stored datetimes must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _optional_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _to_iso(value)


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _optional_from_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    return _from_iso(value)


def _attributes_to_json(attributes: Any) -> str:
    encoded: dict[str, object] = {}
    for name, value in dict(attributes).items():
        if isinstance(value, date) and not isinstance(value, datetime):
            encoded[name] = {"type": _DATE_ATTRIBUTE_MARKER, "value": value.isoformat()}
        else:
            encoded[name] = {"value": value}
    return json.dumps(encoded, sort_keys=True)


def _attributes_from_json(text: str) -> dict[str, AttributeValue]:
    decoded = json.loads(text)
    attributes: dict[str, AttributeValue] = {}
    for name, payload in decoded.items():
        if not isinstance(payload, dict):
            continue
        if payload.get("type") == _DATE_ATTRIBUTE_MARKER:
            attributes[name] = date.fromisoformat(str(payload["value"]))
        else:
            value = payload.get("value")
            if isinstance(value, list):
                attributes[name] = [str(item) for item in value]
            elif isinstance(value, int | float | str):
                attributes[name] = value
    return attributes


class SQLiteRepositoryPlaceholder:
    """Clear placeholder for SQLite ports implemented by later PRD slices."""

    def __init__(self, repository_name: str, slice_number: int) -> None:
        self._repository_name = repository_name
        self._slice_number = slice_number

    def __getattr__(self, method_name: str):
        def _raise_not_implemented(*args: object, **kwargs: object) -> None:
            raise NotImplementedError(
                f"SQLite backend does not implement {self._repository_name} "
                f"repository method '{method_name}' yet. This is scheduled "
                f"for #{self._slice_number}; select backend 'neo4j' for this "
                "operation until that slice lands."
            )

        return _raise_not_implemented


class SQLiteAboutRepository:
    """Storage adapter that persists About links in SQLite."""

    def __init__(self, handle: SQLiteHandle) -> None:
        self._connection = handle.connection

    def link(self, space: str, record_id: str, entity_ids: list[str]) -> None:
        try:
            with self._connection:
                self._connection.executemany(
                    """
                    INSERT INTO about_links (space, record_id, entity_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT (space, record_id, entity_id) DO NOTHING
                    """,
                    [(space, record_id, entity_id) for entity_id in entity_ids],
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                f"About link from MemoryRecord '{record_id}' in MemorySpace "
                f"'{space}' must reference an existing MemoryRecord and Entity."
            ) from exc

    def unlink(self, space: str, record_id: str) -> None:
        with self._connection:
            self._connection.execute(
                """
                DELETE FROM about_links
                WHERE space = ? AND record_id = ?
                """,
                (space, record_id),
            )

    def entities_for_record(self, space: str, record_id: str) -> list[str]:
        rows = self._connection.execute(
            """
            SELECT entity_id
            FROM about_links
            WHERE space = ? AND record_id = ?
            ORDER BY entity_id ASC
            """,
            (space, record_id),
        ).fetchall()
        return [row["entity_id"] for row in rows]

    def records_for_entity(self, space: str, entity_id: str) -> list[str]:
        rows = self._connection.execute(
            """
            SELECT record_id
            FROM about_links
            WHERE space = ? AND entity_id = ?
            ORDER BY record_id ASC
            """,
            (space, entity_id),
        ).fetchall()
        return [row["record_id"] for row in rows]


class SQLiteMemorySpaceRepository:
    """Storage adapter that persists MemorySpaces in SQLite."""

    def __init__(self, handle: SQLiteHandle) -> None:
        self._connection = handle.connection

    def create_space(self, name: str) -> MemorySpace:
        space = MemorySpace(name=name)
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO memory_spaces (name) VALUES (?)",
                    (space.name,),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"MemorySpace '{name}' already exists") from exc
        return space

    def get_space(self, name: str) -> MemorySpace | None:
        row = self._connection.execute(
            "SELECT name FROM memory_spaces WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return MemorySpace(name=row["name"])

    def exists(self, name: str) -> bool:
        return self.get_space(name) is not None


def _claim_memory_record_id(
    connection: sqlite3.Connection,
    *,
    space: str,
    record_id: str,
    record_kind: str,
) -> None:
    try:
        connection.execute(
            """
            INSERT INTO memory_records (space, id, record_kind)
            VALUES (?, ?, ?)
            """,
            (space, record_id, record_kind),
        )
    except sqlite3.IntegrityError as exc:
        raise DuplicateRecordError(
            record_kind=record_kind,
            space=space,
            record_id=record_id,
        ) from exc


def _save_provenance(
    connection: sqlite3.Connection,
    *,
    space: str,
    provenance: Provenance,
) -> None:
    connection.execute(
        """
        INSERT INTO provenance (
            space,
            record_id,
            record_kind,
            source_id,
            episode_id,
            writer,
            reason,
            creation_time,
            validity_time
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (space, record_id, record_kind) DO UPDATE SET
            source_id = excluded.source_id,
            episode_id = excluded.episode_id,
            writer = excluded.writer,
            reason = excluded.reason,
            creation_time = excluded.creation_time,
            validity_time = excluded.validity_time
        """,
        (
            space,
            provenance.record_id,
            provenance.record_kind,
            provenance.source_id,
            provenance.episode_id,
            provenance.writer,
            provenance.reason,
            _to_iso(provenance.creation_time),
            _to_iso(provenance.validity_time),
        ),
    )


def _list_projections(
    connection: sqlite3.Connection,
    *,
    source_name: str,
    label_name: str,
    record_kind: str,
    space: str,
    state: str | None,
    since: datetime | None,
    until: datetime | None,
    limit: int,
    record_ids: set[str] | None = None,
    record_type: str | None = None,
    record_type_column: str | None = "record_type",
) -> list[RecordProjection]:
    if record_type is not None and record_type_column is None:
        return []
    where = ["record.space = ?"]
    values: list[object] = [space]
    if record_ids is not None:
        placeholders = ", ".join("?" for _ in record_ids)
        where.append(f"record.id IN ({placeholders})")
        values.extend(sorted(record_ids))
    if state is not None:
        where.append("record.lifecycle_state = ?")
        values.append(state)
    if record_type is not None and record_type_column is not None:
        where.append(f"record.{record_type_column} = ?")
        values.append(record_type)
    if since is not None:
        where.append("provenance.creation_time >= ?")
        values.append(_to_iso(since))
    if until is not None:
        where.append("provenance.creation_time < ?")
        values.append(_to_iso(until))
    values.append(limit)
    record_type_expression = (
        f"record.{record_type_column}" if record_type_column is not None else "NULL"
    )
    rows = connection.execute(
        f"""
        SELECT record.id AS id,
               record.{label_name} AS label,
               record.lifecycle_state AS lifecycle_state,
               {record_type_expression} AS record_type,
               provenance.creation_time AS creation_time,
               provenance.record_id AS provenance_record_id
        FROM {source_name} AS record
        LEFT JOIN provenance
          ON provenance.space = record.space
         AND provenance.record_id = record.id
         AND provenance.record_kind = ?
        WHERE {" AND ".join(where)}
        ORDER BY provenance.creation_time ASC, record.id ASC
        LIMIT ?
        """,
        (record_kind, *values),
    ).fetchall()
    projections: list[RecordProjection] = []
    for row in rows:
        if row["provenance_record_id"] is None:
            raise ProvenanceIntegrityError(
                f"Provenance missing for {record_kind} '{row['id']}' "
                f"in MemorySpace '{space}'."
            )
        projections.append(
            RecordProjection(
                id=row["id"],
                type=record_kind,
                label=row["label"],
                lifecycle_state=row["lifecycle_state"],
                creation_time=_from_iso(row["creation_time"]),
                record_type=row["record_type"],
            )
        )
    return projections


def _get_provenance(
    connection: sqlite3.Connection,
    *,
    space: str,
    record_id: str,
    record_kind: str,
) -> Provenance | None:
    row = connection.execute(
        """
        SELECT record_id,
               record_kind,
               source_id,
               episode_id,
               writer,
               reason,
               creation_time,
               validity_time
        FROM provenance
        WHERE space = ? AND record_id = ? AND record_kind = ?
        """,
        (space, record_id, record_kind),
    ).fetchone()
    if row is None:
        return None
    return Provenance(
        record_id=row["record_id"],
        record_kind=row["record_kind"],
        source_id=row["source_id"],
        episode_id=row["episode_id"],
        writer=row["writer"],
        reason=row["reason"],
        creation_time=_from_iso(row["creation_time"]),
        validity_time=_from_iso(row["validity_time"]),
    )


class SQLiteEntityRepository:
    """Storage adapter that persists Entities in SQLite."""

    def __init__(self, handle: SQLiteHandle) -> None:
        self._connection = handle.connection

    def save(self, entity: Entity, provenance: Provenance) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO entities (space, id, entity_type, name, attributes_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (space, id) DO UPDATE SET
                    entity_type = excluded.entity_type,
                    name = excluded.name,
                    attributes_json = excluded.attributes_json
                """,
                (
                    entity.space,
                    entity.id,
                    entity.entity_type,
                    entity.name,
                    _attributes_to_json(entity.attributes),
                ),
            )
            _save_provenance(
                self._connection,
                space=entity.space,
                provenance=provenance,
            )

    def get(self, space: str, entity_id: str) -> Entity | None:
        row = self._connection.execute(
            """
            SELECT id, entity_type, name, space, attributes_json
            FROM entities
            WHERE space = ? AND id = ?
            """,
            (space, entity_id),
        ).fetchone()
        if row is None:
            return None
        return _entity_from_row(row)

    def get_provenance(self, space: str, entity_id: str) -> Provenance | None:
        return _get_provenance(
            self._connection,
            space=space,
            record_id=entity_id,
            record_kind="entity",
        )

    def list_by_space(self, space: str) -> list[Entity]:
        rows = self._connection.execute(
            """
            SELECT id, entity_type, name, space, attributes_json
            FROM entities
            WHERE space = ?
            ORDER BY id ASC
            """,
            (space,),
        ).fetchall()
        return [_entity_from_row(row) for row in rows]


def _entity_from_row(row: sqlite3.Row) -> Entity:
    return Entity(
        id=row["id"],
        entity_type=row["entity_type"],
        name=row["name"],
        space=row["space"],
        attributes=_attributes_from_json(row["attributes_json"]),
    )


class SQLiteDecisionRepository:
    """Storage adapter that persists Decisions in SQLite."""

    def __init__(self, handle: SQLiteHandle) -> None:
        self._connection = handle.connection

    def save(self, decision: Decision, provenance: Provenance) -> None:
        with self._connection:
            _claim_memory_record_id(
                self._connection,
                space=decision.space,
                record_id=decision.id,
                record_kind="decision",
            )
            self._connection.execute(
                """
                INSERT INTO decisions (
                    space,
                    id,
                    statement,
                    validity_time,
                    invalidation_time,
                    lifecycle_state,
                    supersedes,
                    superseded_by,
                    record_type
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.space,
                    decision.id,
                    decision.statement,
                    _to_iso(decision.validity_time),
                    _optional_to_iso(decision.invalidation_time),
                    decision.lifecycle_state,
                    decision.supersedes,
                    decision.superseded_by,
                    decision.record_type,
                ),
            )
            _save_provenance(
                self._connection,
                space=decision.space,
                provenance=provenance,
            )

    def get(self, space: str, record_id: str) -> Decision | None:
        row = self._connection.execute(
            """
            SELECT id,
                   statement,
                   space,
                   validity_time,
                   invalidation_time,
                   lifecycle_state,
                   supersedes,
                   superseded_by,
                   record_type
            FROM decisions
            WHERE space = ? AND id = ?
            """,
            (space, record_id),
        ).fetchone()
        if row is None:
            return None
        return _decision_from_row(row)

    def get_provenance(self, space: str, record_id: str) -> Provenance | None:
        return _get_provenance(
            self._connection,
            space=space,
            record_id=record_id,
            record_kind="decision",
        )

    def list_projections_by_space(
        self,
        *,
        space: str,
        state: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        record_ids: set[str] | None = None,
        record_type: str | None = None,
    ) -> list[RecordProjection]:
        return _list_projections(
            self._connection,
            source_name="decisions",
            label_name="statement",
            record_kind="decision",
            space=space,
            state=state,
            since=since,
            until=until,
            limit=limit,
            record_ids=record_ids,
            record_type=record_type,
        )

    def mark_superseded(
        self,
        space: str,
        record_id: str,
        superseded_by: str,
        invalidation_time: datetime,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE decisions
                SET superseded_by = ?,
                    invalidation_time = ?,
                    lifecycle_state = 'superseded'
                WHERE space = ? AND id = ?
                """,
                (
                    superseded_by,
                    _to_iso(invalidation_time),
                    space,
                    record_id,
                ),
            )

    def invalidate(
        self,
        space: str,
        record_id: str,
        invalidation_time: datetime,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE decisions
                SET invalidation_time = ?,
                    lifecycle_state = 'invalidated'
                WHERE space = ? AND id = ?
                """,
                (_to_iso(invalidation_time), space, record_id),
            )

    def correct(self, space: str, record_id: str, new_statement: str) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE decisions
                SET statement = ?
                WHERE space = ? AND id = ?
                """,
                (new_statement, space, record_id),
            )

    def save_provenance(
        self,
        space: str,
        record_id: str,
        provenance: Provenance,
    ) -> None:
        with self._connection:
            _save_provenance(self._connection, space=space, provenance=provenance)

    def list_by_space(self, space: str) -> list[Decision]:
        rows = self._connection.execute(
            """
            SELECT id,
                   statement,
                   space,
                   validity_time,
                   invalidation_time,
                   lifecycle_state,
                   supersedes,
                   superseded_by,
                   record_type
            FROM decisions
            WHERE space = ?
            ORDER BY id ASC
            """,
            (space,),
        ).fetchall()
        return [_decision_from_row(row) for row in rows]


def _decision_from_row(row: sqlite3.Row) -> Decision:
    return Decision(
        id=row["id"],
        statement=row["statement"],
        space=row["space"],
        validity_time=_from_iso(row["validity_time"]),
        invalidation_time=_optional_from_iso(row["invalidation_time"]),
        lifecycle_state=row["lifecycle_state"],
        supersedes=row["supersedes"],
        superseded_by=row["superseded_by"],
        record_type=row["record_type"],
    )


class SQLiteObservationRepository:
    """Storage adapter that persists Observations in SQLite."""

    def __init__(self, handle: SQLiteHandle) -> None:
        self._connection = handle.connection

    def save(self, observation: Observation, provenance: Provenance) -> None:
        with self._connection:
            _claim_memory_record_id(
                self._connection,
                space=observation.space,
                record_id=observation.id,
                record_kind="observation",
            )
            self._connection.execute(
                """
                INSERT INTO observations (
                    space,
                    id,
                    statement,
                    validity_time,
                    invalidation_time,
                    lifecycle_state,
                    supersedes,
                    superseded_by,
                    record_type
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.space,
                    observation.id,
                    observation.statement,
                    _to_iso(observation.validity_time),
                    _optional_to_iso(observation.invalidation_time),
                    observation.lifecycle_state,
                    observation.supersedes,
                    observation.superseded_by,
                    observation.record_type,
                ),
            )
            _save_provenance(
                self._connection,
                space=observation.space,
                provenance=provenance,
            )

    def get(self, space: str, record_id: str) -> Observation | None:
        row = self._connection.execute(
            """
            SELECT id,
                   statement,
                   space,
                   validity_time,
                   invalidation_time,
                   lifecycle_state,
                   supersedes,
                   superseded_by,
                   record_type
            FROM observations
            WHERE space = ? AND id = ?
            """,
            (space, record_id),
        ).fetchone()
        if row is None:
            return None
        return _observation_from_row(row)

    def get_provenance(self, space: str, record_id: str) -> Provenance | None:
        return _get_provenance(
            self._connection,
            space=space,
            record_id=record_id,
            record_kind="observation",
        )

    def list_projections_by_space(
        self,
        *,
        space: str,
        state: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        record_ids: set[str] | None = None,
        record_type: str | None = None,
    ) -> list[RecordProjection]:
        return _list_projections(
            self._connection,
            source_name="observations",
            label_name="statement",
            record_kind="observation",
            space=space,
            state=state,
            since=since,
            until=until,
            limit=limit,
            record_ids=record_ids,
            record_type=record_type,
        )

    def mark_superseded(
        self,
        space: str,
        record_id: str,
        superseded_by: str,
        invalidation_time: datetime,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE observations
                SET superseded_by = ?,
                    invalidation_time = ?,
                    lifecycle_state = 'superseded'
                WHERE space = ? AND id = ?
                """,
                (
                    superseded_by,
                    _to_iso(invalidation_time),
                    space,
                    record_id,
                ),
            )

    def invalidate(
        self,
        space: str,
        record_id: str,
        invalidation_time: datetime,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE observations
                SET invalidation_time = ?,
                    lifecycle_state = 'invalidated'
                WHERE space = ? AND id = ?
                """,
                (_to_iso(invalidation_time), space, record_id),
            )

    def correct(self, space: str, record_id: str, new_statement: str) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE observations
                SET statement = ?
                WHERE space = ? AND id = ?
                """,
                (new_statement, space, record_id),
            )

    def save_provenance(
        self,
        space: str,
        record_id: str,
        provenance: Provenance,
    ) -> None:
        with self._connection:
            _save_provenance(self._connection, space=space, provenance=provenance)

    def list_by_space(self, space: str) -> list[Observation]:
        rows = self._connection.execute(
            """
            SELECT id,
                   statement,
                   space,
                   validity_time,
                   invalidation_time,
                   lifecycle_state,
                   supersedes,
                   superseded_by,
                   record_type
            FROM observations
            WHERE space = ?
            ORDER BY id ASC
            """,
            (space,),
        ).fetchall()
        return [_observation_from_row(row) for row in rows]


def _observation_from_row(row: sqlite3.Row) -> Observation:
    return Observation(
        id=row["id"],
        statement=row["statement"],
        space=row["space"],
        validity_time=_from_iso(row["validity_time"]),
        invalidation_time=_optional_from_iso(row["invalidation_time"]),
        lifecycle_state=row["lifecycle_state"],
        supersedes=row["supersedes"],
        superseded_by=row["superseded_by"],
        record_type=row["record_type"],
    )


class SQLiteRelationRepository:
    """Storage adapter that persists Relations in SQLite."""

    def __init__(self, handle: SQLiteHandle) -> None:
        self._connection = handle.connection

    def save(self, relation: Relation, provenance: Provenance) -> None:
        try:
            with self._connection:
                _claim_memory_record_id(
                    self._connection,
                    space=relation.space,
                    record_id=relation.id,
                    record_kind="relation",
                )
                self._connection.execute(
                    """
                    INSERT INTO relations (
                        space,
                        id,
                        source_entity_id,
                        target_entity_id,
                        relation_type,
                        statement,
                        validity_time,
                        invalidation_time,
                        lifecycle_state,
                        supersedes,
                        superseded_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        relation.space,
                        relation.id,
                        relation.source_entity_id,
                        relation.target_entity_id,
                        relation.relation_type,
                        relation.statement,
                        _to_iso(relation.validity_time),
                        _optional_to_iso(relation.invalidation_time),
                        relation.lifecycle_state,
                        relation.supersedes,
                        relation.superseded_by,
                    ),
                )
                _save_provenance(
                    self._connection,
                    space=relation.space,
                    provenance=provenance,
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                f"Relation '{relation.id}' in MemorySpace '{relation.space}' must "
                "reference existing source Entity and target Entity endpoints."
            ) from exc

    def get(self, space: str, record_id: str) -> Relation | None:
        row = self._connection.execute(
            """
            SELECT id,
                   source_entity_id,
                   target_entity_id,
                   relation_type,
                   statement,
                   space,
                   validity_time,
                   invalidation_time,
                   lifecycle_state,
                   supersedes,
                   superseded_by
            FROM relations
            WHERE space = ? AND id = ?
            """,
            (space, record_id),
        ).fetchone()
        if row is None:
            return None
        return _relation_from_row(row)

    def get_provenance(self, space: str, record_id: str) -> Provenance | None:
        return _get_provenance(
            self._connection,
            space=space,
            record_id=record_id,
            record_kind="relation",
        )

    def list_projections_by_space(
        self,
        *,
        space: str,
        state: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        record_ids: set[str] | None = None,
        record_type: str | None = None,
    ) -> list[RecordProjection]:
        return _list_projections(
            self._connection,
            source_name="relations",
            label_name="statement",
            record_kind="relation",
            space=space,
            state=state,
            since=since,
            until=until,
            limit=limit,
            record_ids=record_ids,
            record_type=record_type,
            record_type_column=None,
        )

    def correct(self, space: str, record_id: str, new_statement: str) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE relations
                SET statement = ?
                WHERE space = ? AND id = ?
                """,
                (new_statement, space, record_id),
            )

    def save_provenance(
        self,
        space: str,
        record_id: str,
        provenance: Provenance,
    ) -> None:
        with self._connection:
            _save_provenance(self._connection, space=space, provenance=provenance)

    def invalidate(
        self,
        space: str,
        record_id: str,
        invalidation_time: datetime,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE relations
                SET invalidation_time = ?,
                    lifecycle_state = 'invalidated'
                WHERE space = ? AND id = ?
                """,
                (_to_iso(invalidation_time), space, record_id),
            )

    def mark_superseded(
        self,
        space: str,
        record_id: str,
        superseded_by: str,
        invalidation_time: datetime,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE relations
                SET superseded_by = ?,
                    invalidation_time = ?,
                    lifecycle_state = 'superseded'
                WHERE space = ? AND id = ?
                """,
                (
                    superseded_by,
                    _to_iso(invalidation_time),
                    space,
                    record_id,
                ),
            )

    def list_by_space(self, space: str) -> list[Relation]:
        rows = self._connection.execute(
            """
            SELECT id,
                   source_entity_id,
                   target_entity_id,
                   relation_type,
                   statement,
                   space,
                   validity_time,
                   invalidation_time,
                   lifecycle_state,
                   supersedes,
                   superseded_by
            FROM relations
            WHERE space = ?
            ORDER BY id ASC
            """,
            (space,),
        ).fetchall()
        return [_relation_from_row(row) for row in rows]

    def list_by_entity(self, space: str, entity_id: str) -> list[Relation]:
        rows = self._connection.execute(
            """
            SELECT id,
                   source_entity_id,
                   target_entity_id,
                   relation_type,
                   statement,
                   space,
                   validity_time,
                   invalidation_time,
                   lifecycle_state,
                   supersedes,
                   superseded_by
            FROM relations
            WHERE space = ?
              AND (source_entity_id = ? OR target_entity_id = ?)
            ORDER BY id ASC
            """,
            (space, entity_id, entity_id),
        ).fetchall()
        return [_relation_from_row(row) for row in rows]


def _relation_from_row(row: sqlite3.Row) -> Relation:
    return Relation(
        id=row["id"],
        source_entity_id=row["source_entity_id"],
        target_entity_id=row["target_entity_id"],
        relation_type=row["relation_type"],
        statement=row["statement"],
        space=row["space"],
        validity_time=_from_iso(row["validity_time"]),
        invalidation_time=_optional_from_iso(row["invalidation_time"]),
        lifecycle_state=row["lifecycle_state"],
        supersedes=row["supersedes"],
        superseded_by=row["superseded_by"],
    )


class SQLiteTaskRepository:
    """Storage adapter that persists Tasks in SQLite."""

    def __init__(self, handle: SQLiteHandle) -> None:
        self._connection = handle.connection

    def save(self, task: Task, provenance: Provenance) -> None:
        with self._connection:
            _claim_memory_record_id(
                self._connection,
                space=task.space,
                record_id=task.id,
                record_kind="task",
            )
            self._connection.execute(
                """
                INSERT INTO tasks (
                    space,
                    id,
                    title,
                    lifecycle_state,
                    validity_time,
                    completion_time,
                    completion_event_id,
                    record_type
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.space,
                    task.id,
                    task.title,
                    task.lifecycle_state,
                    _to_iso(task.validity_time),
                    _optional_to_iso(task.completion_time),
                    task.completion_event_id,
                    task.record_type,
                ),
            )
            _save_provenance(
                self._connection,
                space=task.space,
                provenance=provenance,
            )

    def get(self, *, space: str, task_id: str) -> Task | None:
        row = self._connection.execute(
            """
            SELECT id,
                   title,
                   space,
                   lifecycle_state,
                   validity_time,
                   completion_time,
                   completion_event_id,
                   record_type
            FROM tasks
            WHERE space = ? AND id = ?
            """,
            (space, task_id),
        ).fetchone()
        if row is None:
            return None
        return _task_from_row(row)

    def get_provenance(self, *, space: str, task_id: str) -> Provenance | None:
        return _get_provenance(
            self._connection,
            space=space,
            record_id=task_id,
            record_kind="task",
        )

    def save_provenance(
        self,
        *,
        space: str,
        task_id: str,
        provenance: Provenance,
    ) -> None:
        with self._connection:
            _save_provenance(self._connection, space=space, provenance=provenance)

    def list_projections_by_space(
        self,
        *,
        space: str,
        state: str | None,
        since: datetime | None,
        until: datetime | None,
        limit: int,
        record_ids: set[str] | None = None,
        record_type: str | None = None,
    ) -> list[RecordProjection]:
        return _list_projections(
            self._connection,
            source_name="tasks",
            label_name="title",
            record_kind="task",
            space=space,
            state=state,
            since=since,
            until=until,
            limit=limit,
            record_ids=record_ids,
            record_type=record_type,
        )

    def list_by_space(self, space: str) -> list[Task]:
        rows = self._connection.execute(
            """
            SELECT id,
                   title,
                   space,
                   lifecycle_state,
                   validity_time,
                   completion_time,
                   completion_event_id,
                   record_type
            FROM tasks
            WHERE space = ?
            ORDER BY id ASC
            """,
            (space,),
        ).fetchall()
        return [_task_from_row(row) for row in rows]

    def complete(
        self,
        *,
        space: str,
        task_id: str,
        completion_time: datetime,
        completion_event_id: str,
    ) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE tasks
                SET lifecycle_state = 'completed',
                    completion_time = ?,
                    completion_event_id = ?
                WHERE space = ? AND id = ?
                """,
                (
                    _to_iso(completion_time),
                    completion_event_id,
                    space,
                    task_id,
                ),
            )


def _task_from_row(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        space=row["space"],
        lifecycle_state=row["lifecycle_state"],
        validity_time=_from_iso(row["validity_time"]),
        completion_time=_optional_from_iso(row["completion_time"]),
        completion_event_id=row["completion_event_id"],
        record_type=row["record_type"],
    )
