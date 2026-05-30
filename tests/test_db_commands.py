"""Tests for memorable db start/stop/eject CLI subcommands.

Covers:
- memorable db start works with zero config files (built-in defaults)
- memorable db stop delegates to stop()
- memorable db start/stop detect remote URIs and report
- memorable db eject creates .memorable/docker-compose.yml
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from memorable.cli import main

pytestmark = pytest.mark.usefixtures("clean_memorable_environment")


class TestDbStart:
    """memorable db start delegates to docker runtime start()."""

    def test_start_with_zero_config(self, tmp_path: Path, capsys) -> None:
        with patch("memorable.runtime.docker.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            result = main(["db", "start", "--path", str(tmp_path)])

        assert result == 0
        captured = capsys.readouterr()
        assert "Neo4j container started" in captured.out

    def test_start_reports_failure(self, tmp_path: Path, capsys) -> None:
        with patch("memorable.runtime.docker.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "Cannot connect to Docker daemon"
            result = main(["db", "start", "--path", str(tmp_path)])

        assert result == 1
        captured = capsys.readouterr()
        assert "Cannot connect to Docker daemon" in captured.err


class TestDbStop:
    """memorable db stop delegates to docker runtime stop()."""

    def test_stop_with_default_config(self, tmp_path: Path, capsys) -> None:
        with patch("memorable.runtime.docker.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            result = main(["db", "stop", "--path", str(tmp_path)])

        assert result == 0
        captured = capsys.readouterr()
        assert "Neo4j container stopped" in captured.out

    def test_stop_reports_failure(self, tmp_path: Path, capsys) -> None:
        with patch("memorable.runtime.docker.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "no such container"
            result = main(["db", "stop", "--path", str(tmp_path)])

        assert result == 1
        captured = capsys.readouterr()
        assert "no such container" in captured.err


class TestDbRemoteUriDetection:
    """memorable db start/stop detect remote URIs and report."""

    def _write_remote_config(self, tmp_path: Path, uri: str) -> None:
        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / "runtime.yaml").write_text(f"neo4j:\n  uri: {uri}\n")

    def test_start_detects_neo4j_plus_s(self, tmp_path: Path, capsys) -> None:
        self._write_remote_config(tmp_path, "neo4j+s://cloud.neo4j.io:7687")

        result = main(["db", "start", "--path", str(tmp_path)])

        assert result == 1
        captured = capsys.readouterr()
        assert "remote Neo4j" in captured.err

    def test_stop_detects_neo4j_plus_s(self, tmp_path: Path, capsys) -> None:
        self._write_remote_config(tmp_path, "neo4j+s://cloud.neo4j.io:7687")

        result = main(["db", "stop", "--path", str(tmp_path)])

        assert result == 1
        captured = capsys.readouterr()
        assert "remote Neo4j" in captured.err

    def test_start_detects_non_localhost_bolt(self, tmp_path: Path, capsys) -> None:
        self._write_remote_config(tmp_path, "bolt://prod-server:7687")

        result = main(["db", "start", "--path", str(tmp_path)])

        assert result == 1
        captured = capsys.readouterr()
        assert "remote Neo4j" in captured.err

    def test_start_allows_localhost(self, tmp_path: Path, capsys) -> None:
        self._write_remote_config(tmp_path, "bolt://localhost:7687")

        with patch("memorable.runtime.docker.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            result = main(["db", "start", "--path", str(tmp_path)])

        assert result == 0


class TestDbEject:
    """memorable db eject copies compose template to .memorable/."""

    def test_eject_creates_compose_file(self, tmp_path: Path, capsys) -> None:
        result = main(["db", "eject", "--path", str(tmp_path)])

        assert result == 0
        dest = tmp_path / ".memorable" / "docker-compose.yml"
        assert dest.exists()
        captured = capsys.readouterr()
        assert "Compose template copied" in captured.out

    def test_eject_refuses_overwrite(self, tmp_path: Path, capsys) -> None:
        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / "docker-compose.yml").write_text("custom")

        result = main(["db", "eject", "--path", str(tmp_path)])

        assert result == 1
        captured = capsys.readouterr()
        assert "already exists" in captured.err

    def test_eject_uses_cwd_when_no_path(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        result = main(["db", "eject"])

        assert result == 0
        assert (tmp_path / ".memorable" / "docker-compose.yml").exists()
