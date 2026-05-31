"""Tests for generic CorrectService and correction lifecycle.

Covers slice #46 acceptance criteria:
- correct() method on TemporalRecordRepository protocol
- InMemoryDecisionRepository.correct() implemented
- InMemoryObservationRepository.correct() implemented
- CorrectService operates on any TemporalRecordRepository
- Rejects already-invalidated records with ValueError
- Updates statement in place, replaces provenance
- memorable_correct MCP tool registered and working
- memorable correct CLI command registered and working
- Tests verify correction works for both Decision and Observation
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

# --- Fixture data ---

FIXTURE_TIMESTAMP = datetime(2026, 5, 25, 9, 0, 0, tzinfo=UTC)
CORRECTION_TIMESTAMP = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)

DECISION_ID = "decision:storage-path:v1"
OBSERVATION_ID = "observation:team-comm:v1"
SOURCE_ID = "source:agent-session"
CORRECTION_SOURCE_ID = "source:human-review"

VALID_PROFILE_YAML = """\
version: 1

space:
  name: memorable
  description: Agent memory system

entities:
  - name: Project

records:
  - name: ArchitectureDecision
    extends: Decision
  - name: TeamObservation
    extends: Observation
"""


# =====================================================================
# Protocol tests
# =====================================================================


class TestTemporalRecordRepositoryCorrect:
    """TemporalRecordRepository protocol defines correct()."""

    def test_protocol_defines_correct(self) -> None:
        """Protocol declares a correct() method."""
        from memorable.core.ports import TemporalRecordRepository

        protocol_methods = {
            name for name in dir(TemporalRecordRepository) if not name.startswith("_")
        }
        assert "correct" in protocol_methods


# =====================================================================
# InMemoryDecisionRepository.correct() tests
# =====================================================================


class TestInMemoryDecisionRepositoryCorrect:
    """InMemoryDecisionRepository.correct() updates statement in place."""

    def _store_decision(self, repo):
        from memorable.core.models import Decision, Provenance

        decision = Decision(
            id=DECISION_ID,
            statement="Use Graphiti for storage.",
            space="memorable",
            validity_time=FIXTURE_TIMESTAMP,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        provenance = Provenance(
            record_id=DECISION_ID,
            record_kind="decision",
            source_id=SOURCE_ID,
            episode_id="episode:agent-session:2026-05-25T09:00:00+00:00",
            writer="agent:test",
            reason="test decision",
            creation_time=FIXTURE_TIMESTAMP,
            validity_time=FIXTURE_TIMESTAMP,
        )
        repo.save(decision, provenance)

    def test_correct_updates_statement(self) -> None:
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        self._store_decision(repo)

        repo.correct(
            space="memorable",
            record_id=DECISION_ID,
            new_statement="Use Neo4j for storage.",
        )

        updated = repo.get(space="memorable", record_id=DECISION_ID)
        assert updated is not None
        assert updated.statement == "Use Neo4j for storage."

    def test_correct_preserves_other_fields(self) -> None:
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        self._store_decision(repo)

        repo.correct(
            space="memorable",
            record_id=DECISION_ID,
            new_statement="Use Neo4j for storage.",
        )

        updated = repo.get(space="memorable", record_id=DECISION_ID)
        assert updated is not None
        assert updated.id == DECISION_ID
        assert updated.space == "memorable"
        assert updated.validity_time == FIXTURE_TIMESTAMP
        assert updated.invalidation_time is None
        assert updated.lifecycle_state == "current"
        assert updated.supersedes is None
        assert updated.superseded_by is None


# =====================================================================
# InMemoryObservationRepository.correct() tests
# =====================================================================


class TestInMemoryObservationRepositoryCorrect:
    """InMemoryObservationRepository.correct() updates statement in place."""

    def _store_observation(self, repo):
        from memorable.core.models import Observation, Provenance

        observation = Observation(
            id=OBSERVATION_ID,
            statement="The team prefers async communication.",
            space="memorable",
            validity_time=FIXTURE_TIMESTAMP,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        provenance = Provenance(
            record_id=OBSERVATION_ID,
            record_kind="observation",
            source_id=SOURCE_ID,
            episode_id="episode:agent-session:2026-05-25T09:00:00+00:00",
            writer="agent:test",
            reason="test observation",
            creation_time=FIXTURE_TIMESTAMP,
            validity_time=FIXTURE_TIMESTAMP,
        )
        repo.save(observation, provenance)

    def test_correct_updates_statement(self) -> None:
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        self._store_observation(repo)

        repo.correct(
            space="memorable",
            record_id=OBSERVATION_ID,
            new_statement="The team prefers synchronous communication.",
        )

        updated = repo.get(space="memorable", record_id=OBSERVATION_ID)
        assert updated is not None
        assert updated.statement == "The team prefers synchronous communication."

    def test_correct_preserves_other_fields(self) -> None:
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        self._store_observation(repo)

        repo.correct(
            space="memorable",
            record_id=OBSERVATION_ID,
            new_statement="The team prefers synchronous communication.",
        )

        updated = repo.get(space="memorable", record_id=OBSERVATION_ID)
        assert updated is not None
        assert updated.id == OBSERVATION_ID
        assert updated.space == "memorable"
        assert updated.validity_time == FIXTURE_TIMESTAMP
        assert updated.lifecycle_state == "current"


# =====================================================================
# FakeTemporalRecordRepository.correct() tests
# =====================================================================


class TestFakeTemporalRecordRepositoryCorrect:
    """FakeTemporalRecordRepository satisfies protocol with correct()."""

    def test_correct_updates_statement(self) -> None:
        from test_temporal_record_protocol import (
            FakeTemporalRecord,
            FakeTemporalRecordRepository,
        )

        repo = FakeTemporalRecordRepository()
        repo.put(
            FakeTemporalRecord(
                id="r1",
                space="s",
                statement="old value",
            )
        )

        repo.correct(space="s", record_id="r1", new_statement="new value")

        record = repo.get("s", "r1")
        assert record is not None
        assert record.statement == "new value"


# =====================================================================
# CorrectService tests — Decision
# =====================================================================


class TestCorrectServiceWithDecision:
    """CorrectService corrects a Decision through TemporalRecordRepository."""

    def _setup(self):
        from memorable.core.application import (
            RememberDecisionService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberDecisionService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            decision_id=DECISION_ID,
            statement="Use Graphiti for storage.",
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP,
        )

        return repo

    def test_correct_updates_statement_and_returns_result(self) -> None:
        from memorable.core.application import CorrectService

        repo = self._setup()
        service = CorrectService(repository=repo)

        result = service.correct(
            space="memorable",
            record_id=DECISION_ID,
            new_statement="Use Neo4j for storage.",
            record_kind="decision",
            source=CORRECTION_SOURCE_ID,
            writer="human:reviewer",
            at=CORRECTION_TIMESTAMP,
            reason="outdated docs",
        )

        assert result.record_id == DECISION_ID
        assert result.space == "memorable"
        assert result.new_statement == "Use Neo4j for storage."
        assert result.old_statement == "Use Graphiti for storage."

        # Verify repository was updated
        stored = repo.get(space="memorable", record_id=DECISION_ID)
        assert stored is not None
        assert stored.statement == "Use Neo4j for storage."
        # Original fields preserved
        assert stored.id == DECISION_ID
        assert stored.validity_time == FIXTURE_TIMESTAMP
        assert stored.lifecycle_state == "current"

    def test_correct_replaces_provenance_with_correction_reason(self) -> None:
        from memorable.core.application import CorrectService

        repo = self._setup()
        service = CorrectService(repository=repo)

        service.correct(
            space="memorable",
            record_id=DECISION_ID,
            new_statement="Use Neo4j for storage.",
            record_kind="decision",
            source=CORRECTION_SOURCE_ID,
            writer="human:reviewer",
            at=CORRECTION_TIMESTAMP,
            reason="outdated docs",
        )

        provenance = repo.get_provenance(
            space="memorable",
            record_id=DECISION_ID,
        )
        assert provenance is not None
        assert provenance.source_id == CORRECTION_SOURCE_ID
        assert provenance.writer == "human:reviewer"
        assert provenance.record_kind == "decision"
        assert "Corrected from: 'Use Graphiti for storage.'" in provenance.reason
        assert "outdated docs" in provenance.reason

    def test_correct_provenance_without_reason(self) -> None:
        from memorable.core.application import CorrectService

        repo = self._setup()
        service = CorrectService(repository=repo)

        service.correct(
            space="memorable",
            record_id=DECISION_ID,
            new_statement="Use Neo4j for storage.",
            record_kind="decision",
            source=CORRECTION_SOURCE_ID,
            writer="human:reviewer",
            at=CORRECTION_TIMESTAMP,
        )

        provenance = repo.get_provenance(
            space="memorable",
            record_id=DECISION_ID,
        )
        assert provenance is not None
        assert provenance.reason == "Corrected from: 'Use Graphiti for storage.'."

    def test_correct_rejects_missing_record(self) -> None:
        from memorable.core.application import CorrectService

        repo = self._setup()
        service = CorrectService(repository=repo)

        with pytest.raises(ValueError, match="not found"):
            service.correct(
                space="memorable",
                record_id="decision:missing",
                new_statement="anything",
                record_kind="decision",
                source=CORRECTION_SOURCE_ID,
                writer="human:reviewer",
                at=CORRECTION_TIMESTAMP,
            )

    def test_correct_rejects_invalidated_record(self) -> None:
        from memorable.core.application import CorrectService, InvalidateService

        repo = self._setup()

        # Invalidate first
        InvalidateService(repository=repo).invalidate(
            space="memorable",
            record_id=DECISION_ID,
            at=CORRECTION_TIMESTAMP,
        )

        service = CorrectService(repository=repo)

        with pytest.raises(ValueError, match="invalidated"):
            service.correct(
                space="memorable",
                record_id=DECISION_ID,
                new_statement="anything",
                record_kind="decision",
                source=CORRECTION_SOURCE_ID,
                writer="human:reviewer",
                at=CORRECTION_TIMESTAMP,
            )


# =====================================================================
# CorrectService tests — Observation
# =====================================================================


class TestCorrectServiceWithObservation:
    """CorrectService corrects an Observation through TemporalRecordRepository."""

    def _setup(self):
        from memorable.core.application import RememberObservationService
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberObservationService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            observation_id=OBSERVATION_ID,
            statement="The team prefers async communication.",
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP,
        )

        return repo

    def test_correct_observation(self) -> None:
        from memorable.core.application import CorrectService

        repo = self._setup()
        service = CorrectService(repository=repo)

        result = service.correct(
            space="memorable",
            record_id=OBSERVATION_ID,
            new_statement="The team prefers synchronous communication.",
            record_kind="observation",
            source=CORRECTION_SOURCE_ID,
            writer="human:reviewer",
            at=CORRECTION_TIMESTAMP,
            reason="misheard in meeting",
        )

        assert result.record_id == OBSERVATION_ID
        assert result.old_statement == "The team prefers async communication."
        assert result.new_statement == "The team prefers synchronous communication."

        stored = repo.get(space="memorable", record_id=OBSERVATION_ID)
        assert stored is not None
        assert stored.statement == "The team prefers synchronous communication."

    def test_correct_observation_replaces_provenance(self) -> None:
        from memorable.core.application import CorrectService

        repo = self._setup()
        service = CorrectService(repository=repo)

        service.correct(
            space="memorable",
            record_id=OBSERVATION_ID,
            new_statement="The team prefers synchronous communication.",
            record_kind="observation",
            source=CORRECTION_SOURCE_ID,
            writer="human:reviewer",
            at=CORRECTION_TIMESTAMP,
            reason="misheard in meeting",
        )

        provenance = repo.get_provenance(
            space="memorable",
            record_id=OBSERVATION_ID,
        )
        assert provenance is not None
        assert provenance.record_kind == "observation"
        assert provenance.source_id == CORRECTION_SOURCE_ID
        assert "Corrected from:" in provenance.reason
        assert "misheard in meeting" in provenance.reason

    def test_correct_observation_rejects_already_invalidated(self) -> None:
        from memorable.core.application import CorrectService, InvalidateService

        repo = self._setup()

        InvalidateService(repository=repo).invalidate(
            space="memorable",
            record_id=OBSERVATION_ID,
            at=CORRECTION_TIMESTAMP,
        )

        service = CorrectService(repository=repo)

        with pytest.raises(ValueError, match="invalidated"):
            service.correct(
                space="memorable",
                record_id=OBSERVATION_ID,
                new_statement="anything",
                record_kind="observation",
                source=CORRECTION_SOURCE_ID,
                writer="human:reviewer",
                at=CORRECTION_TIMESTAMP,
            )


# =====================================================================
# CorrectService tests — About re-staple
# =====================================================================


class TestCorrectServiceAboutRestaple:
    """CorrectService re-staples About edges through correction."""

    def _setup(self):
        from memorable.core.application import (
            AboutLinker,
            RememberDecisionService,
            RememberEntityService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryAboutRepository,
            InMemoryDecisionRepository,
            InMemoryEntityRepository,
        )

        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        decision_repo = InMemoryDecisionRepository()
        entity_repo = InMemoryEntityRepository()
        about_repo = InMemoryAboutRepository()
        about_linker = AboutLinker(entity_repo=entity_repo, about_repo=about_repo)
        entity_service = RememberEntityService(repository=entity_repo, profile=profile)

        for entity_id in ("entity:wrong", "entity:right", "entity:other"):
            entity_service.remember(
                space="memorable",
                entity_id=entity_id,
                entity_type="Project",
                name=entity_id,
                source_id=SOURCE_ID,
                at=FIXTURE_TIMESTAMP,
            )

        remember = RememberDecisionService(
            repository=decision_repo,
            profile=profile,
            about_linker=about_linker,
        )
        remember.remember(
            space="memorable",
            decision_id=DECISION_ID,
            statement="Use Graphiti for storage.",
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP,
            about=["entity:wrong"],
        )

        return decision_repo, about_repo, about_linker

    def test_correct_restaples_about_edges(self) -> None:
        from memorable.core.application import CorrectService

        repo, about_repo, about_linker = self._setup()
        service = CorrectService(repository=repo, about_linker=about_linker)

        service.correct(
            space="memorable",
            record_id=DECISION_ID,
            new_statement="Use Neo4j for storage.",
            record_kind="decision",
            source=CORRECTION_SOURCE_ID,
            writer="human:reviewer",
            at=CORRECTION_TIMESTAMP,
            about=["entity:right", "entity:other"],
        )

        assert about_repo.entities_for_record("memorable", DECISION_ID) == [
            "entity:other",
            "entity:right",
        ]
        assert about_repo.records_for_entity("memorable", "entity:wrong") == []

    def test_correct_without_about_leaves_edges_intact(self) -> None:
        from memorable.core.application import CorrectService

        repo, about_repo, about_linker = self._setup()
        service = CorrectService(repository=repo, about_linker=about_linker)

        service.correct(
            space="memorable",
            record_id=DECISION_ID,
            new_statement="Use Neo4j for storage.",
            record_kind="decision",
            source=CORRECTION_SOURCE_ID,
            writer="human:reviewer",
            at=CORRECTION_TIMESTAMP,
        )

        assert about_repo.entities_for_record("memorable", DECISION_ID) == [
            "entity:wrong"
        ]

    def test_correct_restaple_fails_loud_when_target_entity_is_missing(self) -> None:
        from memorable.core.application import CorrectService

        repo, about_repo, about_linker = self._setup()
        service = CorrectService(repository=repo, about_linker=about_linker)

        with pytest.raises(ValueError, match="Entity 'entity:missing' not found"):
            service.correct(
                space="memorable",
                record_id=DECISION_ID,
                new_statement="Use Neo4j for storage.",
                record_kind="decision",
                source=CORRECTION_SOURCE_ID,
                writer="human:reviewer",
                at=CORRECTION_TIMESTAMP,
                about=["entity:missing"],
            )

        assert about_repo.entities_for_record("memorable", DECISION_ID) == [
            "entity:wrong"
        ]


# =====================================================================
# MCP tool tests
# =====================================================================


class TestMCPCorrectTool:
    """MCP memorable_correct tool corrects any temporal record in place."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_correct_decision_via_mcp(self) -> None:
        from memorable.mcp.server import correct_tool, remember_decision_tool

        remember_decision_tool(
            space="memorable",
            decision_id=DECISION_ID,
            statement="Use Graphiti for storage.",
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )

        result = correct_tool(
            space="memorable",
            record_id=DECISION_ID,
            record_type="decision",
            new_statement="Use Neo4j for storage.",
            source=CORRECTION_SOURCE_ID,
            at="2026-05-25T10:00:00Z",
            reason="outdated docs",
        )

        assert "error" not in result
        assert result["record_id"] == DECISION_ID
        assert result["old_statement"] == "Use Graphiti for storage."
        assert result["new_statement"] == "Use Neo4j for storage."

    def test_correct_observation_via_mcp(self) -> None:
        from memorable.mcp.server import correct_tool, remember_observation_tool

        remember_observation_tool(
            space="memorable",
            observation_id=OBSERVATION_ID,
            statement="The team prefers async communication.",
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )

        result = correct_tool(
            space="memorable",
            record_id=OBSERVATION_ID,
            record_type="observation",
            new_statement="The team prefers synchronous communication.",
            source=CORRECTION_SOURCE_ID,
            at="2026-05-25T10:00:00Z",
        )

        assert "error" not in result
        assert result["record_id"] == OBSERVATION_ID
        assert result["new_statement"] == "The team prefers synchronous communication."

    def test_correct_rejects_already_invalidated_via_mcp(self) -> None:
        from memorable.mcp.server import (
            correct_tool,
            invalidate_tool,
            remember_decision_tool,
        )

        remember_decision_tool(
            space="memorable",
            decision_id=DECISION_ID,
            statement="Use Graphiti for storage.",
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )

        invalidate_tool(
            space="memorable",
            record_id=DECISION_ID,
            record_type="decision",
            at="2026-05-25T10:00:00Z",
        )

        result = correct_tool(
            space="memorable",
            record_id=DECISION_ID,
            record_type="decision",
            new_statement="anything",
            source=CORRECTION_SOURCE_ID,
            at="2026-05-25T10:00:00Z",
        )

        assert "error" in result
        assert "invalidated" in result["error"]

    def test_correct_custom_writer_appears_in_provenance(self) -> None:
        from memorable.core.context import default_context
        from memorable.mcp.server import correct_tool, remember_decision_tool

        remember_decision_tool(
            space="memorable",
            decision_id=DECISION_ID,
            statement="Use Graphiti for storage.",
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )

        result = correct_tool(
            space="memorable",
            record_id=DECISION_ID,
            record_type="decision",
            new_statement="Use Neo4j for storage.",
            source=CORRECTION_SOURCE_ID,
            at="2026-05-25T10:00:00Z",
            reason="outdated docs",
            writer="human:luis",
        )

        assert "error" not in result

        provenance = default_context.decision_repo.get_provenance(
            space="memorable",
            record_id=DECISION_ID,
        )
        assert provenance is not None
        assert provenance.writer == "human:luis"

    def test_correct_restaples_about_edges_via_mcp(self) -> None:
        from memorable.core.context import default_context
        from memorable.mcp.server import (
            correct_tool,
            remember_decision_tool,
            remember_entity_tool,
        )

        remember_entity_tool(
            space="memorable",
            entity_id="entity:wrong",
            entity_type="Project",
            name="Wrong",
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )
        remember_entity_tool(
            space="memorable",
            entity_id="entity:right",
            entity_type="Project",
            name="Right",
            source=SOURCE_ID,
            at="2026-05-25T09:01:00Z",
        )
        remember_decision_tool(
            space="memorable",
            decision_id=DECISION_ID,
            statement="Use Graphiti for storage.",
            source=SOURCE_ID,
            at="2026-05-25T09:02:00Z",
            about=["entity:wrong"],
        )

        result = correct_tool(
            space="memorable",
            record_id=DECISION_ID,
            record_type="decision",
            new_statement="Use Neo4j for storage.",
            source=CORRECTION_SOURCE_ID,
            at="2026-05-25T10:00:00Z",
            about=["entity:right"],
        )

        assert "error" not in result
        assert default_context.about_repo.entities_for_record(
            "memorable", DECISION_ID
        ) == ["entity:right"]
        assert (
            default_context.about_repo.records_for_entity("memorable", "entity:wrong")
            == []
        )

    def test_correct_about_missing_entity_fails_loud_via_mcp(self) -> None:
        from memorable.core.context import default_context
        from memorable.mcp.server import (
            correct_tool,
            remember_decision_tool,
            remember_entity_tool,
        )

        remember_entity_tool(
            space="memorable",
            entity_id="entity:wrong",
            entity_type="Project",
            name="Wrong",
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )
        remember_decision_tool(
            space="memorable",
            decision_id=DECISION_ID,
            statement="Use Graphiti for storage.",
            source=SOURCE_ID,
            at="2026-05-25T09:01:00Z",
            about=["entity:wrong"],
        )

        result = correct_tool(
            space="memorable",
            record_id=DECISION_ID,
            record_type="decision",
            new_statement="Use Neo4j for storage.",
            source=CORRECTION_SOURCE_ID,
            at="2026-05-25T10:00:00Z",
            about=["entity:missing"],
        )

        assert result == {
            "error": "About target Entity 'entity:missing' not found "
            "in MemorySpace 'memorable'. Create the Entity before "
            "linking a MemoryRecord to it."
        }
        assert default_context.about_repo.entities_for_record(
            "memorable", DECISION_ID
        ) == ["entity:wrong"]

    def test_correct_restaples_task_about_edges_via_mcp(self) -> None:
        from memorable.core.context import default_context
        from memorable.mcp.server import (
            correct_tool,
            remember_entity_tool,
            remember_task_tool,
        )

        remember_entity_tool(
            space="memorable",
            entity_id="entity:wrong",
            entity_type="Project",
            name="Wrong",
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )
        remember_entity_tool(
            space="memorable",
            entity_id="entity:right",
            entity_type="Project",
            name="Right",
            source=SOURCE_ID,
            at="2026-05-25T09:01:00Z",
        )
        remember_task_tool(
            space="memorable",
            task_id="task:about-correction",
            title="Verify About correction.",
            source=SOURCE_ID,
            at="2026-05-25T09:02:00Z",
            about=["entity:wrong"],
        )

        result = correct_tool(
            space="memorable",
            record_id="task:about-correction",
            record_type="task",
            new_statement="Verify About correction.",
            source=CORRECTION_SOURCE_ID,
            at="2026-05-25T10:00:00Z",
            writer="human:reviewer",
            about=["entity:right"],
        )

        assert "error" not in result
        assert default_context.about_repo.entities_for_record(
            "memorable", "task:about-correction"
        ) == ["entity:right"]
        assert (
            default_context.about_repo.records_for_entity("memorable", "entity:wrong")
            == []
        )
        provenance = default_context.task_repo.get_provenance(
            space="memorable",
            task_id="task:about-correction",
        )
        assert provenance is not None
        assert provenance.record_kind == "task"
        assert provenance.source_id == CORRECTION_SOURCE_ID
        assert provenance.writer == "human:reviewer"
        assert provenance.creation_time == CORRECTION_TIMESTAMP

    def test_correct_restaples_task_about_edges_without_new_statement_via_mcp(
        self,
    ) -> None:
        from memorable.core.context import default_context
        from memorable.mcp.server import (
            correct_tool,
            remember_entity_tool,
            remember_task_tool,
        )

        remember_entity_tool(
            space="memorable",
            entity_id="entity:wrong",
            entity_type="Project",
            name="Wrong",
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )
        remember_entity_tool(
            space="memorable",
            entity_id="entity:right",
            entity_type="Project",
            name="Right",
            source=SOURCE_ID,
            at="2026-05-25T09:01:00Z",
        )
        remember_task_tool(
            space="memorable",
            task_id="task:about-only",
            title="Verify About-only correction.",
            source=SOURCE_ID,
            at="2026-05-25T09:02:00Z",
            about=["entity:wrong"],
        )

        result = correct_tool(
            space="memorable",
            record_id="task:about-only",
            record_type="task",
            source=CORRECTION_SOURCE_ID,
            at="2026-05-25T10:00:00Z",
            about=["entity:right"],
        )

        assert "error" not in result
        assert result["old_statement"] == "Verify About-only correction."
        assert result["new_statement"] == "Verify About-only correction."
        assert default_context.about_repo.entities_for_record(
            "memorable", "task:about-only"
        ) == ["entity:right"]

    def test_correct_task_about_missing_entity_fails_loud_via_mcp(self) -> None:
        from memorable.core.context import default_context
        from memorable.mcp.server import (
            correct_tool,
            remember_entity_tool,
            remember_task_tool,
        )

        remember_entity_tool(
            space="memorable",
            entity_id="entity:wrong",
            entity_type="Project",
            name="Wrong",
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )
        remember_task_tool(
            space="memorable",
            task_id="task:about-correction",
            title="Verify About correction.",
            source=SOURCE_ID,
            at="2026-05-25T09:01:00Z",
            about=["entity:wrong"],
        )

        result = correct_tool(
            space="memorable",
            record_id="task:about-correction",
            record_type="task",
            new_statement="Verify About correction.",
            source=CORRECTION_SOURCE_ID,
            at="2026-05-25T10:00:00Z",
            about=["entity:missing"],
        )

        assert result == {
            "error": "About target Entity 'entity:missing' not found "
            "in MemorySpace 'memorable'. Create the Entity before "
            "linking a MemoryRecord to it."
        }
        assert default_context.about_repo.entities_for_record(
            "memorable", "task:about-correction"
        ) == ["entity:wrong"]

    def test_correct_unknown_record_type(self) -> None:
        from memorable.mcp.server import correct_tool

        result = correct_tool(
            space="memorable",
            record_id="something:v1",
            record_type="unknown",
            new_statement="anything",
            source=CORRECTION_SOURCE_ID,
            at="2026-05-25T10:00:00Z",
        )

        assert "error" in result
        assert "Unknown record_type" in result["error"]


# =====================================================================
# CLI command tests
# =====================================================================


@pytest.mark.usefixtures("cli_in_memory_context")
class TestCLICorrectCommand:
    """CLI `memorable correct` corrects a temporal record in place."""

    def test_correct_decision_command(self, capsys) -> None:
        import json

        from memorable.cli import main

        # Remember a decision first
        main(
            [
                "remember",
                "decision",
                "--space",
                "memorable",
                "--id",
                DECISION_ID,
                "--statement",
                "Use Graphiti for storage.",
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-25T09:00:00Z",
            ]
        )
        capsys.readouterr()  # clear output

        exit_code = main(
            [
                "correct",
                "--space",
                "memorable",
                "--id",
                DECISION_ID,
                "--record-type",
                "decision",
                "--new-statement",
                "Use Neo4j for storage.",
                "--source",
                CORRECTION_SOURCE_ID,
                "--at",
                "2026-05-25T10:00:00Z",
                "--reason",
                "outdated docs",
            ]
        )

        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["record_id"] == DECISION_ID
        assert output["new_statement"] == "Use Neo4j for storage."
        assert output["old_statement"] == "Use Graphiti for storage."

    def test_correct_observation_command(self, capsys) -> None:
        import json

        from memorable.cli import main

        # Remember an observation first
        main(
            [
                "remember",
                "observation",
                "--space",
                "memorable",
                "--id",
                OBSERVATION_ID,
                "--statement",
                "The team prefers async communication.",
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-25T09:00:00Z",
            ]
        )
        capsys.readouterr()  # clear output

        exit_code = main(
            [
                "correct",
                "--space",
                "memorable",
                "--id",
                OBSERVATION_ID,
                "--record-type",
                "observation",
                "--new-statement",
                "The team prefers synchronous communication.",
                "--source",
                CORRECTION_SOURCE_ID,
                "--at",
                "2026-05-25T10:00:00Z",
            ]
        )

        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["record_id"] == OBSERVATION_ID
        assert output["new_statement"] == "The team prefers synchronous communication."

    def test_correct_custom_writer_appears_in_provenance(
        self, cli_in_memory_context, capsys
    ) -> None:
        import json

        from memorable.cli import main

        # Remember a decision first
        main(
            [
                "remember",
                "decision",
                "--space",
                "memorable",
                "--id",
                DECISION_ID,
                "--statement",
                "Use Graphiti for storage.",
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-25T09:00:00Z",
            ]
        )
        capsys.readouterr()  # clear output

        exit_code = main(
            [
                "correct",
                "--space",
                "memorable",
                "--id",
                DECISION_ID,
                "--record-type",
                "decision",
                "--new-statement",
                "Use Neo4j for storage.",
                "--source",
                CORRECTION_SOURCE_ID,
                "--at",
                "2026-05-25T10:00:00Z",
                "--reason",
                "outdated docs",
                "--writer",
                "human:luis",
            ]
        )

        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["record_id"] == DECISION_ID

        # Verify provenance has the custom writer
        provenance = cli_in_memory_context.decision_repo.get_provenance(
            space="memorable",
            record_id=DECISION_ID,
        )
        assert provenance is not None
        assert provenance.writer == "human:luis"

    def test_correct_rejects_already_invalidated(self, capsys) -> None:
        from memorable.cli import main

        # Remember and invalidate a decision
        main(
            [
                "remember",
                "decision",
                "--space",
                "memorable",
                "--id",
                DECISION_ID,
                "--statement",
                "Use Graphiti for storage.",
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-25T09:00:00Z",
            ]
        )
        main(
            [
                "invalidate",
                "--space",
                "memorable",
                "--id",
                DECISION_ID,
                "--record-type",
                "decision",
                "--at",
                "2026-05-25T10:00:00Z",
            ]
        )
        capsys.readouterr()  # clear output

        exit_code = main(
            [
                "correct",
                "--space",
                "memorable",
                "--id",
                DECISION_ID,
                "--record-type",
                "decision",
                "--new-statement",
                "anything",
                "--source",
                CORRECTION_SOURCE_ID,
                "--at",
                "2026-05-25T10:00:00Z",
            ]
        )

        assert exit_code == 1
        stderr = capsys.readouterr().err
        assert "invalidated" in stderr
