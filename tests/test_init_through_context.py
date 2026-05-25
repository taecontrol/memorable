"""Tests for routing CLI init through ApplicationContext.

Verifies that ApplicationContext owns the MemorySpaceRepository and
that the CLI init command uses the shared repository instead of a
throwaway one.
"""

from __future__ import annotations


def test_application_context_has_default_memory_space_repo() -> None:
    """ApplicationContext should default to an InMemoryMemorySpaceRepository."""
    from memorable.core.context import ApplicationContext
    from memorable.core.repositories import InMemoryMemorySpaceRepository

    ctx = ApplicationContext()
    assert isinstance(ctx.memory_space_repo, InMemoryMemorySpaceRepository)


def test_reset_replaces_memory_space_repo_with_fresh_instance() -> None:
    """After reset(), memory_space_repo should be a new empty instance."""
    from memorable.core.context import ApplicationContext

    ctx = ApplicationContext()
    ctx.memory_space_repo.create_space("test-space")
    assert ctx.memory_space_repo.exists("test-space")

    ctx.reset()
    assert not ctx.memory_space_repo.exists("test-space")


def test_constructor_injection_of_memory_space_repo() -> None:
    """Passing a custom MemorySpaceRepository makes it available on the context."""
    from memorable.core.context import ApplicationContext
    from memorable.core.repositories import InMemoryMemorySpaceRepository

    custom_repo = InMemoryMemorySpaceRepository()
    custom_repo.create_space("injected-space")

    ctx = ApplicationContext(memory_space_repo=custom_repo)
    assert ctx.memory_space_repo is custom_repo
    assert ctx.memory_space_repo.exists("injected-space")


def test_cli_init_twice_reports_already_exists(tmp_path: object) -> None:
    """Running init twice on the same space reports 'already exists' the second time.

    This proves the CLI init command uses a shared repository (via
    ApplicationContext) rather than a throwaway one.
    """
    import json
    from pathlib import Path

    from memorable.core.context import default_context

    tmp = Path(str(tmp_path))

    # Set up a .memorable/memory.yaml in a temp directory
    memorable_dir = tmp / ".memorable"
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

    from memorable.cli import main
    from io import StringIO
    import sys

    # First init
    old_stdout = sys.stdout
    sys.stdout = captured = StringIO()
    try:
        rc1 = main(["init", "--path", str(tmp)])
    finally:
        sys.stdout = old_stdout
    first_output = json.loads(captured.getvalue())

    assert rc1 == 0
    assert first_output["status"] == "initialized"

    # Second init -- should report "already exists"
    sys.stdout = captured2 = StringIO()
    try:
        rc2 = main(["init", "--path", str(tmp)])
    finally:
        sys.stdout = old_stdout
    second_output = json.loads(captured2.getvalue())

    assert rc2 == 0
    assert second_output["status"] == "already exists"

    # Clean up: reset context to avoid leaking state to other tests
    default_context.reset()
