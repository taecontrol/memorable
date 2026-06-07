"""CLI remember --about behavior tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from memorable.config import RuntimeConfig
from memorable.core.context import ApplicationContext
from memorable.core.profile import load_profile_from_yaml

PROFILE_YAML = """\
version: 1
space:
  name: test-space
  description: Test space for CLI About wiring
entities:
  - name: Component
records: []
"""


def _setup_workspace(tmp_path: Path) -> None:
    memorable_dir = tmp_path / ".memorable"
    memorable_dir.mkdir()
    (memorable_dir / "memory.yaml").write_text(PROFILE_YAML, encoding="utf-8")


def _setup_entities(ctx: ApplicationContext) -> None:
    from memorable.core.application import RememberEntityService
    from memorable.core.temporal import parse_iso_timestamp

    profile = load_profile_from_yaml(PROFILE_YAML)
    service = RememberEntityService(repository=ctx.entity_repo, profile=profile)
    at = parse_iso_timestamp("2026-06-07T09:00:00Z")
    for entity_id, name in (
        ("entity:frontend", "Frontend"),
        ("entity:backend", "Backend"),
    ):
        service.remember(
            space="test-space",
            entity_id=entity_id,
            entity_type="Component",
            name=name,
            source_id="source:test",
            at=at,
        )


def test_remember_decision_about_creates_about_edges(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """remember decision --about links the Decision to existing Entities."""
    from memorable.cli import main

    _setup_workspace(tmp_path)
    ctx = ApplicationContext()
    _setup_entities(ctx)
    mock_driver = MagicMock()

    monkeypatch.chdir(tmp_path)
    with (
        patch("memorable.cli.build_production_context") as mock_build,
        patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
    ):
        mock_build.return_value = (ctx, mock_driver)

        rc = main(
            [
                "remember",
                "decision",
                "--id",
                "decision:about-build-2",
                "--statement",
                "Use Build 2.",
                "--source",
                "source:test",
                "--at",
                "2026-06-07T09:01:00Z",
                "--about",
                "entity:frontend",
                "--about",
                "entity:backend",
            ]
        )

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["decision_id"] == "decision:about-build-2"
    assert ctx.decision_repo.get("test-space", "decision:about-build-2") is not None
    assert ctx.about_repo.entities_for_record(
        "test-space", "decision:about-build-2"
    ) == ["entity:backend", "entity:frontend"]
    assert ctx.about_repo.records_for_entity("test-space", "entity:frontend") == [
        "decision:about-build-2"
    ]


def test_remember_observation_about_creates_about_edges(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """remember observation --about links the Observation to existing Entities."""
    from memorable.cli import main

    _setup_workspace(tmp_path)
    ctx = ApplicationContext()
    _setup_entities(ctx)
    mock_driver = MagicMock()

    monkeypatch.chdir(tmp_path)
    with (
        patch("memorable.cli.build_production_context") as mock_build,
        patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
    ):
        mock_build.return_value = (ctx, mock_driver)

        rc = main(
            [
                "remember",
                "observation",
                "--id",
                "observation:about-build-2",
                "--statement",
                "Build 2 warmed up quickly.",
                "--source",
                "source:test",
                "--at",
                "2026-06-07T09:01:00Z",
                "--about",
                "entity:frontend",
                "--about",
                "entity:backend",
            ]
        )

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["observation_id"] == "observation:about-build-2"
    assert (
        ctx.observation_repo.get("test-space", "observation:about-build-2") is not None
    )
    assert ctx.about_repo.entities_for_record(
        "test-space", "observation:about-build-2"
    ) == ["entity:backend", "entity:frontend"]
    assert ctx.about_repo.records_for_entity("test-space", "entity:frontend") == [
        "observation:about-build-2"
    ]


def test_remember_task_about_creates_about_edges(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """remember task --about links the Task to existing Entities."""
    from memorable.cli import main

    _setup_workspace(tmp_path)
    ctx = ApplicationContext()
    _setup_entities(ctx)
    mock_driver = MagicMock()

    monkeypatch.chdir(tmp_path)
    with (
        patch("memorable.cli.build_production_context") as mock_build,
        patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
    ):
        mock_build.return_value = (ctx, mock_driver)

        rc = main(
            [
                "remember",
                "task",
                "--id",
                "task:about-build-2",
                "--title",
                "Inspect Build 2.",
                "--source",
                "source:test",
                "--at",
                "2026-06-07T09:01:00Z",
                "--about",
                "entity:frontend",
                "--about",
                "entity:backend",
            ]
        )

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["task_id"] == "task:about-build-2"
    assert (
        ctx.task_repo.get(space="test-space", task_id="task:about-build-2") is not None
    )
    assert ctx.about_repo.entities_for_record("test-space", "task:about-build-2") == [
        "entity:backend",
        "entity:frontend",
    ]
    assert ctx.about_repo.records_for_entity("test-space", "entity:frontend") == [
        "task:about-build-2"
    ]


@pytest.mark.parametrize(
    ("remember_type", "record_id", "content_args", "stored_record"),
    [
        (
            "decision",
            "decision:partial",
            ["--statement", "About a missing Entity."],
            lambda ctx: ctx.decision_repo.get("test-space", "decision:partial"),
        ),
        (
            "observation",
            "observation:partial",
            ["--statement", "About a missing Entity."],
            lambda ctx: ctx.observation_repo.get("test-space", "observation:partial"),
        ),
        (
            "task",
            "task:partial",
            ["--title", "About a missing Entity."],
            lambda ctx: ctx.task_repo.get(space="test-space", task_id="task:partial"),
        ),
    ],
)
def test_remember_about_missing_entity_fails_loud_without_half_write(
    tmp_path: Path,
    monkeypatch,
    capsys,
    remember_type: str,
    record_id: str,
    content_args: list[str],
    stored_record: Callable[[ApplicationContext], object | None],
) -> None:
    """remember --about fails loud and writes nothing when any target is missing."""
    from memorable.cli import main

    _setup_workspace(tmp_path)
    ctx = ApplicationContext()
    _setup_entities(ctx)
    mock_driver = MagicMock()

    monkeypatch.chdir(tmp_path)
    with (
        patch("memorable.cli.build_production_context") as mock_build,
        patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
    ):
        mock_build.return_value = (ctx, mock_driver)

        rc = main(
            [
                "remember",
                remember_type,
                "--id",
                record_id,
                *content_args,
                "--source",
                "source:test",
                "--at",
                "2026-06-07T09:01:00Z",
                "--about",
                "entity:frontend",
                "--about",
                "entity:missing",
            ]
        )

    assert rc == 1
    err = capsys.readouterr().err
    assert "About target Entity 'entity:missing' not found" in err
    assert "Create the Entity before" in err
    assert stored_record(ctx) is None
    assert ctx.about_repo.entities_for_record("test-space", record_id) == []
    assert ctx.about_repo.records_for_entity("test-space", "entity:frontend") == []


@pytest.mark.parametrize(
    ("remember_type", "record_id", "content_args", "stored_record"),
    [
        (
            "decision",
            "decision:no-about",
            ["--statement", "No About edge applies."],
            lambda ctx: ctx.decision_repo.get("test-space", "decision:no-about"),
        ),
        (
            "observation",
            "observation:no-about",
            ["--statement", "No About edge applies."],
            lambda ctx: ctx.observation_repo.get("test-space", "observation:no-about"),
        ),
        (
            "task",
            "task:no-about",
            ["--title", "No About edge applies."],
            lambda ctx: ctx.task_repo.get(space="test-space", task_id="task:no-about"),
        ),
    ],
)
def test_remember_without_about_still_writes_record_with_no_about_edges(
    tmp_path: Path,
    monkeypatch,
    remember_type: str,
    record_id: str,
    content_args: list[str],
    stored_record: Callable[[ApplicationContext], object | None],
) -> None:
    """Omitting --about preserves existing record-write behavior."""
    from memorable.cli import main

    _setup_workspace(tmp_path)
    ctx = ApplicationContext()
    mock_driver = MagicMock()

    monkeypatch.chdir(tmp_path)
    with (
        patch("memorable.cli.build_production_context") as mock_build,
        patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
    ):
        mock_build.return_value = (ctx, mock_driver)

        rc = main(
            [
                "remember",
                remember_type,
                "--id",
                record_id,
                *content_args,
                "--source",
                "source:test",
                "--at",
                "2026-06-07T09:01:00Z",
            ]
        )

    assert rc == 0
    assert stored_record(ctx) is not None
    assert ctx.about_repo.entities_for_record("test-space", record_id) == []


@pytest.mark.parametrize("remember_type", ["decision", "observation", "task"])
def test_remember_about_help_teaches_membership_not_relation_claim(
    capsys, remember_type: str
) -> None:
    """remember --about help uses the authoritative About framing."""
    from memorable.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main(["remember", remember_type, "--help"])

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    normalized_help = " ".join(help_text.split())
    assert "--about" in help_text
    assert "About is membership, not a Relation claim" in normalized_help
    assert "create the Entity first" in normalized_help
