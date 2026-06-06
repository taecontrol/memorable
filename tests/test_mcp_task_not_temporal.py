"""Regression: task is not a generic temporal record kind (PR #142).

TaskRepository does not satisfy TemporalRecordRepository — its get() is
keyword-only and it lacks mark_superseded/invalidate/correct. Task was
wrongly added to the shared `_resolve_repository` dispatch, which made the
generic temporal MCP tools (current_truth, point_in_time, inspect_history,
invalidate) crash with a TypeError on record_kind="task".

These tools must now return the clean unknown-kind error dict for "task",
never raise. (correct_tool is intentionally excluded: it special-cases
record_type == "task" before dispatch and routes to CorrectTaskService.)
"""

from __future__ import annotations

from memorable.core.context import ApplicationContext, default_context
from memorable.mcp.server import (
    current_truth_tool,
    inspect_history_tool,
    invalidate_tool,
    point_in_time_truth_tool,
    set_mcp_context,
)


class TestTaskRejectedByGenericTemporalTools:
    def setup_method(self) -> None:
        self.ctx = ApplicationContext()
        set_mcp_context(self.ctx)

    def teardown_method(self) -> None:
        set_mcp_context(default_context)

    def test_current_truth_returns_error_dict_for_task(self) -> None:
        result = current_truth_tool(
            space="space:1",
            record_id="task:1",
            record_kind="task",
        )
        assert isinstance(result, dict)
        assert "error" in result

    def test_point_in_time_returns_error_dict_for_task(self) -> None:
        result = point_in_time_truth_tool(
            space="space:1",
            record_id="task:1",
            at="2026-01-01T00:00:00Z",
            record_kind="task",
        )
        assert isinstance(result, dict)
        assert "error" in result

    def test_inspect_history_returns_error_dict_for_task(self) -> None:
        result = inspect_history_tool(
            space="space:1",
            record_id="task:1",
            record_kind="task",
        )
        assert isinstance(result, dict)
        assert "error" in result

    def test_invalidate_returns_error_dict_for_task(self) -> None:
        result = invalidate_tool(
            space="space:1",
            record_id="task:1",
            record_kind="task",
            at="2026-01-01T00:00:00Z",
        )
        assert isinstance(result, dict)
        assert "error" in result
