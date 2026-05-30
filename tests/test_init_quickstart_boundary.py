"""Regression tests for Minimal profile quickstart boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from memorable.config import RuntimeConfig
from memorable.core.context import ApplicationContext


def test_cli_init_minimal_profile_allows_kernel_record_writes(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """After CLI init, kernel records are writable without profile declarations."""
    from memorable.cli import main

    project_dir = tmp_path / "field-notes"
    project_dir.mkdir()
    ctx = ApplicationContext()
    mock_driver = MagicMock()

    with (
        patch(
            "memorable.cli.build_production_context",
            return_value=(ctx, mock_driver),
        ),
        patch("memorable.cli.ensure_all_constraints"),
        patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
    ):
        assert main(["init", "--path", str(project_dir)]) == 0

        monkeypatch.chdir(project_dir)
        writes = [
            [
                "remember",
                "decision",
                "--id",
                "decision:quickstart",
                "--statement",
                "Use Minimal profile quickstart.",
                "--source",
                "source:test",
                "--at",
                "2026-05-30T10:00:00Z",
            ],
            [
                "remember",
                "observation",
                "--id",
                "observation:quickstart",
                "--statement",
                "Minimal profile has empty record declarations.",
                "--source",
                "source:test",
                "--at",
                "2026-05-30T10:01:00Z",
            ],
            [
                "remember",
                "task",
                "--id",
                "task:quickstart",
                "--title",
                "Verify quickstart",
                "--source",
                "source:test",
                "--at",
                "2026-05-30T10:02:00Z",
            ],
        ]

        for command in writes:
            assert main(command) == 0

    output_lines = capsys.readouterr().out.strip().splitlines()
    assert [json.loads(line)["record_kind"] for line in output_lines[1:]] == [
        "decision",
        "observation",
        "task",
    ]


def test_cli_undeclared_entity_type_prompts_profile_evolution(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Undeclared Entity type failure names the type and prompts evolution."""
    from memorable.cli import main

    project_dir = tmp_path / "field-notes"
    project_dir.mkdir()
    ctx = ApplicationContext()
    mock_driver = MagicMock()

    with (
        patch(
            "memorable.cli.build_production_context",
            return_value=(ctx, mock_driver),
        ),
        patch("memorable.cli.ensure_all_constraints"),
        patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
    ):
        assert main(["init", "--path", str(project_dir)]) == 0
        capsys.readouterr()

        monkeypatch.chdir(project_dir)
        exit_code = main(
            [
                "remember",
                "entity",
                "--id",
                "entity:trail",
                "--type",
                "Trail",
                "--name",
                "River Loop",
                "--source",
                "source:test",
                "--at",
                "2026-05-30T10:03:00Z",
            ]
        )

    assert exit_code == 1
    error = capsys.readouterr().err
    assert "Trail" in error
    assert "MemoryProfile" in error
    assert "evolve" in error.lower()


def test_cli_undeclared_relation_type_prompts_profile_evolution(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Undeclared Relation type failure names the type and prompts evolution."""
    from memorable.cli import main

    project_dir = tmp_path / "field-notes"
    project_dir.mkdir()
    ctx = ApplicationContext()
    mock_driver = MagicMock()

    with (
        patch(
            "memorable.cli.build_production_context",
            return_value=(ctx, mock_driver),
        ),
        patch("memorable.cli.ensure_all_constraints"),
        patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
    ):
        assert main(["init", "--path", str(project_dir)]) == 0
        capsys.readouterr()

        monkeypatch.chdir(project_dir)
        exit_code = main(
            [
                "remember",
                "relation",
                "--id",
                "relation:trail-gear",
                "--source-entity-id",
                "entity:trail",
                "--target-entity-id",
                "entity:shoes",
                "--relation-type",
                "uses-gear",
                "--statement",
                "River Loop uses trail shoes.",
                "--source",
                "source:test",
                "--at",
                "2026-05-30T10:04:00Z",
            ]
        )

    assert exit_code == 1
    error = capsys.readouterr().err
    assert "uses-gear" in error
    assert "MemoryProfile" in error
    assert "evolve" in error.lower()


def test_mcp_init_space_does_not_scaffold_missing_profile(tmp_path: Path) -> None:
    """MCP init remains non-scaffolding when no MemoryProfile exists."""
    from memorable.mcp.server import init_space_tool

    profile_path = tmp_path / ".memorable" / "memory.yaml"

    result = init_space_tool(str(tmp_path))

    assert "error" in result
    assert "memory.yaml" in str(result["error"])
    assert "memorable init" in str(result["error"])
    assert not profile_path.exists()
