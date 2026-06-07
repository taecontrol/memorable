"""Tests for generic InvalidateService and lifecycle invalidation.

Covers slice #45 acceptance criteria:
- invalidate() method on TemporalRecordRepository protocol
- InMemoryDecisionRepository.invalidate() implemented
- InMemoryObservationRepository.invalidate() implemented
- InvalidateService operates on any TemporalRecordRepository
- Rejects already-invalidated records with ValueError
- Sets lifecycle_state = "invalidated" and invalidation_time
- memorable_invalidate MCP tool registered and working
- memorable invalidate CLI command registered and working
- Tests verify invalidation works for both Decision and Observation
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

# --- Fixture data ---

FIXTURE_TIMESTAMP = datetime(2026, 5, 25, 9, 0, 0, tzinfo=UTC)
INVALIDATION_TIMESTAMP = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)

DECISION_ID = "decision:storage-path:v1"
OBSERVATION_ID = "observation:team-comm:v1"
SOURCE_ID = "source:agent-session"

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


class TestTemporalRecordRepositoryInvalidate:
    """TemporalRecordRepository protocol defines invalidate()."""

    def test_protocol_defines_invalidate(self) -> None:
        """Protocol declares an invalidate() method."""
        from memorable.core.ports import TemporalRecordRepository

        protocol_methods = {
            name for name in dir(TemporalRecordRepository) if not name.startswith("_")
        }
        assert "invalidate" in protocol_methods


# =====================================================================
# InMemoryDecisionRepository.invalidate() tests
# =====================================================================


class TestInMemoryDecisionRepositoryInvalidate:
    """InMemoryDecisionRepository.invalidate() marks a Decision as invalidated."""

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

    def test_invalidate_sets_lifecycle_state(self) -> None:
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        self._store_decision(repo)

        repo.invalidate(
            space="memorable",
            record_id=DECISION_ID,
            invalidation_time=INVALIDATION_TIMESTAMP,
        )

        updated = repo.get(space="memorable", record_id=DECISION_ID)
        assert updated is not None
        assert updated.lifecycle_state == "invalidated"

    def test_invalidate_sets_invalidation_time(self) -> None:
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        self._store_decision(repo)

        repo.invalidate(
            space="memorable",
            record_id=DECISION_ID,
            invalidation_time=INVALIDATION_TIMESTAMP,
        )

        updated = repo.get(space="memorable", record_id=DECISION_ID)
        assert updated is not None
        assert updated.invalidation_time == INVALIDATION_TIMESTAMP

    def test_invalidate_preserves_other_fields(self) -> None:
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        self._store_decision(repo)

        repo.invalidate(
            space="memorable",
            record_id=DECISION_ID,
            invalidation_time=INVALIDATION_TIMESTAMP,
        )

        updated = repo.get(space="memorable", record_id=DECISION_ID)
        assert updated is not None
        assert updated.id == DECISION_ID
        assert updated.statement == "Use Graphiti for storage."
        assert updated.space == "memorable"
        assert updated.superseded_by is None


# =====================================================================
# InMemoryObservationRepository.invalidate() tests
# =====================================================================


class TestInMemoryObservationRepositoryInvalidate:
    """InMemoryObservationRepository.invalidate() marks Observation as invalidated."""

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

    def test_invalidate_sets_lifecycle_state(self) -> None:
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        self._store_observation(repo)

        repo.invalidate(
            space="memorable",
            record_id=OBSERVATION_ID,
            invalidation_time=INVALIDATION_TIMESTAMP,
        )

        updated = repo.get(space="memorable", record_id=OBSERVATION_ID)
        assert updated is not None
        assert updated.lifecycle_state == "invalidated"

    def test_invalidate_sets_invalidation_time(self) -> None:
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        self._store_observation(repo)

        repo.invalidate(
            space="memorable",
            record_id=OBSERVATION_ID,
            invalidation_time=INVALIDATION_TIMESTAMP,
        )

        updated = repo.get(space="memorable", record_id=OBSERVATION_ID)
        assert updated is not None
        assert updated.invalidation_time == INVALIDATION_TIMESTAMP


# =====================================================================
# InvalidateService tests
# =====================================================================


class TestInvalidateServiceWithDecision:
    """InvalidateService invalidates a Decision through TemporalRecordRepository."""

    def _setup(self):
        from memorable.core.application import (
            InvalidateService,
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

        return InvalidateService(repository=repo), repo

    def test_invalidate_sets_lifecycle_state_and_time(self) -> None:
        service, repo = self._setup()

        result = service.invalidate(
            space="memorable",
            record_id=DECISION_ID,
            at=INVALIDATION_TIMESTAMP,
        )

        assert result.record_id == DECISION_ID
        assert result.lifecycle_state == "invalidated"
        assert result.invalidation_time == INVALIDATION_TIMESTAMP

        # Verify in repository
        stored = repo.get(space="memorable", record_id=DECISION_ID)
        assert stored is not None
        assert stored.lifecycle_state == "invalidated"
        assert stored.invalidation_time == INVALIDATION_TIMESTAMP

    def test_invalidate_rejects_missing_record(self) -> None:
        service, _repo = self._setup()

        with pytest.raises(ValueError, match="not found"):
            service.invalidate(
                space="memorable",
                record_id="decision:missing",
                at=INVALIDATION_TIMESTAMP,
            )

    def test_invalidate_rejects_already_invalidated(self) -> None:
        service, _repo = self._setup()

        service.invalidate(
            space="memorable",
            record_id=DECISION_ID,
            at=INVALIDATION_TIMESTAMP,
        )

        with pytest.raises(ValueError, match="already invalidated"):
            service.invalidate(
                space="memorable",
                record_id=DECISION_ID,
                at=INVALIDATION_TIMESTAMP,
            )


class TestInvalidateServiceWithObservation:
    """InvalidateService invalidates an Observation through TemporalRecordRepository."""

    def _setup(self):
        from memorable.core.application import (
            InvalidateService,
            RememberObservationService,
        )
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

        return InvalidateService(repository=repo), repo

    def test_invalidate_observation(self) -> None:
        service, repo = self._setup()

        result = service.invalidate(
            space="memorable",
            record_id=OBSERVATION_ID,
            at=INVALIDATION_TIMESTAMP,
        )

        assert result.record_id == OBSERVATION_ID
        assert result.lifecycle_state == "invalidated"

        stored = repo.get(space="memorable", record_id=OBSERVATION_ID)
        assert stored is not None
        assert stored.lifecycle_state == "invalidated"
        assert stored.invalidation_time == INVALIDATION_TIMESTAMP

    def test_invalidate_observation_rejects_already_invalidated(self) -> None:
        service, _repo = self._setup()

        service.invalidate(
            space="memorable",
            record_id=OBSERVATION_ID,
            at=INVALIDATION_TIMESTAMP,
        )

        with pytest.raises(ValueError, match="already invalidated"):
            service.invalidate(
                space="memorable",
                record_id=OBSERVATION_ID,
                at=INVALIDATION_TIMESTAMP,
            )


# =====================================================================
# MCP tool tests
# =====================================================================


class TestMCPInvalidateTool:
    """MCP memorable_invalidate tool marks any temporal record as invalidated."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_invalidate_decision_via_mcp(self) -> None:
        from memorable.mcp.server import invalidate_tool, remember_decision_tool

        remember_decision_tool(
            space="memorable",
            decision_id=DECISION_ID,
            statement="Use Graphiti for storage.",
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )

        result = invalidate_tool(
            space="memorable",
            record_id=DECISION_ID,
            record_kind="decision",
            at="2026-05-25T10:00:00Z",
        )

        assert "error" not in result
        assert result["record_id"] == DECISION_ID
        assert result["lifecycle_state"] == "invalidated"

    def test_invalidate_observation_via_mcp(self) -> None:
        from memorable.mcp.server import invalidate_tool, remember_observation_tool

        remember_observation_tool(
            space="memorable",
            observation_id=OBSERVATION_ID,
            statement="The team prefers async communication.",
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )

        result = invalidate_tool(
            space="memorable",
            record_id=OBSERVATION_ID,
            record_kind="observation",
            at="2026-05-25T10:00:00Z",
        )

        assert "error" not in result
        assert result["record_id"] == OBSERVATION_ID
        assert result["lifecycle_state"] == "invalidated"

    def test_invalidate_rejects_already_invalidated_via_mcp(self) -> None:
        from memorable.mcp.server import invalidate_tool, remember_decision_tool

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
            record_kind="decision",
            at="2026-05-25T10:00:00Z",
        )

        result = invalidate_tool(
            space="memorable",
            record_id=DECISION_ID,
            record_kind="decision",
            at="2026-05-25T10:00:00Z",
        )

        assert "error" in result
        assert "already invalidated" in result["error"]

    def test_invalidate_unknown_record_kind(self) -> None:
        from memorable.mcp.server import invalidate_tool

        result = invalidate_tool(
            space="memorable",
            record_id="something:v1",
            record_kind="unknown",
            at="2026-05-25T10:00:00Z",
        )

        assert "error" in result
        assert "Unknown record_kind" in result["error"]


# =====================================================================
# CLI command tests
# =====================================================================


@pytest.mark.usefixtures("cli_in_memory_context")
class TestCLIInvalidateCommand:
    """CLI `memorable invalidate` marks a temporal record as invalidated."""

    def test_invalidate_decision_command(self, capsys) -> None:
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
                "invalidate",
                "--space",
                "memorable",
                "--id",
                DECISION_ID,
                "--record-kind",
                "decision",
                "--at",
                "2026-05-25T10:00:00Z",
            ]
        )

        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["record_id"] == DECISION_ID
        assert output["lifecycle_state"] == "invalidated"

    def test_invalidate_observation_command(self, capsys) -> None:
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
                "invalidate",
                "--space",
                "memorable",
                "--id",
                OBSERVATION_ID,
                "--record-type",
                "observation",
                "--at",
                "2026-05-25T10:00:00Z",
            ]
        )

        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["record_id"] == OBSERVATION_ID
        assert output["lifecycle_state"] == "invalidated"

    def test_invalidate_rejects_already_invalidated(self, capsys) -> None:
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

        assert exit_code == 1
        stderr = capsys.readouterr().err
        assert "already invalidated" in stderr
