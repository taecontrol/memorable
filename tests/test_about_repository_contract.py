"""Contract tests for AboutRepository implementations."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

neo4j_available = False
try:
    from neo4j import GraphDatabase

    from memorable.storage.neo4j.config import Neo4jConfig

    _config = Neo4jConfig.from_env()
    _driver = GraphDatabase.driver(_config.uri, auth=(_config.user, _config.password))
    _driver.verify_connectivity()
    _driver.close()
    neo4j_available = True
except Exception:
    pass


def _unique_space() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


AT = datetime(2026, 5, 31, 9, 0, tzinfo=UTC)


@pytest.fixture
def inmemory_about_repo():
    from memorable.core.repositories import InMemoryAboutRepository

    return InMemoryAboutRepository()


@pytest.fixture
def neo4j_about_repo() -> Iterator[object]:
    if not neo4j_available:
        pytest.skip("Neo4j is not available")

    from neo4j import GraphDatabase

    from memorable.storage.neo4j.config import Neo4jConfig
    from memorable.storage.neo4j.repository import Neo4jAboutRepository

    config = Neo4jConfig.from_env()
    driver = GraphDatabase.driver(config.uri, auth=(config.user, config.password))
    repo = Neo4jAboutRepository(driver)
    yield repo
    with driver.session() as session:
        session.run(
            "MATCH (r:Record)-[a:ABOUT]->(:Entity) "
            "WHERE r.space STARTS WITH 'test-' DELETE a"
        )
        for label in ("Decision", "Observation", "Task", "Entity"):
            session.run(
                f"MATCH (p:Provenance)-[r:PROVENANCE_OF]->(n:{label}) "
                "WHERE n.space STARTS WITH 'test-' DELETE r, p"
            )
            session.run(f"MATCH (n:{label}) WHERE n.space STARTS WITH 'test-' DELETE n")
    driver.close()


ALL_REPOS = [
    "inmemory_about_repo",
    pytest.param("neo4j_about_repo", marks=pytest.mark.integration),
]


def _prepare_link(
    repo: object,
    space: str,
    record_id: str,
    entity_ids: list[str],
) -> None:
    if repo.__class__.__name__ != "Neo4jAboutRepository":
        return

    from memorable.core.models import Decision, Entity, Observation, Provenance, Task
    from memorable.storage.neo4j.repository import (
        Neo4jDecisionRepository,
        Neo4jEntityRepository,
        Neo4jObservationRepository,
        Neo4jTaskRepository,
    )

    provenance = Provenance(
        record_id=record_id,
        record_kind="test",
        source_id="source:test",
        episode_id="episode:test",
        writer="test-agent",
        reason="about contract setup",
        creation_time=AT,
        validity_time=AT,
    )
    entity_repo = Neo4jEntityRepository(repo._driver)
    for entity_id in entity_ids:
        entity_repo.save(
            Entity(
                id=entity_id,
                entity_type="test-entity",
                name=entity_id,
                space=space,
            ),
            provenance,
        )

    if record_id.startswith("decision:"):
        Neo4jDecisionRepository(repo._driver).save(
            Decision(
                id=record_id,
                statement=record_id,
                space=space,
                validity_time=AT,
                invalidation_time=None,
                lifecycle_state="current",
                supersedes=None,
                superseded_by=None,
            ),
            provenance,
        )
    elif record_id.startswith("observation:"):
        Neo4jObservationRepository(repo._driver).save(
            Observation(
                id=record_id,
                statement=record_id,
                space=space,
                validity_time=AT,
                invalidation_time=None,
                lifecycle_state="current",
                supersedes=None,
                superseded_by=None,
            ),
            provenance,
        )
    elif record_id.startswith("task:"):
        Neo4jTaskRepository(repo._driver).save(
            Task(
                id=record_id,
                title=record_id,
                space=space,
                lifecycle_state="open",
                validity_time=AT,
                completion_time=None,
                completion_event_id=None,
            ),
            provenance,
        )


def _link(repo: object, space: str, record_id: str, entity_ids: list[str]) -> None:
    _prepare_link(repo, space, record_id, entity_ids)
    repo.link(space, record_id, entity_ids)


def _run_query(repo: object, query: str, **params: object) -> list[object]:
    with repo._driver.session() as session:
        return list(session.run(query, **params))


def test_about_repository_port_methods() -> None:
    from memorable.core.ports import AboutRepository

    methods = {name for name in vars(AboutRepository) if not name.startswith("_")}
    assert methods == {
        "link",
        "unlink",
        "entities_for_record",
        "records_for_entity",
    }


def test_application_context_wires_inmemory_about_repository() -> None:
    from memorable.core.context import ApplicationContext
    from memorable.core.repositories import InMemoryAboutRepository

    ctx = ApplicationContext()

    assert isinstance(ctx.about_repo, InMemoryAboutRepository)


def test_application_context_reset_replaces_about_repository() -> None:
    from memorable.core.context import ApplicationContext

    ctx = ApplicationContext()
    ctx.about_repo.link("space", "decision:1", ["entity:1"])

    ctx.reset()

    assert ctx.about_repo.entities_for_record("space", "decision:1") == []


class TestAboutRepositoryContract:
    """About links are observable through both directional queries."""

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_link_record_to_entity(self, repo_fixture, request) -> None:
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()

        _link(repo, space, "decision:1", ["entity:build-2"])

        assert repo.entities_for_record(space, "decision:1") == ["entity:build-2"]
        assert repo.records_for_entity(space, "entity:build-2") == ["decision:1"]

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_record_can_link_to_many_entities(self, repo_fixture, request) -> None:
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()

        _link(repo, space, "observation:1", ["entity:phase", "entity:workout"])

        assert repo.entities_for_record(space, "observation:1") == [
            "entity:phase",
            "entity:workout",
        ]

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_many_records_can_link_to_one_entity(self, repo_fixture, request) -> None:
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()

        _link(repo, space, "decision:1", ["entity:build-2"])
        _link(repo, space, "task:1", ["entity:build-2"])

        assert repo.records_for_entity(space, "entity:build-2") == [
            "decision:1",
            "task:1",
        ]

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_queries_are_scoped_to_memory_space(self, repo_fixture, request) -> None:
        repo = request.getfixturevalue(repo_fixture)
        space_a = _unique_space()
        space_b = _unique_space()

        _link(repo, space_a, "decision:1", ["entity:build-2"])
        _link(repo, space_b, "decision:1", ["entity:build-2"])

        assert repo.entities_for_record(space_a, "decision:1") == ["entity:build-2"]
        assert repo.records_for_entity(space_a, "entity:build-2") == ["decision:1"]

    @pytest.mark.parametrize("repo_fixture", ALL_REPOS)
    def test_unlink_hard_removes_record_edges(self, repo_fixture, request) -> None:
        repo = request.getfixturevalue(repo_fixture)
        space = _unique_space()

        _link(repo, space, "decision:1", ["entity:build-2", "entity:phase"])
        _link(repo, space, "decision:2", ["entity:build-2"])

        repo.unlink(space, "decision:1")

        assert repo.entities_for_record(space, "decision:1") == []
        assert repo.records_for_entity(space, "entity:phase") == []
        assert repo.records_for_entity(space, "entity:build-2") == ["decision:2"]


@pytest.mark.integration
def test_neo4j_about_relationship_has_no_properties(neo4j_about_repo) -> None:
    repo = neo4j_about_repo
    space = _unique_space()

    _link(repo, space, "decision:1", ["entity:build-2"])

    rows = _run_query(
        repo,
        "MATCH (:Record {space: $space, id: $record_id})"
        "-[about:ABOUT]->(:Entity {space: $space, id: $entity_id}) "
        "RETURN properties(about) AS properties",
        space=space,
        record_id="decision:1",
        entity_id="entity:build-2",
    )
    assert [row["properties"] for row in rows] == [{}]


@pytest.mark.integration
def test_neo4j_schema_rejects_duplicate_memoryrecord_ids(neo4j_about_repo) -> None:
    from neo4j.exceptions import Neo4jError

    from memorable.storage.neo4j.schema import (
        EXPECTED_UNIQUENESS_CONSTRAINTS,
        create_uniqueness_constraint_cypher,
    )

    repo = neo4j_about_repo
    space = _unique_space()
    constraint = next(
        constraint
        for constraint in EXPECTED_UNIQUENESS_CONSTRAINTS
        if constraint.label == "Record"
    )
    _run_query(repo, create_uniqueness_constraint_cypher(constraint))

    with pytest.raises(Neo4jError):
        _run_query(
            repo,
            "CREATE (:Record:Decision {space: $space, id: $record_id}), "
            "(:Record:Task {space: $space, id: $record_id})",
            space=space,
            record_id="record:duplicate",
        )

    # Relation now carries the MemoryRecord-wide :Record label, so it
    # participates in the same space+id uniqueness constraint.
    relation_space = _unique_space()
    with pytest.raises(Neo4jError):
        _run_query(
            repo,
            "CREATE (:Record:Relation {space: $space, id: $record_id}), "
            "(:Record:Decision {space: $space, id: $record_id})",
            space=relation_space,
            record_id="record:duplicate-relation",
        )
