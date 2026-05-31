"""Tests for FastMCP server wiring (issue #25).

Verifies:
- FastMCP server instance is created with name "memorable"
- All handler functions are registered as MCP tools
- Each tool name uses the memorable_ prefix
- Tool descriptions use Memorable Core language
- Tools are callable through call_tool() and return expected shapes
- Entry points wire to mcp.run() with stdio transport
"""

from __future__ import annotations

import asyncio

import pytest


def _list_tool_names() -> set[str]:
    """Return registered tool names from the FastMCP server (sync helper)."""
    from memorable.mcp.server import mcp_server

    tools = asyncio.run(mcp_server.list_tools())
    return {t.name for t in tools}


def _list_tools() -> list:
    """Return registered tool objects from the FastMCP server (sync helper)."""
    from memorable.mcp.server import mcp_server

    return asyncio.run(mcp_server.list_tools())


class TestFastMCPServerInstance:
    def test_server_is_importable(self) -> None:
        from memorable.mcp.server import mcp_server

        assert mcp_server is not None

    def test_server_is_fastmcp_instance(self) -> None:
        from mcp.server.fastmcp import FastMCP

        from memorable.mcp.server import mcp_server

        assert isinstance(mcp_server, FastMCP)

    def test_server_name_is_memorable(self) -> None:
        from memorable.mcp.server import mcp_server

        assert mcp_server.name == "memorable"


EXPECTED_TOOL_NAMES = {
    "memorable_guide",
    "memorable_status",
    "memorable_doctor",
    "memorable_init_space",
    "memorable_inspect_space",
    "memorable_remember_entity",
    "memorable_remember_decision",
    "memorable_remember_observation",
    "memorable_remember_relation",
    "memorable_current_truth",
    "memorable_point_in_time_truth",
    "memorable_inspect_history",
    "memorable_inspect_provenance",
    "memorable_remember_task",
    "memorable_complete_task",
    "memorable_search_memory",
    "memorable_inspect_task",
    "memorable_invalidate",
    "memorable_correct",
    "memorable_list_records",
}

EXPECTED_GUIDE_TOPICS = [
    "overview",
    "writing",
    "retrieval",
    "temporal",
    "profiles",
    "recipes",
    "reference",
]


class TestToolRegistration:
    def test_all_20_tools_registered(self) -> None:
        tool_names = _list_tool_names()
        assert len(tool_names) == 20

    def test_all_expected_tool_names_present(self) -> None:
        tool_names = _list_tool_names()
        assert tool_names == EXPECTED_TOOL_NAMES

    def test_every_tool_name_has_memorable_prefix(self) -> None:
        tools = _list_tools()
        for tool in tools:
            assert tool.name.startswith("memorable_"), (
                f"Tool {tool.name!r} missing memorable_ prefix"
            )

    def test_list_records_tool_contract_signature_is_stable(self) -> None:
        tools = {tool.name: tool for tool in _list_tools()}
        tool = tools["memorable_list_records"]

        assert tool.name == "memorable_list_records"
        assert tool.inputSchema == {
            "properties": {
                "space": {"title": "Space", "type": "string"},
                "type": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "title": "Type",
                },
                "state": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "title": "State",
                },
                "since": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "title": "Since",
                },
                "until": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "title": "Until",
                },
                "about": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "default": None,
                    "title": "About",
                },
                "limit": {"default": 50, "title": "Limit", "type": "integer"},
            },
            "required": ["space"],
            "title": "list_records_toolArguments",
            "type": "object",
        }

    def test_guide_topic_schema_is_closed_set(self) -> None:
        tools = {tool.name: tool for tool in _list_tools()}
        tool = tools["memorable_guide"]

        topic_schema = tool.inputSchema["properties"]["topic"]
        assert {"type": "null"} in topic_schema["anyOf"]
        assert {
            "enum": EXPECTED_GUIDE_TOPICS,
            "type": "string",
        } in topic_schema["anyOf"]


# Core domain terms that must appear in at least one tool description.
# These are from docs/ubiquitous-language.md accepted language.
REQUIRED_DOMAIN_TERMS = {
    "MemorySpace",
    "MemoryProfile",
    "Provenance",
    "Current Truth",
    "Point-In-Time",
    "Supersession",
    "Lifecycle State",
    "Entity",
    "Decision",
    "Task",
    "Observation",
    "Relation",
    "Source",
    "Episode",
    "Hybrid Retrieval",
}

# Storage vocabulary that must not leak into tool descriptions.
AVOIDED_STORAGE_TERMS = {"node", "edge", "neo4j", "graphiti"}


class TestToolDescriptions:
    def test_every_tool_has_a_description(self) -> None:
        tools = _list_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name!r} has no description"

    def test_descriptions_use_core_domain_terms(self) -> None:
        tools = _list_tools()
        all_descriptions = " ".join(t.description for t in tools)
        missing = {
            term for term in REQUIRED_DOMAIN_TERMS if term not in all_descriptions
        }
        assert not missing, f"Tool descriptions missing Memorable Core terms: {missing}"

    def test_descriptions_avoid_storage_vocabulary(self) -> None:
        tools = _list_tools()
        all_descriptions = " ".join(t.description for t in tools).lower()
        leaked = {term for term in AVOIDED_STORAGE_TERMS if term in all_descriptions}
        assert not leaked, f"Tool descriptions leak storage vocabulary: {leaked}"

    def test_doctor_description_distinguishes_status_boundary(self) -> None:
        tools = {tool.name: tool for tool in _list_tools()}
        description = tools["memorable_doctor"].description
        assert "status reports current runtime state" in description
        assert "doctor diagnoses problems" in description
        assert "remediation hints" in description

    def test_about_tool_descriptions_state_agent_contract(self) -> None:
        tools = {tool.name: tool for tool in _list_tools()}
        for tool_name in {
            "memorable_remember_decision",
            "memorable_remember_observation",
            "memorable_remember_task",
            "memorable_correct",
            "memorable_list_records",
        }:
            description = tools[tool_name].description
            assert "Entity first" in description
            assert "membership, not a Relation claim" in description
            assert "correctable" in description


def _call_tool(name: str, arguments: dict) -> object:
    """Call a tool on the FastMCP server and return the result (sync helper)."""
    from memorable.mcp.server import mcp_server

    return asyncio.run(mcp_server.call_tool(name, arguments))


def _call_text_tool(name: str, arguments: dict) -> str:
    content, structured = _call_tool(name, arguments)
    if isinstance(structured, str):
        return structured
    assert len(content) == 1
    return content[0].text


class TestCallToolSuccessPath:
    def test_guide_tool_returns_index_when_called_bare(self) -> None:
        from memorable.guide import render

        assert _call_text_tool("memorable_guide", {}) == render()

    @pytest.mark.parametrize(
        "topic_name",
        ("overview", "writing", "retrieval", "temporal", "profiles", "recipes"),
    )
    def test_guide_tool_returns_authored_topic(self, topic_name: str) -> None:
        from memorable.guide import render

        assert _call_text_tool("memorable_guide", {"topic": topic_name}) == render(
            topic_name
        )

    def test_status_tool_returns_diagnostic_payload(self) -> None:
        result = _call_tool("memorable_status", {})
        # call_tool returns a tuple of (content_blocks, structured_result)
        _, structured = result
        assert structured["product"] == "Memorable"
        assert structured["memory_space_scope"] == "project"
        assert structured["service"] == "diagnostics"

    def test_status_tool_result_uses_core_language(self) -> None:
        import json

        result = _call_tool("memorable_status", {})
        _, structured = result
        text = json.dumps(structured).lower()
        assert "node" not in text
        assert "edge" not in text

    def test_doctor_tool_returns_structured_diagnostics(self, monkeypatch) -> None:
        from memorable.config import RuntimeConfig

        expected = [
            {"check": "neo4j_connectivity", "ok": False, "hint": "start runtime"}
        ]

        monkeypatch.setattr(
            "memorable.mcp.server.load_runtime_config",
            lambda **_kwargs: RuntimeConfig(),
        )
        monkeypatch.setattr(
            "memorable.mcp.server.run_diagnostics", lambda _config: expected
        )

        result = _call_tool("memorable_doctor", {})

        _, structured = result
        assert structured["result"] == expected

    def test_correct_task_about_only_omits_new_statement(self) -> None:
        from memorable.core.context import default_context
        from memorable.mcp.server import set_mcp_context

        default_context.reset()
        set_mcp_context(default_context)
        _call_tool(
            "memorable_remember_entity",
            {
                "space": "memorable",
                "entity_id": "entity:wrong",
                "entity_type": "Project",
                "name": "Wrong",
                "source": "source:test",
                "at": "2026-05-31T09:00:00Z",
            },
        )
        _call_tool(
            "memorable_remember_entity",
            {
                "space": "memorable",
                "entity_id": "entity:right",
                "entity_type": "Project",
                "name": "Right",
                "source": "source:test",
                "at": "2026-05-31T09:01:00Z",
            },
        )
        _call_tool(
            "memorable_remember_task",
            {
                "space": "memorable",
                "task_id": "task:about-only",
                "title": "Correct About only.",
                "source": "source:test",
                "at": "2026-05-31T09:02:00Z",
                "about": ["entity:wrong"],
            },
        )

        _, structured = _call_tool(
            "memorable_correct",
            {
                "space": "memorable",
                "record_id": "task:about-only",
                "record_type": "task",
                "source": "source:correction",
                "at": "2026-05-31T10:00:00Z",
                "about": ["entity:right"],
            },
        )

        assert "error" not in structured
        assert structured["new_statement"] == "Correct About only."
        assert default_context.about_repo.entities_for_record(
            "memorable", "task:about-only"
        ) == ["entity:right"]


class TestCallToolErrorPath:
    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_current_truth_returns_error_for_missing_decision(self) -> None:
        result = _call_tool(
            "memorable_current_truth",
            {"space": "nonexistent", "record_id": "no-such-decision"},
        )
        _, structured = result
        assert "error" in structured
        assert "No Decision found" in structured["error"]
        assert "MemorySpace" in structured["error"]

    def test_error_response_uses_domain_language(self) -> None:
        result = _call_tool(
            "memorable_current_truth",
            {"space": "test-space", "record_id": "missing"},
        )
        _, structured = result
        error_text = structured["error"].lower()
        assert "node" not in error_text
        assert "edge" not in error_text

    def test_remember_decision_about_missing_entity_surfaces_error(self) -> None:
        result = _call_tool(
            "memorable_remember_decision",
            {
                "space": "memorable",
                "decision_id": "decision:missing-about",
                "statement": "This is about a missing Entity.",
                "source": "source:test",
                "at": "2026-05-31T09:00:00Z",
                "about": ["entity:missing"],
            },
        )

        _, structured = result
        assert structured == {
            "error": "About target Entity 'entity:missing' not found "
            "in MemorySpace 'memorable'. Create the Entity before "
            "linking a MemoryRecord to it."
        }


class TestEntryPointWiring:
    def test_main_calls_mcp_server_run(self) -> None:
        """Verify __main__.main() calls mcp_server.run() with stdio transport.

        We patch mcp_server.run to capture the call instead of actually
        starting a stdio loop. Also patches production context to avoid
        requiring a real Neo4j connection.
        """
        from unittest.mock import MagicMock, patch

        from memorable.config import RuntimeConfig
        from memorable.core.context import ApplicationContext
        from memorable.mcp.server import mcp_server

        ctx = ApplicationContext()
        mock_driver = MagicMock()
        mock_driver.verify_connectivity.return_value = None

        with (
            patch.object(mcp_server, "run") as mock_run,
            patch(
                "memorable.mcp.__main__.build_production_context",
                return_value=(ctx, mock_driver),
            ),
            patch(
                "memorable.mcp.__main__.load_runtime_config",
                return_value=RuntimeConfig(),
            ) as mock_load,
            patch("memorable.mcp.__main__.set_mcp_context"),
        ):
            from memorable.mcp.__main__ import main

            main()
            mock_load.assert_called_once_with(include_environment_overrides=True)
            mock_run.assert_called_once_with(transport="stdio")

    def test_main_does_not_raise_system_exit(self) -> None:
        """After wiring, main() should not raise SystemExit."""
        from unittest.mock import MagicMock, patch

        from memorable.config import RuntimeConfig
        from memorable.core.context import ApplicationContext
        from memorable.mcp.server import mcp_server

        ctx = ApplicationContext()
        mock_driver = MagicMock()
        mock_driver.verify_connectivity.return_value = None

        with (
            patch.object(mcp_server, "run"),
            patch(
                "memorable.mcp.__main__.build_production_context",
                return_value=(ctx, mock_driver),
            ),
            patch(
                "memorable.mcp.__main__.load_runtime_config",
                return_value=RuntimeConfig(),
            ),
            patch("memorable.mcp.__main__.set_mcp_context"),
        ):
            from memorable.mcp.__main__ import main

            # Should not raise
            main()
