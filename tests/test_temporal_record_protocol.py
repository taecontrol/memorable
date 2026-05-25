"""Tests for the TemporalRecordRepository protocol.

Verifies that the protocol captures the shared surface needed by temporal
services (CurrentTruth, PointInTimeTruth, InspectHistory), and that
existing repositories satisfy it structurally.
"""

from __future__ import annotations

from typing import runtime_checkable

from memorable.core.ports import TemporalRecordRepository
from memorable.core.repositories import InMemoryDecisionRepository

# --- Fake repository for testing generic temporal services ---


class FakeTemporalRecord:
    """Minimal object satisfying the TemporalRecord protocol."""

    def __init__(
        self,
        *,
        id: str,
        space: str,
        statement: str = "",
        validity_time: object | None = None,
        supersedes: str | None = None,
        superseded_by: str | None = None,
        invalidation_time: object | None = None,
        lifecycle_state: str = "current",
    ) -> None:
        self.id = id
        self.space = space
        self.statement = statement
        self.validity_time = validity_time
        self.supersedes = supersedes
        self.superseded_by = superseded_by
        self.invalidation_time = invalidation_time
        self.lifecycle_state = lifecycle_state


class FakeTemporalRecordRepository:
    """A non-Decision repository that satisfies TemporalRecordRepository."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], FakeTemporalRecord] = {}

    def get(self, space: str, record_id: str) -> FakeTemporalRecord | None:
        return self._records.get((space, record_id))

    def mark_superseded(
        self,
        space: str,
        record_id: str,
        superseded_by: str,
        invalidation_time: object,
    ) -> None:
        key = (space, record_id)
        old = self._records.get(key)
        if old is None:
            return
        old.lifecycle_state = "superseded"
        old.superseded_by = superseded_by
        old.invalidation_time = invalidation_time

    def put(self, record: FakeTemporalRecord) -> None:
        """Helper to seed test data."""
        self._records[(record.space, record.id)] = record


class TestTemporalRecordRepositoryProtocol:
    """TemporalRecordRepository captures the shared temporal repository surface."""

    def test_protocol_defines_get(self) -> None:
        """Protocol declares a get() method."""
        protocol_methods = {
            name for name in dir(TemporalRecordRepository) if not name.startswith("_")
        }
        assert "get" in protocol_methods

    def test_protocol_defines_mark_superseded(self) -> None:
        """Protocol declares a mark_superseded() method."""
        protocol_methods = {
            name for name in dir(TemporalRecordRepository) if not name.startswith("_")
        }
        assert "mark_superseded" in protocol_methods

    def test_protocol_is_runtime_checkable(self) -> None:
        """Protocol can be checked at runtime for structural conformance."""
        assert runtime_checkable  # import guard
        assert isinstance(InMemoryDecisionRepository(), TemporalRecordRepository)

    def test_in_memory_decision_repo_satisfies_protocol(self) -> None:
        """InMemoryDecisionRepository structurally satisfies the protocol."""
        repo = InMemoryDecisionRepository()
        # Must have both required methods
        assert hasattr(repo, "get")
        assert hasattr(repo, "mark_superseded")
        assert callable(repo.get)
        assert callable(repo.mark_superseded)

    def test_fake_repo_satisfies_protocol(self) -> None:
        """FakeTemporalRecordRepository satisfies the protocol at runtime."""
        repo = FakeTemporalRecordRepository()
        assert isinstance(repo, TemporalRecordRepository)


class TestCurrentTruthServiceGeneric:
    """CurrentTruthService works with any TemporalRecordRepository."""

    def test_current_truth_with_non_decision_repo(self) -> None:
        """CurrentTruthService follows supersession on a non-Decision repository."""
        from memorable.core.application import CurrentTruthService

        repo = FakeTemporalRecordRepository()
        repo.put(FakeTemporalRecord(
            id="r1", space="s",
            superseded_by="r2", lifecycle_state="superseded",
        ))
        repo.put(FakeTemporalRecord(
            id="r2", space="s", lifecycle_state="current",
        ))

        service = CurrentTruthService(repository=repo)
        result = service.current(space="s", record_id="r1")

        assert result is not None
        assert result.id == "r2"

    def test_current_truth_returns_none_for_missing(self) -> None:
        from memorable.core.application import CurrentTruthService

        repo = FakeTemporalRecordRepository()
        service = CurrentTruthService(repository=repo)

        result = service.current(space="s", record_id="missing")
        assert result is None


class TestPointInTimeTruthServiceGeneric:
    """PointInTimeTruthService works with any TemporalRecordRepository."""

    def test_point_in_time_with_non_decision_repo(self) -> None:
        """PointInTimeTruthService walks chain on a non-Decision repository."""
        from datetime import UTC, datetime

        from memorable.core.application import PointInTimeTruthService

        t2 = datetime(2026, 1, 1, 10, 5, tzinfo=UTC)

        repo = FakeTemporalRecordRepository()
        repo.put(FakeTemporalRecord(
            id="r1", space="s", superseded_by="r2",
            invalidation_time=t2, lifecycle_state="superseded",
        ))
        repo.put(FakeTemporalRecord(
            id="r2", space="s", lifecycle_state="current",
        ))

        service = PointInTimeTruthService(repository=repo)

        # Before supersession: returns r1
        at_before = datetime(2026, 1, 1, 10, 3, tzinfo=UTC)
        result = service.at(space="s", record_id="r1", at=at_before)
        assert result is not None
        assert result.id == "r1"

        # After supersession: returns r2
        at_after = datetime(2026, 1, 1, 10, 6, tzinfo=UTC)
        result = service.at(space="s", record_id="r1", at=at_after)
        assert result is not None
        assert result.id == "r2"

    def test_point_in_time_returns_none_for_missing(self) -> None:
        from datetime import UTC, datetime

        from memorable.core.application import PointInTimeTruthService

        repo = FakeTemporalRecordRepository()
        service = PointInTimeTruthService(repository=repo)

        result = service.at(
            space="s", record_id="missing",
            at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert result is None


class TestInspectHistoryServiceGeneric:
    """InspectHistoryService works with any TemporalRecordRepository."""

    def test_inspect_history_service_exists(self) -> None:
        """InspectHistoryService is importable from application module."""
        from memorable.core.application import InspectHistoryService

        repo = FakeTemporalRecordRepository()
        service = InspectHistoryService(repository=repo)
        assert service is not None

    def test_inspect_history_with_non_decision_repo(self) -> None:
        """InspectHistoryService walks chain on a non-Decision repository."""
        from memorable.core.application import InspectHistoryService

        repo = FakeTemporalRecordRepository()
        repo.put(FakeTemporalRecord(
            id="r1", space="s",
            superseded_by="r2", lifecycle_state="superseded",
        ))
        repo.put(FakeTemporalRecord(
            id="r2", space="s", lifecycle_state="current",
        ))

        service = InspectHistoryService(repository=repo)
        history = service.history(space="s", record_id="r1")

        assert len(history) == 2
        assert history[0].id == "r1"
        assert history[1].id == "r2"

    def test_inspect_history_returns_empty_for_missing(self) -> None:
        from memorable.core.application import InspectHistoryService

        repo = FakeTemporalRecordRepository()
        service = InspectHistoryService(repository=repo)

        history = service.history(space="s", record_id="missing")
        assert history == []

    def test_backward_compat_alias_exists(self) -> None:
        """InspectDecisionHistoryService still importable as backward-compat alias."""
        from memorable.core.application import InspectDecisionHistoryService

        repo = FakeTemporalRecordRepository()
        service = InspectDecisionHistoryService(repository=repo)
        assert service is not None


class TestMCPInspectHistoryTool:
    """MCP tool memorable_inspect_history replaces the old tool."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_inspect_history_tool_exists(self) -> None:
        """inspect_history_tool is importable from mcp.server."""
        from memorable.mcp.server import inspect_history_tool

        assert callable(inspect_history_tool)

    def test_inspect_history_tool_accepts_record_type(self) -> None:
        """Tool accepts record_type parameter to select repository."""
        from memorable.mcp.server import (
            inspect_history_tool,
            remember_decision_tool,
        )

        remember_decision_tool(
            space="memorable",
            decision_id="decision:test:v1",
            statement="First version.",
            source="source:test",
            at="2026-05-23T10:15:00Z",
        )
        remember_decision_tool(
            space="memorable",
            decision_id="decision:test:v2",
            statement="Second version.",
            source="source:test",
            at="2026-05-23T10:20:00Z",
            supersedes="decision:test:v1",
        )

        result = inspect_history_tool(
            space="memorable",
            record_id="decision:test:v1",
            record_type="decision",
        )

        assert "error" not in result
        assert len(result["history"]) == 2

    def test_inspect_history_tool_unknown_record_type(self) -> None:
        """Tool returns error for unknown record_type."""
        from memorable.mcp.server import inspect_history_tool

        result = inspect_history_tool(
            space="memorable",
            record_id="something:v1",
            record_type="unknown",
        )

        assert "error" in result
