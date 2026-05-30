"""Developer convenience entry point: python -m memorable.mcp."""

from __future__ import annotations

from memorable.config import load_runtime_config
from memorable.mcp.server import mcp_server, set_mcp_context
from memorable.storage.production import build_production_context


def main() -> None:
    """Start the MCP server on stdio with production context."""
    config = load_runtime_config(include_environment_overrides=True)
    ctx, driver = build_production_context(config)
    try:
        set_mcp_context(ctx)
        mcp_server.run(transport="stdio")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
