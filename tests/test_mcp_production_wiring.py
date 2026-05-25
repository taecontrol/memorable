"""Tests for MCP production wiring.

Verifies that the MCP server creates a production context on startup
and uses it in all tool functions instead of default_context.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from memorable.config import RuntimeConfig
from memorable.core.context import ApplicationContext


def _make_mock_driver() -> MagicMock:
    """Create a mock Neo4j driver that passes verify_connectivity."""
    driver = MagicMock()
    driver.verify_connectivity.return_value = None
    return driver


class TestMCPProductionWiring:
    """MCP server uses production context on startup."""

    def test_mcp_main_creates_production_context(self) -> None:
        """MCP __main__.main() creates production context before running."""
        from memorable.mcp.server import mcp_server

        shared_ctx = ApplicationContext()
        mock_driver = _make_mock_driver()

        with (
            patch("memorable.mcp.__main__.build_production_context") as mock_build,
            patch(
                "memorable.mcp.__main__.load_runtime_config",
                return_value=RuntimeConfig(),
            ),
            patch.object(mcp_server, "run") as mock_run,
            patch("memorable.mcp.__main__.set_mcp_context") as mock_set_ctx,
        ):
            mock_build.return_value = (shared_ctx, mock_driver)

            from memorable.mcp.__main__ import main

            main()

            mock_build.assert_called_once()
            mock_set_ctx.assert_called_once_with(shared_ctx)
            mock_run.assert_called_once_with(transport="stdio")

    def test_mcp_main_closes_driver_after_run(self) -> None:
        """MCP __main__.main() closes the driver when the server stops."""
        from memorable.mcp.server import mcp_server

        shared_ctx = ApplicationContext()
        mock_driver = _make_mock_driver()

        with (
            patch("memorable.mcp.__main__.build_production_context") as mock_build,
            patch(
                "memorable.mcp.__main__.load_runtime_config",
                return_value=RuntimeConfig(),
            ),
            patch.object(mcp_server, "run"),
            patch("memorable.mcp.__main__.set_mcp_context"),
        ):
            mock_build.return_value = (shared_ctx, mock_driver)

            from memorable.mcp.__main__ import main

            main()

        mock_driver.close.assert_called_once()

    def test_mcp_main_closes_driver_on_error(self) -> None:
        """MCP __main__.main() closes driver even if server.run() raises."""
        from memorable.mcp.server import mcp_server

        shared_ctx = ApplicationContext()
        mock_driver = _make_mock_driver()

        with (
            patch("memorable.mcp.__main__.build_production_context") as mock_build,
            patch(
                "memorable.mcp.__main__.load_runtime_config",
                return_value=RuntimeConfig(),
            ),
            patch.object(mcp_server, "run", side_effect=RuntimeError("boom")),
            patch("memorable.mcp.__main__.set_mcp_context"),
        ):
            mock_build.return_value = (shared_ctx, mock_driver)

            from memorable.mcp.__main__ import main

            try:
                main()
            except RuntimeError:
                pass

        mock_driver.close.assert_called_once()


class TestMCPToolsUseContext:
    """MCP tool functions use the production context, not default_context."""

    def test_remember_entity_tool_uses_set_context(self) -> None:
        """remember_entity_tool uses the context set by set_mcp_context."""
        from memorable.mcp.server import remember_entity_tool, set_mcp_context

        ctx = ApplicationContext()
        set_mcp_context(ctx)

        try:
            result = remember_entity_tool(
                space="memorable",
                entity_id="entity:mcp-test",
                entity_type="Project",
                name="MCP Test",
                source="source:test",
                at="2026-05-23T10:10:00Z",
            )

            assert "error" not in result
            assert result["entity_id"] == "entity:mcp-test"

            # Verify it was stored in the custom context, not default
            stored = ctx.entity_repo.get(space="memorable", entity_id="entity:mcp-test")
            assert stored is not None
        finally:
            # Reset to default to avoid polluting other tests
            from memorable.core.context import default_context

            set_mcp_context(default_context)
