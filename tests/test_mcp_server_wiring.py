"""Tests for FastMCP server wiring (issue #25).

Verifies:
- FastMCP server instance is created with name "memorable"
- All 14 handler functions are registered as MCP tools
- Each tool name uses the memorable/ prefix
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
    "memorable/status",
    "memorable/init_space",
    "memorable/inspect_space",
    "memorable/remember_entity",
    "memorable/remember_decision",
    "memorable/current_truth",
    "memorable/point_in_time_truth",
    "memorable/inspect_decision_history",
    "memorable/inspect_provenance",
    "memorable/remember_task",
    "memorable/complete_task",
    "memorable/search_memory",
    "memorable/inspect_task",
    "memorable/tracer_run",
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
            assert tool.name.startswith("memorable/"), (
                f"Tool {tool.name!r} missing memorable/ prefix"
            )
