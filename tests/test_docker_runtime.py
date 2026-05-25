"""Tests for the Docker runtime module.

Covers:
- start() invokes correct docker compose command with env vars from config
- stop() invokes correct docker compose down command
- status() returns container state (running, stopped, not found)
- eject() copies template to the correct location
- Remote URI detection skips container operations
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from memorable.config import DockerSettings, Neo4jSettings, RuntimeConfig
from memorable.runtime.docker import (
    ContainerState,
    eject,
    is_remote_uri,
    start,
    status,
    stop,
)


class TestDockerStart:
    """start() invokes docker compose up with env vars from config."""

    def test_start_invokes_docker_compose_up(self) -> None:
        config = RuntimeConfig()

        with patch("memorable.runtime.docker.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            result = start(config)

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd[0:2] == ["docker", "compose"]
        assert "-f" in cmd
        assert "up" in cmd
        assert "-d" in cmd
        assert result.success is True

    def test_start_passes_env_vars_from_config(self) -> None:
        config = RuntimeConfig(
            neo4j=Neo4jSettings(password="secret123"),
            docker=DockerSettings(
                neo4j_version="5.20",
                http_port=17474,
                bolt_port=17687,
            ),
        )

        with patch("memorable.runtime.docker.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            start(config)

        call_args = mock_run.call_args
        env = call_args[1].get("env") or call_args.kwargs.get("env")
        assert env["NEO4J_VERSION"] == "5.20"
        assert env["NEO4J_HTTP_PORT"] == "17474"
        assert env["NEO4J_BOLT_PORT"] == "17687"
        assert env["NEO4J_PASSWORD"] == "secret123"

    def test_start_uses_packaged_compose_template(self) -> None:
        config = RuntimeConfig()

        with patch("memorable.runtime.docker.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            start(config)

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        f_index = cmd.index("-f")
        compose_path = Path(cmd[f_index + 1])
        assert compose_path.name == "docker-compose.yml"
        assert compose_path.exists()


class TestDockerStop:
    """stop() invokes docker compose down."""

    def test_stop_invokes_docker_compose_down(self) -> None:
        config = RuntimeConfig()

        with patch("memorable.runtime.docker.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            result = stop(config)

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd[0:2] == ["docker", "compose"]
        assert "-f" in cmd
        assert "down" in cmd
        assert result.success is True

    def test_stop_reports_failure(self) -> None:
        config = RuntimeConfig()

        with patch("memorable.runtime.docker.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "no such container"
            result = stop(config)

        assert result.success is False
        assert "no such container" in result.message


class TestDockerStatus:
    """status() returns container state."""

    def test_status_returns_running_when_container_is_up(self) -> None:
        config = RuntimeConfig()

        with patch("memorable.runtime.docker.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "running\n"
            result = status(config)

        assert result == ContainerState.RUNNING

    def test_status_returns_stopped_when_container_exited(self) -> None:
        config = RuntimeConfig()

        with patch("memorable.runtime.docker.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "exited\n"
            result = status(config)

        assert result == ContainerState.STOPPED

    def test_status_returns_not_found_when_no_container(self) -> None:
        config = RuntimeConfig()

        with patch("memorable.runtime.docker.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            result = status(config)

        assert result == ContainerState.NOT_FOUND


class TestDockerEject:
    """eject() copies compose template to target directory."""

    def test_eject_copies_template_to_target(self, tmp_path: Path) -> None:
        target_dir = tmp_path / ".memorable"
        result = eject(target_dir)

        assert result.success is True
        dest = target_dir / "docker-compose.yml"
        assert dest.exists()
        content = dest.read_text()
        assert "neo4j" in content

    def test_eject_creates_target_directory(self, tmp_path: Path) -> None:
        target_dir = tmp_path / ".memorable"
        assert not target_dir.exists()

        eject(target_dir)

        assert target_dir.exists()

    def test_eject_refuses_to_overwrite_existing(self, tmp_path: Path) -> None:
        target_dir = tmp_path / ".memorable"
        target_dir.mkdir()
        (target_dir / "docker-compose.yml").write_text("custom content")

        result = eject(target_dir)

        assert result.success is False
        assert "already exists" in result.message
        # Original content preserved
        assert (target_dir / "docker-compose.yml").read_text() == "custom content"


class TestRemoteUriDetection:
    """is_remote_uri() detects non-local Neo4j URIs."""

    def test_localhost_bolt_is_local(self) -> None:
        assert is_remote_uri("bolt://localhost:7687") is False

    def test_localhost_127_is_local(self) -> None:
        assert is_remote_uri("bolt://127.0.0.1:7687") is False

    def test_neo4j_plus_s_is_remote(self) -> None:
        assert is_remote_uri("neo4j+s://cloud.neo4j.io:7687") is True

    def test_neo4j_plus_ssc_is_remote(self) -> None:
        assert is_remote_uri("neo4j+ssc://cloud.neo4j.io:7687") is True

    def test_non_localhost_bolt_is_remote(self) -> None:
        assert is_remote_uri("bolt://prod-server:7687") is True

    def test_neo4j_scheme_localhost_is_local(self) -> None:
        assert is_remote_uri("neo4j://localhost:7687") is False

    def test_neo4j_scheme_remote_host_is_remote(self) -> None:
        assert is_remote_uri("neo4j://db.example.com:7687") is True
