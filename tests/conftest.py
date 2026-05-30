"""Shared fixtures for Memorable tests."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from memorable.config import RuntimeConfig
from memorable.core.context import ApplicationContext


@dataclass(frozen=True)
class DecisionProjectionInMemoryHarness:
    repository: Any
    record_type: str = "decision"

    def remove_provenance(self, *, space: str, record_id: str) -> None:
        self.repository._provenance.pop((space, record_id))

    def save(self, record: Any, provenance: Any) -> None:
        self.repository.save(record, provenance)


@dataclass(frozen=True)
class ObservationProjectionInMemoryHarness:
    repository: Any
    record_type: str = "observation"

    def remove_provenance(self, *, space: str, record_id: str) -> None:
        self.repository._provenance.pop((space, record_id))

    def save(self, record: Any, provenance: Any) -> None:
        self.repository.save(record, provenance)


@dataclass(frozen=True)
class RelationProjectionInMemoryHarness:
    repository: Any
    record_type: str = "relation"

    def remove_provenance(self, *, space: str, record_id: str) -> None:
        self.repository._provenance.pop((space, record_id))

    def save(self, record: Any, provenance: Any) -> None:
        self.repository.save(record, provenance)


@dataclass(frozen=True)
class TaskProjectionInMemoryHarness:
    repository: Any
    record_type: str = "task"

    def remove_provenance(self, *, space: str, record_id: str) -> None:
        self.repository._provenance.pop((space, record_id))

    def save(self, record: Any, provenance: Any) -> None:
        self.repository.save(record, provenance)


@dataclass(frozen=True)
class DecisionProjectionNeo4jHarness:
    repository: Any
    driver: Any
    record_type: str = "decision"

    def remove_provenance(self, *, space: str, record_id: str) -> None:
        with self.driver.session() as session:
            session.run(
                "MATCH (p:Provenance)-[r:PROVENANCE_OF]->"
                "(d:Decision {space: $space, id: $id}) DELETE r, p",
                space=space,
                id=record_id,
            )

    def save(self, record: Any, provenance: Any) -> None:
        self.repository.save(record, provenance)


@dataclass(frozen=True)
class ObservationProjectionNeo4jHarness:
    repository: Any
    driver: Any
    record_type: str = "observation"

    def remove_provenance(self, *, space: str, record_id: str) -> None:
        with self.driver.session() as session:
            session.run(
                "MATCH (p:Provenance)-[r:PROVENANCE_OF]->"
                "(o:Observation {space: $space, id: $id}) DELETE r, p",
                space=space,
                id=record_id,
            )

    def save(self, record: Any, provenance: Any) -> None:
        self.repository.save(record, provenance)


@dataclass(frozen=True)
class RelationProjectionNeo4jHarness:
    repository: Any
    entity_repository: Any
    driver: Any
    record_type: str = "relation"

    def remove_provenance(self, *, space: str, record_id: str) -> None:
        with self.driver.session() as session:
            session.run(
                "MATCH (p:Provenance)-[r:PROVENANCE_OF]->"
                "(rel:Relation {space: $space, id: $id}) DELETE r, p",
                space=space,
                id=record_id,
            )

    def save(self, record: Any, provenance: Any) -> None:
        from memorable.core.models import Entity, Provenance

        for entity_id in (record.source_entity_id, record.target_entity_id):
            self.entity_repository.save(
                Entity(
                    id=entity_id,
                    entity_type="test-entity",
                    name=entity_id,
                    space=record.space,
                ),
                Provenance(
                    record_id=entity_id,
                    record_kind="entity",
                    source_id=provenance.source_id,
                    episode_id=provenance.episode_id,
                    writer=provenance.writer,
                    reason="test relation endpoint",
                    creation_time=provenance.creation_time,
                    validity_time=provenance.validity_time,
                ),
            )
        self.repository.save(record, provenance)


@dataclass(frozen=True)
class TaskProjectionNeo4jHarness:
    repository: Any
    driver: Any
    record_type: str = "task"

    def remove_provenance(self, *, space: str, record_id: str) -> None:
        with self.driver.session() as session:
            session.run(
                "MATCH (p:Provenance)-[r:PROVENANCE_OF]->"
                "(t:Task {space: $space, id: $id}) DELETE r, p",
                space=space,
                id=record_id,
            )

    def save(self, record: Any, provenance: Any) -> None:
        self.repository.save(record, provenance)


def _neo4j_available() -> bool:
    try:
        from neo4j import GraphDatabase

        from memorable.storage.neo4j.config import Neo4jConfig

        config = Neo4jConfig.from_env()
        driver = GraphDatabase.driver(config.uri, auth=(config.user, config.password))
        driver.verify_connectivity()
        driver.close()
    except Exception:
        return False
    return True


@pytest.fixture()
def decision_projection_inmemory_harness() -> DecisionProjectionInMemoryHarness:
    from memorable.core.repositories import InMemoryDecisionRepository

    return DecisionProjectionInMemoryHarness(InMemoryDecisionRepository())


@pytest.fixture()
def observation_projection_inmemory_harness() -> ObservationProjectionInMemoryHarness:
    from memorable.core.repositories import InMemoryObservationRepository

    return ObservationProjectionInMemoryHarness(InMemoryObservationRepository())


@pytest.fixture()
def relation_projection_inmemory_harness() -> RelationProjectionInMemoryHarness:
    from memorable.core.repositories import InMemoryRelationRepository

    return RelationProjectionInMemoryHarness(InMemoryRelationRepository())


@pytest.fixture()
def task_projection_inmemory_harness() -> TaskProjectionInMemoryHarness:
    from memorable.core.repositories import InMemoryTaskRepository

    return TaskProjectionInMemoryHarness(InMemoryTaskRepository())


@pytest.fixture()
def decision_projection_neo4j_harness() -> Iterator[DecisionProjectionNeo4jHarness]:
    if not _neo4j_available():
        pytest.skip("Neo4j is not available")

    from neo4j import GraphDatabase

    from memorable.storage.neo4j.config import Neo4jConfig
    from memorable.storage.neo4j.repository import Neo4jDecisionRepository

    config = Neo4jConfig.from_env()
    driver = GraphDatabase.driver(config.uri, auth=(config.user, config.password))
    repo = Neo4jDecisionRepository(driver)
    yield DecisionProjectionNeo4jHarness(repo, driver)
    with driver.session() as session:
        session.run(
            "MATCH (p:Provenance)-[r:PROVENANCE_OF]->(d:Decision) "
            "WHERE d.space STARTS WITH 'test-' DELETE r, p, d"
        )
        session.run("MATCH (d:Decision) WHERE d.space STARTS WITH 'test-' DELETE d")
    driver.close()


@pytest.fixture()
def observation_projection_neo4j_harness() -> Iterator[
    ObservationProjectionNeo4jHarness
]:
    if not _neo4j_available():
        pytest.skip("Neo4j is not available")

    from neo4j import GraphDatabase

    from memorable.storage.neo4j.config import Neo4jConfig
    from memorable.storage.neo4j.repository import Neo4jObservationRepository

    config = Neo4jConfig.from_env()
    driver = GraphDatabase.driver(config.uri, auth=(config.user, config.password))
    repo = Neo4jObservationRepository(driver)
    yield ObservationProjectionNeo4jHarness(repo, driver)
    with driver.session() as session:
        session.run(
            "MATCH (p:Provenance)-[r:PROVENANCE_OF]->(o:Observation) "
            "WHERE o.space STARTS WITH 'test-' DELETE r, p, o"
        )
        session.run("MATCH (o:Observation) WHERE o.space STARTS WITH 'test-' DELETE o")
    driver.close()


@pytest.fixture()
def relation_projection_neo4j_harness() -> Iterator[RelationProjectionNeo4jHarness]:
    if not _neo4j_available():
        pytest.skip("Neo4j is not available")

    from neo4j import GraphDatabase

    from memorable.storage.neo4j.config import Neo4jConfig
    from memorable.storage.neo4j.repository import (
        Neo4jEntityRepository,
        Neo4jRelationRepository,
    )

    config = Neo4jConfig.from_env()
    driver = GraphDatabase.driver(config.uri, auth=(config.user, config.password))
    repo = Neo4jRelationRepository(driver)
    entity_repo = Neo4jEntityRepository(driver)
    yield RelationProjectionNeo4jHarness(repo, entity_repo, driver)
    with driver.session() as session:
        session.run(
            "MATCH (p:Provenance)-[r:PROVENANCE_OF]->(rel:Relation) "
            "WHERE rel.space STARTS WITH 'test-' DELETE r, p"
        )
        session.run(
            "MATCH (rel:Relation)-[r:FROM|TO]->(:Entity) "
            "WHERE rel.space STARTS WITH 'test-' DELETE r"
        )
        session.run(
            "MATCH (rel:Relation) WHERE rel.space STARTS WITH 'test-' DELETE rel"
        )
        session.run(
            "MATCH (p:Provenance)-[r:PROVENANCE_OF]->(e:Entity) "
            "WHERE e.space STARTS WITH 'test-' DELETE r, p, e"
        )
        session.run("MATCH (e:Entity) WHERE e.space STARTS WITH 'test-' DELETE e")
    driver.close()


@pytest.fixture()
def task_projection_neo4j_harness() -> Iterator[TaskProjectionNeo4jHarness]:
    if not _neo4j_available():
        pytest.skip("Neo4j is not available")

    from neo4j import GraphDatabase

    from memorable.storage.neo4j.config import Neo4jConfig
    from memorable.storage.neo4j.repository import Neo4jTaskRepository

    config = Neo4jConfig.from_env()
    driver = GraphDatabase.driver(config.uri, auth=(config.user, config.password))
    repo = Neo4jTaskRepository(driver)
    yield TaskProjectionNeo4jHarness(repo, driver)
    with driver.session() as session:
        session.run(
            "MATCH (p:Provenance)-[r:PROVENANCE_OF]->(t:Task) "
            "WHERE t.space STARTS WITH 'test-' DELETE r, p, t"
        )
        session.run("MATCH (t:Task) WHERE t.space STARTS WITH 'test-' DELETE t")
    driver.close()


@pytest.fixture()
def clean_memorable_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep host/sandbox runtime variables from changing unit-test defaults."""
    for key in (
        "MEMORABLE_NEO4J_URI",
        "MEMORABLE_NEO4J_USER",
        "MEMORABLE_NEO4J_PASSWORD",
        "MEMORABLE_OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def cli_in_memory_context():
    """Patch CLI production wiring to use an in-memory ApplicationContext.

    CLI memory commands now build a production context (Neo4j-backed) at
    runtime. Tests that exercise CLI behavior without a real database
    should use this fixture to get an in-memory context instead.

    The fixture patches build_production_context and load_runtime_config
    in the cli module, and returns the shared ApplicationContext so tests
    can inspect persisted state if needed.

    Usage::

        def test_something(self, cli_in_memory_context, capsys):
            ctx = cli_in_memory_context
            main(["remember", "entity", "--space", "test", ...])
            # entity is stored in ctx.entity_repo
    """
    ctx = ApplicationContext()
    mock_driver = MagicMock()
    mock_driver.verify_connectivity.return_value = None

    with (
        patch("memorable.cli.build_production_context") as mock_build,
        patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
    ):
        mock_build.return_value = (ctx, mock_driver)
        yield ctx
