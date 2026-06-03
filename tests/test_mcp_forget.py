"""Tests for the MCP Forget surface (memorable_forget_record / _entity).

ADR 0019 ratifies an ungated MCP Forget surface as two separate tools:
record-forget and the high-blast-radius Entity cascade. These tests drive the
real remember services against the same module-level MCP context, then call the
tool functions directly (the established MCP test wiring pattern).
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime

from memorable.core.application import (
    AboutLinker,
    RememberDecisionService,
    RememberEntityService,
    RememberObservationService,
    RememberRelationService,
)
from memorable.core.context import ApplicationContext
from memorable.core.profile import load_profile_from_yaml
from memorable.mcp.server import (
    forget_entity_tool,
    forget_record_tool,
    set_mcp_context,
)

AT = datetime(2026, 6, 3, 9, 0, tzinfo=UTC)

PROFILE_YAML = textwrap.dedent("""\
    version: 1
    space:
      name: memorable
    entities:
      - name: Project
    relations:
      - name: depends-on
    records: []
""")


def _context_with_profile() -> tuple[ApplicationContext, object, AboutLinker]:
    profile = load_profile_from_yaml(PROFILE_YAML)
    ctx = ApplicationContext()
    set_mcp_context(ctx)
    about_linker = AboutLinker(entity_repo=ctx.entity_repo, about_repo=ctx.about_repo)
    return ctx, profile, about_linker


def _remember_entity(ctx, profile, *, space: str, entity_id: str) -> None:
    RememberEntityService(repository=ctx.entity_repo, profile=profile).remember(
        space=space,
        entity_id=entity_id,
        entity_type="Project",
        name=entity_id,
        source_id="source:test",
        at=AT,
    )


def _remember_decision(
    ctx,
    profile,
    about_linker,
    *,
    space: str,
    record_id: str,
    about: list[str] | None = None,
    supersedes: str | None = None,
) -> None:
    RememberDecisionService(
        repository=ctx.decision_repo,
        profile=profile,
        about_linker=about_linker,
    ).remember(
        space=space,
        decision_id=record_id,
        statement="Scratch decision.",
        source_id="source:test",
        at=AT,
        about=about,
        supersedes=supersedes,
    )


def _remember_observation(
    ctx,
    profile,
    about_linker,
    *,
    space: str,
    record_id: str,
    about: list[str] | None = None,
) -> None:
    RememberObservationService(
        repository=ctx.observation_repo,
        profile=profile,
        about_linker=about_linker,
    ).remember(
        space=space,
        observation_id=record_id,
        statement="Scratch observation.",
        source_id="source:test",
        at=AT,
        about=about,
    )


def _remember_relation(
    ctx,
    profile,
    *,
    space: str,
    relation_id: str,
    source_entity_id: str,
    target_entity_id: str,
) -> None:
    RememberRelationService(
        relation_repo=ctx.relation_repo,
        entity_repo=ctx.entity_repo,
        profile=profile,
    ).remember(
        space=space,
        relation_id=relation_id,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        relation_type="depends-on",
        statement=f"{source_entity_id} depends on {target_entity_id}.",
        source_id="source:test",
        at=AT,
    )


def test_forget_record_tool_erases_record() -> None:
    ctx, profile, about_linker = _context_with_profile()
    _remember_decision(
        ctx, profile, about_linker, space="memorable", record_id="decision:scratch"
    )

    result = forget_record_tool(
        space="memorable",
        record_id="decision:scratch",
        record_type="decision",
    )

    assert result == {
        "forgotten": True,
        "record_id": "decision:scratch",
        "record_kind": "decision",
        "space": "memorable",
    }
    assert ctx.decision_repo.get("memorable", "decision:scratch") is None


def test_forget_record_tool_missing_id_returns_error() -> None:
    _context_with_profile()

    result = forget_record_tool(
        space="memorable",
        record_id="decision:missing",
        record_type="decision",
    )

    assert "forgotten" not in result
    assert "Nothing to forget" in str(result["error"])


def test_forget_record_tool_refuses_supersession_chain() -> None:
    ctx, profile, about_linker = _context_with_profile()
    _remember_decision(
        ctx, profile, about_linker, space="memorable", record_id="decision:v1"
    )
    _remember_decision(
        ctx,
        profile,
        about_linker,
        space="memorable",
        record_id="decision:v2",
        supersedes="decision:v1",
    )

    result = forget_record_tool(
        space="memorable",
        record_id="decision:v1",
        record_type="decision",
    )

    assert "forgotten" not in result
    assert "supersession chain" in str(result["error"])
    assert ctx.decision_repo.get("memorable", "decision:v1") is not None
    assert ctx.decision_repo.get("memorable", "decision:v2") is not None


def test_forget_entity_tool_cascades_but_spares_far_end_record() -> None:
    ctx, profile, about_linker = _context_with_profile()
    for entity_id in ("entity:scratch", "entity:related"):
        _remember_entity(ctx, profile, space="memorable", entity_id=entity_id)
    _remember_relation(
        ctx,
        profile,
        space="memorable",
        relation_id="relation:scratch",
        source_entity_id="entity:scratch",
        target_entity_id="entity:related",
    )
    _remember_observation(
        ctx,
        profile,
        about_linker,
        space="memorable",
        record_id="observation:about-scratch",
        about=["entity:scratch"],
    )

    result = forget_entity_tool(space="memorable", entity_id="entity:scratch")

    assert result == {
        "forgotten": True,
        "record_id": "entity:scratch",
        "record_kind": "entity",
        "space": "memorable",
    }
    assert ctx.entity_repo.get("memorable", "entity:scratch") is None
    assert ctx.relation_repo.get("memorable", "relation:scratch") is None
    surviving = ctx.observation_repo.get("memorable", "observation:about-scratch")
    assert surviving is not None
    assert ctx.about_repo.records_for_entity("memorable", "entity:scratch") == []


def test_forget_entity_tool_missing_id_returns_error() -> None:
    _context_with_profile()

    result = forget_entity_tool(space="memorable", entity_id="entity:missing")

    assert "forgotten" not in result
    assert "Nothing to forget" in str(result["error"])
