"""Tests for the tracer-bullet runnable flow (#11).

Proves the accepted architecture composes end to end:
- TracerService runs the fixed fixture with fixed timestamps
- CLI `tracer run` and MCP `tracer_run_tool` exercise the same core behavior
- Output covers current truth, point-in-time truth, task lifecycle,
  provenance inspection, and hybrid GraphRAG retrieval
- No storage vocabulary leaks into agent-facing output
"""

from __future__ import annotations

import json

# =====================================================================
# 1. TracerService core behavior
# =====================================================================


class TestTracerServiceStructuredResults:
    """TracerService.run() returns a result dict with all 7 verification sections."""

    def test_tracer_run_returns_structured_results(self) -> None:
        from memorable.core.tracer import TracerService

        service = TracerService()
        result = service.run()

        expected_sections = [
            "current_truth",
            "point_in_time_before",
            "point_in_time_after",
            "task_before_completion",
            "task_after_completion",
            "provenance",
            "hybrid_retrieval",
        ]
        for section in expected_sections:
            assert section in result, f"Missing section: {section}"


class TestTracerCurrentTruth:
    """Current truth after supersession shows decision:storage-path:v2."""

    def test_tracer_current_truth_after_supersession(self) -> None:
        from memorable.core.tracer import TracerService

        result = TracerService().run()
        ct = result["current_truth"]

        assert ct["decision_id"] == "decision:storage-path:v2"
        assert ct["lifecycle_state"] == "current"
        assert "Direct Neo4j is the first implementation path" in ct["statement"]


class TestTracerPointInTimeTruth:
    """Point-in-time truth before and after supersession."""

    def test_tracer_point_in_time_before_supersession(self) -> None:
        from memorable.core.tracer import TracerService

        result = TracerService().run()
        pit_before = result["point_in_time_before"]

        assert pit_before["decision_id"] == "decision:storage-path:v1"
        assert "Graphiti is the first implementation path" in pit_before["statement"]

    def test_tracer_point_in_time_after_supersession(self) -> None:
        from memorable.core.tracer import TracerService

        result = TracerService().run()
        pit_after = result["point_in_time_after"]

        assert pit_after["decision_id"] == "decision:storage-path:v2"


class TestTracerTaskLifecycle:
    """Task status before and after completion."""

    def test_tracer_task_status_before_completion(self) -> None:
        from memorable.core.tracer import TracerService

        result = TracerService().run()
        task_before = result["task_before_completion"]

        assert task_before["task_id"] == "task:mcp-smoke-path"
        assert task_before["lifecycle_state"] == "open"

    def test_tracer_task_status_after_completion(self) -> None:
        from memorable.core.tracer import TracerService

        result = TracerService().run()
        task_after = result["task_after_completion"]

        assert task_after["task_id"] == "task:mcp-smoke-path"
        assert task_after["lifecycle_state"] == "completed"
        assert task_after["completion_event_id"] == "event:complete-task:mcp-smoke-path"


class TestTracerProvenance:
    """Provenance inspection for decision:storage-path:v2."""

    def test_tracer_provenance_inspection(self) -> None:
        from memorable.core.tracer import TracerService

        result = TracerService().run()
        prov = result["provenance"]

        assert prov["source_id"] == "source:tracer-fixture"
        assert prov["writer"] == "agent:tracer-fixture"

    def test_tracer_decision_provenance_has_reason(self) -> None:
        from memorable.core.tracer import TracerService

        result = TracerService().run()
        prov = result["provenance"]

        assert "reason" in prov
        assert isinstance(prov["reason"], str)
        assert len(prov["reason"]) > 0

    def test_tracer_provenance_returns_record_id_and_record_kind(self) -> None:
        """_verify_provenance output includes unified record_id and record_kind."""
        from memorable.core.tracer import TracerService

        result = TracerService().run()
        prov = result["provenance"]

        assert prov["record_id"] == "decision:storage-path:v2"
        assert prov["record_kind"] == "decision"


class TestTracerHybridRetrieval:
    """Hybrid GraphRAG search returns v2 with full explanation."""

    def test_tracer_hybrid_retrieval(self) -> None:
        from memorable.core.tracer import TracerService

        result = TracerService().run()
        hr = result["hybrid_retrieval"]

        # Must return decision:storage-path:v2
        assert hr["top_result"]["source_id"] == "decision:storage-path:v2"

        explanation = hr["top_result"]["explanation"]
        explanation_text = " ".join(explanation).lower()

        # Explanation must mention all these aspects
        assert "semantic" in explanation_text
        assert "graph" in explanation_text
        assert "temporal" in explanation_text
        assert "provenance" in explanation_text
        assert "supersession" in explanation_text or "supersed" in explanation_text


# =====================================================================
# 2. CLI adapter
# =====================================================================


class TestTracerCLI:
    """CLI `memorable tracer run` outputs valid JSON with all verifications."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_tracer_cli_command(self, capsys) -> None:
        from memorable.cli import main

        exit_code = main(["tracer", "run"])

        assert exit_code == 0

        output = capsys.readouterr().out
        parsed = json.loads(output)

        expected_sections = [
            "current_truth",
            "point_in_time_before",
            "point_in_time_after",
            "task_before_completion",
            "task_after_completion",
            "provenance",
            "hybrid_retrieval",
        ]
        for section in expected_sections:
            assert section in parsed, f"CLI output missing section: {section}"

    def test_tracer_cli_provenance_has_unified_fields(self, capsys) -> None:
        """CLI tracer output provenance section includes record_id and record_kind."""
        from memorable.cli import main

        main(["tracer", "run"])
        parsed = json.loads(capsys.readouterr().out)
        prov = parsed["provenance"]

        assert prov["record_id"] == "decision:storage-path:v2"
        assert prov["record_kind"] == "decision"


# =====================================================================
# 3. MCP adapter
# =====================================================================


class TestTracerMCP:
    """MCP tracer_run_tool returns same structured result."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_tracer_mcp_tool(self) -> None:
        from memorable.mcp.server import tracer_run_tool

        result = tracer_run_tool()

        expected_sections = [
            "current_truth",
            "point_in_time_before",
            "point_in_time_after",
            "task_before_completion",
            "task_after_completion",
            "provenance",
            "hybrid_retrieval",
        ]
        for section in expected_sections:
            assert section in result, f"MCP output missing section: {section}"

    def test_tracer_mcp_provenance_has_unified_fields(self) -> None:
        """MCP tracer output provenance section includes record_id and record_kind."""
        from memorable.mcp.server import tracer_run_tool

        result = tracer_run_tool()
        prov = result["provenance"]

        assert prov["record_id"] == "decision:storage-path:v2"
        assert prov["record_kind"] == "decision"


# =====================================================================
# 4. CLI and MCP share core behavior
# =====================================================================


class TestTracerSharedBehavior:
    """Both CLI and MCP use TracerService."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_tracer_cli_and_mcp_share_core_behavior(self, capsys) -> None:
        from memorable.cli import main
        from memorable.mcp.server import tracer_run_tool

        # Run CLI
        exit_code = main(["tracer", "run"])
        assert exit_code == 0
        cli_output = json.loads(capsys.readouterr().out)

        # Reset and run MCP
        from memorable.core.context import default_context

        default_context.reset()
        mcp_output = tracer_run_tool()

        # Both should have the same sections with the same data
        assert (
            cli_output["current_truth"]["decision_id"]
            == mcp_output["current_truth"]["decision_id"]
        )
        assert (
            cli_output["provenance"]["source_id"]
            == mcp_output["provenance"]["source_id"]
        )


# =====================================================================
# 5. Language boundary
# =====================================================================


class TestTracerLanguageBoundary:
    """No storage vocabulary in tracer output."""

    def test_tracer_output_no_storage_vocabulary(self) -> None:
        from memorable.core.tracer import TracerService

        result = TracerService().run()

        storage_terms = {"node", "edge", "vertex", "database", "table", "row", "column"}

        result_text = json.dumps(result).lower()
        for term in storage_terms:
            assert term not in result_text, (
                f"Storage vocabulary '{term}' found in tracer output"
            )
