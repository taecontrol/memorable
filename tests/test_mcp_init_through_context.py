"""Tests for routing MCP init through ApplicationContext.

Verifies that init_space_tool() uses default_context.memory_space_repo
instead of a throwaway repository, so that a second init on the same
space reports 'already exists'.
"""

from __future__ import annotations

from pathlib import Path


def test_mcp_init_twice_reports_already_exists(tmp_path: Path) -> None:
    """Calling init_space_tool twice on the same space reports 'already exists'.

    This proves the MCP init tool uses the shared repository (via
    ApplicationContext) rather than a throwaway one.
    """
    from memorable.core.context import default_context
    from memorable.mcp.server import init_space_tool

    # Set up a .memorable/memory.yaml in a temp directory
    memorable_dir = tmp_path / ".memorable"
    memorable_dir.mkdir()
    (memorable_dir / "memory.yaml").write_text(
        "version: 1\n"
        "space:\n"
        "  name: test-project\n"
        "  description: Test\n"
        "entities:\n"
        "  - name: Component\n"
        "records:\n"
        "  - name: ArchitectureDecision\n"
        "    extends: Decision\n",
        encoding="utf-8",
    )

    # Reset context so we start clean
    default_context.reset()

    try:
        first = init_space_tool(str(tmp_path))
        assert first["status"] == "initialized"

        second = init_space_tool(str(tmp_path))
        assert second["status"] == "already exists"
    finally:
        # Clean up: reset context to avoid leaking state to other tests
        default_context.reset()
