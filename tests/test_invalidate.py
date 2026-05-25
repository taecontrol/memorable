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

        updated = repo.get(space="memorable", decision_id=DECISION_ID)
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

        updated = repo.get(space="memorable", decision_id=DECISION_ID)
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

        updated = repo.get(space="memorable", decision_id=DECISION_ID)
        assert updated is not None
        assert updated.id == DECISION_ID
        assert updated.statement == "Use Graphiti for storage."
        assert updated.space == "memorable"
        assert updated.superseded_by is None


# =====================================================================
# InMemoryObservationRepository.invalidate() tests
# =====================================================================


class TestInMemoryObservationRepositoryInvalidate:
    """InMemoryObservationRepository.invalidate() marks an Observation as invalidated."""

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

        updated = repo.get(space="memorable", observation_id=OBSERVATION_ID)
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

        updated = repo.get(space="memorable", observation_id=OBSERVATION_ID)
        assert updated is not None
        assert updated.invalidation_time == INVALIDATION_TIMESTAMP
