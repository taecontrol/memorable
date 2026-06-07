"""CLI correct --about re-staple behavior tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

SPACE = "memorable"
SOURCE_ID = "source:test"
CORRECTION_SOURCE_ID = "source:human-review"


def _remember_entity(
    main: Callable[[list[str]], int], capsys: Any, entity_id: str
) -> None:
    rc = main(
        [
            "remember",
            "entity",
            "--space",
            SPACE,
            "--id",
            entity_id,
            "--type",
            "Component",
            "--name",
            entity_id.removeprefix("entity:").title(),
            "--source",
            SOURCE_ID,
            "--at",
            "2026-06-07T09:00:00Z",
        ]
    )
    assert rc == 0
    capsys.readouterr()


def _setup_about_entities(main: Callable[[list[str]], int], capsys: Any) -> None:
    for entity_id in (
        "entity:legacy",
        "entity:frontend",
        "entity:backend",
    ):
        _remember_entity(main, capsys, entity_id)


def _remember_record(
    main: Callable[[list[str]], int],
    capsys: Any,
    *,
    record_kind: str,
    record_id: str,
    statement: str,
    about: str,
) -> None:
    rc = main(
        [
            "remember",
            record_kind,
            "--space",
            SPACE,
            "--id",
            record_id,
            "--statement",
            statement,
            "--source",
            SOURCE_ID,
            "--at",
            "2026-06-07T09:01:00Z",
            "--about",
            about,
        ]
    )
    assert rc == 0
    capsys.readouterr()


def _current_statement(ctx: Any, *, record_kind: str, record_id: str) -> str:
    from memorable.core.application import CurrentTruthService

    repository = {
        "decision": ctx.decision_repo,
        "observation": ctx.observation_repo,
    }[record_kind]
    record = CurrentTruthService(repository=repository).current(
        space=SPACE,
        record_id=record_id,
    )
    assert record is not None
    return record.statement


def test_correct_decision_about_restaples_edges(cli_in_memory_context, capsys) -> None:
    """correct --about replaces a Decision's About edges while correcting it."""
    from memorable.cli import main

    ctx = cli_in_memory_context
    record_id = "decision:api-contract"
    _setup_about_entities(main, capsys)
    _remember_record(
        main,
        capsys,
        record_kind="decision",
        record_id=record_id,
        statement="Use the legacy API contract.",
        about="entity:legacy",
    )

    rc = main(
        [
            "correct",
            "--space",
            SPACE,
            "--id",
            record_id,
            "--record-kind",
            "decision",
            "--new-statement",
            "Use the Build 2 API contract.",
            "--source",
            CORRECTION_SOURCE_ID,
            "--at",
            "2026-06-07T09:02:00Z",
            "--about",
            "entity:frontend",
            "--about",
            "entity:backend",
        ]
    )

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["record_id"] == record_id
    assert output["new_statement"] == "Use the Build 2 API contract."
    assert _current_statement(ctx, record_kind="decision", record_id=record_id) == (
        "Use the Build 2 API contract."
    )
    assert ctx.about_repo.entities_for_record(SPACE, record_id) == [
        "entity:backend",
        "entity:frontend",
    ]
    assert ctx.about_repo.records_for_entity(SPACE, "entity:legacy") == []


def test_correct_observation_about_restaples_edges(
    cli_in_memory_context, capsys
) -> None:
    """correct --about replaces an Observation's About edges while correcting it."""
    from memorable.cli import main

    ctx = cli_in_memory_context
    record_id = "observation:api-contract"
    _setup_about_entities(main, capsys)
    _remember_record(
        main,
        capsys,
        record_kind="observation",
        record_id=record_id,
        statement="The legacy API contract warmed up slowly.",
        about="entity:legacy",
    )

    rc = main(
        [
            "correct",
            "--space",
            SPACE,
            "--id",
            record_id,
            "--record-kind",
            "observation",
            "--new-statement",
            "The Build 2 API contract warmed up quickly.",
            "--source",
            CORRECTION_SOURCE_ID,
            "--at",
            "2026-06-07T09:02:00Z",
            "--about",
            "entity:frontend",
            "--about",
            "entity:backend",
        ]
    )

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["record_id"] == record_id
    assert output["new_statement"] == "The Build 2 API contract warmed up quickly."
    assert _current_statement(ctx, record_kind="observation", record_id=record_id) == (
        "The Build 2 API contract warmed up quickly."
    )
    assert ctx.about_repo.entities_for_record(SPACE, record_id) == [
        "entity:backend",
        "entity:frontend",
    ]
    assert ctx.about_repo.records_for_entity(SPACE, "entity:legacy") == []


@pytest.mark.parametrize(
    ("record_kind", "record_id", "old_statement", "new_statement"),
    [
        (
            "decision",
            "decision:missing-about",
            "Use the legacy API contract.",
            "Use the Build 2 API contract.",
        ),
        (
            "observation",
            "observation:missing-about",
            "The legacy API contract warmed up slowly.",
            "The Build 2 API contract warmed up quickly.",
        ),
    ],
)
def test_correct_about_missing_entity_fails_without_changing_record_or_edges(
    cli_in_memory_context,
    capsys,
    record_kind: str,
    record_id: str,
    old_statement: str,
    new_statement: str,
) -> None:
    """correct --about fails loud and changes nothing when any target is missing."""
    from memorable.cli import main

    ctx = cli_in_memory_context
    _setup_about_entities(main, capsys)
    _remember_record(
        main,
        capsys,
        record_kind=record_kind,
        record_id=record_id,
        statement=old_statement,
        about="entity:legacy",
    )

    rc = main(
        [
            "correct",
            "--space",
            SPACE,
            "--id",
            record_id,
            "--record-kind",
            record_kind,
            "--new-statement",
            new_statement,
            "--source",
            CORRECTION_SOURCE_ID,
            "--at",
            "2026-06-07T09:02:00Z",
            "--about",
            "entity:frontend",
            "--about",
            "entity:missing",
        ]
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert "About target Entity 'entity:missing' not found" in err
    assert "Create the Entity before" in err
    assert _current_statement(ctx, record_kind=record_kind, record_id=record_id) == (
        old_statement
    )
    assert ctx.about_repo.entities_for_record(SPACE, record_id) == ["entity:legacy"]
    assert ctx.about_repo.records_for_entity(SPACE, "entity:frontend") == []


@pytest.mark.parametrize(
    ("record_kind", "record_id", "old_statement", "new_statement"),
    [
        (
            "decision",
            "decision:keep-about",
            "Use the legacy API contract.",
            "Use the Build 2 API contract.",
        ),
        (
            "observation",
            "observation:keep-about",
            "The legacy API contract warmed up slowly.",
            "The Build 2 API contract warmed up quickly.",
        ),
    ],
)
def test_correct_without_about_keeps_existing_about_edges(
    cli_in_memory_context,
    capsys,
    record_kind: str,
    record_id: str,
    old_statement: str,
    new_statement: str,
) -> None:
    """correct without --about leaves the record's memberships untouched."""
    from memorable.cli import main

    ctx = cli_in_memory_context
    _setup_about_entities(main, capsys)
    _remember_record(
        main,
        capsys,
        record_kind=record_kind,
        record_id=record_id,
        statement=old_statement,
        about="entity:legacy",
    )

    rc = main(
        [
            "correct",
            "--space",
            SPACE,
            "--id",
            record_id,
            "--record-kind",
            record_kind,
            "--new-statement",
            new_statement,
            "--source",
            CORRECTION_SOURCE_ID,
            "--at",
            "2026-06-07T09:02:00Z",
        ]
    )

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["record_id"] == record_id
    assert output["new_statement"] == new_statement
    assert _current_statement(ctx, record_kind=record_kind, record_id=record_id) == (
        new_statement
    )
    assert ctx.about_repo.entities_for_record(SPACE, record_id) == ["entity:legacy"]


def test_correct_about_still_requires_new_statement(capsys) -> None:
    """correct --about without --new-statement is rejected by the CLI parser."""
    from memorable.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "correct",
                "--space",
                SPACE,
                "--id",
                "decision:about-only",
                "--record-kind",
                "decision",
                "--source",
                CORRECTION_SOURCE_ID,
                "--at",
                "2026-06-07T09:02:00Z",
                "--about",
                "entity:frontend",
            ]
        )

    assert exc_info.value.code == 2
    assert "--new-statement" in capsys.readouterr().err


def test_correct_about_help_teaches_membership_not_relation_claim(capsys) -> None:
    """correct --about help uses the authoritative About framing."""
    from memorable.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main(["correct", "--help"])

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    normalized_help = " ".join(help_text.split())
    assert "--about" in help_text
    assert "About is membership, not a Relation claim" in normalized_help
    assert "create the Entity first" in normalized_help
