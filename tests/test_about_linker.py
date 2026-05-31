"""Tests for AboutLinker and record write integration."""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime

import pytest

AT = datetime(2026, 5, 31, 9, 0, tzinfo=UTC)

PROFILE_YAML = textwrap.dedent("""\
    version: 1
    space:
      name: memorable
    entities:
      - name: Project
      - name: Component
    records: []
""")


def _about_linker():
    from memorable.core.application import AboutLinker, RememberEntityService
    from memorable.core.profile import load_profile_from_yaml
    from memorable.core.repositories import (
        InMemoryAboutRepository,
        InMemoryEntityRepository,
    )

    profile = load_profile_from_yaml(PROFILE_YAML)
    entity_repo = InMemoryEntityRepository()
    about_repo = InMemoryAboutRepository()
    entity_service = RememberEntityService(repository=entity_repo, profile=profile)
    linker = AboutLinker(entity_repo=entity_repo, about_repo=about_repo)
    return linker, about_repo, entity_service, profile


def _remember_entity(
    entity_service,
    entity_id: str,
    entity_type: str = "Project",
) -> None:
    entity_service.remember(
        space="memorable",
        entity_id=entity_id,
        entity_type=entity_type,
        name=entity_id,
        source_id="source:test",
        at=AT,
    )


class TestAboutLinker:
    def test_links_record_to_existing_entity(self) -> None:
        linker, about_repo, entity_service, _profile = _about_linker()
        _remember_entity(entity_service, "entity:build-2")

        linker.link(
            space="memorable",
            record_id="decision:build-2",
            entity_ids=["entity:build-2"],
        )

        assert about_repo.entities_for_record("memorable", "decision:build-2") == [
            "entity:build-2"
        ]
        assert about_repo.records_for_entity("memorable", "entity:build-2") == [
            "decision:build-2"
        ]

    def test_links_record_to_many_entities(self) -> None:
        linker, about_repo, entity_service, _profile = _about_linker()
        _remember_entity(entity_service, "entity:phase")
        _remember_entity(entity_service, "entity:workout", entity_type="Component")

        linker.link(
            space="memorable",
            record_id="observation:session",
            entity_ids=["entity:phase", "entity:workout"],
        )

        assert about_repo.entities_for_record("memorable", "observation:session") == [
            "entity:phase",
            "entity:workout",
        ]

    def test_missing_entity_fails_loud_with_no_partial_edges(self) -> None:
        linker, about_repo, entity_service, _profile = _about_linker()
        _remember_entity(entity_service, "entity:known")

        with pytest.raises(ValueError, match="Entity 'entity:missing' not found"):
            linker.link(
                space="memorable",
                record_id="decision:partial",
                entity_ids=["entity:known", "entity:missing"],
            )

        assert about_repo.entities_for_record("memorable", "decision:partial") == []
        assert about_repo.records_for_entity("memorable", "entity:known") == []

    def test_restaple_hard_removes_prior_edges_then_adds_new_edges(self) -> None:
        linker, about_repo, entity_service, _profile = _about_linker()
        _remember_entity(entity_service, "entity:wrong")
        _remember_entity(entity_service, "entity:right")

        linker.link(
            space="memorable",
            record_id="task:stapled",
            entity_ids=["entity:wrong"],
        )
        linker.restaple(
            space="memorable",
            record_id="task:stapled",
            entity_ids=["entity:right"],
        )

        assert about_repo.entities_for_record("memorable", "task:stapled") == [
            "entity:right"
        ]
        assert about_repo.records_for_entity("memorable", "entity:wrong") == []


class TestRememberServicesAbout:
    def test_remember_decision_writes_about_edges(self) -> None:
        from memorable.core.application import RememberDecisionService
        from memorable.core.repositories import InMemoryDecisionRepository

        linker, about_repo, entity_service, profile = _about_linker()
        _remember_entity(entity_service, "entity:build-2")
        decision_repo = InMemoryDecisionRepository()
        service = RememberDecisionService(
            repository=decision_repo,
            profile=profile,
            about_linker=linker,
        )

        service.remember(
            space="memorable",
            decision_id="decision:about-build-2",
            statement="Use Build 2.",
            source_id="source:test",
            at=AT,
            about=["entity:build-2"],
        )

        assert decision_repo.get("memorable", "decision:about-build-2") is not None
        assert about_repo.entities_for_record(
            "memorable", "decision:about-build-2"
        ) == ["entity:build-2"]

    def test_remember_decision_missing_about_entity_writes_no_record(self) -> None:
        from memorable.core.application import RememberDecisionService
        from memorable.core.repositories import InMemoryDecisionRepository

        linker, about_repo, entity_service, profile = _about_linker()
        _remember_entity(entity_service, "entity:known")
        decision_repo = InMemoryDecisionRepository()
        service = RememberDecisionService(
            repository=decision_repo,
            profile=profile,
            about_linker=linker,
        )

        with pytest.raises(ValueError, match="Entity 'entity:missing' not found"):
            service.remember(
                space="memorable",
                decision_id="decision:partial",
                statement="About a missing Entity.",
                source_id="source:test",
                at=AT,
                about=["entity:known", "entity:missing"],
            )

        assert decision_repo.get("memorable", "decision:partial") is None
        assert about_repo.entities_for_record("memorable", "decision:partial") == []

    def test_remember_observation_writes_about_edges(self) -> None:
        from memorable.core.application import RememberObservationService
        from memorable.core.repositories import InMemoryObservationRepository

        linker, about_repo, entity_service, profile = _about_linker()
        _remember_entity(entity_service, "entity:device")
        observation_repo = InMemoryObservationRepository()
        service = RememberObservationService(
            repository=observation_repo,
            profile=profile,
            about_linker=linker,
        )

        service.remember(
            space="memorable",
            observation_id="observation:device",
            statement="Device warmed up quickly.",
            source_id="source:test",
            at=AT,
            about=["entity:device"],
        )

        assert observation_repo.get("memorable", "observation:device") is not None
        assert about_repo.entities_for_record("memorable", "observation:device") == [
            "entity:device"
        ]

    def test_remember_observation_missing_about_entity_writes_no_record(self) -> None:
        from memorable.core.application import RememberObservationService
        from memorable.core.repositories import InMemoryObservationRepository

        linker, about_repo, entity_service, profile = _about_linker()
        _remember_entity(entity_service, "entity:known")
        observation_repo = InMemoryObservationRepository()
        service = RememberObservationService(
            repository=observation_repo,
            profile=profile,
            about_linker=linker,
        )

        with pytest.raises(ValueError, match="Entity 'entity:missing' not found"):
            service.remember(
                space="memorable",
                observation_id="observation:partial",
                statement="About a missing Entity.",
                source_id="source:test",
                at=AT,
                about=["entity:known", "entity:missing"],
            )

        assert observation_repo.get("memorable", "observation:partial") is None
        assert about_repo.entities_for_record("memorable", "observation:partial") == []

    def test_remember_task_writes_about_edges(self) -> None:
        from memorable.core.application import RememberTaskService
        from memorable.core.repositories import InMemoryTaskRepository

        linker, about_repo, entity_service, profile = _about_linker()
        _remember_entity(entity_service, "entity:build-2")
        task_repo = InMemoryTaskRepository()
        service = RememberTaskService(
            repository=task_repo,
            profile=profile,
            about_linker=linker,
        )

        service.remember(
            space="memorable",
            task_id="task:build-2",
            title="Inspect Build 2.",
            source_id="source:test",
            at=AT,
            about=["entity:build-2"],
        )

        assert task_repo.get(space="memorable", task_id="task:build-2") is not None
        assert about_repo.entities_for_record("memorable", "task:build-2") == [
            "entity:build-2"
        ]

    def test_remember_task_missing_about_entity_writes_no_record(self) -> None:
        from memorable.core.application import RememberTaskService
        from memorable.core.repositories import InMemoryTaskRepository

        linker, about_repo, entity_service, profile = _about_linker()
        _remember_entity(entity_service, "entity:known")
        task_repo = InMemoryTaskRepository()
        service = RememberTaskService(
            repository=task_repo,
            profile=profile,
            about_linker=linker,
        )

        with pytest.raises(ValueError, match="Entity 'entity:missing' not found"):
            service.remember(
                space="memorable",
                task_id="task:partial",
                title="About a missing Entity.",
                source_id="source:test",
                at=AT,
                about=["entity:known", "entity:missing"],
            )

        assert task_repo.get(space="memorable", task_id="task:partial") is None
        assert about_repo.entities_for_record("memorable", "task:partial") == []

    def test_omitting_about_writes_no_edges(self) -> None:
        from memorable.core.application import RememberDecisionService
        from memorable.core.repositories import InMemoryDecisionRepository

        linker, about_repo, _entity_service, profile = _about_linker()
        service = RememberDecisionService(
            repository=InMemoryDecisionRepository(),
            profile=profile,
            about_linker=linker,
        )

        service.remember(
            space="memorable",
            decision_id="decision:no-about",
            statement="No entity applies.",
            source_id="source:test",
            at=AT,
        )

        assert about_repo.entities_for_record("memorable", "decision:no-about") == []


class TestMCPRememberToolsAbout:
    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_remember_decision_tool_writes_about_edges(self) -> None:
        from memorable.core.context import default_context
        from memorable.mcp.server import remember_decision_tool, remember_entity_tool

        remember_entity_tool(
            space="memorable",
            entity_id="entity:build-2",
            entity_type="Project",
            name="Build 2",
            source="source:test",
            at="2026-05-31T09:00:00Z",
        )

        result = remember_decision_tool(
            space="memorable",
            decision_id="decision:about-build-2",
            statement="Use Build 2.",
            source="source:test",
            at="2026-05-31T09:01:00Z",
            about=["entity:build-2"],
        )

        assert "error" not in result
        assert default_context.about_repo.entities_for_record(
            "memorable", "decision:about-build-2"
        ) == ["entity:build-2"]

    def test_remember_observation_tool_writes_about_edges(self) -> None:
        from memorable.core.context import default_context
        from memorable.mcp.server import remember_entity_tool, remember_observation_tool

        remember_entity_tool(
            space="memorable",
            entity_id="entity:device",
            entity_type="Component",
            name="Device",
            source="source:test",
            at="2026-05-31T09:00:00Z",
        )

        result = remember_observation_tool(
            space="memorable",
            observation_id="observation:device",
            statement="Device warmed up quickly.",
            source="source:test",
            at="2026-05-31T09:01:00Z",
            about=["entity:device"],
        )

        assert "error" not in result
        assert default_context.about_repo.entities_for_record(
            "memorable", "observation:device"
        ) == ["entity:device"]

    def test_remember_task_tool_writes_about_edges(self) -> None:
        from memorable.core.context import default_context
        from memorable.mcp.server import remember_entity_tool, remember_task_tool

        remember_entity_tool(
            space="memorable",
            entity_id="entity:build-2",
            entity_type="Project",
            name="Build 2",
            source="source:test",
            at="2026-05-31T09:00:00Z",
        )

        result = remember_task_tool(
            space="memorable",
            task_id="task:build-2",
            title="Inspect Build 2.",
            source="source:test",
            at="2026-05-31T09:01:00Z",
            about=["entity:build-2"],
        )

        assert "error" not in result
        assert default_context.about_repo.entities_for_record(
            "memorable", "task:build-2"
        ) == ["entity:build-2"]

    def test_remember_decision_tool_missing_entity_fails_loud_without_edges(
        self,
    ) -> None:
        from memorable.core.context import default_context
        from memorable.mcp.server import remember_decision_tool, remember_entity_tool

        remember_entity_tool(
            space="memorable",
            entity_id="entity:known",
            entity_type="Project",
            name="Known",
            source="source:test",
            at="2026-05-31T09:00:00Z",
        )

        result = remember_decision_tool(
            space="memorable",
            decision_id="decision:partial",
            statement="About a missing Entity.",
            source="source:test",
            at="2026-05-31T09:01:00Z",
            about=["entity:known", "entity:missing"],
        )

        assert result == {
            "error": "About target Entity 'entity:missing' not found "
            "in MemorySpace 'memorable'. Create the Entity before "
            "linking a MemoryRecord to it."
        }
        assert (
            default_context.about_repo.entities_for_record(
                "memorable", "decision:partial"
            )
            == []
        )
        assert (
            default_context.about_repo.records_for_entity("memorable", "entity:known")
            == []
        )
        assert (
            default_context.decision_repo.get("memorable", "decision:partial") is None
        )
