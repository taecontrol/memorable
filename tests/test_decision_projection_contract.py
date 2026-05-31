"""Contract tests for Memory Review repository projections."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

import pytest

from memorable.core.models import (
    Decision,
    Observation,
    Provenance,
    ProvenanceIntegrityError,
    Relation,
    Task,
)


def _unique_space() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


def _make_record(
    record_type: str,
    space: str,
    record_id: str,
    *,
    statement: str | None = None,
    lifecycle_state: str | None = None,
) -> Any:
    validity_time = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    if record_type == "decision":
        return Decision(
            id=record_id,
            statement=statement or f"Decision {record_id}",
            space=space,
            validity_time=validity_time,
            invalidation_time=None,
            lifecycle_state=lifecycle_state or "current",
            supersedes=None,
            superseded_by=None,
        )
    if record_type == "observation":
        return Observation(
            id=record_id,
            statement=statement or f"Observation {record_id}",
            space=space,
            validity_time=validity_time,
            invalidation_time=None,
            lifecycle_state=lifecycle_state or "current",
            supersedes=None,
            superseded_by=None,
        )
    if record_type == "relation":
        return Relation(
            id=record_id,
            source_entity_id=f"entity:{record_id}:source",
            target_entity_id=f"entity:{record_id}:target",
            relation_type="depends-on",
            statement=statement or f"Relation {record_id}",
            space=space,
            validity_time=validity_time,
            invalidation_time=None,
            lifecycle_state=lifecycle_state or "current",
            supersedes=None,
            superseded_by=None,
        )
    if record_type == "task":
        return Task(
            id=record_id,
            title=statement or f"Task {record_id}",
            space=space,
            lifecycle_state=lifecycle_state or "open",
            validity_time=validity_time,
            completion_time=None,
            completion_event_id=None,
        )
    raise AssertionError(f"Unsupported record type: {record_type}")


def _make_provenance(
    record_type: str,
    record_id: str,
    creation_time: datetime,
) -> Provenance:
    return Provenance(
        record_id=record_id,
        record_kind=record_type,
        source_id="src-1",
        episode_id="ep-1",
        writer="test-agent",
        reason="test reason",
        creation_time=creation_time,
        validity_time=creation_time,
    )


ALL_REPOS = [
    "decision_projection_inmemory_harness",
    "observation_projection_inmemory_harness",
    "relation_projection_inmemory_harness",
    "task_projection_inmemory_harness",
    pytest.param("decision_projection_neo4j_harness", marks=pytest.mark.integration),
    pytest.param("observation_projection_neo4j_harness", marks=pytest.mark.integration),
    pytest.param("relation_projection_neo4j_harness", marks=pytest.mark.integration),
    pytest.param("task_projection_neo4j_harness", marks=pytest.mark.integration),
]


class ProjectionHarness(Protocol):
    repository: Any
    record_type: str

    def save(self, record: Any, provenance: Provenance) -> None:
        """Persist a MemoryRecord and its Provenance."""
        ...

    def remove_provenance(self, *, space: str, record_id: str) -> None:
        """Remove Provenance to simulate a store-invariant violation."""
        ...


def _harness(
    harness_fixture: str,
    request: pytest.FixtureRequest,
) -> ProjectionHarness:
    return request.getfixturevalue(harness_fixture)


def _save(
    harness: ProjectionHarness,
    *,
    space: str,
    record_id: str,
    creation_time: datetime,
    statement: str | None = None,
    lifecycle_state: str | None = None,
) -> None:
    record = _make_record(
        harness.record_type,
        space,
        record_id,
        statement=statement,
        lifecycle_state=lifecycle_state,
    )
    provenance = _make_provenance(harness.record_type, record_id, creation_time)
    harness.save(record, provenance)


@pytest.mark.parametrize("harness_fixture", ALL_REPOS)
def test_list_projections_by_space_orders_by_creation_time(
    harness_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    harness = _harness(harness_fixture, request)
    repo = harness.repository
    space = _unique_space()
    prefix = harness.record_type[:3]
    t1 = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 25, 11, 0, 0, tzinfo=UTC)
    t3 = datetime(2026, 5, 25, 12, 0, 0, tzinfo=UTC)

    _save(harness, space=space, record_id=f"{prefix}-late", creation_time=t3)
    _save(harness, space=space, record_id=f"{prefix}-b", creation_time=t2)
    _save(harness, space=space, record_id=f"{prefix}-early", creation_time=t1)
    _save(harness, space=space, record_id=f"{prefix}-a", creation_time=t2)

    projections = repo.list_projections_by_space(
        space=space,
        state=None,
        since=None,
        until=None,
        limit=10,
    )

    assert [(p.id, p.creation_time) for p in projections] == [
        (f"{prefix}-early", t1),
        (f"{prefix}-a", t2),
        (f"{prefix}-b", t2),
        (f"{prefix}-late", t3),
    ]
    assert projections[0].type == harness.record_type
    assert projections[0].label == f"{harness.record_type.title()} {prefix}-early"
    assert projections[0].lifecycle_state == (
        "open" if harness.record_type == "task" else "current"
    )


@pytest.mark.parametrize("harness_fixture", ALL_REPOS)
def test_list_projections_by_space_filters_by_record_ids(
    harness_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    harness = _harness(harness_fixture, request)
    repo = harness.repository
    space = _unique_space()
    prefix = harness.record_type[:3]
    t1 = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 25, 11, 0, 0, tzinfo=UTC)

    _save(harness, space=space, record_id=f"{prefix}-wanted", creation_time=t1)
    _save(harness, space=space, record_id=f"{prefix}-unrelated", creation_time=t2)

    projections = repo.list_projections_by_space(
        space=space,
        state=None,
        since=None,
        until=None,
        limit=10,
        record_ids={f"{prefix}-wanted"},
    )

    assert [p.id for p in projections] == [f"{prefix}-wanted"]


@pytest.mark.parametrize("harness_fixture", ALL_REPOS)
def test_list_projections_by_space_filters_by_lifecycle_state(
    harness_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    harness = _harness(harness_fixture, request)
    repo = harness.repository
    space = _unique_space()
    t1 = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 25, 11, 0, 0, tzinfo=UTC)
    wanted_state = "completed" if harness.record_type == "task" else "superseded"
    default_state = "open" if harness.record_type == "task" else "current"

    _save(
        harness,
        space=space,
        record_id="rec-default",
        creation_time=t1,
        lifecycle_state=default_state,
    )
    _save(
        harness,
        space=space,
        record_id="rec-wanted",
        creation_time=t2,
        lifecycle_state=wanted_state,
    )

    projections = repo.list_projections_by_space(
        space=space,
        state=wanted_state,
        since=None,
        until=None,
        limit=10,
    )

    assert [p.id for p in projections] == ["rec-wanted"]
    assert projections[0].lifecycle_state == wanted_state


@pytest.mark.parametrize("harness_fixture", ALL_REPOS)
def test_list_projections_by_space_uses_half_open_creation_time_window(
    harness_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    harness = _harness(harness_fixture, request)
    repo = harness.repository
    space = _unique_space()
    before = datetime(2026, 5, 25, 9, 0, 0, tzinfo=UTC)
    since = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    inside = datetime(2026, 5, 25, 11, 0, 0, tzinfo=UTC)
    until = datetime(2026, 5, 25, 12, 0, 0, tzinfo=UTC)

    _save(harness, space=space, record_id="rec-before", creation_time=before)
    _save(harness, space=space, record_id="rec-since", creation_time=since)
    _save(harness, space=space, record_id="rec-inside", creation_time=inside)
    _save(harness, space=space, record_id="rec-until", creation_time=until)

    projections = repo.list_projections_by_space(
        space=space,
        state=None,
        since=since,
        until=until,
        limit=10,
    )

    assert [p.id for p in projections] == ["rec-since", "rec-inside"]


@pytest.mark.parametrize("harness_fixture", ALL_REPOS)
def test_list_projections_by_space_truncates_to_limit(
    harness_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    harness = _harness(harness_fixture, request)
    repo = harness.repository
    space = _unique_space()

    for index in range(4):
        creation_time = datetime(2026, 5, 25, 10 + index, 0, 0, tzinfo=UTC)
        record_id = f"rec-{index}"
        _save(harness, space=space, record_id=record_id, creation_time=creation_time)

    projections = repo.list_projections_by_space(
        space=space,
        state=None,
        since=None,
        until=None,
        limit=2,
    )

    assert [p.id for p in projections] == ["rec-0", "rec-1"]


@pytest.mark.parametrize("harness_fixture", ALL_REPOS)
def test_list_projections_by_space_returns_empty_result(
    harness_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    harness = _harness(harness_fixture, request)
    repo = harness.repository
    space = _unique_space()

    projections = repo.list_projections_by_space(
        space=space,
        state="current",
        since=None,
        until=None,
        limit=10,
    )

    assert projections == []


@pytest.mark.parametrize("harness_fixture", ALL_REPOS)
def test_list_projections_by_space_raises_when_provenance_join_is_missing(
    harness_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    harness = _harness(harness_fixture, request)
    repo = harness.repository
    space = _unique_space()
    creation_time = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    _save(
        harness,
        space=space,
        record_id="rec-missing-provenance",
        creation_time=creation_time,
    )
    harness.remove_provenance(space=space, record_id="rec-missing-provenance")

    with pytest.raises(ProvenanceIntegrityError):
        repo.list_projections_by_space(
            space=space,
            state=None,
            since=None,
            until=None,
            limit=10,
        )
