"""Tests for record_type parameter on current_truth and point_in_time_truth MCP tools.

Covers slice #52 acceptance criteria:
- memorable_current_truth accepts optional record_type (default: "decision")
- memorable_point_in_time_truth accepts optional record_type (default: "decision")
- Both dispatch to observation_repo when record_type == "observation"
- Both return error dict for unknown record_type values
- Existing decision-only calls still work unchanged (backward compat)
- Tool count remains 16
"""

from __future__ import annotations

# --- Fixture data ---

OBSERVATION_V1_ID = "observation:team-comm:v1"
OBSERVATION_V2_ID = "observation:team-comm:v2"
DECISION_ID = "decision:storage-path:v1"
SOURCE_ID = "source:agent-session"

OBSERVATION_STATEMENT_V1 = "The team prefers async communication."
OBSERVATION_STATEMENT_V2 = (
    "The team prefers async communication but holds weekly sync standups."
)
DECISION_STATEMENT = "Use Graphiti for storage."


# =====================================================================
# current_truth_tool + record_type
# =====================================================================


class TestCurrentTruthWithRecordType:
    """current_truth_tool dispatches by record_type."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_current_truth_observation(self) -> None:
        """current_truth_tool returns observation when record_type is observation."""
        from memorable.mcp.server import current_truth_tool, remember_observation_tool

        remember_observation_tool(
            space="memorable",
            observation_id=OBSERVATION_V1_ID,
            statement=OBSERVATION_STATEMENT_V1,
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )

        result = current_truth_tool(
            space="memorable",
            record_id=OBSERVATION_V1_ID,
            record_type="observation",
        )

        assert "error" not in result
        assert result["record_id"] == OBSERVATION_V1_ID
        assert result["statement"] == OBSERVATION_STATEMENT_V1
        assert result["lifecycle_state"] == "current"

    def test_current_truth_defaults_to_decision(self) -> None:
        """Omitting record_type defaults to decision (backward compat)."""
        from memorable.mcp.server import current_truth_tool, remember_decision_tool

        remember_decision_tool(
            space="memorable",
            decision_id=DECISION_ID,
            statement=DECISION_STATEMENT,
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )

        result = current_truth_tool(
            space="memorable",
            record_id=DECISION_ID,
        )

        assert "error" not in result
        assert result["record_id"] == DECISION_ID
        assert result["statement"] == DECISION_STATEMENT

    def test_current_truth_unknown_record_type(self) -> None:
        """Unknown record_type returns an error dict."""
        from memorable.mcp.server import current_truth_tool

        result = current_truth_tool(
            space="memorable",
            record_id="anything",
            record_type="unknown",
        )

        assert "error" in result
        assert "Unknown record_type" in result["error"]
        assert "unknown" in result["error"]

    def test_current_truth_observation_follows_supersession(self) -> None:
        """current_truth follows supersession chain for observations."""
        from memorable.mcp.server import current_truth_tool, remember_observation_tool

        remember_observation_tool(
            space="memorable",
            observation_id=OBSERVATION_V1_ID,
            statement=OBSERVATION_STATEMENT_V1,
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )
        remember_observation_tool(
            space="memorable",
            observation_id=OBSERVATION_V2_ID,
            statement=OBSERVATION_STATEMENT_V2,
            source=SOURCE_ID,
            at="2026-05-25T09:10:00Z",
            supersedes=OBSERVATION_V1_ID,
        )

        result = current_truth_tool(
            space="memorable",
            record_id=OBSERVATION_V1_ID,
            record_type="observation",
        )

        assert "error" not in result
        assert result["record_id"] == OBSERVATION_V2_ID
        assert result["statement"] == OBSERVATION_STATEMENT_V2


# =====================================================================
# point_in_time_truth_tool + record_type
# =====================================================================


class TestPointInTimeTruthWithRecordType:
    """point_in_time_truth_tool dispatches by record_type."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_point_in_time_truth_observation(self) -> None:
        """Returns observation valid at a specific time."""
        from memorable.mcp.server import (
            point_in_time_truth_tool,
            remember_observation_tool,
        )

        remember_observation_tool(
            space="memorable",
            observation_id=OBSERVATION_V1_ID,
            statement=OBSERVATION_STATEMENT_V1,
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )
        remember_observation_tool(
            space="memorable",
            observation_id=OBSERVATION_V2_ID,
            statement=OBSERVATION_STATEMENT_V2,
            source=SOURCE_ID,
            at="2026-05-25T09:10:00Z",
            supersedes=OBSERVATION_V1_ID,
        )

        # Query before supersession -- should return v1
        result = point_in_time_truth_tool(
            space="memorable",
            record_id=OBSERVATION_V1_ID,
            at="2026-05-25T09:05:00Z",
            record_type="observation",
        )

        assert "error" not in result
        assert result["record_id"] == OBSERVATION_V1_ID
        assert result["statement"] == OBSERVATION_STATEMENT_V1

    def test_point_in_time_truth_defaults_to_decision(self) -> None:
        """Omitting record_type defaults to decision (backward compat)."""
        from memorable.mcp.server import (
            point_in_time_truth_tool,
            remember_decision_tool,
        )

        remember_decision_tool(
            space="memorable",
            decision_id=DECISION_ID,
            statement=DECISION_STATEMENT,
            source=SOURCE_ID,
            at="2026-05-25T09:00:00Z",
        )

        result = point_in_time_truth_tool(
            space="memorable",
            record_id=DECISION_ID,
            at="2026-05-25T09:05:00Z",
        )

        assert "error" not in result
        assert result["record_id"] == DECISION_ID
        assert result["statement"] == DECISION_STATEMENT

    def test_point_in_time_truth_unknown_record_type(self) -> None:
        """Unknown record_type returns an error dict."""
        from memorable.mcp.server import point_in_time_truth_tool

        result = point_in_time_truth_tool(
            space="memorable",
            record_id="anything",
            at="2026-05-25T09:00:00Z",
            record_type="unknown",
        )

        assert "error" in result
        assert "Unknown record_type" in result["error"]

    def test_point_in_time_truth_observation_not_found(self) -> None:
        """Returns error when observation does not exist."""
        from memorable.mcp.server import point_in_time_truth_tool

        result = point_in_time_truth_tool(
            space="memorable",
            record_id="observation:missing",
            at="2026-05-25T09:00:00Z",
            record_type="observation",
        )

        assert "error" in result
        assert "No Observation found" in result["error"]
        assert "MemorySpace" in result["error"]
