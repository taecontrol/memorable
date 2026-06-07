from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from memorable.config import RuntimeConfig, SQLiteSettings, StorageSettings
from memorable.core.models import Entity, MemorySpace, Provenance


@dataclass(frozen=True)
class EntityPortHarness:
    name: str
    entity_repo: Any
    memory_space_repo: Any
    close: Any


def _provenance(record_id: str) -> Provenance:
    return Provenance(
        record_id=record_id,
        record_kind="entity",
        source_id="source:conformance",
        episode_id="episode:conformance",
        writer="agent:conformance",
        reason="prove entity port conformance",
        creation_time=datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
        validity_time=datetime(2026, 6, 7, 11, 0, tzinfo=UTC),
    )


@pytest.fixture(params=["in-memory", "neo4j", "sqlite"])
def entity_port_harness(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> Iterator[EntityPortHarness]:
    if request.param == "in-memory":
        from memorable.core.repositories import (
            InMemoryEntityRepository,
            InMemoryMemorySpaceRepository,
        )

        yield EntityPortHarness(
            name="in-memory",
            entity_repo=InMemoryEntityRepository(),
            memory_space_repo=InMemoryMemorySpaceRepository(),
            close=lambda: None,
        )
        return

    if request.param == "neo4j":
        from test_neo4j_adapter import FakeDriver

        from memorable.storage.neo4j.repository import (
            Neo4jEntityRepository,
            Neo4jMemorySpaceRepository,
        )

        driver = FakeDriver()
        yield EntityPortHarness(
            name="neo4j",
            entity_repo=Neo4jEntityRepository(driver),
            memory_space_repo=Neo4jMemorySpaceRepository(driver),
            close=lambda: None,
        )
        return

    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import (
        SQLiteEntityRepository,
        SQLiteMemorySpaceRepository,
    )

    config = RuntimeConfig(
        storage=StorageSettings(backend="sqlite"),
        sqlite=SQLiteSettings(path=str(tmp_path / "memory.db")),
        base_path=tmp_path,
    )
    handle = connect(config)
    try:
        yield EntityPortHarness(
            name="sqlite",
            entity_repo=SQLiteEntityRepository(handle),
            memory_space_repo=SQLiteMemorySpaceRepository(handle),
            close=handle.close,
        )
    finally:
        handle.close()


def test_memory_space_repository_conformance(
    entity_port_harness: EntityPortHarness,
) -> None:
    repo = entity_port_harness.memory_space_repo

    created = repo.create_space("test-conformance")

    assert created == MemorySpace(name="test-conformance")
    assert repo.get_space("test-conformance") == created
    assert repo.exists("test-conformance") is True
    assert repo.get_space("missing") is None


def test_entity_save_round_trips_verbatim_through_repository_port(
    entity_port_harness: EntityPortHarness,
) -> None:
    repo = entity_port_harness.entity_repo
    entity = Entity(
        id=f"entity:{entity_port_harness.name}:1",
        entity_type="Component",
        name="Storage Adapter",
        space="test-conformance",
        attributes={
            "status": "current",
            "rank": 7,
            "first_seen": date(2026, 6, 7),
            "tags": ["portable", "local"],
        },
    )
    provenance = _provenance(entity.id)

    repo.save(entity, provenance)

    assert repo.get("test-conformance", entity.id) == entity
    assert repo.get_provenance("test-conformance", entity.id) == provenance


def test_entity_list_by_space_returns_every_entity_for_space(
    entity_port_harness: EntityPortHarness,
) -> None:
    repo = entity_port_harness.entity_repo
    entities = [
        Entity(
            id=f"entity:{entity_port_harness.name}:a",
            entity_type="Component",
            name="Alpha",
            space="test-conformance",
        ),
        Entity(
            id=f"entity:{entity_port_harness.name}:b",
            entity_type="Component",
            name="Beta",
            space="test-conformance",
        ),
        Entity(
            id=f"entity:{entity_port_harness.name}:other",
            entity_type="Component",
            name="Other",
            space="other-space",
        ),
    ]
    for entity in entities:
        repo.save(entity, _provenance(entity.id))

    listed_ids = {entity.id for entity in repo.list_by_space("test-conformance")}

    assert listed_ids == {
        f"entity:{entity_port_harness.name}:a",
        f"entity:{entity_port_harness.name}:b",
    }
