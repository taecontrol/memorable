from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from memorable.config import RuntimeConfig, SQLiteSettings, StorageSettings
from memorable.core.application import (
    CompleteTaskService,
    InvalidateService,
    RememberDecisionService,
    RememberEntityService,
    RememberObservationService,
    RememberRelationService,
    RememberTaskService,
)
from memorable.core.profile import load_profile_from_yaml
from memorable.retrieval.index import InMemoryEmbeddingIndex, RetrievalIndex
from memorable.retrieval.models import EmbeddingRecord
from memorable.retrieval.service import (
    EmbeddingIndexCompatibilityError,
    build_retrieval_service,
)
from memorable.storage.production import build_production_context
from memorable.storage.sqlite.connection import connect
from memorable.storage.sqlite.retrieval_index import SqliteVecRetrievalIndex

PROFILE_YAML = """
version: 1
space:
  name: test-space
  description: sqlite-vec retrieval index tests
entities:
  - name: Component
relations:
  - name: depends-on
"""


class LifecycleMarkerEmbeddingProvider:
    @property
    def provider_name(self) -> str:
        return "lifecycle-marker"

    @property
    def model_name(self) -> str:
        return "deterministic-test"

    def embed(self, text: str) -> list[float]:
        lowered = text.lower()
        if "superseded retrieval marker" in lowered:
            return [1.0, 0.0, 0.0]
        if "completed retrieval marker" in lowered:
            return [0.0, 1.0, 0.0]
        if "invalidated retrieval marker" in lowered:
            return [0.0, 0.0, 1.0]
        return [0.5, 0.5, 0.0]


class DimensionedEmbeddingProvider:
    def __init__(self, dimensions: int) -> None:
        self._dimensions = dimensions

    @property
    def provider_name(self) -> str:
        return "dimensioned-test"

    @property
    def model_name(self) -> str:
        return "deterministic-test"

    def embed(self, text: str) -> list[float]:
        vector = [1.0] + [0.0] * (self._dimensions - 1)
        return vector


def _sqlite_config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(
        storage=StorageSettings(backend="sqlite"),
        sqlite=SQLiteSettings(path=str(tmp_path / "memory.db")),
        base_path=tmp_path,
    )


def _embedding(
    *,
    source_id: str,
    space: str = "test-space",
    vector: list[float],
    provider_name: str = "provider-a",
    model_name: str = "model-a",
    source_kind: str = "Decision",
) -> EmbeddingRecord:
    at = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    return EmbeddingRecord(
        source_id=source_id,
        source_kind=source_kind,
        space=space,
        indexable_text=f"Indexable Text for {source_id}",
        vector=vector,
        provider_name=provider_name,
        model_name=model_name,
        dimensions=len(vector),
        indexable_text_hash=f"hash:{source_id}",
        indexable_text_version="1",
        created_at=at,
        updated_at=at,
    )


def test_sqlite_vec_index_persists_embeddings_and_ranks_candidates(
    tmp_path: Path,
) -> None:
    handle = connect(_sqlite_config(tmp_path))
    try:
        index = SqliteVecRetrievalIndex(handle)
        index.store(_embedding(source_id="decision:near", vector=[1.0, 0.0]))
        index.store(_embedding(source_id="decision:far", vector=[0.0, 1.0]))
    finally:
        handle.close()

    reopened = connect(_sqlite_config(tmp_path))
    try:
        index = SqliteVecRetrievalIndex(reopened)

        records = index.records(space="test-space")
        results = index.search(
            space="test-space",
            query_vector=[1.0, 0.0],
            top_k=2,
            provider_name="provider-a",
            model_name="model-a",
            dimensions=2,
        )
    finally:
        reopened.close()

    assert [record.source_id for record in records] == [
        "decision:far",
        "decision:near",
    ]
    assert [result.source_id for result in results] == [
        "decision:near",
        "decision:far",
    ]
    assert results[0].score == pytest.approx(1.0)
    assert results[1].score == pytest.approx(0.0)


@pytest.fixture(params=["in-memory", "sqlite-vec"])
def retrieval_index(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "in-memory":
        yield InMemoryEmbeddingIndex()
        return

    handle = connect(_sqlite_config(tmp_path))
    try:
        yield SqliteVecRetrievalIndex(handle)
    finally:
        handle.close()


def test_retrieval_index_contract_filters_compatible_embeddings_before_top_k(
    retrieval_index: RetrievalIndex,
) -> None:
    retrieval_index.store(_embedding(source_id="decision:target", vector=[0.8, 0.6]))
    for index in range(20):
        retrieval_index.store(
            _embedding(
                source_id=f"decision:incompatible-provider-{index}",
                vector=[1.0, 0.0],
                provider_name="provider-b",
            )
        )
        retrieval_index.store(
            _embedding(
                source_id=f"decision:other-space-{index}",
                space="other-space",
                vector=[1.0, 0.0],
            )
        )

    results = retrieval_index.search(
        space="test-space",
        query_vector=[1.0, 0.0],
        top_k=1,
        provider_name="provider-a",
        model_name="model-a",
        dimensions=2,
    )

    assert [result.source_id for result in results] == ["decision:target"]
    assert results[0].score == pytest.approx(0.8)


def test_retrieval_index_contract_delete_and_clear_space_remove_embeddings(
    retrieval_index: RetrievalIndex,
) -> None:
    retrieval_index.store(_embedding(source_id="decision:remove", vector=[1.0, 0.0]))
    retrieval_index.store(_embedding(source_id="decision:keep", vector=[0.0, 1.0]))
    retrieval_index.store(
        _embedding(
            source_id="decision:other-space",
            space="other-space",
            vector=[1.0, 0.0],
        )
    )

    retrieval_index.delete(
        space="test-space",
        source_id="decision:remove",
        source_kind="Decision",
    )
    retrieval_index.clear_space("other-space")

    assert [
        record.source_id for record in retrieval_index.records(space="test-space")
    ] == ["decision:keep"]
    assert retrieval_index.records(space="other-space") == []


def test_sqlite_vec_recreate_index_keeps_records_and_fails_loud_for_old_dimension(
    tmp_path: Path,
) -> None:
    handle = connect(_sqlite_config(tmp_path))
    try:
        index = SqliteVecRetrievalIndex(handle)
        index.store(_embedding(source_id="decision:old-dim", vector=[1.0, 0.0]))

        index.recreate_index(3)
        index.store(_embedding(source_id="decision:new-dim", vector=[1.0, 0.0, 0.0]))

        records = index.records(space="test-space")
        with pytest.raises(ValueError) as error:
            index.search(
                space="test-space",
                query_vector=[1.0, 0.0],
                top_k=1,
                provider_name="provider-a",
                model_name="model-a",
                dimensions=2,
            )
        new_dimension_results = index.search(
            space="test-space",
            query_vector=[1.0, 0.0, 0.0],
            top_k=1,
            provider_name="provider-a",
            model_name="model-a",
            dimensions=3,
        )
    finally:
        handle.close()

    assert {record.source_id for record in records} == {
        "decision:old-dim",
        "decision:new-dim",
    }
    message = str(error.value)
    assert "SQLite Embedding index was created for 3 dimensions" in message
    assert "active search needs 2 dimensions" in message
    assert "memorable reindex --space test-space" in message
    assert [result.source_id for result in new_dimension_results] == [
        "decision:new-dim"
    ]


def test_sqlite_search_reports_reindex_when_vector_table_dimension_drifts(
    tmp_path: Path,
) -> None:
    profile = load_profile_from_yaml(PROFILE_YAML)
    at = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    ctx, resource = build_production_context(_sqlite_config(tmp_path))
    try:
        remember_decision = RememberDecisionService(ctx.decision_repo, profile)
        remember_decision.remember(
            space="space-b",
            decision_id="decision:space-b",
            statement=(
                "Space B decision should stay searchable after other spaces reindex"
            ),
            source_id="source:test",
            at=at,
        )
        remember_decision.remember(
            space="space-a",
            decision_id="decision:space-a",
            statement="Space A reindex changes the physical vector table dimensions",
            source_id="source:test",
            at=at,
        )

        two_dimensional_service = build_retrieval_service(
            ctx,
            DimensionedEmbeddingProvider(2),
            dimensions=2,
            profile=profile,
        )
        three_dimensional_service = build_retrieval_service(
            ctx,
            DimensionedEmbeddingProvider(3),
            dimensions=3,
            profile=profile,
        )
        two_dimensional_service.reindex("space-b")
        three_dimensional_service.reindex("space-a")

        with pytest.raises(EmbeddingIndexCompatibilityError) as error:
            two_dimensional_service.search(
                space="space-b",
                query="Space B decision should stay searchable",
            )
    finally:
        resource.close()

    message = str(error.value)
    assert "Embedding index search failed for MemorySpace 'space-b'" in message
    assert "dimensions 2" in message
    assert "memorable reindex --space space-b" in message
    assert "SQLite Embedding index was created for 3 dimensions" in message


def test_sqlite_reindex_indexes_superseded_invalidated_and_completed_records(
    tmp_path: Path,
) -> None:
    profile = load_profile_from_yaml(PROFILE_YAML)
    provider = LifecycleMarkerEmbeddingProvider()
    at = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    ctx, resource = build_production_context(_sqlite_config(tmp_path))
    try:
        RememberEntityService(ctx.entity_repo, profile).remember(
            space="test-space",
            entity_id="entity:api",
            entity_type="Component",
            name="API component",
            source_id="source:test",
            at=at,
        )
        RememberEntityService(ctx.entity_repo, profile).remember(
            space="test-space",
            entity_id="entity:db",
            entity_type="Component",
            name="Database component",
            source_id="source:test",
            at=at,
        )
        RememberRelationService(ctx.relation_repo, ctx.entity_repo, profile).remember(
            space="test-space",
            relation_id="relation:api-db",
            source_entity_id="entity:api",
            target_entity_id="entity:db",
            relation_type="depends-on",
            statement="API depends on database",
            source_id="source:test",
            at=at,
        )
        RememberDecisionService(ctx.decision_repo, profile).remember(
            space="test-space",
            decision_id="decision:superseded",
            statement="Superseded retrieval marker should stay searchable",
            source_id="source:test",
            at=at,
        )
        RememberDecisionService(ctx.decision_repo, profile).remember(
            space="test-space",
            decision_id="decision:successor",
            statement="Successor current marker replaces the old decision",
            source_id="source:test",
            at=at,
            supersedes="decision:superseded",
        )
        RememberTaskService(ctx.task_repo, profile).remember(
            space="test-space",
            task_id="task:completed",
            title="Completed retrieval marker should stay searchable",
            source_id="source:test",
            at=at,
        )
        CompleteTaskService(ctx.task_repo).complete(
            space="test-space",
            task_id="task:completed",
            at=at,
        )
        RememberObservationService(ctx.observation_repo, profile).remember(
            space="test-space",
            observation_id="observation:invalidated",
            statement="Invalidated retrieval marker should stay searchable",
            source_id="source:test",
            at=at,
        )
        InvalidateService(ctx.observation_repo).invalidate(
            space="test-space",
            record_id="observation:invalidated",
            at=at,
        )

        service = build_retrieval_service(ctx, provider, dimensions=3, profile=profile)
        result = service.reindex("test-space")
        records = ctx.retrieval_index.records(space="test-space")
        superseded_results = ctx.retrieval_index.search(
            space="test-space",
            query_vector=[1.0, 0.0, 0.0],
            top_k=1,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            dimensions=3,
        )
        completed_results = ctx.retrieval_index.search(
            space="test-space",
            query_vector=[0.0, 1.0, 0.0],
            top_k=1,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            dimensions=3,
        )
        invalidated_results = ctx.retrieval_index.search(
            space="test-space",
            query_vector=[0.0, 0.0, 1.0],
            top_k=1,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            dimensions=3,
        )
    finally:
        resource.close()

    assert result.indexed_by_kind["Entity"] == 2
    assert result.indexed_by_kind["Decision"] == 2
    assert result.indexed_by_kind["Task"] == 1
    assert result.indexed_by_kind["Observation"] == 1
    assert result.indexed_by_kind["Relation"] == 1
    assert {
        "entity:api",
        "relation:api-db",
        "decision:superseded",
        "task:completed",
        "observation:invalidated",
    }.issubset({record.source_id for record in records})
    assert [result.source_id for result in superseded_results] == [
        "decision:superseded"
    ]
    assert [result.source_id for result in completed_results] == ["task:completed"]
    assert [result.source_id for result in invalidated_results] == [
        "observation:invalidated"
    ]


def test_sqlite_backend_construction_wires_persistent_retrieval_index(
    tmp_path: Path,
) -> None:
    ctx, resource = build_production_context(_sqlite_config(tmp_path))
    try:
        assert isinstance(ctx.retrieval_index, SqliteVecRetrievalIndex)
    finally:
        resource.close()
