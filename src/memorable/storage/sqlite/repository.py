"""SQLite adapters for Memorable Core persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from typing import Any

from memorable.core.attributes import AttributeValue
from memorable.core.models import Entity, MemorySpace, Provenance
from memorable.storage.sqlite.connection import SQLiteHandle

_DATE_ATTRIBUTE_MARKER = "date"


def _to_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("stored datetimes must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


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
            self._connection.execute(
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
                    entity.space,
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
        row = self._connection.execute(
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
            WHERE space = ? AND record_id = ? AND record_kind = 'entity'
            """,
            (space, entity_id),
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
