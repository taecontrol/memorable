"""Tests for the production context factory.

Verifies that build_production_context creates a Neo4j driver,
wires all four Neo4j repositories into ApplicationContext,
and fails fast when Neo4j is unreachable.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from memorable.config import RuntimeConfig


def _make_mock_driver() -> MagicMock:
    """Create a mock Neo4j driver that passes verify_connectivity."""
    driver = MagicMock()
    driver.verify_connectivity.return_value = None
    return driver


def test_build_production_context_returns_context_and_driver() -> None:
    """build_production_context returns a tuple of (ApplicationContext, driver)."""
    from memorable.core.context import ApplicationContext
    from memorable.storage.production import build_production_context

    config = RuntimeConfig()

    with patch("memorable.storage.neo4j.connection.GraphDatabase") as mock_gdb:
        mock_driver = _make_mock_driver()
        mock_gdb.driver.return_value = mock_driver

        ctx, driver = build_production_context(config)

    assert isinstance(ctx, ApplicationContext)
    driver.close()
    mock_driver.close.assert_called_once()


def test_build_production_context_wires_all_neo4j_repos() -> None:
    """All five repository slots use Neo4j adapters, not in-memory."""
    from memorable.storage.neo4j.repository import (
        Neo4jAboutRepository,
        Neo4jDecisionRepository,
        Neo4jEntityRepository,
        Neo4jMemorySpaceRepository,
        Neo4jObservationRepository,
        Neo4jTaskRepository,
    )
    from memorable.storage.production import build_production_context

    config = RuntimeConfig()

    with patch("memorable.storage.neo4j.connection.GraphDatabase") as mock_gdb:
        mock_driver = _make_mock_driver()
        mock_gdb.driver.return_value = mock_driver

        ctx, _ = build_production_context(config)

    assert isinstance(ctx.entity_repo, Neo4jEntityRepository)
    assert isinstance(ctx.decision_repo, Neo4jDecisionRepository)
    assert isinstance(ctx.task_repo, Neo4jTaskRepository)
    assert isinstance(ctx.observation_repo, Neo4jObservationRepository)
    assert isinstance(ctx.about_repo, Neo4jAboutRepository)
    assert isinstance(ctx.memory_space_repo, Neo4jMemorySpaceRepository)


def test_build_production_context_wires_sqlite_implemented_repos_and_retrieval_index(
    tmp_path,
) -> None:
    """SQLite selection wires implemented ports and persistent retrieval."""
    from memorable.config import SQLiteSettings, StorageSettings
    from memorable.storage.production import build_production_context
    from memorable.storage.sqlite.connection import SQLiteHandle
    from memorable.storage.sqlite.repository import (
        SQLiteAboutRepository,
        SQLiteDecisionRepository,
        SQLiteEntityRepository,
        SQLiteForgetRepository,
        SQLiteMemorySpaceRepository,
        SQLiteObservationRepository,
        SQLiteRelationRepository,
        SQLiteTaskRepository,
    )
    from memorable.storage.sqlite.retrieval_index import SqliteVecRetrievalIndex

    config = RuntimeConfig(
        storage=StorageSettings(backend="sqlite"),
        sqlite=SQLiteSettings(path=str(tmp_path / "memory.db")),
        base_path=tmp_path,
    )

    ctx, resource = build_production_context(config)
    try:
        assert isinstance(resource, SQLiteHandle)
        assert isinstance(ctx.entity_repo, SQLiteEntityRepository)
        assert isinstance(ctx.decision_repo, SQLiteDecisionRepository)
        assert isinstance(ctx.observation_repo, SQLiteObservationRepository)
        assert isinstance(ctx.relation_repo, SQLiteRelationRepository)
        assert isinstance(ctx.task_repo, SQLiteTaskRepository)
        assert isinstance(ctx.about_repo, SQLiteAboutRepository)
        assert isinstance(ctx.forget_repo, SQLiteForgetRepository)
        assert isinstance(ctx.memory_space_repo, SQLiteMemorySpaceRepository)
        assert isinstance(ctx.retrieval_index, SqliteVecRetrievalIndex)
    finally:
        resource.close()


def test_neo4j_backend_construction_skips_sqlite_vec_capability_probe() -> None:
    """Selecting Neo4j does not invoke the SQLite vector capability probe."""
    from memorable.storage.production import build_production_context

    config = RuntimeConfig()

    with (
        patch("memorable.storage.neo4j.connection.GraphDatabase") as mock_gdb,
        patch(
            "memorable.storage.sqlite.retrieval_index.probe_sqlite_vec_loadability",
            side_effect=AssertionError("sqlite-vec probe should not run"),
        ) as probe,
    ):
        mock_driver = _make_mock_driver()
        mock_gdb.driver.return_value = mock_driver

        _, driver = build_production_context(config)

    driver.close()
    probe.assert_not_called()
    mock_driver.close.assert_called_once()


def test_sqlite_backend_construction_fails_loudly_when_sqlite_vec_load_fails(
    tmp_path,
) -> None:
    """SQLite construction reports interpreter remedies when sqlite-vec fails."""
    import pytest

    from memorable.config import SQLiteSettings, StorageSettings
    from memorable.storage.production import build_production_context

    config = RuntimeConfig(
        storage=StorageSettings(backend="sqlite"),
        sqlite=SQLiteSettings(path=str(tmp_path / "memory.db")),
        base_path=tmp_path,
    )

    with patch("sqlite_vec.load", side_effect=RuntimeError("extensions disabled")):
        with pytest.raises(RuntimeError) as exc_info:
            build_production_context(config)

    message = str(exc_info.value)
    assert "sqlite-vec cannot load" in message
    assert "uv-managed" in message
    assert "Homebrew" in message
    assert "conda-forge" in message
    assert "Windows >= 3.11" in message
    assert "select the Neo4j backend" in message
    assert "extensions disabled" in message


def test_sqlite_backend_construction_closes_handle_when_probe_fails(
    tmp_path,
) -> None:
    """A failed SQLite construction does not leak an unreturned handle."""
    import pytest

    from memorable.config import SQLiteSettings, StorageSettings
    from memorable.storage.production import build_production_context

    config = RuntimeConfig(
        storage=StorageSettings(backend="sqlite"),
        sqlite=SQLiteSettings(path=str(tmp_path / "memory.db")),
        base_path=tmp_path,
    )
    handle = MagicMock()
    handle.connection = MagicMock()

    with (
        patch("memorable.storage.production.connect_sqlite", return_value=handle),
        patch(
            "memorable.storage.sqlite.retrieval_index.probe_sqlite_vec_loadability",
            side_effect=RuntimeError("probe failed"),
        ),
    ):
        with pytest.raises(RuntimeError, match="probe failed"):
            build_production_context(config)

    handle.close.assert_called_once()


def test_build_production_context_fails_fast_when_neo4j_unreachable() -> None:
    """When Neo4j is unreachable, raises ConnectionError with actionable message."""
    import pytest

    from memorable.storage.production import build_production_context

    config = RuntimeConfig()

    with patch("memorable.storage.neo4j.connection.GraphDatabase") as mock_gdb:
        mock_driver = MagicMock()
        mock_driver.verify_connectivity.side_effect = Exception("connection refused")
        mock_gdb.driver.return_value = mock_driver

        with pytest.raises(ConnectionError, match="memorable db start"):
            build_production_context(config)

        # Driver should be closed after failure
        mock_driver.close.assert_called_once()


def test_fail_fast_error_includes_configured_uri() -> None:
    """The error message should include the URI that was attempted."""
    import pytest

    from memorable.storage.production import build_production_context

    config = RuntimeConfig()

    with patch("memorable.storage.neo4j.connection.GraphDatabase") as mock_gdb:
        mock_driver = MagicMock()
        mock_driver.verify_connectivity.side_effect = Exception("timeout")
        mock_gdb.driver.return_value = mock_driver

        with pytest.raises(ConnectionError, match="bolt://127.0.0.1:7687"):
            build_production_context(config)


def test_build_production_context_routes_through_connection_policy() -> None:
    """Localhost config connects to the IPv4-resolved endpoint via the policy."""
    from memorable.config import Neo4jSettings
    from memorable.storage.production import build_production_context

    config = RuntimeConfig(neo4j=Neo4jSettings(uri="bolt://localhost:7687"))

    with patch("memorable.storage.neo4j.connection.GraphDatabase") as mock_gdb:
        mock_driver = _make_mock_driver()
        mock_gdb.driver.return_value = mock_driver

        _, driver = build_production_context(config)

    driver.close()
    mock_driver.close.assert_called_once()
    assert mock_gdb.driver.call_args.args[0] == "bolt://127.0.0.1:7687"


def test_application_context_default_still_uses_in_memory() -> None:
    """ApplicationContext() with no args must still use in-memory repos.

    This is a regression guard: production wiring must not change the
    default behavior. All existing tests rely on in-memory repos.
    """
    from memorable.core.context import ApplicationContext
    from memorable.core.repositories import (
        InMemoryDecisionRepository,
        InMemoryEntityRepository,
        InMemoryMemorySpaceRepository,
        InMemoryTaskRepository,
    )

    ctx = ApplicationContext()

    assert isinstance(ctx.entity_repo, InMemoryEntityRepository)
    assert isinstance(ctx.decision_repo, InMemoryDecisionRepository)
    assert isinstance(ctx.task_repo, InMemoryTaskRepository)
    assert isinstance(ctx.memory_space_repo, InMemoryMemorySpaceRepository)


def test_build_production_context_passes_config_to_driver() -> None:
    """The factory passes URI and auth from RuntimeConfig to the driver."""
    from memorable.config import Neo4jSettings
    from memorable.storage.production import build_production_context

    custom_neo4j = Neo4jSettings(
        uri="bolt://custom-host:9999",
        user="custom-user",
        password="custom-pass",
    )
    config = RuntimeConfig(neo4j=custom_neo4j)

    with patch("memorable.storage.neo4j.connection.GraphDatabase") as mock_gdb:
        mock_driver = _make_mock_driver()
        mock_gdb.driver.return_value = mock_driver

        build_production_context(config)

    # Non-local host is preserved exactly; auth and benign-notification
    # suppression flow through the shared connection policy.
    assert mock_gdb.driver.call_args.args[0] == "bolt://custom-host:9999"
    call_kwargs = mock_gdb.driver.call_args.kwargs
    assert call_kwargs["auth"] == ("custom-user", "custom-pass")
    assert call_kwargs["notifications_disabled_classifications"] == ["UNRECOGNIZED"]


def test_build_production_context_suppresses_sparse_graph_notifications() -> None:
    """Production driver suppresses only sparse-graph UNRECOGNIZED notices."""
    from memorable.storage.production import build_production_context

    config = RuntimeConfig()

    with patch("memorable.storage.neo4j.connection.GraphDatabase") as mock_gdb:
        mock_driver = _make_mock_driver()
        mock_gdb.driver.return_value = mock_driver

        build_production_context(config)

    call_kwargs = mock_gdb.driver.call_args.kwargs
    assert call_kwargs["notifications_disabled_classifications"] == ["UNRECOGNIZED"]
    assert "PERFORMANCE" not in call_kwargs["notifications_disabled_classifications"]
    assert "notifications_min_severity" not in call_kwargs


def test_cli_init_bootstraps_constraints_with_production_context(
    tmp_path,
) -> None:
    """memorable init calls ensure_all_constraints with production context."""
    import json
    import sys
    from io import StringIO
    from pathlib import Path

    from memorable.cli import main

    tmp = Path(str(tmp_path))
    memorable_dir = tmp / ".memorable"
    memorable_dir.mkdir()
    (memorable_dir / "memory.yaml").write_text(
        "version: 1\n"
        "space:\n"
        "  name: test-project\n"
        "  description: Test\n"
        "entities:\n"
        "  - name: Component\n"
        "records:\n"
        "  - name: ArchitectureDecision\n"
        "    extends: Decision\n",
        encoding="utf-8",
    )

    with (
        patch("memorable.cli.build_production_context") as mock_build,
        patch("memorable.cli.ensure_all_constraints") as mock_constraints,
        patch("memorable.cli.load_runtime_config") as mock_config,
    ):
        mock_driver = _make_mock_driver()
        # Use a real ApplicationContext so InitService works
        from memorable.core.context import ApplicationContext

        ctx = ApplicationContext()
        mock_build.return_value = (ctx, mock_driver)
        mock_config.return_value = RuntimeConfig()

        old_stdout = sys.stdout
        sys.stdout = captured = StringIO()
        try:
            rc = main(["init", "--path", str(tmp)])
        finally:
            sys.stdout = old_stdout

        assert rc == 0
        output = json.loads(captured.getvalue())
        assert output["space"] == "test-project"
        assert output["status"] == "initialized"

        # Constraints should have been bootstrapped
        mock_constraints.assert_called_once_with(
            mock_driver, vector_dimensions=RuntimeConfig().embeddings.dimensions
        )

        # Driver should be closed after init completes
        mock_driver.close.assert_called_once()


def test_cli_init_with_sqlite_initializes_space_and_closes_resource(
    tmp_path,
    capsys,
) -> None:
    """memorable init works with SQLite without Neo4j schema bootstrap."""
    import json

    from memorable.cli import main

    memorable_dir = tmp_path / ".memorable"
    memorable_dir.mkdir()
    (memorable_dir / "runtime.yaml").write_text(
        "storage:\n  backend: sqlite\nsqlite:\n  path: .memorable/memory.db\n",
        encoding="utf-8",
    )
    (memorable_dir / "memory.yaml").write_text(
        "version: 1\n"
        "space:\n"
        "  name: sqlite-project\n"
        "  description: Test\n"
        "entities:\n"
        "  - name: Component\n",
        encoding="utf-8",
    )

    rc = main(["init", "--path", str(tmp_path)])

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["space"] == "sqlite-project"
    assert output["status"] == "initialized"
    assert (memorable_dir / "memory.db").exists()


def test_cli_init_prints_connection_error_when_neo4j_unreachable(
    tmp_path,
    capsys,
) -> None:
    """When Neo4j is unreachable, init prints the error and exits with code 1."""
    from pathlib import Path

    from memorable.cli import main

    tmp = Path(str(tmp_path))
    memorable_dir = tmp / ".memorable"
    memorable_dir.mkdir()
    (memorable_dir / "memory.yaml").write_text(
        "version: 1\n"
        "space:\n"
        "  name: test-project\n"
        "  description: Test\n"
        "entities:\n"
        "  - name: Component\n"
        "records:\n"
        "  - name: ArchitectureDecision\n"
        "    extends: Decision\n",
        encoding="utf-8",
    )

    with (
        patch(
            "memorable.cli.build_production_context",
            side_effect=ConnectionError(
                "Cannot connect to Neo4j at bolt://localhost:7687"
            ),
        ),
        patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
    ):
        rc = main(["init", "--path", str(tmp)])

    assert rc == 1
    captured = capsys.readouterr()
    assert "Cannot connect to Neo4j" in captured.err
