"""Tests for the Relation domain model."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


class TestRelationConstruction:
    """A Relation is a typed, directed, temporal connection between two Entities."""

    def test_relation_holds_all_required_fields(self) -> None:
        """A valid Relation exposes all temporal and structural fields."""
        from memorable.core.models import Relation

        now = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)
        rel = Relation(
            id="rel:1",
            source_entity_id="entity:a",
            target_entity_id="entity:b",
            relation_type="depends-on",
            statement="A depends on B",
            space="my-project",
            validity_time=now,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )

        assert rel.id == "rel:1"
        assert rel.source_entity_id == "entity:a"
        assert rel.target_entity_id == "entity:b"
        assert rel.relation_type == "depends-on"
        assert rel.statement == "A depends on B"
        assert rel.space == "my-project"
        assert rel.validity_time == now
        assert rel.invalidation_time is None
        assert rel.lifecycle_state == "current"
        assert rel.supersedes is None
        assert rel.superseded_by is None


class TestRelationValidation:
    """Relation rejects invalid inputs at construction time."""

    def _valid_kwargs(self) -> dict:
        return dict(
            id="rel:1",
            source_entity_id="entity:a",
            target_entity_id="entity:b",
            relation_type="depends-on",
            statement="A depends on B",
            space="my-project",
            validity_time=datetime(2026, 5, 26, 12, 0, tzinfo=UTC),
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )

    @pytest.mark.parametrize(
        "field",
        ["id", "source_entity_id", "target_entity_id", "relation_type", "statement", "space"],
    )
    def test_empty_required_field_raises(self, field: str) -> None:
        """Each required string field rejects an empty value."""
        from memorable.core.models import Relation

        kwargs = self._valid_kwargs()
        kwargs[field] = ""

        with pytest.raises(ValueError, match=field):
            Relation(**kwargs)
