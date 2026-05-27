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

from datetime import UTC, datetime

from memorable.core.models import Relation


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
