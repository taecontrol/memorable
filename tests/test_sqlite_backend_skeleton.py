from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


def _pythonpath_env() -> dict[str, str]:
    env = os.environ.copy()
    src_path = str(PROJECT_ROOT / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        src_path if not existing else f"{src_path}{os.pathsep}{existing}"
    )
    return env


def _run_cli_process(
    workspace: Path,
    argv: list[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "memorable.cli", *argv],
        cwd=workspace,
        env=_pythonpath_env(),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_cli_sqlite_writer_succeeds_while_mcp_shaped_reader_holds_read(
    tmp_path: Path,
) -> None:
    from memorable.config import load_runtime_config
    from memorable.storage.production import build_production_context

    _write_sqlite_workspace(tmp_path)
    seed = _run_cli_process(
        tmp_path,
        [
            "remember",
            "entity",
            "--id",
            "entity:mcp-reader",
            "--type",
            "Component",
            "--name",
            "MCP Reader",
            "--source",
            "source:test",
            "--at",
            "2026-06-07T09:00:00Z",
        ],
    )
    assert seed.returncode == 0, seed.stderr

    config = load_runtime_config(
        base_path=tmp_path,
        include_environment_overrides=True,
    )
    ctx, resource = build_production_context(config)
    ready = threading.Event()
    release = threading.Event()
    reader_results: queue.Queue[tuple[str, object, object]] = queue.Queue()

    def _mcp_shaped_reader() -> None:
        try:
            resource.connection.execute("BEGIN")
            existing = ctx.entity_repo.get("sqlite-project", "entity:mcp-reader")
            if existing is None:
                raise AssertionError("MCP-shaped reader did not see seeded Entity")
            ready.set()
            if not release.wait(timeout=10):
                raise AssertionError("CLI writer did not finish before timeout")
            resource.connection.execute("COMMIT")
            written = ctx.entity_repo.get("sqlite-project", "entity:cli-writer")
            reader_results.put(("ok", written is not None, ""))
        except Exception as exc:
            reader_results.put(("error", type(exc).__name__, str(exc)))
            ready.set()

    reader = threading.Thread(target=_mcp_shaped_reader, daemon=True)
    try:
        reader.start()
        assert ready.wait(timeout=5), "MCP-shaped reader did not start"
        if not reader_results.empty():
            assert reader_results.get_nowait() == ("ok", True, "")

        writer = _run_cli_process(
            tmp_path,
            [
                "remember",
                "entity",
                "--id",
                "entity:cli-writer",
                "--type",
                "Component",
                "--name",
                "CLI Writer",
                "--source",
                "source:test",
                "--at",
                "2026-06-07T10:00:00Z",
            ],
        )
        assert writer.returncode == 0, writer.stderr

        release.set()
        reader.join(timeout=5)
        assert not reader.is_alive(), "MCP-shaped reader did not finish"
        assert reader_results.get(timeout=1) == ("ok", True, "")
    finally:
        release.set()
        reader.join(timeout=5)
        resource.close()


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


def test_cli_sqlite_forget_entity_cascades_relation_and_about(
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
                "relation:forgotten-with-source",
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
    capsys.readouterr()
    assert (
        _run_without_neo4j(
            [
                "remember",
                "decision",
                "--id",
                "decision:about-forgotten-source",
                "--statement",
                "Source can be forgotten.",
                "--source",
                "source:test",
                "--at",
                "2026-06-07T11:00:00Z",
                "--about",
                "entity:source",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        _run_without_neo4j(
            [
                "forget",
                "--target-type",
                "entity",
                "--id",
                "entity:source",
            ]
        )
        == 0
    )
    forgotten = json.loads(capsys.readouterr().out)
    assert forgotten["record_id"] == "entity:source"
    assert forgotten["record_kind"] == "entity"

    assert _run_without_neo4j(["list", "--record-kind", "relation"]) == 0
    relations = json.loads(capsys.readouterr().out)
    assert relations["records"] == []

    assert _run_without_neo4j(["list", "--about", "entity:source"]) == 0
    about_source = json.loads(capsys.readouterr().out)
    assert about_source["records"] == []

    assert (
        _run_without_neo4j(
            [
                "forget",
                "--target-type",
                "entity",
                "--id",
                "entity:source",
            ]
        )
        == 1
    )
    assert "Nothing to forget" in capsys.readouterr().err

    assert _run_without_neo4j(["inspect", "provenance", "--id", "entity:target"]) == 0
    assert "Provenance for entity:target" in capsys.readouterr().out


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
