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

    def test_self_relation_raises(self) -> None:
        """A Relation where source and target are the same Entity is rejected."""
        from memorable.core.models import Relation

        kwargs = self._valid_kwargs()
        kwargs["source_entity_id"] = "entity:same"
        kwargs["target_entity_id"] = "entity:same"

        with pytest.raises(ValueError, match="self-relation"):
            Relation(**kwargs)


class TestRelationTemporalProtocol:
    """Relation structurally satisfies the TemporalRecord protocol."""

    def test_relation_satisfies_temporal_record_protocol(self) -> None:
        """A Relation instance is recognized as a TemporalRecord at runtime."""
        from memorable.core.models import Relation
        from memorable.core.ports import TemporalRecord

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

        assert isinstance(rel, TemporalRecord)


class TestRelationDeclaration:
    """RelationDeclaration declares allowed relation types in a MemoryProfile."""

    def test_relation_declaration_has_name(self) -> None:
        """A RelationDeclaration holds the name of an allowed relation type."""
        from memorable.core.profile import RelationDeclaration

        decl = RelationDeclaration(name="depends-on")
        assert decl.name == "depends-on"

    def test_memory_profile_has_relations_field_defaulting_to_empty(self) -> None:
        """MemoryProfile.relations defaults to an empty tuple."""
        from memorable.core.profile import MemoryProfile, SpaceDeclaration

        profile = MemoryProfile(
            version=1,
            space=SpaceDeclaration(name="test"),
        )

        assert profile.relations == ()

    def test_load_profile_parses_relations_section(self) -> None:
        """load_profile_from_yaml turns a relations: list into RelationDeclaration instances."""
        import textwrap

        from memorable.core.profile import RelationDeclaration, load_profile_from_yaml

        yaml_text = textwrap.dedent("""\
            version: 1
            space:
              name: test-project
            relations:
              - name: depends-on
              - name: owns
              - name: serves
        """)

        profile = load_profile_from_yaml(yaml_text)

        assert len(profile.relations) == 3
        assert profile.relations[0] == RelationDeclaration(name="depends-on")
        assert profile.relations[1] == RelationDeclaration(name="owns")
        assert profile.relations[2] == RelationDeclaration(name="serves")

    def test_profile_without_relations_section_loads(self) -> None:
        """A profile YAML without a relations: section loads with empty relations."""
        import textwrap

        from memorable.core.profile import load_profile_from_yaml

        yaml_text = textwrap.dedent("""\
            version: 1
            space:
              name: test-project
            entities:
              - name: Component
        """)

        profile = load_profile_from_yaml(yaml_text)

        assert profile.relations == ()
        assert len(profile.entities) == 1

    def test_relation_is_in_kernel_record_types(self) -> None:
        """'Relation' is a recognized kernel type for record declarations."""
        from memorable.core.profile import KERNEL_RECORD_TYPES

        assert "Relation" in KERNEL_RECORD_TYPES
