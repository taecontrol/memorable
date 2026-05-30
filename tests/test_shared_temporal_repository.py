"""Tests for the shared in-memory temporal repository implementation.

Verifies that InMemoryTemporalRepository provides a single generic
implementation of temporal methods (get, mark_superseded, invalidate,
correct, save_provenance, get_provenance, list_by_space) so that
concrete repositories (Decision, Observation) delegate to shared code
instead of duplicating ~90 lines each.
"""

from __future__ import annotations

from datetime import UTC, datetime

from memorable.core.models import Decision, Provenance
from memorable.core.repositories import InMemoryTemporalRepository

FIXTURE_TS = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)


def _make_decision(space: str = "s", record_id: str = "d-1") -> Decision:
    return Decision(
        id=record_id,
        statement="Use Neo4j as storage.",
        space=space,
        validity_time=FIXTURE_TS,
        invalidation_time=None,
        lifecycle_state="current",
        supersedes=None,
        superseded_by=None,
    )


def _make_provenance(record_id: str = "d-1") -> Provenance:
    return Provenance(
        record_id=record_id,
        record_kind="decision",
        source_id="src-1",
        episode_id="ep-1",
        writer="test-agent",
        reason="test reason",
        creation_time=FIXTURE_TS,
        validity_time=FIXTURE_TS,
    )


class TestGenericTemporalRepositoryStoreAndRetrieve:
    """A generic temporal repository can store and retrieve records by (space, id)."""

    def test_save_then_get_returns_record(self) -> None:
        repo: InMemoryTemporalRepository[Decision] = InMemoryTemporalRepository()
        decision = _make_decision()
        prov = _make_provenance()

        repo.save_record(decision, prov)
        result = repo.get("s", "d-1")

        assert result is not None
        assert result.id == "d-1"
        assert result.statement == "Use Neo4j as storage."

    def test_get_returns_none_for_missing(self) -> None:
        repo: InMemoryTemporalRepository[Decision] = InMemoryTemporalRepository()

        result = repo.get("s", "missing")
        assert result is None


class TestGenericTemporalRepositoryMarkSuperseded:
    """mark_superseded updates lifecycle, invalidation_time, and superseded_by."""

    def test_mark_superseded_updates_properties(self) -> None:
        repo: InMemoryTemporalRepository[Decision] = InMemoryTemporalRepository()
        repo.save_record(_make_decision(), _make_provenance())

        inv_time = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
        repo.mark_superseded("s", "d-1", "d-2", inv_time)

        result = repo.get("s", "d-1")
        assert result is not None
        assert result.lifecycle_state == "superseded"
        assert result.invalidation_time == inv_time
        assert result.superseded_by == "d-2"

    def test_mark_superseded_preserves_original_fields(self) -> None:
        repo: InMemoryTemporalRepository[Decision] = InMemoryTemporalRepository()
        repo.save_record(_make_decision(), _make_provenance())

        inv_time = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
        repo.mark_superseded("s", "d-1", "d-2", inv_time)

        result = repo.get("s", "d-1")
        assert result is not None
        assert result.statement == "Use Neo4j as storage."
        assert result.validity_time == FIXTURE_TS
        assert result.supersedes is None

    def test_mark_superseded_no_op_for_missing(self) -> None:
        repo: InMemoryTemporalRepository[Decision] = InMemoryTemporalRepository()

        inv_time = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
        repo.mark_superseded("s", "missing", "d-2", inv_time)
        # Should not raise


class TestGenericTemporalRepositoryInvalidate:
    """invalidate marks a record as invalidated with no replacement."""

    def test_invalidate_sets_lifecycle_and_time(self) -> None:
        repo: InMemoryTemporalRepository[Decision] = InMemoryTemporalRepository()
        repo.save_record(_make_decision(), _make_provenance())

        inv_time = datetime(2026, 5, 26, 14, 0, 0, tzinfo=UTC)
        repo.invalidate("s", "d-1", inv_time)

        result = repo.get("s", "d-1")
        assert result is not None
        assert result.lifecycle_state == "invalidated"
        assert result.invalidation_time == inv_time

    def test_invalidate_preserves_supersession_fields(self) -> None:
        repo: InMemoryTemporalRepository[Decision] = InMemoryTemporalRepository()
        repo.save_record(_make_decision(), _make_provenance())

        inv_time = datetime(2026, 5, 26, 14, 0, 0, tzinfo=UTC)
        repo.invalidate("s", "d-1", inv_time)

        result = repo.get("s", "d-1")
        assert result is not None
        assert result.supersedes is None
        assert result.superseded_by is None


class TestGenericTemporalRepositoryCorrect:
    """correct updates the statement without changing lifecycle state."""

    def test_correct_updates_statement(self) -> None:
        repo: InMemoryTemporalRepository[Decision] = InMemoryTemporalRepository()
        repo.save_record(_make_decision(), _make_provenance())

        repo.correct("s", "d-1", "Corrected statement.")

        result = repo.get("s", "d-1")
        assert result is not None
        assert result.statement == "Corrected statement."
        assert result.lifecycle_state == "current"


class TestGenericTemporalRepositoryProvenance:
    """save_provenance and get_provenance work through the generic implementation."""

    def test_get_provenance_after_save(self) -> None:
        repo: InMemoryTemporalRepository[Decision] = InMemoryTemporalRepository()
        repo.save_record(_make_decision(), _make_provenance())

        result = repo.get_provenance("s", "d-1")
        assert result is not None
        assert result.record_id == "d-1"
        assert result.writer == "test-agent"

    def test_save_provenance_replaces_existing(self) -> None:
        repo: InMemoryTemporalRepository[Decision] = InMemoryTemporalRepository()
        repo.save_record(_make_decision(), _make_provenance())

        new_prov = Provenance(
            record_id="d-1",
            record_kind="decision",
            source_id="new-src",
            episode_id="new-ep",
            writer="corrector-agent",
            reason="correction provenance",
            creation_time=datetime(2026, 5, 26, 15, 0, 0, tzinfo=UTC),
            validity_time=datetime(2026, 5, 26, 15, 0, 0, tzinfo=UTC),
        )
        repo.save_provenance("s", "d-1", new_prov)

        result = repo.get_provenance("s", "d-1")
        assert result is not None
        assert result.source_id == "new-src"
        assert result.writer == "corrector-agent"

    def test_get_provenance_returns_none_for_missing(self) -> None:
        repo: InMemoryTemporalRepository[Decision] = InMemoryTemporalRepository()

        result = repo.get_provenance("s", "missing")
        assert result is None


class TestGenericTemporalRepositoryListBySpace:
    """list_by_space returns only records in the specified space."""

    def test_list_by_space_filters_correctly(self) -> None:
        repo: InMemoryTemporalRepository[Decision] = InMemoryTemporalRepository()
        repo.save_record(_make_decision("a", "d-a"), _make_provenance("d-a"))
        repo.save_record(_make_decision("b", "d-b"), _make_provenance("d-b"))

        results = repo.list_by_space("a")
        assert len(results) == 1
        assert results[0].id == "d-a"

    def test_list_by_space_empty_for_unknown(self) -> None:
        repo: InMemoryTemporalRepository[Decision] = InMemoryTemporalRepository()

        results = repo.list_by_space("unknown")
        assert results == []


class TestConcreteReposDelegateToShared:
    """InMemoryDecisionRepository and InMemoryObservationRepository inherit
    from InMemoryTemporalRepository so temporal methods are implemented once."""

    def test_decision_repo_inherits_from_temporal(self) -> None:
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        assert isinstance(repo, InMemoryTemporalRepository)

    def test_observation_repo_inherits_from_temporal(self) -> None:
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        assert isinstance(repo, InMemoryTemporalRepository)

    def test_decision_repo_has_all_decision_protocol_methods(
        self,
    ) -> None:
        """DecisionRepository protocol methods are all present."""
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        required = (
            "save",
            "get",
            "get_provenance",
            "list_by_space",
            "list_projections_by_space",
            "mark_superseded",
        )
        for method in required:
            assert hasattr(repo, method), f"Missing method: {method}"
            assert callable(getattr(repo, method))

    def test_observation_repo_has_all_observation_protocol_methods(
        self,
    ) -> None:
        """ObservationRepository protocol methods are all present."""
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        required = (
            "save",
            "get",
            "get_provenance",
            "list_by_space",
            "mark_superseded",
        )
        for method in required:
            assert hasattr(repo, method), f"Missing method: {method}"
            assert callable(getattr(repo, method))

    def test_decision_repo_satisfies_temporal_protocol(self) -> None:
        from memorable.core.ports import TemporalRecordRepository
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        assert isinstance(repo, TemporalRecordRepository)

    def test_observation_repo_satisfies_temporal_protocol(self) -> None:
        from memorable.core.ports import TemporalRecordRepository
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        assert isinstance(repo, TemporalRecordRepository)

    def test_decision_save_uses_domain_parameter_name(self) -> None:
        """Decision repo save() accepts (decision, provenance) for protocol compat."""
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        decision = _make_decision()
        prov = _make_provenance()

        repo.save(decision, prov)
        result = repo.get("s", "d-1")
        assert result is not None
        assert result.id == "d-1"

    def test_observation_save_uses_domain_parameter_name(self) -> None:
        """Observation repo save() accepts (observation, provenance)."""
        from memorable.core.models import Observation
        from memorable.core.repositories import InMemoryObservationRepository

        repo = InMemoryObservationRepository()
        obs = Observation(
            id="o-1",
            statement="Dark mode preferred.",
            space="s",
            validity_time=FIXTURE_TS,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        prov = Provenance(
            record_id="o-1",
            record_kind="observation",
            source_id="src-1",
            episode_id="ep-1",
            writer="test-agent",
            reason="test",
            creation_time=FIXTURE_TS,
            validity_time=FIXTURE_TS,
        )

        repo.save(obs, prov)
        result = repo.get("s", "o-1")
        assert result is not None
        assert result.id == "o-1"
