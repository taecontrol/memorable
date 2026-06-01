from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from memorable.core.models import Decision, Observation, Provenance, Task

PROFILE_YAML = """\
version: 1
space:
  name: memorable
  description: test
entities:
  - name: Project
records: []
"""

AT = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


class _Result:
    def __init__(self, record: dict[str, str] | None = None) -> None:
        self._record = record

    def single(self) -> dict[str, str] | None:
        return self._record


class _ConstraintSession:
    def __init__(self, *, existing_record: bool) -> None:
        self._existing_record = existing_record

    def __enter__(self) -> _ConstraintSession:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def run(self, query: str, **params: object) -> _Result:
        from neo4j.exceptions import ConstraintError

        if "MATCH (record:Record" in query:
            if self._existing_record:
                return _Result({"id": str(params["id"])})
            return _Result()
        raise ConstraintError("other constraint failure")


class _ConstraintDriver:
    def __init__(self, *, existing_record: bool) -> None:
        self._existing_record = existing_record

    def session(self) -> _ConstraintSession:
        return _ConstraintSession(existing_record=self._existing_record)


def _profile():
    from memorable.core.profile import load_profile_from_yaml

    return load_profile_from_yaml(PROFILE_YAML)


def _make_provenance(record_id: str, record_kind: str) -> Provenance:
    return Provenance(
        record_id=record_id,
        record_kind=record_kind,
        source_id="source:test",
        episode_id="episode:test",
        writer="agent:test",
        reason="test",
        creation_time=AT,
        validity_time=AT,
    )


def _make_record(record_kind: str, *, space: str, record_id: str):
    if record_kind == "decision":
        return Decision(
            id=record_id,
            statement="Remember a Decision.",
            space=space,
            validity_time=AT,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
    if record_kind == "observation":
        return Observation(
            id=record_id,
            statement="Remember an Observation.",
            space=space,
            validity_time=AT,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
    return Task(
        id=record_id,
        title="Remember a Task.",
        space=space,
        lifecycle_state="open",
        validity_time=AT,
        completion_time=None,
        completion_event_id=None,
    )


def _remember(service: object, *, record_kind: str, record_id: str) -> None:
    if record_kind == "decision":
        service.remember(
            space="memorable",
            decision_id=record_id,
            statement=f"Remember {record_id}.",
            source_id="source:test",
            at=AT,
        )
    elif record_kind == "observation":
        service.remember(
            space="memorable",
            observation_id=record_id,
            statement=f"Remember {record_id}.",
            source_id="source:test",
            at=AT,
        )
    else:
        service.remember(
            space="memorable",
            task_id=record_id,
            title=f"Remember {record_id}.",
            source_id="source:test",
            at=AT,
        )


def _service_for(record_kind: str) -> object:
    from memorable.core.application import (
        RememberDecisionService,
        RememberObservationService,
        RememberTaskService,
    )
    from memorable.core.repositories import (
        InMemoryDecisionRepository,
        InMemoryObservationRepository,
        InMemoryTaskRepository,
    )

    if record_kind == "decision":
        return RememberDecisionService(
            repository=InMemoryDecisionRepository(),
            profile=_profile(),
        )
    if record_kind == "observation":
        return RememberObservationService(
            repository=InMemoryObservationRepository(),
            profile=_profile(),
        )
    return RememberTaskService(
        repository=InMemoryTaskRepository(),
        profile=_profile(),
    )


@pytest.mark.parametrize("record_kind", ["decision", "observation", "task"])
def test_duplicate_id_raises_domain_error_for_writable_record_type(
    record_kind: str,
) -> None:
    from memorable.core.application import (
        DuplicateRecordError,
    )

    service = _service_for(record_kind)
    record_id = f"{record_kind}:duplicate"

    _remember(service, record_kind=record_kind, record_id=record_id)

    with pytest.raises(DuplicateRecordError) as exc_info:
        _remember(service, record_kind=record_kind, record_id=record_id)

    assert exc_info.value.record_kind == record_kind
    assert exc_info.value.space == "memorable"
    assert exc_info.value.record_id == record_id
    message = str(exc_info.value)
    assert record_id in message
    assert "MemorySpace 'memorable'" in message
    assert "correct" in message
    assert "new record id" in message
    assert "Neo" not in message
    assert "node" not in message.lower()
    assert "constraint" not in message.lower()

    _remember(service, record_kind=record_kind, record_id=f"{record_kind}:fresh")


def test_in_memory_context_rejects_duplicate_id_across_writable_record_types() -> None:
    from memorable.core.application import (
        DuplicateRecordError,
        RememberDecisionService,
        RememberTaskService,
    )
    from memorable.core.context import ApplicationContext

    ctx = ApplicationContext()
    profile = _profile()
    decision_service = RememberDecisionService(
        repository=ctx.decision_repo,
        profile=profile,
    )
    task_service = RememberTaskService(
        repository=ctx.task_repo,
        profile=profile,
    )

    decision_service.remember(
        space="memorable",
        decision_id="record:shared",
        statement="Remember shared id as a Decision.",
        source_id="source:test",
        at=AT,
    )

    with pytest.raises(DuplicateRecordError) as exc_info:
        task_service.remember(
            space="memorable",
            task_id="record:shared",
            title="Remember shared id as a Task.",
            source_id="source:test",
            at=AT,
        )

    assert exc_info.value.record_kind == "task"
    assert exc_info.value.record_id == "record:shared"


def test_mcp_duplicate_id_returns_domain_error() -> None:
    from memorable.core.context import default_context
    from memorable.mcp.server import remember_decision_tool, set_mcp_context

    default_context.reset()
    set_mcp_context(default_context)

    remember_decision_tool(
        space="memorable",
        decision_id="decision:mcp-duplicate",
        statement="Remember once.",
        source="source:test",
        at="2026-06-01T09:00:00Z",
    )

    result = remember_decision_tool(
        space="memorable",
        decision_id="decision:mcp-duplicate",
        statement="Remember twice.",
        source="source:test",
        at="2026-06-01T09:00:00Z",
    )

    error = result["error"]
    assert "decision:mcp-duplicate" in error
    assert "MemorySpace 'memorable'" in error
    assert "correct" in error
    assert "new record id" in error
    assert "Neo" not in error
    assert "node" not in error.lower()
    assert "constraint" not in error.lower()


def test_cli_duplicate_id_returns_domain_error(cli_in_memory_context, capsys) -> None:
    from memorable.cli import main

    command = [
        "remember",
        "decision",
        "--space",
        "memorable",
        "--id",
        "decision:cli-duplicate",
        "--statement",
        "Remember once.",
        "--source",
        "source:test",
        "--at",
        "2026-06-01T09:00:00Z",
    ]

    assert main(command) == 0
    capsys.readouterr()

    assert main(command) == 1
    captured = capsys.readouterr()
    assert "decision:cli-duplicate" in captured.err
    assert "MemorySpace 'memorable'" in captured.err
    assert "correct" in captured.err
    assert "new record id" in captured.err
    assert "Neo" not in captured.err
    assert "node" not in captured.err.lower()
    assert "constraint" not in captured.err.lower()


def test_neo4j_save_translates_constraint_error_when_record_exists() -> None:
    from memorable.core.application import DuplicateRecordError
    from memorable.storage.neo4j.repository import Neo4jDecisionRepository

    repo = Neo4jDecisionRepository(_ConstraintDriver(existing_record=True))
    record = _make_record(
        "decision",
        space="memorable",
        record_id="decision:existing",
    )

    with pytest.raises(DuplicateRecordError) as exc_info:
        repo.save(record, _make_provenance("decision:existing", "decision"))

    assert exc_info.value.record_kind == "decision"
    assert exc_info.value.space == "memorable"
    assert exc_info.value.record_id == "decision:existing"


def test_neo4j_save_preserves_constraint_error_when_record_does_not_exist() -> None:
    from neo4j.exceptions import ConstraintError

    from memorable.storage.neo4j.repository import Neo4jDecisionRepository

    repo = Neo4jDecisionRepository(_ConstraintDriver(existing_record=False))
    record = _make_record(
        "decision",
        space="memorable",
        record_id="decision:missing",
    )

    with pytest.raises(ConstraintError):
        repo.save(record, _make_provenance("decision:missing", "decision"))


@pytest.mark.integration
@pytest.mark.parametrize(
    ("record_kind", "fixture_name"),
    [
        ("decision", "decision_projection_neo4j_harness"),
        ("observation", "observation_projection_neo4j_harness"),
        ("task", "task_projection_neo4j_harness"),
    ],
)
def test_neo4j_duplicate_id_raises_domain_error(
    record_kind: str,
    fixture_name: str,
    request: pytest.FixtureRequest,
) -> None:
    from memorable.core.application import DuplicateRecordError
    from memorable.storage.neo4j.repository import ensure_all_constraints

    harness = request.getfixturevalue(fixture_name)
    ensure_all_constraints(harness.driver)
    space = f"test-dup-{uuid.uuid4().hex[:8]}"
    record_id = f"{record_kind}:duplicate"
    record = _make_record(record_kind, space=space, record_id=record_id)

    harness.save(record, _make_provenance(record_id, record_kind))

    with pytest.raises(DuplicateRecordError) as exc_info:
        harness.save(record, _make_provenance(record_id, record_kind))

    assert exc_info.value.record_kind == record_kind
    assert exc_info.value.space == space
    assert exc_info.value.record_id == record_id

    fresh_id = f"{record_kind}:fresh"
    harness.save(
        replace(record, id=fresh_id),
        _make_provenance(fresh_id, record_kind),
    )
