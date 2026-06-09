from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch


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
        SQLiteEntityRepository,
        SQLiteMemorySpaceRepository,
    )

    handle = connect_sqlite(
        RuntimeConfig(base_path=tmp_path, sqlite=SQLiteSettings(path="roundtrip.db"))
    )
    ctx = ApplicationContext(
        entity_repo=SQLiteEntityRepository(handle),
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

    assert summary.as_dict() == {"memory_spaces": 1, "entities": 1}
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

    assert first_summary.as_dict() == {"memory_spaces": 1, "entities": 2}
    assert second_summary.as_dict() == {"memory_spaces": 1, "entities": 2}
    assert intermediate_snapshot == source_snapshot
    assert target_snapshot == source_snapshot
    assert _space_entity_snapshot(source, "project-alpha") == source_snapshot


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
    source.memory_space_repo.create_space("project-alpha")
    _seed_entity(source, space="project-alpha")
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
                "project-alpha",
            ]
        )

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {
        "from": "sqlite",
        "to": "neo4j",
        "space": "project-alpha",
        "memory_spaces": 1,
        "entities": 1,
    }
    assert [call.args[0].storage.backend for call in build_context.call_args_list] == [
        "sqlite",
        "neo4j",
    ]
    assert target.entity_repo.list_by_space("project-alpha") == (
        source.entity_repo.list_by_space("project-alpha")
    )
    source_resource.close.assert_called_once_with()
    target_resource.close.assert_called_once_with()
