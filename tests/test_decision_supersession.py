"""Tests for Decision supersession and temporal truth.

Covers slice #7 acceptance criteria:
- Initial Decision is valid at 2026-05-23T10:15:00Z.
- Superseding Decision is valid at 2026-05-23T10:20:00Z
  and explicitly supersedes the initial Decision.
- Current Truth returns the superseding Decision.
- Point-In-Time Truth before supersession returns initial.
- Point-In-Time Truth after supersession returns new.
- History is append-first and inspectable.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime

import pytest

# --- Fixture data ---

FIXTURE_TIMESTAMP_V1 = datetime(2026, 5, 23, 10, 15, 0, tzinfo=UTC)
FIXTURE_TIMESTAMP_V2 = datetime(2026, 5, 23, 10, 20, 0, tzinfo=UTC)

STATEMENT_V1 = "Graphiti is the first implementation path for Memorable storage."
STATEMENT_V2 = (
    "Direct Neo4j is the first implementation path;"
    " Graphiti remains optional behind the"
    " storage adapter."
)

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
""")

V1_ID = "decision:storage-path:v1"
V2_ID = "decision:storage-path:v2"
SOURCE_ID = "source:tracer-fixture"
EPISODE_V1 = "episode:tracer-fixture:2026-05-23T10:15:00+00:00"
EPISODE_V2 = "episode:tracer-fixture:2026-05-23T10:20:00+00:00"


# =====================================================================
# Domain model tests
# =====================================================================


class TestDecisionModel:
    """Decision is a remembered choice with temporal validity."""

    def test_decision_has_required_fields(self) -> None:
        from memorable.core.models import Decision

        decision = Decision(
            id=V1_ID,
            statement=STATEMENT_V1,
            space="memorable",
            validity_time=FIXTURE_TIMESTAMP_V1,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        assert decision.id == V1_ID
        assert decision.statement == STATEMENT_V1
        assert decision.space == "memorable"
        assert decision.validity_time == FIXTURE_TIMESTAMP_V1
        assert decision.invalidation_time is None
        assert decision.lifecycle_state == "current"
        assert decision.supersedes is None
        assert decision.superseded_by is None

    def test_decision_is_frozen(self) -> None:
        from memorable.core.models import Decision

        decision = Decision(
            id="decision:x",
            statement="X",
            space="s",
            validity_time=FIXTURE_TIMESTAMP_V1,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        with pytest.raises(AttributeError):
            decision.statement = "Y"  # type: ignore[misc]

    def test_decision_requires_non_empty_id(self) -> None:
        from memorable.core.models import Decision

        with pytest.raises(ValueError, match="id"):
            Decision(
                id="",
                statement="X",
                space="s",
                validity_time=FIXTURE_TIMESTAMP_V1,
                invalidation_time=None,
                lifecycle_state="current",
                supersedes=None,
                superseded_by=None,
            )

    def test_decision_requires_non_empty_statement(self) -> None:
        from memorable.core.models import Decision

        with pytest.raises(ValueError, match="statement"):
            Decision(
                id="decision:x",
                statement="",
                space="s",
                validity_time=FIXTURE_TIMESTAMP_V1,
                invalidation_time=None,
                lifecycle_state="current",
                supersedes=None,
                superseded_by=None,
            )


class TestDecisionProvenanceModel:
    """Provenance explains where a Decision came from."""

    def test_decision_provenance_has_required_fields(self) -> None:
        from memorable.core.models import Provenance

        prov = Provenance(
            record_id=V1_ID,
            record_kind="decision",
            source_id=SOURCE_ID,
            episode_id=EPISODE_V1,
            writer="agent:tracer-fixture",
            reason="tests Decision supersession",
            creation_time=FIXTURE_TIMESTAMP_V1,
            validity_time=FIXTURE_TIMESTAMP_V1,
        )
        assert prov.record_id == V1_ID
        assert prov.record_kind == "decision"
        assert prov.source_id == SOURCE_ID
        assert prov.writer == "agent:tracer-fixture"
        assert prov.creation_time == FIXTURE_TIMESTAMP_V1
        assert prov.validity_time == FIXTURE_TIMESTAMP_V1


# =====================================================================
# Repository port tests
# =====================================================================


class TestDecisionRepositoryPort:
    """DecisionRepository defines persistence for Decisions."""

    def _make_decision_v1(self):
        from memorable.core.models import Decision, Provenance

        decision = Decision(
            id=V1_ID,
            statement=STATEMENT_V1,
            space="memorable",
            validity_time=FIXTURE_TIMESTAMP_V1,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        provenance = Provenance(
            record_id=V1_ID,
            record_kind="decision",
            source_id=SOURCE_ID,
            episode_id=EPISODE_V1,
            writer="agent:tracer-fixture",
            reason="initial decision",
            creation_time=FIXTURE_TIMESTAMP_V1,
            validity_time=FIXTURE_TIMESTAMP_V1,
        )
        return decision, provenance

    def _make_decision_v2(self):
        from memorable.core.models import Decision, Provenance

        decision = Decision(
            id=V2_ID,
            statement=STATEMENT_V2,
            space="memorable",
            validity_time=FIXTURE_TIMESTAMP_V2,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=V1_ID,
            superseded_by=None,
        )
        provenance = Provenance(
            record_id=V2_ID,
            record_kind="decision",
            source_id=SOURCE_ID,
            episode_id=EPISODE_V2,
            writer="agent:tracer-fixture",
            reason="superseding decision",
            creation_time=FIXTURE_TIMESTAMP_V2,
            validity_time=FIXTURE_TIMESTAMP_V2,
        )
        return decision, provenance

    def test_save_and_retrieve_decision(self) -> None:
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        repo = InMemoryDecisionRepository()
        decision, provenance = self._make_decision_v1()

        repo.save(decision, provenance)
        retrieved = repo.get(space="memorable", record_id=V1_ID)

        assert retrieved is not None
        assert retrieved.id == V1_ID
        assert retrieved.statement == STATEMENT_V1

    def test_retrieve_provenance(self) -> None:
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        repo = InMemoryDecisionRepository()
        decision, provenance = self._make_decision_v1()

        repo.save(decision, provenance)
        prov = repo.get_provenance(space="memorable", record_id=V1_ID)

        assert prov is not None
        assert prov.source_id == SOURCE_ID
        assert prov.writer == "agent:tracer-fixture"

    def test_get_returns_none_for_missing(self) -> None:
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        repo = InMemoryDecisionRepository()
        assert repo.get(space="memorable", record_id="decision:missing") is None

    def test_get_provenance_returns_none_for_missing(self) -> None:
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        repo = InMemoryDecisionRepository()
        assert (
            repo.get_provenance(space="memorable", record_id="decision:missing") is None
        )

    def test_mark_superseded_updates_old_decision(self) -> None:
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        repo = InMemoryDecisionRepository()
        v1, prov1 = self._make_decision_v1()

        repo.save(v1, prov1)
        repo.mark_superseded(
            space="memorable",
            record_id=V1_ID,
            superseded_by=V2_ID,
            invalidation_time=FIXTURE_TIMESTAMP_V2,
        )

        updated = repo.get(space="memorable", record_id=V1_ID)
        assert updated is not None
        assert updated.lifecycle_state == "superseded"
        assert updated.invalidation_time == FIXTURE_TIMESTAMP_V2
        assert updated.superseded_by == V2_ID

    def test_append_first_v1_not_deleted(self) -> None:
        """Append-first: v1 not deleted, just marked."""
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        repo = InMemoryDecisionRepository()
        v1, prov1 = self._make_decision_v1()
        v2, prov2 = self._make_decision_v2()

        repo.save(v1, prov1)
        repo.save(v2, prov2)
        repo.mark_superseded(
            space="memorable",
            record_id=V1_ID,
            superseded_by=V2_ID,
            invalidation_time=FIXTURE_TIMESTAMP_V2,
        )

        # v1 still exists
        v1_stored = repo.get(space="memorable", record_id=V1_ID)
        assert v1_stored is not None
        assert v1_stored.lifecycle_state == "superseded"

        # v2 also exists
        v2_stored = repo.get(space="memorable", record_id=V2_ID)
        assert v2_stored is not None
        assert v2_stored.lifecycle_state == "current"


# =====================================================================
# Application service tests
# =====================================================================


class TestRememberDecisionService:
    """RememberDecisionService validates and creates provenance."""

    def _make_service(self):
        from memorable.core.application import (
            RememberDecisionService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        repo = InMemoryDecisionRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        return (
            RememberDecisionService(repository=repo, profile=profile),
            repo,
        )

    def test_remember_decision_stores_with_provenance(self) -> None:
        service, repo = self._make_service()

        result = service.remember(
            space="memorable",
            decision_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        assert result.decision.id == V1_ID
        assert result.decision.lifecycle_state == "current"
        assert result.provenance.source_id == SOURCE_ID
        assert result.provenance.creation_time == FIXTURE_TIMESTAMP_V1

        stored = repo.get(space="memorable", record_id=V1_ID)
        assert stored is not None

    def test_remember_decision_with_supersession(self) -> None:
        service, repo = self._make_service()

        # Remember v1
        service.remember(
            space="memorable",
            decision_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        # Remember v2, superseding v1
        result = service.remember(
            space="memorable",
            decision_id=V2_ID,
            statement=STATEMENT_V2,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V2,
            supersedes=V1_ID,
        )

        assert result.decision.id == V2_ID
        assert result.decision.supersedes == V1_ID
        assert result.decision.lifecycle_state == "current"

        # v1 should now be marked superseded
        v1 = repo.get(space="memorable", record_id=V1_ID)
        assert v1 is not None
        assert v1.lifecycle_state == "superseded"
        assert v1.invalidation_time == FIXTURE_TIMESTAMP_V2
        assert v1.superseded_by == V2_ID

    def test_rejects_profile_without_decision_record(self) -> None:
        """Profile must have a record that extends Decision."""
        from memorable.core.application import (
            RememberDecisionService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        no_decision_yaml = textwrap.dedent("""\
            version: 1
            space:
              name: memorable
              description: test
            entities:
              - name: Project
            records: []
        """)
        repo = InMemoryDecisionRepository()
        profile = load_profile_from_yaml(no_decision_yaml)

        service = RememberDecisionService(repository=repo, profile=profile)

        with pytest.raises(ValueError, match="Decision"):
            service.remember(
                space="memorable",
                decision_id="decision:x",
                statement="X",
                source_id="source:test",
                at=FIXTURE_TIMESTAMP_V1,
            )

    def test_remember_decision_sets_writer(self) -> None:
        service, _repo = self._make_service()

        result = service.remember(
            space="memorable",
            decision_id=V1_ID,
            statement="Test decision.",
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
            writer="agent:tracer-fixture",
        )

        assert result.provenance.writer == "agent:tracer-fixture"


class TestCurrentTruthService:
    """CurrentTruthService follows supersession chain."""

    def _setup_chain(self):
        from memorable.core.application import (
            CurrentTruthService,
            RememberDecisionService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        repo = InMemoryDecisionRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberDecisionService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            decision_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )
        remember.remember(
            space="memorable",
            decision_id=V2_ID,
            statement=STATEMENT_V2,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V2,
            supersedes=V1_ID,
        )

        return CurrentTruthService(repository=repo), repo

    def test_current_truth_returns_superseding(self) -> None:
        service, _repo = self._setup_chain()

        result = service.current(space="memorable", record_id=V1_ID)

        assert result is not None
        assert result.id == V2_ID

    def test_current_truth_returns_self_when_not_superseded(
        self,
    ) -> None:
        from memorable.core.application import (
            CurrentTruthService,
            RememberDecisionService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        repo = InMemoryDecisionRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberDecisionService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            decision_id=V1_ID,
            statement="Graphiti is the first path.",
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        service = CurrentTruthService(repository=repo)
        result = service.current(space="memorable", record_id=V1_ID)

        assert result is not None
        assert result.id == V1_ID

    def test_current_truth_returns_none_for_missing(self) -> None:
        from memorable.core.application import CurrentTruthService
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        repo = InMemoryDecisionRepository()
        service = CurrentTruthService(repository=repo)

        result = service.current(space="memorable", record_id="decision:missing")
        assert result is None


class TestPointInTimeTruthService:
    """PointInTimeTruthService returns Decision valid at a time."""

    def _setup_chain(self):
        from memorable.core.application import (
            PointInTimeTruthService,
            RememberDecisionService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        repo = InMemoryDecisionRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberDecisionService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            decision_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )
        remember.remember(
            space="memorable",
            decision_id=V2_ID,
            statement=STATEMENT_V2,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V2,
            supersedes=V1_ID,
        )

        return PointInTimeTruthService(repository=repo), repo

    def test_before_supersession_returns_v1(self) -> None:
        service, _repo = self._setup_chain()

        at_1017 = datetime(2026, 5, 23, 10, 17, 0, tzinfo=UTC)
        result = service.at(space="memorable", record_id=V1_ID, at=at_1017)

        assert result is not None
        assert result.id == V1_ID

    def test_after_supersession_returns_v2(self) -> None:
        service, _repo = self._setup_chain()

        at_1021 = datetime(2026, 5, 23, 10, 21, 0, tzinfo=UTC)
        result = service.at(space="memorable", record_id=V1_ID, at=at_1021)

        assert result is not None
        assert result.id == V2_ID

    def test_returns_none_for_missing(self) -> None:
        from memorable.core.application import (
            PointInTimeTruthService,
        )
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        repo = InMemoryDecisionRepository()
        service = PointInTimeTruthService(repository=repo)

        result = service.at(
            space="memorable",
            record_id="decision:missing",
            at=FIXTURE_TIMESTAMP_V1,
        )
        assert result is None


class TestInspectHistoryService:
    """InspectHistoryService returns the supersession chain."""

    def _setup_chain(self):
        from memorable.core.application import (
            InspectHistoryService,
            RememberDecisionService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        repo = InMemoryDecisionRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberDecisionService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            decision_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )
        remember.remember(
            space="memorable",
            decision_id=V2_ID,
            statement=STATEMENT_V2,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V2,
            supersedes=V1_ID,
        )

        return InspectHistoryService(repository=repo), repo

    def test_history_returns_full_chain(self) -> None:
        service, _repo = self._setup_chain()

        history = service.history(space="memorable", record_id=V1_ID)

        assert len(history) == 2
        assert history[0].id == V1_ID
        assert history[1].id == V2_ID

    def test_history_single_when_not_superseded(self) -> None:
        from memorable.core.application import (
            InspectHistoryService,
            RememberDecisionService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        repo = InMemoryDecisionRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberDecisionService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            decision_id=V1_ID,
            statement="Only one decision.",
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        service = InspectHistoryService(repository=repo)
        history = service.history(space="memorable", record_id=V1_ID)

        assert len(history) == 1
        assert history[0].id == V1_ID

    def test_history_returns_empty_for_missing(self) -> None:
        from memorable.core.application import (
            InspectHistoryService,
        )
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        repo = InMemoryDecisionRepository()
        service = InspectHistoryService(repository=repo)

        history = service.history(space="memorable", record_id="decision:missing")
        assert history == []


# =====================================================================
# CLI adapter tests
# =====================================================================


@pytest.mark.usefixtures("cli_in_memory_context")
class TestCLIRememberDecision:
    """CLI `memorable remember decision` writes a Decision."""

    def test_remember_decision_command(self, capsys) -> None:
        from memorable.cli import main

        exit_code = main(
            [
                "remember",
                "decision",
                "--space",
                "memorable",
                "--id",
                V1_ID,
                "--statement",
                STATEMENT_V1,
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:15:00Z",
            ]
        )

        assert exit_code == 0
        output = capsys.readouterr().out
        assert V1_ID in output
        assert SOURCE_ID in output

    def test_remember_decision_includes_unified_provenance_fields(self, capsys) -> None:
        """CLI remember decision JSON output includes record_id and record_kind."""
        import json

        from memorable.cli import main

        exit_code = main(
            [
                "remember",
                "decision",
                "--space",
                "memorable",
                "--id",
                V1_ID,
                "--statement",
                STATEMENT_V1,
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:15:00Z",
            ]
        )

        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["record_id"] == V1_ID
        assert output["record_kind"] == "decision"

    def test_remember_decision_with_supersession(self, capsys) -> None:
        from memorable.cli import main

        # Remember v1
        main(
            [
                "remember",
                "decision",
                "--space",
                "memorable",
                "--id",
                V1_ID,
                "--statement",
                STATEMENT_V1,
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:15:00Z",
            ]
        )

        # Remember v2 superseding v1
        exit_code = main(
            [
                "remember",
                "decision",
                "--space",
                "memorable",
                "--id",
                V2_ID,
                "--statement",
                "Direct Neo4j first.",
                "--supersedes",
                V1_ID,
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:20:00Z",
            ]
        )

        assert exit_code == 0
        output = capsys.readouterr().out
        assert V2_ID in output


@pytest.mark.usefixtures("cli_in_memory_context")
class TestCLITruthCurrent:
    """CLI `memorable truth current` follows supersession."""

    def test_truth_current_command(self, capsys) -> None:
        from memorable.cli import main

        main(
            [
                "remember",
                "decision",
                "--space",
                "memorable",
                "--id",
                V1_ID,
                "--statement",
                "Graphiti first.",
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:15:00Z",
            ]
        )
        main(
            [
                "remember",
                "decision",
                "--space",
                "memorable",
                "--id",
                V2_ID,
                "--statement",
                "Direct Neo4j first.",
                "--supersedes",
                V1_ID,
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:20:00Z",
            ]
        )

        exit_code = main(
            [
                "truth",
                "current",
                "--space",
                "memorable",
                "--id",
                V1_ID,
            ]
        )

        assert exit_code == 0
        output = capsys.readouterr().out
        assert V2_ID in output


@pytest.mark.usefixtures("cli_in_memory_context")
class TestCLITruthAsOf:
    """CLI `memorable truth as-of` returns Decision at a time."""

    def test_truth_as_of_before_supersession(self, capsys) -> None:
        from memorable.cli import main

        main(
            [
                "remember",
                "decision",
                "--space",
                "memorable",
                "--id",
                V1_ID,
                "--statement",
                "Graphiti first.",
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:15:00Z",
            ]
        )
        main(
            [
                "remember",
                "decision",
                "--space",
                "memorable",
                "--id",
                V2_ID,
                "--statement",
                "Direct Neo4j first.",
                "--supersedes",
                V1_ID,
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:20:00Z",
            ]
        )

        exit_code = main(
            [
                "truth",
                "as-of",
                "--space",
                "memorable",
                "--id",
                V1_ID,
                "--at",
                "2026-05-23T10:17:00Z",
            ]
        )

        assert exit_code == 0
        output = capsys.readouterr().out
        assert V1_ID in output


@pytest.mark.usefixtures("cli_in_memory_context")
class TestCLIInspectHistory:
    """CLI `memorable inspect history` shows supersession chain."""

    def test_inspect_history_command(self, capsys) -> None:
        from memorable.cli import main

        main(
            [
                "remember",
                "decision",
                "--space",
                "memorable",
                "--id",
                V1_ID,
                "--statement",
                "Graphiti first.",
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:15:00Z",
            ]
        )
        main(
            [
                "remember",
                "decision",
                "--space",
                "memorable",
                "--id",
                V2_ID,
                "--statement",
                "Direct Neo4j first.",
                "--supersedes",
                V1_ID,
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:20:00Z",
            ]
        )

        exit_code = main(
            [
                "inspect",
                "history",
                "--space",
                "memorable",
                "--id",
                V1_ID,
            ]
        )

        assert exit_code == 0
        output = capsys.readouterr().out
        assert V1_ID in output
        assert V2_ID in output


# =====================================================================
# MCP adapter tests
# =====================================================================


class TestMCPRememberDecision:
    """MCP remember_decision_tool writes a Decision."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_remember_decision_tool(self) -> None:
        from memorable.mcp.server import remember_decision_tool

        result = remember_decision_tool(
            space="memorable",
            decision_id=V1_ID,
            statement=STATEMENT_V1,
            source=SOURCE_ID,
            at="2026-05-23T10:15:00Z",
        )

        assert result["decision_id"] == V1_ID
        assert result["source"] == SOURCE_ID
        assert "error" not in result

    def test_remember_decision_tool_includes_unified_provenance_fields(self) -> None:
        """MCP remember_decision_tool response includes record_id and record_kind."""
        from memorable.mcp.server import remember_decision_tool

        result = remember_decision_tool(
            space="memorable",
            decision_id=V1_ID,
            statement=STATEMENT_V1,
            source=SOURCE_ID,
            at="2026-05-23T10:15:00Z",
        )

        assert "error" not in result
        assert result["record_id"] == V1_ID
        assert result["record_kind"] == "decision"

    def test_remember_decision_with_supersession(self) -> None:
        from memorable.mcp.server import remember_decision_tool

        remember_decision_tool(
            space="memorable",
            decision_id=V1_ID,
            statement="Graphiti first.",
            source=SOURCE_ID,
            at="2026-05-23T10:15:00Z",
        )

        result = remember_decision_tool(
            space="memorable",
            decision_id=V2_ID,
            statement="Direct Neo4j first.",
            source=SOURCE_ID,
            at="2026-05-23T10:20:00Z",
            supersedes=V1_ID,
        )

        assert result["decision_id"] == V2_ID
        assert "error" not in result


class TestMCPCurrentTruth:
    """MCP current_truth_tool follows supersession chain."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_current_truth_tool(self) -> None:
        from memorable.mcp.server import (
            current_truth_tool,
            remember_decision_tool,
        )

        remember_decision_tool(
            space="memorable",
            decision_id=V1_ID,
            statement="Graphiti first.",
            source=SOURCE_ID,
            at="2026-05-23T10:15:00Z",
        )
        remember_decision_tool(
            space="memorable",
            decision_id=V2_ID,
            statement="Direct Neo4j first.",
            source=SOURCE_ID,
            at="2026-05-23T10:20:00Z",
            supersedes=V1_ID,
        )

        result = current_truth_tool(
            space="memorable",
            decision_id=V1_ID,
        )

        assert "error" not in result
        assert result["decision_id"] == V2_ID


class TestMCPPointInTimeTruth:
    """MCP point_in_time_truth_tool returns Decision at a time."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_point_in_time_truth_tool(self) -> None:
        from memorable.mcp.server import (
            point_in_time_truth_tool,
            remember_decision_tool,
        )

        remember_decision_tool(
            space="memorable",
            decision_id=V1_ID,
            statement="Graphiti first.",
            source=SOURCE_ID,
            at="2026-05-23T10:15:00Z",
        )
        remember_decision_tool(
            space="memorable",
            decision_id=V2_ID,
            statement="Direct Neo4j first.",
            source=SOURCE_ID,
            at="2026-05-23T10:20:00Z",
            supersedes=V1_ID,
        )

        result = point_in_time_truth_tool(
            space="memorable",
            decision_id=V1_ID,
            at="2026-05-23T10:17:00Z",
        )

        assert "error" not in result
        assert result["decision_id"] == V1_ID


class TestMCPInspectHistory:
    """MCP inspect_history_tool returns the chain for decisions."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_inspect_history_tool_for_decisions(self) -> None:
        from memorable.mcp.server import (
            inspect_history_tool,
            remember_decision_tool,
        )

        remember_decision_tool(
            space="memorable",
            decision_id=V1_ID,
            statement="Graphiti first.",
            source=SOURCE_ID,
            at="2026-05-23T10:15:00Z",
        )
        remember_decision_tool(
            space="memorable",
            decision_id=V2_ID,
            statement="Direct Neo4j first.",
            source=SOURCE_ID,
            at="2026-05-23T10:20:00Z",
            supersedes=V1_ID,
        )

        result = inspect_history_tool(
            space="memorable",
            record_id=V1_ID,
            record_type="decision",
        )

        assert "error" not in result
        assert len(result["history"]) == 2
        ids = [h["record_id"] for h in result["history"]]
        assert ids == [V1_ID, V2_ID]


# =====================================================================
# Thin repository / service-owned chain-walking tests (slice #30)
# =====================================================================


class TestDecisionRepositoryHasNoGetCurrent:
    """DecisionRepository protocol must not expose get_current (ADR 0009)."""

    def test_protocol_has_no_get_current(self) -> None:
        """get_current is not part of the DecisionRepository protocol."""
        from memorable.core.ports import DecisionRepository

        protocol_methods = {
            name for name in dir(DecisionRepository) if not name.startswith("_")
        }
        assert "get_current" not in protocol_methods

    def test_in_memory_repo_has_no_get_current(self) -> None:
        """InMemoryDecisionRepository does not implement get_current."""
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        assert not hasattr(repo, "get_current")


class TestCurrentTruthServiceOwnsChainWalking:
    """CurrentTruthService owns the supersession chain-walking logic.

    This replaces the former repo-level test_get_current_follows_supersession_chain.
    The service composes thin repo.get() calls to walk the chain.
    """

    def _setup_chain(self):
        from memorable.core.application import (
            CurrentTruthService,
            RememberDecisionService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberDecisionService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            decision_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )
        remember.remember(
            space="memorable",
            decision_id=V2_ID,
            statement=STATEMENT_V2,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V2,
            supersedes=V1_ID,
        )

        return CurrentTruthService(repository=repo), repo

    def test_service_follows_supersession_chain(self) -> None:
        """Service walks v1 -> v2 chain via repo.get() calls."""
        service, _repo = self._setup_chain()

        result = service.current(space="memorable", record_id=V1_ID)

        assert result is not None
        assert result.id == V2_ID
        assert result.lifecycle_state == "current"

    def test_service_returns_self_when_not_superseded(self) -> None:
        from memorable.core.application import (
            CurrentTruthService,
            RememberDecisionService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberDecisionService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            decision_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        service = CurrentTruthService(repository=repo)
        result = service.current(space="memorable", record_id=V1_ID)

        assert result is not None
        assert result.id == V1_ID

    def test_service_returns_none_for_missing(self) -> None:
        from memorable.core.application import CurrentTruthService
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        service = CurrentTruthService(repository=repo)

        result = service.current(space="memorable", record_id="decision:missing")
        assert result is None


# =====================================================================
# Thin repository / service-owned point-in-time projection tests (slice #32)
# =====================================================================


class TestDecisionRepositoryHasNoGetAt:
    """DecisionRepository protocol must not expose get_at (ADR 0009)."""

    def test_protocol_has_no_get_at(self) -> None:
        """get_at is not part of the DecisionRepository protocol."""
        from memorable.core.ports import DecisionRepository

        protocol_methods = {
            name for name in dir(DecisionRepository) if not name.startswith("_")
        }
        assert "get_at" not in protocol_methods

    def test_in_memory_repo_has_no_get_at(self) -> None:
        """InMemoryDecisionRepository does not implement get_at."""
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        assert not hasattr(repo, "get_at")


class TestPointInTimeTruthServiceOwnsProjection:
    """PointInTimeTruthService owns the point-in-time temporal projection logic.

    This replaces the former repo-level test_get_at_returns_decision_valid_at_time.
    The service composes thin repo.get() calls to walk the chain and check
    invalidation_time against the query timestamp.
    """

    def _setup_chain(self):
        from memorable.core.application import (
            PointInTimeTruthService,
            RememberDecisionService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberDecisionService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            decision_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )
        remember.remember(
            space="memorable",
            decision_id=V2_ID,
            statement=STATEMENT_V2,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V2,
            supersedes=V1_ID,
        )

        return PointInTimeTruthService(repository=repo), repo

    def test_service_walks_chain_correctly(self) -> None:
        """Query at 10:17 returns v1; query at 10:21 returns v2."""
        service, _repo = self._setup_chain()

        at_1017 = datetime(2026, 5, 23, 10, 17, 0, tzinfo=UTC)
        result_v1 = service.at(space="memorable", record_id=V1_ID, at=at_1017)

        assert result_v1 is not None
        assert result_v1.id == V1_ID

        at_1021 = datetime(2026, 5, 23, 10, 21, 0, tzinfo=UTC)
        result_v2 = service.at(space="memorable", record_id=V1_ID, at=at_1021)

        assert result_v2 is not None
        assert result_v2.id == V2_ID

    def test_service_returns_self_when_not_superseded(self) -> None:
        from memorable.core.application import (
            PointInTimeTruthService,
            RememberDecisionService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberDecisionService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            decision_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        service = PointInTimeTruthService(repository=repo)
        at_1017 = datetime(2026, 5, 23, 10, 17, 0, tzinfo=UTC)
        result = service.at(space="memorable", record_id=V1_ID, at=at_1017)

        assert result is not None
        assert result.id == V1_ID

    def test_service_returns_none_for_missing(self) -> None:
        from memorable.core.application import PointInTimeTruthService
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        service = PointInTimeTruthService(repository=repo)

        result = service.at(
            space="memorable",
            record_id="decision:missing",
            at=FIXTURE_TIMESTAMP_V1,
        )
        assert result is None


# =====================================================================
# Thin repository / service-owned decision history tests (slice #33)
# =====================================================================


class TestDecisionRepositoryHasNoGetHistory:
    """DecisionRepository protocol must not expose get_history (ADR 0009)."""

    def test_protocol_has_no_get_history(self) -> None:
        """get_history is not part of the DecisionRepository protocol."""
        from memorable.core.ports import DecisionRepository

        protocol_methods = {
            name for name in dir(DecisionRepository) if not name.startswith("_")
        }
        assert "get_history" not in protocol_methods

    def test_in_memory_repo_has_no_get_history(self) -> None:
        """InMemoryDecisionRepository does not implement get_history."""
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        assert not hasattr(repo, "get_history")


class TestInspectHistoryServiceOwnsChainTraversal:
    """InspectHistoryService owns the supersession chain traversal logic.

    This replaces the former repo-level test_get_history_returns_supersession_chain.
    The service composes thin repo.get() calls to walk the chain following
    superseded_by links.
    """

    def _setup_chain(self):
        from memorable.core.application import (
            InspectHistoryService,
            RememberDecisionService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberDecisionService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            decision_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )
        remember.remember(
            space="memorable",
            decision_id=V2_ID,
            statement=STATEMENT_V2,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V2,
            supersedes=V1_ID,
        )

        return InspectHistoryService(repository=repo), repo

    def test_service_walks_supersession_chain(self) -> None:
        """Service walks v1 -> v2 chain via repo.get() calls."""
        service, _repo = self._setup_chain()

        history = service.history(space="memorable", record_id=V1_ID)

        assert len(history) == 2
        assert history[0].id == V1_ID
        assert history[1].id == V2_ID

    def test_service_returns_single_when_not_superseded(self) -> None:
        from memorable.core.application import (
            InspectHistoryService,
            RememberDecisionService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberDecisionService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            decision_id=V1_ID,
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        service = InspectHistoryService(repository=repo)
        history = service.history(space="memorable", record_id=V1_ID)

        assert len(history) == 1
        assert history[0].id == V1_ID

    def test_service_returns_empty_for_missing(self) -> None:
        from memorable.core.application import InspectHistoryService
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
        service = InspectHistoryService(repository=repo)

        history = service.history(space="memorable", record_id="decision:missing")
        assert history == []


# =====================================================================
# Cycle protection tests
# =====================================================================


class TestChainWalkingCycleProtection:
    """Chain-walking services must terminate even with corrupted cyclic data.

    If data corruption creates a cycle (v1.superseded_by -> v2, v2.superseded_by -> v1),
    the services must not loop forever.
    """

    def _make_cyclic_repo(self):
        """Create a repo with a circular supersession chain: v1 -> v2 -> v1."""
        from memorable.core.models import Decision
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()

        v1 = Decision(
            id=V1_ID,
            statement=STATEMENT_V1,
            space="memorable",
            validity_time=FIXTURE_TIMESTAMP_V1,
            invalidation_time=FIXTURE_TIMESTAMP_V2,
            lifecycle_state="superseded",
            supersedes=None,
            superseded_by=V2_ID,
        )
        v2 = Decision(
            id=V2_ID,
            statement=STATEMENT_V2,
            space="memorable",
            validity_time=FIXTURE_TIMESTAMP_V2,
            invalidation_time=FIXTURE_TIMESTAMP_V1,
            lifecycle_state="superseded",
            supersedes=V1_ID,
            superseded_by=V1_ID,  # Corrupt: cycle back to v1
        )

        from memorable.core.models import Provenance

        prov1 = Provenance(
            record_id=V1_ID,
            record_kind="decision",
            source_id=SOURCE_ID,
            episode_id=EPISODE_V1,
            writer="agent:test",
            reason="cycle test",
            creation_time=FIXTURE_TIMESTAMP_V1,
            validity_time=FIXTURE_TIMESTAMP_V1,
        )
        prov2 = Provenance(
            record_id=V2_ID,
            record_kind="decision",
            source_id=SOURCE_ID,
            episode_id=EPISODE_V2,
            writer="agent:test",
            reason="cycle test",
            creation_time=FIXTURE_TIMESTAMP_V2,
            validity_time=FIXTURE_TIMESTAMP_V2,
        )

        repo.save(v1, prov1)
        repo.save(v2, prov2)

        return repo

    def test_current_truth_terminates_on_cycle(self) -> None:
        """CurrentTruthService.current() must not hang on a cyclic chain."""
        from memorable.core.application import CurrentTruthService

        repo = self._make_cyclic_repo()
        service = CurrentTruthService(repository=repo)

        result = service.current(space="memorable", record_id=V1_ID)

        # Must return a decision (not hang forever)
        assert result is not None
        assert result.id in {V1_ID, V2_ID}

    def test_point_in_time_terminates_on_cycle(self) -> None:
        """PointInTimeTruthService.at() must not hang on a cyclic chain."""
        from memorable.core.application import PointInTimeTruthService

        repo = self._make_cyclic_repo()
        service = PointInTimeTruthService(repository=repo)

        at_query = datetime(2026, 5, 23, 10, 25, 0, tzinfo=UTC)
        result = service.at(space="memorable", record_id=V1_ID, at=at_query)

        # Must return a decision (not hang forever)
        assert result is not None
        assert result.id in {V1_ID, V2_ID}

    def test_history_terminates_on_cycle(self) -> None:
        """InspectHistoryService.history() must not hang on a cyclic chain."""
        from memorable.core.application import InspectHistoryService

        repo = self._make_cyclic_repo()
        service = InspectHistoryService(repository=repo)

        history = service.history(space="memorable", record_id=V1_ID)

        # Must return a finite list (not hang forever)
        assert isinstance(history, list)
        assert len(history) <= 2  # Only v1 and v2 exist
        assert len(history) >= 1  # At least the starting decision


# =====================================================================
# Language boundary test
# =====================================================================


class TestLanguageBoundary:
    """Outputs use domain language, not storage vocabulary."""

    def test_no_storage_vocabulary_in_error_messages(self) -> None:
        """Error messages must not leak storage terms."""
        from memorable.core.application import (
            RememberDecisionService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryDecisionRepository,
        )

        no_decision_yaml = textwrap.dedent("""\
            version: 1
            space:
              name: memorable
              description: test
            entities:
              - name: Project
            records: []
        """)
        repo = InMemoryDecisionRepository()
        profile = load_profile_from_yaml(no_decision_yaml)
        service = RememberDecisionService(repository=repo, profile=profile)

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
                decision_id="decision:x",
                statement="X",
                source_id="source:test",
                at=FIXTURE_TIMESTAMP_V1,
            )
        message_lower = str(exc_info.value).lower()
        for term in storage_terms:
            assert term not in message_lower, (
                f"Storage vocabulary '{term}' found in error: {exc_info.value}"
            )
