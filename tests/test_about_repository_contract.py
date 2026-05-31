"""Contract tests for AboutRepository implementations."""

from __future__ import annotations

import uuid

import pytest


def _unique_space() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def inmemory_about_repo():
    from memorable.core.repositories import InMemoryAboutRepository

    return InMemoryAboutRepository()


ALL_REPOS = ["inmemory_about_repo"]


def test_about_repository_port_methods() -> None:
    from memorable.core.ports import AboutRepository

    methods = {name for name in vars(AboutRepository) if not name.startswith("_")}
    assert methods == {
        "link",
        "unlink",
        "entities_for_record",
        "records_for_entity",
    }


def test_application_context_wires_inmemory_about_repository() -> None:
    from memorable.core.context import ApplicationContext
    from memorable.core.repositories import InMemoryAboutRepository

    ctx = ApplicationContext()

    assert isinstance(ctx.about_repo, InMemoryAboutRepository)


def test_application_context_reset_replaces_about_repository() -> None:
    from memorable.core.context import ApplicationContext

    ctx = ApplicationContext()
    ctx.about_repo.link("space", "decision:1", ["entity:1"])

    ctx.reset()

    assert ctx.about_repo.entities_for_record("space", "decision:1") == []


class TestAboutRepositoryContract:
    """About links are observable through both directional queries."""

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_link_record_to_entity(self, repo_fixture, request) -> None:
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()

        repo.link(space, "decision:1", ["entity:build-2"])

        assert repo.entities_for_record(space, "decision:1") == ["entity:build-2"]
        assert repo.records_for_entity(space, "entity:build-2") == ["decision:1"]

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_record_can_link_to_many_entities(self, repo_fixture, request) -> None:
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()

        repo.link(space, "observation:1", ["entity:phase", "entity:workout"])

        assert repo.entities_for_record(space, "observation:1") == [
            "entity:phase",
            "entity:workout",
        ]

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_many_records_can_link_to_one_entity(self, repo_fixture, request) -> None:
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()

        repo.link(space, "decision:1", ["entity:build-2"])
        repo.link(space, "task:1", ["entity:build-2"])

        assert repo.records_for_entity(space, "entity:build-2") == [
            "decision:1",
            "task:1",
        ]

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_queries_are_scoped_to_memory_space(self, repo_fixture, request) -> None:
        repo = request.getfixturevalue(repo_fixture)

        repo.link("space-a", "decision:1", ["entity:build-2"])
        repo.link("space-b", "decision:1", ["entity:build-2"])

        assert repo.entities_for_record("space-a", "decision:1") == [
            "entity:build-2"
        ]
        assert repo.records_for_entity("space-a", "entity:build-2") == [
            "decision:1"
        ]

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_unlink_hard_removes_record_edges(self, repo_fixture, request) -> None:
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()

        repo.link(space, "decision:1", ["entity:build-2", "entity:phase"])
        repo.link(space, "decision:2", ["entity:build-2"])

        repo.unlink(space, "decision:1")

        assert repo.entities_for_record(space, "decision:1") == []
        assert repo.records_for_entity(space, "entity:phase") == []
        assert repo.records_for_entity(space, "entity:build-2") == ["decision:2"]
