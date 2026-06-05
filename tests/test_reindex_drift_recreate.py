"""Reindex drops and recreates the persistent Embedding index (PRD #195, #198).

`memorable reindex` is the sanctioned repair for embedding provider/model/
dimension drift. Beyond backfilling Embeddings, it must recreate the vector
index at the currently configured dimensions so dimension drift is resolved in
one operation. Storage-specific drop/recreate Cypher stays inside the Neo4j
adapter; the application service only orchestrates through the retrieval port.
"""

from __future__ import annotations

import textwrap
import uuid
from datetime import UTC, datetime

import pytest

from memorable.core.application import (
    RememberDecisionService,
    RememberEntityService,
)
from memorable.core.profile import load_profile_from_yaml
from memorable.core.repositories import (
    InMemoryDecisionRepository,
    InMemoryEntityRepository,
    InMemoryObservationRepository,
    InMemoryRelationRepository,
    InMemoryTaskRepository,
)
from memorable.retrieval.models import EmbeddingRecord, SearchCandidate
from memorable.retrieval.service import HybridRetrievalService


class _FakeEmbeddingProvider:
    def __init__(self, dimensions: int = 16) -> None:
        self.dimensions = dimensions

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "unit-test"

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for index, char in enumerate(text.encode("utf-8")):
            vector[index % self.dimensions] += float(char)
        return vector


class _RecordingIndex:
    """Retrieval index spy that records the order of operations."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def recreate_index(self, dimensions: int) -> None:
        self.events.append(("recreate_index", dimensions))

    def clear_space(self, space: str) -> None:
        self.events.append(("clear_space", space))

    def store(self, record: EmbeddingRecord) -> None:
        self.events.append(("store", record.source_id))

    def delete(self, *, space: str, source_id: str, source_kind: str) -> None: ...

    def records(self, *, space: str | None = None) -> list[EmbeddingRecord]:
        return []

    def search(
        self,
        space: str,
        query_vector: list[float],
        top_k: int = 10,
        *,
        provider_name: str | None = None,
        model_name: str | None = None,
        dimensions: int | None = None,
    ) -> list[SearchCandidate]:
        return []


_PROFILE_YAML = textwrap.dedent(
    """\
    version: 1
    space:
      name: test-space
      description: Reindex drift recreate fixture
    entities:
      - name: Component
    records:
      - name: ArchitectureDecision
        extends: Decision
    """
)


def _build_service(index: _RecordingIndex, dimensions: int) -> HybridRetrievalService:
    entity_repo = InMemoryEntityRepository()
    decision_repo = InMemoryDecisionRepository()
    task_repo = InMemoryTaskRepository()
    observation_repo = InMemoryObservationRepository()
    relation_repo = InMemoryRelationRepository()
    return HybridRetrievalService(
        entity_repo=entity_repo,
        decision_repo=decision_repo,
        task_repo=task_repo,
        observation_repo=observation_repo,
        relation_repo=relation_repo,
        embedding_provider=_FakeEmbeddingProvider(dimensions=dimensions),
        dimensions=dimensions,
        retrieval_index=index,
    )


def test_reindex_recreates_vector_index_at_configured_dimensions_first() -> None:
    index = _RecordingIndex()
    service = _build_service(index, dimensions=16)

    service.reindex("test-space")

    assert index.events[0] == ("recreate_index", 16)


def _live_vector_index_dimensions(driver, name: str) -> int | None:
    with driver.session() as session:
        result = session.run(
            "SHOW INDEXES YIELD name, type, options "
            "WHERE name = $name AND type = 'VECTOR' "
            "RETURN options AS options",
            name=name,
        )
        record = result.single()
    if record is None:
        return None
    options = record["options"]
    if not isinstance(options, dict):
        return None
    index_config = options.get("indexConfig")
    if not isinstance(index_config, dict):
        return None
    dimensions = index_config.get("vector.dimensions")
    return dimensions if isinstance(dimensions, int) else None


@pytest.mark.integration
def test_neo4j_recreate_index_resolves_dimension_drift() -> None:
    try:
        from live_neo4j import build_live_neo4j_driver

        from memorable.storage.neo4j.repository import ensure_all_constraints
        from memorable.storage.neo4j.retrieval_index import Neo4jRetrievalIndex
        from memorable.storage.neo4j.schema import EXPECTED_VECTOR_INDEX
    except Exception:
        pytest.skip("Neo4j dependencies are not available")

    driver = build_live_neo4j_driver()
    try:
        try:
            driver.verify_connectivity()
        except Exception:
            pytest.skip("Neo4j is not available")

        index_name = EXPECTED_VECTOR_INDEX.name
        # Start from a stale index built for the wrong (drifted) dimensions.
        with driver.session() as session:
            session.run(f"DROP INDEX {index_name} IF EXISTS")
        ensure_all_constraints(driver, vector_dimensions=8)
        with driver.session() as session:
            session.run("CALL db.awaitIndex($name, 30)", name=index_name)
        assert _live_vector_index_dimensions(driver, index_name) == 8

        index = Neo4jRetrievalIndex(driver)
        index.recreate_index(32)
        with driver.session() as session:
            session.run("CALL db.awaitIndex($name, 30)", name=index_name)

        assert _live_vector_index_dimensions(driver, index_name) == 32
    finally:
        # Leave the index at the repo default so other tests are unaffected.
        with driver.session() as session:
            session.run(f"DROP INDEX {index_name} IF EXISTS")
        try:
            from memorable.storage.neo4j.repository import ensure_all_constraints

            ensure_all_constraints(driver, vector_dimensions=384)
        except Exception:
            pass
        driver.close()


@pytest.mark.integration
def test_reindex_recreates_index_and_backfills_counts_through_neo4j() -> None:
    try:
        from live_neo4j import build_live_neo4j_driver

        from memorable.storage.neo4j.repository import ensure_all_constraints
        from memorable.storage.neo4j.retrieval_index import Neo4jRetrievalIndex
        from memorable.storage.neo4j.schema import EXPECTED_VECTOR_INDEX
    except Exception:
        pytest.skip("Neo4j dependencies are not available")

    driver = build_live_neo4j_driver()
    index_name = EXPECTED_VECTOR_INDEX.name
    space = f"test-reindex-drift-{uuid.uuid4().hex[:8]}"
    try:
        try:
            driver.verify_connectivity()
        except Exception:
            pytest.skip("Neo4j is not available")

        # Pre-existing dimension drift: a stale index built for 8 dims.
        with driver.session() as session:
            session.run(f"DROP INDEX {index_name} IF EXISTS")
        ensure_all_constraints(driver, vector_dimensions=8)
        with driver.session() as session:
            session.run("CALL db.awaitIndex($name, 30)", name=index_name)
        assert _live_vector_index_dimensions(driver, index_name) == 8

        profile = load_profile_from_yaml(_PROFILE_YAML)
        at = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
        source = "source:reindex-drift"
        entity_repo = InMemoryEntityRepository()
        decision_repo = InMemoryDecisionRepository()
        task_repo = InMemoryTaskRepository()
        observation_repo = InMemoryObservationRepository()
        relation_repo = InMemoryRelationRepository()
        RememberEntityService(repository=entity_repo, profile=profile).remember(
            space=space,
            entity_id="entity:auth",
            entity_type="Component",
            name="Auth component",
            source_id=source,
            at=at,
        )
        RememberDecisionService(repository=decision_repo, profile=profile).remember(
            space=space,
            decision_id="decision:retention",
            statement="Keep a persistent Embedding index for retention search",
            source_id=source,
            at=at,
        )

        index = Neo4jRetrievalIndex(driver)
        service = HybridRetrievalService(
            entity_repo=entity_repo,
            decision_repo=decision_repo,
            task_repo=task_repo,
            observation_repo=observation_repo,
            relation_repo=relation_repo,
            embedding_provider=_FakeEmbeddingProvider(dimensions=32),
            dimensions=32,
            retrieval_index=index,
        )

        result = service.reindex(space)
        with driver.session() as session:
            session.run("CALL db.awaitIndex($name, 30)", name=index_name)

        # Drift resolved: live index now matches the configured dimensions.
        assert _live_vector_index_dimensions(driver, index_name) == 32
        # Backfill counts reflect every retrievable record kind.
        assert result.indexed_by_kind == {
            "Entity": 1,
            "Decision": 1,
            "Task": 0,
            "Observation": 0,
            "Relation": 0,
        }
        assert result.indexed_total == 2
        # Embeddings are persisted in Neo4j and retrievable through the port.
        persisted = {record.source_id for record in index.records(space=space)}
        assert persisted == {"entity:auth", "decision:retention"}
    finally:
        with driver.session() as session:
            session.run(
                "MATCH (embedding:Embedding) "
                "WHERE embedding.space STARTS WITH 'test-reindex-drift-' "
                "DELETE embedding"
            )
            session.run(f"DROP INDEX {index_name} IF EXISTS")
        try:
            from memorable.storage.neo4j.repository import ensure_all_constraints

            ensure_all_constraints(driver, vector_dimensions=384)
        except Exception:
            pass
        driver.close()


@pytest.mark.integration
def test_reindex_on_empty_space_recreates_index_with_zero_counts() -> None:
    try:
        from live_neo4j import build_live_neo4j_driver

        from memorable.storage.neo4j.repository import ensure_all_constraints
        from memorable.storage.neo4j.retrieval_index import Neo4jRetrievalIndex
        from memorable.storage.neo4j.schema import EXPECTED_VECTOR_INDEX
    except Exception:
        pytest.skip("Neo4j dependencies are not available")

    driver = build_live_neo4j_driver()
    index_name = EXPECTED_VECTOR_INDEX.name
    space = f"test-reindex-drift-empty-{uuid.uuid4().hex[:8]}"
    try:
        try:
            driver.verify_connectivity()
        except Exception:
            pytest.skip("Neo4j is not available")

        with driver.session() as session:
            session.run(f"DROP INDEX {index_name} IF EXISTS")
        ensure_all_constraints(driver, vector_dimensions=8)
        with driver.session() as session:
            session.run("CALL db.awaitIndex($name, 30)", name=index_name)

        index = Neo4jRetrievalIndex(driver)
        service = HybridRetrievalService(
            entity_repo=InMemoryEntityRepository(),
            decision_repo=InMemoryDecisionRepository(),
            task_repo=InMemoryTaskRepository(),
            observation_repo=InMemoryObservationRepository(),
            relation_repo=InMemoryRelationRepository(),
            embedding_provider=_FakeEmbeddingProvider(dimensions=32),
            dimensions=32,
            retrieval_index=index,
        )

        result = service.reindex(space)
        with driver.session() as session:
            session.run("CALL db.awaitIndex($name, 30)", name=index_name)

        assert _live_vector_index_dimensions(driver, index_name) == 32
        assert result.indexed_total == 0
        assert result.indexed_by_kind == {
            "Entity": 0,
            "Decision": 0,
            "Task": 0,
            "Observation": 0,
            "Relation": 0,
        }
    finally:
        with driver.session() as session:
            session.run(f"DROP INDEX {index_name} IF EXISTS")
        try:
            from memorable.storage.neo4j.repository import ensure_all_constraints

            ensure_all_constraints(driver, vector_dimensions=384)
        except Exception:
            pass
        driver.close()
