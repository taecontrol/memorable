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


# =====================================================================
# ApplicationContext tests
# =====================================================================


class TestObservationInApplicationContext:
    """observation_repo is wired into ApplicationContext."""

    def test_context_has_observation_repo(self) -> None:
        from memorable.core.context import ApplicationContext

        ctx = ApplicationContext()
        assert hasattr(ctx, "observation_repo")
        assert ctx.observation_repo is not None

    def test_default_context_has_observation_repo(self) -> None:
        from memorable.core.context import default_context

        assert hasattr(default_context, "observation_repo")
        assert default_context.observation_repo is not None

    def test_reset_clears_observation_repo(self) -> None:
        from memorable.core.context import ApplicationContext
        from memorable.core.models import Observation, Provenance
        from memorable.core.repositories import InMemoryObservationRepository

        ctx = ApplicationContext()
        # Store something, then reset
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
        prov = Provenance(
            record_id=V1_ID,
            record_kind="observation",
            source_id=SOURCE_ID,
            episode_id="episode:test:2026-05-25T09:00:00+00:00",
            writer="agent:test",
            reason="test",
            creation_time=FIXTURE_TIMESTAMP_V1,
            validity_time=FIXTURE_TIMESTAMP_V1,
        )
        ctx.observation_repo.save(obs, prov)
        ctx.reset()
        assert ctx.observation_repo.get(space="memorable", observation_id=V1_ID) is None


# =====================================================================
# Application service tests
# =====================================================================

VALID_PROFILE_YAML = """\
version: 1

space:
  name: memorable
  description: Agent memory system

entities:
  - name: Project

records:
  - name: TeamObservation
    extends: Observation
"""


class TestRememberObservationService:
    """RememberObservationService validates and creates provenance."""

    def _make_service(self):
        from memorable.core.application import RememberObservationService
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        return (
            RememberObservationService(repository=repo, profile=profile),
            repo,
        )

    def test_remember_observation_stores_with_provenance(self) -> None:
        service, repo = self._make_service()

        result = service.remember(
            space="memorable",
            observation_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        assert result.observation.id == V1_ID
        assert result.observation.lifecycle_state == "current"
        assert result.provenance.source_id == SOURCE_ID
        assert result.provenance.record_kind == "observation"
        assert result.provenance.creation_time == FIXTURE_TIMESTAMP_V1

        stored = repo.get(space="memorable", observation_id=V1_ID)
        assert stored is not None

    def test_remember_observation_with_supersession(self) -> None:
        service, repo = self._make_service()

        # Remember v1
        service.remember(
            space="memorable",
            observation_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        # Remember v2, superseding v1
        result = service.remember(
            space="memorable",
            observation_id=V2_ID,
            statement=STATEMENT_V2,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V2,
            supersedes=V1_ID,
        )

        assert result.observation.id == V2_ID
        assert result.observation.supersedes == V1_ID
        assert result.observation.lifecycle_state == "current"

        # v1 should now be marked superseded
        v1 = repo.get(space="memorable", observation_id=V1_ID)
        assert v1 is not None
        assert v1.lifecycle_state == "superseded"
        assert v1.invalidation_time == FIXTURE_TIMESTAMP_V2
        assert v1.superseded_by == V2_ID

    def test_rejects_profile_without_observation_record(self) -> None:
        """Profile must have a record that extends Observation."""
        import textwrap

        from memorable.core.application import RememberObservationService
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryObservationRepository

        no_obs_yaml = textwrap.dedent("""\
            version: 1
            space:
              name: memorable
              description: test
            entities:
              - name: Project
            records:
              - name: ArchitectureDecision
                extends: Decision
        """)
        repo = InMemoryObservationRepository()
        profile = load_profile_from_yaml(no_obs_yaml)

        service = RememberObservationService(repository=repo, profile=profile)

        with pytest.raises(ValueError, match="Observation"):
            service.remember(
                space="memorable",
                observation_id="observation:x",
                statement="X",
                source_id="source:test",
                at=FIXTURE_TIMESTAMP_V1,
            )

    def test_remember_observation_sets_writer(self) -> None:
        service, _repo = self._make_service()

        result = service.remember(
            space="memorable",
            observation_id=V1_ID,
            statement="Test observation.",
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
            writer="agent:test-writer",
        )

        assert result.provenance.writer == "agent:test-writer"


# =====================================================================
# Temporal services with ObservationRepository
# =====================================================================


class TestCurrentTruthServiceWithObservation:
    """CurrentTruthService works with ObservationRepository."""

    def _setup_chain(self):
        from memorable.core.application import (
            CurrentTruthService,
            RememberObservationService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberObservationService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            observation_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )
        remember.remember(
            space="memorable",
            observation_id=V2_ID,
            statement=STATEMENT_V2,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V2,
            supersedes=V1_ID,
        )

        return CurrentTruthService(repository=repo), repo

    def test_current_truth_returns_superseding_observation(self) -> None:
        service, _repo = self._setup_chain()

        result = service.current(space="memorable", record_id=V1_ID)

        assert result is not None
        assert result.id == V2_ID

    def test_current_truth_returns_self_when_not_superseded(self) -> None:
        from memorable.core.application import (
            CurrentTruthService,
            RememberObservationService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberObservationService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            observation_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        service = CurrentTruthService(repository=repo)
        result = service.current(space="memorable", record_id=V1_ID)

        assert result is not None
        assert result.id == V1_ID


class TestPointInTimeTruthServiceWithObservation:
    """PointInTimeTruthService works with ObservationRepository."""

    def _setup_chain(self):
        from memorable.core.application import (
            PointInTimeTruthService,
            RememberObservationService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberObservationService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            observation_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )
        remember.remember(
            space="memorable",
            observation_id=V2_ID,
            statement=STATEMENT_V2,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V2,
            supersedes=V1_ID,
        )

        return PointInTimeTruthService(repository=repo), repo

    def test_before_supersession_returns_v1(self) -> None:
        service, _repo = self._setup_chain()

        at_query = datetime(2026, 5, 25, 9, 5, 0, tzinfo=UTC)
        result = service.at(space="memorable", record_id=V1_ID, at=at_query)

        assert result is not None
        assert result.id == V1_ID

    def test_after_supersession_returns_v2(self) -> None:
        service, _repo = self._setup_chain()

        at_query = datetime(2026, 5, 25, 9, 15, 0, tzinfo=UTC)
        result = service.at(space="memorable", record_id=V1_ID, at=at_query)

        assert result is not None
        assert result.id == V2_ID


class TestInspectHistoryServiceWithObservation:
    """InspectHistoryService works with ObservationRepository."""

    def _setup_chain(self):
        from memorable.core.application import (
            InspectHistoryService,
            RememberObservationService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberObservationService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            observation_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )
        remember.remember(
            space="memorable",
            observation_id=V2_ID,
            statement=STATEMENT_V2,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V2,
            supersedes=V1_ID,
        )

        return InspectHistoryService(repository=repo), repo

    def test_history_returns_full_chain(self) -> None:
        service, _repo = self._setup_chain()

        history = service.history(space="memorable", record_id=V1_ID)

        assert len(history) == 2
        assert history[0].id == V1_ID
        assert history[1].id == V2_ID

    def test_history_single_when_not_superseded(self) -> None:
        from memorable.core.application import (
            InspectHistoryService,
            RememberObservationService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberObservationService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            observation_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        service = InspectHistoryService(repository=repo)
        history = service.history(space="memorable", record_id=V1_ID)

        assert len(history) == 1
        assert history[0].id == V1_ID


# =====================================================================
# MCP adapter tests
# =====================================================================


class TestMCPRememberObservation:
    """MCP remember_observation_tool writes an Observation."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_remember_observation_tool(self) -> None:
        from memorable.mcp.server import remember_observation_tool

        result = remember_observation_tool(
            space="memorable",
            observation_id=V1_ID,
            statement=STATEMENT_V1,
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )

        assert result["observation_id"] == V1_ID
        assert result["source"] == SOURCE_ID
        assert result["record_kind"] == "observation"
        assert "error" not in result

    def test_remember_observation_tool_with_supersession(self) -> None:
        from memorable.mcp.server import remember_observation_tool

        remember_observation_tool(
            space="memorable",
            observation_id=V1_ID,
            statement=STATEMENT_V1,
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )

        result = remember_observation_tool(
            space="memorable",
            observation_id=V2_ID,
            statement=STATEMENT_V2,
            source=SOURCE_ID,
            at="2026-05-25T09:10:00Z",
            supersedes=V1_ID,
        )

        assert result["observation_id"] == V2_ID
        assert result["lifecycle_state"] == "current"
        assert "error" not in result

    def test_inspect_history_tool_with_observation(self) -> None:
        from memorable.mcp.server import (
            inspect_history_tool,
            remember_observation_tool,
        )

        remember_observation_tool(
            space="memorable",
            observation_id=V1_ID,
            statement=STATEMENT_V1,
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )
        remember_observation_tool(
            space="memorable",
            observation_id=V2_ID,
            statement=STATEMENT_V2,
            source=SOURCE_ID,
            at="2026-05-25T09:10:00Z",
            supersedes=V1_ID,
        )

        result = inspect_history_tool(
            space="memorable",
            record_id=V1_ID,
            record_type="observation",
        )

        assert "error" not in result
        assert len(result["history"]) == 2
        ids = [h["record_id"] for h in result["history"]]
        assert ids == [V1_ID, V2_ID]
