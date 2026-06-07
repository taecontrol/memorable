"""Tests for ApplicationContext About wiring."""

from __future__ import annotations

from datetime import UTC, datetime

PROFILE_YAML = """\
version: 1
space:
  name: memorable
entities:
  - name: Project
records: []
"""


def test_application_context_about_linker_uses_context_repositories() -> None:
    """ctx.about_linker links through the context's Entity and About repositories."""
    from memorable.core.application import RememberEntityService
    from memorable.core.context import ApplicationContext
    from memorable.core.profile import load_profile_from_yaml

    ctx = ApplicationContext()
    profile = load_profile_from_yaml(PROFILE_YAML)
    entity_service = RememberEntityService(repository=ctx.entity_repo, profile=profile)
    at = datetime(2026, 6, 7, 9, 0, tzinfo=UTC)
    entity_service.remember(
        space="memorable",
        entity_id="entity:build-2",
        entity_type="Project",
        name="Build 2",
        source_id="source:test",
        at=at,
    )

    ctx.about_linker().link(
        space="memorable",
        record_id="decision:build-2",
        entity_ids=["entity:build-2"],
    )

    assert ctx.about_repo.entities_for_record("memorable", "decision:build-2") == [
        "entity:build-2"
    ]
    assert ctx.about_repo.records_for_entity("memorable", "entity:build-2") == [
        "decision:build-2"
    ]
