"""Tests for Task lifecycle completion and temporal truth.

Covers slice #8 acceptance criteria:
- Task remembered at 2026-05-23T10:25:00Z as open.
- Task completed at 2026-05-23T10:30:00Z with append-first event.
- Before completion (as-of 10:27), lifecycle_state is "open".
- After completion (as-of 10:31 or current), lifecycle_state is "completed".
- Completion is append-first: the original task record is NOT deleted.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime

import pytest

# --- Fixture data ---

FIXTURE_TIMESTAMP_REMEMBER = datetime(2026, 5, 23, 10, 25, 0, tzinfo=UTC)
FIXTURE_TIMESTAMP_COMPLETE = datetime(2026, 5, 23, 10, 30, 0, tzinfo=UTC)

TASK_ID = "task:mcp-smoke-path"
TASK_TITLE = "Build the MCP smoke path over shared core behavior."
SOURCE_ID = "source:tracer-fixture"
EVENT_ID = "event:complete-task:mcp-smoke-path"

VALID_PROFILE_YAML = textwrap.dedent("""\
    version: 1

    space:
      name: memorable
      description: Agent memory system design

    entities:
      - name: Project
      - name: Component

    records:
      - name: ArchitectureDecision
        extends: Decision
      - name: FollowUp
        extends: Task
""")


# =====================================================================
# Domain model tests
# =====================================================================


class TestTaskModel:
    """Task is a remembered work item with lifecycle state."""

    def test_task_has_required_fields(self) -> None:
        from memorable.core.models import Task

        task = Task(
            id=TASK_ID,
            title=TASK_TITLE,
            space="memorable",
            lifecycle_state="open",
            validity_time=FIXTURE_TIMESTAMP_REMEMBER,
            completion_time=None,
            completion_event_id=None,
        )
        assert task.id == TASK_ID
        assert task.title == TASK_TITLE
        assert task.space == "memorable"
        assert task.lifecycle_state == "open"
        assert task.validity_time == FIXTURE_TIMESTAMP_REMEMBER
        assert task.completion_time is None
        assert task.completion_event_id is None

    def test_task_is_frozen(self) -> None:
        from memorable.core.models import Task

        task = Task(
            id=TASK_ID,
            title=TASK_TITLE,
            space="memorable",
            lifecycle_state="open",
            validity_time=FIXTURE_TIMESTAMP_REMEMBER,
            completion_time=None,
            completion_event_id=None,
        )
        with pytest.raises(AttributeError):
            task.title = "Changed"  # type: ignore[misc]

    def test_task_requires_non_empty_id(self) -> None:
        from memorable.core.models import Task

        with pytest.raises(ValueError, match="id"):
            Task(
                id="",
                title=TASK_TITLE,
                space="memorable",
                lifecycle_state="open",
                validity_time=FIXTURE_TIMESTAMP_REMEMBER,
                completion_time=None,
                completion_event_id=None,
            )

    def test_task_requires_non_empty_title(self) -> None:
        from memorable.core.models import Task

        with pytest.raises(ValueError, match="title"):
            Task(
                id=TASK_ID,
                title="",
                space="memorable",
                lifecycle_state="open",
                validity_time=FIXTURE_TIMESTAMP_REMEMBER,
                completion_time=None,
                completion_event_id=None,
            )


class TestTaskProvenanceModel:
    """Provenance explains where a Task came from."""

    def test_task_provenance_has_required_fields(self) -> None:
        from memorable.core.models import Provenance

        prov = Provenance(
            record_id=TASK_ID,
            record_kind="task",
            source_id=SOURCE_ID,
            episode_id="episode:tracer-fixture:2026-05-23T10:25:00+00:00",
            writer="agent:tracer-fixture",
            reason="tests Task lifecycle",
            creation_time=FIXTURE_TIMESTAMP_REMEMBER,
            validity_time=FIXTURE_TIMESTAMP_REMEMBER,
        )
        assert prov.record_id == TASK_ID
        assert prov.record_kind == "task"
        assert prov.source_id == SOURCE_ID
        assert prov.writer == "agent:tracer-fixture"
        assert prov.creation_time == FIXTURE_TIMESTAMP_REMEMBER
        assert prov.validity_time == FIXTURE_TIMESTAMP_REMEMBER


# =====================================================================
# Repository port tests
# =====================================================================


class TestTaskRepositoryPort:
    """InMemoryTaskRepository defines persistence for Tasks."""

    def _make_task(self):
        from memorable.core.models import Provenance, Task

        task = Task(
            id=TASK_ID,
            title=TASK_TITLE,
            space="memorable",
            lifecycle_state="open",
            validity_time=FIXTURE_TIMESTAMP_REMEMBER,
            completion_time=None,
            completion_event_id=None,
        )
        provenance = Provenance(
            record_id=TASK_ID,
            record_kind="task",
            source_id=SOURCE_ID,
            episode_id="episode:tracer-fixture:2026-05-23T10:25:00+00:00",
            writer="agent:tracer-fixture",
            reason="initial task",
            creation_time=FIXTURE_TIMESTAMP_REMEMBER,
            validity_time=FIXTURE_TIMESTAMP_REMEMBER,
        )
        return task, provenance

    def test_save_and_retrieve_task(self) -> None:
        from memorable.core.repositories import InMemoryTaskRepository

        repo = InMemoryTaskRepository()
        task, provenance = self._make_task()

        repo.save(task, provenance)
        retrieved = repo.get(space="memorable", task_id=TASK_ID)

        assert retrieved is not None
        assert retrieved.id == TASK_ID
        assert retrieved.title == TASK_TITLE

    def test_retrieve_provenance(self) -> None:
        from memorable.core.repositories import InMemoryTaskRepository

        repo = InMemoryTaskRepository()
        task, provenance = self._make_task()

        repo.save(task, provenance)
        prov = repo.get_provenance(space="memorable", task_id=TASK_ID)

        assert prov is not None
        assert prov.source_id == SOURCE_ID
        assert prov.writer == "agent:tracer-fixture"

    def test_get_returns_none_for_missing(self) -> None:
        from memorable.core.repositories import InMemoryTaskRepository

        repo = InMemoryTaskRepository()
        assert repo.get(space="memorable", task_id="task:missing") is None

    def test_get_provenance_returns_none_for_missing(self) -> None:
        from memorable.core.repositories import InMemoryTaskRepository

        repo = InMemoryTaskRepository()
        assert repo.get_provenance(space="memorable", task_id="task:missing") is None

    def test_complete_updates_task(self) -> None:
        from memorable.core.repositories import InMemoryTaskRepository

        repo = InMemoryTaskRepository()
        task, provenance = self._make_task()
        repo.save(task, provenance)

        repo.complete(
            space="memorable",
            task_id=TASK_ID,
            completion_time=FIXTURE_TIMESTAMP_COMPLETE,
            completion_event_id=EVENT_ID,
        )

        completed = repo.get(space="memorable", task_id=TASK_ID)
        assert completed is not None
        assert completed.lifecycle_state == "completed"
        assert completed.completion_time == FIXTURE_TIMESTAMP_COMPLETE
        assert completed.completion_event_id == EVENT_ID

    def test_append_first_task_not_deleted(self) -> None:
        """Append-first: task not deleted after completion, just updated."""
        from memorable.core.repositories import InMemoryTaskRepository

        repo = InMemoryTaskRepository()
        task, provenance = self._make_task()
        repo.save(task, provenance)

        repo.complete(
            space="memorable",
            task_id=TASK_ID,
            completion_time=FIXTURE_TIMESTAMP_COMPLETE,
            completion_event_id=EVENT_ID,
        )

        # Task still exists
        stored = repo.get(space="memorable", task_id=TASK_ID)
        assert stored is not None
        assert stored.lifecycle_state == "completed"

        # Provenance still exists
        prov = repo.get_provenance(space="memorable", task_id=TASK_ID)
        assert prov is not None


# =====================================================================
# Application service tests
# =====================================================================


class TestRememberTaskService:
    """RememberTaskService validates and creates provenance."""

    def _make_service(self):
        from memorable.core.application import RememberTaskService
        from memorable.core.clock import FixedClock
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryTaskRepository

        repo = InMemoryTaskRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        return (
            RememberTaskService(
                repository=repo,
                profile=profile,
                clock=FixedClock(FIXTURE_TIMESTAMP_REMEMBER),
            ),
            repo,
        )

    def test_remember_task_stores_with_provenance(self) -> None:
        service, repo = self._make_service()

        result = service.remember(
            space="memorable",
            task_id=TASK_ID,
            title=TASK_TITLE,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_REMEMBER,
        )

        assert result.task.id == TASK_ID
        assert result.task.lifecycle_state == "open"
        assert result.provenance.source_id == SOURCE_ID
        assert result.provenance.creation_time == FIXTURE_TIMESTAMP_REMEMBER

        stored = repo.get(space="memorable", task_id=TASK_ID)
        assert stored is not None

    def test_remember_task_with_declared_subtype_round_trips(self) -> None:
        service, repo = self._make_service()

        result = service.remember(
            space="memorable",
            task_id=TASK_ID,
            title=TASK_TITLE,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_REMEMBER,
            record_type="FollowUp",
        )

        assert result.task.record_type == "FollowUp"
        stored = repo.get(space="memorable", task_id=TASK_ID)
        assert stored is not None
        assert stored.record_type == "FollowUp"

    @pytest.mark.parametrize(
        ("record_type", "expected"),
        [
            ("Pattern", "Record Subtype 'Pattern' is not declared"),
            (
                "ArchitectureDecision",
                "Record Subtype 'ArchitectureDecision' extends Decision, not Task",
            ),
        ],
    )
    def test_remember_task_with_invalid_subtype_fails_loud(
        self,
        record_type: str,
        expected: str,
    ) -> None:
        from memorable.core.application import UndeclaredTypeError

        service, _repo = self._make_service()

        with pytest.raises(UndeclaredTypeError) as error:
            service.remember(
                space="memorable",
                task_id=TASK_ID,
                title=TASK_TITLE,
                source_id=SOURCE_ID,
                at=FIXTURE_TIMESTAMP_REMEMBER,
                record_type=record_type,
            )

        message = str(error.value)
        assert expected in message
        assert "FollowUp" in message

    def test_remember_task_creates_episode(self) -> None:
        service, _repo = self._make_service()

        result = service.remember(
            space="memorable",
            task_id=TASK_ID,
            title=TASK_TITLE,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_REMEMBER,
        )

        expected_episode = "episode:tracer-fixture:2026-05-23T10:25:00+00:00"
        assert result.provenance.episode_id == expected_episode

    def test_remembers_task_against_empty_profile(self) -> None:
        """Task is a kernel record type: writable with no declaration.

        An Agent can create a Task in an empty-profile MemorySpace so that
        commitments are captured from the first session. A profile record
        extending Task is optional specialization, never a precondition.
        """
        from memorable.core.application import RememberTaskService
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryTaskRepository

        empty_records_yaml = textwrap.dedent("""\
            version: 1
            space:
              name: memorable
              description: test
            entities:
              - name: Project
            records: []
        """)
        repo = InMemoryTaskRepository()
        profile = load_profile_from_yaml(empty_records_yaml)

        service = RememberTaskService(repository=repo, profile=profile)

        result = service.remember(
            space="memorable",
            task_id=TASK_ID,
            title=TASK_TITLE,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_REMEMBER,
        )

        assert result.task.id == TASK_ID
        assert repo.get(space="memorable", task_id=TASK_ID) is not None

    def test_remember_task_sets_writer(self) -> None:
        service, _repo = self._make_service()

        result = service.remember(
            space="memorable",
            task_id=TASK_ID,
            title=TASK_TITLE,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_REMEMBER,
            writer="agent:tracer-fixture",
        )

        assert result.provenance.writer == "agent:tracer-fixture"


class TestCompleteTaskService:
    """CompleteTaskService marks a Task as completed."""

    def _setup_task(self):
        from memorable.core.application import (
            CompleteTaskService,
            RememberTaskService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryTaskRepository

        repo = InMemoryTaskRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberTaskService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            task_id=TASK_ID,
            title=TASK_TITLE,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_REMEMBER,
        )

        complete = CompleteTaskService(repository=repo)
        return complete, repo

    def test_complete_task(self) -> None:
        service, repo = self._setup_task()

        result = service.complete(
            space="memorable",
            task_id=TASK_ID,
            at=FIXTURE_TIMESTAMP_COMPLETE,
        )

        assert result.task.lifecycle_state == "completed"
        assert result.event_id == EVENT_ID
        assert result.completion_time == FIXTURE_TIMESTAMP_COMPLETE

    def test_complete_preserves_record_subtype(self) -> None:
        from memorable.core.application import CompleteTaskService, RememberTaskService
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryTaskRepository

        repo = InMemoryTaskRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        RememberTaskService(repository=repo, profile=profile).remember(
            space="memorable",
            task_id=TASK_ID,
            title=TASK_TITLE,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_REMEMBER,
            record_type="FollowUp",
        )

        result = CompleteTaskService(repository=repo).complete(
            space="memorable",
            task_id=TASK_ID,
            at=FIXTURE_TIMESTAMP_COMPLETE,
        )

        assert result.task.record_type == "FollowUp"

    def test_complete_rejects_missing_task(self) -> None:
        from memorable.core.application import CompleteTaskService
        from memorable.core.repositories import InMemoryTaskRepository

        repo = InMemoryTaskRepository()
        service = CompleteTaskService(repository=repo)

        with pytest.raises(ValueError, match="not found"):
            service.complete(
                space="memorable",
                task_id="task:missing",
                at=FIXTURE_TIMESTAMP_COMPLETE,
            )

    def test_complete_rejects_already_completed(self) -> None:
        service, _repo = self._setup_task()

        service.complete(
            space="memorable",
            task_id=TASK_ID,
            at=FIXTURE_TIMESTAMP_COMPLETE,
        )

        with pytest.raises(ValueError, match="already completed"):
            service.complete(
                space="memorable",
                task_id=TASK_ID,
                at=FIXTURE_TIMESTAMP_COMPLETE,
            )

    def test_complete_creates_event_id(self) -> None:
        service, _repo = self._setup_task()

        result = service.complete(
            space="memorable",
            task_id=TASK_ID,
            at=FIXTURE_TIMESTAMP_COMPLETE,
        )

        assert result.event_id == EVENT_ID


class TestInspectTaskService:
    """InspectTaskService returns task state at current or as-of time."""

    def _setup_completed_task(self):
        from memorable.core.application import (
            CompleteTaskService,
            InspectTaskService,
            RememberTaskService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryTaskRepository

        repo = InMemoryTaskRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        remember = RememberTaskService(repository=repo, profile=profile)

        remember.remember(
            space="memorable",
            task_id=TASK_ID,
            title=TASK_TITLE,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_REMEMBER,
        )

        complete = CompleteTaskService(repository=repo)
        complete.complete(
            space="memorable",
            task_id=TASK_ID,
            at=FIXTURE_TIMESTAMP_COMPLETE,
        )

        inspect = InspectTaskService(repository=repo)
        return inspect, repo

    def test_inspect_current_state(self) -> None:
        service, _repo = self._setup_completed_task()

        result = service.inspect(space="memorable", task_id=TASK_ID)

        assert result is not None
        assert result.lifecycle_state == "completed"

    def test_inspect_as_of_before_completion(self) -> None:
        service, _repo = self._setup_completed_task()

        at_1027 = datetime(2026, 5, 23, 10, 27, 0, tzinfo=UTC)
        result = service.inspect(space="memorable", task_id=TASK_ID, as_of=at_1027)

        assert result is not None
        assert result.lifecycle_state == "open"

    def test_inspect_as_of_before_completion_preserves_record_subtype(self) -> None:
        from memorable.core.application import (
            CompleteTaskService,
            InspectTaskService,
            RememberTaskService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryTaskRepository

        repo = InMemoryTaskRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        RememberTaskService(repository=repo, profile=profile).remember(
            space="memorable",
            task_id=TASK_ID,
            title=TASK_TITLE,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_REMEMBER,
            record_type="FollowUp",
        )
        CompleteTaskService(repository=repo).complete(
            space="memorable",
            task_id=TASK_ID,
            at=FIXTURE_TIMESTAMP_COMPLETE,
        )

        at_1027 = datetime(2026, 5, 23, 10, 27, 0, tzinfo=UTC)
        result = InspectTaskService(repository=repo).inspect(
            space="memorable",
            task_id=TASK_ID,
            as_of=at_1027,
        )

        assert result is not None
        assert result.lifecycle_state == "open"
        assert result.record_type == "FollowUp"

    def test_inspect_as_of_after_completion(self) -> None:
        service, _repo = self._setup_completed_task()

        at_1031 = datetime(2026, 5, 23, 10, 31, 0, tzinfo=UTC)
        result = service.inspect(space="memorable", task_id=TASK_ID, as_of=at_1031)

        assert result is not None
        assert result.lifecycle_state == "completed"

    def test_inspect_as_of_before_validity_returns_none(self) -> None:
        service, _repo = self._setup_completed_task()

        at_1020 = datetime(2026, 5, 23, 10, 20, 0, tzinfo=UTC)
        result = service.inspect(space="memorable", task_id=TASK_ID, as_of=at_1020)

        assert result is None

    def test_inspect_as_of_at_exact_validity_time_returns_task(self) -> None:
        """as_of == validity_time is visible (strict < excludes it)."""
        service, _repo = self._setup_completed_task()

        result = service.inspect(
            space="memorable", task_id=TASK_ID, as_of=FIXTURE_TIMESTAMP_REMEMBER
        )

        assert result is not None
        assert result.lifecycle_state == "open"

    def test_inspect_as_of_at_exact_completion_time_returns_completed(self) -> None:
        """as_of == completion_time: completion is visible (strict <)."""
        service, _repo = self._setup_completed_task()

        result = service.inspect(
            space="memorable", task_id=TASK_ID, as_of=FIXTURE_TIMESTAMP_COMPLETE
        )

        assert result is not None
        assert result.lifecycle_state == "completed"

    def test_inspect_returns_none_for_missing(self) -> None:
        from memorable.core.application import InspectTaskService
        from memorable.core.repositories import InMemoryTaskRepository

        repo = InMemoryTaskRepository()
        service = InspectTaskService(repository=repo)

        result = service.inspect(space="memorable", task_id="task:missing")
        assert result is None


# =====================================================================
# CLI adapter tests
# =====================================================================


@pytest.mark.usefixtures("cli_in_memory_context")
class TestCLIRememberTask:
    """CLI `memorable remember task` writes a Task."""

    def test_remember_task_command(self, capsys) -> None:
        from memorable.cli import main

        exit_code = main(
            [
                "remember",
                "task",
                "--space",
                "memorable",
                "--id",
                TASK_ID,
                "--title",
                TASK_TITLE,
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:25:00Z",
            ]
        )

        assert exit_code == 0
        output = capsys.readouterr().out
        assert TASK_ID in output
        assert SOURCE_ID in output

    def test_remember_task_includes_unified_provenance_fields(self, capsys) -> None:
        """CLI remember task JSON output includes record_id and record_kind."""
        import json

        from memorable.cli import main

        exit_code = main(
            [
                "remember",
                "task",
                "--space",
                "memorable",
                "--id",
                TASK_ID,
                "--title",
                TASK_TITLE,
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:25:00Z",
            ]
        )

        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["record_id"] == TASK_ID
        assert output["record_kind"] == "task"

    def test_remember_task_with_type_outputs_record_type(self, capsys) -> None:
        import json

        from memorable.cli import main

        exit_code = main(
            [
                "remember",
                "task",
                "--space",
                "memorable",
                "--id",
                TASK_ID,
                "--title",
                TASK_TITLE,
                "--type",
                "FollowUp",
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:25:00Z",
            ]
        )

        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["record_kind"] == "task"
        assert output["record_type"] == "FollowUp"

        exit_code = main(
            [
                "task",
                "inspect",
                "--space",
                "memorable",
                "--id",
                TASK_ID,
            ]
        )

        assert exit_code == 0
        inspect_output = json.loads(capsys.readouterr().out)
        assert inspect_output["record_type"] == "FollowUp"


@pytest.mark.usefixtures("cli_in_memory_context")
class TestCLICompleteTask:
    """CLI `memorable complete task` completes a Task."""

    def test_complete_task_command(self, capsys) -> None:
        from memorable.cli import main

        # Remember first
        main(
            [
                "remember",
                "task",
                "--space",
                "memorable",
                "--id",
                TASK_ID,
                "--title",
                TASK_TITLE,
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:25:00Z",
            ]
        )

        # Complete
        exit_code = main(
            [
                "complete",
                "task",
                "--space",
                "memorable",
                "--id",
                TASK_ID,
                "--at",
                "2026-05-23T10:30:00Z",
            ]
        )

        assert exit_code == 0
        output = capsys.readouterr().out
        assert EVENT_ID in output
        assert "completed" in output


@pytest.mark.usefixtures("cli_in_memory_context")
class TestCLITaskInspect:
    """CLI `memorable task inspect` shows task lifecycle."""

    def test_task_inspect_command(self, capsys) -> None:
        from memorable.cli import main

        # Remember and complete
        main(
            [
                "remember",
                "task",
                "--space",
                "memorable",
                "--id",
                TASK_ID,
                "--title",
                TASK_TITLE,
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:25:00Z",
            ]
        )
        main(
            [
                "complete",
                "task",
                "--space",
                "memorable",
                "--id",
                TASK_ID,
                "--at",
                "2026-05-23T10:30:00Z",
            ]
        )

        exit_code = main(
            [
                "task",
                "inspect",
                "--space",
                "memorable",
                "--id",
                TASK_ID,
            ]
        )

        assert exit_code == 0
        output = capsys.readouterr().out
        assert TASK_ID in output
        assert "completed" in output

    def test_task_inspect_as_of_before_completion(self, capsys) -> None:
        from memorable.cli import main

        main(
            [
                "remember",
                "task",
                "--space",
                "memorable",
                "--id",
                TASK_ID,
                "--title",
                TASK_TITLE,
                "--source",
                SOURCE_ID,
                "--at",
                "2026-05-23T10:25:00Z",
            ]
        )
        main(
            [
                "complete",
                "task",
                "--space",
                "memorable",
                "--id",
                TASK_ID,
                "--at",
                "2026-05-23T10:30:00Z",
            ]
        )

        exit_code = main(
            [
                "task",
                "inspect",
                "--space",
                "memorable",
                "--id",
                TASK_ID,
                "--as-of",
                "2026-05-23T10:27:00Z",
            ]
        )

        assert exit_code == 0
        output = capsys.readouterr().out
        assert "open" in output


# =====================================================================
# MCP adapter tests
# =====================================================================


class TestMCPRememberTask:
    """MCP remember_task_tool writes a Task."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_remember_task_tool(self) -> None:
        from memorable.mcp.server import remember_task_tool

        result = remember_task_tool(
            space="memorable",
            task_id=TASK_ID,
            title=TASK_TITLE,
            source=SOURCE_ID,
            at="2026-05-23T10:25:00Z",
        )

        assert result["task_id"] == TASK_ID
        assert result["source"] == SOURCE_ID
        assert "error" not in result

    def test_remember_task_tool_with_record_type_reads_back(self) -> None:
        from memorable.mcp.server import inspect_task_tool, remember_task_tool

        remember_result = remember_task_tool(
            space="memorable",
            task_id=TASK_ID,
            title=TASK_TITLE,
            source=SOURCE_ID,
            at="2026-05-23T10:25:00Z",
            record_type="FollowUp",
        )

        assert "error" not in remember_result
        assert remember_result["record_kind"] == "task"
        assert remember_result["record_type"] == "FollowUp"

        inspect_result = inspect_task_tool(space="memorable", task_id=TASK_ID)

        assert "error" not in inspect_result
        assert inspect_result["record_type"] == "FollowUp"

    def test_remember_task_tool_includes_unified_provenance_fields(self) -> None:
        """MCP remember_task_tool response includes record_id and record_kind."""
        from memorable.mcp.server import remember_task_tool

        result = remember_task_tool(
            space="memorable",
            task_id=TASK_ID,
            title=TASK_TITLE,
            source=SOURCE_ID,
            at="2026-05-23T10:25:00Z",
        )

        assert "error" not in result
        assert result["record_id"] == TASK_ID
        assert result["record_kind"] == "task"


class TestMCPCompleteTask:
    """MCP complete_task_tool completes a Task."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_complete_task_tool(self) -> None:
        from memorable.mcp.server import (
            complete_task_tool,
            remember_task_tool,
        )

        remember_task_tool(
            space="memorable",
            task_id=TASK_ID,
            title=TASK_TITLE,
            source=SOURCE_ID,
            at="2026-05-23T10:25:00Z",
        )

        result = complete_task_tool(
            space="memorable",
            task_id=TASK_ID,
            at="2026-05-23T10:30:00Z",
        )

        assert "error" not in result
        assert result["event_id"] == EVENT_ID
        assert result["lifecycle_state"] == "completed"

    def test_complete_task_tool_rejects_missing(self) -> None:
        from memorable.mcp.server import complete_task_tool

        result = complete_task_tool(
            space="memorable",
            task_id="task:missing",
            at="2026-05-23T10:30:00Z",
        )

        assert "error" in result


class TestMCPInspectTask:
    """MCP inspect_task_tool inspects task lifecycle."""

    def setup_method(self) -> None:
        from memorable.core.context import default_context

        default_context.reset()

    def test_inspect_task_tool(self) -> None:
        from memorable.mcp.server import (
            complete_task_tool,
            inspect_task_tool,
            remember_task_tool,
        )

        remember_task_tool(
            space="memorable",
            task_id=TASK_ID,
            title=TASK_TITLE,
            source=SOURCE_ID,
            at="2026-05-23T10:25:00Z",
        )
        complete_task_tool(
            space="memorable",
            task_id=TASK_ID,
            at="2026-05-23T10:30:00Z",
        )

        result = inspect_task_tool(
            space="memorable",
            task_id=TASK_ID,
        )

        assert "error" not in result
        assert result["lifecycle_state"] == "completed"

    def test_inspect_task_tool_as_of(self) -> None:
        from memorable.mcp.server import (
            complete_task_tool,
            inspect_task_tool,
            remember_task_tool,
        )

        remember_task_tool(
            space="memorable",
            task_id=TASK_ID,
            title=TASK_TITLE,
            source=SOURCE_ID,
            at="2026-05-23T10:25:00Z",
        )
        complete_task_tool(
            space="memorable",
            task_id=TASK_ID,
            at="2026-05-23T10:30:00Z",
        )

        result = inspect_task_tool(
            space="memorable",
            task_id=TASK_ID,
            as_of="2026-05-23T10:27:00Z",
        )

        assert "error" not in result
        assert result["lifecycle_state"] == "open"

    def test_inspect_task_tool_missing(self) -> None:
        from memorable.mcp.server import inspect_task_tool

        result = inspect_task_tool(
            space="memorable",
            task_id="task:missing",
        )

        assert "error" in result


# =====================================================================
# Language boundary test
# =====================================================================


class TestLanguageBoundary:
    """Outputs use domain language, not storage vocabulary."""

    def test_no_storage_vocabulary_in_error_messages(self) -> None:
        """Error messages must not leak storage terms.

        Exercised through the Entity declaration gate, which still raises an
        actionable error for undeclared project-specific types. (The kernel
        Task write is ungated and no longer produces an error here.)
        """
        from memorable.core.application import RememberEntityService
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import InMemoryEntityRepository

        no_entity_yaml = textwrap.dedent("""\
            version: 1
            space:
              name: memorable
              description: test
            entities: []
            records: []
        """)
        repo = InMemoryEntityRepository()
        profile = load_profile_from_yaml(no_entity_yaml)
        service = RememberEntityService(repository=repo, profile=profile)

        storage_terms = {
            "node",
            "edge",
            "index",
            "vertex",
            "graph",
            "database",
            "table",
        }

        with pytest.raises(ValueError) as exc_info:
            service.remember(
                space="memorable",
                entity_id="entity:x",
                entity_type="Component",
                name="X",
                source_id=SOURCE_ID,
                at=FIXTURE_TIMESTAMP_REMEMBER,
            )
        message_lower = str(exc_info.value).lower()
        for term in storage_terms:
            assert term not in message_lower, (
                f"Storage vocabulary '{term}' found in error: {exc_info.value}"
            )
