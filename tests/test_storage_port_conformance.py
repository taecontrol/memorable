from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from memorable.config import RuntimeConfig, SQLiteSettings, StorageSettings
from memorable.core.models import (
    Decision,
    Entity,
    MemorySpace,
    Observation,
    Provenance,
    Task,
)


@dataclass(frozen=True)
class EntityPortHarness:
    name: str
    entity_repo: Any
    memory_space_repo: Any
    close: Any


@dataclass(frozen=True)
class TemporalRecordHarness:
    name: str
    decision_repo: Any
    observation_repo: Any
    task_repo: Any
    close: Any


def _provenance(record_id: str) -> Provenance:
    return _record_provenance(record_id, "entity")


def _record_provenance(record_id: str, record_kind: str) -> Provenance:
    return Provenance(
        record_id=record_id,
        record_kind=record_kind,
        source_id="source:conformance",
        episode_id="episode:conformance",
        writer="agent:conformance",
        reason=f"prove {record_kind} port conformance",
        creation_time=datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
        validity_time=datetime(2026, 6, 7, 11, 0, tzinfo=UTC),
    )


@pytest.fixture(params=["in-memory", "neo4j", "sqlite"])
def temporal_record_harness(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> Iterator[TemporalRecordHarness]:
    if request.param == "in-memory":
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
            InMemoryObservationRepository,
            InMemoryTaskRepository,
        )

        record_keys: set[tuple[str, str]] = set()
        yield TemporalRecordHarness(
            name="in-memory",
            decision_repo=InMemoryDecisionRepository(record_keys),
            observation_repo=InMemoryObservationRepository(record_keys),
            task_repo=InMemoryTaskRepository(record_keys),
            close=lambda: None,
        )
        return

    if request.param == "neo4j":
        from test_neo4j_adapter import FakeDriver

        from memorable.storage.neo4j.repository import (
            Neo4jDecisionRepository,
            Neo4jObservationRepository,
            Neo4jTaskRepository,
        )

        driver = FakeDriver()
        yield TemporalRecordHarness(
            name="neo4j",
            decision_repo=Neo4jDecisionRepository(driver),
            observation_repo=Neo4jObservationRepository(driver),
            task_repo=Neo4jTaskRepository(driver),
            close=lambda: None,
        )
        return

    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import (
        SQLiteDecisionRepository,
        SQLiteObservationRepository,
        SQLiteTaskRepository,
    )

    config = RuntimeConfig(
        storage=StorageSettings(backend="sqlite"),
        sqlite=SQLiteSettings(path=str(tmp_path / "memory.db")),
        base_path=tmp_path,
    )
    handle = connect(config)
    try:
        yield TemporalRecordHarness(
            name="sqlite",
            decision_repo=SQLiteDecisionRepository(handle),
            observation_repo=SQLiteObservationRepository(handle),
            task_repo=SQLiteTaskRepository(handle),
            close=handle.close,
        )
    finally:
        handle.close()


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


def _decision(record_id: str, harness_name: str, *, state: str) -> Decision:
    return Decision(
        id=f"decision:{harness_name}:{record_id}",
        statement=f"Decision {record_id}.",
        space="test-conformance",
        validity_time=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
        invalidation_time=(
            datetime(2026, 6, 8, 9, 0, tzinfo=UTC) if state != "current" else None
        ),
        lifecycle_state=state,
        supersedes=None,
        superseded_by=None,
        record_type="ArchitectureDecision",
    )


def _observation(record_id: str, harness_name: str, *, state: str) -> Observation:
    return Observation(
        id=f"observation:{harness_name}:{record_id}",
        statement=f"Observation {record_id}.",
        space="test-conformance",
        validity_time=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
        invalidation_time=(
            datetime(2026, 6, 8, 9, 0, tzinfo=UTC) if state != "current" else None
        ),
        lifecycle_state=state,
        supersedes=None,
        superseded_by=None,
        record_type="GeneralObservation",
    )


def _task(record_id: str, harness_name: str, *, state: str) -> Task:
    completion_time = (
        datetime(2026, 6, 8, 9, 0, tzinfo=UTC) if state == "completed" else None
    )
    return Task(
        id=f"task:{harness_name}:{record_id}",
        title=f"Task {record_id}.",
        space="test-conformance",
        lifecycle_state=state,
        validity_time=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
        completion_time=completion_time,
        completion_event_id=(
            f"event:complete-task:{record_id}" if completion_time is not None else None
        ),
        record_type="FollowUp",
    )


@pytest.mark.parametrize(
    "record_kind",
    ["decision", "observation", "task"],
)
def test_temporal_record_save_round_trips_verbatim_through_repository_port(
    temporal_record_harness: TemporalRecordHarness,
    record_kind: str,
) -> None:
    if record_kind == "decision":
        repo = temporal_record_harness.decision_repo
        records = [
            _decision(
                "round-trip-current",
                temporal_record_harness.name,
                state="current",
            ),
            _decision(
                "round-trip-superseded",
                temporal_record_harness.name,
                state="superseded",
            ),
            _decision(
                "round-trip-invalidated",
                temporal_record_harness.name,
                state="invalidated",
            ),
        ]
    elif record_kind == "observation":
        repo = temporal_record_harness.observation_repo
        records = [
            _observation(
                "round-trip-current", temporal_record_harness.name, state="current"
            ),
            _observation(
                "round-trip-superseded",
                temporal_record_harness.name,
                state="superseded",
            ),
            _observation(
                "round-trip-invalidated",
                temporal_record_harness.name,
                state="invalidated",
            ),
        ]
    else:
        repo = temporal_record_harness.task_repo
        records = [
            _task("round-trip-open", temporal_record_harness.name, state="open"),
            _task(
                "round-trip-completed",
                temporal_record_harness.name,
                state="completed",
            ),
        ]

    for record in records:
        provenance = _record_provenance(record.id, record_kind)
        repo.save(record, provenance)

        if record_kind == "task":
            assert repo.get(space="test-conformance", task_id=record.id) == record
            assert (
                repo.get_provenance(
                    space="test-conformance",
                    task_id=record.id,
                )
                == provenance
            )
        else:
            assert repo.get("test-conformance", record.id) == record
            assert repo.get_provenance("test-conformance", record.id) == provenance


@pytest.mark.parametrize(
    "record_kind",
    ["decision", "observation", "task"],
)
def test_temporal_record_current_and_as_of_include_open_ended_successor(
    temporal_record_harness: TemporalRecordHarness,
    record_kind: str,
) -> None:
    from memorable.core.application import CurrentTruthService, PointInTimeTruthService

    if record_kind == "task":
        pytest.skip("Task uses completion lifecycle, not supersession read paths")
    if record_kind == "decision":
        repo = temporal_record_harness.decision_repo
        predecessor = _decision("old", temporal_record_harness.name, state="current")
        successor = _decision("new", temporal_record_harness.name, state="current")
        successor = Decision(
            id=successor.id,
            statement=successor.statement,
            space=successor.space,
            validity_time=successor.validity_time,
            invalidation_time=None,
            lifecycle_state=successor.lifecycle_state,
            supersedes=predecessor.id,
            superseded_by=None,
            record_type=successor.record_type,
        )
    else:
        repo = temporal_record_harness.observation_repo
        predecessor = _observation("old", temporal_record_harness.name, state="current")
        successor = _observation("new", temporal_record_harness.name, state="current")
        successor = Observation(
            id=successor.id,
            statement=successor.statement,
            space=successor.space,
            validity_time=successor.validity_time,
            invalidation_time=None,
            lifecycle_state=successor.lifecycle_state,
            supersedes=predecessor.id,
            superseded_by=None,
            record_type=successor.record_type,
        )

    repo.save(predecessor, _record_provenance(predecessor.id, record_kind))
    repo.save(successor, _record_provenance(successor.id, record_kind))
    repo.mark_superseded(
        "test-conformance",
        predecessor.id,
        superseded_by=successor.id,
        invalidation_time=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
    )

    assert (
        CurrentTruthService(repo).current(
            space="test-conformance",
            record_id=predecessor.id,
        )
        == successor
    )
    assert (
        PointInTimeTruthService(repo).at(
            space="test-conformance",
            record_id=predecessor.id,
            at=datetime(2026, 6, 9, 9, 0, tzinfo=UTC),
        )
        == successor
    )


def test_task_completion_replays_as_completed_through_task_read_path(
    temporal_record_harness: TemporalRecordHarness,
) -> None:
    from memorable.core.application import CompleteTaskService, InspectTaskService

    repo = temporal_record_harness.task_repo
    task = _task("complete-me", temporal_record_harness.name, state="open")
    repo.save(task, _record_provenance(task.id, "task"))

    result = CompleteTaskService(repo).complete(
        space="test-conformance",
        task_id=task.id,
        at=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
    )

    inspected = InspectTaskService(repo).inspect(
        space="test-conformance",
        task_id=task.id,
    )
    assert result.task == inspected
    assert inspected is not None
    assert inspected.lifecycle_state == "completed"
    assert inspected.completion_time == datetime(2026, 6, 8, 9, 0, tzinfo=UTC)
    assert inspected.completion_event_id == (
        f"event:complete-task:{task.id.split(':', 1)[-1]}"
    )


@pytest.mark.parametrize(
    "record_kind",
    ["decision", "observation", "task"],
)
def test_temporal_record_list_by_space_returns_every_lifecycle_state(
    temporal_record_harness: TemporalRecordHarness,
    record_kind: str,
) -> None:
    if record_kind == "decision":
        repo = temporal_record_harness.decision_repo
        records = [
            _decision("current", temporal_record_harness.name, state="current"),
            _decision("superseded", temporal_record_harness.name, state="superseded"),
            _decision("invalidated", temporal_record_harness.name, state="invalidated"),
        ]
        other_space = Decision(
            id=f"decision:{temporal_record_harness.name}:other",
            statement="Other space.",
            space="other-space",
            validity_time=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
    elif record_kind == "observation":
        repo = temporal_record_harness.observation_repo
        records = [
            _observation("current", temporal_record_harness.name, state="current"),
            _observation(
                "superseded", temporal_record_harness.name, state="superseded"
            ),
            _observation(
                "invalidated", temporal_record_harness.name, state="invalidated"
            ),
        ]
        other_space = Observation(
            id=f"observation:{temporal_record_harness.name}:other",
            statement="Other space.",
            space="other-space",
            validity_time=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
    else:
        repo = temporal_record_harness.task_repo
        records = [
            _task("open", temporal_record_harness.name, state="open"),
            _task("completed", temporal_record_harness.name, state="completed"),
        ]
        other_space = Task(
            id=f"task:{temporal_record_harness.name}:other",
            title="Other space.",
            space="other-space",
            lifecycle_state="open",
            validity_time=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
            completion_time=None,
            completion_event_id=None,
        )

    for record in [*records, other_space]:
        repo.save(record, _record_provenance(record.id, record_kind))

    listed_ids = {record.id for record in repo.list_by_space("test-conformance")}

    assert listed_ids == {record.id for record in records}
