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
