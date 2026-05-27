"""Tests for Relation retrieval integration.

Covers slice #64 acceptance criteria:
- indexable_text_for_relation() includes relation type, statement,
  endpoints, lifecycle state, and space
- Relations are indexed in the search index as source_kind="Relation"
- Relations surface as semantic search results when their statement
  matches a query
- Graph expansion from an Entity uses list_by_entity() to find connected
  Relations and extracts the other endpoint Entity with decayed score
- Superseded and invalidated Relations are excluded from graph expansion
- The fake "every Entity connects to every record" heuristic is removed
  for Entity expansion
- Supersession traversal for Decisions and Observations is unchanged
- HybridRetrievalService accepts a relation_repo in its constructor
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime

from memorable.core.models import Relation

# --- Shared fixture data ---

SOURCE_ID = "source:relation-test"

RELATION_PROFILE_YAML = textwrap.dedent("""\
    version: 1

    space:
      name: myproject
      description: Test project for relation retrieval

    entities:
      - name: Component
      - name: Service

    relations:
      - name: depends-on
      - name: owns

    records:
      - name: ArchitectureDecision
        extends: Decision
      - name: FollowUp
        extends: Task
      - name: GeneralObservation
        extends: Observation
""")

RELATION_TIMESTAMPS = {
    "entity_auth": datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC),
    "entity_token": datetime(2026, 5, 25, 10, 1, 0, tzinfo=UTC),
    "entity_db": datetime(2026, 5, 25, 10, 2, 0, tzinfo=UTC),
    "relation_v1": datetime(2026, 5, 25, 10, 10, 0, tzinfo=UTC),
    "relation_v2": datetime(2026, 5, 25, 10, 20, 0, tzinfo=UTC),
    "decision": datetime(2026, 5, 25, 10, 5, 0, tzinfo=UTC),
    "observation": datetime(2026, 5, 25, 10, 6, 0, tzinfo=UTC),
}


def _build_relation_fixture():
    """Build a fixture with entities, relations, and a retrieval service."""
    from memorable.core.application import (
        RememberDecisionService,
        RememberEntityService,
        RememberObservationService,
        RememberRelationService,
    )
    from memorable.core.profile import load_profile_from_yaml
    from memorable.core.repositories import (
        InMemoryDecisionRepository,
        InMemoryEntityRepository,
        InMemoryObservationRepository,
        InMemoryRelationRepository,
        InMemoryTaskRepository,
    )
    from memorable.retrieval.embeddings import FakeEmbeddingProvider
    from memorable.retrieval.service import HybridRetrievalService

    entity_repo = InMemoryEntityRepository()
    decision_repo = InMemoryDecisionRepository()
    task_repo = InMemoryTaskRepository()
    observation_repo = InMemoryObservationRepository()
    relation_repo = InMemoryRelationRepository()
    profile = load_profile_from_yaml(RELATION_PROFILE_YAML)

    # Entities
    entity_svc = RememberEntityService(repository=entity_repo, profile=profile)
    entity_svc.remember(
        space="myproject",
        entity_id="entity:auth-module",
        entity_type="Component",
        name="Auth Module",
        source_id=SOURCE_ID,
        at=RELATION_TIMESTAMPS["entity_auth"],
    )
    entity_svc.remember(
        space="myproject",
        entity_id="entity:token-service",
        entity_type="Service",
        name="Token Service",
        source_id=SOURCE_ID,
        at=RELATION_TIMESTAMPS["entity_token"],
    )
    entity_svc.remember(
        space="myproject",
        entity_id="entity:database",
        entity_type="Component",
        name="Database",
        source_id=SOURCE_ID,
        at=RELATION_TIMESTAMPS["entity_db"],
    )

    # Relation: auth-module depends-on token-service
    relation_svc = RememberRelationService(
        relation_repo=relation_repo, entity_repo=entity_repo, profile=profile
    )
    relation_svc.remember(
        space="myproject",
        relation_id="relation:auth-depends-token",
        source_entity_id="entity:auth-module",
        target_entity_id="entity:token-service",
        relation_type="depends-on",
        statement="auth-module depends on token-service for JWT validation",
        source_id=SOURCE_ID,
        at=RELATION_TIMESTAMPS["relation_v1"],
    )

    # Decision (for testing that Decision supersession is unchanged)
    decision_svc = RememberDecisionService(
        repository=decision_repo, profile=profile
    )
    decision_svc.remember(
        space="myproject",
        decision_id="decision:use-jwt",
        statement="Use JWT for authentication tokens",
        source_id=SOURCE_ID,
        at=RELATION_TIMESTAMPS["decision"],
    )

    # Observation (for testing that Observation supersession is unchanged)
    observation_svc = RememberObservationService(
        repository=observation_repo, profile=profile
    )
    observation_svc.remember(
        space="myproject",
        observation_id="observation:jwt-fast",
        statement="JWT validation is fast enough for our use case",
        source_id=SOURCE_ID,
        at=RELATION_TIMESTAMPS["observation"],
    )

    provider = FakeEmbeddingProvider(dimensions=32)
    service = HybridRetrievalService(
        entity_repo=entity_repo,
        decision_repo=decision_repo,
        task_repo=task_repo,
        observation_repo=observation_repo,
        relation_repo=relation_repo,
        embedding_provider=provider,
    )

    return (
        service,
        entity_repo,
        decision_repo,
        task_repo,
        observation_repo,
        relation_repo,
    )


# =====================================================================
# 1. Indexable Text for Relation
# =====================================================================


class TestIndexableTextForRelation:
    """indexable_text_for_relation() includes all required fields."""

    def test_includes_relation_type_and_statement(self) -> None:
        from memorable.retrieval.indexable_text import indexable_text_for_relation

        relation = Relation(
            id="relation:auth-depends-token",
            source_entity_id="entity:auth-module",
            target_entity_id="entity:token-service",
            relation_type="depends-on",
            statement="auth-module depends on token-service for JWT validation",
            space="myproject",
            validity_time=datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC),
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )

        text = indexable_text_for_relation(relation)

        assert "depends-on" in text
        assert "auth-module depends on token-service" in text

    def test_includes_endpoints(self) -> None:
        from memorable.retrieval.indexable_text import indexable_text_for_relation

        relation = Relation(
            id="relation:auth-depends-token",
            source_entity_id="entity:auth-module",
            target_entity_id="entity:token-service",
            relation_type="depends-on",
            statement="auth-module depends on token-service for JWT validation",
            space="myproject",
            validity_time=datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC),
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )

        text = indexable_text_for_relation(relation)

        assert "entity:auth-module" in text
        assert "entity:token-service" in text

    def test_includes_lifecycle_state_and_space(self) -> None:
        from memorable.retrieval.indexable_text import indexable_text_for_relation

        relation = Relation(
            id="relation:auth-depends-token",
            source_entity_id="entity:auth-module",
            target_entity_id="entity:token-service",
            relation_type="depends-on",
            statement="auth-module depends on token-service for JWT validation",
            space="myproject",
            validity_time=datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC),
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )

        text = indexable_text_for_relation(relation)

        assert "current" in text
        assert "myproject" in text

    def test_includes_id(self) -> None:
        from memorable.retrieval.indexable_text import indexable_text_for_relation

        relation = Relation(
            id="relation:auth-depends-token",
            source_entity_id="entity:auth-module",
            target_entity_id="entity:token-service",
            relation_type="depends-on",
            statement="auth-module depends on token-service for JWT validation",
            space="myproject",
            validity_time=datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC),
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )

        text = indexable_text_for_relation(relation)

        assert "relation:auth-depends-token" in text


# =====================================================================
# 2. HybridRetrievalService accepts relation_repo
# =====================================================================


class TestRelationRepoConstructor:
    """HybridRetrievalService accepts a relation_repo parameter."""

    def test_constructor_accepts_relation_repo(self) -> None:
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
            InMemoryEntityRepository,
            InMemoryObservationRepository,
            InMemoryRelationRepository,
            InMemoryTaskRepository,
        )
        from memorable.retrieval.embeddings import FakeEmbeddingProvider
        from memorable.retrieval.service import HybridRetrievalService

        service = HybridRetrievalService(
            entity_repo=InMemoryEntityRepository(),
            decision_repo=InMemoryDecisionRepository(),
            task_repo=InMemoryTaskRepository(),
            observation_repo=InMemoryObservationRepository(),
            relation_repo=InMemoryRelationRepository(),
            embedding_provider=FakeEmbeddingProvider(dimensions=32),
        )

        assert service._relation_repo is not None

    def test_constructor_defaults_relation_repo_to_none(self) -> None:
        """Without relation_repo, service still constructs (backward compat)."""
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
            InMemoryEntityRepository,
            InMemoryObservationRepository,
            InMemoryTaskRepository,
        )
        from memorable.retrieval.embeddings import FakeEmbeddingProvider
        from memorable.retrieval.service import HybridRetrievalService

        service = HybridRetrievalService(
            entity_repo=InMemoryEntityRepository(),
            decision_repo=InMemoryDecisionRepository(),
            task_repo=InMemoryTaskRepository(),
            observation_repo=InMemoryObservationRepository(),
            embedding_provider=FakeEmbeddingProvider(dimensions=32),
        )

        assert service._relation_repo is None


# =====================================================================
# 3. Relations surface as search results
# =====================================================================


class TestRelationSearchResults:
    """Relations are indexed and appear as search results."""

    def test_relation_appears_in_search_results(self) -> None:
        """A Relation surfaces as a search result with source_kind='Relation'."""
        service, *_ = _build_relation_fixture()

        results = service.search(
            space="myproject",
            query="auth-module depends on token-service JWT validation",
            mode="current",
        )

        result_ids = [r.source_id for r in results]
        assert "relation:auth-depends-token" in result_ids

        relation_results = [
            r for r in results if r.source_id == "relation:auth-depends-token"
        ]
        assert relation_results[0].source_kind == "Relation"

    def test_relation_result_has_lifecycle_state(self) -> None:
        service, *_ = _build_relation_fixture()

        results = service.search(
            space="myproject",
            query="auth-module depends on token-service",
            mode="current",
        )

        relation_results = [
            r for r in results if r.source_id == "relation:auth-depends-token"
        ]
        assert len(relation_results) == 1
        assert relation_results[0].lifecycle_state == "current"
