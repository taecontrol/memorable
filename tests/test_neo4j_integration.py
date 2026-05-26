"""Integration tests for Neo4j adapters with a real Neo4j instance.

These tests require a running Neo4j instance. They are marked with
@pytest.mark.integration and will be skipped if Neo4j is unavailable.

Run with: uv run pytest tests/test_neo4j_integration.py -v -m integration
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from memorable.core.models import (
    Decision,
    Entity,
    MemorySpace,
    Observation,
    Provenance,
    Task,
)
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
def cleanup_test_data(neo4j_driver):
    """Clean up any test data after each test."""
    yield
    with neo4j_driver.session() as session:
        session.run("MATCH (s:MemorySpace) WHERE s.name STARTS WITH 'test-' DELETE s")
        session.run(
            "MATCH (p:Provenance)-[r:PROVENANCE_OF]->(e:Entity) "
            "WHERE e.space STARTS WITH 'test-' DELETE r, p, e"
        )
        session.run("MATCH (e:Entity) WHERE e.space STARTS WITH 'test-' DELETE e")
        session.run(
            "MATCH (p:Provenance)-[r:PROVENANCE_OF]->(d:Decision) "
            "WHERE d.space STARTS WITH 'test-' DELETE r, p, d"
        )
        session.run("MATCH (d:Decision) WHERE d.space STARTS WITH 'test-' DELETE d")
        session.run(
            "MATCH (p:Provenance)-[r:PROVENANCE_OF]->(t:Task) "
            "WHERE t.space STARTS WITH 'test-' DELETE r, p, t"
        )
        session.run("MATCH (t:Task) WHERE t.space STARTS WITH 'test-' DELETE t")
        session.run(
            "MATCH (p:Provenance)-[r:PROVENANCE_OF]->(o:Observation) "
            "WHERE o.space STARTS WITH 'test-' DELETE r, p, o"
        )
        session.run("MATCH (o:Observation) WHERE o.space STARTS WITH 'test-' DELETE o")


def _unique_name(prefix: str = "test-") -> str:
    """Generate a unique name for test isolation."""
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _make_provenance(
    record_id: str, record_kind: str, ts: datetime | None = None
) -> Provenance:
    """Create a test Provenance instance."""
    ts = ts or datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    return Provenance(
        record_id=record_id,
        record_kind=record_kind,
        source_id="src-1",
        episode_id="ep-1",
        writer="test-agent",
        reason="test reason",
        creation_time=ts,
        validity_time=ts,
    )


# --- MemorySpace integration tests ---


class TestMemorySpaceIsolation:
    """Two MemorySpaces cannot read each other through normal repository methods."""

    @pytest.mark.integration
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

    @pytest.mark.integration
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

    @pytest.mark.integration
    def test_space_does_not_see_other_space(self, repo) -> None:
        """A MemorySpace query for one name does not return another."""
        name_a = _unique_name("test-iso-a-")
        name_b = _unique_name("test-iso-b-")

        repo.create_space(name_a)
        # name_b is NOT created

        assert repo.exists(name_a)
        assert not repo.exists(name_b)
        assert repo.get_space(name_b) is None

    @pytest.mark.integration
    def test_duplicate_space_creation_rejected(self, repo) -> None:
        """Creating a MemorySpace with an existing name is rejected."""
        name = _unique_name()
        repo.create_space(name)

        with pytest.raises(ValueError, match="already exists"):
            repo.create_space(name)

    @pytest.mark.integration
    def test_isolation_across_repositories(self, neo4j_driver) -> None:
        """Two repo instances share persistence but enforce same boundaries."""
        from memorable.storage.neo4j.repository import Neo4jMemorySpaceRepository

        repo1 = Neo4jMemorySpaceRepository(driver=neo4j_driver)
        repo2 = Neo4jMemorySpaceRepository(driver=neo4j_driver)

        name = _unique_name()
        repo1.create_space(name)

        assert repo2.exists(name)
        assert repo2.get_space(name) == MemorySpace(name=name)

        other = _unique_name()
        assert not repo2.exists(other)


# --- Entity integration tests ---


class TestEntityIntegration:
    """Integration tests for Neo4jEntityRepository."""

    @pytest.mark.integration
    def test_save_then_get_returns_same_data(self, neo4j_driver) -> None:
        """Save then get returns the same Entity."""
        from memorable.storage.neo4j.repository import Neo4jEntityRepository

        repo = Neo4jEntityRepository(driver=neo4j_driver)
        space = _unique_name()
        entity = Entity(
            id="ent-1", entity_type="component", name="Auth Service", space=space
        )
        provenance = _make_provenance("ent-1", "entity")

        repo.save(entity, provenance)
        result = repo.get(space, "ent-1")

        assert result is not None
        assert result.id == "ent-1"
        assert result.entity_type == "component"
        assert result.name == "Auth Service"
        assert result.space == space

    @pytest.mark.integration
    def test_list_by_space_filters_correctly(self, neo4j_driver) -> None:
        """list_by_space returns only entities in the specified space."""
        from memorable.storage.neo4j.repository import Neo4jEntityRepository

        repo = Neo4jEntityRepository(driver=neo4j_driver)
        space_a = _unique_name("test-a-")
        space_b = _unique_name("test-b-")

        e1 = Entity(id="e1", entity_type="api", name="Users", space=space_a)
        e2 = Entity(id="e2", entity_type="api", name="Orders", space=space_a)
        e3 = Entity(id="e3", entity_type="api", name="Other", space=space_b)

        repo.save(e1, _make_provenance("e1", "entity"))
        repo.save(e2, _make_provenance("e2", "entity"))
        repo.save(e3, _make_provenance("e3", "entity"))

        results = repo.list_by_space(space_a)
        ids = {e.id for e in results}
        assert ids == {"e1", "e2"}

    @pytest.mark.integration
    def test_cross_space_isolation(self, neo4j_driver) -> None:
        """Writing to space A then querying space B returns nothing."""
        from memorable.storage.neo4j.repository import Neo4jEntityRepository

        repo = Neo4jEntityRepository(driver=neo4j_driver)
        space_a = _unique_name("test-write-")
        space_b = _unique_name("test-read-")

        entity = Entity(id="ent-1", entity_type="service", name="Auth", space=space_a)
        repo.save(entity, _make_provenance("ent-1", "entity"))

        assert repo.get(space_b, "ent-1") is None
        assert repo.list_by_space(space_b) == []

    @pytest.mark.integration
    def test_get_provenance_after_save(self, neo4j_driver) -> None:
        """get_provenance returns the correct provenance after save."""
        from memorable.storage.neo4j.repository import Neo4jEntityRepository

        repo = Neo4jEntityRepository(driver=neo4j_driver)
        space = _unique_name()
        entity = Entity(id="ent-1", entity_type="component", name="Auth", space=space)
        ts = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)
        provenance = Provenance(
            record_id="ent-1",
            record_kind="entity",
            source_id="src-42",
            episode_id="ep-7",
            writer="agent-x",
            reason="discovered",
            creation_time=ts,
            validity_time=ts,
        )

        repo.save(entity, provenance)
        result = repo.get_provenance(space, "ent-1")

        assert result is not None
        assert result.record_id == "ent-1"
        assert result.source_id == "src-42"
        assert result.writer == "agent-x"


# --- Decision integration tests ---


class TestDecisionIntegration:
    """Integration tests for Neo4jDecisionRepository."""

    @pytest.mark.integration
    def test_save_then_get_returns_same_data(self, neo4j_driver) -> None:
        """Save then get returns the same Decision."""
        from memorable.storage.neo4j.repository import Neo4jDecisionRepository

        repo = Neo4jDecisionRepository(driver=neo4j_driver)
        space = _unique_name()
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)
        decision = Decision(
            id="dec-1",
            statement="Use PostgreSQL",
            space=space,
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="active",
            supersedes=None,
            superseded_by=None,
        )
        provenance = _make_provenance("dec-1", "decision")

        repo.save(decision, provenance)
        result = repo.get(space, "dec-1")

        assert result is not None
        assert result.id == "dec-1"
        assert result.statement == "Use PostgreSQL"
        assert result.lifecycle_state == "active"
        assert result.invalidation_time is None

    @pytest.mark.integration
    def test_list_by_space_filters_correctly(self, neo4j_driver) -> None:
        """list_by_space returns only decisions in the specified space."""
        from memorable.storage.neo4j.repository import Neo4jDecisionRepository

        repo = Neo4jDecisionRepository(driver=neo4j_driver)
        space_a = _unique_name("test-a-")
        space_b = _unique_name("test-b-")
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)

        d1 = Decision(
            id="d1",
            statement="Use Neo4j",
            space=space_a,
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="active",
            supersedes=None,
            superseded_by=None,
        )
        d2 = Decision(
            id="d2",
            statement="Use GraphQL",
            space=space_b,
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="active",
            supersedes=None,
            superseded_by=None,
        )

        repo.save(d1, _make_provenance("d1", "decision"))
        repo.save(d2, _make_provenance("d2", "decision"))

        results = repo.list_by_space(space_a)
        assert len(results) == 1
        assert results[0].id == "d1"

    @pytest.mark.integration
    def test_mark_superseded_updates_properties(self, neo4j_driver) -> None:
        """mark_superseded updates superseded_by, invalidation_time, lifecycle."""
        from memorable.storage.neo4j.repository import Neo4jDecisionRepository

        repo = Neo4jDecisionRepository(driver=neo4j_driver)
        space = _unique_name()
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)
        inv_time = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)

        decision = Decision(
            id="dec-1",
            statement="Use MySQL",
            space=space,
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="active",
            supersedes=None,
            superseded_by=None,
        )
        repo.save(decision, _make_provenance("dec-1", "decision"))

        repo.mark_superseded(space, "dec-1", "dec-2", inv_time)

        result = repo.get(space, "dec-1")
        assert result is not None
        assert result.superseded_by == "dec-2"
        assert result.invalidation_time == inv_time
        assert result.lifecycle_state == "superseded"

    @pytest.mark.integration
    def test_cross_space_isolation(self, neo4j_driver) -> None:
        """Writing to space A then querying space B returns nothing."""
        from memorable.storage.neo4j.repository import Neo4jDecisionRepository

        repo = Neo4jDecisionRepository(driver=neo4j_driver)
        space_a = _unique_name("test-write-")
        space_b = _unique_name("test-read-")
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)

        decision = Decision(
            id="dec-1",
            statement="Use X",
            space=space_a,
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="active",
            supersedes=None,
            superseded_by=None,
        )
        repo.save(decision, _make_provenance("dec-1", "decision"))

        assert repo.get(space_b, "dec-1") is None
        assert repo.list_by_space(space_b) == []


# --- Task integration tests ---


class TestTaskIntegration:
    """Integration tests for Neo4jTaskRepository."""

    @pytest.mark.integration
    def test_save_then_get_returns_same_data(self, neo4j_driver) -> None:
        """Save then get returns the same Task."""
        from memorable.storage.neo4j.repository import Neo4jTaskRepository

        repo = Neo4jTaskRepository(driver=neo4j_driver)
        space = _unique_name()
        ts = datetime(2025, 4, 1, 8, 0, 0, tzinfo=UTC)
        task = Task(
            id="task-1",
            title="Implement auth",
            space=space,
            lifecycle_state="open",
            validity_time=ts,
            completion_time=None,
            completion_event_id=None,
        )
        provenance = _make_provenance("task-1", "task")

        repo.save(task, provenance)
        result = repo.get(space=space, task_id="task-1")

        assert result is not None
        assert result.id == "task-1"
        assert result.title == "Implement auth"
        assert result.lifecycle_state == "open"
        assert result.completion_time is None

    @pytest.mark.integration
    def test_list_by_space_filters_correctly(self, neo4j_driver) -> None:
        """list_by_space returns only tasks in the specified space."""
        from memorable.storage.neo4j.repository import Neo4jTaskRepository

        repo = Neo4jTaskRepository(driver=neo4j_driver)
        space_a = _unique_name("test-a-")
        space_b = _unique_name("test-b-")
        ts = datetime(2025, 4, 1, 8, 0, 0, tzinfo=UTC)

        t1 = Task(
            id="t1",
            title="Task A",
            space=space_a,
            lifecycle_state="open",
            validity_time=ts,
            completion_time=None,
            completion_event_id=None,
        )
        t2 = Task(
            id="t2",
            title="Task B",
            space=space_b,
            lifecycle_state="open",
            validity_time=ts,
            completion_time=None,
            completion_event_id=None,
        )

        repo.save(t1, _make_provenance("t1", "task"))
        repo.save(t2, _make_provenance("t2", "task"))

        results = repo.list_by_space(space_a)
        assert len(results) == 1
        assert results[0].id == "t1"

    @pytest.mark.integration
    def test_complete_updates_lifecycle(self, neo4j_driver) -> None:
        """complete sets lifecycle_state, completion_time, completion_event_id."""
        from memorable.storage.neo4j.repository import Neo4jTaskRepository

        repo = Neo4jTaskRepository(driver=neo4j_driver)
        space = _unique_name()
        ts = datetime(2025, 4, 1, 8, 0, 0, tzinfo=UTC)
        comp_time = datetime(2025, 4, 5, 16, 0, 0, tzinfo=UTC)

        task = Task(
            id="task-1",
            title="Implement auth",
            space=space,
            lifecycle_state="open",
            validity_time=ts,
            completion_time=None,
            completion_event_id=None,
        )
        repo.save(task, _make_provenance("task-1", "task"))

        repo.complete(
            space=space,
            task_id="task-1",
            completion_time=comp_time,
            completion_event_id="evt-99",
        )

        result = repo.get(space=space, task_id="task-1")
        assert result is not None
        assert result.lifecycle_state == "completed"
        assert result.completion_time == comp_time
        assert result.completion_event_id == "evt-99"

    @pytest.mark.integration
    def test_cross_space_isolation(self, neo4j_driver) -> None:
        """Writing to space A then querying space B returns nothing."""
        from memorable.storage.neo4j.repository import Neo4jTaskRepository

        repo = Neo4jTaskRepository(driver=neo4j_driver)
        space_a = _unique_name("test-write-")
        space_b = _unique_name("test-read-")
        ts = datetime(2025, 4, 1, 8, 0, 0, tzinfo=UTC)

        task = Task(
            id="task-1",
            title="Do thing",
            space=space_a,
            lifecycle_state="open",
            validity_time=ts,
            completion_time=None,
            completion_event_id=None,
        )
        repo.save(task, _make_provenance("task-1", "task"))

        assert repo.get(space=space_b, task_id="task-1") is None
        assert repo.list_by_space(space_b) == []


# --- Observation integration tests ---


class TestObservationIntegration:
    """Integration tests for Neo4jObservationRepository."""

    @pytest.mark.integration
    def test_save_then_get_returns_same_data(self, neo4j_driver) -> None:
        """Save then get returns the same Observation."""
        from memorable.storage.neo4j.repository import Neo4jObservationRepository

        repo = Neo4jObservationRepository(driver=neo4j_driver)
        space = _unique_name()
        ts = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
        observation = Observation(
            id="obs-1",
            statement="Team prefers async communication.",
            space=space,
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        provenance = _make_provenance("obs-1", "observation")

        repo.save(observation, provenance)
        result = repo.get(space, "obs-1")

        assert result is not None
        assert result.id == "obs-1"
        assert result.statement == "Team prefers async communication."
        assert result.lifecycle_state == "current"
        assert result.invalidation_time is None

    @pytest.mark.integration
    def test_list_by_space_filters_correctly(self, neo4j_driver) -> None:
        """list_by_space returns only observations in the specified space."""
        from memorable.storage.neo4j.repository import Neo4jObservationRepository

        repo = Neo4jObservationRepository(driver=neo4j_driver)
        space_a = _unique_name("test-a-")
        space_b = _unique_name("test-b-")
        ts = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)

        o1 = Observation(
            id="o1",
            statement="Fact A",
            space=space_a,
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        o2 = Observation(
            id="o2",
            statement="Fact B",
            space=space_b,
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )

        repo.save(o1, _make_provenance("o1", "observation"))
        repo.save(o2, _make_provenance("o2", "observation"))

        results = repo.list_by_space(space_a)
        assert len(results) == 1
        assert results[0].id == "o1"

    @pytest.mark.integration
    def test_mark_superseded_updates_properties(self, neo4j_driver) -> None:
        """mark_superseded updates superseded_by, invalidation_time, lifecycle."""
        from memorable.storage.neo4j.repository import Neo4jObservationRepository

        repo = Neo4jObservationRepository(driver=neo4j_driver)
        space = _unique_name()
        ts = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
        inv_time = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)

        observation = Observation(
            id="obs-1",
            statement="Old fact",
            space=space,
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        repo.save(observation, _make_provenance("obs-1", "observation"))

        repo.mark_superseded(space, "obs-1", "obs-2", inv_time)

        result = repo.get(space, "obs-1")
        assert result is not None
        assert result.superseded_by == "obs-2"
        assert result.invalidation_time == inv_time
        assert result.lifecycle_state == "superseded"

    @pytest.mark.integration
    def test_invalidate_sets_lifecycle(self, neo4j_driver) -> None:
        """invalidate marks the observation as invalidated."""
        from memorable.storage.neo4j.repository import Neo4jObservationRepository

        repo = Neo4jObservationRepository(driver=neo4j_driver)
        space = _unique_name()
        ts = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
        inv_time = datetime(2026, 5, 26, 14, 0, 0, tzinfo=UTC)

        observation = Observation(
            id="obs-1",
            statement="Incorrect fact",
            space=space,
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        repo.save(observation, _make_provenance("obs-1", "observation"))

        repo.invalidate(space, "obs-1", inv_time)

        result = repo.get(space, "obs-1")
        assert result is not None
        assert result.lifecycle_state == "invalidated"
        assert result.invalidation_time == inv_time

    @pytest.mark.integration
    def test_correct_updates_statement(self, neo4j_driver) -> None:
        """correct updates the statement without changing lifecycle."""
        from memorable.storage.neo4j.repository import Neo4jObservationRepository

        repo = Neo4jObservationRepository(driver=neo4j_driver)
        space = _unique_name()
        ts = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)

        observation = Observation(
            id="obs-1",
            statement="Typo in fact",
            space=space,
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        repo.save(observation, _make_provenance("obs-1", "observation"))

        repo.correct(space, "obs-1", "Corrected fact")

        result = repo.get(space, "obs-1")
        assert result is not None
        assert result.statement == "Corrected fact"
        assert result.lifecycle_state == "current"

    @pytest.mark.integration
    def test_cross_space_isolation(self, neo4j_driver) -> None:
        """Writing to space A then querying space B returns nothing."""
        from memorable.storage.neo4j.repository import Neo4jObservationRepository

        repo = Neo4jObservationRepository(driver=neo4j_driver)
        space_a = _unique_name("test-write-")
        space_b = _unique_name("test-read-")
        ts = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)

        observation = Observation(
            id="obs-1",
            statement="Some fact",
            space=space_a,
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        repo.save(observation, _make_provenance("obs-1", "observation"))

        assert repo.get(space_b, "obs-1") is None
        assert repo.list_by_space(space_b) == []

    @pytest.mark.integration
    def test_get_provenance_after_save(self, neo4j_driver) -> None:
        """get_provenance returns the correct provenance after save."""
        from memorable.storage.neo4j.repository import Neo4jObservationRepository

        repo = Neo4jObservationRepository(driver=neo4j_driver)
        space = _unique_name()
        ts = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
        observation = Observation(
            id="obs-1",
            statement="A fact",
            space=space,
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        provenance = Provenance(
            record_id="obs-1",
            record_kind="observation",
            source_id="src-42",
            episode_id="ep-7",
            writer="agent-x",
            reason="discovered",
            creation_time=ts,
            validity_time=ts,
        )

        repo.save(observation, provenance)
        result = repo.get_provenance(space, "obs-1")

        assert result is not None
        assert result.record_id == "obs-1"
        assert result.record_kind == "observation"
        assert result.source_id == "src-42"
        assert result.writer == "agent-x"


# --- Schema bootstrap integration tests ---


class TestEnsureAllConstraintsIntegration:
    """Integration tests for ensure_all_constraints."""

    @pytest.mark.integration
    def test_constraint_creation_is_idempotent(self, neo4j_driver) -> None:
        """Running ensure_all_constraints twice does not error."""
        from memorable.storage.neo4j.repository import ensure_all_constraints

        ensure_all_constraints(neo4j_driver)
        ensure_all_constraints(neo4j_driver)
