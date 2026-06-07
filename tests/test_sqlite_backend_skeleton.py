from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


def _write_sqlite_workspace(path: Path) -> None:
    memorable_dir = path / ".memorable"
    memorable_dir.mkdir()
    (memorable_dir / "runtime.yaml").write_text(
        "storage:\n"
        "  backend: sqlite\n"
        "sqlite:\n"
        "  path: .memorable/memory.db\n"
        "embeddings:\n"
        "  provider: fake\n"
        "  dimensions: 32\n",
        encoding="utf-8",
    )
    (memorable_dir / "memory.yaml").write_text(
        "version: 1\n"
        "space:\n"
        "  name: sqlite-project\n"
        "  description: SQLite skeleton test\n"
        "entities:\n"
        "  - name: Component\n"
        "relations:\n"
        "  - name: depends-on\n"
        "    description: Component dependency.\n",
        encoding="utf-8",
    )


def _run_without_neo4j(argv: list[str]) -> int:
    from memorable.cli import main

    with patch(
        "memorable.storage.neo4j.connection.GraphDatabase.driver",
        side_effect=AssertionError("Neo4j must not be used by SQLite backend"),
    ):
        return main(argv)


def test_cli_remember_entity_with_sqlite_writes_file_and_reads_back(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_sqlite_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    remember_rc = _run_without_neo4j(
        [
            "remember",
            "entity",
            "--id",
            "entity:sqlite",
            "--type",
            "Component",
            "--name",
            "SQLite Adapter",
            "--source",
            "source:test",
            "--at",
            "2026-06-07T09:00:00Z",
        ]
    )

    assert remember_rc == 0
    remembered = json.loads(capsys.readouterr().out)
    assert remembered["entity_id"] == "entity:sqlite"
    assert (tmp_path / ".memorable" / "memory.db").exists()

    inspect_rc = _run_without_neo4j(["inspect", "provenance", "--id", "entity:sqlite"])

    assert inspect_rc == 0
    inspected = capsys.readouterr().out
    assert "Provenance for entity:sqlite" in inspected
    assert "source:test" in inspected


def test_cli_sqlite_observation_list_and_task_completion(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_sqlite_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert (
        _run_without_neo4j(
            [
                "remember",
                "observation",
                "--id",
                "observation:sqlite",
                "--statement",
                "SQLite stores Observations.",
                "--source",
                "source:test",
                "--at",
                "2026-06-07T09:00:00Z",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert _run_without_neo4j(["list", "--record-kind", "observation"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [record["id"] for record in listed["records"]] == ["observation:sqlite"]

    assert (
        _run_without_neo4j(
            [
                "remember",
                "task",
                "--id",
                "task:sqlite",
                "--title",
                "Finish SQLite typed records.",
                "--source",
                "source:test",
                "--at",
                "2026-06-07T10:00:00Z",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        _run_without_neo4j(
            [
                "complete",
                "task",
                "--id",
                "task:sqlite",
                "--at",
                "2026-06-08T10:00:00Z",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert _run_without_neo4j(["task", "inspect", "--id", "task:sqlite"]) == 0
    task = json.loads(capsys.readouterr().out)
    assert task["lifecycle_state"] == "completed"
    assert task["completion_event_id"] == "event:complete-task:sqlite"


def test_cli_sqlite_remember_decision_about_and_list_review_filter(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_sqlite_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    for entity_id, name in [
        ("entity:frontend", "Frontend"),
        ("entity:backend", "Backend"),
    ]:
        assert (
            _run_without_neo4j(
                [
                    "remember",
                    "entity",
                    "--id",
                    entity_id,
                    "--type",
                    "Component",
                    "--name",
                    name,
                    "--source",
                    "source:test",
                    "--at",
                    "2026-06-07T09:00:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

    assert (
        _run_without_neo4j(
            [
                "remember",
                "decision",
                "--id",
                "decision:about-sqlite",
                "--statement",
                "SQLite About links work.",
                "--source",
                "source:test",
                "--at",
                "2026-06-07T10:00:00Z",
                "--about",
                "entity:frontend",
            ]
        )
        == 0
    )
    remembered = json.loads(capsys.readouterr().out)
    assert remembered["decision_id"] == "decision:about-sqlite"

    assert _run_without_neo4j(["list", "--about", "entity:frontend"]) == 0
    frontend_records = json.loads(capsys.readouterr().out)
    assert [record["id"] for record in frontend_records["records"]] == [
        "decision:about-sqlite"
    ]

    assert _run_without_neo4j(["list", "--about", "entity:backend"]) == 0
    backend_records = json.loads(capsys.readouterr().out)
    assert backend_records["records"] == []


def test_cli_sqlite_remember_relation_and_list_review(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_sqlite_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    for entity_id, name in [
        ("entity:source", "Source"),
        ("entity:target", "Target"),
    ]:
        assert (
            _run_without_neo4j(
                [
                    "remember",
                    "entity",
                    "--id",
                    entity_id,
                    "--type",
                    "Component",
                    "--name",
                    name,
                    "--source",
                    "source:test",
                    "--at",
                    "2026-06-07T09:00:00Z",
                ]
            )
            == 0
        )
        capsys.readouterr()

    assert (
        _run_without_neo4j(
            [
                "remember",
                "relation",
                "--id",
                "relation:sqlite",
                "--source-entity-id",
                "entity:source",
                "--target-entity-id",
                "entity:target",
                "--relation-type",
                "depends-on",
                "--statement",
                "Source depends on Target.",
                "--source",
                "source:test",
                "--at",
                "2026-06-07T10:00:00Z",
            ]
        )
        == 0
    )
    remembered = json.loads(capsys.readouterr().out)
    assert remembered["relation_id"] == "relation:sqlite"
    assert remembered["source_entity_id"] == "entity:source"
    assert remembered["target_entity_id"] == "entity:target"

    assert _run_without_neo4j(["list", "--record-kind", "relation"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [record["id"] for record in listed["records"]] == ["relation:sqlite"]


def test_cli_sqlite_decision_supersession_reads_current_as_of_and_history(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_sqlite_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert (
        _run_without_neo4j(
            [
                "remember",
                "decision",
                "--id",
                "decision:old",
                "--statement",
                "Use Neo4j only.",
                "--source",
                "source:test",
                "--at",
                "2026-06-07T09:00:00Z",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        _run_without_neo4j(
            [
                "remember",
                "decision",
                "--id",
                "decision:new",
                "--statement",
                "SQLite is selectable.",
                "--source",
                "source:test",
                "--at",
                "2026-06-08T09:00:00Z",
                "--supersedes",
                "decision:old",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert _run_without_neo4j(["truth", "current", "--id", "decision:old"]) == 0
    current = json.loads(capsys.readouterr().out)
    assert current["decision_id"] == "decision:new"

    assert (
        _run_without_neo4j(
            [
                "truth",
                "as-of",
                "--id",
                "decision:old",
                "--at",
                "2026-06-09T09:00:00Z",
            ]
        )
        == 0
    )
    as_of = json.loads(capsys.readouterr().out)
    assert as_of["decision_id"] == "decision:new"

    assert _run_without_neo4j(["inspect", "history", "--id", "decision:old"]) == 0
    history = capsys.readouterr().out
    assert "decision:old" in history
    assert "decision:new" in history

    assert (
        _run_without_neo4j(["list", "--record-kind", "decision", "--limit", "1"]) == 0
    )
    listed = json.loads(capsys.readouterr().out)
    assert [record["id"] for record in listed["records"]] == ["decision:old"]
