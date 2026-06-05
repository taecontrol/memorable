"""Tracer-bullet runnable flow.

Runs the fixed fixture from the tracer-bullet contract (#1) with fixed
timestamps and returns structured verification results proving the
architecture composes end to end.
"""

from __future__ import annotations

from datetime import UTC, datetime

from memorable.core.application import (
    CompleteTaskService,
    CurrentTruthService,
    InspectTaskService,
    PointInTimeTruthService,
    RememberDecisionService,
    RememberEntityService,
    RememberTaskService,
)
from memorable.core.context import ApplicationContext
from memorable.core.profile import MemoryProfile, load_profile_from_yaml

# Fixed fixture timestamps from the tracer-bullet contract.
FIXTURE_TIMESTAMPS = {
    "space": datetime(2026, 5, 23, 10, 0, 0, tzinfo=UTC),
    "profile": datetime(2026, 5, 23, 10, 5, 0, tzinfo=UTC),
    "entity": datetime(2026, 5, 23, 10, 10, 0, tzinfo=UTC),
    "decision_v1": datetime(2026, 5, 23, 10, 15, 0, tzinfo=UTC),
    "decision_v2": datetime(2026, 5, 23, 10, 20, 0, tzinfo=UTC),
    "task": datetime(2026, 5, 23, 10, 25, 0, tzinfo=UTC),
    "task_complete": datetime(2026, 5, 23, 10, 30, 0, tzinfo=UTC),
}

SOURCE_ID = "source:tracer-fixture"
WRITER = "agent:tracer-fixture"

STATEMENT_V1 = "Graphiti is the first implementation path for Memorable storage."
STATEMENT_V2 = (
    "Direct Neo4j is the first implementation path;"
    " Graphiti remains optional behind the storage adapter."
)

TASK_TITLE = "Build the MCP smoke path over shared core behavior."

PROFILE_YAML = """\
version: 1
space:
  name: memorable
  description: Default memory space
entities:
  - name: Project
  - name: Component
records:
  - name: ArchitectureDecision
    extends: Decision
  - name: FollowUp
    extends: Task
"""

# Query timestamps for verification.
QUERY_AT_10_17 = datetime(2026, 5, 23, 10, 17, 0, tzinfo=UTC)
QUERY_AT_10_21 = datetime(2026, 5, 23, 10, 21, 0, tzinfo=UTC)
QUERY_AT_10_27 = datetime(2026, 5, 23, 10, 27, 0, tzinfo=UTC)
QUERY_AT_10_31 = datetime(2026, 5, 23, 10, 31, 0, tzinfo=UTC)


class TracerService:
    """Application service that runs the full tracer-bullet fixture
    and returns structured verification results.

    Creates its own ApplicationContext to avoid polluting global state.
    """

    def run(self) -> dict[str, object]:
        """Execute the fixture and return all verification sections."""
        ctx = ApplicationContext()
        profile = load_profile_from_yaml(PROFILE_YAML)

        # --- Execute fixture steps ---
        self._run_fixture(ctx, profile)

        # --- Collect verification results ---
        return {
            "current_truth": self._verify_current_truth(ctx),
            "point_in_time_before": self._verify_pit_before(ctx),
            "point_in_time_after": self._verify_pit_after(ctx),
            "task_before_completion": self._verify_task_before(ctx),
            "task_after_completion": self._verify_task_after(ctx),
            "provenance": self._verify_provenance(ctx),
            "hybrid_retrieval": self._verify_hybrid_retrieval(ctx),
        }

    def _run_fixture(self, ctx: ApplicationContext, profile: MemoryProfile) -> None:
        """Run the 7-step fixed fixture."""
        # Step 3: Remember Entity
        entity_svc = RememberEntityService(repository=ctx.entity_repo, profile=profile)
        entity_svc.remember(
            space="memorable",
            entity_id="entity:memorable",
            entity_type="Project",
            name="Memorable",
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMPS["entity"],
            writer=WRITER,
            reason="Tracer fixture: initial entity for the Memorable project.",
        )

        # Step 4: Remember initial Decision
        decision_svc = RememberDecisionService(
            repository=ctx.decision_repo, profile=profile
        )
        decision_svc.remember(
            space="memorable",
            decision_id="decision:storage-path:v1",
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMPS["decision_v1"],
            writer=WRITER,
            reason="Tracer fixture: initial storage path decision.",
        )

        # Step 5: Remember superseding Decision
        decision_svc.remember(
            space="memorable",
            decision_id="decision:storage-path:v2",
            statement=STATEMENT_V2,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMPS["decision_v2"],
            writer=WRITER,
            reason="Tracer fixture: superseding storage path decision.",
            supersedes="decision:storage-path:v1",
        )

        # Step 6: Remember Task
        task_svc = RememberTaskService(repository=ctx.task_repo, profile=profile)
        task_svc.remember(
            space="memorable",
            task_id="task:mcp-smoke-path",
            title=TASK_TITLE,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMPS["task"],
            writer=WRITER,
            reason="Tracer fixture: task for building the MCP smoke path.",
        )

        # Step 7: Complete Task
        complete_svc = CompleteTaskService(repository=ctx.task_repo)
        complete_svc.complete(
            space="memorable",
            task_id="task:mcp-smoke-path",
            at=FIXTURE_TIMESTAMPS["task_complete"],
        )

    def _verify_current_truth(self, ctx: ApplicationContext) -> dict[str, object]:
        svc = CurrentTruthService(repository=ctx.decision_repo)
        decision = svc.current(space="memorable", record_id="decision:storage-path:v1")
        return {
            "decision_id": decision.id,
            "statement": decision.statement,
            "lifecycle_state": decision.lifecycle_state,
            "validity_time": decision.validity_time.isoformat(),
        }

    def _verify_pit_before(self, ctx: ApplicationContext) -> dict[str, object]:
        svc = PointInTimeTruthService(repository=ctx.decision_repo)
        decision = svc.at(
            space="memorable",
            record_id="decision:storage-path:v1",
            at=QUERY_AT_10_17,
        )
        return {
            "decision_id": decision.id,
            "statement": decision.statement,
            "lifecycle_state": decision.lifecycle_state,
            "as_of": QUERY_AT_10_17.isoformat(),
        }

    def _verify_pit_after(self, ctx: ApplicationContext) -> dict[str, object]:
        svc = PointInTimeTruthService(repository=ctx.decision_repo)
        decision = svc.at(
            space="memorable",
            record_id="decision:storage-path:v1",
            at=QUERY_AT_10_21,
        )
        return {
            "decision_id": decision.id,
            "statement": decision.statement,
            "lifecycle_state": decision.lifecycle_state,
            "as_of": QUERY_AT_10_21.isoformat(),
        }

    def _verify_task_before(self, ctx: ApplicationContext) -> dict[str, object]:
        svc = InspectTaskService(repository=ctx.task_repo)
        task = svc.inspect(
            space="memorable",
            task_id="task:mcp-smoke-path",
            as_of=QUERY_AT_10_27,
        )
        return {
            "task_id": task.id,
            "title": task.title,
            "lifecycle_state": task.lifecycle_state,
            "as_of": QUERY_AT_10_27.isoformat(),
        }

    def _verify_task_after(self, ctx: ApplicationContext) -> dict[str, object]:
        svc = InspectTaskService(repository=ctx.task_repo)
        task = svc.inspect(
            space="memorable",
            task_id="task:mcp-smoke-path",
            as_of=QUERY_AT_10_31,
        )
        return {
            "task_id": task.id,
            "title": task.title,
            "lifecycle_state": task.lifecycle_state,
            "completion_event_id": task.completion_event_id,
            "as_of": QUERY_AT_10_31.isoformat(),
        }

    def _verify_provenance(self, ctx: ApplicationContext) -> dict[str, object]:
        provenance = ctx.decision_repo.get_provenance(
            space="memorable", record_id="decision:storage-path:v2"
        )
        return {
            "record_id": provenance.record_id,
            "record_kind": provenance.record_kind,
            "source_id": provenance.source_id,
            "writer": provenance.writer,
            "reason": provenance.reason,
            "episode_id": provenance.episode_id,
            "creation_time": provenance.creation_time.isoformat(),
        }

    def _verify_hybrid_retrieval(self, ctx: ApplicationContext) -> dict[str, object]:
        from memorable.retrieval.embeddings import FakeEmbeddingProvider
        from memorable.retrieval.service import build_retrieval_service

        retrieval = build_retrieval_service(ctx, FakeEmbeddingProvider(dimensions=32))
        retrieval.reindex("memorable")

        results = retrieval.search(
            space="memorable",
            query=(
                "How should agents retrieve the current"
                " storage implementation decision?"
            ),
            mode="current",
        )

        # Find the decision result
        decision_results = [
            r for r in results if r.source_id == "decision:storage-path:v2"
        ]

        if decision_results:
            top = decision_results[0]
            return {
                "query": (
                    "How should agents retrieve the current"
                    " storage implementation decision?"
                ),
                "mode": "current",
                "top_result": {
                    "source_id": top.source_id,
                    "source_kind": top.source_kind,
                    "lifecycle_state": top.lifecycle_state,
                    "score": round(top.score, 4),
                    "explanation": list(top.explanation),
                    "provenance_summary": dict(top.provenance_summary),
                },
                "total_results": len(results),
            }

        return {"error": "decision:storage-path:v2 not found in results"}
