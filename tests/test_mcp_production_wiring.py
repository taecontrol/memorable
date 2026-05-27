"""Tests for MCP production wiring.

Verifies that the MCP server creates a production context on startup
and uses it in all tool functions instead of default_context.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from memorable.config import EmbeddingSettings, RuntimeConfig
from memorable.core.context import ApplicationContext, default_context


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
            set_mcp_context(default_context)


class TestMCPSearchUsesRuntimeConfig:
    """MCP search builds embedding provider from runtime config."""

    def test_search_builds_provider_from_runtime_config(self) -> None:
        """search_memory_tool uses build_embedding_provider with config.embeddings."""
        from memorable.mcp.server import search_memory_tool, set_mcp_context
        from memorable.retrieval.embeddings import FakeEmbeddingProvider

        ctx = ApplicationContext()
        set_mcp_context(ctx)

        config = RuntimeConfig(
            embeddings=EmbeddingSettings(provider="fake", dimensions=32),
        )

        try:
            with (
                patch(
                    "memorable.mcp.server.load_runtime_config",
                    return_value=config,
                ),
                patch(
                    "memorable.retrieval.embeddings.build_embedding_provider",
                ) as mock_build_provider,
            ):
                mock_build_provider.return_value = FakeEmbeddingProvider(
                    dimensions=32
                )

                result = search_memory_tool(
                    space="memorable", query="test query"
                )

            assert "error" not in result
            mock_build_provider.assert_called_once_with(
                config.embeddings,
                api_key=config.embeddings.api_key,
            )
        finally:
            set_mcp_context(default_context)

    def test_search_openrouter_with_api_key_builds_provider(self) -> None:
        """openrouter + api_key builds OpenRouter provider successfully."""
        from memorable.mcp.server import search_memory_tool, set_mcp_context
        from memorable.retrieval.embeddings import FakeEmbeddingProvider

        ctx = ApplicationContext()
        set_mcp_context(ctx)

        config = RuntimeConfig(
            embeddings=EmbeddingSettings(
                provider="openrouter",
                api_key="sk-or-test-key",
            ),
        )

        try:
            with (
                patch(
                    "memorable.mcp.server.load_runtime_config",
                    return_value=config,
                ),
                patch(
                    "memorable.retrieval.embeddings.build_embedding_provider",
                ) as mock_build_provider,
            ):
                mock_build_provider.return_value = FakeEmbeddingProvider(
                    dimensions=32
                )

                result = search_memory_tool(
                    space="memorable", query="test"
                )

            assert "error" not in result
            mock_build_provider.assert_called_once_with(
                config.embeddings,
                api_key="sk-or-test-key",
            )
        finally:
            set_mcp_context(default_context)

    def test_search_unknown_provider_returns_error(self) -> None:
        """Unknown provider returns error dict, not a traceback."""
        from memorable.mcp.server import search_memory_tool, set_mcp_context

        ctx = ApplicationContext()
        set_mcp_context(ctx)

        config = RuntimeConfig(
            embeddings=EmbeddingSettings(provider="nonexistent"),
        )

        try:
            with patch(
                "memorable.mcp.server.load_runtime_config",
                return_value=config,
            ):
                result = search_memory_tool(
                    space="memorable", query="test"
                )

            assert "error" in result
            assert "nonexistent" in result["error"]
        finally:
            set_mcp_context(default_context)

    def test_search_openrouter_without_api_key_returns_error(self) -> None:
        """openrouter without API key returns error dict with actionable message."""
        from memorable.mcp.server import search_memory_tool, set_mcp_context

        ctx = ApplicationContext()
        set_mcp_context(ctx)

        config = RuntimeConfig(
            embeddings=EmbeddingSettings(provider="openrouter"),
        )

        try:
            with patch(
                "memorable.mcp.server.load_runtime_config",
                return_value=config,
            ):
                result = search_memory_tool(
                    space="memorable", query="test"
                )

            assert "error" in result
            assert "MEMORABLE_OPENROUTER_API_KEY" in result["error"]
        finally:
            set_mcp_context(default_context)

    def test_search_default_config_uses_fastembed(self) -> None:
        """Default config (no runtime.yaml, no .env) passes fastembed settings."""
        from memorable.mcp.server import search_memory_tool, set_mcp_context
        from memorable.retrieval.embeddings import FakeEmbeddingProvider

        ctx = ApplicationContext()
        set_mcp_context(ctx)

        try:
            with (
                patch(
                    "memorable.mcp.server.load_runtime_config",
                    return_value=RuntimeConfig(),
                ),
                patch(
                    "memorable.retrieval.embeddings.build_embedding_provider",
                ) as mock_build_provider,
            ):
                mock_build_provider.return_value = FakeEmbeddingProvider(
                    dimensions=32
                )

                result = search_memory_tool(
                    space="memorable", query="anything"
                )

            assert "error" not in result
            called_settings = mock_build_provider.call_args[0][0]
            assert called_settings.provider == "fastembed"
            assert called_settings.api_key is None
        finally:
            set_mcp_context(default_context)
