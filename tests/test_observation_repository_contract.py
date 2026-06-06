"""Contract tests for ObservationRepository implementations.

These tests verify behavioral equivalence between InMemoryObservationRepository
and Neo4jObservationRepository. Both adapters must satisfy the same contract:
save, get, list_by_space, get_provenance, mark_superseded, invalidate, correct.

Neo4j tests are marked with @pytest.mark.integration and skip if unavailable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

# --- Check Neo4j availability ---
from live_neo4j import build_live_neo4j_driver, live_neo4j_available

from memorable.core.models import Observation, Provenance

neo4j_available = live_neo4j_available()


# --- Fixtures ---

FIXTURE_TS = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)


def _unique_space() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


def _make_observation(space: str, obs_id: str = "obs-1") -> Observation:
    return Observation(
        id=obs_id,
        statement="The system favors eventual consistency.",
        space=space,
        validity_time=FIXTURE_TS,
        invalidation_time=None,
        lifecycle_state="current",
        supersedes=None,
        superseded_by=None,
    )


def _make_provenance(record_id: str) -> Provenance:
    return Provenance(
        record_id=record_id,
        record_kind="observation",
        source_id="src-1",
        episode_id="ep-1",
        writer="test-agent",
        reason="test reason",
        creation_time=FIXTURE_TS,
        validity_time=FIXTURE_TS,
    )


@pytest.fixture
def inmemory_repo():
    from memorable.core.repositories import InMemoryObservationRepository

    return InMemoryObservationRepository()


@pytest.fixture
def neo4j_repo():
    if not neo4j_available:
        pytest.skip("Neo4j is not available")

    from memorable.storage.neo4j.repository import Neo4jObservationRepository

    driver = build_live_neo4j_driver()
    repo = Neo4jObservationRepository(driver)
    yield repo
    # Cleanup test data
    with driver.session() as session:
        session.run(
            "MATCH (p:Provenance)-[r:PROVENANCE_OF]->(o:Observation) "
            "WHERE o.space STARTS WITH 'test-' DELETE r, p, o"
        )
        session.run("MATCH (o:Observation) WHERE o.space STARTS WITH 'test-' DELETE o")
    driver.close()


ALL_REPOS = ["inmemory_repo", "neo4j_repo"]


# =====================================================================
# Contract: save and get
# =====================================================================


class TestObservationSaveAndGet:
    """An Observation can be saved and retrieved by space and id."""

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_save_then_get_returns_same_observation(self, repo_fixture, request):
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()
        obs = _make_observation(space)
        prov = _make_provenance("obs-1")

        repo.save(obs, prov)
        result = repo.get(space, "obs-1")

        assert result is not None
        assert result.id == "obs-1"
        assert result.statement == "The system favors eventual consistency."
        assert result.space == space
        assert result.lifecycle_state == "current"

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_get_returns_none_for_missing(self, repo_fixture, request):
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()

        result = repo.get(space, "nonexistent")
        assert result is None


# =====================================================================
# Contract: list_by_space
# =====================================================================


class TestObservationListBySpace:
    """list_by_space returns only observations in the specified space."""

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_list_by_space_filters_correctly(self, repo_fixture, request):
        repo = request.getfixturevalue(repo_fixture)
        space_a = _unique_space()
        space_b = _unique_space()

        obs_a = _make_observation(space_a, "obs-a")
        obs_b = _make_observation(space_b, "obs-b")

        repo.save(obs_a, _make_provenance("obs-a"))
        repo.save(obs_b, _make_provenance("obs-b"))

        results = repo.list_by_space(space_a)
        assert len(results) == 1
        assert results[0].id == "obs-a"

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_list_by_space_empty_for_unknown_space(self, repo_fixture, request):
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()

        results = repo.list_by_space(space)
        assert results == []


# =====================================================================
# Contract: get_provenance
# =====================================================================


class TestObservationGetProvenance:
    """get_provenance returns the provenance associated with an observation."""

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_get_provenance_after_save(self, repo_fixture, request):
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()
        obs = _make_observation(space)
        prov = _make_provenance("obs-1")

        repo.save(obs, prov)
        result = repo.get_provenance(space, "obs-1")

        assert result is not None
        assert result.record_id == "obs-1"
        assert result.record_kind == "observation"
        assert result.writer == "test-agent"

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_get_provenance_returns_none_for_missing(self, repo_fixture, request):
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()

        result = repo.get_provenance(space, "nonexistent")
        assert result is None


# =====================================================================
# Contract: mark_superseded
# =====================================================================


class TestObservationMarkSuperseded:
    """mark_superseded updates lifecycle, invalidation_time, and superseded_by."""

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_mark_superseded_updates_properties(self, repo_fixture, request):
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()
        obs = _make_observation(space)
        repo.save(obs, _make_provenance("obs-1"))

        inv_time = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
        repo.mark_superseded(space, "obs-1", "obs-2", inv_time)

        result = repo.get(space, "obs-1")
        assert result is not None
        assert result.lifecycle_state == "superseded"
        assert result.invalidation_time == inv_time
        assert result.superseded_by == "obs-2"


# =====================================================================
# Contract: invalidate
# =====================================================================


class TestObservationInvalidate:
    """invalidate marks a record as invalidated with no replacement."""

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_invalidate_sets_lifecycle_and_time(self, repo_fixture, request):
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()
        obs = _make_observation(space)
        repo.save(obs, _make_provenance("obs-1"))

        inv_time = datetime(2026, 5, 26, 14, 0, 0, tzinfo=UTC)
        repo.invalidate(space, "obs-1", inv_time)

        result = repo.get(space, "obs-1")
        assert result is not None
        assert result.lifecycle_state == "invalidated"
        assert result.invalidation_time == inv_time


# =====================================================================
# Contract: correct
# =====================================================================


class TestObservationCorrect:
    """correct updates the statement without changing lifecycle state."""

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_correct_updates_statement(self, repo_fixture, request):
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()
        obs = _make_observation(space)
        repo.save(obs, _make_provenance("obs-1"))

        repo.correct(space, "obs-1", "Corrected statement.")

        result = repo.get(space, "obs-1")
        assert result is not None
        assert result.statement == "Corrected statement."
        assert result.lifecycle_state == "current"  # unchanged


# =====================================================================
# Contract: save_provenance (replace provenance)
# =====================================================================


class TestObservationSaveProvenance:
    """save_provenance replaces the provenance for an existing observation."""

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_save_provenance_replaces_existing(self, repo_fixture, request):
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()
        obs = _make_observation(space)
        repo.save(obs, _make_provenance("obs-1"))

        new_prov = Provenance(
            record_id="obs-1",
            record_kind="observation",
            source_id="new-src",
            episode_id="new-ep",
            writer="corrector-agent",
            reason="correction provenance",
            creation_time=datetime(2026, 5, 26, 15, 0, 0, tzinfo=UTC),
            validity_time=datetime(2026, 5, 26, 15, 0, 0, tzinfo=UTC),
        )
        repo.save_provenance(space, "obs-1", new_prov)

        result = repo.get_provenance(space, "obs-1")
        assert result is not None
        assert result.source_id == "new-src"
        assert result.writer == "corrector-agent"
        assert result.reason == "correction provenance"
