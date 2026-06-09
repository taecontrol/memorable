from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from memorable.retrieval.models import EmbeddingRecord

SPACE = "project-alpha"
NEO4J_FULL_SPACE = "test-migrate-full-memory-space"


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _seed_entity(ctx, *, space: str, entity_id: str = "entity:memorable") -> None:
    from memorable.core.models import Entity, Provenance

    ctx.entity_repo.save(
        Entity(
            id=entity_id,
            entity_type="Project",
            name="Memorable",
            space=space,
            attributes={"url": "https://example.test", "tags": ["memory", "agent"]},
        ),
        Provenance(
            record_id=entity_id,
            record_kind="entity",
            source_id="conversation:1",
            episode_id="episode:1",
            writer="agent:test",
            reason="seed migration fixture",
            creation_time=_at("2026-06-01T10:00:00Z"),
            validity_time=_at("2026-05-31T09:00:00Z"),
        ),
    )


def _sqlite_application_context(tmp_path: Path):
    from memorable.config import RuntimeConfig, SQLiteSettings
    from memorable.core.context import ApplicationContext
    from memorable.storage.sqlite.connection import connect as connect_sqlite
    from memorable.storage.sqlite.repository import (
        SQLiteAboutRepository,
        SQLiteDecisionRepository,
        SQLiteEntityRepository,
        SQLiteMemorySpaceRepository,
        SQLiteObservationRepository,
        SQLiteRelationRepository,
        SQLiteTaskRepository,
    )
    from memorable.storage.sqlite.retrieval_index import SqliteVecRetrievalIndex

    handle = connect_sqlite(
        RuntimeConfig(base_path=tmp_path, sqlite=SQLiteSettings(path="roundtrip.db"))
    )
    ctx = ApplicationContext(
        entity_repo=SQLiteEntityRepository(handle),
        decision_repo=SQLiteDecisionRepository(handle),
        observation_repo=SQLiteObservationRepository(handle),
        task_repo=SQLiteTaskRepository(handle),
        relation_repo=SQLiteRelationRepository(handle),
        about_repo=SQLiteAboutRepository(handle),
        memory_space_repo=SQLiteMemorySpaceRepository(handle),
        retrieval_index=SqliteVecRetrievalIndex(handle),
        atomic_write=handle.atomic_write,
    )
    return ctx, handle


def _neo4j_application_context(driver):
    from memorable.core.context import ApplicationContext
    from memorable.storage.neo4j.repository import (
        Neo4jAboutRepository,
        Neo4jDecisionRepository,
        Neo4jEntityRepository,
        Neo4jForgetRepository,
        Neo4jMemorySpaceRepository,
        Neo4jObservationRepository,
        Neo4jRelationRepository,
        Neo4jTaskRepository,
    )
    from memorable.storage.neo4j.retrieval_index import Neo4jRetrievalIndex

    return ApplicationContext(
        entity_repo=Neo4jEntityRepository(driver),
        decision_repo=Neo4jDecisionRepository(driver),
        observation_repo=Neo4jObservationRepository(driver),
        task_repo=Neo4jTaskRepository(driver),
        relation_repo=Neo4jRelationRepository(driver),
        about_repo=Neo4jAboutRepository(driver),
        forget_repo=Neo4jForgetRepository(driver),
        memory_space_repo=Neo4jMemorySpaceRepository(driver),
        retrieval_index=Neo4jRetrievalIndex(driver),
    )


def _delete_neo4j_memory_space(driver, space: str) -> None:
    with driver.session() as session:
        session.run(
            "MATCH (embedding:Embedding {space: $space}) DELETE embedding",
            space=space,
        )
        session.run(
            "MATCH (p:Provenance)-[:PROVENANCE_OF]->"
            "(record:Record {space: $space}) DETACH DELETE p",
            space=space,
        )
        session.run(
            "MATCH (p:Provenance)-[:PROVENANCE_OF]->"
            "(entity:Entity {space: $space}) DETACH DELETE p",
            space=space,
        )
        session.run(
            "MATCH (record:Record {space: $space}) DETACH DELETE record",
            space=space,
        )
        session.run(
            "MATCH (entity:Entity {space: $space}) DETACH DELETE entity",
            space=space,
        )
        session.run(
            "MATCH (memory_space:MemorySpace {name: $space}) "
            "DETACH DELETE memory_space",
            space=space,
        )


def _space_entity_snapshot(ctx, space: str):
    return (
        ctx.memory_space_repo.get_space(space),
        [
            (entity, ctx.entity_repo.get_provenance(space, entity.id))
            for entity in sorted(
                ctx.entity_repo.list_by_space(space),
                key=lambda e: e.id,
            )
        ],
    )


def _remember_decision(
    ctx,
    *,
    decision_id: str,
    statement: str,
    at: str,
    supersedes: str | None = None,
    about: list[str] | None = None,
    space: str = SPACE,
) -> None:
    from memorable.core.application import RememberDecisionService
    from memorable.core.clock import FixedClock

    RememberDecisionService(
        repository=ctx.decision_repo,
        profile=ctx.load_profile(),
        about_linker=ctx.about_linker(),
        clock=FixedClock(_at(at)),
    ).remember(
        space=space,
        decision_id=decision_id,
        statement=statement,
        source_id="conversation:decision",
        at=_at(at),
        writer="agent:test",
        reason=f"seed {decision_id}",
        supersedes=supersedes,
        about=about,
        record_type="ArchitectureDecision",
    )


def _seed_decisions_in_every_lifecycle_state(
    ctx,
    *,
    space: str = SPACE,
) -> None:
    from memorable.core.application import InvalidateService

    _remember_decision(
        ctx,
        decision_id="decision:legacy",
        statement="Use Neo4j as the only local backend.",
        at="2026-06-01T10:00:00Z",
        space=space,
    )
    _remember_decision(
        ctx,
        decision_id="decision:current",
        statement="Support SQLite and Neo4j as co-equal backends.",
        at="2026-06-02T10:00:00Z",
        supersedes="decision:legacy",
        space=space,
    )
    _remember_decision(
        ctx,
        decision_id="decision:invalidated",
        statement="The migration target may be merged automatically.",
        at="2026-06-03T10:00:00Z",
        space=space,
    )
    InvalidateService(ctx.decision_repo).invalidate(
        space=space,
        record_id="decision:invalidated",
        at=_at("2026-06-04T10:00:00Z"),
    )


def _remember_observation(
    ctx,
    *,
    observation_id: str,
    statement: str,
    at: str,
    supersedes: str | None = None,
    about: list[str] | None = None,
    space: str = SPACE,
) -> None:
    from memorable.core.application import RememberObservationService
    from memorable.core.clock import FixedClock

    RememberObservationService(
        repository=ctx.observation_repo,
        profile=ctx.load_profile(),
        about_linker=ctx.about_linker(),
        clock=FixedClock(_at(at)),
    ).remember(
        space=space,
        observation_id=observation_id,
        statement=statement,
        source_id="conversation:observation",
        at=_at(at),
        writer="agent:test",
        reason=f"seed {observation_id}",
        supersedes=supersedes,
        about=about,
        record_type="GeneralObservation",
    )


def _seed_observations_in_every_lifecycle_state(
    ctx,
    *,
    space: str = SPACE,
) -> None:
    from memorable.core.application import InvalidateService

    _remember_observation(
        ctx,
        observation_id="observation:legacy",
        statement="Migration supports only Entities.",
        at="2026-06-01T11:00:00Z",
        space=space,
    )
    _remember_observation(
        ctx,
        observation_id="observation:current",
        statement="Migration now carries temporal records.",
        at="2026-06-02T11:00:00Z",
        supersedes="observation:legacy",
        space=space,
    )
    _remember_observation(
        ctx,
        observation_id="observation:invalidated",
        statement="Invalidated observations can be ignored.",
        at="2026-06-03T11:00:00Z",
        space=space,
    )
    InvalidateService(ctx.observation_repo).invalidate(
        space=space,
        record_id="observation:invalidated",
        at=_at("2026-06-04T11:00:00Z"),
    )


def _remember_relation(
    ctx,
    *,
    relation_id: str,
    source_entity_id: str,
    target_entity_id: str,
    statement: str,
    at: str,
    supersedes: str | None = None,
    space: str = SPACE,
) -> None:
    from memorable.core.application import RememberRelationService
    from memorable.core.clock import FixedClock

    RememberRelationService(
        relation_repo=ctx.relation_repo,
        entity_repo=ctx.entity_repo,
        profile=ctx.load_profile(),
        clock=FixedClock(_at(at)),
    ).remember(
        space=space,
        relation_id=relation_id,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        relation_type="depends-on",
        statement=statement,
        source_id="conversation:relation",
        at=_at(at),
        writer="agent:test",
        reason=f"seed {relation_id}",
        supersedes=supersedes,
    )


def _seed_relation_entities(ctx, *, space: str = SPACE) -> None:
    for entity_id in ("entity:memorable", "entity:neo4j", "entity:sqlite"):
        _seed_entity(ctx, space=space, entity_id=entity_id)


def _seed_relations_in_every_lifecycle_state(
    ctx,
    *,
    space: str = SPACE,
) -> None:
    from memorable.core.application import InvalidateService

    _remember_relation(
        ctx,
        relation_id="relation:legacy",
        source_entity_id="entity:memorable",
        target_entity_id="entity:neo4j",
        statement="Memorable depends on Neo4j as its only durable backend.",
        at="2026-06-01T09:00:00Z",
        space=space,
    )
    _remember_relation(
        ctx,
        relation_id="relation:current",
        source_entity_id="entity:memorable",
        target_entity_id="entity:sqlite",
        statement="Memorable depends on SQLite for embedded storage.",
        at="2026-06-02T09:00:00Z",
        supersedes="relation:legacy",
        space=space,
    )
    _remember_relation(
        ctx,
        relation_id="relation:invalidated",
        source_entity_id="entity:sqlite",
        target_entity_id="entity:neo4j",
        statement="SQLite depends on Neo4j for migration.",
        at="2026-06-03T09:00:00Z",
        space=space,
    )
    InvalidateService(ctx.relation_repo).invalidate(
        space=space,
        record_id="relation:invalidated",
        at=_at("2026-06-04T09:00:00Z"),
    )


def _remember_task(
    ctx,
    *,
    task_id: str,
    title: str,
    at: str,
    record_type: str | None = "FollowUp",
    about: list[str] | None = None,
    space: str = SPACE,
) -> None:
    from memorable.core.application import RememberTaskService
    from memorable.core.clock import FixedClock

    RememberTaskService(
        repository=ctx.task_repo,
        profile=ctx.load_profile(),
        about_linker=ctx.about_linker(),
        clock=FixedClock(_at(at)),
    ).remember(
        space=space,
        task_id=task_id,
        title=title,
        source_id="conversation:task",
        at=_at(at),
        writer="agent:test",
        reason=f"seed {task_id}",
        about=about,
        record_type=record_type,
    )


def _seed_tasks_in_every_lifecycle_state(
    ctx,
    *,
    space: str = SPACE,
) -> None:
    _remember_task(
        ctx,
        task_id="task:open",
        title="Verify the migrated MemorySpace.",
        at="2026-06-01T12:00:00Z",
        space=space,
    )
    _remember_task(
        ctx,
        task_id="task:completed",
        title="Capture the migration requirements.",
        at="2026-06-02T12:00:00Z",
        space=space,
    )
    ctx.task_repo.complete(
        space=space,
        task_id="task:completed",
        completion_time=_at("2026-06-03T12:00:00Z"),
        completion_event_id="event:task-completed:source",
    )


def _append_first_application_context():
    from dataclasses import replace

    from memorable.core.context import ApplicationContext
    from memorable.core.repositories import InMemoryTaskRepository

    class AppendFirstTaskRepository(InMemoryTaskRepository):
        def save(self, task, provenance) -> None:
            if task.lifecycle_state == "completed":
                task = replace(
                    task,
                    lifecycle_state="open",
                    completion_time=None,
                    completion_event_id=None,
                )
            super().save(task, provenance)

    return ApplicationContext(task_repo=AppendFirstTaskRepository())


def _task_read_snapshot(ctx, *, space: str = SPACE):
    from memorable.core.application import InspectTaskService

    service = InspectTaskService(ctx.task_repo)
    tasks = sorted(ctx.task_repo.list_by_space(space), key=lambda task: task.id)
    provenance = [
        ctx.task_repo.get_provenance(space=space, task_id=task.id) for task in tasks
    ]
    return {
        "task_ids": [task.id for task in tasks],
        "open_current": service.inspect(space=space, task_id="task:open"),
        "completed_current": service.inspect(
            space=space,
            task_id="task:completed",
        ),
        "completed_before_completion": service.inspect(
            space=space,
            task_id="task:completed",
            as_of=_at("2026-06-03T11:00:00Z"),
        ),
        "completed_after_completion": service.inspect(
            space=space,
            task_id="task:completed",
            as_of=_at("2026-06-03T13:00:00Z"),
        ),
        "provenance": provenance,
    }


def _embedding(
    *,
    source_id: str,
    source_kind: str,
    vector: list[float],
    text: str,
    space: str = SPACE,
) -> EmbeddingRecord:
    return EmbeddingRecord(
        source_id=source_id,
        source_kind=source_kind,
        space=space,
        indexable_text=text,
        vector=vector,
        provider_name="verbatim-provider",
        model_name="verbatim-model",
        dimensions=3,
        indexable_text_hash=f"hash:{source_id}",
        indexable_text_version="2026-06-09",
        created_at=_at("2026-06-04T12:00:00.123456Z"),
        updated_at=_at("2026-06-05T12:00:00.654321Z"),
    )


def _seed_embeddings(ctx, *, space: str = SPACE) -> None:
    ctx.retrieval_index.store(
        _embedding(
            source_id="entity:memorable",
            source_kind="Entity",
            vector=[1.0, 0.0, 0.0],
            text="Entity: Memorable project-scoped memory.",
            space=space,
        )
    )
    ctx.retrieval_index.store(
        _embedding(
            source_id="decision:current",
            source_kind="Decision",
            vector=[0.0, 1.0, 0.0],
            text="Decision: copy Embeddings verbatim during migration.",
            space=space,
        )
    )


def _embedding_snapshot(ctx, *, space: str = SPACE):
    return sorted(
        ctx.retrieval_index.records(space=space),
        key=lambda record: (
            record.source_kind,
            record.source_id,
            record.provider_name,
            record.model_name,
            record.dimensions,
        ),
    )


def _embedding_search_ids(
    ctx,
    query_vector: list[float],
    *,
    space: str = SPACE,
) -> list[str]:
    return [
        candidate.source_id
        for candidate in ctx.retrieval_index.search(
            space=space,
            query_vector=query_vector,
            top_k=1,
            provider_name="verbatim-provider",
            model_name="verbatim-model",
            dimensions=3,
        )
    ]


def _temporal_read_snapshot(
    ctx,
    *,
    kind: str,
    root_id: str,
    invalidated_id: str,
    before_supersession: str,
    after_supersession: str,
    after_invalidation: str,
    space: str = SPACE,
):
    from memorable.core.application import (
        CurrentTruthService,
        InspectHistoryService,
        PointInTimeTruthService,
    )

    repo = {
        "decision": ctx.decision_repo,
        "observation": ctx.observation_repo,
        "relation": ctx.relation_repo,
    }[kind]
    provenance = [
        repo.get_provenance(space, record.id)
        for record in sorted(repo.list_by_space(space), key=lambda record: record.id)
    ]
    return {
        "history": InspectHistoryService(repo).history(
            space=space,
            record_id=root_id,
        ),
        "current": CurrentTruthService(repo).current(
            space=space,
            record_id=root_id,
        ),
        "point_in_time_before_supersession": PointInTimeTruthService(repo).at(
            space=space,
            record_id=root_id,
            at=_at(before_supersession),
        ),
        "point_in_time_after_supersession": PointInTimeTruthService(repo).at(
            space=space,
            record_id=root_id,
            at=_at(after_supersession),
        ),
        "invalidated_point_in_time": PointInTimeTruthService(repo).at(
            space=space,
            record_id=invalidated_id,
            at=_at(after_invalidation),
        ),
        "provenance": provenance,
    }


def _decision_read_snapshot(ctx, *, space: str = SPACE):
    return _temporal_read_snapshot(
        ctx,
        kind="decision",
        root_id="decision:legacy",
        invalidated_id="decision:invalidated",
        before_supersession="2026-06-01T12:00:00Z",
        after_supersession="2026-06-02T12:00:00Z",
        after_invalidation="2026-06-05T12:00:00Z",
        space=space,
    )


def _observation_read_snapshot(ctx, *, space: str = SPACE):
    return _temporal_read_snapshot(
        ctx,
        kind="observation",
        root_id="observation:legacy",
        invalidated_id="observation:invalidated",
        before_supersession="2026-06-01T12:00:00Z",
        after_supersession="2026-06-02T12:00:00Z",
        after_invalidation="2026-06-05T12:00:00Z",
        space=space,
    )


def test_migrator_copies_space_entities_provenance_without_changing_source() -> None:
    """Migrating copies Entities and provenance through ports."""
    from memorable.core.context import ApplicationContext
    from memorable.storage.migrate import migrate_memory_space

    source = ApplicationContext()
    target = ApplicationContext()
    source.memory_space_repo.create_space("project-alpha")
    _seed_entity(source, space="project-alpha")

    source_entities_before = list(source.entity_repo.list_by_space("project-alpha"))
    source_provenance_before = source.entity_repo.get_provenance(
        "project-alpha", "entity:memorable"
    )

    summary = migrate_memory_space(source=source, target=target, space="project-alpha")

    assert summary.as_dict() == {
        "memory_spaces": 1,
        "entities": 1,
        "decisions": 0,
        "observations": 0,
        "tasks": 0,
        "relations": 0,
        "about_links": 0,
        "embeddings": 0,
    }
    assert target.memory_space_repo.get_space("project-alpha") == (
        source.memory_space_repo.get_space("project-alpha")
    )
    assert target.entity_repo.list_by_space("project-alpha") == source_entities_before
    assert (
        target.entity_repo.get_provenance("project-alpha", "entity:memorable")
        == source_provenance_before
    )
    assert source.entity_repo.list_by_space("project-alpha") == source_entities_before
    assert (
        source.entity_repo.get_provenance("project-alpha", "entity:memorable")
        == source_provenance_before
    )


def test_round_trip_memory_to_sqlite_to_memory_preserves_spaces_entities_and_provenance(
    tmp_path: Path,
) -> None:
    """A MemorySpace round-trips in-memory → SQLite → in-memory faithfully."""
    from memorable.core.context import ApplicationContext
    from memorable.storage.migrate import migrate_memory_space

    source = ApplicationContext()
    source.memory_space_repo.create_space("project-alpha")
    _seed_entity(source, space="project-alpha", entity_id="entity:memorable")
    _seed_entity(source, space="project-alpha", entity_id="entity:sqlite")
    source_snapshot = _space_entity_snapshot(source, "project-alpha")

    sqlite_ctx, sqlite_handle = _sqlite_application_context(tmp_path)
    try:
        first_summary = migrate_memory_space(
            source=source,
            target=sqlite_ctx,
            space="project-alpha",
        )
        intermediate_snapshot = _space_entity_snapshot(sqlite_ctx, "project-alpha")

        target = ApplicationContext()
        second_summary = migrate_memory_space(
            source=sqlite_ctx,
            target=target,
            space="project-alpha",
        )
        target_snapshot = _space_entity_snapshot(target, "project-alpha")
    finally:
        sqlite_handle.close()

    assert first_summary.as_dict() == {
        "memory_spaces": 1,
        "entities": 2,
        "decisions": 0,
        "observations": 0,
        "tasks": 0,
        "relations": 0,
        "about_links": 0,
        "embeddings": 0,
    }
    assert second_summary.as_dict() == {
        "memory_spaces": 1,
        "entities": 2,
        "decisions": 0,
        "observations": 0,
        "tasks": 0,
        "relations": 0,
        "about_links": 0,
        "embeddings": 0,
    }
    assert intermediate_snapshot == source_snapshot
    assert target_snapshot == source_snapshot
    assert _space_entity_snapshot(source, "project-alpha") == source_snapshot


def test_round_trip_preserves_decisions_in_every_lifecycle_state(
    tmp_path: Path,
) -> None:
    """Decision Current Truth, PIT Truth, history, and provenance survive."""
    from memorable.core.context import ApplicationContext
    from memorable.storage.migrate import migrate_memory_space

    source = ApplicationContext()
    source.memory_space_repo.create_space(SPACE)
    _seed_decisions_in_every_lifecycle_state(source)
    source_snapshot = _decision_read_snapshot(source)

    sqlite_ctx, sqlite_handle = _sqlite_application_context(tmp_path)
    try:
        migrate_memory_space(source=source, target=sqlite_ctx, space=SPACE)
        target = ApplicationContext()
        migrate_memory_space(source=sqlite_ctx, target=target, space=SPACE)
    finally:
        sqlite_handle.close()

    assert [record.lifecycle_state for record in source_snapshot["history"]] == [
        "superseded",
        "current",
    ]
    assert source_snapshot["current"].id == "decision:current"
    assert source_snapshot["point_in_time_before_supersession"].id == (
        "decision:legacy"
    )
    assert source_snapshot["point_in_time_after_supersession"].id == (
        "decision:current"
    )
    assert source_snapshot["invalidated_point_in_time"].lifecycle_state == (
        "invalidated"
    )
    assert _decision_read_snapshot(target) == source_snapshot
    assert _decision_read_snapshot(source) == source_snapshot


def test_round_trip_preserves_observations_in_every_lifecycle_state(
    tmp_path: Path,
) -> None:
    """Observation Current Truth, PIT Truth, history, and provenance survive."""
    from memorable.core.context import ApplicationContext
    from memorable.storage.migrate import migrate_memory_space

    source = ApplicationContext()
    source.memory_space_repo.create_space(SPACE)
    _seed_observations_in_every_lifecycle_state(source)
    source_snapshot = _observation_read_snapshot(source)

    sqlite_ctx, sqlite_handle = _sqlite_application_context(tmp_path)
    try:
        migrate_memory_space(source=source, target=sqlite_ctx, space=SPACE)
        target = ApplicationContext()
        migrate_memory_space(source=sqlite_ctx, target=target, space=SPACE)
    finally:
        sqlite_handle.close()

    assert [record.lifecycle_state for record in source_snapshot["history"]] == [
        "superseded",
        "current",
    ]
    assert source_snapshot["current"].id == "observation:current"
    assert source_snapshot["point_in_time_before_supersession"].id == (
        "observation:legacy"
    )
    assert source_snapshot["point_in_time_after_supersession"].id == (
        "observation:current"
    )
    assert source_snapshot["invalidated_point_in_time"].lifecycle_state == (
        "invalidated"
    )
    assert _observation_read_snapshot(target) == source_snapshot
    assert _observation_read_snapshot(source) == source_snapshot


def _relation_read_snapshot(ctx, *, space: str = SPACE):
    snapshot = _temporal_read_snapshot(
        ctx,
        kind="relation",
        root_id="relation:legacy",
        invalidated_id="relation:invalidated",
        before_supersession="2026-06-01T12:00:00Z",
        after_supersession="2026-06-02T12:00:00Z",
        after_invalidation="2026-06-05T12:00:00Z",
        space=space,
    )
    snapshot["relations_by_entity"] = sorted(
        ctx.relation_repo.list_by_entity(space, "entity:memorable"),
        key=lambda relation: relation.id,
    )
    return snapshot


def _seed_about_records(ctx, *, space: str = SPACE) -> None:
    _remember_decision(
        ctx,
        decision_id="decision:about-migration",
        statement="Migration preserves About membership.",
        at="2026-06-01T13:00:00Z",
        about=["entity:memorable", "entity:sqlite"],
        space=space,
    )
    _remember_observation(
        ctx,
        observation_id="observation:about-migration",
        statement="About links remain symmetric after migration.",
        at="2026-06-01T14:00:00Z",
        about=["entity:neo4j"],
        space=space,
    )
    _remember_task(
        ctx,
        task_id="task:about-migration",
        title="Verify migrated About links.",
        at="2026-06-01T15:00:00Z",
        about=["entity:memorable"],
        space=space,
    )


def _record_ids_that_may_have_about(ctx, *, space: str = SPACE) -> list[str]:
    return sorted(
        record.id
        for records in (
            ctx.decision_repo.list_by_space(space),
            ctx.observation_repo.list_by_space(space),
            ctx.task_repo.list_by_space(space),
            ctx.relation_repo.list_by_space(space),
        )
        for record in records
    )


def _about_snapshot(ctx, *, space: str = SPACE):
    record_to_entities = {
        record_id: ctx.about_repo.entities_for_record(space, record_id)
        for record_id in _record_ids_that_may_have_about(ctx, space=space)
    }
    entity_to_records = {
        entity.id: ctx.about_repo.records_for_entity(space, entity.id)
        for entity in sorted(
            ctx.entity_repo.list_by_space(space),
            key=lambda entity: entity.id,
        )
    }
    return {
        "entities_for_record": {
            record_id: entity_ids
            for record_id, entity_ids in record_to_entities.items()
            if entity_ids
        },
        "records_for_entity": {
            entity_id: record_ids
            for entity_id, record_ids in entity_to_records.items()
            if record_ids
        },
    }


def _seed_full_memory_space(ctx, *, space: str = SPACE) -> None:
    """Build a fully populated MemorySpace, including an erased Task."""
    from memorable.core.application import ForgetService

    ctx.memory_space_repo.create_space(space)
    _seed_relation_entities(ctx, space=space)
    _seed_decisions_in_every_lifecycle_state(ctx, space=space)
    _seed_observations_in_every_lifecycle_state(ctx, space=space)
    _seed_tasks_in_every_lifecycle_state(ctx, space=space)
    _seed_relations_in_every_lifecycle_state(ctx, space=space)
    _seed_about_records(ctx, space=space)
    _remember_task(
        ctx,
        task_id="task:forgotten",
        title="This forgotten Task must leave no tombstone to migrate.",
        at="2026-06-01T16:00:00Z",
        about=["entity:memorable"],
        space=space,
    )
    ForgetService(ctx.forget_repo).forget_record(
        space=space,
        record_id="task:forgotten",
        record_kind="task",
    )
    _seed_embeddings(ctx, space=space)


def _expected_full_summary() -> dict[str, int]:
    return {
        "memory_spaces": 1,
        "entities": 3,
        "decisions": 4,
        "observations": 4,
        "tasks": 3,
        "relations": 3,
        "about_links": 4,
        "embeddings": 2,
    }


def _full_memory_space_snapshot(ctx, *, space: str = SPACE):
    from memorable.core.application import InspectTaskService

    return {
        "space_entities": _space_entity_snapshot(ctx, space),
        "decisions": _decision_read_snapshot(ctx, space=space),
        "observations": _observation_read_snapshot(ctx, space=space),
        "tasks": _task_read_snapshot(ctx, space=space),
        "relations": _relation_read_snapshot(ctx, space=space),
        "about": _about_snapshot(ctx, space=space),
        "embeddings": _embedding_snapshot(ctx, space=space),
        "forgotten_task_current": InspectTaskService(ctx.task_repo).inspect(
            space=space,
            task_id="task:forgotten",
        ),
        "forgotten_task_about": ctx.about_repo.entities_for_record(
            space,
            "task:forgotten",
        ),
    }


def test_round_trip_preserves_tasks_with_completion_replayed_as_append_first_event(
    tmp_path: Path,
) -> None:
    """Open and completed Tasks survive via the Task read path."""
    from memorable.core.context import ApplicationContext
    from memorable.storage.migrate import migrate_memory_space

    source = ApplicationContext()
    source.memory_space_repo.create_space(SPACE)
    _seed_tasks_in_every_lifecycle_state(source)
    source_snapshot = _task_read_snapshot(source)

    sqlite_ctx, sqlite_handle = _sqlite_application_context(tmp_path)
    try:
        migrate_memory_space(source=source, target=sqlite_ctx, space=SPACE)
        target = _append_first_application_context()
        migrate_memory_space(source=sqlite_ctx, target=target, space=SPACE)
    finally:
        sqlite_handle.close()

    assert source_snapshot["open_current"].lifecycle_state == "open"
    assert source_snapshot["completed_current"].lifecycle_state == "completed"
    assert source_snapshot["completed_current"].completion_time == _at(
        "2026-06-03T12:00:00Z"
    )
    assert source_snapshot["completed_current"].completion_event_id == (
        "event:task-completed:source"
    )
    assert source_snapshot["completed_before_completion"].lifecycle_state == "open"
    assert source_snapshot["completed_before_completion"].completion_time is None
    assert source_snapshot["completed_after_completion"].lifecycle_state == (
        "completed"
    )
    assert _task_read_snapshot(target) == source_snapshot
    assert _task_read_snapshot(source) == source_snapshot


def test_round_trip_preserves_relations_in_every_lifecycle_state(
    tmp_path: Path,
) -> None:
    """Relation truth, endpoints, supersession, and provenance survive."""
    from memorable.core.context import ApplicationContext
    from memorable.storage.migrate import migrate_memory_space

    source = ApplicationContext()
    source.memory_space_repo.create_space(SPACE)
    _seed_relation_entities(source)
    _seed_relations_in_every_lifecycle_state(source)
    source_snapshot = _relation_read_snapshot(source)

    sqlite_ctx, sqlite_handle = _sqlite_application_context(tmp_path)
    try:
        migrate_memory_space(source=source, target=sqlite_ctx, space=SPACE)
        target = ApplicationContext()
        migrate_memory_space(source=sqlite_ctx, target=target, space=SPACE)
    finally:
        sqlite_handle.close()

    assert [record.lifecycle_state for record in source_snapshot["history"]] == [
        "superseded",
        "current",
    ]
    assert source_snapshot["current"].id == "relation:current"
    assert source_snapshot["point_in_time_before_supersession"].target_entity_id == (
        "entity:neo4j"
    )
    assert source_snapshot["point_in_time_after_supersession"].target_entity_id == (
        "entity:sqlite"
    )
    assert source_snapshot["invalidated_point_in_time"].lifecycle_state == (
        "invalidated"
    )
    assert _relation_read_snapshot(target) == source_snapshot
    assert _relation_read_snapshot(source) == source_snapshot


def test_round_trip_preserves_about_links_symmetrically_after_records_exist(
    tmp_path: Path,
) -> None:
    """About membership survives after its target records and Entities exist."""
    from memorable.core.context import ApplicationContext
    from memorable.storage.migrate import migrate_memory_space

    source = ApplicationContext()
    source.memory_space_repo.create_space(SPACE)
    _seed_relation_entities(source)
    _seed_about_records(source)
    source_snapshot = _about_snapshot(source)

    sqlite_ctx, sqlite_handle = _sqlite_application_context(tmp_path)
    try:
        first_summary = migrate_memory_space(
            source=source,
            target=sqlite_ctx,
            space=SPACE,
        )
        target = ApplicationContext()
        second_summary = migrate_memory_space(
            source=sqlite_ctx,
            target=target,
            space=SPACE,
        )
    finally:
        sqlite_handle.close()

    assert source_snapshot == {
        "entities_for_record": {
            "decision:about-migration": ["entity:memorable", "entity:sqlite"],
            "observation:about-migration": ["entity:neo4j"],
            "task:about-migration": ["entity:memorable"],
        },
        "records_for_entity": {
            "entity:memorable": ["decision:about-migration", "task:about-migration"],
            "entity:neo4j": ["observation:about-migration"],
            "entity:sqlite": ["decision:about-migration"],
        },
    }
    assert _about_snapshot(target) == source_snapshot
    assert _about_snapshot(source) == source_snapshot
    assert first_summary.as_dict()["about_links"] == 4
    assert second_summary.as_dict()["about_links"] == 4


def test_round_trip_preserves_embeddings_verbatim_and_searchable(
    tmp_path: Path,
) -> None:
    """Stored Embeddings survive migration without vector or metadata drift."""
    from memorable.core.context import ApplicationContext
    from memorable.storage.migrate import migrate_memory_space

    source = ApplicationContext()
    source.memory_space_repo.create_space(SPACE)
    _seed_entity(source, space=SPACE)
    _remember_decision(
        source,
        decision_id="decision:current",
        statement="Copy stored Embeddings verbatim during migration.",
        at="2026-06-02T10:00:00Z",
    )
    _seed_embeddings(source)
    source_snapshot = _embedding_snapshot(source)

    sqlite_ctx, sqlite_handle = _sqlite_application_context(tmp_path)
    try:
        migrate_memory_space(source=source, target=sqlite_ctx, space=SPACE)
        intermediate_snapshot = _embedding_snapshot(sqlite_ctx)
        intermediate_search_ids = _embedding_search_ids(sqlite_ctx, [1.0, 0.0, 0.0])

        target = ApplicationContext()
        migrate_memory_space(source=sqlite_ctx, target=target, space=SPACE)
        target_snapshot = _embedding_snapshot(target)
        target_search_ids = _embedding_search_ids(target, [0.0, 1.0, 0.0])
    finally:
        sqlite_handle.close()

    assert intermediate_snapshot == source_snapshot
    assert target_snapshot == source_snapshot
    assert intermediate_search_ids == ["entity:memorable"]
    assert target_search_ids == ["decision:current"]
    assert _embedding_snapshot(source) == source_snapshot


def test_full_memory_space_round_trip_is_faithful_and_non_destructive(
    tmp_path: Path,
) -> None:
    """The centerpiece round-trip preserves the whole observable MemorySpace.

    Forgotten records need no special migration handling: Forget leaves no
    tombstone, so the erased Task is absent from read paths and About membership.
    """
    from memorable.core.context import ApplicationContext
    from memorable.storage.migrate import migrate_memory_space

    source = ApplicationContext()
    _seed_full_memory_space(source)
    source_snapshot = _full_memory_space_snapshot(source)

    sqlite_ctx, sqlite_handle = _sqlite_application_context(tmp_path)
    try:
        first_summary = migrate_memory_space(
            source=source,
            target=sqlite_ctx,
            space=SPACE,
        )
        intermediate_snapshot = _full_memory_space_snapshot(sqlite_ctx)

        target = ApplicationContext()
        second_summary = migrate_memory_space(
            source=sqlite_ctx,
            target=target,
            space=SPACE,
        )
        target_snapshot = _full_memory_space_snapshot(target)
    finally:
        sqlite_handle.close()

    assert first_summary.as_dict() == _expected_full_summary()
    assert second_summary.as_dict() == _expected_full_summary()
    assert intermediate_snapshot == source_snapshot
    assert target_snapshot == source_snapshot
    assert _full_memory_space_snapshot(source) == source_snapshot
    assert source_snapshot["forgotten_task_current"] is None
    assert source_snapshot["forgotten_task_about"] == []


@pytest.mark.integration
def test_full_memory_space_round_trip_with_neo4j_when_fixture_is_available(
    live_neo4j_driver,
) -> None:
    """The same fidelity assertions cover Neo4j ↔ in-memory when available."""
    from memorable.core.context import ApplicationContext
    from memorable.storage.migrate import migrate_memory_space

    space = NEO4J_FULL_SPACE
    source = ApplicationContext()
    _seed_full_memory_space(source, space=space)
    source_snapshot = _full_memory_space_snapshot(source, space=space)

    _delete_neo4j_memory_space(live_neo4j_driver, space)
    neo4j_ctx = _neo4j_application_context(live_neo4j_driver)
    try:
        first_summary = migrate_memory_space(
            source=source,
            target=neo4j_ctx,
            space=space,
        )
        intermediate_snapshot = _full_memory_space_snapshot(neo4j_ctx, space=space)

        target = ApplicationContext()
        second_summary = migrate_memory_space(
            source=neo4j_ctx,
            target=target,
            space=space,
        )
        target_snapshot = _full_memory_space_snapshot(target, space=space)
    finally:
        _delete_neo4j_memory_space(live_neo4j_driver, space)

    assert first_summary.as_dict() == _expected_full_summary()
    assert second_summary.as_dict() == _expected_full_summary()
    assert intermediate_snapshot == source_snapshot
    assert target_snapshot == source_snapshot
    assert _full_memory_space_snapshot(source, space=space) == source_snapshot


def test_cli_migrate_rejects_existing_target_space_without_changing_either_side(
    capsys,
) -> None:
    """Migration fails loud instead of merging into an existing target space."""
    from memorable.cli import main
    from memorable.config import RuntimeConfig
    from memorable.core.context import ApplicationContext

    source = ApplicationContext()
    target = ApplicationContext()
    source.memory_space_repo.create_space("project-alpha")
    target.memory_space_repo.create_space("project-alpha")
    _seed_entity(source, space="project-alpha", entity_id="entity:source")
    _seed_entity(target, space="project-alpha", entity_id="entity:target")
    source_snapshot = _space_entity_snapshot(source, "project-alpha")
    target_snapshot = _space_entity_snapshot(target, "project-alpha")
    source_resource = MagicMock()
    target_resource = MagicMock()

    with (
        patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
        patch(
            "memorable.cli.build_production_context",
            side_effect=[(source, source_resource), (target, target_resource)],
        ),
    ):
        rc = main(
            [
                "migrate",
                "--from",
                "sqlite",
                "--to",
                "neo4j",
                "--space",
                "project-alpha",
            ]
        )

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "already exists" in captured.err
    assert _space_entity_snapshot(source, "project-alpha") == source_snapshot
    assert _space_entity_snapshot(target, "project-alpha") == target_snapshot
    source_resource.close.assert_called_once_with()
    target_resource.close.assert_called_once_with()


def test_cli_migrate_prints_summary_and_copies_between_selected_backends(
    capsys,
) -> None:
    """The migrate command resolves source/target backends and prints counts."""
    from memorable.cli import main
    from memorable.config import RuntimeConfig
    from memorable.core.context import ApplicationContext

    source = ApplicationContext()
    target = ApplicationContext()
    _seed_full_memory_space(source)
    source_resource = MagicMock()
    target_resource = MagicMock()

    with (
        patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
        patch(
            "memorable.cli.build_production_context",
            side_effect=[(source, source_resource), (target, target_resource)],
        ) as build_context,
    ):
        rc = main(
            [
                "migrate",
                "--from",
                "sqlite",
                "--to",
                "neo4j",
                "--space",
                SPACE,
            ]
        )

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {
        "from": "sqlite",
        "to": "neo4j",
        "space": SPACE,
        **_expected_full_summary(),
    }
    assert [call.args[0].storage.backend for call in build_context.call_args_list] == [
        "sqlite",
        "neo4j",
    ]
    assert target.entity_repo.list_by_space(SPACE) == source.entity_repo.list_by_space(
        SPACE
    )
    assert _decision_read_snapshot(target) == _decision_read_snapshot(source)
    assert _observation_read_snapshot(target) == _observation_read_snapshot(source)
    assert _task_read_snapshot(target) == _task_read_snapshot(source)
    assert _relation_read_snapshot(target) == _relation_read_snapshot(source)
    assert _about_snapshot(target) == _about_snapshot(source)
    assert _embedding_snapshot(target) == _embedding_snapshot(source)
    source_resource.close.assert_called_once_with()
    target_resource.close.assert_called_once_with()
