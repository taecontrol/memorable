"""Tests for Memory Review: the memorable_list_records primitive.

Covers slice #83: a deep query service in core that deterministically lists
MemoryRecords (Decision, Observation, Relation, Task) in a MemorySpace,
projecting each to {id, type, label, lifecycle_state, creation_time}, ordered
by Creation Time and capped by a limit (default 50). Entities are excluded.

Service tests drive the service against in-memory repositories and assert on
returned projections — never on storage internals.
"""

from __future__ import annotations

from datetime import UTC, datetime

SPACE = "memorable"
SOURCE_ID = "source:tracer-fixture"

T1 = datetime(2026, 5, 23, 10, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 5, 23, 11, 0, 0, tzinfo=UTC)
T3 = datetime(2026, 5, 23, 12, 0, 0, tzinfo=UTC)
T4 = datetime(2026, 5, 23, 13, 0, 0, tzinfo=UTC)


def _make_context():
    from memorable.core.context import ApplicationContext

    return ApplicationContext()


def _remember_decision(ctx, *, decision_id: str, statement: str, at: datetime):
    from memorable.core.application import RememberDecisionService

    profile = ctx.load_profile(SPACE)
    service = RememberDecisionService(repository=ctx.decision_repo, profile=profile)
    service.remember(
        space=SPACE,
        decision_id=decision_id,
        statement=statement,
        source_id=SOURCE_ID,
        at=at,
    )


def _remember_observation(ctx, *, observation_id: str, statement: str, at: datetime):
    from memorable.core.application import RememberObservationService

    profile = ctx.load_profile(SPACE)
    service = RememberObservationService(
        repository=ctx.observation_repo, profile=profile
    )
    service.remember(
        space=SPACE,
        observation_id=observation_id,
        statement=statement,
        source_id=SOURCE_ID,
        at=at,
    )


def _remember_entities(ctx, *entity_ids: str, at: datetime):
    from memorable.core.application import RememberEntityService

    profile = ctx.load_profile(SPACE)
    service = RememberEntityService(repository=ctx.entity_repo, profile=profile)
    for entity_id in entity_ids:
        service.remember(
            space=SPACE,
            entity_id=entity_id,
            entity_type="Project",
            name=entity_id,
            source_id=SOURCE_ID,
            at=at,
        )


def _remember_relation(
    ctx,
    *,
    relation_id: str,
    source_entity_id: str,
    target_entity_id: str,
    statement: str,
    at: datetime,
):
    from memorable.core.application import RememberRelationService

    profile = ctx.load_profile(SPACE)
    service = RememberRelationService(
        relation_repo=ctx.relation_repo,
        entity_repo=ctx.entity_repo,
        profile=profile,
    )
    service.remember(
        space=SPACE,
        relation_id=relation_id,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        relation_type="depends-on",
        statement=statement,
        source_id=SOURCE_ID,
        at=at,
    )


def _remember_task(ctx, *, task_id: str, title: str, at: datetime):
    from memorable.core.application import RememberTaskService

    profile = ctx.load_profile(SPACE)
    service = RememberTaskService(repository=ctx.task_repo, profile=profile)
    service.remember(
        space=SPACE,
        task_id=task_id,
        title=title,
        source_id=SOURCE_ID,
        at=at,
    )


class TestListRecordsService:
    """ListRecordsService deterministically lists MemoryRecords as projections."""

    def _make_service(self, ctx):
        from memorable.core.application import ListRecordsService

        return ListRecordsService(
            decision_repo=ctx.decision_repo,
            observation_repo=ctx.observation_repo,
            relation_repo=ctx.relation_repo,
            task_repo=ctx.task_repo,
        )

    def test_lists_decision_as_projection(self) -> None:
        ctx = _make_context()
        _remember_decision(
            ctx,
            decision_id="decision:1",
            statement="Adopt Neo4j for storage.",
            at=T1,
        )
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE)

        assert len(projections) == 1
        projection = projections[0]
        assert projection.id == "decision:1"
        assert projection.type == "decision"
        assert projection.label == "Adopt Neo4j for storage."
        assert projection.lifecycle_state == "current"
        assert projection.creation_time == T1

    def test_includes_observation_and_relation_with_statement_labels(self) -> None:
        ctx = _make_context()
        _remember_observation(
            ctx,
            observation_id="observation:1",
            statement="Tests are green.",
            at=T1,
        )
        _remember_entities(ctx, "entity:a", "entity:b", at=T1)
        _remember_relation(
            ctx,
            relation_id="relation:1",
            source_entity_id="entity:a",
            target_entity_id="entity:b",
            statement="A depends on B.",
            at=T2,
        )
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE)

        by_id = {p.id: p for p in projections}
        assert by_id["observation:1"].type == "observation"
        assert by_id["observation:1"].label == "Tests are green."
        assert by_id["relation:1"].type == "relation"
        assert by_id["relation:1"].label == "A depends on B."

    def test_includes_task_with_title_label(self) -> None:
        ctx = _make_context()
        _remember_task(
            ctx,
            task_id="task:1",
            title="Wire the listing primitive.",
            at=T1,
        )
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE)

        assert len(projections) == 1
        projection = projections[0]
        assert projection.id == "task:1"
        assert projection.type == "task"
        assert projection.label == "Wire the listing primitive."
        assert projection.lifecycle_state == "open"
        assert projection.creation_time == T1

    def test_orders_projections_by_creation_time(self) -> None:
        ctx = _make_context()
        # Insert out of chronological order across record types.
        _remember_task(ctx, task_id="task:late", title="Late task.", at=T4)
        _remember_decision(
            ctx, decision_id="decision:early", statement="Early decision.", at=T1
        )
        _remember_observation(
            ctx, observation_id="observation:mid", statement="Mid obs.", at=T2
        )
        _remember_entities(ctx, "entity:a", "entity:b", at=T1)
        _remember_relation(
            ctx,
            relation_id="relation:later",
            source_entity_id="entity:a",
            target_entity_id="entity:b",
            statement="Later relation.",
            at=T3,
        )
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE)

        assert [p.id for p in projections] == [
            "decision:early",
            "observation:mid",
            "relation:later",
            "task:late",
        ]

    def test_excludes_entities(self) -> None:
        ctx = _make_context()
        _remember_entities(ctx, "entity:a", "entity:b", at=T1)
        _remember_decision(
            ctx, decision_id="decision:1", statement="A decision.", at=T2
        )
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE)

        assert [p.id for p in projections] == ["decision:1"]
        assert all(p.type != "entity" for p in projections)

    def test_default_limit_caps_at_fifty(self) -> None:
        ctx = _make_context()
        for i in range(60):
            minute = i % 60
            at = datetime(2026, 5, 23, 10, minute, 0, tzinfo=UTC)
            _remember_decision(
                ctx, decision_id=f"decision:{i:02d}", statement=f"Decision {i}.", at=at
            )
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE)

        assert len(projections) == 50

    def test_limit_can_be_overridden(self) -> None:
        ctx = _make_context()
        for i in range(10):
            at = datetime(2026, 5, 23, 10, i, 0, tzinfo=UTC)
            _remember_decision(
                ctx, decision_id=f"decision:{i}", statement=f"Decision {i}.", at=at
            )
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, limit=3)

        assert len(projections) == 3
        # The earliest by Creation Time come first.
        assert [p.id for p in projections] == [
            "decision:0",
            "decision:1",
            "decision:2",
        ]


class TestMCPListRecords:
    """MCP list_records_tool wraps ListRecordsService and returns projections."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_list_records_tool_returns_projections(self) -> None:
        from memorable.mcp.server import (
            list_records_tool,
            remember_decision_tool,
            remember_task_tool,
        )

        remember_decision_tool(
            space=SPACE,
            decision_id="decision:1",
            statement="Adopt Neo4j.",
            source=SOURCE_ID,
            at="2026-05-23T10:00:00Z",
        )
        remember_task_tool(
            space=SPACE,
            task_id="task:1",
            title="Ship the primitive.",
            source=SOURCE_ID,
            at="2026-05-23T11:00:00Z",
        )

        result = list_records_tool(space=SPACE)

        assert "error" not in result
        records = result["records"]
        assert [r["id"] for r in records] == ["decision:1", "task:1"]

        decision = records[0]
        assert decision["type"] == "decision"
        assert decision["label"] == "Adopt Neo4j."
        assert decision["lifecycle_state"] == "current"
        assert decision["creation_time"] == "2026-05-23T10:00:00+00:00"

        task = records[1]
        assert task["type"] == "task"
        assert task["label"] == "Ship the primitive."
        assert task["lifecycle_state"] == "open"

    def test_list_records_tool_respects_limit(self) -> None:
        from memorable.mcp.server import list_records_tool, remember_decision_tool

        for i in range(5):
            remember_decision_tool(
                space=SPACE,
                decision_id=f"decision:{i}",
                statement=f"Decision {i}.",
                source=SOURCE_ID,
                at=f"2026-05-23T10:0{i}:00Z",
            )

        result = list_records_tool(space=SPACE, limit=2)

        assert "error" not in result
        assert len(result["records"]) == 2

    def test_list_records_tool_returns_error_dict_when_provenance_missing(
        self,
    ) -> None:
        """A stored record whose Provenance join is broken yields an error dict.

        In a graph store a record node can outlive (or precede) its Provenance
        relationship, so ``list_by_space`` returns the record while
        ``get_provenance`` returns None. The tool must surface this as an error
        dict rather than letting the join failure escape to the MCP caller.
        """
        from memorable.core.context import ApplicationContext
        from memorable.core.models import Decision
        from memorable.core.repositories import InMemoryDecisionRepository
        from memorable.mcp.server import list_records_tool, set_mcp_context

        class MissingProvenanceDecisionRepo(InMemoryDecisionRepository):
            def get_provenance(self, space: str, record_id: str):  # noqa: ARG002
                return None

        repo = MissingProvenanceDecisionRepo()
        repo._records[(SPACE, "decision:orphan")] = Decision(
            id="decision:orphan",
            statement="Orphaned decision.",
            space=SPACE,
            validity_time=T1,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )

        ctx = ApplicationContext(decision_repo=repo)
        set_mcp_context(ctx)
        try:
            result = list_records_tool(space=SPACE)
        finally:
            from memorable.core.context import default_context

            set_mcp_context(default_context)

        assert "error" in result
