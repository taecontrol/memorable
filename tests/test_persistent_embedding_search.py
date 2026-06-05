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
from memorable.retrieval.service import (
    EmbeddingIndexCompatibilityError,
    HybridRetrievalService,
)


class CountingEmbeddingProvider:
    def __init__(
        self,
        dimensions: int = 8,
        *,
        provider_name: str = "counting",
        model_name: str = "deterministic-test",
    ) -> None:
        self.dimensions = dimensions
        self._provider_name = provider_name
        self._model_name = model_name
        self.calls: list[str] = []

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        vector = [0.0] * self.dimensions
        for index, char in enumerate(text.encode("utf-8")):
            vector[index % self.dimensions] += float(char)
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude == 0.0:
            return vector
        return [value / magnitude for value in vector]


class FailingOnSecondEmbedProvider(CountingEmbeddingProvider):
    def embed(self, text: str) -> list[float]:
        if self.calls:
            self.calls.append(text)
            raise RuntimeError("embedding provider offline")
        return super().embed(text)


class SemanticNeedleEmbeddingProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def provider_name(self) -> str:
        return "needle-test"

    @property
    def model_name(self) -> str:
        return "semantic-needle"

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        lowered = text.lower()
        if "corrected vector needle" in lowered:
            return [1.0, 0.0]
        if "decoy vector lure" in lowered:
            return [0.6, 0.8]
        if "obsolete vector text" in lowered:
            return [0.0, 1.0]
        return [0.1, 0.9]


class FailingSearchIndex:
    def __init__(self) -> None:
        from memorable.retrieval.index import InMemoryEmbeddingIndex

        self._inner = InMemoryEmbeddingIndex()

    def store(self, record: EmbeddingRecord) -> None:
        self._inner.store(record)

    def clear_space(self, space: str) -> None:
        self._inner.clear_space(space)

    def delete(self, *, space: str, source_id: str, source_kind: str) -> None:
        self._inner.delete(space=space, source_id=source_id, source_kind=source_kind)

    def records(self, *, space: str | None = None) -> list[EmbeddingRecord]:
        return self._inner.records(space=space)

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
        raise RuntimeError("vector index offline")


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
    repeated_results = service.search(
        space="test-space",
        query="persistent Embedding retention search",
        top_k=10,
    )

    assert provider.calls == [
        "persistent Embedding retention search",
        "persistent Embedding retention search",
    ]
    assert {result.source_id for result in repeated_results} == {
        result.source_id for result in results
    }
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


def test_index_coverage_reports_stale_indexable_text() -> None:
    profile = load_profile_from_yaml(PROFILE_YAML)
    at = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    decision_repo = InMemoryDecisionRepository()
    RememberDecisionService(repository=decision_repo, profile=profile).remember(
        space="test-space",
        decision_id="decision:stale-coverage",
        statement="Original statement stored in the Embedding index",
        source_id="source:coverage-test",
        at=at,
    )

    service = HybridRetrievalService(
        entity_repo=InMemoryEntityRepository(),
        decision_repo=decision_repo,
        task_repo=InMemoryTaskRepository(),
        observation_repo=InMemoryObservationRepository(),
        relation_repo=InMemoryRelationRepository(),
        embedding_provider=CountingEmbeddingProvider(dimensions=8),
        dimensions=8,
    )
    service.reindex("test-space")

    decision_repo.correct(
        space="test-space",
        record_id="decision:stale-coverage",
        new_statement="Corrected statement that needs a fresh Embedding",
    )

    report = service.index_coverage("test-space")

    assert report.expected_by_kind["Decision"] == 1
    assert report.missing_by_kind["Decision"] == 0
    assert report.stale_by_kind["Decision"] == 1
    assert not report.ok
    assert "memorable reindex --space test-space" in report.actionable_hint


def test_search_reports_stale_embedding_coverage_instead_of_using_it() -> None:
    profile = load_profile_from_yaml(PROFILE_YAML)
    at = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    decision_repo = InMemoryDecisionRepository()
    RememberDecisionService(repository=decision_repo, profile=profile).remember(
        space="test-space",
        decision_id="decision:stale-search",
        statement="Original statement stored in a stale Embedding",
        source_id="source:stale-search-test",
        at=at,
    )

    provider = CountingEmbeddingProvider(dimensions=8)
    service = HybridRetrievalService(
        entity_repo=InMemoryEntityRepository(),
        decision_repo=decision_repo,
        task_repo=InMemoryTaskRepository(),
        observation_repo=InMemoryObservationRepository(),
        relation_repo=InMemoryRelationRepository(),
        embedding_provider=provider,
        dimensions=8,
    )
    service.reindex("test-space")
    provider.calls.clear()

    decision_repo.correct(
        space="test-space",
        record_id="decision:stale-search",
        new_statement="Corrected statement needs explicit reindex before search",
    )

    with pytest.raises(EmbeddingIndexCompatibilityError) as error:
        service.search(
            space="test-space",
            query="Original statement stored in a stale Embedding",
        )

    assert "stale Decision=1" in str(error.value)
    assert "memorable reindex --space test-space" in str(error.value)
    assert provider.calls == ["Original statement stored in a stale Embedding"]


def test_search_reports_incompatible_embeddings_with_active_coverage() -> None:
    from memorable.retrieval.index import InMemoryEmbeddingIndex
    from memorable.retrieval.indexing import EmbeddingIndexer

    profile = load_profile_from_yaml(PROFILE_YAML)
    at = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    decision_repo = InMemoryDecisionRepository()
    service = RememberDecisionService(repository=decision_repo, profile=profile)
    result = service.remember(
        space="test-space",
        decision_id="decision:provider-switch",
        statement="Provider switch should require an explicit reindex",
        source_id="source:provider-switch-test",
        at=at,
    )

    index = InMemoryEmbeddingIndex()
    old_provider = CountingEmbeddingProvider(
        dimensions=8,
        provider_name="old-provider",
        model_name="old-model",
    )
    active_provider = CountingEmbeddingProvider(
        dimensions=8,
        provider_name="active-provider",
        model_name="active-model",
    )
    old_service = HybridRetrievalService(
        entity_repo=InMemoryEntityRepository(),
        decision_repo=decision_repo,
        task_repo=InMemoryTaskRepository(),
        observation_repo=InMemoryObservationRepository(),
        relation_repo=InMemoryRelationRepository(),
        embedding_provider=old_provider,
        dimensions=8,
        retrieval_index=index,
    )
    old_service.reindex("test-space")
    EmbeddingIndexer(
        retrieval_index=index,
        embedding_provider=active_provider,
        dimensions=8,
    ).upsert_decision(result.decision)

    active_service = HybridRetrievalService(
        entity_repo=InMemoryEntityRepository(),
        decision_repo=decision_repo,
        task_repo=InMemoryTaskRepository(),
        observation_repo=InMemoryObservationRepository(),
        relation_repo=InMemoryRelationRepository(),
        embedding_provider=active_provider,
        dimensions=8,
        retrieval_index=index,
    )
    active_provider.calls.clear()

    with pytest.raises(EmbeddingIndexCompatibilityError) as error:
        active_service.search(
            space="test-space",
            query="Provider switch should require an explicit reindex",
        )

    assert "incompatible stored Embeddings Decision=1" in str(error.value)
    assert "memorable reindex --space test-space" in str(error.value)
    assert active_provider.calls == [
        "Provider switch should require an explicit reindex"
    ]


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
    assert (
        record.indexable_text_hash
        == hashlib.sha256(record.indexable_text.encode("utf-8")).hexdigest()
    )


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

    assert provider.calls == ["CLI immediate Entity Decision Task Observation Relation"]
    result_ids = {result["source_id"] for result in search_output["results"]}
    assert {
        "entity:cli-auth",
        "entity:cli-db",
        "decision:cli-immediate-kind",
        "task:cli-immediate-kind",
        "observation:cli-immediate-kind",
        "relation:cli-immediate-kind",
    }.issubset(result_ids)


@pytest.mark.parametrize(
    ("record_kind", "record_id", "source_kind", "remember_args"),
    [
        (
            "decision",
            "decision:cli-forget-index-decision",
            "Decision",
            ["decision", "--statement", "Scratch decision Embedding should be erased"],
        ),
        (
            "observation",
            "observation:cli-forget-index-observation",
            "Observation",
            [
                "observation",
                "--statement",
                "Scratch observation Embedding should be erased",
            ],
        ),
        (
            "task",
            "task:cli-forget-index-task",
            "Task",
            ["task", "--title", "Scratch task Embedding should be erased"],
        ),
    ],
)
def test_cli_forget_record_erases_derived_embedding_and_keeps_entities(
    tmp_path: Path,
    monkeypatch,
    capsys,
    record_kind: str,
    record_id: str,
    source_kind: str,
    remember_args: list[str],
) -> None:
    from memorable.cli import main
    from memorable.retrieval.service import build_retrieval_service

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
                    "entity",
                    "--space",
                    "test-space",
                    "--id",
                    "entity:cli-forget-retained",
                    "--type",
                    "Component",
                    "--name",
                    "Retained independent Entity",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:00:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        assert (
            main(
                [
                    "remember",
                    remember_args[0],
                    "--space",
                    "test-space",
                    "--id",
                    record_id,
                    *remember_args[1:],
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:01:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        assert any(
            record.source_id == record_id and record.source_kind == source_kind
            for record in ctx.retrieval_index.records(space="test-space")
        )

        assert (
            main(
                [
                    "forget",
                    "--space",
                    "test-space",
                    "--target-type",
                    record_kind,
                    "--id",
                    record_id,
                ]
            )
            == 0
        )
        capsys.readouterr()

        provider.calls.clear()
        service = build_retrieval_service(ctx, provider, dimensions=8)
        results = service.search(
            space="test-space",
            query="Scratch Embedding should be erased",
        )
        coverage = service.index_coverage("test-space")

    remaining_embeddings = ctx.retrieval_index.records(space="test-space")
    assert ctx.entity_repo.get("test-space", "entity:cli-forget-retained") is not None
    assert any(
        record.source_id == "entity:cli-forget-retained"
        and record.source_kind == "Entity"
        for record in remaining_embeddings
    )
    assert not any(
        record.source_id == record_id and record.source_kind == source_kind
        for record in remaining_embeddings
    )
    assert record_id not in {result.source_id for result in results}
    assert provider.calls == ["Scratch Embedding should be erased"]
    assert coverage.ok


def test_cli_forget_entity_erases_entity_and_cascaded_relation_embeddings(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main
    from memorable.retrieval.service import build_retrieval_service

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
        for entity_id, name in [
            ("entity:cli-forget-source", "CLI forgotten source"),
            ("entity:cli-forget-target", "CLI retained target"),
        ]:
            assert (
                main(
                    [
                        "remember",
                        "entity",
                        "--space",
                        "test-space",
                        "--id",
                        entity_id,
                        "--type",
                        "Component",
                        "--name",
                        name,
                        "--source",
                        "source:cli-test",
                        "--at",
                        "2026-06-05T12:00:00Z",
                    ]
                )
                == 0
            )
            capsys.readouterr()

        assert (
            main(
                [
                    "remember",
                    "relation",
                    "--space",
                    "test-space",
                    "--id",
                    "relation:cli-cascade-erased",
                    "--source-entity-id",
                    "entity:cli-forget-source",
                    "--target-entity-id",
                    "entity:cli-forget-target",
                    "--relation-type",
                    "depends-on",
                    "--statement",
                    "Forgotten source depends on retained target",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:01:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        assert (
            main(
                [
                    "forget",
                    "--space",
                    "test-space",
                    "--target-type",
                    "entity",
                    "--id",
                    "entity:cli-forget-source",
                ]
            )
            == 0
        )
        capsys.readouterr()

        provider.calls.clear()
        service = build_retrieval_service(ctx, provider, dimensions=8)
        results = service.search(
            space="test-space",
            query="Forgotten source depends on retained target",
        )
        coverage = service.index_coverage("test-space")

    remaining_embeddings = ctx.retrieval_index.records(space="test-space")
    remaining_sources = {
        (record.source_kind, record.source_id) for record in remaining_embeddings
    }
    assert ctx.entity_repo.get("test-space", "entity:cli-forget-source") is None
    assert ctx.relation_repo.get("test-space", "relation:cli-cascade-erased") is None
    assert ctx.entity_repo.get("test-space", "entity:cli-forget-target") is not None
    assert ("Entity", "entity:cli-forget-source") not in remaining_sources
    assert ("Relation", "relation:cli-cascade-erased") not in remaining_sources
    assert ("Entity", "entity:cli-forget-target") in remaining_sources
    assert "relation:cli-cascade-erased" not in {result.source_id for result in results}
    assert provider.calls == ["Forgotten source depends on retained target"]
    assert coverage.ok


def test_mcp_forget_record_erases_derived_embedding_and_keeps_entities(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from memorable.core.context import default_context
    from memorable.mcp.server import (
        forget_record_tool,
        remember_decision_tool,
        remember_entity_tool,
        set_mcp_context,
    )
    from memorable.retrieval.service import build_retrieval_service

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
            entity_result = remember_entity_tool(
                space="test-space",
                entity_id="entity:mcp-forget-retained",
                entity_type="Component",
                name="MCP retained independent Entity",
                source="source:mcp-test",
                at="2026-06-05T12:00:00Z",
            )
            assert "error" not in entity_result

            decision_result = remember_decision_tool(
                space="test-space",
                decision_id="decision:mcp-forget-index",
                statement="MCP scratch decision Embedding should be erased",
                source="source:mcp-test",
                at="2026-06-05T12:01:00Z",
            )
            assert "error" not in decision_result
            assert any(
                record.source_id == "decision:mcp-forget-index"
                and record.source_kind == "Decision"
                for record in ctx.retrieval_index.records(space="test-space")
            )

            forget_result = forget_record_tool(
                space="test-space",
                record_id="decision:mcp-forget-index",
                record_type="decision",
            )
            assert "error" not in forget_result

            provider.calls.clear()
            service = build_retrieval_service(ctx, provider, dimensions=8)
            results = service.search(
                space="test-space",
                query="MCP scratch decision Embedding should be erased",
            )
            coverage = service.index_coverage("test-space")

        remaining_embeddings = ctx.retrieval_index.records(space="test-space")
        assert (
            ctx.entity_repo.get("test-space", "entity:mcp-forget-retained") is not None
        )
        assert any(
            record.source_id == "entity:mcp-forget-retained"
            and record.source_kind == "Entity"
            for record in remaining_embeddings
        )
        assert not any(
            record.source_id == "decision:mcp-forget-index"
            and record.source_kind == "Decision"
            for record in remaining_embeddings
        )
        assert "decision:mcp-forget-index" not in {
            result.source_id for result in results
        }
        assert provider.calls == ["MCP scratch decision Embedding should be erased"]
        assert coverage.ok
    finally:
        set_mcp_context(default_context)


def test_mcp_forget_entity_erases_entity_and_cascaded_relation_embeddings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from memorable.core.context import default_context
    from memorable.mcp.server import (
        forget_entity_tool,
        remember_entity_tool,
        remember_relation_tool,
        set_mcp_context,
    )
    from memorable.retrieval.service import build_retrieval_service

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
            for entity_id, name in [
                ("entity:mcp-forget-source", "MCP forgotten source"),
                ("entity:mcp-forget-target", "MCP retained target"),
            ]:
                entity_result = remember_entity_tool(
                    space="test-space",
                    entity_id=entity_id,
                    entity_type="Component",
                    name=name,
                    source="source:mcp-test",
                    at="2026-06-05T12:00:00Z",
                )
                assert "error" not in entity_result

            relation_result = remember_relation_tool(
                space="test-space",
                relation_id="relation:mcp-cascade-erased",
                source_entity_id="entity:mcp-forget-source",
                target_entity_id="entity:mcp-forget-target",
                relation_type="depends-on",
                statement="MCP forgotten source depends on retained target",
                source="source:mcp-test",
                at="2026-06-05T12:01:00Z",
            )
            assert "error" not in relation_result

            forget_result = forget_entity_tool(
                space="test-space",
                entity_id="entity:mcp-forget-source",
            )
            assert "error" not in forget_result

            provider.calls.clear()
            service = build_retrieval_service(ctx, provider, dimensions=8)
            results = service.search(
                space="test-space",
                query="MCP forgotten source depends on retained target",
            )
            coverage = service.index_coverage("test-space")

        remaining_embeddings = ctx.retrieval_index.records(space="test-space")
        remaining_sources = {
            (record.source_kind, record.source_id) for record in remaining_embeddings
        }
        assert ctx.entity_repo.get("test-space", "entity:mcp-forget-source") is None
        assert (
            ctx.relation_repo.get("test-space", "relation:mcp-cascade-erased") is None
        )
        assert ctx.entity_repo.get("test-space", "entity:mcp-forget-target") is not None
        assert ("Entity", "entity:mcp-forget-source") not in remaining_sources
        assert ("Relation", "relation:mcp-cascade-erased") not in remaining_sources
        assert ("Entity", "entity:mcp-forget-target") in remaining_sources
        assert "relation:mcp-cascade-erased" not in {
            result.source_id for result in results
        }
        assert provider.calls == ["MCP forgotten source depends on retained target"]
        assert coverage.ok
    finally:
        set_mcp_context(default_context)


def test_cli_invalidate_decision_refreshes_embedding_and_current_search_filters_it(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main
    from memorable.retrieval.service import build_retrieval_service

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    driver = MagicMock()
    provider = SemanticNeedleEmbeddingProvider()
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=2),
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
                    "decision:cli-invalidate-refresh",
                    "--statement",
                    "Corrected vector needle later invalidated",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:00:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        assert (
            main(
                [
                    "invalidate",
                    "--space",
                    "test-space",
                    "--record-type",
                    "decision",
                    "--id",
                    "decision:cli-invalidate-refresh",
                    "--at",
                    "2026-06-05T12:05:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        service = build_retrieval_service(ctx, provider, dimensions=2)
        coverage = service.index_coverage("test-space")
        current_results = service.search(
            space="test-space",
            query="corrected vector needle",
            mode="current",
        )
        historical_results = service.search(
            space="test-space",
            query="corrected vector needle",
            mode="as-of",
            as_of=datetime(2026, 6, 5, 12, 3, tzinfo=UTC),
        )

    assert coverage.stale_by_kind["Decision"] == 0
    assert coverage.ok
    assert "decision:cli-invalidate-refresh" not in {
        result.source_id for result in current_results
    }
    assert "decision:cli-invalidate-refresh" in {
        result.source_id for result in historical_results
    }


def test_cli_correct_decision_refreshes_embedding_without_manual_reindex(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main
    from memorable.retrieval.service import build_retrieval_service

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    driver = MagicMock()
    provider = SemanticNeedleEmbeddingProvider()
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=2),
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
                    "decision:cli-correct-refresh",
                    "--statement",
                    "Obsolete vector text before correction",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:00:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        for index in range(3):
            assert (
                main(
                    [
                        "remember",
                        "decision",
                        "--space",
                        "test-space",
                        "--id",
                        f"decision:cli-correct-decoy-{index}",
                        "--statement",
                        f"Decoy vector lure {index}",
                        "--source",
                        "source:cli-test",
                        "--at",
                        "2026-06-05T12:01:00Z",
                    ]
                )
                == 0
            )
            capsys.readouterr()

        assert (
            main(
                [
                    "correct",
                    "--space",
                    "test-space",
                    "--record-type",
                    "decision",
                    "--id",
                    "decision:cli-correct-refresh",
                    "--new-statement",
                    "Corrected vector needle after correction",
                    "--source",
                    "source:correction",
                    "--at",
                    "2026-06-05T12:02:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        provider.calls.clear()
        service = build_retrieval_service(ctx, provider, dimensions=2)
        results = service.search(
            space="test-space",
            query="corrected vector needle",
            top_k=1,
        )

    assert provider.calls == ["corrected vector needle"]
    assert [result.source_id for result in results] == ["decision:cli-correct-refresh"]
    assert results[0].lifecycle_state == "current"


def test_cli_supersede_relation_refreshes_old_embedding_without_manual_reindex(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main
    from memorable.retrieval.service import build_retrieval_service

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    driver = MagicMock()
    provider = SemanticNeedleEmbeddingProvider()
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=2),
    )

    with (
        patch("memorable.cli.build_production_context", return_value=(ctx, driver)),
        patch("memorable.cli.load_runtime_config", return_value=config),
        patch(
            "memorable.retrieval.embeddings.build_embedding_provider",
            return_value=provider,
        ),
    ):
        for entity_id, name in [
            ("entity:cli-super-source", "CLI Supersession Source"),
            ("entity:cli-super-target", "CLI Supersession Target"),
        ]:
            assert (
                main(
                    [
                        "remember",
                        "entity",
                        "--space",
                        "test-space",
                        "--id",
                        entity_id,
                        "--type",
                        "Component",
                        "--name",
                        name,
                        "--source",
                        "source:cli-test",
                        "--at",
                        "2026-06-05T12:00:00Z",
                    ]
                )
                == 0
            )
            capsys.readouterr()

        assert (
            main(
                [
                    "remember",
                    "relation",
                    "--space",
                    "test-space",
                    "--id",
                    "relation:cli-superseded-refresh",
                    "--source-entity-id",
                    "entity:cli-super-source",
                    "--target-entity-id",
                    "entity:cli-super-target",
                    "--relation-type",
                    "depends-on",
                    "--statement",
                    "Obsolete vector text relation should be superseded",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:01:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        assert (
            main(
                [
                    "remember",
                    "relation",
                    "--space",
                    "test-space",
                    "--id",
                    "relation:cli-superseding-refresh",
                    "--source-entity-id",
                    "entity:cli-super-source",
                    "--target-entity-id",
                    "entity:cli-super-target",
                    "--relation-type",
                    "depends-on",
                    "--statement",
                    "Corrected vector needle relation is current truth",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:10:00Z",
                    "--supersedes",
                    "relation:cli-superseded-refresh",
                ]
            )
            == 0
        )
        capsys.readouterr()

        service = build_retrieval_service(ctx, provider, dimensions=2)
        coverage = service.index_coverage("test-space")

    assert coverage.stale_by_kind["Relation"] == 0
    assert coverage.ok


def test_cli_supersede_observation_refreshes_old_embedding_without_manual_reindex(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main
    from memorable.retrieval.service import build_retrieval_service

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    driver = MagicMock()
    provider = SemanticNeedleEmbeddingProvider()
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=2),
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
                    "observation",
                    "--space",
                    "test-space",
                    "--id",
                    "observation:cli-superseded-refresh",
                    "--statement",
                    "Obsolete vector text observation should be superseded",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:00:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        assert (
            main(
                [
                    "remember",
                    "observation",
                    "--space",
                    "test-space",
                    "--id",
                    "observation:cli-superseding-refresh",
                    "--statement",
                    "Corrected vector needle observation is current truth",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:10:00Z",
                    "--supersedes",
                    "observation:cli-superseded-refresh",
                ]
            )
            == 0
        )
        capsys.readouterr()

        service = build_retrieval_service(ctx, provider, dimensions=2)
        coverage = service.index_coverage("test-space")
        current_results = service.search(
            space="test-space",
            query="obsolete vector text",
            mode="current",
            top_k=1,
        )

    assert coverage.stale_by_kind["Observation"] == 0
    assert coverage.ok
    assert [result.source_id for result in current_results] == [
        "observation:cli-superseding-refresh"
    ]


def test_cli_complete_task_refreshes_embedding_without_manual_reindex(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main
    from memorable.retrieval.service import build_retrieval_service

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    driver = MagicMock()
    provider = SemanticNeedleEmbeddingProvider()
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=2),
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
                    "task",
                    "--space",
                    "test-space",
                    "--id",
                    "task:cli-complete-refresh",
                    "--title",
                    "Corrected vector needle CLI task to complete",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:00:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        assert (
            main(
                [
                    "complete",
                    "task",
                    "--space",
                    "test-space",
                    "--id",
                    "task:cli-complete-refresh",
                    "--at",
                    "2026-06-05T12:05:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        service = build_retrieval_service(ctx, provider, dimensions=2)
        coverage = service.index_coverage("test-space")

    assert coverage.stale_by_kind["Task"] == 0
    assert coverage.ok


def test_cli_supersession_refreshes_old_embedding_and_current_truth_wins(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main
    from memorable.retrieval.service import build_retrieval_service

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    driver = MagicMock()
    provider = SemanticNeedleEmbeddingProvider()
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=2),
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
                    "decision:cli-superseded-refresh",
                    "--statement",
                    "Obsolete vector text should be superseded",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:00:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        assert (
            main(
                [
                    "remember",
                    "decision",
                    "--space",
                    "test-space",
                    "--id",
                    "decision:cli-superseding-refresh",
                    "--statement",
                    "Corrected vector needle is current truth",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:10:00Z",
                    "--supersedes",
                    "decision:cli-superseded-refresh",
                ]
            )
            == 0
        )
        capsys.readouterr()

        service = build_retrieval_service(ctx, provider, dimensions=2)
        coverage = service.index_coverage("test-space")
        current_results = service.search(
            space="test-space",
            query="obsolete vector text",
            mode="current",
            top_k=1,
        )
        historical_results = service.search(
            space="test-space",
            query="obsolete vector text",
            mode="as-of",
            as_of=datetime(2026, 6, 5, 12, 5, tzinfo=UTC),
            top_k=1,
        )

    assert coverage.stale_by_kind["Decision"] == 0
    assert coverage.ok
    assert [result.source_id for result in current_results] == [
        "decision:cli-superseding-refresh"
    ]
    assert [result.source_id for result in historical_results] == [
        "decision:cli-superseded-refresh"
    ]


def test_cli_search_reports_embedding_provider_failure_with_doctor_hint(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    driver = MagicMock()
    provider = FailingOnSecondEmbedProvider(dimensions=8)
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
                    "decision:search-provider-failure",
                    "--statement",
                    "Search should report Embedding Provider failures",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:00:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        assert (
            main(
                [
                    "search",
                    "--space",
                    "test-space",
                    "--query",
                    "provider failure",
                ]
            )
            == 1
        )
        search_output = capsys.readouterr()

    assert "Embedding Provider" in search_output.err
    assert "memorable doctor" in search_output.err
    assert "embedding provider offline" in search_output.err


def test_cli_search_reports_vector_index_failure_with_doctor_hint(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext(retrieval_index=FailingSearchIndex())
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
                    "decision:search-index-failure",
                    "--statement",
                    "Search should report vector index failures",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:00:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        assert (
            main(
                [
                    "search",
                    "--space",
                    "test-space",
                    "--query",
                    "vector index failure",
                ]
            )
            == 1
        )
        search_output = capsys.readouterr()

    assert "Embedding index search failed" in search_output.err
    assert "memorable doctor" in search_output.err
    assert "vector index offline" in search_output.err


def test_cli_search_reports_reindex_when_only_incompatible_embeddings_exist(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    driver = MagicMock()
    old_provider = CountingEmbeddingProvider(
        dimensions=8,
        provider_name="old-provider",
        model_name="old-model",
    )
    active_provider = CountingEmbeddingProvider(
        dimensions=8,
        provider_name="active-provider",
        model_name="active-model",
    )
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=8),
    )

    with (
        patch("memorable.cli.build_production_context", return_value=(ctx, driver)),
        patch("memorable.cli.load_runtime_config", return_value=config),
        patch(
            "memorable.retrieval.embeddings.build_embedding_provider",
            side_effect=[old_provider, active_provider],
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
                    "decision:incompatible-index",
                    "--statement",
                    "Search should fail loud when only old Embeddings exist",
                    "--source",
                    "source:cli-test",
                    "--at",
                    "2026-06-05T12:00:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

        assert (
            main(
                [
                    "search",
                    "--space",
                    "test-space",
                    "--query",
                    "old embedding compatibility",
                ]
            )
            == 1
        )
        search_output = capsys.readouterr()

    assert "No compatible Embeddings" in search_output.err
    assert "active-provider" in search_output.err
    assert "active-model" in search_output.err
    assert "memorable reindex --space test-space" in search_output.err


def test_cli_reindex_reports_index_failure_with_doctor_hint(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    profile = load_profile_from_yaml(PROFILE_YAML)
    ctx = ApplicationContext(retrieval_index=FailingEmbeddingIndex())
    RememberDecisionService(repository=ctx.decision_repo, profile=profile).remember(
        space="test-space",
        decision_id="decision:reindex-index-failure",
        statement="Reindex should report vector index failures",
        source_id="source:cli-test",
        at=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
    )
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
        assert main(["reindex", "--space", "test-space"]) == 1
        output = capsys.readouterr()

    assert "Reindex failed" in output.err
    assert "memorable doctor" in output.err
    assert "vector index unavailable" in output.err


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

        assert (
            main(
                [
                    "truth",
                    "current",
                    "--space",
                    "test-space",
                    "--id",
                    "decision:cli-partial-index",
                ]
            )
            == 0
        )
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


def test_mcp_supersede_observation_refreshes_old_embedding_without_manual_reindex(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from memorable.core.context import default_context
    from memorable.mcp.server import (
        remember_observation_tool,
        set_mcp_context,
    )
    from memorable.retrieval.service import build_retrieval_service

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    provider = SemanticNeedleEmbeddingProvider()
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=2),
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
            old_result = remember_observation_tool(
                space="test-space",
                observation_id="observation:mcp-superseded-refresh",
                statement="Obsolete vector text observation should be superseded",
                source="source:mcp-test",
                at="2026-06-05T12:00:00Z",
            )
            assert "error" not in old_result

            new_result = remember_observation_tool(
                space="test-space",
                observation_id="observation:mcp-superseding-refresh",
                statement="Corrected vector needle observation is current truth",
                source="source:mcp-test",
                at="2026-06-05T12:10:00Z",
                supersedes="observation:mcp-superseded-refresh",
            )
            assert "error" not in new_result

            service = build_retrieval_service(ctx, provider, dimensions=2)
            coverage = service.index_coverage("test-space")

        assert coverage.stale_by_kind["Observation"] == 0
        assert coverage.ok
    finally:
        set_mcp_context(default_context)


def test_mcp_supersede_decision_refreshes_old_embedding_without_manual_reindex(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from memorable.core.context import default_context
    from memorable.mcp.server import (
        remember_decision_tool,
        search_memory_tool,
        set_mcp_context,
    )
    from memorable.retrieval.service import build_retrieval_service

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    provider = SemanticNeedleEmbeddingProvider()
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=2),
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
            old_result = remember_decision_tool(
                space="test-space",
                decision_id="decision:mcp-superseded-refresh",
                statement="Obsolete vector text should be superseded",
                source="source:mcp-test",
                at="2026-06-05T12:00:00Z",
            )
            assert "error" not in old_result

            new_result = remember_decision_tool(
                space="test-space",
                decision_id="decision:mcp-superseding-refresh",
                statement="Corrected vector needle is current truth",
                source="source:mcp-test",
                at="2026-06-05T12:10:00Z",
                supersedes="decision:mcp-superseded-refresh",
            )
            assert "error" not in new_result

            service = build_retrieval_service(ctx, provider, dimensions=2)
            coverage = service.index_coverage("test-space")
            current_result = search_memory_tool(
                space="test-space",
                query="obsolete vector text",
            )

        assert coverage.stale_by_kind["Decision"] == 0
        assert coverage.ok
        assert "decision:mcp-superseded-refresh" not in {
            result["source_id"] for result in current_result["results"]
        }
    finally:
        set_mcp_context(default_context)


def test_mcp_supersede_relation_refreshes_old_embedding_without_manual_reindex(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from memorable.core.context import default_context
    from memorable.mcp.server import (
        remember_entity_tool,
        remember_relation_tool,
        search_memory_tool,
        set_mcp_context,
    )
    from memorable.retrieval.service import build_retrieval_service

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    provider = SemanticNeedleEmbeddingProvider()
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=2),
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
            for entity_id, name in [
                ("entity:mcp-super-source", "MCP Supersession Source"),
                ("entity:mcp-super-target", "MCP Supersession Target"),
            ]:
                result = remember_entity_tool(
                    space="test-space",
                    entity_id=entity_id,
                    entity_type="Component",
                    name=name,
                    source="source:mcp-test",
                    at="2026-06-05T12:00:00Z",
                )
                assert "error" not in result

            old_result = remember_relation_tool(
                space="test-space",
                relation_id="relation:mcp-superseded-refresh",
                source_entity_id="entity:mcp-super-source",
                target_entity_id="entity:mcp-super-target",
                relation_type="depends-on",
                statement="Obsolete vector text relation should be superseded",
                source="source:mcp-test",
                at="2026-06-05T12:01:00Z",
            )
            assert "error" not in old_result

            new_result = remember_relation_tool(
                space="test-space",
                relation_id="relation:mcp-superseding-refresh",
                source_entity_id="entity:mcp-super-source",
                target_entity_id="entity:mcp-super-target",
                relation_type="depends-on",
                statement="Corrected vector needle relation is current truth",
                source="source:mcp-test",
                at="2026-06-05T12:10:00Z",
                supersedes="relation:mcp-superseded-refresh",
            )
            assert "error" not in new_result

            service = build_retrieval_service(ctx, provider, dimensions=2)
            coverage = service.index_coverage("test-space")
            current_old_query = search_memory_tool(
                space="test-space",
                query="obsolete vector text",
            )
            current_new_query = search_memory_tool(
                space="test-space",
                query="corrected vector needle",
            )
            historical_result = search_memory_tool(
                space="test-space",
                query="obsolete vector text",
                mode="as-of",
                as_of="2026-06-05T12:05:00Z",
            )

        assert coverage.stale_by_kind["Relation"] == 0
        assert coverage.ok
        assert "relation:mcp-superseded-refresh" not in {
            result["source_id"] for result in current_old_query["results"]
        }
        assert "relation:mcp-superseding-refresh" in {
            result["source_id"] for result in current_new_query["results"]
        }
        assert "relation:mcp-superseded-refresh" in {
            result["source_id"] for result in historical_result["results"]
        }
    finally:
        set_mcp_context(default_context)


def test_mcp_invalidate_relation_refreshes_embedding_and_current_search_filters_it(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from memorable.core.context import default_context
    from memorable.mcp.server import (
        invalidate_tool,
        remember_entity_tool,
        remember_relation_tool,
        search_memory_tool,
        set_mcp_context,
    )
    from memorable.retrieval.service import build_retrieval_service

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    provider = SemanticNeedleEmbeddingProvider()
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=2),
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
            for entity_id, name in [
                ("entity:mcp-invalid-source", "MCP Invalid Source"),
                ("entity:mcp-invalid-target", "MCP Invalid Target"),
            ]:
                result = remember_entity_tool(
                    space="test-space",
                    entity_id=entity_id,
                    entity_type="Component",
                    name=name,
                    source="source:mcp-test",
                    at="2026-06-05T12:00:00Z",
                )
                assert "error" not in result

            relation_result = remember_relation_tool(
                space="test-space",
                relation_id="relation:mcp-invalidate-refresh",
                source_entity_id="entity:mcp-invalid-source",
                target_entity_id="entity:mcp-invalid-target",
                relation_type="depends-on",
                statement="Corrected vector needle relation to invalidate",
                source="source:mcp-test",
                at="2026-06-05T12:01:00Z",
            )
            assert "error" not in relation_result

            invalidation_result = invalidate_tool(
                space="test-space",
                record_id="relation:mcp-invalidate-refresh",
                record_type="relation",
                at="2026-06-05T12:05:00Z",
            )
            assert "error" not in invalidation_result

            service = build_retrieval_service(ctx, provider, dimensions=2)
            coverage = service.index_coverage("test-space")
            current_result = search_memory_tool(
                space="test-space",
                query="corrected vector needle",
            )
            historical_result = search_memory_tool(
                space="test-space",
                query="corrected vector needle",
                mode="as-of",
                as_of="2026-06-05T12:03:00Z",
            )

        assert coverage.stale_by_kind["Relation"] == 0
        assert coverage.ok
        assert "relation:mcp-invalidate-refresh" not in {
            result["source_id"] for result in current_result["results"]
        }
        assert "relation:mcp-invalidate-refresh" in {
            result["source_id"] for result in historical_result["results"]
        }
    finally:
        set_mcp_context(default_context)


def test_mcp_complete_task_refreshes_embedding_and_remains_retrievable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from memorable.core.context import default_context
    from memorable.mcp.server import (
        complete_task_tool,
        remember_task_tool,
        search_memory_tool,
        set_mcp_context,
    )
    from memorable.retrieval.service import build_retrieval_service

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    provider = SemanticNeedleEmbeddingProvider()
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=2),
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
            remember_result = remember_task_tool(
                space="test-space",
                task_id="task:mcp-complete-refresh",
                title="Corrected vector needle task to complete",
                source="source:mcp-test",
                at="2026-06-05T12:00:00Z",
            )
            assert "error" not in remember_result

            complete_result = complete_task_tool(
                space="test-space",
                task_id="task:mcp-complete-refresh",
                at="2026-06-05T12:05:00Z",
            )
            assert "error" not in complete_result

            service = build_retrieval_service(ctx, provider, dimensions=2)
            coverage = service.index_coverage("test-space")

            current_result = search_memory_tool(
                space="test-space",
                query="corrected vector needle",
            )
            historical_result = search_memory_tool(
                space="test-space",
                query="corrected vector needle",
                mode="as-of",
                as_of="2026-06-05T12:03:00Z",
            )

        assert coverage.stale_by_kind["Task"] == 0
        assert coverage.ok
        current_tasks = [
            result
            for result in current_result["results"]
            if result["source_id"] == "task:mcp-complete-refresh"
        ]
        historical_tasks = [
            result
            for result in historical_result["results"]
            if result["source_id"] == "task:mcp-complete-refresh"
        ]
        assert current_tasks[0]["lifecycle_state"] == "completed"
        assert historical_tasks[0]["lifecycle_state"] == "open"
    finally:
        set_mcp_context(default_context)


def test_mcp_correct_relation_refreshes_embedding_without_manual_reindex(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from memorable.core.context import default_context
    from memorable.mcp.server import (
        correct_tool,
        remember_decision_tool,
        remember_entity_tool,
        remember_relation_tool,
        search_memory_tool,
        set_mcp_context,
    )

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    provider = SemanticNeedleEmbeddingProvider()
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=2),
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
            for entity_id, name in [
                ("entity:mcp-source", "MCP Source"),
                ("entity:mcp-target", "MCP Target"),
            ]:
                result = remember_entity_tool(
                    space="test-space",
                    entity_id=entity_id,
                    entity_type="Component",
                    name=name,
                    source="source:mcp-test",
                    at="2026-06-05T12:00:00Z",
                )
                assert "error" not in result

            relation_result = remember_relation_tool(
                space="test-space",
                relation_id="relation:mcp-correct-refresh",
                source_entity_id="entity:mcp-source",
                target_entity_id="entity:mcp-target",
                relation_type="depends-on",
                statement="Obsolete vector text before relation correction",
                source="source:mcp-test",
                at="2026-06-05T12:01:00Z",
            )
            assert "error" not in relation_result

            for index in range(3):
                decoy_result = remember_decision_tool(
                    space="test-space",
                    decision_id=f"decision:mcp-relation-decoy-{index}",
                    statement=f"Decoy vector lure {index}",
                    source="source:mcp-test",
                    at="2026-06-05T12:02:00Z",
                )
                assert "error" not in decoy_result

            correction_result = correct_tool(
                space="test-space",
                record_id="relation:mcp-correct-refresh",
                record_type="relation",
                new_statement="Corrected vector needle after relation correction",
                source="source:correction",
                at="2026-06-05T12:03:00Z",
            )
            assert "error" not in correction_result

            provider.calls.clear()
            search_result = search_memory_tool(
                space="test-space",
                query="corrected vector needle",
            )

        assert provider.calls == ["corrected vector needle"]
        assert search_result["results"][0]["source_id"] == (
            "relation:mcp-correct-refresh"
        )
        assert search_result["results"][0]["lifecycle_state"] == "current"
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


def test_mcp_search_reports_reindex_when_only_incompatible_embeddings_exist(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from memorable.core.context import default_context
    from memorable.mcp.server import (
        remember_decision_tool,
        search_memory_tool,
        set_mcp_context,
    )

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = ApplicationContext()
    old_provider = CountingEmbeddingProvider(
        dimensions=8,
        provider_name="old-provider",
        model_name="old-model",
    )
    active_provider = CountingEmbeddingProvider(
        dimensions=8,
        provider_name="active-provider",
        model_name="active-model",
    )
    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", dimensions=8),
    )
    set_mcp_context(ctx)

    try:
        with (
            patch("memorable.mcp.server.load_runtime_config", return_value=config),
            patch(
                "memorable.retrieval.embeddings.build_embedding_provider",
                side_effect=[old_provider, active_provider],
            ),
        ):
            remember_result = remember_decision_tool(
                space="test-space",
                decision_id="decision:mcp-incompatible-index",
                statement="MCP search should report incompatible Embedding coverage",
                source="source:mcp-test",
                at="2026-06-05T12:00:00Z",
            )
            assert "error" not in remember_result

            search_result = search_memory_tool(
                space="test-space",
                query="old embedding compatibility",
            )

        assert "No compatible Embeddings" in str(search_result["error"])
        assert "active-provider" in str(search_result["error"])
        assert search_result["reindex_command"] == (
            "memorable reindex --space test-space"
        )
    finally:
        set_mcp_context(default_context)


def test_mcp_reindex_reports_index_failure_with_doctor_hint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from memorable.core.context import default_context
    from memorable.mcp.server import reindex_space_tool, set_mcp_context

    _write_profile(tmp_path)
    monkeypatch.chdir(tmp_path)

    profile = load_profile_from_yaml(PROFILE_YAML)
    ctx = ApplicationContext(retrieval_index=FailingEmbeddingIndex())
    RememberDecisionService(repository=ctx.decision_repo, profile=profile).remember(
        space="test-space",
        decision_id="decision:mcp-reindex-index-failure",
        statement="MCP reindex should report vector index failures",
        source_id="source:mcp-test",
        at=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
    )
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
            result = reindex_space_tool(space="test-space")

        assert "Reindex failed" in str(result["error"])
        assert "memorable doctor" in str(result["error"])
        assert "vector index unavailable" in str(result["error"])
        assert result["reindex_command"] == ("memorable reindex --space test-space")
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
        "memorable.storage.neo4j.connection.GraphDatabase.driver",
        return_value=driver,
    ):
        ctx, returned_driver = build_production_context(RuntimeConfig())

    assert returned_driver is driver
    assert isinstance(ctx.retrieval_index, Neo4jRetrievalIndex)


@pytest.mark.integration
def test_neo4j_retrieval_index_returns_space_candidate_behind_global_decoys() -> None:
    try:
        from live_neo4j import build_live_neo4j_driver

        from memorable.storage.neo4j.repository import ensure_all_constraints
        from memorable.storage.neo4j.retrieval_index import Neo4jRetrievalIndex
        from memorable.storage.neo4j.schema import EXPECTED_VECTOR_INDEX
    except Exception:
        pytest.skip("Neo4j dependencies are not available")

    driver = build_live_neo4j_driver()
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
                    provider_name="other-provider" if incompatible_provider else "fake",
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
