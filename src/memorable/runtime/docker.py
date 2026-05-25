"""Docker Compose operations for managing a local Neo4j container.

Encapsulates docker compose up/down/status so the rest of Memorable
never touches Docker directly. Ships a default docker-compose.yml
as package data.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

from memorable.config import RuntimeConfig

_TEMPLATE_PATH = Path(__file__).parent / "docker-compose.yml"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class ContainerState(Enum):
    """State of the Neo4j Docker container."""

    RUNNING = "running"
    STOPPED = "stopped"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class DockerResult:
    """Outcome of a Docker runtime operation."""

    success: bool
    message: str


def is_remote_uri(uri: str) -> bool:
    """Return True if the Neo4j URI points to a non-local server.

    Schemes neo4j+s:// and neo4j+ssc:// are always remote (TLS-encrypted
    cloud connections). For bolt:// and neo4j://, the host must be
    localhost or 127.0.0.1 to be considered local.
    """
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()
    if scheme in ("neo4j+s", "neo4j+ssc"):
        return True
    host = (parsed.hostname or "").lower()
    return host not in _LOCAL_HOSTS


def _compose_env(config: RuntimeConfig) -> dict[str, str]:
    """Build environment variables for the docker compose template."""
    env = dict(os.environ)
    env["NEO4J_VERSION"] = config.docker.neo4j_version
    env["NEO4J_HTTP_PORT"] = str(config.docker.http_port)
    env["NEO4J_BOLT_PORT"] = str(config.docker.bolt_port)
    env["NEO4J_PASSWORD"] = config.neo4j.password
    return env


def resolve_compose_file(project_dir: Path | None = None) -> Path:
    """Return the compose file to use.

    If *project_dir* is provided and an ejected
    ``.memorable/docker-compose.yml`` exists there, prefer it.
    Otherwise fall back to the packaged template.
    """
    if project_dir is not None:
        ejected = project_dir / ".memorable" / "docker-compose.yml"
        if ejected.exists():
            return ejected
    return _TEMPLATE_PATH


def start(config: RuntimeConfig, *, project_dir: Path | None = None) -> DockerResult:
    """Start the local Neo4j container via docker compose up -d."""
    compose_file = resolve_compose_file(project_dir)
    cmd = [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "up",
        "-d",
    ]
    result = subprocess.run(
        cmd,
        env=_compose_env(config),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return DockerResult(
            success=False,
            message=f"docker compose up failed: {result.stderr.strip()}",
        )
    return DockerResult(success=True, message="Neo4j container started.")


def stop(config: RuntimeConfig, *, project_dir: Path | None = None) -> DockerResult:
    """Stop the local Neo4j container via docker compose down."""
    compose_file = resolve_compose_file(project_dir)
    cmd = [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "down",
    ]
    result = subprocess.run(
        cmd,
        env=_compose_env(config),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return DockerResult(
            success=False,
            message=f"docker compose down failed: {result.stderr.strip()}",
        )
    return DockerResult(success=True, message="Neo4j container stopped.")


def status(config: RuntimeConfig, *, project_dir: Path | None = None) -> ContainerState:
    """Check the state of the local Neo4j container."""
    compose_file = resolve_compose_file(project_dir)
    cmd = [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "ps",
        "--format",
        "{{.State}}",
        "neo4j",
    ]
    result = subprocess.run(
        cmd,
        env=_compose_env(config),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return ContainerState.NOT_FOUND

    state = result.stdout.strip().lower()
    if state == "running":
        return ContainerState.RUNNING
    return ContainerState.STOPPED


def eject(target_dir: Path) -> DockerResult:
    """Copy the packaged docker-compose.yml to target_dir for customization."""
    dest = target_dir / "docker-compose.yml"
    if dest.exists():
        return DockerResult(
            success=False,
            message=f"{dest} already exists. Remove it first to re-eject.",
        )
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_TEMPLATE_PATH, dest)
    return DockerResult(
        success=True,
        message=f"Compose template copied to {dest}.",
    )
