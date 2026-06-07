from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from memorable.config import RuntimeConfig, SQLiteSettings, StorageSettings
from memorable.core.models import Decision, Entity, Observation, Provenance, Task


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


def _provenance(record_id: str, record_kind: str) -> Provenance:
    return Provenance(
        record_id=record_id,
        record_kind=record_kind,
        source_id="source:test",
        episode_id="episode:test",
        writer="agent:test",
        reason=f"prove sqlite {record_kind} round-trip",
        creation_time=datetime(2026, 6, 7, 10, 30, tzinfo=UTC),
        validity_time=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
    )


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
        provenance = _provenance(entity.id, "entity")

        repo.save(entity, provenance)

        assert repo.get("test-project", "entity:sqlite") == entity
        assert repo.get_provenance("test-project", "entity:sqlite") == provenance
    finally:
        handle.close()


def _decision(
    record_id: str,
    *,
    state: str = "current",
    invalidation_time: datetime | None = None,
    supersedes: str | None = None,
    superseded_by: str | None = None,
) -> Decision:
    return Decision(
        id=record_id,
        statement=f"Statement for {record_id}.",
        space="test-project",
        validity_time=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
        invalidation_time=invalidation_time,
        lifecycle_state=state,
        supersedes=supersedes,
        superseded_by=superseded_by,
        record_type="ArchitectureDecision",
    )


def _observation(
    record_id: str,
    *,
    state: str = "current",
    invalidation_time: datetime | None = None,
    supersedes: str | None = None,
    superseded_by: str | None = None,
) -> Observation:
    return Observation(
        id=record_id,
        statement=f"Observation for {record_id}.",
        space="test-project",
        validity_time=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
        invalidation_time=invalidation_time,
        lifecycle_state=state,
        supersedes=supersedes,
        superseded_by=superseded_by,
        record_type="GeneralObservation",
    )


def test_sqlite_decision_repository_round_trips_record_and_provenance(
    tmp_path: Path,
) -> None:
    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import SQLiteDecisionRepository

    handle = connect(_sqlite_config(tmp_path))
    try:
        repo = SQLiteDecisionRepository(handle)
        decision = _decision(
            "decision:sqlite",
            state="superseded",
            invalidation_time=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
            supersedes="decision:old",
            superseded_by="decision:new",
        )
        provenance = _provenance(decision.id, "decision")

        repo.save(decision, provenance)

        assert repo.get("test-project", decision.id) == decision
        assert repo.get_provenance("test-project", decision.id) == provenance
    finally:
        handle.close()


def _task(
    task_id: str,
    *,
    state: str = "open",
    completion_time: datetime | None = None,
    completion_event_id: str | None = None,
) -> Task:
    return Task(
        id=task_id,
        title=f"Task for {task_id}.",
        space="test-project",
        lifecycle_state=state,
        validity_time=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
        completion_time=completion_time,
        completion_event_id=completion_event_id,
        record_type="FollowUp",
    )


def test_sqlite_observation_repository_round_trips_record_and_provenance(
    tmp_path: Path,
) -> None:
    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import SQLiteObservationRepository

    handle = connect(_sqlite_config(tmp_path))
    try:
        repo = SQLiteObservationRepository(handle)
        observation = _observation(
            "observation:sqlite",
            state="superseded",
            invalidation_time=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
            supersedes="observation:old",
            superseded_by="observation:new",
        )
        provenance = _provenance(observation.id, "observation")

        repo.save(observation, provenance)

        assert repo.get("test-project", observation.id) == observation
        assert repo.get_provenance("test-project", observation.id) == provenance
    finally:
        handle.close()


def test_sqlite_task_repository_round_trips_record_and_provenance(
    tmp_path: Path,
) -> None:
    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import SQLiteTaskRepository

    handle = connect(_sqlite_config(tmp_path))
    try:
        repo = SQLiteTaskRepository(handle)
        task = _task(
            "task:sqlite",
            state="completed",
            completion_time=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
            completion_event_id="event:complete-task:sqlite",
        )
        provenance = _provenance(task.id, "task")

        repo.save(task, provenance)

        assert repo.get(space="test-project", task_id=task.id) == task
        assert repo.get_provenance(space="test-project", task_id=task.id) == provenance
    finally:
        handle.close()


def test_sqlite_decision_correction_updates_statement_and_provenance(
    tmp_path: Path,
) -> None:
    from memorable.core.application import CorrectService
    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import SQLiteDecisionRepository

    handle = connect(_sqlite_config(tmp_path))
    try:
        repo = SQLiteDecisionRepository(handle)
        decision = _decision("decision:correct-me")
        repo.save(decision, _provenance(decision.id, "decision"))

        CorrectService(repo).correct(
            space="test-project",
            record_id=decision.id,
            new_statement="Corrected Decision.",
            record_kind="decision",
            source="source:correction",
            writer="agent:test",
            at=datetime(2026, 6, 9, 9, 0, tzinfo=UTC),
            reason="fix typo",
        )

        corrected = repo.get("test-project", decision.id)
        provenance = repo.get_provenance("test-project", decision.id)
        assert corrected is not None
        assert corrected.statement == "Corrected Decision."
        assert provenance is not None
        assert provenance.source_id == "source:correction"
        assert provenance.reason.startswith("Corrected from")
    finally:
        handle.close()


def test_sqlite_observation_invalidation_updates_lifecycle_read_path(
    tmp_path: Path,
) -> None:
    from memorable.core.application import InvalidateService
    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import SQLiteObservationRepository

    handle = connect(_sqlite_config(tmp_path))
    try:
        repo = SQLiteObservationRepository(handle)
        observation = _observation("observation:invalidate-me")
        repo.save(observation, _provenance(observation.id, "observation"))

        InvalidateService(repo).invalidate(
            space="test-project",
            record_id=observation.id,
            at=datetime(2026, 6, 9, 9, 0, tzinfo=UTC),
        )

        invalidated = repo.get("test-project", observation.id)
        assert invalidated is not None
        assert invalidated.lifecycle_state == "invalidated"
        assert invalidated.invalidation_time == datetime(2026, 6, 9, 9, 0, tzinfo=UTC)
    finally:
        handle.close()


def test_sqlite_rejects_duplicate_id_across_typed_memory_records(
    tmp_path: Path,
) -> None:
    from memorable.core.errors import DuplicateRecordError
    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import (
        SQLiteDecisionRepository,
        SQLiteTaskRepository,
    )

    handle = connect(_sqlite_config(tmp_path))
    try:
        decision_repo = SQLiteDecisionRepository(handle)
        task_repo = SQLiteTaskRepository(handle)
        decision = _decision("record:shared")
        task = _task("record:shared")
        decision_repo.save(decision, _provenance(decision.id, "decision"))

        with pytest.raises(DuplicateRecordError) as exc_info:
            task_repo.save(task, _provenance(task.id, "task"))

        assert exc_info.value.record_kind == "task"
        assert exc_info.value.space == "test-project"
        assert exc_info.value.record_id == "record:shared"
    finally:
        handle.close()


def test_sqlite_task_save_provenance_replaces_provenance(
    tmp_path: Path,
) -> None:
    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import SQLiteTaskRepository

    handle = connect(_sqlite_config(tmp_path))
    try:
        repo = SQLiteTaskRepository(handle)
        task = _task("task:replace-provenance")
        repo.save(task, _provenance(task.id, "task"))
        replacement = Provenance(
            record_id=task.id,
            record_kind="task",
            source_id="source:replacement",
            episode_id="episode:replacement",
            writer="agent:replacement",
            reason="replace provenance",
            creation_time=datetime(2026, 6, 9, 9, 0, tzinfo=UTC),
            validity_time=datetime(2026, 6, 9, 8, 0, tzinfo=UTC),
        )

        repo.save_provenance(
            space="test-project",
            task_id=task.id,
            provenance=replacement,
        )

        assert repo.get_provenance(space="test-project", task_id=task.id) == replacement
    finally:
        handle.close()


def test_sqlite_task_completion_reads_back_as_completed(
    tmp_path: Path,
) -> None:
    from memorable.core.application import CompleteTaskService, InspectTaskService
    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import SQLiteTaskRepository

    handle = connect(_sqlite_config(tmp_path))
    try:
        repo = SQLiteTaskRepository(handle)
        task = _task("task:complete-me")
        repo.save(task, _provenance(task.id, "task"))

        result = CompleteTaskService(repo).complete(
            space="test-project",
            task_id=task.id,
            at=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
        )

        inspected = InspectTaskService(repo).inspect(
            space="test-project",
            task_id=task.id,
        )
        assert result.task == inspected
        assert inspected is not None
        assert inspected.lifecycle_state == "completed"
        assert inspected.completion_time == datetime(2026, 6, 8, 9, 0, tzinfo=UTC)
        assert inspected.completion_event_id == "event:complete-task:complete-me"
    finally:
        handle.close()


def test_sqlite_decision_supersession_resolves_through_truth_services(
    tmp_path: Path,
) -> None:
    from memorable.core.application import CurrentTruthService, PointInTimeTruthService
    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import SQLiteDecisionRepository

    handle = connect(_sqlite_config(tmp_path))
    try:
        repo = SQLiteDecisionRepository(handle)
        predecessor = _decision("decision:old")
        successor = _decision("decision:new", supersedes=predecessor.id)
        repo.save(predecessor, _provenance(predecessor.id, "decision"))
        repo.save(successor, _provenance(successor.id, "decision"))

        repo.mark_superseded(
            "test-project",
            predecessor.id,
            superseded_by=successor.id,
            invalidation_time=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
        )

        assert (
            CurrentTruthService(repo).current(
                space="test-project",
                record_id=predecessor.id,
            )
            == successor
        )
        assert (
            PointInTimeTruthService(repo).at(
                space="test-project",
                record_id=predecessor.id,
                at=datetime(2026, 6, 9, 9, 0, tzinfo=UTC),
            )
            == successor
        )
    finally:
        handle.close()


@pytest.mark.parametrize("record_kind", ["decision", "observation", "task"])
def test_sqlite_typed_record_projections_are_ordered_filtered_and_bounded(
    tmp_path: Path,
    record_kind: str,
) -> None:
    from memorable.core.application import ListRecordsService
    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import (
        SQLiteDecisionRepository,
        SQLiteObservationRepository,
        SQLiteRepositoryPlaceholder,
        SQLiteTaskRepository,
    )

    handle = connect(_sqlite_config(tmp_path))
    try:
        decision_repo = SQLiteDecisionRepository(handle)
        observation_repo = SQLiteObservationRepository(handle)
        task_repo = SQLiteTaskRepository(handle)
        repo = {
            "decision": decision_repo,
            "observation": observation_repo,
            "task": task_repo,
        }[record_kind]
        records = {
            "decision": [
                _decision("decision:late"),
                _decision("decision:early"),
            ],
            "observation": [
                _observation("observation:late"),
                _observation("observation:early"),
            ],
            "task": [
                _task("task:late"),
                _task("task:early"),
            ],
        }[record_kind]
        creation_times = {
            records[0].id: datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
            records[1].id: datetime(2026, 6, 7, 10, 0, tzinfo=UTC),
        }
        for record in records:
            provenance = _provenance(record.id, record_kind)
            repo.save(
                record,
                Provenance(
                    record_id=provenance.record_id,
                    record_kind=provenance.record_kind,
                    source_id=provenance.source_id,
                    episode_id=provenance.episode_id,
                    writer=provenance.writer,
                    reason=provenance.reason,
                    creation_time=creation_times[record.id],
                    validity_time=provenance.validity_time,
                ),
            )

        projections = ListRecordsService(
            decision_repo=decision_repo,
            observation_repo=observation_repo,
            relation_repo=SQLiteRepositoryPlaceholder("Relation", 242),
            task_repo=task_repo,
        ).list_records(
            space="test-project",
            type=record_kind,
            limit=1,
        )

        assert [projection.id for projection in projections] == [records[1].id]
        assert projections[0].type == record_kind
    finally:
        handle.close()


def test_sqlite_decision_projections_are_ordered_filtered_and_bounded(
    tmp_path: Path,
) -> None:
    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import SQLiteDecisionRepository

    handle = connect(_sqlite_config(tmp_path))
    try:
        repo = SQLiteDecisionRepository(handle)
        records = [
            _decision("decision:late"),
            _decision("decision:early"),
            _decision(
                "decision:old",
                state="superseded",
                invalidation_time=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
            ),
        ]
        creation_times = {
            "decision:late": datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
            "decision:early": datetime(2026, 6, 7, 10, 0, tzinfo=UTC),
            "decision:old": datetime(2026, 6, 7, 11, 0, tzinfo=UTC),
        }
        for decision in records:
            provenance = _provenance(decision.id, "decision")
            provenance = Provenance(
                record_id=provenance.record_id,
                record_kind=provenance.record_kind,
                source_id=provenance.source_id,
                episode_id=provenance.episode_id,
                writer=provenance.writer,
                reason=provenance.reason,
                creation_time=creation_times[decision.id],
                validity_time=provenance.validity_time,
            )
            repo.save(decision, provenance)

        projections = repo.list_projections_by_space(
            space="test-project",
            state="current",
            since=datetime(2026, 6, 7, 9, 30, tzinfo=UTC),
            until=datetime(2026, 6, 7, 13, 0, tzinfo=UTC),
            limit=2,
            record_type="ArchitectureDecision",
        )

        assert [projection.id for projection in projections] == [
            "decision:early",
            "decision:late",
        ]
        assert [projection.type for projection in projections] == [
            "decision",
            "decision",
        ]
        assert [projection.label for projection in projections] == [
            "Statement for decision:early.",
            "Statement for decision:late.",
        ]
    finally:
        handle.close()


def test_sqlite_decision_repository_lists_all_lifecycle_states(
    tmp_path: Path,
) -> None:
    from memorable.storage.sqlite.connection import connect
    from memorable.storage.sqlite.repository import SQLiteDecisionRepository

    handle = connect(_sqlite_config(tmp_path))
    try:
        repo = SQLiteDecisionRepository(handle)
        current = _decision("decision:current")
        superseded = _decision(
            "decision:superseded",
            state="superseded",
            invalidation_time=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
            superseded_by="decision:replacement",
        )
        invalidated = _decision(
            "decision:invalidated",
            state="invalidated",
            invalidation_time=datetime(2026, 6, 9, 9, 0, tzinfo=UTC),
        )
        other_space = Decision(
            id="decision:other-space",
            statement="Other space.",
            space="other-space",
            validity_time=datetime(2026, 6, 7, 9, 0, tzinfo=UTC),
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        for decision in [current, superseded, invalidated, other_space]:
            repo.save(decision, _provenance(decision.id, "decision"))

        listed_ids = {decision.id for decision in repo.list_by_space("test-project")}

        assert listed_ids == {
            "decision:current",
            "decision:superseded",
            "decision:invalidated",
        }
    finally:
        handle.close()
