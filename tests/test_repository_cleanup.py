"""Tests that verify repository module cleanup and protocol contracts.

- The dead-code factory ``make_memory_space_repository`` is removed.
- Repository protocols expose only clean CRUD-style methods.
"""

from __future__ import annotations


def _public_methods(cls: type) -> set[str]:
    return {name for name in vars(cls) if not name.startswith("_")}


def test_make_memory_space_repository_is_not_importable() -> None:
    """The factory function must not exist in the public API."""
    import importlib

    mod = importlib.import_module("memorable.core.repositories")
    assert not hasattr(mod, "make_memory_space_repository"), (
        "make_memory_space_repository should have been removed from "
        "memorable.core.repositories"
    )


def test_decision_repository_protocol_methods() -> None:
    from memorable.core.ports import DecisionRepository

    expected = {"save", "get", "get_provenance", "list_by_space", "mark_superseded"}
    assert _public_methods(DecisionRepository) == expected


def test_task_repository_protocol_methods() -> None:
    from memorable.core.ports import TaskRepository

    expected = {"save", "get", "get_provenance", "list_by_space", "complete"}
    assert _public_methods(TaskRepository) == expected


def test_entity_repository_protocol_methods() -> None:
    from memorable.core.ports import EntityRepository

    expected = {"save", "get", "get_provenance", "list_by_space"}
    assert _public_methods(EntityRepository) == expected


def test_memory_space_repository_protocol_methods() -> None:
    from memorable.core.ports import MemorySpaceRepository

    expected = {"create_space", "get_space", "exists"}
    assert _public_methods(MemorySpaceRepository) == expected
