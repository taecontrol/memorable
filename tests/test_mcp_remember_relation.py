"""End-to-end tests for the memorable_remember_relation MCP tool.

Verifies:
- Happy path: remember a Relation returns expected dict shape
- Error: undeclared relation type returns error dict
- Error: missing source entity returns error dict
- Error: self-relation returns error dict
- Temporal tools work with record_type="relation": current_truth,
  point_in_time_truth, inspect_history, invalidate, correct
"""

from __future__ import annotations

import asyncio

from memorable.core.context import ApplicationContext
from memorable.mcp.server import set_mcp_context


def _call_tool(name: str, arguments: dict) -> object:
    """Call a tool on the FastMCP server and return the result (sync helper)."""
    from memorable.mcp.server import mcp_server

    return asyncio.run(mcp_server.call_tool(name, arguments))


def _setup_space_with_entities() -> ApplicationContext:
    """Create a context with a space and two entities.

    Returns the context so tests can inspect repos if needed.
    """
    ctx = ApplicationContext()
    set_mcp_context(ctx)

    # Initialize the space
    ctx.memory_space_repo.create_space("test-space")

    # Remember two entities as source and target
    _, source_result = _call_tool(
        "memorable_remember_entity",
        {
            "space": "test-space",
            "entity_id": "entity:frontend",
            "entity_type": "Component",
            "name": "Frontend",
            "source": "test-source",
            "at": "2026-05-26T10:00:00Z",
        },
    )
    assert "error" not in source_result, f"Source entity setup failed: {source_result}"

    _, target_result = _call_tool(
        "memorable_remember_entity",
        {
            "space": "test-space",
            "entity_id": "entity:backend",
            "entity_type": "Component",
            "name": "Backend",
            "source": "test-source",
            "at": "2026-05-26T10:00:00Z",
        },
    )
    assert "error" not in target_result, f"Target entity setup failed: {target_result}"

    return ctx


class TestRememberRelationHappyPath:
    def setup_method(self) -> None:
        self.ctx = _setup_space_with_entities()

    def test_remember_relation_returns_expected_keys(self) -> None:
        _, result = _call_tool(
            "memorable_remember_relation",
            {
                "space": "test-space",
                "relation_id": "rel:1",
                "source_entity_id": "entity:frontend",
                "target_entity_id": "entity:backend",
                "relation_type": "depends-on",
                "statement": "Frontend depends on Backend",
                "source": "test-source",
                "at": "2026-05-26T12:00:00Z",
            },
        )
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
        assert set(result.keys()) == expected_keys

    def test_remember_relation_returns_correct_values(self) -> None:
        _, result = _call_tool(
            "memorable_remember_relation",
            {
                "space": "test-space",
                "relation_id": "rel:2",
                "source_entity_id": "entity:frontend",
                "target_entity_id": "entity:backend",
                "relation_type": "depends-on",
                "statement": "Frontend depends on Backend API",
                "source": "test-source",
                "at": "2026-05-26T12:00:00Z",
            },
        )
        assert result["relation_id"] == "rel:2"
        assert result["statement"] == "Frontend depends on Backend API"
        assert result["space"] == "test-space"
        assert result["record_kind"] == "relation"
        assert result["lifecycle_state"] == "current"
        assert result["source_entity_id"] == "entity:frontend"
        assert result["target_entity_id"] == "entity:backend"
        assert result["relation_type"] == "depends-on"
        assert result["source"] == "test-source"

    def test_remember_relation_with_supersession(self) -> None:
        # Remember first relation
        _call_tool(
            "memorable_remember_relation",
            {
                "space": "test-space",
                "relation_id": "rel:original",
                "source_entity_id": "entity:frontend",
                "target_entity_id": "entity:backend",
                "relation_type": "depends-on",
                "statement": "Frontend depends on Backend v1",
                "source": "test-source",
                "at": "2026-05-26T12:00:00Z",
            },
        )

        # Supersede with a new relation
        _, result = _call_tool(
            "memorable_remember_relation",
            {
                "space": "test-space",
                "relation_id": "rel:successor",
                "source_entity_id": "entity:frontend",
                "target_entity_id": "entity:backend",
                "relation_type": "depends-on",
                "statement": "Frontend depends on Backend v2",
                "source": "test-source",
                "at": "2026-05-26T13:00:00Z",
                "supersedes": "rel:original",
            },
        )
        assert result["relation_id"] == "rel:successor"
        assert result["lifecycle_state"] == "current"


class TestRememberRelationErrors:
    def setup_method(self) -> None:
        self.ctx = _setup_space_with_entities()

    def test_undeclared_relation_type_returns_error(self) -> None:
        _, result = _call_tool(
            "memorable_remember_relation",
            {
                "space": "test-space",
                "relation_id": "rel:bad",
                "source_entity_id": "entity:frontend",
                "target_entity_id": "entity:backend",
                "relation_type": "not-declared",
                "statement": "Bad relation type",
                "source": "test-source",
                "at": "2026-05-26T12:00:00Z",
            },
        )
        assert "error" in result
        assert "not-declared" in result["error"]
        assert "not declared" in result["error"].lower()

    def test_missing_source_entity_returns_error(self) -> None:
        _, result = _call_tool(
            "memorable_remember_relation",
            {
                "space": "test-space",
                "relation_id": "rel:bad",
                "source_entity_id": "entity:nonexistent",
                "target_entity_id": "entity:backend",
                "relation_type": "depends-on",
                "statement": "Bad source entity",
                "source": "test-source",
                "at": "2026-05-26T12:00:00Z",
            },
        )
        assert "error" in result
        assert "entity:nonexistent" in result["error"]

    def test_missing_target_entity_returns_error(self) -> None:
        _, result = _call_tool(
            "memorable_remember_relation",
            {
                "space": "test-space",
                "relation_id": "rel:bad",
                "source_entity_id": "entity:frontend",
                "target_entity_id": "entity:ghost",
                "relation_type": "depends-on",
                "statement": "Bad target entity",
                "source": "test-source",
                "at": "2026-05-26T12:00:00Z",
            },
        )
        assert "error" in result
        assert "entity:ghost" in result["error"]

    def test_self_relation_returns_error(self) -> None:
        _, result = _call_tool(
            "memorable_remember_relation",
            {
                "space": "test-space",
                "relation_id": "rel:bad",
                "source_entity_id": "entity:frontend",
                "target_entity_id": "entity:frontend",
                "relation_type": "depends-on",
                "statement": "Self-referencing relation",
                "source": "test-source",
                "at": "2026-05-26T12:00:00Z",
            },
        )
        assert "error" in result
        assert "self-relation" in result["error"].lower()


class TestRelationTemporalToolWiring:
    """Temporal tools (current_truth, point_in_time_truth, inspect_history,
    invalidate, correct) work with record_type='relation'.
    """

    def setup_method(self) -> None:
        self.ctx = _setup_space_with_entities()
        # Remember a relation to work with
        _call_tool(
            "memorable_remember_relation",
            {
                "space": "test-space",
                "relation_id": "rel:temporal",
                "source_entity_id": "entity:frontend",
                "target_entity_id": "entity:backend",
                "relation_type": "depends-on",
                "statement": "Frontend depends on Backend",
                "source": "test-source",
                "at": "2026-05-26T12:00:00Z",
            },
        )

    def test_current_truth_resolves_relation(self) -> None:
        _, result = _call_tool(
            "memorable_current_truth",
            {
                "space": "test-space",
                "record_id": "rel:temporal",
                "record_type": "relation",
            },
        )
        assert "error" not in result
        assert result["record_id"] == "rel:temporal"
        assert result["lifecycle_state"] == "current"

    def test_point_in_time_truth_resolves_relation(self) -> None:
        _, result = _call_tool(
            "memorable_point_in_time_truth",
            {
                "space": "test-space",
                "record_id": "rel:temporal",
                "at": "2026-05-26T13:00:00Z",
                "record_type": "relation",
            },
        )
        assert "error" not in result
        assert result["record_id"] == "rel:temporal"

    def test_inspect_history_returns_relation_chain(self) -> None:
        _, result = _call_tool(
            "memorable_inspect_history",
            {
                "space": "test-space",
                "record_id": "rel:temporal",
                "record_type": "relation",
            },
        )
        assert "error" not in result
        assert result["record_type"] == "relation"
        assert len(result["history"]) == 1
        assert result["history"][0]["record_id"] == "rel:temporal"

    def test_invalidate_marks_relation_invalidated(self) -> None:
        _, result = _call_tool(
            "memorable_invalidate",
            {
                "space": "test-space",
                "record_id": "rel:temporal",
                "record_type": "relation",
                "at": "2026-05-26T14:00:00Z",
            },
        )
        assert "error" not in result
        assert result["lifecycle_state"] == "invalidated"

    def test_correct_updates_relation_statement(self) -> None:
        _, result = _call_tool(
            "memorable_correct",
            {
                "space": "test-space",
                "record_id": "rel:temporal",
                "record_type": "relation",
                "new_statement": "Frontend requires Backend API",
                "source": "correction-source",
                "at": "2026-05-26T14:00:00Z",
            },
        )
        assert "error" not in result
        assert result["old_statement"] == "Frontend depends on Backend"
        assert result["new_statement"] == "Frontend requires Backend API"
