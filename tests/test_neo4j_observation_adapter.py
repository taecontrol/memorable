"""Unit tests for Neo4jObservationRepository.

Verifies the adapter exists, is importable, satisfies the protocol,
and that production wiring includes it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch


def _observation_with_record_type():
    from memorable.core.models import Observation, Provenance

    at = datetime(2026, 6, 6, 10, 0, tzinfo=UTC)
    observation = Observation(
        id="observation:episode-1",
        statement="Episode 1 happened.",
        space="memorable",
        validity_time=at,
        invalidation_time=None,
        lifecycle_state="current",
        supersedes=None,
        superseded_by=None,
        record_type="Episode",
    )
    provenance = Provenance(
        record_id=observation.id,
        record_kind="observation",
        source_id="source:test",
        episode_id="episode:test",
        writer="agent:test",
        reason="test",
        creation_time=at,
        validity_time=at,
    )
    return observation, provenance


class TestNeo4jObservationRepositoryExists:
    """Neo4jObservationRepository can be imported and instantiated."""

    def test_importable(self) -> None:
        from memorable.storage.neo4j.repository import Neo4jObservationRepository

        assert Neo4jObservationRepository is not None

    def test_has_observation_repository_methods(self) -> None:
        from memorable.storage.neo4j.repository import Neo4jObservationRepository

        driver = MagicMock()
        repo = Neo4jObservationRepository(driver)
        # Verify the full ObservationRepository surface
        assert callable(repo.save)
        assert callable(repo.get)
        assert callable(repo.get_provenance)
        assert callable(repo.list_by_space)
        assert callable(repo.list_projections_by_space)
        assert callable(repo.mark_superseded)

    def test_satisfies_temporal_record_repository_protocol(self) -> None:
        from memorable.core.ports import TemporalRecordRepository
        from memorable.storage.neo4j.repository import Neo4jObservationRepository

        driver = MagicMock()
        repo = Neo4jObservationRepository(driver)
        assert isinstance(repo, TemporalRecordRepository)


class TestNeo4jObservationRecordSubtype:
    def test_save_persists_record_type_property(self) -> None:
        from memorable.storage.neo4j.repository import Neo4jObservationRepository

        observation, provenance = _observation_with_record_type()
        driver = MagicMock()
        session = MagicMock()
        driver.session.return_value.__enter__.return_value = session
        driver.session.return_value.__exit__.return_value = False

        Neo4jObservationRepository(driver).save(observation, provenance)

        _, kwargs = session.run.call_args
        assert "record_type" in kwargs
        assert kwargs["record_type"] == "Episode"

    def test_get_returns_record_type_property(self) -> None:
        from memorable.storage.neo4j.repository import Neo4jObservationRepository

        observation, _provenance = _observation_with_record_type()
        driver = MagicMock()
        session = MagicMock()
        session.run.return_value.single.return_value = {
            "id": observation.id,
            "statement": observation.statement,
            "space": observation.space,
            "validity_time": observation.validity_time.isoformat(
                timespec="microseconds"
            ),
            "invalidation_time": None,
            "lifecycle_state": observation.lifecycle_state,
            "supersedes": None,
            "superseded_by": None,
            "record_type": "Episode",
        }
        driver.session.return_value.__enter__.return_value = session
        driver.session.return_value.__exit__.return_value = False

        retrieved = Neo4jObservationRepository(driver).get(
            observation.space,
            observation.id,
        )

        assert retrieved is not None
        assert retrieved.record_type == "Episode"


class TestProductionWiringIncludesObservation:
    """build_production_context wires Neo4jObservationRepository."""

    def test_production_context_has_neo4j_observation_repo(self) -> None:
        from memorable.config import RuntimeConfig, StorageSettings
        from memorable.storage.neo4j.repository import Neo4jObservationRepository
        from memorable.storage.production import build_production_context

        config = RuntimeConfig(storage=StorageSettings(backend="neo4j"))
        mock_driver = MagicMock()
        mock_driver.verify_connectivity.return_value = None

        with patch("memorable.storage.neo4j.connection.GraphDatabase") as mock_gdb:
            mock_gdb.driver.return_value = mock_driver
            ctx, _ = build_production_context(config)

        assert isinstance(ctx.observation_repo, Neo4jObservationRepository)


class TestObservationConstraintInSchema:
    """ensure_all_constraints includes observation_space_id_unique."""

    def test_observation_constraint_is_created(self) -> None:
        from memorable.storage.neo4j.repository import ensure_all_constraints

        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(
            return_value=mock_session
        )
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        ensure_all_constraints(mock_driver)

        # Collect all Cypher queries
        calls = [str(call) for call in mock_session.run.call_args_list]
        constraint_queries = " ".join(calls)

        assert "observation_space_id_unique" in constraint_queries
        assert "Observation" in constraint_queries
