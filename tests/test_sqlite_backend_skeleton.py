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
        "  - name: Component\n",
        encoding="utf-8",
    )


def test_cli_remember_entity_with_sqlite_writes_file_and_reads_back(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from memorable.cli import main

    _write_sqlite_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    with patch(
        "memorable.storage.neo4j.connection.GraphDatabase.driver",
        side_effect=AssertionError("Neo4j must not be used by SQLite backend"),
    ):
        remember_rc = main(
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

    with patch(
        "memorable.storage.neo4j.connection.GraphDatabase.driver",
        side_effect=AssertionError("Neo4j must not be used by SQLite backend"),
    ):
        inspect_rc = main(["inspect", "provenance", "--id", "entity:sqlite"])

    assert inspect_rc == 0
    inspected = capsys.readouterr().out
    assert "Provenance for entity:sqlite" in inspected
    assert "source:test" in inspected
