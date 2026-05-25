"""Tests for CLI production wiring.

Verifies that CLI memory commands use the production context
(Neo4j-backed) instead of the in-memory default_context,
and that the driver is closed on exit.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from memorable.config import RuntimeConfig
from memorable.core.context import ApplicationContext


def _make_mock_driver() -> MagicMock:
    """Create a mock Neo4j driver that passes verify_connectivity."""
    driver = MagicMock()
    driver.verify_connectivity.return_value = None
    return driver


def _setup_workspace(tmp_path: Path) -> Path:
    """Create a .memorable/memory.yaml in tmp_path and return it."""
    memorable_dir = tmp_path / ".memorable"
    memorable_dir.mkdir()
    (memorable_dir / "memory.yaml").write_text(
        "version: 1\n"
        "space:\n"
        "  name: test-project\n"
        "  description: Test\n"
        "entities:\n"
        "  - name: Project\n"
        "  - name: Component\n"
        "records:\n"
        "  - name: ArchitectureDecision\n"
        "    extends: Decision\n",
        encoding="utf-8",
    )
    return tmp_path


class TestCLIMemoryCommandsUseProductionContext:
    """CLI memory commands use production context instead of default_context."""

    def test_remember_entity_uses_production_context(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """remember entity persists to the production context, not default_context."""
        from memorable.cli import main
        from memorable.core.context import default_context

        _setup_workspace(tmp_path)
        shared_ctx = ApplicationContext()
        mock_driver = _make_mock_driver()

        monkeypatch.chdir(tmp_path)
        with (
            patch(
                "memorable.cli.build_production_context",
            ) as mock_build,
            patch(
                "memorable.cli.load_runtime_config",
                return_value=RuntimeConfig(),
            ),
        ):
            mock_build.return_value = (shared_ctx, mock_driver)

            rc = main([
                "remember", "entity",
                "--id", "entity:test",
                "--type", "Project",
                "--name", "Test",
                "--source", "source:test",
                "--at", "2026-05-23T10:10:00Z",
            ])

        assert rc == 0

        # Verify entity was persisted in shared_ctx, not default_context
        stored = shared_ctx.entity_repo.get(
            space="test-project", entity_id="entity:test"
        )
        assert stored is not None
        assert stored.name == "Test"

        # Verify default_context was NOT used
        default_stored = default_context.entity_repo.get(
            space="test-project", entity_id="entity:test"
        )
        assert default_stored is None

    def test_driver_is_closed_on_exit(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The Neo4j driver is closed after the CLI command completes."""
        from memorable.cli import main

        _setup_workspace(tmp_path)
        shared_ctx = ApplicationContext()
        mock_driver = _make_mock_driver()

        monkeypatch.chdir(tmp_path)
        with (
            patch(
                "memorable.cli.build_production_context",
            ) as mock_build,
            patch(
                "memorable.cli.load_runtime_config",
                return_value=RuntimeConfig(),
            ),
        ):
            mock_build.return_value = (shared_ctx, mock_driver)

            main([
                "remember", "entity",
                "--id", "entity:test",
                "--type", "Project",
                "--name", "Test",
                "--source", "source:test",
                "--at", "2026-05-23T10:10:00Z",
            ])

        mock_driver.close.assert_called_once()

    def test_driver_is_closed_even_on_error(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The driver is closed even when a command fails."""
        from memorable.cli import main

        _setup_workspace(tmp_path)
        shared_ctx = ApplicationContext()
        mock_driver = _make_mock_driver()

        monkeypatch.chdir(tmp_path)
        with (
            patch(
                "memorable.cli.build_production_context",
            ) as mock_build,
            patch(
                "memorable.cli.load_runtime_config",
                return_value=RuntimeConfig(),
            ),
        ):
            mock_build.return_value = (shared_ctx, mock_driver)

            # UnknownType should cause an error
            rc = main([
                "remember", "entity",
                "--id", "entity:test",
                "--type", "UnknownType",
                "--name", "Test",
                "--source", "source:test",
                "--at", "2026-05-23T10:10:00Z",
            ])

        assert rc == 1
        mock_driver.close.assert_called_once()

    def test_space_inferred_from_memory_yaml_in_remember_entity(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """--space is optional; space is inferred from memory.yaml."""
        from memorable.cli import main

        _setup_workspace(tmp_path)
        shared_ctx = ApplicationContext()
        mock_driver = _make_mock_driver()

        monkeypatch.chdir(tmp_path)
        with (
            patch(
                "memorable.cli.build_production_context",
            ) as mock_build,
            patch(
                "memorable.cli.load_runtime_config",
                return_value=RuntimeConfig(),
            ),
        ):
            mock_build.return_value = (shared_ctx, mock_driver)

            rc = main([
                "remember", "entity",
                "--id", "entity:test",
                "--type", "Project",
                "--name", "Test",
                "--source", "source:test",
                "--at", "2026-05-23T10:10:00Z",
            ])

        assert rc == 0
        output = json.loads(capsys.readouterr().out)
        assert output["space"] == "test-project"

    def test_space_flag_overrides_inferred_space_in_cli(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """--space explicitly overrides the inferred space name."""
        from memorable.cli import main

        _setup_workspace(tmp_path)
        shared_ctx = ApplicationContext()
        mock_driver = _make_mock_driver()

        monkeypatch.chdir(tmp_path)
        with (
            patch(
                "memorable.cli.build_production_context",
            ) as mock_build,
            patch(
                "memorable.cli.load_runtime_config",
                return_value=RuntimeConfig(),
            ),
        ):
            mock_build.return_value = (shared_ctx, mock_driver)

            rc = main([
                "remember", "entity",
                "--space", "override-space",
                "--id", "entity:test",
                "--type", "Project",
                "--name", "Test",
                "--source", "source:test",
                "--at", "2026-05-23T10:10:00Z",
            ])

        assert rc == 0
        output = json.loads(capsys.readouterr().out)
        assert output["space"] == "override-space"

    def test_connection_error_prints_helpful_message(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """When Neo4j is unreachable, prints error and exits 1."""
        from memorable.cli import main

        _setup_workspace(tmp_path)

        monkeypatch.chdir(tmp_path)
        with (
            patch(
                "memorable.cli.build_production_context",
                side_effect=ConnectionError(
                    "Cannot connect to Neo4j"
                    " at bolt://localhost:7687"
                ),
            ),
            patch(
                "memorable.cli.load_runtime_config",
                return_value=RuntimeConfig(),
            ),
        ):
            rc = main([
                "remember", "entity",
                "--id", "entity:test",
                "--type", "Project",
                "--name", "Test",
                "--source", "source:test",
                "--at", "2026-05-23T10:10:00Z",
            ])

        assert rc == 1
        err = capsys.readouterr().err
        assert "Cannot connect to Neo4j" in err


class TestCLICommandsNotNeedingContext:
    """Commands that don't need a context should still work without one."""

    def test_status_command_works_without_production_context(self, capsys) -> None:
        """'memorable status' doesn't need a production context."""
        from memorable.cli import main

        rc = main(["status"])
        assert rc == 0

    def test_tracer_command_uses_in_memory_context(self, capsys) -> None:
        """'memorable tracer run' uses in-memory context, not production."""
        from memorable.cli import main

        rc = main(["tracer", "run"])
        assert rc == 0
