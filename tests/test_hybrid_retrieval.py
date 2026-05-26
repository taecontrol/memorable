"""Tests for hybrid GraphRAG retrieval.

Covers slice #9 acceptance criteria:
- Embeddings are derived from Indexable Text and are not canonical memory.
- Fake embedding provider is deterministic and stable for tests.
- Retrieval combines semantic candidates, graph expansion, temporal filtering,
  and provenance-aware result explanation.
- Ranking is simple but explicit enough for the tracer bullet.
- Retrieval output explains why each record was returned,
  including lifecycle state and provenance.
- Superseded and completed records are handled according to
  current truth or point-in-time query mode.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime

import pytest

# --- Fixture data (from contract) ---

FIXTURE_TIMESTAMPS = {
    "space": datetime(2026, 5, 23, 10, 0, 0, tzinfo=UTC),
    "profile": datetime(2026, 5, 23, 10, 5, 0, tzinfo=UTC),
    "entity": datetime(2026, 5, 23, 10, 10, 0, tzinfo=UTC),
    "decision_v1": datetime(2026, 5, 23, 10, 15, 0, tzinfo=UTC),
    "decision_v2": datetime(2026, 5, 23, 10, 20, 0, tzinfo=UTC),
    "task": datetime(2026, 5, 23, 10, 25, 0, tzinfo=UTC),
    "task_complete": datetime(2026, 5, 23, 10, 30, 0, tzinfo=UTC),
}

SOURCE_ID = "source:tracer-fixture"

VALID_PROFILE_YAML = textwrap.dedent("""\
    version: 1

    space:
      name: memorable
      description: Agent memory system design

    write_policy:
      default: auto
      sensitive: suggest

    entities:
      - name: Project
      - name: Component

    records:
      - name: ArchitectureDecision
        extends: Decision
      - name: FollowUp
        extends: Task
""")

STATEMENT_V1 = "Graphiti is the first implementation path for Memorable storage."
STATEMENT_V2 = (
    "Direct Neo4j is the first implementation path;"
    " Graphiti remains optional behind the"
    " storage adapter."
)


# =====================================================================
# 1. Embedding provider tests
# =====================================================================


class TestFakeEmbeddingProvider:
    """FakeEmbeddingProvider is deterministic and stable for tests."""

    def test_embed_returns_list_of_floats(self) -> None:
        from memorable.retrieval.embeddings import FakeEmbeddingProvider

        provider = FakeEmbeddingProvider(dimensions=8)
        vector = provider.embed("hello world")

        assert isinstance(vector, list)
        assert len(vector) == 8
        assert all(isinstance(v, float) for v in vector)

    def test_same_text_same_vector(self) -> None:
        from memorable.retrieval.embeddings import FakeEmbeddingProvider

        provider = FakeEmbeddingProvider(dimensions=16)
        v1 = provider.embed("storage decision")
        v2 = provider.embed("storage decision")

        assert v1 == v2

    def test_different_text_different_vector(self) -> None:
        from memorable.retrieval.embeddings import FakeEmbeddingProvider

        provider = FakeEmbeddingProvider(dimensions=16)
        v1 = provider.embed("storage decision")
        v2 = provider.embed("something else entirely")

        assert v1 != v2

    def test_deterministic_across_instances(self) -> None:
        from memorable.retrieval.embeddings import FakeEmbeddingProvider

        p1 = FakeEmbeddingProvider(dimensions=8)
        p2 = FakeEmbeddingProvider(dimensions=8)

        assert p1.embed("test text") == p2.embed("test text")

    def test_vectors_are_normalized(self) -> None:
        """Vectors should be unit-length for cosine similarity."""
        import math

        from memorable.retrieval.embeddings import FakeEmbeddingProvider

        provider = FakeEmbeddingProvider(dimensions=32)
        vector = provider.embed("some text here")

        magnitude = math.sqrt(sum(v * v for v in vector))
        assert abs(magnitude - 1.0) < 1e-6

    def test_provider_name_and_model(self) -> None:
        from memorable.retrieval.embeddings import FakeEmbeddingProvider

        provider = FakeEmbeddingProvider(dimensions=8)

        assert provider.provider_name == "fake"
        assert provider.model_name == "hash-based"

    def test_conforms_to_embedding_provider_protocol(self) -> None:
        from memorable.retrieval.embeddings import (
            EmbeddingProvider,
            FakeEmbeddingProvider,
        )

        provider = FakeEmbeddingProvider(dimensions=8)
        # Protocol structural check: must have embed, provider_name, model_name
        assert isinstance(provider, EmbeddingProvider)


# =====================================================================
# 2. Indexable Text generation tests
# =====================================================================


class TestIndexableText:
    """Indexable Text is derived from domain objects for search."""

    def test_entity_indexable_text(self) -> None:
        from memorable.core.models import Entity
        from memorable.retrieval.indexable_text import indexable_text_for_entity

        entity = Entity(
            id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            space="memorable",
        )

        text = indexable_text_for_entity(entity)

        assert "Memorable" in text
        assert "Project" in text
        assert "entity:memorable" in text

    def test_decision_indexable_text(self) -> None:
        from memorable.core.models import Decision
        from memorable.retrieval.indexable_text import indexable_text_for_decision

        decision = Decision(
            id="decision:storage-path:v2",
            statement=STATEMENT_V2,
            space="memorable",
            validity_time=FIXTURE_TIMESTAMPS["decision_v2"],
            invalidation_time=None,
            lifecycle_state="current",
            supersedes="decision:storage-path:v1",
            superseded_by=None,
        )

        text = indexable_text_for_decision(decision)

        assert "Decision" in text
        assert "storage" in text.lower()
        assert "decision:storage-path:v2" in text

    def test_task_indexable_text(self) -> None:
        from memorable.core.models import Task
        from memorable.retrieval.indexable_text import indexable_text_for_task

        task = Task(
            id="task:mcp-smoke-path",
            title="Expose Memorable Core through MCP smoke path",
            space="memorable",
            lifecycle_state="open",
            validity_time=FIXTURE_TIMESTAMPS["task"],
            completion_time=None,
            completion_event_id=None,
        )

        text = indexable_text_for_task(task)

        assert "Task" in text
        assert "MCP" in text
        assert "task:mcp-smoke-path" in text

    def test_indexable_text_is_not_canonical_memory(self) -> None:
        """Indexable Text is derived, not stored as canonical memory."""
        from memorable.core.models import Entity
        from memorable.retrieval.indexable_text import indexable_text_for_entity

        entity = Entity(
            id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            space="memorable",
        )

        # Calling twice produces the same text (derived, not stored)
        text1 = indexable_text_for_entity(entity)
        text2 = indexable_text_for_entity(entity)
        assert text1 == text2
        assert isinstance(text1, str)


# =====================================================================
# 3. Embedding index tests
# =====================================================================


class TestEmbeddingIndex:
    """In-memory embedding index stores and searches vectors."""

    def _make_index(self):
        from memorable.retrieval.embeddings import FakeEmbeddingProvider
        from memorable.retrieval.index import InMemoryEmbeddingIndex

        provider = FakeEmbeddingProvider(dimensions=32)
        index = InMemoryEmbeddingIndex()
        return index, provider

    def test_store_and_search(self) -> None:
        from memorable.retrieval.models import EmbeddingRecord

        index, provider = self._make_index()

        text = "storage implementation for Memorable"
        vector = provider.embed(text)

        record = EmbeddingRecord(
            source_id="decision:storage-path:v2",
            source_kind="Decision",
            space="memorable",
            indexable_text=text,
            vector=vector,
            provider_name="fake",
            model_name="hash-based",
            dimensions=32,
        )
        index.store(record)

        query_vector = provider.embed("storage implementation")
        results = index.search(space="memorable", query_vector=query_vector, top_k=5)

        assert len(results) >= 1
        assert results[0].source_id == "decision:storage-path:v2"

    def test_search_returns_scores(self) -> None:
        from memorable.retrieval.models import EmbeddingRecord

        index, provider = self._make_index()

        record = EmbeddingRecord(
            source_id="entity:memorable",
            source_kind="Entity",
            space="memorable",
            indexable_text="Memorable project",
            vector=provider.embed("Memorable project"),
            provider_name="fake",
            model_name="hash-based",
            dimensions=32,
        )
        index.store(record)

        results = index.search(
            space="memorable",
            query_vector=provider.embed("Memorable project"),
            top_k=5,
        )

        assert len(results) == 1
        assert results[0].score > 0.0
        assert results[0].score <= 1.0 + 1e-9

    def test_search_scoped_by_space(self) -> None:
        from memorable.retrieval.models import EmbeddingRecord

        index, provider = self._make_index()

        record_a = EmbeddingRecord(
            source_id="entity:a",
            source_kind="Entity",
            space="space-a",
            indexable_text="test text",
            vector=provider.embed("test text"),
            provider_name="fake",
            model_name="hash-based",
            dimensions=32,
        )
        record_b = EmbeddingRecord(
            source_id="entity:b",
            source_kind="Entity",
            space="space-b",
            indexable_text="test text",
            vector=provider.embed("test text"),
            provider_name="fake",
            model_name="hash-based",
            dimensions=32,
        )

        index.store(record_a)
        index.store(record_b)

        results = index.search(
            space="space-a",
            query_vector=provider.embed("test text"),
            top_k=5,
        )

        assert len(results) == 1
        assert results[0].source_id == "entity:a"

    def test_search_top_k_limits_results(self) -> None:
        from memorable.retrieval.models import EmbeddingRecord

        index, provider = self._make_index()

        for i in range(10):
            record = EmbeddingRecord(
                source_id=f"entity:{i}",
                source_kind="Entity",
                space="memorable",
                indexable_text=f"text variant {i}",
                vector=provider.embed(f"text variant {i}"),
                provider_name="fake",
                model_name="hash-based",
                dimensions=32,
            )
            index.store(record)

        results = index.search(
            space="memorable",
            query_vector=provider.embed("text variant 3"),
            top_k=3,
        )

        assert len(results) <= 3

    def test_search_ordered_by_similarity_descending(self) -> None:
        from memorable.retrieval.models import EmbeddingRecord

        index, provider = self._make_index()

        for i in range(5):
            record = EmbeddingRecord(
                source_id=f"entity:{i}",
                source_kind="Entity",
                space="memorable",
                indexable_text=f"text variant {i}",
                vector=provider.embed(f"text variant {i}"),
                provider_name="fake",
                model_name="hash-based",
                dimensions=32,
            )
            index.store(record)

        results = index.search(
            space="memorable",
            query_vector=provider.embed("text variant 2"),
            top_k=5,
        )

        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)


# =====================================================================
# 4. Retrieval models tests
# =====================================================================


class TestRetrievalModels:
    """Retrieval data models are frozen dataclasses."""

    def test_embedding_record_is_frozen(self) -> None:
        from memorable.retrieval.models import EmbeddingRecord

        record = EmbeddingRecord(
            source_id="entity:x",
            source_kind="Entity",
            space="s",
            indexable_text="text",
            vector=[0.1, 0.2],
            provider_name="fake",
            model_name="hash-based",
            dimensions=2,
        )

        with pytest.raises(AttributeError):
            record.source_id = "entity:y"  # type: ignore[misc]

    def test_retrieval_result_has_explanation(self) -> None:
        from memorable.retrieval.models import RetrievalResult

        result = RetrievalResult(
            source_id="decision:storage-path:v2",
            source_kind="Decision",
            lifecycle_state="current",
            score=0.95,
            explanation=[
                "semantic candidate from Indexable Text",
                "temporal filter kept it because it is current",
            ],
            provenance_summary={
                "source_id": SOURCE_ID,
                "episode_id": "episode:tracer-fixture:2026-05-23T10:20:00+00:00",
            },
        )

        assert result.source_id == "decision:storage-path:v2"
        assert len(result.explanation) == 2
        assert result.provenance_summary["source_id"] == SOURCE_ID

    def test_retrieval_result_is_frozen(self) -> None:
        from memorable.retrieval.models import RetrievalResult

        result = RetrievalResult(
            source_id="entity:x",
            source_kind="Entity",
            lifecycle_state="current",
            score=0.5,
            explanation=["test"],
            provenance_summary={},
        )

        with pytest.raises(AttributeError):
            result.score = 0.9  # type: ignore[misc]


# =====================================================================
# 5. Full fixture setup helper
# =====================================================================


def _build_fixture():
    """Build the full tracer-bullet fixture and return repos + service."""
    from memorable.core.application import (
        CompleteTaskService,
        RememberDecisionService,
        RememberEntityService,
        RememberTaskService,
    )
    from memorable.core.profile import load_profile_from_yaml
    from memorable.core.repositories import (
        InMemoryDecisionRepository,
        InMemoryEntityRepository,
        InMemoryTaskRepository,
    )
    from memorable.retrieval.embeddings import FakeEmbeddingProvider
    from memorable.retrieval.service import HybridRetrievalService

    entity_repo = InMemoryEntityRepository()
    decision_repo = InMemoryDecisionRepository()
    task_repo = InMemoryTaskRepository()
    profile = load_profile_from_yaml(VALID_PROFILE_YAML)

    # Step 3: Remember Entity
    entity_svc = RememberEntityService(repository=entity_repo, profile=profile)
    entity_svc.remember(
        space="memorable",
        entity_id="entity:memorable",
        entity_type="Project",
        name="Memorable",
        source_id=SOURCE_ID,
        at=FIXTURE_TIMESTAMPS["entity"],
    )

    # Step 4: Remember initial Decision
    decision_svc = RememberDecisionService(repository=decision_repo, profile=profile)
    decision_svc.remember(
        space="memorable",
        decision_id="decision:storage-path:v1",
        statement=STATEMENT_V1,
        source_id=SOURCE_ID,
        at=FIXTURE_TIMESTAMPS["decision_v1"],
    )

    # Step 5: Remember superseding Decision
    decision_svc.remember(
        space="memorable",
        decision_id="decision:storage-path:v2",
        statement=STATEMENT_V2,
        source_id=SOURCE_ID,
        at=FIXTURE_TIMESTAMPS["decision_v2"],
        supersedes="decision:storage-path:v1",
    )

    # Step 6: Remember Task
    task_svc = RememberTaskService(repository=task_repo, profile=profile)
    task_svc.remember(
        space="memorable",
        task_id="task:mcp-smoke-path",
        title="Expose Memorable Core through MCP smoke path",
        source_id=SOURCE_ID,
        at=FIXTURE_TIMESTAMPS["task"],
    )

    # Step 7: Complete Task
    complete_svc = CompleteTaskService(repository=task_repo)
    complete_svc.complete(
        space="memorable",
        task_id="task:mcp-smoke-path",
        at=FIXTURE_TIMESTAMPS["task_complete"],
    )

    provider = FakeEmbeddingProvider(dimensions=32)
    retrieval_service = HybridRetrievalService(
        entity_repo=entity_repo,
        decision_repo=decision_repo,
        task_repo=task_repo,
        embedding_provider=provider,
    )

    return retrieval_service, entity_repo, decision_repo, task_repo


# =====================================================================
# 6. Temporal filtering tests
# =====================================================================


class TestTemporalFiltering:
    """Temporal filtering respects current truth and point-in-time truth."""

    def test_current_mode_excludes_superseded_decisions(self) -> None:
        """In current mode, superseded decisions are not in results."""
        service, *_ = _build_fixture()

        results = service.search(
            space="memorable",
            query="storage implementation decision",
            mode="current",
        )

        result_ids = [r.source_id for r in results]
        assert "decision:storage-path:v2" in result_ids
        assert "decision:storage-path:v1" not in result_ids

    def test_current_mode_includes_completed_task_with_lifecycle(self) -> None:
        """In current mode, completed tasks appear with their lifecycle state."""
        service, *_ = _build_fixture()

        results = service.search(
            space="memorable",
            query="MCP smoke path task",
            mode="current",
        )

        task_results = [r for r in results if r.source_id == "task:mcp-smoke-path"]
        assert len(task_results) == 1
        assert task_results[0].lifecycle_state == "completed"

    def test_as_of_mode_before_supersession_returns_v1(self) -> None:
        """Point-in-time before supersession returns the original decision."""
        service, *_ = _build_fixture()

        at_before = datetime(2026, 5, 23, 10, 17, 0, tzinfo=UTC)

        results = service.search(
            space="memorable",
            query="storage implementation decision",
            mode="as-of",
            as_of=at_before,
        )

        result_ids = [r.source_id for r in results]
        assert "decision:storage-path:v1" in result_ids
        assert "decision:storage-path:v2" not in result_ids

    def test_as_of_mode_before_completion_shows_task_open(self) -> None:
        """Point-in-time before completion shows task as open."""
        service, *_ = _build_fixture()

        at_before = datetime(2026, 5, 23, 10, 27, 0, tzinfo=UTC)

        results = service.search(
            space="memorable",
            query="MCP smoke path task",
            mode="as-of",
            as_of=at_before,
        )

        task_results = [r for r in results if r.source_id == "task:mcp-smoke-path"]
        assert len(task_results) == 1
        assert task_results[0].lifecycle_state == "open"

    def test_current_mode_excludes_invalidated_decision(self) -> None:
        """Invalidated decisions are excluded from current mode results."""
        service, _, decision_repo, _ = _build_fixture()

        invalidation_time = datetime(2026, 5, 23, 10, 22, 0, tzinfo=UTC)
        decision_repo.invalidate(
            space="memorable",
            record_id="decision:storage-path:v2",
            invalidation_time=invalidation_time,
        )

        results = service.search(
            space="memorable",
            query="storage implementation decision",
            mode="current",
        )

        result_ids = [r.source_id for r in results]
        assert "decision:storage-path:v2" not in result_ids

    def test_invalidated_decision_visible_in_as_of_before_invalidation(self) -> None:
        """Invalidated decision visible in as-of mode before invalidation."""
        service, _, decision_repo, _ = _build_fixture()

        invalidation_time = datetime(2026, 5, 23, 10, 22, 0, tzinfo=UTC)
        decision_repo.invalidate(
            space="memorable",
            record_id="decision:storage-path:v2",
            invalidation_time=invalidation_time,
        )

        # Query at a time after validity but before invalidation
        at_before_invalidation = datetime(2026, 5, 23, 10, 21, 0, tzinfo=UTC)

        results = service.search(
            space="memorable",
            query="storage implementation decision",
            mode="as-of",
            as_of=at_before_invalidation,
        )

        result_ids = [r.source_id for r in results]
        assert "decision:storage-path:v2" in result_ids


# =====================================================================
# 7. Graph expansion tests
# =====================================================================


class TestGraphExpansion:
    """Graph expansion finds related records via repositories."""

    def test_entity_expands_to_related_decisions(self) -> None:
        """When entity:memorable is a candidate, related decisions are found."""
        service, *_ = _build_fixture()

        results = service.search(
            space="memorable",
            query="Memorable project",
            mode="current",
        )

        result_ids = [r.source_id for r in results]
        # The entity should be found, and graph expansion should
        # bring in related decisions (v2 is current)
        assert "entity:memorable" in result_ids
        assert "decision:storage-path:v2" in result_ids

    def test_decision_expands_to_related_entity(self) -> None:
        """When a decision is a candidate, related entities are found."""
        service, *_ = _build_fixture()

        results = service.search(
            space="memorable",
            query="storage implementation decision for Memorable",
            mode="current",
        )

        result_ids = [r.source_id for r in results]
        # Both the decision and the entity should be present
        assert "decision:storage-path:v2" in result_ids
        assert "entity:memorable" in result_ids


# =====================================================================
# 8. Provenance-aware explanation tests
# =====================================================================


class TestProvenanceAwareExplanation:
    """Retrieval results include provenance-aware explanations."""

    def test_result_explains_why_returned(self) -> None:
        service, *_ = _build_fixture()

        results = service.search(
            space="memorable",
            query=(
                "How should agents retrieve the"
                " current storage implementation"
                " decision?"
            ),
            mode="current",
        )

        decision_results = [
            r for r in results if r.source_id == "decision:storage-path:v2"
        ]
        assert len(decision_results) == 1

        result = decision_results[0]
        assert len(result.explanation) > 0
        # Must mention semantic candidate
        assert any("semantic" in e.lower() for e in result.explanation)

    def test_result_includes_provenance_summary(self) -> None:
        service, *_ = _build_fixture()

        results = service.search(
            space="memorable",
            query="storage implementation decision",
            mode="current",
        )

        decision_results = [
            r for r in results if r.source_id == "decision:storage-path:v2"
        ]
        assert len(decision_results) == 1

        result = decision_results[0]
        assert result.provenance_summary.get("source_id") == SOURCE_ID
        assert "episode_id" in result.provenance_summary

    def test_provenance_summary_uses_only_shared_fields(self) -> None:
        """Retrieval provenance summary uses unified fields, not type-specific ones."""
        service, *_ = _build_fixture()

        results = service.search(
            space="memorable",
            query="storage implementation decision Memorable task",
            mode="current",
        )

        type_specific_fields = {"entity_id", "decision_id", "task_id"}
        for result in results:
            for field in type_specific_fields:
                assert field not in result.provenance_summary, (
                    f"Type-specific field '{field}' found in"
                    f" provenance_summary for {result.source_id}"
                )

    def test_result_includes_lifecycle_state(self) -> None:
        service, *_ = _build_fixture()

        results = service.search(
            space="memorable",
            query="storage implementation",
            mode="current",
        )

        decision_results = [
            r for r in results if r.source_id == "decision:storage-path:v2"
        ]
        assert len(decision_results) == 1
        assert decision_results[0].lifecycle_state == "current"

    def test_historical_context_mentions_supersession(self) -> None:
        """The search result for the contract query explains supersession history."""
        service, *_ = _build_fixture()

        results = service.search(
            space="memorable",
            query=(
                "How should agents retrieve the"
                " current storage implementation"
                " decision?"
            ),
            mode="current",
        )

        decision_results = [
            r for r in results if r.source_id == "decision:storage-path:v2"
        ]
        assert len(decision_results) == 1

        result = decision_results[0]
        # Explanation should mention supersession history
        explanations_joined = " ".join(result.explanation).lower()
        has_supersession = (
            "supersession" in explanations_joined or "supersed" in explanations_joined
        )
        assert has_supersession


# =====================================================================
# 9. Full hybrid retrieval integration test (contract query)
# =====================================================================


class TestContractQuery:
    """Full integration test matching the contract expected output."""

    def test_contract_search_returns_current_decision(self) -> None:
        """Search from the contract returns decision:storage-path:v2 as current."""
        service, *_ = _build_fixture()

        results = service.search(
            space="memorable",
            query=(
                "How should agents retrieve the"
                " current storage implementation"
                " decision?"
            ),
            mode="current",
        )

        # decision:storage-path:v2 should be the top-ranked decision
        decision_results = [r for r in results if r.source_kind == "Decision"]
        assert len(decision_results) >= 1
        assert decision_results[0].source_id == "decision:storage-path:v2"
        assert decision_results[0].lifecycle_state == "current"

    def test_contract_search_does_not_return_superseded_as_current(self) -> None:
        """v1 is NOT returned in current mode."""
        service, *_ = _build_fixture()

        results = service.search(
            space="memorable",
            query=(
                "How should agents retrieve the"
                " current storage implementation"
                " decision?"
            ),
            mode="current",
        )

        result_ids = [r.source_id for r in results]
        assert "decision:storage-path:v1" not in result_ids

    def test_contract_search_result_has_provenance(self) -> None:
        """Contract result includes provenance from source:tracer-fixture."""
        service, *_ = _build_fixture()

        results = service.search(
            space="memorable",
            query=(
                "How should agents retrieve the"
                " current storage implementation"
                " decision?"
            ),
            mode="current",
        )

        decision_results = [
            r for r in results if r.source_id == "decision:storage-path:v2"
        ]
        assert len(decision_results) == 1
        assert decision_results[0].provenance_summary["source_id"] == SOURCE_ID


# =====================================================================
# 10. Ranking tests
# =====================================================================


class TestRanking:
    """Simple ranking by cosine similarity score."""

    def test_results_ranked_by_score_descending(self) -> None:
        service, *_ = _build_fixture()

        results = service.search(
            space="memorable",
            query="storage implementation decision",
            mode="current",
        )

        if len(results) > 1:
            scores = [r.score for r in results]
            assert scores == sorted(scores, reverse=True)


# =====================================================================
# 11. CLI adapter tests
# =====================================================================


@pytest.mark.usefixtures("cli_in_memory_context")
class TestCLISearch:
    """CLI `memorable search` performs hybrid retrieval."""

    def _setup_fixture_via_cli(self) -> None:
        from memorable.cli import main

        # Entity
        main(
            [
                "remember",
                "entity",
                "--space",
                "memorable",
                "--id",
                "entity:memorable",
                "--type",
                "Project",
                "--name",
                "Memorable",
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:10:00Z",
            ]
        )
        # Decision v1
        main(
            [
                "remember",
                "decision",
                "--space",
                "memorable",
                "--id",
                "decision:storage-path:v1",
                "--statement",
                STATEMENT_V1,
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:15:00Z",
            ]
        )
        # Decision v2
        main(
            [
                "remember",
                "decision",
                "--space",
                "memorable",
                "--id",
                "decision:storage-path:v2",
                "--statement",
                STATEMENT_V2,
                "--supersedes",
                "decision:storage-path:v1",
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:20:00Z",
            ]
        )

    def test_search_command(self, capsys) -> None:
        from memorable.cli import main

        self._setup_fixture_via_cli()

        exit_code = main(
            [
                "search",
                "--space",
                "memorable",
                "--query",
                "storage implementation decision",
            ]
        )

        assert exit_code == 0
        output = capsys.readouterr().out
        assert "decision:storage-path:v2" in output

    def test_search_command_with_mode(self, capsys) -> None:
        import json as json_mod

        from memorable.cli import main

        self._setup_fixture_via_cli()
        # Clear capsys from setup commands
        capsys.readouterr()

        exit_code = main(
            [
                "search",
                "--space",
                "memorable",
                "--query",
                "storage implementation",
                "--mode",
                "current",
            ]
        )

        assert exit_code == 0
        output = capsys.readouterr().out
        parsed = json_mod.loads(output)
        result_ids = [r["source_id"] for r in parsed["results"]]
        assert "decision:storage-path:v2" in result_ids
        # v1 is superseded -- not returned as a result in current mode
        assert "decision:storage-path:v1" not in result_ids


# =====================================================================
# 12. MCP adapter tests
# =====================================================================


class TestMCPSearchTool:
    """MCP search_memory_tool performs hybrid retrieval."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def _setup_fixture_via_mcp(self) -> None:
        from memorable.mcp.server import (
            remember_decision_tool,
            remember_entity_tool,
        )

        remember_entity_tool(
            space="memorable",
            entity_id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            source=SOURCE_ID,
            at="2026-05-23T10:10:00Z",
        )
        remember_decision_tool(
            space="memorable",
            decision_id="decision:storage-path:v1",
            statement=STATEMENT_V1,
            source=SOURCE_ID,
            at="2026-05-23T10:15:00Z",
        )
        remember_decision_tool(
            space="memorable",
            decision_id="decision:storage-path:v2",
            statement=STATEMENT_V2,
            source=SOURCE_ID,
            at="2026-05-23T10:20:00Z",
            supersedes="decision:storage-path:v1",
        )

    def test_search_memory_tool(self) -> None:
        from memorable.mcp.server import search_memory_tool

        self._setup_fixture_via_mcp()

        result = search_memory_tool(
            space="memorable",
            query="storage implementation decision",
        )

        assert "error" not in result
        assert "results" in result
        result_ids = [r["source_id"] for r in result["results"]]
        assert "decision:storage-path:v2" in result_ids

    def test_search_memory_tool_current_mode(self) -> None:
        from memorable.mcp.server import search_memory_tool

        self._setup_fixture_via_mcp()

        result = search_memory_tool(
            space="memorable",
            query="storage implementation decision",
            mode="current",
        )

        assert "error" not in result
        result_ids = [r["source_id"] for r in result["results"]]
        assert "decision:storage-path:v1" not in result_ids


# =====================================================================
# 13. Language boundary tests
# =====================================================================


class TestLanguageBoundary:
    """Retrieval output uses domain language, not storage vocabulary."""

    def test_no_storage_vocabulary_in_explanations(self) -> None:
        service, *_ = _build_fixture()

        results = service.search(
            space="memorable",
            query="storage implementation",
            mode="current",
        )

        # "Indexable Text" is domain language (ubiquitous language),
        # not storage vocabulary, so we exclude "index" only when it
        # appears as a standalone storage term, not inside "Indexable".
        storage_terms = {
            "node",
            "edge",
            "vertex",
            "database",
            "table",
            "row",
            "column",
        }

        for result in results:
            for explanation in result.explanation:
                explanation_lower = explanation.lower()
                for term in storage_terms:
                    assert term not in explanation_lower, (
                        f"Storage vocabulary '{term}' found"
                        f" in explanation: {explanation}"
                    )

    def test_source_kind_uses_domain_names(self) -> None:
        service, *_ = _build_fixture()

        results = service.search(
            space="memorable",
            query="storage implementation",
            mode="current",
        )

        valid_kinds = {"Entity", "Decision", "Task", "Observation"}
        for result in results:
            assert result.source_kind in valid_kinds, (
                f"source_kind '{result.source_kind}' is not a domain term"
            )


# =====================================================================
# 14. Dependency injection tests for temporal services
# =====================================================================


class TestHybridRetrievalServiceDependencyInjection:
    """HybridRetrievalService accepts injected temporal services."""

    def test_constructor_accepts_point_in_time_service(self) -> None:
        """Constructor accepts a point_in_time_service parameter."""
        from memorable.core.application import PointInTimeTruthService
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
            InMemoryEntityRepository,
            InMemoryTaskRepository,
        )
        from memorable.retrieval.embeddings import FakeEmbeddingProvider
        from memorable.retrieval.service import HybridRetrievalService

        entity_repo = InMemoryEntityRepository()
        decision_repo = InMemoryDecisionRepository()
        task_repo = InMemoryTaskRepository()
        provider = FakeEmbeddingProvider(dimensions=32)
        pit_service = PointInTimeTruthService(repository=decision_repo)

        service = HybridRetrievalService(
            entity_repo=entity_repo,
            decision_repo=decision_repo,
            task_repo=task_repo,
            embedding_provider=provider,
            point_in_time_service=pit_service,
        )

        assert service is not None

    def test_constructor_accepts_inspect_task_service(self) -> None:
        """Constructor accepts an inspect_task_service parameter."""
        from memorable.core.application import InspectTaskService
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
            InMemoryEntityRepository,
            InMemoryTaskRepository,
        )
        from memorable.retrieval.embeddings import FakeEmbeddingProvider
        from memorable.retrieval.service import HybridRetrievalService

        entity_repo = InMemoryEntityRepository()
        decision_repo = InMemoryDecisionRepository()
        task_repo = InMemoryTaskRepository()
        provider = FakeEmbeddingProvider(dimensions=32)
        inspect_service = InspectTaskService(repository=task_repo)

        service = HybridRetrievalService(
            entity_repo=entity_repo,
            decision_repo=decision_repo,
            task_repo=task_repo,
            embedding_provider=provider,
            inspect_task_service=inspect_service,
        )

        assert service is not None

    def test_uses_injected_point_in_time_service(self) -> None:
        """as-of search uses the injected PointInTimeTruthService, not a new one."""
        from unittest.mock import MagicMock

        from memorable.core.application import (
            PointInTimeTruthService,
            RememberDecisionService,
            RememberEntityService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
            InMemoryEntityRepository,
            InMemoryTaskRepository,
        )
        from memorable.retrieval.embeddings import FakeEmbeddingProvider
        from memorable.retrieval.service import HybridRetrievalService

        entity_repo = InMemoryEntityRepository()
        decision_repo = InMemoryDecisionRepository()
        task_repo = InMemoryTaskRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)

        entity_svc = RememberEntityService(repository=entity_repo, profile=profile)
        entity_svc.remember(
            space="memorable",
            entity_id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMPS["entity"],
        )

        decision_svc = RememberDecisionService(
            repository=decision_repo, profile=profile
        )
        decision_svc.remember(
            space="memorable",
            decision_id="decision:storage-path:v1",
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMPS["decision_v1"],
        )

        provider = FakeEmbeddingProvider(dimensions=32)

        # Wrap a real service to spy on calls
        real_pit = PointInTimeTruthService(repository=decision_repo)
        spy_pit = MagicMock(wraps=real_pit)

        service = HybridRetrievalService(
            entity_repo=entity_repo,
            decision_repo=decision_repo,
            task_repo=task_repo,
            embedding_provider=provider,
            point_in_time_service=spy_pit,
        )

        at_query = datetime(2026, 5, 23, 10, 17, 0, tzinfo=UTC)
        service.search(
            space="memorable",
            query="storage implementation decision",
            mode="as-of",
            as_of=at_query,
        )

        spy_pit.at.assert_called()

    def test_uses_injected_inspect_task_service(self) -> None:
        """as-of search uses the injected InspectTaskService, not a new one."""
        from unittest.mock import MagicMock

        from memorable.core.application import (
            InspectTaskService,
            RememberEntityService,
            RememberTaskService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
            InMemoryEntityRepository,
            InMemoryTaskRepository,
        )
        from memorable.retrieval.embeddings import FakeEmbeddingProvider
        from memorable.retrieval.service import HybridRetrievalService

        entity_repo = InMemoryEntityRepository()
        decision_repo = InMemoryDecisionRepository()
        task_repo = InMemoryTaskRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)

        entity_svc = RememberEntityService(repository=entity_repo, profile=profile)
        entity_svc.remember(
            space="memorable",
            entity_id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMPS["entity"],
        )

        task_svc = RememberTaskService(repository=task_repo, profile=profile)
        task_svc.remember(
            space="memorable",
            task_id="task:mcp-smoke-path",
            title="Expose Memorable Core through MCP smoke path",
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMPS["task"],
        )

        provider = FakeEmbeddingProvider(dimensions=32)

        real_inspect = InspectTaskService(repository=task_repo)
        spy_inspect = MagicMock(wraps=real_inspect)

        service = HybridRetrievalService(
            entity_repo=entity_repo,
            decision_repo=decision_repo,
            task_repo=task_repo,
            embedding_provider=provider,
            inspect_task_service=spy_inspect,
        )

        at_query = datetime(2026, 5, 23, 10, 27, 0, tzinfo=UTC)
        service.search(
            space="memorable",
            query="MCP smoke path task",
            mode="as-of",
            as_of=at_query,
        )

        spy_inspect.inspect.assert_called()


# =====================================================================
# 15. Observation retrieval integration tests
# =====================================================================

OBSERVATION_PROFILE_YAML = textwrap.dedent("""\
    version: 1

    space:
      name: memorable
      description: Agent memory system design

    entities:
      - name: Project
      - name: Component

    records:
      - name: ArchitectureDecision
        extends: Decision
      - name: FollowUp
        extends: Task
      - name: GeneralObservation
        extends: Observation
""")

OBSERVATION_TIMESTAMPS = {
    "entity": datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC),
    "obs_v1": datetime(2026, 5, 24, 10, 10, 0, tzinfo=UTC),
    "obs_v2": datetime(2026, 5, 24, 10, 20, 0, tzinfo=UTC),
    "obs_invalidated": datetime(2026, 5, 24, 10, 30, 0, tzinfo=UTC),
}

OBS_STATEMENT_V1 = "The team prefers PostgreSQL for relational storage."
OBS_STATEMENT_V2 = "The team now prefers SQLite for local development storage."
OBS_STATEMENT_STANDALONE = "Code coverage is above 90 percent."


def _build_observation_fixture():
    """Build a fixture with observations for retrieval tests."""
    from memorable.core.application import (
        RememberEntityService,
        RememberObservationService,
    )
    from memorable.core.profile import load_profile_from_yaml
    from memorable.core.repositories import (
        InMemoryDecisionRepository,
        InMemoryEntityRepository,
        InMemoryObservationRepository,
        InMemoryTaskRepository,
    )
    from memorable.retrieval.embeddings import FakeEmbeddingProvider
    from memorable.retrieval.service import HybridRetrievalService

    entity_repo = InMemoryEntityRepository()
    decision_repo = InMemoryDecisionRepository()
    task_repo = InMemoryTaskRepository()
    observation_repo = InMemoryObservationRepository()
    profile = load_profile_from_yaml(OBSERVATION_PROFILE_YAML)

    # Entity
    entity_svc = RememberEntityService(repository=entity_repo, profile=profile)
    entity_svc.remember(
        space="memorable",
        entity_id="entity:memorable",
        entity_type="Project",
        name="Memorable",
        source_id=SOURCE_ID,
        at=OBSERVATION_TIMESTAMPS["entity"],
    )

    # Observation v1 (will be superseded)
    obs_svc = RememberObservationService(repository=observation_repo, profile=profile)
    obs_svc.remember(
        space="memorable",
        observation_id="observation:storage-pref:v1",
        statement=OBS_STATEMENT_V1,
        source_id=SOURCE_ID,
        at=OBSERVATION_TIMESTAMPS["obs_v1"],
    )

    # Observation v2 (supersedes v1)
    obs_svc.remember(
        space="memorable",
        observation_id="observation:storage-pref:v2",
        statement=OBS_STATEMENT_V2,
        source_id=SOURCE_ID,
        at=OBSERVATION_TIMESTAMPS["obs_v2"],
        supersedes="observation:storage-pref:v1",
    )

    # Standalone observation (will be invalidated in some tests)
    obs_svc.remember(
        space="memorable",
        observation_id="observation:coverage",
        statement=OBS_STATEMENT_STANDALONE,
        source_id=SOURCE_ID,
        at=OBSERVATION_TIMESTAMPS["obs_v1"],
    )

    provider = FakeEmbeddingProvider(dimensions=32)
    service = HybridRetrievalService(
        entity_repo=entity_repo,
        decision_repo=decision_repo,
        task_repo=task_repo,
        observation_repo=observation_repo,
        embedding_provider=provider,
    )

    return service, entity_repo, decision_repo, task_repo, observation_repo


class TestObservationIndexableText:
    """Indexable Text generation for Observation records."""

    def test_indexable_text_for_observation(self) -> None:
        """Format matches: Observation {id}: {statement} (lifecycle: ..., space: ...)"""
        from memorable.core.models import Observation
        from memorable.retrieval.indexable_text import indexable_text_for_observation

        observation = Observation(
            id="observation:storage-pref:v1",
            statement=OBS_STATEMENT_V1,
            space="memorable",
            validity_time=OBSERVATION_TIMESTAMPS["obs_v1"],
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )

        text = indexable_text_for_observation(observation)

        assert text == (
            f"Observation observation:storage-pref:v1: {OBS_STATEMENT_V1} "
            f"(lifecycle: current, space: memorable)"
        )

    def test_indexable_text_includes_key_fields(self) -> None:
        from memorable.core.models import Observation
        from memorable.retrieval.indexable_text import indexable_text_for_observation

        observation = Observation(
            id="observation:coverage",
            statement=OBS_STATEMENT_STANDALONE,
            space="memorable",
            validity_time=OBSERVATION_TIMESTAMPS["obs_v1"],
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )

        text = indexable_text_for_observation(observation)

        assert "Observation" in text
        assert "observation:coverage" in text
        assert OBS_STATEMENT_STANDALONE in text
        assert "current" in text
        assert "memorable" in text


class TestObservationRetrievalIndex:
    """Observations are indexed and searchable in the hybrid retrieval pipeline."""

    def test_rebuild_index_includes_observations(self) -> None:
        """Observations get indexed during _rebuild_index."""
        service, *_ = _build_observation_fixture()

        # After search, observations should appear in results
        results = service.search(
            space="memorable",
            query="storage preference observation",
            mode="current",
        )

        result_ids = [r.source_id for r in results]
        # v2 is current, so it should appear
        assert "observation:storage-pref:v2" in result_ids

    def test_observation_search_returns_results(self) -> None:
        """Observations appear in search results with correct source_kind."""
        service, *_ = _build_observation_fixture()

        results = service.search(
            space="memorable",
            query="code coverage above 90 percent",
            mode="current",
        )

        obs_results = [r for r in results if r.source_kind == "Observation"]
        assert len(obs_results) >= 1
        obs_ids = [r.source_id for r in obs_results]
        assert "observation:coverage" in obs_ids


class TestObservationTemporalFiltering:
    """Temporal filtering for observations in retrieval."""

    def test_superseded_observation_excluded_current_mode(self) -> None:
        """Superseded observations are excluded from current mode results."""
        service, *_ = _build_observation_fixture()

        results = service.search(
            space="memorable",
            query="storage preference PostgreSQL SQLite",
            mode="current",
        )

        result_ids = [r.source_id for r in results]
        # v1 is superseded, should not appear
        assert "observation:storage-pref:v1" not in result_ids
        # v2 is current, should appear
        assert "observation:storage-pref:v2" in result_ids

    def test_invalidated_observation_excluded_current_mode(self) -> None:
        """Invalidated observations are excluded from current mode results."""
        service, _, _, _, observation_repo = _build_observation_fixture()

        # Invalidate the coverage observation
        observation_repo.invalidate(
            space="memorable",
            record_id="observation:coverage",
            invalidation_time=OBSERVATION_TIMESTAMPS["obs_invalidated"],
        )

        results = service.search(
            space="memorable",
            query="code coverage above 90 percent",
            mode="current",
        )

        result_ids = [r.source_id for r in results]
        assert "observation:coverage" not in result_ids

    def test_observation_point_in_time_mode(self) -> None:
        """Point-in-time queries return the observation valid at that time."""
        service, *_ = _build_observation_fixture()

        # Query at a time before v2 existed -- v1 should be returned
        at_before_v2 = datetime(2026, 5, 24, 10, 15, 0, tzinfo=UTC)

        results = service.search(
            space="memorable",
            query="storage preference PostgreSQL",
            mode="as-of",
            as_of=at_before_v2,
        )

        result_ids = [r.source_id for r in results]
        assert "observation:storage-pref:v1" in result_ids
        assert "observation:storage-pref:v2" not in result_ids


class TestObservationGraphExpansion:
    """Graph expansion for observations includes entity and supersession."""

    def test_graph_expand_observation_to_entities(self) -> None:
        """Observation graph expansion relates to entities in the same space."""
        service, *_ = _build_observation_fixture()

        results = service.search(
            space="memorable",
            query="storage preference observation SQLite",
            mode="current",
        )

        result_ids = [r.source_id for r in results]
        # Graph expansion should bring in the entity
        assert "entity:memorable" in result_ids

    def test_graph_expand_observation_supersession_links(self) -> None:
        """Observation graph expansion follows supersession links."""
        service, *_ = _build_observation_fixture()

        # Access internal method to verify supersession link traversal
        related = service._graph_expand(
            "memorable", "observation:storage-pref:v2", "Observation"
        )

        related_ids = [r_id for r_id, _ in related]
        # Should include the entity
        assert "entity:memorable" in related_ids
        # Should follow supersedes link back to v1
        assert "observation:storage-pref:v1" in related_ids

    def test_graph_expand_entity_to_observations(self) -> None:
        """Entity graph expansion includes observations in the same space."""
        service, *_ = _build_observation_fixture()

        related = service._graph_expand("memorable", "entity:memorable", "Entity")

        related_ids = [r_id for r_id, _ in related]
        related_kinds = [kind for _, kind in related]
        # Entity should expand to observations
        assert "Observation" in related_kinds
        # Should include current observations
        assert "observation:storage-pref:v2" in related_ids
        assert "observation:coverage" in related_ids


class TestObservationApplicationContext:
    """ApplicationContext wires observation_repo into HybridRetrievalService."""

    def test_build_retrieval_service_wires_observation_repo(self) -> None:
        """build_retrieval_service passes observation_repo to HybridRetrievalService."""
        from memorable.core.context import ApplicationContext

        ctx = ApplicationContext()
        service = ctx.build_retrieval_service()

        # The service should have an observation_repo attribute
        assert service._observation_repo is ctx.observation_repo
