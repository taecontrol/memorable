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


def _complete_task(ctx, *, task_id: str, at: datetime):
    from memorable.core.application import CompleteTaskService

    service = CompleteTaskService(repository=ctx.task_repo)
    service.complete(space=SPACE, task_id=task_id, at=at, source_id=SOURCE_ID)


def _invalidate_record(ctx, repo, *, record_id: str, at: datetime):
    from memorable.core.application import InvalidateService

    service = InvalidateService(repository=repo)
    service.invalidate(space=SPACE, record_id=record_id, at=at)


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

    def test_bounded_merge_matches_naive_sort_all_then_slice(self) -> None:
        from memorable.core.application import ListRecordsService
        from memorable.core.models import RecordProjection

        def at_minute(minute: int) -> datetime:
            return datetime(2026, 5, 23, 10, minute, tzinfo=UTC)

        def projection(record_type: str, record_id: str, at: datetime):
            return RecordProjection(
                id=record_id,
                type=record_type,
                label=record_id,
                lifecycle_state="current",
                creation_time=at,
            )

        class ProjectionOnlyRepo:
            def __init__(self, rows: list[RecordProjection]) -> None:
                self._rows = rows

            def list_projections_by_space(
                self,
                *,
                space: str,
                state: str | None,
                since: datetime | None,
                until: datetime | None,
                limit: int,
            ) -> list[RecordProjection]:
                assert space == SPACE
                assert state is None
                assert since is None
                assert until is None
                return self._rows[:limit]

        rows_by_type = {
            "decision": [
                projection("decision", "decision:04", at_minute(4)),
                projection("decision", "decision:07", at_minute(7)),
            ],
            "observation": [
                projection("observation", "observation:01", at_minute(1)),
                projection("observation", "observation:06", at_minute(6)),
            ],
            "relation": [
                projection("relation", "relation:03", at_minute(3)),
                projection("relation", "relation:05", at_minute(5)),
            ],
            "task": [
                projection("task", "task:02", at_minute(2)),
                projection("task", "task:08", at_minute(8)),
            ],
        }
        service = ListRecordsService(
            decision_repo=ProjectionOnlyRepo(rows_by_type["decision"]),
            observation_repo=ProjectionOnlyRepo(rows_by_type["observation"]),
            relation_repo=ProjectionOnlyRepo(rows_by_type["relation"]),
            task_repo=ProjectionOnlyRepo(rows_by_type["task"]),
        )
        all_rows = [row for rows in rows_by_type.values() for row in rows]
        expected = sorted(all_rows, key=lambda p: (p.creation_time, p.id))[:5]

        projections = service.list_records(space=SPACE, limit=5)

        assert projections == expected

    def test_missing_provenance_raises_integrity_error_not_value_error(self) -> None:
        """A broken Provenance join is a store invariant violation, not bad input.

        ``list_projections_by_space`` can return a record whose Provenance join
        is missing (e.g. a graph node that outlived its Provenance
        relationship). That is a data-integrity failure distinct from a caller
        passing an unlistable ``type``, so it must raise
        ``ProvenanceIntegrityError`` rather than the ``ValueError`` reserved for
        bad input.
        """
        import pytest

        from memorable.core.application import ListRecordsService
        from memorable.core.context import ApplicationContext
        from memorable.core.models import Decision, ProvenanceIntegrityError
        from memorable.core.repositories import InMemoryDecisionRepository

        repo = InMemoryDecisionRepository()
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
        service = ListRecordsService(
            decision_repo=ctx.decision_repo,
            observation_repo=ctx.observation_repo,
            relation_repo=ctx.relation_repo,
            task_repo=ctx.task_repo,
        )

        with pytest.raises(ProvenanceIntegrityError):
            service.list_records(space=SPACE)

    def test_equal_creation_time_tie_breaks_by_id_ascending(self) -> None:
        ctx = _make_context()
        # Same Creation Time, inserted in reverse-id order so a stable sort
        # alone would preserve insertion order. Only a (creation_time, id)
        # key yields ascending ids.
        _remember_decision(
            ctx, decision_id="decision:c", statement="Third by id.", at=T1
        )
        _remember_decision(
            ctx, decision_id="decision:b", statement="Second by id.", at=T1
        )
        _remember_decision(
            ctx, decision_id="decision:a", statement="First by id.", at=T1
        )
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE)

        assert [p.id for p in projections] == [
            "decision:a",
            "decision:b",
            "decision:c",
        ]


class TestListRecordsServiceTypeFilter:
    """ListRecordsService restricts listing to a single MemoryRecord type."""

    def _make_service(self, ctx):
        from memorable.core.application import ListRecordsService

        return ListRecordsService(
            decision_repo=ctx.decision_repo,
            observation_repo=ctx.observation_repo,
            relation_repo=ctx.relation_repo,
            task_repo=ctx.task_repo,
        )

    def _seed_all_types(self, ctx) -> None:
        _remember_decision(
            ctx, decision_id="decision:1", statement="A decision.", at=T1
        )
        _remember_observation(
            ctx, observation_id="observation:1", statement="An observation.", at=T2
        )
        _remember_entities(ctx, "entity:a", "entity:b", at=T1)
        _remember_relation(
            ctx,
            relation_id="relation:1",
            source_entity_id="entity:a",
            target_entity_id="entity:b",
            statement="A relates to B.",
            at=T3,
        )
        _remember_task(ctx, task_id="task:1", title="A task.", at=T4)

    def test_filters_to_decisions_only(self) -> None:
        ctx = _make_context()
        self._seed_all_types(ctx)
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, type="decision")

        assert [p.id for p in projections] == ["decision:1"]
        assert all(p.type == "decision" for p in projections)

    def test_filters_to_observations_only(self) -> None:
        ctx = _make_context()
        self._seed_all_types(ctx)
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, type="observation")

        assert [p.id for p in projections] == ["observation:1"]
        assert all(p.type == "observation" for p in projections)

    def test_filters_to_relations_only(self) -> None:
        ctx = _make_context()
        self._seed_all_types(ctx)
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, type="relation")

        assert [p.id for p in projections] == ["relation:1"]
        assert all(p.type == "relation" for p in projections)

    def test_filters_to_tasks_only(self) -> None:
        ctx = _make_context()
        self._seed_all_types(ctx)
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, type="task")

        assert [p.id for p in projections] == ["task:1"]
        assert all(p.type == "task" for p in projections)

    def test_type_none_lists_all_record_types(self) -> None:
        ctx = _make_context()
        self._seed_all_types(ctx)
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, type=None)

        assert {p.type for p in projections} == {
            "decision",
            "observation",
            "relation",
            "task",
        }

    def test_entity_type_is_rejected(self) -> None:
        import pytest

        ctx = _make_context()
        self._seed_all_types(ctx)
        service = self._make_service(ctx)

        with pytest.raises(ValueError, match="entity"):
            service.list_records(space=SPACE, type="entity")

    def test_unknown_type_is_rejected(self) -> None:
        import pytest

        ctx = _make_context()
        service = self._make_service(ctx)

        with pytest.raises(ValueError, match="nonsense"):
            service.list_records(space=SPACE, type="nonsense")


class TestListRecordsServiceStateFilter:
    """ListRecordsService restricts listing to a single Lifecycle State."""

    def _make_service(self, ctx):
        from memorable.core.application import ListRecordsService

        return ListRecordsService(
            decision_repo=ctx.decision_repo,
            observation_repo=ctx.observation_repo,
            relation_repo=ctx.relation_repo,
            task_repo=ctx.task_repo,
        )

    def test_filters_to_open_records(self) -> None:
        ctx = _make_context()
        _remember_decision(
            ctx, decision_id="decision:1", statement="A current decision.", at=T1
        )
        _remember_task(ctx, task_id="task:open", title="Still open.", at=T2)
        _remember_task(ctx, task_id="task:done", title="Will complete.", at=T3)
        _complete_task(ctx, task_id="task:done", at=T4)
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, state="open")

        assert [p.id for p in projections] == ["task:open"]
        assert all(p.lifecycle_state == "open" for p in projections)

    def test_filters_to_current_records(self) -> None:
        ctx = _make_context()
        _remember_decision(
            ctx, decision_id="decision:1", statement="A current decision.", at=T1
        )
        _remember_observation(
            ctx,
            observation_id="observation:1",
            statement="A current observation.",
            at=T2,
        )
        _remember_task(ctx, task_id="task:1", title="An open task.", at=T3)
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, state="current")

        assert [p.id for p in projections] == ["decision:1", "observation:1"]
        assert all(p.lifecycle_state == "current" for p in projections)

    def test_filters_to_completed_records(self) -> None:
        ctx = _make_context()
        _remember_task(ctx, task_id="task:open", title="Still open.", at=T1)
        _remember_task(ctx, task_id="task:done", title="Will complete.", at=T2)
        _complete_task(ctx, task_id="task:done", at=T3)
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, state="completed")

        assert [p.id for p in projections] == ["task:done"]
        assert all(p.lifecycle_state == "completed" for p in projections)

    def test_filters_to_superseded_records(self) -> None:
        from memorable.core.application import RememberDecisionService

        ctx = _make_context()
        _remember_decision(
            ctx, decision_id="decision:old", statement="Old call.", at=T1
        )
        # Remembering a successor with supersedes marks the old as superseded.
        profile = ctx.load_profile(SPACE)
        RememberDecisionService(repository=ctx.decision_repo, profile=profile).remember(
            space=SPACE,
            decision_id="decision:new",
            statement="New call.",
            source_id=SOURCE_ID,
            at=T2,
            supersedes="decision:old",
        )
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, state="superseded")

        assert [p.id for p in projections] == ["decision:old"]
        assert all(p.lifecycle_state == "superseded" for p in projections)

    def test_filters_to_invalidated_records(self) -> None:
        ctx = _make_context()
        _remember_observation(
            ctx, observation_id="observation:1", statement="No longer true.", at=T1
        )
        _remember_observation(
            ctx, observation_id="observation:2", statement="Still true.", at=T2
        )
        _invalidate_record(ctx, ctx.observation_repo, record_id="observation:1", at=T3)
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, state="invalidated")

        assert [p.id for p in projections] == ["observation:1"]
        assert all(p.lifecycle_state == "invalidated" for p in projections)

    def test_state_none_lists_records_in_any_state(self) -> None:
        ctx = _make_context()
        _remember_decision(
            ctx, decision_id="decision:1", statement="A decision.", at=T1
        )
        _remember_task(ctx, task_id="task:open", title="Open.", at=T2)
        _remember_task(ctx, task_id="task:done", title="Done.", at=T3)
        _complete_task(ctx, task_id="task:done", at=T4)
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, state=None)

        assert {p.id for p in projections} == {
            "decision:1",
            "task:open",
            "task:done",
        }
        assert {p.lifecycle_state for p in projections} == {
            "current",
            "open",
            "completed",
        }

    def test_type_and_state_filters_compose(self) -> None:
        ctx = _make_context()
        _remember_task(ctx, task_id="task:open", title="Open task.", at=T1)
        _remember_task(ctx, task_id="task:done", title="Done task.", at=T2)
        _complete_task(ctx, task_id="task:done", at=T3)
        _remember_decision(
            ctx, decision_id="decision:1", statement="A decision.", at=T4
        )
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, type="task", state="open")

        assert [p.id for p in projections] == ["task:open"]


class TestListRecordsServiceCreationTimeWindow:
    """ListRecordsService bounds listing by a Provenance Creation Time window.

    Boundary semantics: ``since`` is an inclusive lower bound and ``until`` is
    an exclusive upper bound, both compared against Provenance Creation Time.
    Either bound may be omitted; omitting both preserves list-all behavior.
    """

    def _make_service(self, ctx):
        from memorable.core.application import ListRecordsService

        return ListRecordsService(
            decision_repo=ctx.decision_repo,
            observation_repo=ctx.observation_repo,
            relation_repo=ctx.relation_repo,
            task_repo=ctx.task_repo,
        )

    def _seed_four_decisions(self, ctx) -> None:
        _remember_decision(ctx, decision_id="decision:t1", statement="At T1.", at=T1)
        _remember_decision(ctx, decision_id="decision:t2", statement="At T2.", at=T2)
        _remember_decision(ctx, decision_id="decision:t3", statement="At T3.", at=T3)
        _remember_decision(ctx, decision_id="decision:t4", statement="At T4.", at=T4)

    def test_since_is_inclusive_lower_bound(self) -> None:
        ctx = _make_context()
        self._seed_four_decisions(ctx)
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, since=T2)

        # T2 itself is included (inclusive lower bound); T1 is excluded.
        assert [p.id for p in projections] == [
            "decision:t2",
            "decision:t3",
            "decision:t4",
        ]

    def test_until_is_exclusive_upper_bound(self) -> None:
        ctx = _make_context()
        self._seed_four_decisions(ctx)
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, until=T3)

        # T3 itself is excluded (exclusive upper bound); T1 and T2 remain.
        assert [p.id for p in projections] == ["decision:t1", "decision:t2"]

    def test_since_and_until_bound_a_window(self) -> None:
        ctx = _make_context()
        self._seed_four_decisions(ctx)
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, since=T2, until=T4)

        # [T2, T4): T2 and T3 included, T1 before and T4 at the open bound excluded.
        assert [p.id for p in projections] == ["decision:t2", "decision:t3"]

    def test_omitting_both_bounds_lists_all(self) -> None:
        ctx = _make_context()
        self._seed_four_decisions(ctx)
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE)

        assert [p.id for p in projections] == [
            "decision:t1",
            "decision:t2",
            "decision:t3",
            "decision:t4",
        ]

    def test_type_and_creation_time_window_compose(self) -> None:
        ctx = _make_context()
        # A decision and a task both at T2; only the decision should survive a
        # type=decision + since=T2 compound filter.
        _remember_decision(
            ctx, decision_id="decision:early", statement="Before window.", at=T1
        )
        _remember_decision(
            ctx, decision_id="decision:in", statement="In window.", at=T2
        )
        _remember_task(ctx, task_id="task:in", title="Also in window.", at=T2)
        service = self._make_service(ctx)

        projections = service.list_records(space=SPACE, type="decision", since=T2)

        assert [p.id for p in projections] == ["decision:in"]
        assert all(p.type == "decision" for p in projections)


class TestMCPListRecords:
    """MCP list_records_tool wraps ListRecordsService and returns projections."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_list_records_tool_contract_shape_and_order_are_stable(self) -> None:
        import asyncio

        from memorable.mcp.server import (
            mcp_server,
            remember_decision_tool,
            remember_entity_tool,
            remember_observation_tool,
            remember_relation_tool,
            remember_task_tool,
        )

        remember_entity_tool(
            space=SPACE,
            entity_id="entity:contract-source",
            entity_type="Project",
            name="Contract Source",
            source=SOURCE_ID,
            at="2026-05-23T09:00:00Z",
        )
        remember_entity_tool(
            space=SPACE,
            entity_id="entity:contract-target",
            entity_type="Project",
            name="Contract Target",
            source=SOURCE_ID,
            at="2026-05-23T09:01:00Z",
        )
        remember_decision_tool(
            space=SPACE,
            decision_id="decision:contract",
            statement="Keep the MCP listing contract stable.",
            source=SOURCE_ID,
            at="2026-05-23T10:00:00Z",
        )
        remember_observation_tool(
            space=SPACE,
            observation_id="observation:contract",
            statement="Agents depend on this projection shape.",
            source=SOURCE_ID,
            at="2026-05-23T11:00:00Z",
        )
        remember_relation_tool(
            space=SPACE,
            relation_id="relation:contract",
            source_entity_id="entity:contract-source",
            target_entity_id="entity:contract-target",
            relation_type="depends-on",
            statement="Contract source depends on contract target.",
            source=SOURCE_ID,
            at="2026-05-23T12:00:00Z",
        )
        remember_task_tool(
            space=SPACE,
            task_id="task:contract",
            title="Verify the MCP contract.",
            source=SOURCE_ID,
            at="2026-05-23T13:00:00Z",
        )

        _, result = asyncio.run(
            mcp_server.call_tool(
                "memorable_list_records", {"space": SPACE, "limit": 10}
            )
        )

        assert "error" not in result
        records = result["records"]
        assert [set(record) for record in records] == [
            {"id", "type", "label", "lifecycle_state", "creation_time"},
            {"id", "type", "label", "lifecycle_state", "creation_time"},
            {"id", "type", "label", "lifecycle_state", "creation_time"},
            {"id", "type", "label", "lifecycle_state", "creation_time"},
        ]
        assert records == [
            {
                "id": "decision:contract",
                "type": "decision",
                "label": "Keep the MCP listing contract stable.",
                "lifecycle_state": "current",
                "creation_time": "2026-05-23T10:00:00+00:00",
            },
            {
                "id": "observation:contract",
                "type": "observation",
                "label": "Agents depend on this projection shape.",
                "lifecycle_state": "current",
                "creation_time": "2026-05-23T11:00:00+00:00",
            },
            {
                "id": "relation:contract",
                "type": "relation",
                "label": "Contract source depends on contract target.",
                "lifecycle_state": "current",
                "creation_time": "2026-05-23T12:00:00+00:00",
            },
            {
                "id": "task:contract",
                "type": "task",
                "label": "Verify the MCP contract.",
                "lifecycle_state": "open",
                "creation_time": "2026-05-23T13:00:00+00:00",
            },
        ]

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

    def test_list_records_tool_filters_by_type(self) -> None:
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

        result = list_records_tool(space=SPACE, type="decision")

        assert "error" not in result
        records = result["records"]
        assert [r["id"] for r in records] == ["decision:1"]
        assert all(r["type"] == "decision" for r in records)

    def test_list_records_tool_rejects_entity_type(self) -> None:
        from memorable.mcp.server import list_records_tool

        result = list_records_tool(space=SPACE, type="entity")

        assert "error" in result
        assert "entity" in result["error"].lower()

    def test_list_records_tool_rejects_unknown_type(self) -> None:
        from memorable.mcp.server import list_records_tool

        result = list_records_tool(space=SPACE, type="nonsense")

        assert "error" in result
        assert "nonsense" in result["error"]

    def _seed_decisions_across_days(self) -> None:
        from memorable.mcp.server import remember_decision_tool

        remember_decision_tool(
            space=SPACE,
            decision_id="decision:mon",
            statement="Monday call.",
            source=SOURCE_ID,
            at="2026-05-25T10:00:00Z",
        )
        remember_decision_tool(
            space=SPACE,
            decision_id="decision:wed",
            statement="Wednesday call.",
            source=SOURCE_ID,
            at="2026-05-27T10:00:00Z",
        )
        remember_decision_tool(
            space=SPACE,
            decision_id="decision:fri",
            statement="Friday call.",
            source=SOURCE_ID,
            at="2026-05-29T10:00:00Z",
        )

    def test_list_records_tool_filters_by_since(self) -> None:
        from memorable.mcp.server import list_records_tool

        self._seed_decisions_across_days()

        result = list_records_tool(space=SPACE, since="2026-05-27T10:00:00Z")

        assert "error" not in result
        # since is an inclusive lower bound: Wednesday is included, Monday dropped.
        assert [r["id"] for r in result["records"]] == [
            "decision:wed",
            "decision:fri",
        ]

    def test_list_records_tool_filters_by_until(self) -> None:
        from memorable.mcp.server import list_records_tool

        self._seed_decisions_across_days()

        result = list_records_tool(space=SPACE, until="2026-05-27T10:00:00Z")

        assert "error" not in result
        # until is an exclusive upper bound: Wednesday is dropped.
        assert [r["id"] for r in result["records"]] == ["decision:mon"]

    def test_list_records_tool_composes_type_and_since(self) -> None:
        from memorable.mcp.server import (
            list_records_tool,
            remember_decision_tool,
            remember_task_tool,
        )

        remember_decision_tool(
            space=SPACE,
            decision_id="decision:in",
            statement="Decision today.",
            source=SOURCE_ID,
            at="2026-05-30T09:00:00Z",
        )
        remember_task_tool(
            space=SPACE,
            task_id="task:in",
            title="Task today.",
            source=SOURCE_ID,
            at="2026-05-30T09:00:00Z",
        )
        remember_decision_tool(
            space=SPACE,
            decision_id="decision:old",
            statement="Decision yesterday.",
            source=SOURCE_ID,
            at="2026-05-29T09:00:00Z",
        )

        result = list_records_tool(
            space=SPACE, type="decision", since="2026-05-30T00:00:00Z"
        )

        assert "error" not in result
        assert [r["id"] for r in result["records"]] == ["decision:in"]

    def test_list_records_tool_filters_by_state(self) -> None:
        from memorable.mcp.server import (
            complete_task_tool,
            list_records_tool,
            remember_task_tool,
        )

        remember_task_tool(
            space=SPACE,
            task_id="task:open",
            title="Still open.",
            source=SOURCE_ID,
            at="2026-05-23T10:00:00Z",
        )
        remember_task_tool(
            space=SPACE,
            task_id="task:done",
            title="Will complete.",
            source=SOURCE_ID,
            at="2026-05-23T11:00:00Z",
        )
        complete_task_tool(
            space=SPACE,
            task_id="task:done",
            at="2026-05-23T12:00:00Z",
            source=SOURCE_ID,
        )

        result = list_records_tool(space=SPACE, state="open")

        assert "error" not in result
        records = result["records"]
        assert [r["id"] for r in records] == ["task:open"]
        assert all(r["lifecycle_state"] == "open" for r in records)
