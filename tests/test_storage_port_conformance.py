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
    Relation,
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
    entity_repo: Any
    decision_repo: Any
    observation_repo: Any
    relation_repo: Any
    task_repo: Any
    about_repo: Any
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
            InMemoryAboutRepository,
            InMemoryDecisionRepository,
            InMemoryEntityRepository,
            InMemoryObservationRepository,
            InMemoryRelationRepository,
            InMemoryTaskRepository,
        )

        record_keys: set[tuple[str, str]] = set()
        yield TemporalRecordHarness(
            name="in-memory",
            entity_repo=InMemoryEntityRepository(),
            decision_repo=InMemoryDecisionRepository(record_keys),
            observation_repo=InMemoryObservationRepository(record_keys),
            relation_repo=InMemoryRelationRepository(record_keys),
            task_repo=InMemoryTaskRepository(record_keys),
            about_repo=InMemoryAboutRepository(),
            close=lambda: None,
        )
        return

    if request.param == "neo4j":
        from test_neo4j_adapter import FakeDriver

        from memorable.storage.neo4j.repository import (
            Neo4jAboutRepository,
            Neo4jDecisionRepository,
            Neo4jEntityRepository,
            Neo4jObservationRepository,
            Neo4jRelationRepository,
            Neo4jTaskRepository,
        )

        driver = FakeDriver()
        yield TemporalRecordHarness(
            name="neo4j",
            entity_repo=Neo4jEntityRepository(driver),
            decision_repo=Neo4jDecisionRepository(driver),
            observation_repo=Neo4jObservationRepository(driver),
            relation_repo=Neo4jRelationRepository(driver),
            task_repo=Neo4jTaskRepository(driver),
            about_repo=Neo4jAboutRepository(driver),
            close=lambda: None,
        )
        return

    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import (
        SQLiteAboutRepository,
        SQLiteDecisionRepository,
        SQLiteEntityRepository,
        SQLiteObservationRepository,
        SQLiteRelationRepository,
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
            entity_repo=SQLiteEntityRepository(handle),
            decision_repo=SQLiteDecisionRepository(handle),
            observation_repo=SQLiteObservationRepository(handle),
            relation_repo=SQLiteRelationRepository(handle),
            task_repo=SQLiteTaskRepository(handle),
            about_repo=SQLiteAboutRepository(handle),
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


def _relation(record_id: str, harness_name: str, *, state: str) -> Relation:
    return Relation(
        id=f"relation:{harness_name}:{record_id}",
        source_entity_id=f"entity:{harness_name}:source",
        target_entity_id=f"entity:{harness_name}:target",
        relation_type="depends-on",
        statement=f"Relation {record_id}.",
        space="test-conformance",
        validity_time=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
        invalidation_time=(
            datetime(2026, 6, 8, 9, 0, tzinfo=UTC) if state != "current" else None
        ),
        lifecycle_state=state,
        supersedes=None,
        superseded_by=None,
    )


def _save_relation_endpoints(
    entity_repo: Any,
    harness_name: str,
    *,
    space: str = "test-conformance",
) -> None:
    entity_repo.save(
        Entity(
            id=f"entity:{harness_name}:source",
            entity_type="Component",
            name="Source",
            space=space,
        ),
        _provenance(f"entity:{harness_name}:source"),
    )
    entity_repo.save(
        Entity(
            id=f"entity:{harness_name}:target",
            entity_type="Component",
            name="Target",
            space=space,
        ),
        _provenance(f"entity:{harness_name}:target"),
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
    ["decision", "observation", "relation", "task"],
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
    elif record_kind == "relation":
        repo = temporal_record_harness.relation_repo
        _save_relation_endpoints(
            temporal_record_harness.entity_repo,
            temporal_record_harness.name,
        )
        records = [
            _relation(
                "round-trip-current",
                temporal_record_harness.name,
                state="current",
            ),
            _relation(
                "round-trip-superseded",
                temporal_record_harness.name,
                state="superseded",
            ),
            _relation(
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
    ["decision", "observation", "relation", "task"],
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
    elif record_kind == "observation":
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
    else:
        repo = temporal_record_harness.relation_repo
        _save_relation_endpoints(
            temporal_record_harness.entity_repo,
            temporal_record_harness.name,
        )
        predecessor = _relation("old", temporal_record_harness.name, state="current")
        successor = _relation("new", temporal_record_harness.name, state="current")
        successor = Relation(
            id=successor.id,
            source_entity_id=successor.source_entity_id,
            target_entity_id=successor.target_entity_id,
            relation_type=successor.relation_type,
            statement=successor.statement,
            space=successor.space,
            validity_time=successor.validity_time,
            invalidation_time=None,
            lifecycle_state=successor.lifecycle_state,
            supersedes=predecessor.id,
            superseded_by=None,
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
    ["decision", "observation", "relation", "task"],
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
    elif record_kind == "relation":
        repo = temporal_record_harness.relation_repo
        _save_relation_endpoints(
            temporal_record_harness.entity_repo,
            temporal_record_harness.name,
        )
        _save_relation_endpoints(
            temporal_record_harness.entity_repo,
            temporal_record_harness.name,
            space="other-space",
        )
        records = [
            _relation("current", temporal_record_harness.name, state="current"),
            _relation("superseded", temporal_record_harness.name, state="superseded"),
            _relation("invalidated", temporal_record_harness.name, state="invalidated"),
        ]
        other_space = Relation(
            id=f"relation:{temporal_record_harness.name}:other",
            source_entity_id=f"entity:{temporal_record_harness.name}:source",
            target_entity_id=f"entity:{temporal_record_harness.name}:target",
            relation_type="depends-on",
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


def test_about_link_is_symmetric_and_unlink_removes_both_directions(
    temporal_record_harness: TemporalRecordHarness,
) -> None:
    about_repo = temporal_record_harness.about_repo
    entity_repo = temporal_record_harness.entity_repo
    decision_repo = temporal_record_harness.decision_repo
    harness_name = temporal_record_harness.name
    frontend_id = f"entity:{harness_name}:frontend"
    backend_id = f"entity:{harness_name}:backend"
    for entity_id, name in [
        (frontend_id, "Frontend"),
        (backend_id, "Backend"),
    ]:
        entity_repo.save(
            Entity(
                id=entity_id,
                entity_type="Component",
                name=name,
                space="test-conformance",
            ),
            _provenance(entity_id),
        )
    linked = _decision("about-linked", harness_name, state="current")
    sibling = _decision("about-sibling", harness_name, state="current")
    for decision in [linked, sibling]:
        decision_repo.save(decision, _record_provenance(decision.id, "decision"))

    about_repo.link("test-conformance", linked.id, [frontend_id, backend_id])
    about_repo.link("test-conformance", sibling.id, [frontend_id])

    assert about_repo.entities_for_record("test-conformance", linked.id) == [
        backend_id,
        frontend_id,
    ]
    assert about_repo.records_for_entity("test-conformance", frontend_id) == [
        linked.id,
        sibling.id,
    ]

    about_repo.unlink("test-conformance", linked.id)

    assert about_repo.entities_for_record("test-conformance", linked.id) == []
    assert about_repo.records_for_entity("test-conformance", backend_id) == []
    assert about_repo.records_for_entity("test-conformance", frontend_id) == [
        sibling.id
    ]


def test_relation_list_by_entity_returns_incident_relations(
    temporal_record_harness: TemporalRecordHarness,
) -> None:
    repo = temporal_record_harness.relation_repo
    entity_repo = temporal_record_harness.entity_repo
    harness_name = temporal_record_harness.name
    _save_relation_endpoints(entity_repo, harness_name)
    entity_repo.save(
        Entity(
            id=f"entity:{harness_name}:other",
            entity_type="Component",
            name="Other",
            space="test-conformance",
        ),
        _provenance(f"entity:{harness_name}:other"),
    )
    source_relation = _relation("source", harness_name, state="current")
    target_relation = Relation(
        id=f"relation:{harness_name}:target",
        source_entity_id=f"entity:{harness_name}:other",
        target_entity_id=f"entity:{harness_name}:source",
        relation_type="depends-on",
        statement="Other depends on Source.",
        space="test-conformance",
        validity_time=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
        invalidation_time=None,
        lifecycle_state="current",
        supersedes=None,
        superseded_by=None,
    )
    unrelated = Relation(
        id=f"relation:{harness_name}:unrelated",
        source_entity_id=f"entity:{harness_name}:target",
        target_entity_id=f"entity:{harness_name}:other",
        relation_type="depends-on",
        statement="Target depends on Other.",
        space="test-conformance",
        validity_time=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
        invalidation_time=None,
        lifecycle_state="current",
        supersedes=None,
        superseded_by=None,
    )
    for relation in [source_relation, target_relation, unrelated]:
        repo.save(relation, _record_provenance(relation.id, "relation"))

    listed_ids = {
        relation.id
        for relation in repo.list_by_entity(
            "test-conformance",
            f"entity:{harness_name}:source",
        )
    }

    assert listed_ids == {source_relation.id, target_relation.id}
