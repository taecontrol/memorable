"""Unit tests for Neo4jObservationRepository.

Verifies the adapter exists, is importable, satisfies the protocol,
and that production wiring includes it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


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


class TestProductionWiringIncludesObservation:
    """build_production_context wires Neo4jObservationRepository."""

    def test_production_context_has_neo4j_observation_repo(self) -> None:
        from memorable.config import RuntimeConfig
        from memorable.storage.neo4j.repository import Neo4jObservationRepository
        from memorable.storage.production import build_production_context

        config = RuntimeConfig()
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
