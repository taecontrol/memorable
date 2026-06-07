from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

PROFILE_YAML = """\
version: 1
space:
  name: memorable
entities:
  - name: Project
  - name: Component
relations:
  - name: depends-on
records:
  - name: ArchitectureDecision
    extends: Decision
  - name: GeneralObservation
    extends: Observation
  - name: FollowUp
    extends: Task
"""

VALIDITY_TIME = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)
CORRECTION_VALIDITY_TIME = datetime(2026, 5, 2, 10, 0, 0, tzinfo=UTC)
CREATION_TIME = datetime(2026, 6, 7, 12, 0, 0, 123456, tzinfo=UTC)
CORRECTION_CREATION_TIME = datetime(2026, 6, 8, 13, 0, 0, 654321, tzinfo=UTC)
SOURCE_ID = "source:test"
CORRECTION_SOURCE_ID = "source:correction"
SPACE = "memorable"


def _profile():
    from memorable.core.profile import load_profile_from_yaml

    return load_profile_from_yaml(PROFILE_YAML)


def _write_profile(workspace: Path) -> None:
    memory_dir = workspace / ".memorable"
    memory_dir.mkdir()
    (memory_dir / "memory.yaml").write_text(PROFILE_YAML, encoding="utf-8")


def test_remember_decision_separates_creation_time_from_validity_time() -> None:
    from memorable.core.application import RememberDecisionService
    from memorable.core.clock import FixedClock
    from memorable.core.repositories import InMemoryDecisionRepository

    service = RememberDecisionService(
        repository=InMemoryDecisionRepository(),
        profile=_profile(),
        clock=FixedClock(CREATION_TIME),
    )

    result = service.remember(
        space=SPACE,
        decision_id="decision:backdated",
        statement="Backdated decision.",
        source_id=SOURCE_ID,
        at=VALIDITY_TIME,
    )

    assert result.provenance.creation_time == CREATION_TIME
    assert result.provenance.validity_time == VALIDITY_TIME
    assert result.provenance.creation_time != result.provenance.validity_time
    assert result.decision.validity_time == VALIDITY_TIME


def test_remember_entity_separates_creation_time_from_validity_time() -> None:
    from memorable.core.application import RememberEntityService
    from memorable.core.clock import FixedClock
    from memorable.core.repositories import InMemoryEntityRepository

    service = RememberEntityService(
        repository=InMemoryEntityRepository(),
        profile=_profile(),
        clock=FixedClock(CREATION_TIME),
    )

    result = service.remember(
        space=SPACE,
        entity_id="entity:backdated",
        entity_type="Project",
        name="Backdated Entity",
        source_id=SOURCE_ID,
        at=VALIDITY_TIME,
    )

    assert result.provenance.creation_time == CREATION_TIME
    assert result.provenance.validity_time == VALIDITY_TIME
    assert result.provenance.creation_time != result.provenance.validity_time


def test_remember_observation_separates_creation_time_from_validity_time() -> None:
    from memorable.core.application import RememberObservationService
    from memorable.core.clock import FixedClock
    from memorable.core.repositories import InMemoryObservationRepository

    service = RememberObservationService(
        repository=InMemoryObservationRepository(),
        profile=_profile(),
        clock=FixedClock(CREATION_TIME),
    )

    result = service.remember(
        space=SPACE,
        observation_id="observation:backdated",
        statement="Backdated observation.",
        source_id=SOURCE_ID,
        at=VALIDITY_TIME,
    )

    assert result.provenance.creation_time == CREATION_TIME
    assert result.provenance.validity_time == VALIDITY_TIME
    assert result.provenance.creation_time != result.provenance.validity_time


def test_remember_task_separates_creation_time_from_validity_time() -> None:
    from memorable.core.application import RememberTaskService
    from memorable.core.clock import FixedClock
    from memorable.core.repositories import InMemoryTaskRepository

    service = RememberTaskService(
        repository=InMemoryTaskRepository(),
        profile=_profile(),
        clock=FixedClock(CREATION_TIME),
    )

    result = service.remember(
        space=SPACE,
        task_id="task:backdated",
        title="Backdated task.",
        source_id=SOURCE_ID,
        at=VALIDITY_TIME,
    )

    assert result.provenance.creation_time == CREATION_TIME
    assert result.provenance.validity_time == VALIDITY_TIME
    assert result.provenance.creation_time != result.provenance.validity_time
    assert result.task.validity_time == VALIDITY_TIME


def test_remember_relation_separates_creation_time_from_validity_time() -> None:
    from memorable.core.application import (
        RememberEntityService,
        RememberRelationService,
    )
    from memorable.core.clock import FixedClock
    from memorable.core.repositories import (
        InMemoryEntityRepository,
        InMemoryRelationRepository,
    )

    entity_repo = InMemoryEntityRepository()
    relation_repo = InMemoryRelationRepository()
    profile = _profile()
    entity_service = RememberEntityService(
        repository=entity_repo,
        profile=profile,
        clock=FixedClock(CREATION_TIME),
    )
    for entity_id in ("entity:source", "entity:target"):
        entity_service.remember(
            space=SPACE,
            entity_id=entity_id,
            entity_type="Component",
            name=entity_id,
            source_id=SOURCE_ID,
            at=VALIDITY_TIME,
        )
    relation_service = RememberRelationService(
        relation_repo=relation_repo,
        entity_repo=entity_repo,
        profile=profile,
        clock=FixedClock(CREATION_TIME),
    )

    result = relation_service.remember(
        space=SPACE,
        relation_id="relation:backdated",
        source_entity_id="entity:source",
        target_entity_id="entity:target",
        relation_type="depends-on",
        statement="Source depends on target.",
        source_id=SOURCE_ID,
        at=VALIDITY_TIME,
    )

    assert result.provenance.creation_time == CREATION_TIME
    assert result.provenance.validity_time == VALIDITY_TIME
    assert result.provenance.creation_time != result.provenance.validity_time
    assert result.relation.validity_time == VALIDITY_TIME


def test_correct_record_separates_creation_time_from_validity_time() -> None:
    from memorable.core.application import (
        CorrectService,
        CurrentTruthService,
        RememberDecisionService,
    )
    from memorable.core.clock import FixedClock
    from memorable.core.repositories import InMemoryDecisionRepository

    repo = InMemoryDecisionRepository()
    remember = RememberDecisionService(
        repository=repo,
        profile=_profile(),
        clock=FixedClock(CREATION_TIME),
    )
    remember.remember(
        space=SPACE,
        decision_id="decision:corrected",
        statement="Old statement.",
        source_id=SOURCE_ID,
        at=VALIDITY_TIME,
    )
    correct = CorrectService(
        repository=repo,
        clock=FixedClock(CORRECTION_CREATION_TIME),
    )

    correct.correct(
        space=SPACE,
        record_id="decision:corrected",
        new_statement="Corrected statement.",
        record_kind="decision",
        source=CORRECTION_SOURCE_ID,
        writer="human:reviewer",
        at=CORRECTION_VALIDITY_TIME,
    )

    current = CurrentTruthService(repository=repo).current(
        space=SPACE,
        record_id="decision:corrected",
    )
    provenance = repo.get_provenance(space=SPACE, record_id="decision:corrected")

    assert current is not None
    assert current.statement == "Corrected statement."
    assert provenance is not None
    assert provenance.creation_time == CORRECTION_CREATION_TIME
    assert provenance.validity_time == CORRECTION_VALIDITY_TIME
    assert provenance.creation_time != provenance.validity_time


def test_memory_review_since_until_windows_on_creation_time_not_validity_time() -> None:
    from datetime import timedelta

    from memorable.core.application import ListRecordsService, RememberDecisionService
    from memorable.core.clock import FixedClock
    from memorable.core.repositories import (
        InMemoryDecisionRepository,
        InMemoryObservationRepository,
        InMemoryRelationRepository,
        InMemoryTaskRepository,
    )

    decision_repo = InMemoryDecisionRepository()
    RememberDecisionService(
        repository=decision_repo,
        profile=_profile(),
        clock=FixedClock(CREATION_TIME),
    ).remember(
        space=SPACE,
        decision_id="decision:review-window",
        statement="Backdated decision written now.",
        source_id=SOURCE_ID,
        at=VALIDITY_TIME,
    )
    service = ListRecordsService(
        decision_repo=decision_repo,
        observation_repo=InMemoryObservationRepository(),
        relation_repo=InMemoryRelationRepository(),
        task_repo=InMemoryTaskRepository(),
    )

    now_window = service.list_records(
        space=SPACE,
        since=CREATION_TIME - timedelta(seconds=1),
        until=CREATION_TIME + timedelta(seconds=1),
    )
    validity_window = service.list_records(
        space=SPACE,
        since=VALIDITY_TIME - timedelta(seconds=1),
        until=VALIDITY_TIME + timedelta(seconds=1),
    )

    assert [projection.id for projection in now_window] == ["decision:review-window"]
    assert now_window[0].creation_time == CREATION_TIME
    assert validity_window == []


def test_correct_task_separates_creation_time_from_validity_time() -> None:
    from memorable.core.application import (
        AboutLinker,
        CorrectTaskService,
        InspectTaskService,
        RememberEntityService,
        RememberTaskService,
    )
    from memorable.core.clock import FixedClock
    from memorable.core.repositories import (
        InMemoryAboutRepository,
        InMemoryEntityRepository,
        InMemoryTaskRepository,
    )

    entity_repo = InMemoryEntityRepository()
    about_repo = InMemoryAboutRepository()
    task_repo = InMemoryTaskRepository()
    profile = _profile()
    linker = AboutLinker(entity_repo=entity_repo, about_repo=about_repo)
    RememberEntityService(
        repository=entity_repo,
        profile=profile,
        clock=FixedClock(CREATION_TIME),
    ).remember(
        space=SPACE,
        entity_id="entity:task-target",
        entity_type="Project",
        name="Task Target",
        source_id=SOURCE_ID,
        at=VALIDITY_TIME,
    )
    RememberTaskService(
        repository=task_repo,
        profile=profile,
        about_linker=linker,
        clock=FixedClock(CREATION_TIME),
    ).remember(
        space=SPACE,
        task_id="task:corrected",
        title="Backdated task.",
        source_id=SOURCE_ID,
        at=VALIDITY_TIME,
        about=["entity:task-target"],
    )
    correct = CorrectTaskService(
        repository=task_repo,
        about_linker=linker,
        clock=FixedClock(CORRECTION_CREATION_TIME),
    )

    correct.correct(
        space=SPACE,
        task_id="task:corrected",
        new_statement="Backdated task.",
        source=CORRECTION_SOURCE_ID,
        writer="human:reviewer",
        at=CORRECTION_VALIDITY_TIME,
        about=["entity:task-target"],
    )

    task = InspectTaskService(repository=task_repo).inspect(
        space=SPACE,
        task_id="task:corrected",
    )
    provenance = task_repo.get_provenance(space=SPACE, task_id="task:corrected")

    assert task is not None
    assert task.title == "Backdated task."
    assert provenance is not None
    assert provenance.creation_time == CORRECTION_CREATION_TIME
    assert provenance.validity_time == CORRECTION_VALIDITY_TIME
    assert provenance.creation_time != provenance.validity_time


def test_cli_remember_decision_uses_system_clock_for_creation_time(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main
    from memorable.config import EmbeddingSettings, RuntimeConfig
    from memorable.core.clock import FixedClock
    from memorable.core.context import ApplicationContext

    _write_profile(tmp_path)
    ctx = ApplicationContext()
    driver = MagicMock()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "memorable.cli.SystemClock",
        lambda: FixedClock(CREATION_TIME),
    )

    with (
        patch("memorable.cli.build_production_context", return_value=(ctx, driver)),
        patch(
            "memorable.cli.load_runtime_config",
            return_value=RuntimeConfig(
                embeddings=EmbeddingSettings(provider="fake", dimensions=32),
            ),
        ),
    ):
        rc = main(
            [
                "remember",
                "decision",
                "--id",
                "decision:cli-clock",
                "--statement",
                "CLI writes Creation Time from clock.",
                "--source",
                SOURCE_ID,
                "--at",
                VALIDITY_TIME.isoformat(),
            ]
        )

    output = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert output["creation_time"] == CREATION_TIME.isoformat()
    assert output["validity_time"] == VALIDITY_TIME.isoformat()
    assert output["creation_time"] != output["validity_time"]


def test_mcp_remember_decision_uses_system_clock_for_creation_time(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from memorable.config import EmbeddingSettings, RuntimeConfig
    from memorable.core.clock import FixedClock
    from memorable.core.context import ApplicationContext, default_context
    from memorable.mcp.server import (
        remember_decision_tool,
        set_mcp_context,
    )

    _write_profile(tmp_path)
    ctx = ApplicationContext()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "memorable.mcp.server.SystemClock",
        lambda: FixedClock(CREATION_TIME),
    )
    monkeypatch.setattr(
        "memorable.mcp.server.load_runtime_config",
        lambda **_: RuntimeConfig(
            embeddings=EmbeddingSettings(provider="fake", dimensions=32),
        ),
    )
    set_mcp_context(ctx)

    try:
        result = remember_decision_tool(
            space=SPACE,
            decision_id="decision:mcp-clock",
            statement="MCP writes Creation Time from clock.",
            source=SOURCE_ID,
            at=VALIDITY_TIME.isoformat(),
        )
    finally:
        set_mcp_context(default_context)

    assert "error" not in result
    assert result["creation_time"] == CREATION_TIME.isoformat()
    assert result["validity_time"] == VALIDITY_TIME.isoformat()
    assert result["creation_time"] != result["validity_time"]
