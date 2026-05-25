"""Developer convenience entry point: python -m memorable.mcp."""

from __future__ import annotations


def main() -> None:
    """Start the MCP server on stdio."""
    from memorable.mcp.server import mcp_server

    mcp_server.run(transport="stdio")


if __name__ == "__main__":
    main()
