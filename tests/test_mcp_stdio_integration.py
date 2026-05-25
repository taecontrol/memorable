"""Integration test for MCP stdio transport (issue #26).

Spawns the MCP server as a subprocess over stdio and exercises the
full protocol path: initialize -> list_tools -> call_tool -> verify response.

This proves an agent can connect to Memorable over MCP and use memory
tools without importing Python internals.

Run with: uv run pytest tests/test_mcp_stdio_integration.py -v -m integration
"""

from __future__ import annotations

import json
import sys

import pytest

pytestmark = pytest.mark.integration


async def _connect_and_run(callback):
    """Spawn the MCP server subprocess and run *callback(session)*.

    Uses the MCP SDK's stdio_client + ClientSession to establish a
    real stdio transport connection to ``python -m memorable.mcp``.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "memorable.mcp"],
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await callback(session)


class TestStdioServerSpawns:
    """The MCP server can be spawned as a subprocess and initialized."""

    @pytest.mark.anyio
    async def test_server_initializes_over_stdio(self) -> None:
        """Spawning the server and calling initialize() succeeds."""

        async def _check(session):
            # If we get here, the handshake succeeded.
            return True

        assert await _connect_and_run(_check)


class TestListToolsOverStdio:
    """list_tools works through the stdio transport."""

    @pytest.mark.anyio
    async def test_list_tools_returns_all_registered_tools(self) -> None:
        async def _check(session):
            result = await session.list_tools()
            tool_names = {t.name for t in result.tools}
            return tool_names

        tool_names = await _connect_and_run(_check)

        expected = {
            "memorable_status",
            "memorable_init_space",
            "memorable_inspect_space",
            "memorable_remember_entity",
            "memorable_remember_decision",
            "memorable_remember_observation",
            "memorable_current_truth",
            "memorable_point_in_time_truth",
            "memorable_inspect_history",
            "memorable_inspect_provenance",
            "memorable_remember_task",
            "memorable_complete_task",
            "memorable_search_memory",
            "memorable_inspect_task",
        }
        assert tool_names == expected

    @pytest.mark.anyio
    async def test_list_tools_returns_15_tools(self) -> None:
        async def _check(session):
            result = await session.list_tools()
            return len(result.tools)

        count = await _connect_and_run(_check)
        assert count == 15


class TestCallToolOverStdio:
    """call_tool works through the stdio transport for memorable_status."""

    @pytest.mark.anyio
    async def test_status_tool_returns_text_content(self) -> None:
        """The status tool returns at least one text content block."""

        async def _check(session):
            result = await session.call_tool("memorable_status", {})
            return result

        result = await _connect_and_run(_check)
        assert result.content, "Expected at least one content block"
        assert not result.isError

    @pytest.mark.anyio
    async def test_status_tool_content_is_valid_json(self) -> None:
        """The text content block is parseable JSON."""

        async def _check(session):
            result = await session.call_tool("memorable_status", {})
            return result

        result = await _connect_and_run(_check)
        text_block = result.content[0]
        payload = json.loads(text_block.text)
        assert isinstance(payload, dict)

    @pytest.mark.anyio
    async def test_status_tool_response_shape(self) -> None:
        """The status response has the expected Memorable diagnostic fields."""

        async def _check(session):
            result = await session.call_tool("memorable_status", {})
            return result

        result = await _connect_and_run(_check)
        payload = json.loads(result.content[0].text)

        assert payload["product"] == "Memorable"
        assert payload["memory_space_scope"] == "project"
        assert payload["service"] == "diagnostics"

    @pytest.mark.anyio
    async def test_status_structured_content(self) -> None:
        """If the server returns structuredContent, it matches the payload."""

        async def _check(session):
            result = await session.call_tool("memorable_status", {})
            return result

        result = await _connect_and_run(_check)

        if result.structuredContent is not None:
            assert result.structuredContent["product"] == "Memorable"
            assert result.structuredContent["service"] == "diagnostics"


class TestCallToolErrorOverStdio:
    """Error paths work through the stdio transport."""

    @pytest.mark.anyio
    async def test_current_truth_error_for_missing_decision(self) -> None:
        """Calling current_truth for a nonexistent decision returns an error."""

        async def _check(session):
            result = await session.call_tool(
                "memorable_current_truth",
                {"space": "nonexistent", "decision_id": "no-such-decision"},
            )
            return result

        result = await _connect_and_run(_check)
        text_block = result.content[0]
        payload = json.loads(text_block.text)

        assert "error" in payload
        assert "No Decision found" in payload["error"]
