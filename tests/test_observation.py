"""Tests for Observation record type with remember and supersession support.

Covers slice #44 acceptance criteria:
- Observation frozen dataclass with validation (empty id/statement rejected)
- ObservationRepository protocol and InMemoryObservationRepository
- RememberObservationService with profile validation (extends: Observation)
- Supersession wiring when supersedes is provided
- Generic temporal services work with ObservationRepository
- MCP tool and CLI command
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

# --- Fixture data ---

FIXTURE_TIMESTAMP_V1 = datetime(2026, 5, 25, 9, 0, 0, tzinfo=UTC)
FIXTURE_TIMESTAMP_V2 = datetime(2026, 5, 25, 9, 10, 0, tzinfo=UTC)

STATEMENT_V1 = "The team prefers async communication over synchronous meetings."
STATEMENT_V2 = (
    "The team prefers async communication but holds weekly sync standups."
)

V1_ID = "observation:team-comm:v1"
V2_ID = "observation:team-comm:v2"
SOURCE_ID = "source:agent-session"


# =====================================================================
# Domain model tests
# =====================================================================


class TestObservationModel:
    """Observation is a remembered assertion with temporal validity."""

    def test_observation_has_required_fields(self) -> None:
        from memorable.core.models import Observation

        obs = Observation(
            id=V1_ID,
            statement=STATEMENT_V1,
            space="memorable",
            validity_time=FIXTURE_TIMESTAMP_V1,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        assert obs.id == V1_ID
        assert obs.statement == STATEMENT_V1
        assert obs.space == "memorable"
        assert obs.validity_time == FIXTURE_TIMESTAMP_V1
        assert obs.invalidation_time is None
        assert obs.lifecycle_state == "current"
        assert obs.supersedes is None
        assert obs.superseded_by is None

    def test_observation_is_frozen(self) -> None:
        from memorable.core.models import Observation

        obs = Observation(
            id="observation:x",
            statement="X",
            space="s",
            validity_time=FIXTURE_TIMESTAMP_V1,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        with pytest.raises(AttributeError):
            obs.statement = "Y"  # type: ignore[misc]

    def test_observation_requires_non_empty_id(self) -> None:
        from memorable.core.models import Observation

        with pytest.raises(ValueError, match="id"):
            Observation(
                id="",
                statement="X",
                space="s",
                validity_time=FIXTURE_TIMESTAMP_V1,
                invalidation_time=None,
                lifecycle_state="current",
                supersedes=None,
                superseded_by=None,
            )

    def test_observation_requires_non_empty_statement(self) -> None:
        from memorable.core.models import Observation

        with pytest.raises(ValueError, match="statement"):
            Observation(
                id="observation:x",
                statement="",
                space="s",
                validity_time=FIXTURE_TIMESTAMP_V1,
                invalidation_time=None,
                lifecycle_state="current",
                supersedes=None,
                superseded_by=None,
            )


# =====================================================================
# Repository port tests
# =====================================================================


class TestObservationRepositoryPort:
    """ObservationRepository defines persistence for Observations."""

    def _make_observation_v1(self):
        from memorable.core.models import Observation, Provenance

        obs = Observation(
            id=V1_ID,
            statement=STATEMENT_V1,
            space="memorable",
            validity_time=FIXTURE_TIMESTAMP_V1,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        provenance = Provenance(
            record_id=V1_ID,
            record_kind="observation",
            source_id=SOURCE_ID,
            episode_id="episode:agent-session:2026-05-25T09:00:00+00:00",
            writer="agent:test",
            reason="initial observation",
            creation_time=FIXTURE_TIMESTAMP_V1,
            validity_time=FIXTURE_TIMESTAMP_V1,
        )
        return obs, provenance

    def _make_observation_v2(self):
        from memorable.core.models import Observation, Provenance

        obs = Observation(
            id=V2_ID,
            statement=STATEMENT_V2,
            space="memorable",
            validity_time=FIXTURE_TIMESTAMP_V2,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=V1_ID,
            superseded_by=None,
        )
        provenance = Provenance(
            record_id=V2_ID,
            record_kind="observation",
            source_id=SOURCE_ID,
            episode_id="episode:agent-session:2026-05-25T09:10:00+00:00",
            writer="agent:test",
            reason="superseding observation",
            creation_time=FIXTURE_TIMESTAMP_V2,
            validity_time=FIXTURE_TIMESTAMP_V2,
        )
        return obs, provenance

    def test_save_and_retrieve_observation(self) -> None:
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        obs, provenance = self._make_observation_v1()

        repo.save(obs, provenance)
        retrieved = repo.get(space="memorable", observation_id=V1_ID)

        assert retrieved is not None
        assert retrieved.id == V1_ID
        assert retrieved.statement == STATEMENT_V1

    def test_retrieve_provenance(self) -> None:
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        obs, provenance = self._make_observation_v1()

        repo.save(obs, provenance)
        prov = repo.get_provenance(space="memorable", observation_id=V1_ID)

        assert prov is not None
        assert prov.source_id == SOURCE_ID
        assert prov.record_kind == "observation"

    def test_get_returns_none_for_missing(self) -> None:
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        assert repo.get(space="memorable", observation_id="observation:missing") is None

    def test_get_provenance_returns_none_for_missing(self) -> None:
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        assert (
            repo.get_provenance(space="memorable", observation_id="observation:missing")
            is None
        )

    def test_list_by_space(self) -> None:
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        v1, prov1 = self._make_observation_v1()
        v2, prov2 = self._make_observation_v2()

        repo.save(v1, prov1)
        repo.save(v2, prov2)

        observations = repo.list_by_space("memorable")
        assert len(observations) == 2
        ids = {o.id for o in observations}
        assert ids == {V1_ID, V2_ID}

    def test_mark_superseded_updates_old_observation(self) -> None:
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        v1, prov1 = self._make_observation_v1()

        repo.save(v1, prov1)
        repo.mark_superseded(
            space="memorable",
            observation_id=V1_ID,
            superseded_by=V2_ID,
            invalidation_time=FIXTURE_TIMESTAMP_V2,
        )

        updated = repo.get(space="memorable", observation_id=V1_ID)
        assert updated is not None
        assert updated.lifecycle_state == "superseded"
        assert updated.invalidation_time == FIXTURE_TIMESTAMP_V2
        assert updated.superseded_by == V2_ID

    def test_append_first_v1_not_deleted(self) -> None:
        """Append-first: v1 not deleted, just marked superseded."""
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        v1, prov1 = self._make_observation_v1()
        v2, prov2 = self._make_observation_v2()

        repo.save(v1, prov1)
        repo.save(v2, prov2)
        repo.mark_superseded(
            space="memorable",
            observation_id=V1_ID,
            superseded_by=V2_ID,
            invalidation_time=FIXTURE_TIMESTAMP_V2,
        )

        v1_stored = repo.get(space="memorable", observation_id=V1_ID)
        assert v1_stored is not None
        assert v1_stored.lifecycle_state == "superseded"

        v2_stored = repo.get(space="memorable", observation_id=V2_ID)
        assert v2_stored is not None
        assert v2_stored.lifecycle_state == "current"

    def test_observation_repo_satisfies_temporal_record_protocol(self) -> None:
        """InMemoryObservationRepository satisfies TemporalRecordRepository."""
        from memorable.core.ports import TemporalRecordRepository
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        assert isinstance(repo, TemporalRecordRepository)
