"""Contract tests for Decision Memory Review projections."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

import pytest

from memorable.core.models import Decision, Provenance, ProvenanceIntegrityError
from memorable.core.ports import DecisionRepository


def _unique_space() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


def _make_decision(
    space: str,
    decision_id: str,
    *,
    statement: str | None = None,
    lifecycle_state: str = "current",
) -> Decision:
    return Decision(
        id=decision_id,
        statement=statement or f"Decision {decision_id}",
        space=space,
        validity_time=datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC),
        invalidation_time=None,
        lifecycle_state=lifecycle_state,
        supersedes=None,
        superseded_by=None,
    )


def _make_provenance(record_id: str, creation_time: datetime) -> Provenance:
    return Provenance(
        record_id=record_id,
        record_kind="decision",
        source_id="src-1",
        episode_id="ep-1",
        writer="test-agent",
        reason="test reason",
        creation_time=creation_time,
        validity_time=creation_time,
    )


ALL_REPOS = [
    "decision_projection_inmemory_harness",
    pytest.param("decision_projection_neo4j_harness", marks=pytest.mark.integration),
]


class DecisionProjectionHarness(Protocol):
    repository: DecisionRepository

    def remove_provenance(self, *, space: str, record_id: str) -> None:
        """Remove Provenance to simulate a store-invariant violation."""
        ...


def _harness(
    harness_fixture: str,
    request: pytest.FixtureRequest,
) -> DecisionProjectionHarness:
    return request.getfixturevalue(harness_fixture)


def _remove_provenance(
    harness: DecisionProjectionHarness,
    *,
    space: str,
    record_id: str,
) -> None:
    harness.remove_provenance(space=space, record_id=record_id)


@pytest.mark.parametrize("harness_fixture", ALL_REPOS)
def test_list_projections_by_space_orders_by_creation_time(
    harness_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    repo = _harness(harness_fixture, request).repository
    space = _unique_space()
    t1 = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 25, 11, 0, 0, tzinfo=UTC)
    t3 = datetime(2026, 5, 25, 12, 0, 0, tzinfo=UTC)

    repo.save(_make_decision(space, "dec-late"), _make_provenance("dec-late", t3))
    repo.save(_make_decision(space, "dec-b"), _make_provenance("dec-b", t2))
    repo.save(_make_decision(space, "dec-early"), _make_provenance("dec-early", t1))
    repo.save(_make_decision(space, "dec-a"), _make_provenance("dec-a", t2))

    projections = repo.list_projections_by_space(
        space=space,
        state=None,
        since=None,
        until=None,
        limit=10,
    )

    assert [(p.id, p.creation_time) for p in projections] == [
        ("dec-early", t1),
        ("dec-a", t2),
        ("dec-b", t2),
        ("dec-late", t3),
    ]
    assert projections[0].type == "decision"
    assert projections[0].label == "Decision dec-early"
    assert projections[0].lifecycle_state == "current"


@pytest.mark.parametrize("harness_fixture", ALL_REPOS)
def test_list_projections_by_space_filters_by_lifecycle_state(
    harness_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    repo = _harness(harness_fixture, request).repository
    space = _unique_space()
    t1 = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 25, 11, 0, 0, tzinfo=UTC)

    repo.save(
        _make_decision(space, "dec-current", lifecycle_state="current"),
        _make_provenance("dec-current", t1),
    )
    repo.save(
        _make_decision(space, "dec-superseded", lifecycle_state="superseded"),
        _make_provenance("dec-superseded", t2),
    )

    projections = repo.list_projections_by_space(
        space=space,
        state="superseded",
        since=None,
        until=None,
        limit=10,
    )

    assert [p.id for p in projections] == ["dec-superseded"]
    assert projections[0].lifecycle_state == "superseded"


@pytest.mark.parametrize("harness_fixture", ALL_REPOS)
def test_list_projections_by_space_uses_half_open_creation_time_window(
    harness_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    repo = _harness(harness_fixture, request).repository
    space = _unique_space()
    before = datetime(2026, 5, 25, 9, 0, 0, tzinfo=UTC)
    since = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    inside = datetime(2026, 5, 25, 11, 0, 0, tzinfo=UTC)
    until = datetime(2026, 5, 25, 12, 0, 0, tzinfo=UTC)

    repo.save(
        _make_decision(space, "dec-before"),
        _make_provenance("dec-before", before),
    )
    repo.save(_make_decision(space, "dec-since"), _make_provenance("dec-since", since))
    repo.save(
        _make_decision(space, "dec-inside"),
        _make_provenance("dec-inside", inside),
    )
    repo.save(_make_decision(space, "dec-until"), _make_provenance("dec-until", until))

    projections = repo.list_projections_by_space(
        space=space,
        state=None,
        since=since,
        until=until,
        limit=10,
    )

    assert [p.id for p in projections] == ["dec-since", "dec-inside"]


@pytest.mark.parametrize("harness_fixture", ALL_REPOS)
def test_list_projections_by_space_truncates_to_limit(
    harness_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    repo = _harness(harness_fixture, request).repository
    space = _unique_space()

    for index in range(4):
        creation_time = datetime(2026, 5, 25, 10 + index, 0, 0, tzinfo=UTC)
        decision_id = f"dec-{index}"
        repo.save(
            _make_decision(space, decision_id),
            _make_provenance(decision_id, creation_time),
        )

    projections = repo.list_projections_by_space(
        space=space,
        state=None,
        since=None,
        until=None,
        limit=2,
    )

    assert [p.id for p in projections] == ["dec-0", "dec-1"]


@pytest.mark.parametrize("harness_fixture", ALL_REPOS)
def test_list_projections_by_space_returns_empty_result(
    harness_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    repo = _harness(harness_fixture, request).repository
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
    repo.save(
        _make_decision(space, "dec-missing-provenance"),
        _make_provenance("dec-missing-provenance", creation_time),
    )
    _remove_provenance(
        harness,
        space=space,
        record_id="dec-missing-provenance",
    )

    with pytest.raises(ProvenanceIntegrityError):
        repo.list_projections_by_space(
            space=space,
            state=None,
            since=None,
            until=None,
            limit=10,
        )


@pytest.mark.parametrize("harness_fixture", ALL_REPOS)
def test_list_projections_by_space_does_not_let_limit_hide_missing_provenance(
    harness_fixture: str,
    request: pytest.FixtureRequest,
) -> None:
    harness = _harness(harness_fixture, request)
    repo = harness.repository
    space = _unique_space()
    valid_time = datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC)
    missing_time = datetime(2026, 5, 25, 11, 0, 0, tzinfo=UTC)
    repo.save(
        _make_decision(space, "dec-valid"),
        _make_provenance("dec-valid", valid_time),
    )
    repo.save(
        _make_decision(space, "dec-missing-provenance"),
        _make_provenance("dec-missing-provenance", missing_time),
    )
    _remove_provenance(
        harness,
        space=space,
        record_id="dec-missing-provenance",
    )

    with pytest.raises(ProvenanceIntegrityError):
        repo.list_projections_by_space(
            space=space,
            state=None,
            since=None,
            until=None,
            limit=1,
        )
