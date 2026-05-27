"""Tests for centralized record_type → repository dispatch helper (issue #54).

Verifies:
- Returns DecisionRepository for record_type "decision"
- Returns ObservationRepository for record_type "observation"
- Returns a structured error dict for unknown record_type values
- Error dict shape matches the established convention
"""

from __future__ import annotations

from memorable.core.context import ApplicationContext
from memorable.core.ports import TemporalRecordRepository
from memorable.mcp.server import _resolve_repository, set_mcp_context


class TestResolveRepositoryHappyPath:
    def setup_method(self) -> None:
        self.ctx = ApplicationContext()
        set_mcp_context(self.ctx)

    def test_returns_decision_repo_for_decision(self) -> None:
        result = _resolve_repository("decision")
        assert result is self.ctx.decision_repo

    def test_returns_observation_repo_for_observation(self) -> None:
        result = _resolve_repository("observation")
        assert result is self.ctx.observation_repo

    def test_decision_repo_satisfies_temporal_record_repository(self) -> None:
        result = _resolve_repository("decision")
        assert isinstance(result, TemporalRecordRepository)

    def test_observation_repo_satisfies_temporal_record_repository(self) -> None:
        result = _resolve_repository("observation")
        assert isinstance(result, TemporalRecordRepository)

    def test_returns_relation_repo_for_relation(self) -> None:
        result = _resolve_repository("relation")
        assert result is self.ctx.relation_repo

    def test_relation_repo_satisfies_temporal_record_repository(self) -> None:
        result = _resolve_repository("relation")
        assert isinstance(result, TemporalRecordRepository)


class TestResolveRepositoryErrorPath:
    def setup_method(self) -> None:
        self.ctx = ApplicationContext()
        set_mcp_context(self.ctx)

    def test_unknown_type_returns_error_dict(self) -> None:
        result = _resolve_repository("unknown")
        assert isinstance(result, dict)
        assert "error" in result

    def test_error_message_includes_unknown_type_name(self) -> None:
        result = _resolve_repository("bogus_type")
        assert "bogus_type" in result["error"]

    def test_error_message_lists_supported_types(self) -> None:
        result = _resolve_repository("invalid")
        assert "decision" in result["error"]
        assert "observation" in result["error"]

    def test_error_dict_shape_matches_convention(self) -> None:
        """The error dict must match the exact shape used by tools today."""
        result = _resolve_repository("nope")
        expected = {
            "error": "Unknown record_type 'nope'. "
            "Supported types: decision, observation, relation."
        }
        assert result == expected

    def test_empty_string_returns_error(self) -> None:
        result = _resolve_repository("")
        assert isinstance(result, dict)
        assert "error" in result

    def test_none_like_string_returns_error(self) -> None:
        result = _resolve_repository("None")
        assert isinstance(result, dict)
        assert "error" in result
