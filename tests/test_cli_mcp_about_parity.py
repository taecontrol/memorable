"""CLI and MCP About parity regression tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from memorable.config import EmbeddingSettings, RuntimeConfig
from memorable.core.context import ApplicationContext, default_context

SPACE = "memorable"
SOURCE_ID = "source:test"
CORRECTION_SOURCE_ID = "source:human-review"
ABOUT_TARGETS = ["entity:frontend", "entity:backend"]
EXPECTED_ABOUT_TARGETS = ["entity:backend", "entity:frontend"]


class TrackingApplicationContext(ApplicationContext):
    """ApplicationContext that exposes factory use as observable behavior."""

    def __init__(self) -> None:
        super().__init__()
        self.about_linker_calls = 0

    def about_linker(self):
        self.about_linker_calls += 1
        return super().about_linker()

    def reset_about_linker_calls(self) -> None:
        self.about_linker_calls = 0


@pytest.fixture()
def about_parity_context(
    monkeypatch, clean_memorable_environment
) -> Iterator[TrackingApplicationContext]:
    """Run CLI and MCP against one in-memory context with fake Embeddings."""
    from memorable.mcp.server import set_mcp_context

    ctx = TrackingApplicationContext()
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", model="hash", dimensions=32)
    )
    driver = MagicMock()

    monkeypatch.setattr("memorable.cli.load_runtime_config", lambda **_kwargs: config)
    monkeypatch.setattr(
        "memorable.cli.build_production_context",
        lambda _config: (ctx, driver),
    )
    monkeypatch.setattr(
        "memorable.mcp.server.load_runtime_config", lambda **_kwargs: config
    )
    set_mcp_context(ctx)
    yield ctx
    default_context.reset()
    set_mcp_context(default_context)


def _call_mcp_tool(name: str, arguments: dict[str, object]) -> dict[str, object]:
    from memorable.mcp.server import mcp_server

    _content, structured = asyncio.run(mcp_server.call_tool(name, arguments))
    assert isinstance(structured, dict)
    return structured


def _remember_entity_via_cli(main: Any, capsys: Any, entity_id: str) -> None:
    rc = main(
        [
            "remember",
            "entity",
            "--space",
            SPACE,
            "--id",
            entity_id,
            "--type",
            "Component",
            "--name",
            entity_id.removeprefix("entity:").title(),
            "--source",
            SOURCE_ID,
            "--at",
            "2026-06-07T09:00:00Z",
        ]
    )
    assert rc == 0
    capsys.readouterr()


def _setup_about_entities_via_cli(main: Any, capsys: Any) -> None:
    for entity_id in ("entity:legacy", *ABOUT_TARGETS):
        _remember_entity_via_cli(main, capsys, entity_id)


def _remember_decision_via_cli(main: Any, capsys: Any, record_id: str) -> None:
    rc = main(
        [
            "remember",
            "decision",
            "--space",
            SPACE,
            "--id",
            record_id,
            "--statement",
            "Use the Build 2 API contract.",
            "--source",
            SOURCE_ID,
            "--at",
            "2026-06-07T09:01:00Z",
            "--about",
            ABOUT_TARGETS[0],
            "--about",
            ABOUT_TARGETS[1],
        ]
    )
    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["decision_id"] == record_id


def _remember_decision_via_mcp(record_id: str) -> None:
    result = _call_mcp_tool(
        "memorable_remember_decision",
        {
            "space": SPACE,
            "decision_id": record_id,
            "statement": "Use the Build 2 API contract.",
            "source": SOURCE_ID,
            "at": "2026-06-07T09:01:00Z",
            "about": ABOUT_TARGETS,
        },
    )
    assert "error" not in result
    assert result["decision_id"] == record_id


def _remember_observation_via_cli(main: Any, capsys: Any, record_id: str) -> None:
    rc = main(
        [
            "remember",
            "observation",
            "--space",
            SPACE,
            "--id",
            record_id,
            "--statement",
            "The Build 2 API contract warmed up quickly.",
            "--source",
            SOURCE_ID,
            "--at",
            "2026-06-07T09:01:00Z",
            "--about",
            ABOUT_TARGETS[0],
            "--about",
            ABOUT_TARGETS[1],
        ]
    )
    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["observation_id"] == record_id


def _remember_observation_via_mcp(record_id: str) -> None:
    result = _call_mcp_tool(
        "memorable_remember_observation",
        {
            "space": SPACE,
            "observation_id": record_id,
            "statement": "The Build 2 API contract warmed up quickly.",
            "source": SOURCE_ID,
            "at": "2026-06-07T09:01:00Z",
            "about": ABOUT_TARGETS,
        },
    )
    assert "error" not in result
    assert result["observation_id"] == record_id


def _remember_task_via_cli(main: Any, capsys: Any, record_id: str) -> None:
    rc = main(
        [
            "remember",
            "task",
            "--space",
            SPACE,
            "--id",
            record_id,
            "--title",
            "Review the Build 2 API contract.",
            "--source",
            SOURCE_ID,
            "--at",
            "2026-06-07T09:01:00Z",
            "--about",
            ABOUT_TARGETS[0],
            "--about",
            ABOUT_TARGETS[1],
        ]
    )
    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["task_id"] == record_id


def _remember_task_via_mcp(record_id: str) -> None:
    result = _call_mcp_tool(
        "memorable_remember_task",
        {
            "space": SPACE,
            "task_id": record_id,
            "title": "Review the Build 2 API contract.",
            "source": SOURCE_ID,
            "at": "2026-06-07T09:01:00Z",
            "about": ABOUT_TARGETS,
        },
    )
    assert "error" not in result
    assert result["task_id"] == record_id


def test_remember_decision_about_edges_match_cli_and_mcp(
    about_parity_context: TrackingApplicationContext, capsys
) -> None:
    """MCP and CLI Decision writes produce identical About memberships."""
    from memorable.cli import main

    ctx = about_parity_context
    _setup_about_entities_via_cli(main, capsys)
    ctx.reset_about_linker_calls()

    _remember_decision_via_cli(main, capsys, "decision:cli-parity")
    _remember_decision_via_mcp("decision:mcp-parity")

    assert ctx.about_repo.entities_for_record(SPACE, "decision:cli-parity") == (
        EXPECTED_ABOUT_TARGETS
    )
    assert ctx.about_repo.entities_for_record(SPACE, "decision:mcp-parity") == (
        ctx.about_repo.entities_for_record(SPACE, "decision:cli-parity")
    )
    assert ctx.about_linker_calls == 2


def test_remember_observation_about_edges_match_cli_and_mcp(
    about_parity_context: TrackingApplicationContext, capsys
) -> None:
    """MCP and CLI Observation writes produce identical About memberships."""
    from memorable.cli import main

    ctx = about_parity_context
    _setup_about_entities_via_cli(main, capsys)
    ctx.reset_about_linker_calls()

    _remember_observation_via_cli(main, capsys, "observation:cli-parity")
    _remember_observation_via_mcp("observation:mcp-parity")

    assert ctx.about_repo.entities_for_record(SPACE, "observation:cli-parity") == (
        EXPECTED_ABOUT_TARGETS
    )
    assert ctx.about_repo.entities_for_record(SPACE, "observation:mcp-parity") == (
        ctx.about_repo.entities_for_record(SPACE, "observation:cli-parity")
    )
    assert ctx.about_linker_calls == 2


def test_remember_task_about_edges_match_cli_and_mcp(
    about_parity_context: TrackingApplicationContext, capsys
) -> None:
    """MCP and CLI Task writes produce identical About memberships."""
    from memorable.cli import main

    ctx = about_parity_context
    _setup_about_entities_via_cli(main, capsys)
    ctx.reset_about_linker_calls()

    _remember_task_via_cli(main, capsys, "task:cli-parity")
    _remember_task_via_mcp("task:mcp-parity")

    assert ctx.about_repo.entities_for_record(SPACE, "task:cli-parity") == (
        EXPECTED_ABOUT_TARGETS
    )
    assert ctx.about_repo.entities_for_record(SPACE, "task:mcp-parity") == (
        ctx.about_repo.entities_for_record(SPACE, "task:cli-parity")
    )
    assert ctx.about_linker_calls == 2


def _current_statement(
    ctx: ApplicationContext, *, record_kind: str, record_id: str
) -> str:
    from memorable.core.application import CurrentTruthService

    repository = {
        "decision": ctx.decision_repo,
        "observation": ctx.observation_repo,
    }[record_kind]
    record = CurrentTruthService(repository=repository).current(
        space=SPACE,
        record_id=record_id,
    )
    assert record is not None
    return record.statement


def _remember_record_with_legacy_about_via_cli(
    main: Any,
    capsys: Any,
    *,
    record_kind: str,
    record_id: str,
    statement: str,
) -> None:
    rc = main(
        [
            "remember",
            record_kind,
            "--space",
            SPACE,
            "--id",
            record_id,
            "--statement",
            statement,
            "--source",
            SOURCE_ID,
            "--at",
            "2026-06-07T09:01:00Z",
            "--about",
            "entity:legacy",
        ]
    )
    assert rc == 0
    capsys.readouterr()


def _remember_record_with_legacy_about_via_mcp(
    *, record_kind: str, record_id: str, statement: str
) -> None:
    tool_name = {
        "decision": "memorable_remember_decision",
        "observation": "memorable_remember_observation",
    }[record_kind]
    id_key = {
        "decision": "decision_id",
        "observation": "observation_id",
    }[record_kind]
    result = _call_mcp_tool(
        tool_name,
        {
            "space": SPACE,
            id_key: record_id,
            "statement": statement,
            "source": SOURCE_ID,
            "at": "2026-06-07T09:01:00Z",
            "about": ["entity:legacy"],
        },
    )
    assert "error" not in result


def _correct_record_via_cli(
    main: Any,
    capsys: Any,
    *,
    record_kind: str,
    record_id: str,
    new_statement: str,
) -> None:
    rc = main(
        [
            "correct",
            "--space",
            SPACE,
            "--id",
            record_id,
            "--record-kind",
            record_kind,
            "--new-statement",
            new_statement,
            "--source",
            CORRECTION_SOURCE_ID,
            "--at",
            "2026-06-07T09:02:00Z",
            "--about",
            ABOUT_TARGETS[0],
            "--about",
            ABOUT_TARGETS[1],
        ]
    )
    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["record_id"] == record_id
    assert output["new_statement"] == new_statement


def _correct_record_via_mcp(
    *, record_kind: str, record_id: str, new_statement: str
) -> None:
    result = _call_mcp_tool(
        "memorable_correct",
        {
            "space": SPACE,
            "record_id": record_id,
            "record_kind": record_kind,
            "new_statement": new_statement,
            "source": CORRECTION_SOURCE_ID,
            "at": "2026-06-07T09:02:00Z",
            "about": ABOUT_TARGETS,
        },
    )
    assert "error" not in result
    assert result["record_id"] == record_id
    assert result["new_statement"] == new_statement


@pytest.mark.parametrize(
    ("record_kind", "old_statement", "new_statement"),
    [
        (
            "decision",
            "Use the legacy API contract.",
            "Use the Build 2 API contract.",
        ),
        (
            "observation",
            "The legacy API contract warmed up slowly.",
            "The Build 2 API contract warmed up quickly.",
        ),
    ],
)
def test_correct_about_restaple_matches_cli_and_mcp(
    about_parity_context: TrackingApplicationContext,
    capsys,
    record_kind: str,
    old_statement: str,
    new_statement: str,
) -> None:
    """MCP and CLI corrections produce identical re-stapled memberships."""
    from memorable.cli import main

    ctx = about_parity_context
    cli_record_id = f"{record_kind}:cli-correct-parity"
    mcp_record_id = f"{record_kind}:mcp-correct-parity"
    _setup_about_entities_via_cli(main, capsys)
    _remember_record_with_legacy_about_via_cli(
        main,
        capsys,
        record_kind=record_kind,
        record_id=cli_record_id,
        statement=old_statement,
    )
    _remember_record_with_legacy_about_via_mcp(
        record_kind=record_kind,
        record_id=mcp_record_id,
        statement=old_statement,
    )
    ctx.reset_about_linker_calls()

    _correct_record_via_cli(
        main,
        capsys,
        record_kind=record_kind,
        record_id=cli_record_id,
        new_statement=new_statement,
    )
    _correct_record_via_mcp(
        record_kind=record_kind,
        record_id=mcp_record_id,
        new_statement=new_statement,
    )

    cli_current_statement = _current_statement(
        ctx, record_kind=record_kind, record_id=cli_record_id
    )
    mcp_current_statement = _current_statement(
        ctx, record_kind=record_kind, record_id=mcp_record_id
    )
    assert cli_current_statement == new_statement
    assert mcp_current_statement == cli_current_statement
    assert ctx.about_repo.entities_for_record(SPACE, cli_record_id) == (
        EXPECTED_ABOUT_TARGETS
    )
    assert ctx.about_repo.entities_for_record(SPACE, mcp_record_id) == (
        ctx.about_repo.entities_for_record(SPACE, cli_record_id)
    )
    assert ctx.about_repo.records_for_entity(SPACE, "entity:legacy") == []
    assert ctx.about_linker_calls == 2
