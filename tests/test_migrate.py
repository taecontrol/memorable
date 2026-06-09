from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

SPACE = "project-alpha"


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
        SQLiteDecisionRepository,
        SQLiteEntityRepository,
        SQLiteMemorySpaceRepository,
        SQLiteObservationRepository,
    )

    handle = connect_sqlite(
        RuntimeConfig(base_path=tmp_path, sqlite=SQLiteSettings(path="roundtrip.db"))
    )
    ctx = ApplicationContext(
        entity_repo=SQLiteEntityRepository(handle),
        decision_repo=SQLiteDecisionRepository(handle),
        observation_repo=SQLiteObservationRepository(handle),
        memory_space_repo=SQLiteMemorySpaceRepository(handle),
        atomic_write=handle.atomic_write,
    )
    return ctx, handle


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
) -> None:
    from memorable.core.application import RememberDecisionService
    from memorable.core.clock import FixedClock

    RememberDecisionService(
        repository=ctx.decision_repo,
        profile=ctx.load_profile(),
        clock=FixedClock(_at(at)),
    ).remember(
        space=SPACE,
        decision_id=decision_id,
        statement=statement,
        source_id="conversation:decision",
        at=_at(at),
        writer="agent:test",
        reason=f"seed {decision_id}",
        supersedes=supersedes,
        record_type="ArchitectureDecision",
    )


def _seed_decisions_in_every_lifecycle_state(ctx) -> None:
    from memorable.core.application import InvalidateService

    _remember_decision(
        ctx,
        decision_id="decision:legacy",
        statement="Use Neo4j as the only local backend.",
        at="2026-06-01T10:00:00Z",
    )
    _remember_decision(
        ctx,
        decision_id="decision:current",
        statement="Support SQLite and Neo4j as co-equal backends.",
        at="2026-06-02T10:00:00Z",
        supersedes="decision:legacy",
    )
    _remember_decision(
        ctx,
        decision_id="decision:invalidated",
        statement="The migration target may be merged automatically.",
        at="2026-06-03T10:00:00Z",
    )
    InvalidateService(ctx.decision_repo).invalidate(
        space=SPACE,
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
) -> None:
    from memorable.core.application import RememberObservationService
    from memorable.core.clock import FixedClock

    RememberObservationService(
        repository=ctx.observation_repo,
        profile=ctx.load_profile(),
        clock=FixedClock(_at(at)),
    ).remember(
        space=SPACE,
        observation_id=observation_id,
        statement=statement,
        source_id="conversation:observation",
        at=_at(at),
        writer="agent:test",
        reason=f"seed {observation_id}",
        supersedes=supersedes,
        record_type="GeneralObservation",
    )


def _seed_observations_in_every_lifecycle_state(ctx) -> None:
    from memorable.core.application import InvalidateService

    _remember_observation(
        ctx,
        observation_id="observation:legacy",
        statement="Migration supports only Entities.",
        at="2026-06-01T11:00:00Z",
    )
    _remember_observation(
        ctx,
        observation_id="observation:current",
        statement="Migration now carries temporal records.",
        at="2026-06-02T11:00:00Z",
        supersedes="observation:legacy",
    )
    _remember_observation(
        ctx,
        observation_id="observation:invalidated",
        statement="Invalidated observations can be ignored.",
        at="2026-06-03T11:00:00Z",
    )
    InvalidateService(ctx.observation_repo).invalidate(
        space=SPACE,
        record_id="observation:invalidated",
        at=_at("2026-06-04T11:00:00Z"),
    )


def _temporal_read_snapshot(
    ctx,
    *,
    kind: str,
    root_id: str,
    invalidated_id: str,
    before_supersession: str,
    after_supersession: str,
    after_invalidation: str,
):
    from memorable.core.application import (
        CurrentTruthService,
        InspectHistoryService,
        PointInTimeTruthService,
    )

    repo = {
        "decision": ctx.decision_repo,
        "observation": ctx.observation_repo,
    }[kind]
    provenance = [
        repo.get_provenance(SPACE, record.id)
        for record in sorted(repo.list_by_space(SPACE), key=lambda record: record.id)
    ]
    return {
        "history": InspectHistoryService(repo).history(
            space=SPACE,
            record_id=root_id,
        ),
        "current": CurrentTruthService(repo).current(
            space=SPACE,
            record_id=root_id,
        ),
        "point_in_time_before_supersession": PointInTimeTruthService(repo).at(
            space=SPACE,
            record_id=root_id,
            at=_at(before_supersession),
        ),
        "point_in_time_after_supersession": PointInTimeTruthService(repo).at(
            space=SPACE,
            record_id=root_id,
            at=_at(after_supersession),
        ),
        "invalidated_point_in_time": PointInTimeTruthService(repo).at(
            space=SPACE,
            record_id=invalidated_id,
            at=_at(after_invalidation),
        ),
        "provenance": provenance,
    }


def _decision_read_snapshot(ctx):
    return _temporal_read_snapshot(
        ctx,
        kind="decision",
        root_id="decision:legacy",
        invalidated_id="decision:invalidated",
        before_supersession="2026-06-01T12:00:00Z",
        after_supersession="2026-06-02T12:00:00Z",
        after_invalidation="2026-06-05T12:00:00Z",
    )


def _observation_read_snapshot(ctx):
    return _temporal_read_snapshot(
        ctx,
        kind="observation",
        root_id="observation:legacy",
        invalidated_id="observation:invalidated",
        before_supersession="2026-06-01T12:00:00Z",
        after_supersession="2026-06-02T12:00:00Z",
        after_invalidation="2026-06-05T12:00:00Z",
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
    }
    assert second_summary.as_dict() == {
        "memory_spaces": 1,
        "entities": 2,
        "decisions": 0,
        "observations": 0,
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
    source.memory_space_repo.create_space(SPACE)
    _seed_entity(source, space=SPACE)
    _seed_decisions_in_every_lifecycle_state(source)
    _seed_observations_in_every_lifecycle_state(source)
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
        "memory_spaces": 1,
        "entities": 1,
        "decisions": 3,
        "observations": 3,
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
    source_resource.close.assert_called_once_with()
    target_resource.close.assert_called_once_with()
