"""Tests for FastMCP server wiring (issue #25).

Verifies:
- FastMCP server instance is created with name "memorable"
- All 14 handler functions are registered as MCP tools
- Each tool name uses the memorable_ prefix
- Tool descriptions use Memorable Core language
- Tools are callable through call_tool() and return expected shapes
- Entry points wire to mcp.run() with stdio transport
"""

from __future__ import annotations

import asyncio


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
    "memorable_status",
    "memorable_init_space",
    "memorable_inspect_space",
    "memorable_remember_entity",
    "memorable_remember_decision",
    "memorable_current_truth",
    "memorable_point_in_time_truth",
    "memorable_inspect_decision_history",
    "memorable_inspect_provenance",
    "memorable_remember_task",
    "memorable_complete_task",
    "memorable_search_memory",
    "memorable_inspect_task",
    "memorable_tracer_run",
}


class TestToolRegistration:
    def test_all_14_tools_registered(self) -> None:
        tool_names = _list_tool_names()
        assert len(tool_names) == 14

    def test_all_expected_tool_names_present(self) -> None:
        tool_names = _list_tool_names()
        assert tool_names == EXPECTED_TOOL_NAMES

    def test_every_tool_name_has_memorable_prefix(self) -> None:
        tools = _list_tools()
        for tool in tools:
            assert tool.name.startswith("memorable_"), (
                f"Tool {tool.name!r} missing memorable_ prefix"
            )


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
            assert tool.description, (
                f"Tool {tool.name!r} has no description"
            )

    def test_descriptions_use_core_domain_terms(self) -> None:
        tools = _list_tools()
        all_descriptions = " ".join(t.description for t in tools)
        missing = {
            term for term in REQUIRED_DOMAIN_TERMS if term not in all_descriptions
        }
        assert not missing, (
            f"Tool descriptions missing Memorable Core terms: {missing}"
        )

    def test_descriptions_avoid_storage_vocabulary(self) -> None:
        tools = _list_tools()
        all_descriptions = " ".join(t.description for t in tools).lower()
        leaked = {
            term for term in AVOIDED_STORAGE_TERMS if term in all_descriptions
        }
        assert not leaked, (
            f"Tool descriptions leak storage vocabulary: {leaked}"
        )


def _call_tool(name: str, arguments: dict) -> object:
    """Call a tool on the FastMCP server and return the result (sync helper)."""
    from memorable.mcp.server import mcp_server

    return asyncio.run(mcp_server.call_tool(name, arguments))


class TestCallToolSuccessPath:
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


class TestCallToolErrorPath:
    def test_current_truth_returns_error_for_missing_decision(self) -> None:
        result = _call_tool(
            "memorable_current_truth",
            {"space": "nonexistent", "decision_id": "no-such-decision"},
        )
        _, structured = result
        assert "error" in structured
        assert "No Decision found" in structured["error"]
        assert "MemorySpace" in structured["error"]

    def test_error_response_uses_domain_language(self) -> None:
        result = _call_tool(
            "memorable_current_truth",
            {"space": "test-space", "decision_id": "missing"},
        )
        _, structured = result
        error_text = structured["error"].lower()
        assert "node" not in error_text
        assert "edge" not in error_text


class TestEntryPointWiring:
    def test_main_calls_mcp_server_run(self) -> None:
        """Verify __main__.main() calls mcp_server.run() with stdio transport.

        We patch mcp_server.run to capture the call instead of actually
        starting a stdio loop.
        """
        from unittest.mock import patch

        from memorable.mcp.server import mcp_server

        with patch.object(mcp_server, "run") as mock_run:
            from memorable.mcp.__main__ import main

            main()
            mock_run.assert_called_once_with(transport="stdio")

    def test_main_does_not_raise_system_exit(self) -> None:
        """After wiring, main() should not raise SystemExit."""
        from unittest.mock import patch

        from memorable.mcp.server import mcp_server

        with patch.object(mcp_server, "run"):
            from memorable.mcp.__main__ import main

            # Should not raise
            main()
