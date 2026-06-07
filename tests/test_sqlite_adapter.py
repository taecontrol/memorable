from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from memorable.config import RuntimeConfig, SQLiteSettings, StorageSettings
from memorable.core.models import Entity, Provenance


def _sqlite_config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(
        storage=StorageSettings(backend="sqlite"),
        sqlite=SQLiteSettings(path=str(tmp_path / ".memorable" / "memory.db")),
        base_path=tmp_path,
    )


def test_sqlite_connect_creates_file_and_sets_connection_invariants(
    tmp_path: Path,
) -> None:
    from memorable.storage.sqlite.connection import connect

    config = _sqlite_config(tmp_path)
    db_path = tmp_path / ".memorable" / "memory.db"

    handle = connect(config)
    try:
        assert handle.path == db_path
        assert db_path.exists()
        assert handle.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert handle.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert handle.connection.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
    finally:
        handle.close()

    second_handle = connect(config)
    try:
        assert (
            second_handle.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        )
        assert (
            second_handle.connection.execute("PRAGMA journal_mode").fetchone()[0]
            == "wal"
        )
        assert (
            second_handle.connection.execute("PRAGMA busy_timeout").fetchone()[0]
            >= 5000
        )
    finally:
        second_handle.close()


def test_sqlite_memory_space_repository_round_trips_created_space(
    tmp_path: Path,
) -> None:
    from memorable.core.models import MemorySpace
    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import SQLiteMemorySpaceRepository

    handle = connect(_sqlite_config(tmp_path))
    try:
        repo = SQLiteMemorySpaceRepository(handle)

        created = repo.create_space("test-project")

        assert created == MemorySpace(name="test-project")
        assert repo.get_space("test-project") == created
        assert repo.exists("test-project") is True
        assert repo.get_space("missing") is None
    finally:
        handle.close()


def test_sqlite_entity_repository_round_trips_entity_and_provenance(
    tmp_path: Path,
) -> None:
    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import SQLiteEntityRepository

    handle = connect(_sqlite_config(tmp_path))
    try:
        repo = SQLiteEntityRepository(handle)
        entity = Entity(
            id="entity:sqlite",
            entity_type="Component",
            name="SQLite Adapter",
            space="test-project",
            attributes={
                "status": "walking-skeleton",
                "priority": 1,
                "first_seen": date(2026, 6, 7),
                "tags": ["embedded", "local"],
            },
        )
        provenance = Provenance(
            record_id=entity.id,
            record_kind="entity",
            source_id="source:test",
            episode_id="episode:test",
            writer="agent:test",
            reason="prove sqlite entity round-trip",
            creation_time=datetime(2026, 6, 7, 10, 30, tzinfo=UTC),
            validity_time=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
        )

        repo.save(entity, provenance)

        assert repo.get("test-project", "entity:sqlite") == entity
        assert repo.get_provenance("test-project", "entity:sqlite") == provenance
    finally:
        handle.close()
