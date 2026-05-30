"""Tests for Entity write with inspectable Provenance.

Covers slice #6 acceptance criteria:
- Entity writes are validated by the MemoryProfile where applicable.
- Every write records provenance with Source or Episode information.
- Provenance inspection explains where the memory came from and why it is believed.
- Normal outputs use Entity, Source, Episode, Provenance, and MemorySpace language.
- The fixture can remember Entity Memorable at 2026-05-23T10:10:00Z.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime

import pytest

# --- Fixture data ---

FIXTURE_TIMESTAMP = datetime(2026, 5, 23, 10, 10, 0, tzinfo=UTC)

VALID_PROFILE_YAML = textwrap.dedent("""\
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
""")


# =====================================================================
# Domain model tests
# =====================================================================


class TestEntityModel:
    """Entity is a remembered thing with identity inside a MemorySpace."""

    def test_entity_has_identity_and_type(self) -> None:
        from memorable.core.models import Entity

        entity = Entity(
            id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            space="memorable",
        )
        assert entity.id == "entity:memorable"
        assert entity.entity_type == "Project"
        assert entity.name == "Memorable"
        assert entity.space == "memorable"

    def test_entity_is_frozen(self) -> None:
        from memorable.core.models import Entity

        entity = Entity(id="entity:x", entity_type="Project", name="X", space="s")
        with pytest.raises(AttributeError):
            entity.name = "Y"  # type: ignore[misc]

    def test_entity_requires_non_empty_id(self) -> None:
        from memorable.core.models import Entity

        with pytest.raises(ValueError, match="id"):
            Entity(id="", entity_type="Project", name="X", space="s")

    def test_entity_requires_non_empty_name(self) -> None:
        from memorable.core.models import Entity

        with pytest.raises(ValueError, match="name"):
            Entity(id="entity:x", entity_type="Project", name="", space="s")


class TestSourceModel:
    """Source is where a memory came from."""

    def test_source_has_id_and_category(self) -> None:
        from memorable.core.models import Source

        source = Source(id="source:tracer-fixture", category="test_fixture")
        assert source.id == "source:tracer-fixture"
        assert source.category == "test_fixture"


class TestEpisodeModel:
    """Episode is a provenance event that produced memory."""

    def test_episode_has_id_source_and_timestamp(self) -> None:
        from memorable.core.models import Episode

        episode = Episode(
            id="episode:tracer:2026-05-23T10:10:00Z",
            source_id="source:tracer-fixture",
            timestamp=FIXTURE_TIMESTAMP,
        )
        assert episode.id == "episode:tracer:2026-05-23T10:10:00Z"
        assert episode.source_id == "source:tracer-fixture"
        assert episode.timestamp == FIXTURE_TIMESTAMP


class TestProvenanceModel:
    """Provenance explains where a memory came from and why it is believed."""

    def test_provenance_has_required_fields(self) -> None:
        from memorable.core.models import Provenance

        prov = Provenance(
            record_id="entity:memorable",
            record_kind="entity",
            source_id="source:tracer-fixture",
            episode_id="episode:tracer:2026-05-23T10:10:00Z",
            writer="agent:tracer-fixture",
            reason="tests Entity write with inspectable provenance",
            creation_time=FIXTURE_TIMESTAMP,
            validity_time=FIXTURE_TIMESTAMP,
        )
        assert prov.record_id == "entity:memorable"
        assert prov.record_kind == "entity"
        assert prov.source_id == "source:tracer-fixture"
        assert prov.episode_id == "episode:tracer:2026-05-23T10:10:00Z"
        assert prov.writer == "agent:tracer-fixture"
        assert prov.reason == "tests Entity write with inspectable provenance"
        assert prov.creation_time == FIXTURE_TIMESTAMP
        assert prov.validity_time == FIXTURE_TIMESTAMP


# =====================================================================
# Repository port tests
# =====================================================================


class TestEntityRepositoryPort:
    """EntityRepository protocol defines persistence for Entities with provenance."""

    def test_in_memory_entity_repository_saves_and_retrieves(self) -> None:
        from memorable.core.models import Entity, Provenance
        from memorable.core.repositories import InMemoryEntityRepository

        repo = InMemoryEntityRepository()
        entity = Entity(
            id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            space="memorable",
        )
        provenance = Provenance(
            record_id="entity:memorable",
            record_kind="entity",
            source_id="source:tracer-fixture",
            episode_id="episode:tracer:2026-05-23T10:10:00Z",
            writer="agent:tracer-fixture",
            reason="test",
            creation_time=FIXTURE_TIMESTAMP,
            validity_time=FIXTURE_TIMESTAMP,
        )

        repo.save(entity, provenance)
        retrieved = repo.get(space="memorable", entity_id="entity:memorable")

        assert retrieved is not None
        assert retrieved.id == "entity:memorable"

    def test_in_memory_entity_repository_retrieves_provenance(self) -> None:
        from memorable.core.models import Entity, Provenance
        from memorable.core.repositories import InMemoryEntityRepository

        repo = InMemoryEntityRepository()
        entity = Entity(
            id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            space="memorable",
        )
        provenance = Provenance(
            record_id="entity:memorable",
            record_kind="entity",
            source_id="source:tracer-fixture",
            episode_id="episode:tracer:2026-05-23T10:10:00Z",
            writer="agent:tracer-fixture",
            reason="test provenance retrieval",
            creation_time=FIXTURE_TIMESTAMP,
            validity_time=FIXTURE_TIMESTAMP,
        )

        repo.save(entity, provenance)
        prov = repo.get_provenance(space="memorable", entity_id="entity:memorable")

        assert prov is not None
        assert prov.source_id == "source:tracer-fixture"
        assert prov.episode_id == "episode:tracer:2026-05-23T10:10:00Z"
        assert prov.writer == "agent:tracer-fixture"

    def test_get_returns_none_for_missing_entity(self) -> None:
        from memorable.core.repositories import InMemoryEntityRepository

        repo = InMemoryEntityRepository()
        assert repo.get(space="memorable", entity_id="entity:missing") is None

    def test_get_provenance_returns_none_for_missing_entity(self) -> None:
        from memorable.core.repositories import InMemoryEntityRepository

        repo = InMemoryEntityRepository()
        assert (
            repo.get_provenance(space="memorable", entity_id="entity:missing") is None
        )


# =====================================================================
# Application service tests
# =====================================================================


class TestRememberEntityService:
    """RememberEntityService validates against MemoryProfile and creates provenance."""

    def _make_service(self):
        from memorable.core.application import RememberEntityService
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryEntityRepository

        repo = InMemoryEntityRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        return RememberEntityService(repository=repo, profile=profile), repo

    def test_remember_entity_stores_entity_with_provenance(self) -> None:
        service, repo = self._make_service()

        result = service.remember(
            space="memorable",
            entity_id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            source_id="source:tracer-fixture",
            at=FIXTURE_TIMESTAMP,
        )

        assert result.entity.id == "entity:memorable"
        assert result.entity.entity_type == "Project"
        assert result.entity.name == "Memorable"
        assert result.provenance.source_id == "source:tracer-fixture"
        assert result.provenance.creation_time == FIXTURE_TIMESTAMP
        assert result.provenance.validity_time == FIXTURE_TIMESTAMP

        # Verify persisted
        stored = repo.get(space="memorable", entity_id="entity:memorable")
        assert stored is not None
        assert stored.name == "Memorable"

    def test_remember_entity_creates_episode(self) -> None:
        """The service creates an Episode from the source and timestamp."""
        service, _repo = self._make_service()

        result = service.remember(
            space="memorable",
            entity_id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            source_id="source:tracer-fixture",
            at=FIXTURE_TIMESTAMP,
        )

        assert result.provenance.episode_id is not None
        assert "2026-05-23T10:10:00" in result.provenance.episode_id

    def test_remember_entity_rejects_undeclared_entity_type(self) -> None:
        """Entity type must be declared in the MemoryProfile."""
        service, _repo = self._make_service()

        with pytest.raises(ValueError, match="not declared"):
            service.remember(
                space="memorable",
                entity_id="entity:x",
                entity_type="UnknownType",
                name="X",
                source_id="source:test",
                at=FIXTURE_TIMESTAMP,
            )

    def test_remember_entity_sets_writer(self) -> None:
        """Provenance writer is set to agent:tracer-fixture by default."""
        service, _repo = self._make_service()

        result = service.remember(
            space="memorable",
            entity_id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            source_id="source:tracer-fixture",
            at=FIXTURE_TIMESTAMP,
            writer="agent:tracer-fixture",
        )

        assert result.provenance.writer == "agent:tracer-fixture"


class TestInspectProvenance:
    """Provenance inspection explains where a memory came from."""

    def _remember_fixture_entity(self):
        from memorable.core.application import RememberEntityService
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryEntityRepository

        repo = InMemoryEntityRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        service = RememberEntityService(repository=repo, profile=profile)

        service.remember(
            space="memorable",
            entity_id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            source_id="source:tracer-fixture",
            at=FIXTURE_TIMESTAMP,
            writer="agent:tracer-fixture",
            reason="tests Entity write with inspectable provenance",
        )
        return service, repo

    def test_inspect_provenance_returns_full_provenance(self) -> None:
        from memorable.core.application import InspectProvenanceService

        _service, repo = self._remember_fixture_entity()
        inspector = InspectProvenanceService(repository=repo)

        result = inspector.inspect(space="memorable", entity_id="entity:memorable")

        assert result is not None
        assert result.source_id == "source:tracer-fixture"
        assert result.writer == "agent:tracer-fixture"
        assert result.creation_time == FIXTURE_TIMESTAMP
        assert result.validity_time == FIXTURE_TIMESTAMP
        assert "inspectable provenance" in result.reason

    def test_inspect_provenance_returns_none_for_missing(self) -> None:
        from memorable.core.application import InspectProvenanceService
        from memorable.core.repositories import InMemoryEntityRepository

        repo = InMemoryEntityRepository()
        inspector = InspectProvenanceService(repository=repo)

        result = inspector.inspect(space="memorable", entity_id="entity:missing")
        assert result is None


# =====================================================================
# CLI adapter tests
# =====================================================================


@pytest.mark.usefixtures("cli_in_memory_context")
class TestCLIRememberEntity:
    """CLI `memorable remember entity` writes an Entity with provenance."""

    def test_remember_entity_command(self, capsys) -> None:
        from memorable.cli import main

        exit_code = main(
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
                "source:tracer-fixture",
                "--at",
                "2026-05-23T10:10:00Z",
            ]
        )

        assert exit_code == 0
        output = capsys.readouterr().out
        assert "entity:memorable" in output
        assert "source:tracer-fixture" in output

    def test_remember_entity_includes_unified_provenance_fields(self, capsys) -> None:
        """CLI remember entity JSON output includes record_id and record_kind."""
        import json

        from memorable.cli import main

        exit_code = main(
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
                "source:tracer-fixture",
                "--at",
                "2026-05-23T10:10:00Z",
            ]
        )

        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["record_id"] == "entity:memorable"
        assert output["record_kind"] == "entity"

    def test_remember_entity_rejects_undeclared_type(self, capsys) -> None:
        from memorable.cli import main

        exit_code = main(
            [
                "remember",
                "entity",
                "--space",
                "memorable",
                "--id",
                "entity:x",
                "--type",
                "UnknownType",
                "--name",
                "X",
                "--source",
                "source:test",
                "--at",
                "2026-05-23T10:10:00Z",
            ]
        )

        assert exit_code == 1
        err = capsys.readouterr().err
        assert "not declared" in err


@pytest.mark.usefixtures("cli_in_memory_context")
class TestCLIInspectProvenance:
    """CLI `memorable inspect provenance` shows where a memory came from."""

    def test_inspect_provenance_command(self, capsys) -> None:
        """After remembering, inspect provenance shows full provenance info."""
        from memorable.cli import main

        # First remember an entity
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
                "source:tracer-fixture",
                "--at",
                "2026-05-23T10:10:00Z",
            ]
        )

        # Then inspect its provenance
        exit_code = main(
            [
                "inspect",
                "provenance",
                "--space",
                "memorable",
                "--id",
                "entity:memorable",
            ]
        )

        assert exit_code == 0
        output = capsys.readouterr().out
        assert "source:tracer-fixture" in output
        assert "2026-05-23T10:10:00" in output

    def test_inspect_provenance_shows_record_kind(self, capsys) -> None:
        """Inspect provenance output includes Record Kind field."""
        from memorable.cli import main

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
                "source:tracer-fixture",
                "--at",
                "2026-05-23T10:10:00Z",
            ]
        )

        exit_code = main(
            [
                "inspect",
                "provenance",
                "--space",
                "memorable",
                "--id",
                "entity:memorable",
            ]
        )

        assert exit_code == 0
        output = capsys.readouterr().out
        assert "Record Kind:" in output
        assert "entity" in output


# =====================================================================
# MCP adapter tests
# =====================================================================


class TestMCPRememberEntity:
    """MCP remember_entity_tool writes an Entity with provenance."""

    def test_remember_entity_tool(self) -> None:
        from memorable.mcp.server import remember_entity_tool

        result = remember_entity_tool(
            space="memorable",
            entity_id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            source="source:tracer-fixture",
            at="2026-05-23T10:10:00Z",
        )

        assert result["entity_id"] == "entity:memorable"
        assert result["source"] == "source:tracer-fixture"
        assert "error" not in result

    def test_remember_entity_tool_includes_unified_provenance_fields(self) -> None:
        """MCP remember_entity_tool response includes record_id and record_kind."""
        from memorable.mcp.server import remember_entity_tool

        result = remember_entity_tool(
            space="memorable",
            entity_id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            source="source:tracer-fixture",
            at="2026-05-23T10:10:00Z",
        )

        assert "error" not in result
        assert result["record_id"] == "entity:memorable"
        assert result["record_kind"] == "entity"

    def test_remember_entity_tool_rejects_undeclared_type(self) -> None:
        from memorable.mcp.server import remember_entity_tool

        result = remember_entity_tool(
            space="memorable",
            entity_id="entity:x",
            entity_type="UnknownType",
            name="X",
            source="source:test",
            at="2026-05-23T10:10:00Z",
        )

        assert "error" in result
        assert "not declared" in result["error"]


class TestMCPInspectProvenance:
    """MCP inspect_provenance_tool shows where a memory came from."""

    def test_inspect_provenance_tool(self) -> None:
        from memorable.mcp.server import inspect_provenance_tool, remember_entity_tool

        remember_entity_tool(
            space="memorable",
            entity_id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            source="source:tracer-fixture",
            at="2026-05-23T10:10:00Z",
        )

        result = inspect_provenance_tool(
            space="memorable",
            entity_id="entity:memorable",
        )

        assert "error" not in result
        assert result["source"] == "source:tracer-fixture"
        assert result["writer"] is not None
        assert "2026-05-23T10:10:00" in result["creation_time"]

    def test_inspect_provenance_tool_includes_unified_fields(self) -> None:
        """MCP inspect_provenance_tool response includes record_id and record_kind."""
        from memorable.mcp.server import inspect_provenance_tool, remember_entity_tool

        remember_entity_tool(
            space="memorable",
            entity_id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            source="source:tracer-fixture",
            at="2026-05-23T10:10:00Z",
        )

        result = inspect_provenance_tool(
            space="memorable",
            entity_id="entity:memorable",
        )

        assert "error" not in result
        assert result["record_id"] == "entity:memorable"
        assert result["record_kind"] == "entity"

    def test_inspect_provenance_returns_error_for_missing(self) -> None:
        from memorable.mcp.server import inspect_provenance_tool

        result = inspect_provenance_tool(
            space="memorable",
            entity_id="entity:missing",
        )

        assert "error" in result


# =====================================================================
# Language boundary test
# =====================================================================


class TestLanguageBoundary:
    """Outputs use Entity, Source, Episode, Provenance, and MemorySpace language."""

    def test_no_storage_vocabulary_in_error_messages(self) -> None:
        """Error messages must not leak storage terms."""
        from memorable.core.application import RememberEntityService
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryEntityRepository

        repo = InMemoryEntityRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        service = RememberEntityService(repository=repo, profile=profile)

        storage_terms = {
            "node",
            "edge",
            "index",
            "vertex",
            "graph",
            "database",
            "table",
        }

        with pytest.raises(ValueError) as exc_info:
            service.remember(
                space="memorable",
                entity_id="entity:x",
                entity_type="UnknownType",
                name="X",
                source_id="source:test",
                at=FIXTURE_TIMESTAMP,
            )
        message_lower = str(exc_info.value).lower()
        for term in storage_terms:
            assert term not in message_lower, (
                f"Storage vocabulary '{term}' found in error: {exc_info.value}"
            )
