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

    def remove_provenance(self, *, space: str, record_id: str) -> None:
        self.repository._provenance.pop((space, record_id))


@dataclass(frozen=True)
class DecisionProjectionNeo4jHarness:
    repository: Any
    driver: Any

    def remove_provenance(self, *, space: str, record_id: str) -> None:
        with self.driver.session() as session:
            session.run(
                "MATCH (p:Provenance)-[r:PROVENANCE_OF]->"
                "(d:Decision {space: $space, id: $id}) DELETE r, p",
                space=space,
                id=record_id,
            )


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
