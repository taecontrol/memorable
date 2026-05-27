"""Tests for CLI `memorable remember relation` subcommand.

Verifies:
- Subcommand exists and parses all required arguments
- Output is JSON with expected relation, provenance, and lifecycle fields
- Optional arguments (--writer, --reason, --supersedes) are accepted
- Error cases produce exit code 1 with helpful messages
- Production context dispatch is wired correctly
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from memorable.config import RuntimeConfig
from memorable.core.context import ApplicationContext
from memorable.core.profile import load_profile_from_yaml

PROFILE_YAML = """\
version: 1
space:
  name: test-space
  description: Test space for relation CLI
entities:
  - name: Component
records:
  - name: GeneralObservation
    extends: Observation
relations:
  - name: depends-on
  - name: owns
"""


def _setup_workspace(tmp_path: Path) -> Path:
    """Create a .memorable/memory.yaml in tmp_path."""
    memorable_dir = tmp_path / ".memorable"
    memorable_dir.mkdir()
    (memorable_dir / "memory.yaml").write_text(PROFILE_YAML, encoding="utf-8")
    return tmp_path


def _setup_entities(ctx: ApplicationContext) -> None:
    """Pre-populate two entities in the context for relation source/target."""
    from memorable.core.application import RememberEntityService
    from memorable.core.temporal import parse_iso_timestamp

    profile = load_profile_from_yaml(PROFILE_YAML)
    ctx._profiles["test-space"] = profile

    service = RememberEntityService(repository=ctx.entity_repo, profile=profile)
    at = parse_iso_timestamp("2026-05-26T10:00:00Z")

    service.remember(
        space="test-space",
        entity_id="entity:frontend",
        entity_type="Component",
        name="Frontend",
        source_id="test-source",
        at=at,
    )
    service.remember(
        space="test-space",
        entity_id="entity:backend",
        entity_type="Component",
        name="Backend",
        source_id="test-source",
        at=at,
    )


class TestRememberRelationCLI:
    """CLI `memorable remember relation` subcommand."""

    def test_remember_relation_outputs_expected_json_keys(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """remember relation outputs JSON with all relation and provenance fields."""
        from memorable.cli import main

        _setup_workspace(tmp_path)
        ctx = ApplicationContext()
        _setup_entities(ctx)
        mock_driver = MagicMock()

        monkeypatch.chdir(tmp_path)
        with (
            patch("memorable.cli.build_production_context") as mock_build,
            patch(
                "memorable.cli.load_runtime_config",
                return_value=RuntimeConfig(),
            ),
        ):
            mock_build.return_value = (ctx, mock_driver)

            rc = main(
                [
                    "remember",
                    "relation",
                    "--id",
                    "rel:1",
                    "--source-entity-id",
                    "entity:frontend",
                    "--target-entity-id",
                    "entity:backend",
                    "--relation-type",
                    "depends-on",
                    "--statement",
                    "Frontend depends on Backend",
                    "--source",
                    "test-source",
                    "--at",
                    "2026-05-26T12:00:00Z",
                ]
            )

        assert rc == 0
        output = json.loads(capsys.readouterr().out)
        expected_keys = {
            "relation_id",
            "statement",
            "space",
            "record_kind",
            "lifecycle_state",
            "source_entity_id",
            "target_entity_id",
            "relation_type",
            "source",
            "episode",
            "creation_time",
            "validity_time",
        }
        assert set(output.keys()) == expected_keys

    def test_remember_relation_outputs_correct_values(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """remember relation outputs correct field values."""
        from memorable.cli import main

        _setup_workspace(tmp_path)
        ctx = ApplicationContext()
        _setup_entities(ctx)
        mock_driver = MagicMock()

        monkeypatch.chdir(tmp_path)
        with (
            patch("memorable.cli.build_production_context") as mock_build,
            patch(
                "memorable.cli.load_runtime_config",
                return_value=RuntimeConfig(),
            ),
        ):
            mock_build.return_value = (ctx, mock_driver)

            rc = main(
                [
                    "remember",
                    "relation",
                    "--id",
                    "rel:2",
                    "--source-entity-id",
                    "entity:frontend",
                    "--target-entity-id",
                    "entity:backend",
                    "--relation-type",
                    "depends-on",
                    "--statement",
                    "Frontend depends on Backend API",
                    "--source",
                    "test-source",
                    "--at",
                    "2026-05-26T12:00:00Z",
                ]
            )

        assert rc == 0
        output = json.loads(capsys.readouterr().out)
        assert output["relation_id"] == "rel:2"
        assert output["statement"] == "Frontend depends on Backend API"
        assert output["space"] == "test-space"
        assert output["record_kind"] == "relation"
        assert output["lifecycle_state"] == "current"
        assert output["source_entity_id"] == "entity:frontend"
        assert output["target_entity_id"] == "entity:backend"
        assert output["relation_type"] == "depends-on"
        assert output["source"] == "test-source"

    def test_remember_relation_accepts_optional_args(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """remember relation accepts --writer, --reason, --supersedes."""
        from memorable.cli import main

        _setup_workspace(tmp_path)
        ctx = ApplicationContext()
        _setup_entities(ctx)
        mock_driver = MagicMock()

        monkeypatch.chdir(tmp_path)
        with (
            patch("memorable.cli.build_production_context") as mock_build,
            patch(
                "memorable.cli.load_runtime_config",
                return_value=RuntimeConfig(),
            ),
        ):
            mock_build.return_value = (ctx, mock_driver)

            # First remember a relation to supersede
            main(
                [
                    "remember",
                    "relation",
                    "--id",
                    "rel:original",
                    "--source-entity-id",
                    "entity:frontend",
                    "--target-entity-id",
                    "entity:backend",
                    "--relation-type",
                    "depends-on",
                    "--statement",
                    "Frontend depends on Backend v1",
                    "--source",
                    "test-source",
                    "--at",
                    "2026-05-26T12:00:00Z",
                ]
            )

            # Now supersede with optional args
            rc = main(
                [
                    "remember",
                    "relation",
                    "--id",
                    "rel:successor",
                    "--source-entity-id",
                    "entity:frontend",
                    "--target-entity-id",
                    "entity:backend",
                    "--relation-type",
                    "depends-on",
                    "--statement",
                    "Frontend depends on Backend v2",
                    "--source",
                    "test-source",
                    "--at",
                    "2026-05-26T13:00:00Z",
                    "--writer",
                    "agent:test",
                    "--reason",
                    "Updated dependency",
                    "--supersedes",
                    "rel:original",
                ]
            )

        assert rc == 0
        output = json.loads(capsys.readouterr().out.strip().split("\n")[-1])
        assert output["relation_id"] == "rel:successor"
        assert output["lifecycle_state"] == "current"

    def test_remember_relation_error_for_undeclared_type(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """remember relation with undeclared type returns exit 1."""
        from memorable.cli import main

        _setup_workspace(tmp_path)
        ctx = ApplicationContext()
        _setup_entities(ctx)
        mock_driver = MagicMock()

        monkeypatch.chdir(tmp_path)
        with (
            patch("memorable.cli.build_production_context") as mock_build,
            patch(
                "memorable.cli.load_runtime_config",
                return_value=RuntimeConfig(),
            ),
        ):
            mock_build.return_value = (ctx, mock_driver)

            rc = main(
                [
                    "remember",
                    "relation",
                    "--id",
                    "rel:bad",
                    "--source-entity-id",
                    "entity:frontend",
                    "--target-entity-id",
                    "entity:backend",
                    "--relation-type",
                    "not-declared",
                    "--statement",
                    "Bad relation type",
                    "--source",
                    "test-source",
                    "--at",
                    "2026-05-26T12:00:00Z",
                ]
            )

        assert rc == 1
        err = capsys.readouterr().err
        assert "not-declared" in err
        assert "not declared" in err.lower()


class TestRememberRelationProductionWiring:
    """CLI remember relation uses the production context, not default_context."""

    def test_remember_relation_persists_to_production_context(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """remember relation stores the relation in the production context."""
        from memorable.cli import main
        from memorable.core.context import default_context

        _setup_workspace(tmp_path)
        ctx = ApplicationContext()
        _setup_entities(ctx)
        mock_driver = MagicMock()

        monkeypatch.chdir(tmp_path)
        with (
            patch("memorable.cli.build_production_context") as mock_build,
            patch(
                "memorable.cli.load_runtime_config",
                return_value=RuntimeConfig(),
            ),
        ):
            mock_build.return_value = (ctx, mock_driver)

            rc = main(
                [
                    "remember",
                    "relation",
                    "--id",
                    "rel:wiring-test",
                    "--source-entity-id",
                    "entity:frontend",
                    "--target-entity-id",
                    "entity:backend",
                    "--relation-type",
                    "depends-on",
                    "--statement",
                    "Frontend depends on Backend",
                    "--source",
                    "test-source",
                    "--at",
                    "2026-05-26T12:00:00Z",
                ]
            )

        assert rc == 0

        # Verify stored in production context
        stored = ctx.relation_repo.get("test-space", "rel:wiring-test")
        assert stored is not None
        assert stored.relation_type == "depends-on"

        # Verify NOT stored in default_context
        default_stored = default_context.relation_repo.get(
            "test-space", "rel:wiring-test"
        )
        assert default_stored is None

    def test_driver_is_closed_after_remember_relation(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The Neo4j driver is closed after remember relation completes."""
        from memorable.cli import main

        _setup_workspace(tmp_path)
        ctx = ApplicationContext()
        _setup_entities(ctx)
        mock_driver = MagicMock()

        monkeypatch.chdir(tmp_path)
        with (
            patch("memorable.cli.build_production_context") as mock_build,
            patch(
                "memorable.cli.load_runtime_config",
                return_value=RuntimeConfig(),
            ),
        ):
            mock_build.return_value = (ctx, mock_driver)

            main(
                [
                    "remember",
                    "relation",
                    "--id",
                    "rel:driver-test",
                    "--source-entity-id",
                    "entity:frontend",
                    "--target-entity-id",
                    "entity:backend",
                    "--relation-type",
                    "depends-on",
                    "--statement",
                    "Test statement",
                    "--source",
                    "test-source",
                    "--at",
                    "2026-05-26T12:00:00Z",
                ]
            )

        mock_driver.close.assert_called_once()


class TestProfileShowRelationTypes:
    """Profile inspection includes relation type declarations."""

    def test_mcp_inspect_space_includes_relation_types(self, tmp_path: Path) -> None:
        """MCP inspect_space_tool includes relation declarations in output."""
        from memorable.mcp.server import inspect_space_tool

        memorable_dir = tmp_path / ".memorable"
        memorable_dir.mkdir()
        (memorable_dir / "memory.yaml").write_text(PROFILE_YAML, encoding="utf-8")

        result = inspect_space_tool(str(tmp_path))

        assert "relations" in result
        assert result["relations"] == ["depends-on", "owns"]
        assert result["relation_count"] == 2

    def test_cli_profile_show_includes_relation_types(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """CLI profile show includes relation type declarations in output."""
        from memorable.cli import main

        _setup_workspace(tmp_path)
        monkeypatch.chdir(tmp_path)

        rc = main(["profile", "show"])

        assert rc == 0
        output = json.loads(capsys.readouterr().out)
        assert "relations" in output
        assert output["relations"] == ["depends-on", "owns"]

    def test_cli_profile_show_with_path_flag(self, tmp_path: Path, capsys) -> None:
        """CLI profile show --path reads from specified directory."""
        from memorable.cli import main

        _setup_workspace(tmp_path)

        rc = main(["profile", "show", "--path", str(tmp_path)])

        assert rc == 0
        output = json.loads(capsys.readouterr().out)
        assert output["space_name"] == "test-space"
        assert output["relations"] == ["depends-on", "owns"]

    def test_cli_profile_show_fails_when_no_profile_exists(
        self, tmp_path: Path, capsys
    ) -> None:
        """CLI profile show returns exit 1 with helpful error when no profile."""
        from memorable.cli import main

        rc = main(["profile", "show", "--path", str(tmp_path)])

        assert rc == 1
        err = capsys.readouterr().err
        assert "memory.yaml" in err

    def test_cli_profile_show_empty_relations(self, tmp_path: Path, capsys) -> None:
        """Profile with no relation declarations shows empty list."""
        from memorable.cli import main

        memorable_dir = tmp_path / ".memorable"
        memorable_dir.mkdir()
        (memorable_dir / "memory.yaml").write_text(
            "version: 1\nspace:\n  name: no-relations\nentities:\n  - name: Project\n",
            encoding="utf-8",
        )

        rc = main(["profile", "show", "--path", str(tmp_path)])

        assert rc == 0
        output = json.loads(capsys.readouterr().out)
        assert output["relations"] == []
        assert output["relation_count"] == 0
