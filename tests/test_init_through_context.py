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
