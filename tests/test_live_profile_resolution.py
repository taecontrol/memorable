"""Regression tests for live MemoryProfile resolution."""

from __future__ import annotations

import asyncio
from pathlib import Path


def _declarations(section: str, names: list[str]) -> str:
    if not names:
        return f"{section}: []\n"
    lines = "\n".join(f"  - name: {name}" for name in names)
    return f"{section}:\n{lines}\n"


def _write_profile(
    profile_path: Path,
    *,
    entities: list[str] | None = None,
    relations: list[str] | None = None,
) -> None:
    profile_path.write_text(
        "version: 1\n"
        "space:\n"
        "  name: live-space\n"
        f"{_declarations('entities', entities or [])}"
        f"{_declarations('relations', relations or [])}"
        "records: []\n",
        encoding="utf-8",
    )


def _call_tool(name: str, arguments: dict[str, object]) -> object:
    from memorable.mcp.server import mcp_server

    return asyncio.run(mcp_server.call_tool(name, arguments))


def test_load_profile_reads_memory_yaml_again_after_edit(
    tmp_path: Path, monkeypatch
) -> None:
    """A second load_profile call observes the current MemoryProfile file."""
    from memorable.core.context import ApplicationContext

    profile_dir = tmp_path / ".memorable"
    profile_dir.mkdir()
    profile_path = profile_dir / "memory.yaml"
    _write_profile(profile_path, entities=["Project"])

    monkeypatch.chdir(tmp_path)
    ctx = ApplicationContext()

    first = ctx.load_profile("live-space")
    _write_profile(profile_path, entities=["Project", "Trail"])
    second = ctx.load_profile("live-space")

    assert [entity.name for entity in first.entities] == ["Project"]
    assert [entity.name for entity in second.entities] == ["Project", "Trail"]


def test_mcp_remember_entity_uses_edited_profile_without_rebuilding_context(
    tmp_path: Path, monkeypatch
) -> None:
    """The same MCP context sees a newly declared Entity type on the next call."""
    from memorable.core.context import ApplicationContext, default_context
    from memorable.mcp.server import set_mcp_context

    profile_dir = tmp_path / ".memorable"
    profile_dir.mkdir()
    profile_path = profile_dir / "memory.yaml"
    _write_profile(profile_path, entities=[])

    monkeypatch.chdir(tmp_path)
    ctx = ApplicationContext()
    set_mcp_context(ctx)

    try:
        _, first = _call_tool(
            "memorable_remember_entity",
            {
                "space": "live-space",
                "entity_id": "entity:trail",
                "entity_type": "Trail",
                "name": "River Loop",
                "source": "source:test",
                "at": "2026-05-31T10:00:00Z",
            },
        )

        _write_profile(profile_path, entities=["Trail"])

        _, second = _call_tool(
            "memorable_remember_entity",
            {
                "space": "live-space",
                "entity_id": "entity:trail",
                "entity_type": "Trail",
                "name": "River Loop",
                "source": "source:test",
                "at": "2026-05-31T10:01:00Z",
            },
        )
    finally:
        default_context.reset()
        set_mcp_context(default_context)

    assert "Entity type 'Trail'" in first["error"]
    assert "Declared types: []" in first["error"]
    assert "error" not in second
    assert second["entity_type"] == "Trail"


def test_load_profile_uses_default_profile_when_memory_yaml_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """Missing filesystem profile still falls back to the built-in default."""
    from memorable.core.context import ApplicationContext

    monkeypatch.chdir(tmp_path)
    profile = ApplicationContext().load_profile("memorable")

    assert profile.space.name == "memorable"
    assert "Project" in {entity.name for entity in profile.entities}
    assert "depends-on" in {relation.name for relation in profile.relations}


def test_reset_replaces_entity_repository_with_empty_instance() -> None:
    """reset() still clears repository state after profile cache removal."""
    from memorable.core.context import ApplicationContext
    from memorable.core.models import Entity, Provenance
    from memorable.core.temporal import parse_iso_timestamp

    ctx = ApplicationContext()
    at = parse_iso_timestamp("2026-05-31T10:00:00Z")
    ctx.entity_repo.save(
        Entity(
            id="entity:trail",
            entity_type="Trail",
            name="River Loop",
            space="live-space",
        ),
        Provenance(
            record_id="entity:trail",
            record_kind="entity",
            source_id="source:test",
            episode_id="episode:source:test:2026-05-31T10:00:00+00:00",
            writer="agent:test",
            reason="test reset",
            creation_time=at,
            validity_time=at,
        ),
    )

    ctx.reset()

    assert ctx.entity_repo.get("live-space", "entity:trail") is None


def test_mcp_init_space_existing_space_leaves_memory_yaml_unchanged(
    tmp_path: Path,
) -> None:
    """MCP init_space reports existing space without overwriting edited profile."""
    from memorable.core.context import ApplicationContext, default_context
    from memorable.mcp.server import init_space_tool, set_mcp_context

    profile_dir = tmp_path / ".memorable"
    profile_dir.mkdir()
    profile_path = profile_dir / "memory.yaml"
    _write_profile(profile_path, entities=["Project"])

    ctx = ApplicationContext()
    set_mcp_context(ctx)

    try:
        first = init_space_tool(str(tmp_path))
        _write_profile(profile_path, entities=["Project", "Trail"])
        edited_yaml = profile_path.read_text(encoding="utf-8")

        second = init_space_tool(str(tmp_path))
    finally:
        default_context.reset()
        set_mcp_context(default_context)

    assert first["status"] == "initialized"
    assert second["status"] == "already exists"
    assert profile_path.read_text(encoding="utf-8") == edited_yaml
