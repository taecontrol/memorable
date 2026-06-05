from __future__ import annotations

import hashlib
import json
import math
import textwrap
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from memorable.config import EmbeddingSettings, RuntimeConfig
from memorable.core.application import (
    RememberDecisionService,
    RememberEntityService,
    RememberObservationService,
    RememberRelationService,
    RememberTaskService,
)
from memorable.core.context import ApplicationContext
from memorable.core.profile import load_profile_from_yaml
from memorable.core.repositories import (
    InMemoryDecisionRepository,
    InMemoryEntityRepository,
    InMemoryObservationRepository,
    InMemoryRelationRepository,
    InMemoryTaskRepository,
)
from memorable.retrieval.models import EmbeddingRecord
from memorable.retrieval.service import HybridRetrievalService


class CountingEmbeddingProvider:
    def __init__(self, dimensions: int = 8) -> None:
        self.dimensions = dimensions
        self.calls: list[str] = []

    @property
    def provider_name(self) -> str:
        return "counting"

    @property
    def model_name(self) -> str:
        return "deterministic-test"

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        vector = [0.0] * self.dimensions
        for index, char in enumerate(text.encode("utf-8")):
            vector[index % self.dimensions] += float(char)
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude == 0.0:
            return vector
        return [value / magnitude for value in vector]


class FailingEmbeddingIndex:
    def store(self, record: EmbeddingRecord) -> None:
        raise RuntimeError("vector index unavailable")

    def clear_space(self, space: str) -> None:
        return None

    def delete(self, *, space: str, source_id: str, source_kind: str) -> None:
        return None

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
    ) -> list[object]:
        return []


PROFILE_YAML = textwrap.dedent(
    """\
    version: 1
    space:
      name: test-space
      description: Persistent Embedding search test
    entities:
      - name: Component
    relations:
      - name: depends-on
    records:
      - name: ArchitectureDecision
        extends: Decision
      - name: FollowUp
        extends: Task
      - name: GeneralObservation
        extends: Observation
    """
)


def test_reindex_backfills_all_retrievable_kinds_and_search_embeds_only_query() -> None:
    profile = load_profile_from_yaml(PROFILE_YAML)
    at = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    source = "source:persistent-index-test"

    entity_repo = InMemoryEntityRepository()
    decision_repo = InMemoryDecisionRepository()
    task_repo = InMemoryTaskRepository()
    observation_repo = InMemoryObservationRepository()
    relation_repo = InMemoryRelationRepository()

    entity_service = RememberEntityService(repository=entity_repo, profile=profile)
    entity_service.remember(
        space="test-space",
        entity_id="entity:auth",
        entity_type="Component",
        name="Auth component",
        source_id=source,
        at=at,
    )
    entity_service.remember(
        space="test-space",
        entity_id="entity:database",
        entity_type="Component",
        name="Database component",
        source_id=source,
        at=at,
    )
    RememberDecisionService(repository=decision_repo, profile=profile).remember(
        space="test-space",
        decision_id="decision:retention",
        statement="Keep a persistent Embedding index for retention policy search",
        source_id=source,
        at=at,
    )
    RememberTaskService(repository=task_repo, profile=profile).remember(
        space="test-space",
        task_id="task:backfill",
        title="Backfill persistent Embeddings for existing memory",
        source_id=source,
        at=at,
    )
    RememberObservationService(repository=observation_repo, profile=profile).remember(
        space="test-space",
        observation_id="observation:latency",
        statement="Search latency improves when stored items are not re-embedded",
        source_id=source,
        at=at,
    )
    RememberRelationService(
        relation_repo=relation_repo,
        entity_repo=entity_repo,
        profile=profile,
    ).remember(
        space="test-space",
        relation_id="relation:auth-db",
        source_entity_id="entity:auth",
        target_entity_id="entity:database",
        relation_type="depends-on",
        statement="Auth component depends on Database component",
        source_id=source,
        at=at,
    )

    provider = CountingEmbeddingProvider(dimensions=8)
    service = HybridRetrievalService(
        entity_repo=entity_repo,
        decision_repo=decision_repo,
        task_repo=task_repo,
        observation_repo=observation_repo,
        relation_repo=relation_repo,
        embedding_provider=provider,
        dimensions=8,
    )

    result = service.reindex("test-space")
    assert result.indexed_by_kind == {
        "Entity": 2,
        "Decision": 1,
        "Task": 1,
        "Observation": 1,
        "Relation": 1,
    }
    assert len(provider.calls) == 6

    provider.calls.clear()
    results = service.search(
        space="test-space",
        query="persistent Embedding retention search",
        top_k=10,
    )

    assert provider.calls == ["persistent Embedding retention search"]
    result_ids = {result.source_id for result in results}
    assert {
        "entity:auth",
        "entity:database",
        "decision:retention",
        "task:backfill",
        "observation:latency",
        "relation:auth-db",
    }.issubset(result_ids)


def _write_profile(tmp_path: Path) -> None:
    memorable_dir = tmp_path / ".memorable"
    memorable_dir.mkdir()
    (memorable_dir / "memory.yaml").write_text(PROFILE_YAML, encoding="utf-8")


def test_reindex_preserves_embedding_metadata() -> None:
    from memorable.retrieval.index import InMemoryEmbeddingIndex

    profile = load_profile_from_yaml(PROFILE_YAML)
    at = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    entity_repo = InMemoryEntityRepository()
    RememberEntityService(repository=entity_repo, profile=profile).remember(
        space="test-space",
        entity_id="entity:metadata",
        entity_type="Component",
        name="Metadata component",
        source_id="source:metadata-test",
        at=at,
    )

    index = InMemoryEmbeddingIndex()
    provider = CountingEmbeddingProvider(dimensions=8)
    service = HybridRetrievalService(
        entity_repo=entity_repo,
        decision_repo=InMemoryDecisionRepository(),
        task_repo=InMemoryTaskRepository(),
        observation_repo=InMemoryObservationRepository(),
        relation_repo=InMemoryRelationRepository(),
        embedding_provider=provider,
        dimensions=8,
        retrieval_index=index,
    )

    service.reindex("test-space")

    records = index.records(space="test-space")
    assert len(records) == 1
    record = records[0]
    assert record.provider_name == "counting"
    assert record.model_name == "deterministic-test"
    assert record.dimensions == 8
    assert record.indexable_text_version
    assert record.indexable_text_hash == hashlib.sha256(
        record.indexable_text.encode("utf-8")
    ).hexdigest()


def test_cli_remember_decision_upserts_embedding_for_immediate_search(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    driver = MagicMock()
    provider = CountingEmbeddingProvider(dimensions=8)
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=8),
    )

    with (
        patch("memorable.cli.build_production_context", return_value=(ctx, driver)),
        patch("memorable.cli.load_runtime_config", return_value=config),
        patch(
            "memorable.retrieval.embeddings.build_embedding_provider",
            return_value=provider,
        ),
    ):
        assert (
            main(
                [
                    "remember",
                    "decision",
                    "--space",
                    "test-space",
                    "--id",
                    "decision:cli-immediate",
                    "--statement",
                    "Newly remembered Decisions are indexed immediately",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:00:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        provider.calls.clear()
        assert (
            main(
                [
                    "search",
                    "--space",
                    "test-space",
                    "--query",
                    "newly remembered decision search",
                ]
            )
            == 0
        )
        search_output = json.loads(capsys.readouterr().out)

    assert provider.calls == ["newly remembered decision search"]
    result_ids = {result["source_id"] for result in search_output["results"]}
    assert "decision:cli-immediate" in result_ids


def test_cli_remember_upserts_embeddings_for_all_retrievable_kinds(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    driver = MagicMock()
    provider = CountingEmbeddingProvider(dimensions=8)
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=8),
    )

    with (
        patch("memorable.cli.build_production_context", return_value=(ctx, driver)),
        patch("memorable.cli.load_runtime_config", return_value=config),
        patch(
            "memorable.retrieval.embeddings.build_embedding_provider",
            return_value=provider,
        ),
    ):
        commands = [
            [
                "remember",
                "entity",
                "--space",
                "test-space",
                "--id",
                "entity:cli-auth",
                "--type",
                "Component",
                "--name",
                "CLI Auth component",
                "--source",
                "source:cli-test",
                "--at",
                "2026-06-05T12:00:00Z",
            ],
            [
                "remember",
                "entity",
                "--space",
                "test-space",
                "--id",
                "entity:cli-db",
                "--type",
                "Component",
                "--name",
                "CLI Database component",
                "--source",
                "source:cli-test",
                "--at",
                "2026-06-05T12:00:00Z",
            ],
            [
                "remember",
                "decision",
                "--space",
                "test-space",
                "--id",
                "decision:cli-immediate-kind",
                "--statement",
                "CLI remembers index Decisions immediately",
                "--source",
                "source:cli-test",
                "--at",
                "2026-06-05T12:00:00Z",
            ],
            [
                "remember",
                "task",
                "--space",
                "test-space",
                "--id",
                "task:cli-immediate-kind",
                "--title",
                "CLI remembers index Tasks immediately",
                "--source",
                "source:cli-test",
                "--at",
                "2026-06-05T12:00:00Z",
            ],
            [
                "remember",
                "observation",
                "--space",
                "test-space",
                "--id",
                "observation:cli-immediate-kind",
                "--statement",
                "CLI remembers index Observations immediately",
                "--source",
                "source:cli-test",
                "--at",
                "2026-06-05T12:00:00Z",
            ],
            [
                "remember",
                "relation",
                "--space",
                "test-space",
                "--id",
                "relation:cli-immediate-kind",
                "--source-entity-id",
                "entity:cli-auth",
                "--target-entity-id",
                "entity:cli-db",
                "--relation-type",
                "depends-on",
                "--statement",
                "CLI Auth component depends on CLI Database component",
                "--source",
                "source:cli-test",
                "--at",
                "2026-06-05T12:00:00Z",
            ],
        ]
        for command in commands:
            assert main(command) == 0
            capsys.readouterr()

        provider.calls.clear()
        assert (
            main(
                [
                    "search",
                    "--space",
                    "test-space",
                    "--query",
                    "CLI immediate Entity Decision Task Observation Relation",
                ]
            )
            == 0
        )
        search_output = json.loads(capsys.readouterr().out)

    assert provider.calls == [
        "CLI immediate Entity Decision Task Observation Relation"
    ]
    result_ids = {result["source_id"] for result in search_output["results"]}
    assert {
        "entity:cli-auth",
        "entity:cli-db",
        "decision:cli-immediate-kind",
        "task:cli-immediate-kind",
        "observation:cli-immediate-kind",
        "relation:cli-immediate-kind",
    }.issubset(result_ids)


def test_cli_reindex_backfills_memory_for_later_search(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    driver = MagicMock()
    provider = CountingEmbeddingProvider(dimensions=8)
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=8),
    )

    with (
        patch("memorable.cli.build_production_context", return_value=(ctx, driver)),
        patch("memorable.cli.load_runtime_config", return_value=config),
        patch(
            "memorable.retrieval.embeddings.build_embedding_provider",
            return_value=provider,
        ),
    ):
        assert (
            main(
                [
                    "remember",
                    "decision",
                    "--space",
                    "test-space",
                    "--id",
                    "decision:cli-backfill",
                    "--statement",
                    "Persistent search uses backfilled Embeddings",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:00:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        assert main(["reindex", "--space", "test-space"]) == 0
        reindex_output = json.loads(capsys.readouterr().out)
        assert reindex_output["indexed_by_kind"]["Decision"] == 1

        provider.calls.clear()
        assert (
            main(
                [
                    "search",
                    "--space",
                    "test-space",
                    "--query",
                    "backfilled persistent search",
                ]
            )
            == 0
        )
        search_output = json.loads(capsys.readouterr().out)

    assert provider.calls == ["backfilled persistent search"]
    result_ids = {result["source_id"] for result in search_output["results"]}
    assert "decision:cli-backfill" in result_ids


def test_cli_remember_reports_partial_state_when_embedding_upsert_fails(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext(retrieval_index=FailingEmbeddingIndex())
    driver = MagicMock()
    provider = CountingEmbeddingProvider(dimensions=8)
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=8),
    )

    with (
        patch("memorable.cli.build_production_context", return_value=(ctx, driver)),
        patch("memorable.cli.load_runtime_config", return_value=config),
        patch(
            "memorable.retrieval.embeddings.build_embedding_provider",
            return_value=provider,
        ),
    ):
        assert (
            main(
                [
                    "remember",
                    "decision",
                    "--space",
                    "test-space",
                    "--id",
                    "decision:cli-partial-index",
                    "--statement",
                    "Canonical memory survives index maintenance failure",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:00:00Z",
                ]
            )
            == 1
        )
        remember_output = capsys.readouterr()

        assert main(
            [
                "truth",
                "current",
                "--space",
                "test-space",
                "--id",
                "decision:cli-partial-index",
            ]
        ) == 0
        truth_output = json.loads(capsys.readouterr().out)

    assert "Canonical memory was written" in remember_output.err
    assert "memorable reindex --space test-space" in remember_output.err
    assert "vector index unavailable" in remember_output.err
    assert truth_output["decision_id"] == "decision:cli-partial-index"


def test_mcp_remember_upserts_embeddings_for_all_retrievable_kinds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from memorable.core.context import default_context
    from memorable.mcp.server import (
        remember_decision_tool,
        remember_entity_tool,
        remember_observation_tool,
        remember_relation_tool,
        remember_task_tool,
        search_memory_tool,
        set_mcp_context,
    )

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    provider = CountingEmbeddingProvider(dimensions=8)
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=8),
    )
    set_mcp_context(ctx)

    try:
        with (
            patch("memorable.mcp.server.load_runtime_config", return_value=config),
            patch(
                "memorable.retrieval.embeddings.build_embedding_provider",
                return_value=provider,
            ),
        ):
            remember_results = [
                remember_entity_tool(
                    space="test-space",
                    entity_id="entity:mcp-auth",
                    entity_type="Component",
                    name="MCP Auth component",
                    source="source:mcp-test",
                    at="2026-06-05T12:00:00Z",
                ),
                remember_entity_tool(
                    space="test-space",
                    entity_id="entity:mcp-db",
                    entity_type="Component",
                    name="MCP Database component",
                    source="source:mcp-test",
                    at="2026-06-05T12:00:00Z",
                ),
                remember_decision_tool(
                    space="test-space",
                    decision_id="decision:mcp-immediate-kind",
                    statement="MCP remembers index Decisions immediately",
                    source="source:mcp-test",
                    at="2026-06-05T12:00:00Z",
                ),
                remember_task_tool(
                    space="test-space",
                    task_id="task:mcp-immediate-kind",
                    title="MCP remembers index Tasks immediately",
                    source="source:mcp-test",
                    at="2026-06-05T12:00:00Z",
                ),
                remember_observation_tool(
                    space="test-space",
                    observation_id="observation:mcp-immediate-kind",
                    statement="MCP remembers index Observations immediately",
                    source="source:mcp-test",
                    at="2026-06-05T12:00:00Z",
                ),
                remember_relation_tool(
                    space="test-space",
                    relation_id="relation:mcp-immediate-kind",
                    source_entity_id="entity:mcp-auth",
                    target_entity_id="entity:mcp-db",
                    relation_type="depends-on",
                    statement="MCP Auth component depends on MCP Database component",
                    source="source:mcp-test",
                    at="2026-06-05T12:00:00Z",
                ),
            ]
            assert all("error" not in result for result in remember_results)

            provider.calls.clear()
            search_result = search_memory_tool(
                space="test-space",
                query="MCP immediate Entity Decision Task Observation Relation",
            )

        assert provider.calls == [
            "MCP immediate Entity Decision Task Observation Relation"
        ]
        result_ids = {result["source_id"] for result in search_result["results"]}
        assert {
            "entity:mcp-auth",
            "entity:mcp-db",
            "decision:mcp-immediate-kind",
            "task:mcp-immediate-kind",
            "observation:mcp-immediate-kind",
            "relation:mcp-immediate-kind",
        }.issubset(result_ids)
    finally:
        set_mcp_context(default_context)


def test_mcp_remember_reports_partial_state_when_embedding_upsert_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from memorable.core.context import default_context
    from memorable.mcp.server import (
        current_truth_tool,
        remember_decision_tool,
        set_mcp_context,
    )

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext(retrieval_index=FailingEmbeddingIndex())
    provider = CountingEmbeddingProvider(dimensions=8)
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=8),
    )
    set_mcp_context(ctx)

    try:
        with (
            patch("memorable.mcp.server.load_runtime_config", return_value=config),
            patch(
                "memorable.retrieval.embeddings.build_embedding_provider",
                return_value=provider,
            ),
        ):
            result = remember_decision_tool(
                space="test-space",
                decision_id="decision:mcp-partial-index",
                statement="MCP reports partial index maintenance failure",
                source="source:mcp-test",
                at="2026-06-05T12:00:00Z",
            )

        current = current_truth_tool(
            space="test-space",
            record_id="decision:mcp-partial-index",
        )

        assert result["canonical_memory_written"] is True
        assert result["reindex_command"] == "memorable reindex --space test-space"
        assert "Canonical memory was written" in str(result["error"])
        assert "vector index unavailable" in str(result["error"])
        assert current["record_id"] == "decision:mcp-partial-index"
    finally:
        set_mcp_context(default_context)


def test_mcp_reindex_backfills_memory_for_later_search(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from memorable.core.context import default_context
    from memorable.mcp.server import (
        reindex_space_tool,
        remember_decision_tool,
        search_memory_tool,
        set_mcp_context,
    )

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    provider = CountingEmbeddingProvider(dimensions=8)
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=8),
    )
    set_mcp_context(ctx)

    try:
        remember_result = remember_decision_tool(
            space="test-space",
            decision_id="decision:mcp-backfill",
            statement="MCP search uses backfilled persistent Embeddings",
            source="source:mcp-test",
            at="2026-06-05T12:00:00Z",
        )
        assert "error" not in remember_result

        with (
            patch("memorable.mcp.server.load_runtime_config", return_value=config),
            patch(
                "memorable.retrieval.embeddings.build_embedding_provider",
                return_value=provider,
            ),
        ):
            reindex_result = reindex_space_tool(space="test-space")
            assert "error" not in reindex_result
            assert reindex_result["indexed_by_kind"]["Decision"] == 1

            provider.calls.clear()
            search_result = search_memory_tool(
                space="test-space",
                query="MCP backfilled persistent search",
            )

        assert provider.calls == ["MCP backfilled persistent search"]
        result_ids = {result["source_id"] for result in search_result["results"]}
        assert "decision:mcp-backfill" in result_ids
    finally:
        set_mcp_context(default_context)


def test_production_context_wires_neo4j_retrieval_index() -> None:
    from memorable.storage.neo4j.retrieval_index import Neo4jRetrievalIndex
    from memorable.storage.production import build_production_context

    driver = MagicMock()
    driver.verify_connectivity.return_value = None

    with patch(
        "memorable.storage.production.GraphDatabase.driver",
        return_value=driver,
    ):
        ctx, returned_driver = build_production_context(RuntimeConfig())

    assert returned_driver is driver
    assert isinstance(ctx.retrieval_index, Neo4jRetrievalIndex)


@pytest.mark.integration
def test_neo4j_retrieval_index_returns_space_candidate_behind_global_decoys() -> None:
    try:
        from neo4j import GraphDatabase

        from memorable.storage.neo4j.config import Neo4jConfig
        from memorable.storage.neo4j.repository import ensure_all_constraints
        from memorable.storage.neo4j.retrieval_index import Neo4jRetrievalIndex
        from memorable.storage.neo4j.schema import EXPECTED_VECTOR_INDEX
    except Exception:
        pytest.skip("Neo4j dependencies are not available")

    config = Neo4jConfig.from_env()
    driver = GraphDatabase.driver(config.uri, auth=(config.user, config.password))
    prefix = f"test-embedding-index-{uuid.uuid4().hex[:8]}"
    try:
        try:
            driver.verify_connectivity()
        except Exception:
            pytest.skip("Neo4j is not available")

        ensure_all_constraints(driver, vector_dimensions=384)
        with driver.session() as session:
            session.run(
                "CALL db.awaitIndex($name, 10)",
                name=EXPECTED_VECTOR_INDEX.name,
            )

        space = f"{prefix}-target"
        other_space = f"{prefix}-other"
        index = Neo4jRetrievalIndex(driver)
        query_vector = [1.0] + [0.0] * 383
        target_vector = [0.8, 0.6] + [0.0] * 382
        index.store(
            EmbeddingRecord(
                source_id="decision:target",
                source_kind="Decision",
                space=space,
                indexable_text="Target MemorySpace candidate behind closer decoys",
                vector=target_vector,
                provider_name="fake",
                model_name="unit-test",
                dimensions=384,
                indexable_text_hash=hashlib.sha256(b"target").hexdigest(),
            )
        )
        for index_number in range(120):
            incompatible_provider = index_number % 2 == 0
            index.store(
                EmbeddingRecord(
                    source_id=f"decision:decoy-{index_number}",
                    source_kind="Decision",
                    space=space if incompatible_provider else other_space,
                    indexable_text="Closer global decoy",
                    vector=query_vector,
                    provider_name="other-provider"
                    if incompatible_provider
                    else "fake",
                    model_name="unit-test",
                    dimensions=384,
                    indexable_text_hash=hashlib.sha256(
                        f"decoy-{index_number}".encode()
                    ).hexdigest(),
                )
            )

        results = index.search(
            space=space,
            query_vector=query_vector,
            top_k=1,
            provider_name="fake",
            model_name="unit-test",
            dimensions=384,
        )
    finally:
        with driver.session() as session:
            session.run(
                "MATCH (embedding:Embedding) "
                "WHERE embedding.space STARTS WITH $prefix "
                "DELETE embedding",
                prefix=prefix,
            )
        driver.close()

    assert [result.source_id for result in results] == ["decision:target"]


@pytest.mark.integration
def test_neo4j_retrieval_index_searches_vector_candidates() -> None:
    try:
        from neo4j import GraphDatabase

        from memorable.storage.neo4j.config import Neo4jConfig
        from memorable.storage.neo4j.repository import ensure_all_constraints
        from memorable.storage.neo4j.retrieval_index import Neo4jRetrievalIndex
        from memorable.storage.neo4j.schema import EXPECTED_VECTOR_INDEX
    except Exception:
        pytest.skip("Neo4j dependencies are not available")

    config = Neo4jConfig.from_env()
    driver = GraphDatabase.driver(config.uri, auth=(config.user, config.password))
    try:
        try:
            driver.verify_connectivity()
        except Exception:
            pytest.skip("Neo4j is not available")

        ensure_all_constraints(driver, vector_dimensions=384)
        with driver.session() as session:
            session.run(
                "CALL db.awaitIndex($name, 10)",
                name=EXPECTED_VECTOR_INDEX.name,
            )

        space = f"test-embedding-index-{uuid.uuid4().hex[:8]}"
        index = Neo4jRetrievalIndex(driver)
        index.clear_space(space)
        vector_a = [1.0] + [0.0] * 383
        vector_b = [0.0, 1.0] + [0.0] * 382
        index.store(
            EmbeddingRecord(
                source_id="decision:neo4j-a",
                source_kind="Decision",
                space=space,
                indexable_text="Neo4j vector candidate A",
                vector=vector_a,
                provider_name="fake",
                model_name="unit-test",
                dimensions=384,
                indexable_text_hash=hashlib.sha256(b"a").hexdigest(),
            )
        )
        index.store(
            EmbeddingRecord(
                source_id="decision:neo4j-b",
                source_kind="Decision",
                space=space,
                indexable_text="Neo4j vector candidate B",
                vector=vector_b,
                provider_name="fake",
                model_name="unit-test",
                dimensions=384,
                indexable_text_hash=hashlib.sha256(b"b").hexdigest(),
            )
        )

        results = index.search(
            space=space,
            query_vector=vector_a,
            top_k=1,
            provider_name="fake",
            model_name="unit-test",
            dimensions=384,
        )
    finally:
        with driver.session() as session:
            session.run(
                "MATCH (embedding:Embedding) "
                "WHERE embedding.space STARTS WITH 'test-embedding-index-' "
                "DELETE embedding"
            )
        driver.close()

    assert [result.source_id for result in results] == ["decision:neo4j-a"]
