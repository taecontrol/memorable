"""Integration tests for MemorySpace isolation with a real Neo4j instance.

These tests require a running Neo4j instance. They are marked with
@pytest.mark.integration and will be skipped if Neo4j is unavailable.

Run with: uv run pytest tests/test_neo4j_integration.py -v -m integration
"""

from __future__ import annotations

import uuid

import pytest

from memorable.core.models import MemorySpace
from memorable.storage.neo4j.config import Neo4jConfig

# Skip all tests in this module if Neo4j is unavailable
neo4j_available = False
try:
    from neo4j import GraphDatabase

    config = Neo4jConfig.from_env()
    _driver = GraphDatabase.driver(config.uri, auth=(config.user, config.password))
    _driver.verify_connectivity()
    _driver.close()
    neo4j_available = True
except Exception:
    pass

pytestmark = pytest.mark.skipif(
    not neo4j_available,
    reason="Neo4j is not available",
)


@pytest.fixture
def neo4j_driver():
    """Provide a Neo4j driver connected to the test instance."""
    from neo4j import GraphDatabase

    config = Neo4jConfig.from_env()
    driver = GraphDatabase.driver(config.uri, auth=(config.user, config.password))
    yield driver
    driver.close()


@pytest.fixture
def repo(neo4j_driver):
    """Provide a Neo4jMemorySpaceRepository with constraints set up."""
    from memorable.storage.neo4j.repository import Neo4jMemorySpaceRepository

    repository = Neo4jMemorySpaceRepository(driver=neo4j_driver)
    repository.ensure_constraints()
    return repository


@pytest.fixture(autouse=True)
def cleanup_test_spaces(neo4j_driver):
    """Clean up any test MemorySpaces after each test."""
    yield
    with neo4j_driver.session() as session:
        session.run("MATCH (s:MemorySpace) WHERE s.name STARTS WITH 'test-' DELETE s")


def _unique_name(prefix: str = "test-") -> str:
    """Generate a unique MemorySpace name for test isolation."""
    return f"{prefix}{uuid.uuid4().hex[:8]}"


class TestMemorySpaceIsolation:
    """Two MemorySpaces cannot read each other through normal repository methods."""

    def test_create_and_retrieve_memory_space(self, repo) -> None:
        """A created MemorySpace can be retrieved by name."""
        name = _unique_name()
        created = repo.create_space(name)

        assert isinstance(created, MemorySpace)
        assert created.name == name

        retrieved = repo.get_space(name)
        assert retrieved is not None
        assert retrieved.name == name
        assert retrieved == created

    def test_two_spaces_are_independent(self, repo) -> None:
        """Creating one MemorySpace does not make the other visible."""
        name_a = _unique_name("test-alpha-")
        name_b = _unique_name("test-beta-")

        repo.create_space(name_a)
        repo.create_space(name_b)

        space_a = repo.get_space(name_a)
        space_b = repo.get_space(name_b)

        assert space_a is not None
        assert space_b is not None
        assert space_a != space_b
        assert space_a.name == name_a
        assert space_b.name == name_b

    def test_space_does_not_see_other_space(self, repo) -> None:
        """A MemorySpace query for one name does not return another."""
        name_a = _unique_name("test-iso-a-")
        name_b = _unique_name("test-iso-b-")

        repo.create_space(name_a)
        # name_b is NOT created

        assert repo.exists(name_a)
        assert not repo.exists(name_b)
        assert repo.get_space(name_b) is None

    def test_duplicate_space_creation_rejected(self, repo) -> None:
        """Creating a MemorySpace with an existing name is rejected."""
        name = _unique_name()
        repo.create_space(name)

        with pytest.raises(ValueError, match="already exists"):
            repo.create_space(name)

    def test_isolation_across_repositories(self, neo4j_driver) -> None:
        """Two repo instances share persistence but enforce same boundaries."""
        from memorable.storage.neo4j.repository import Neo4jMemorySpaceRepository

        repo1 = Neo4jMemorySpaceRepository(driver=neo4j_driver)
        repo2 = Neo4jMemorySpaceRepository(driver=neo4j_driver)

        name = _unique_name()
        repo1.create_space(name)

        # repo2 sees it through the shared storage
        assert repo2.exists(name)
        assert repo2.get_space(name) == MemorySpace(name=name)

        # But a different name is still isolated
        other = _unique_name()
        assert not repo2.exists(other)
