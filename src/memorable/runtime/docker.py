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


def start(config: RuntimeConfig) -> DockerResult:
    """Start the local Neo4j container via docker compose up -d."""
    cmd = [
        "docker", "compose",
        "-f", str(_TEMPLATE_PATH),
        "up", "-d",
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


def stop(config: RuntimeConfig) -> DockerResult:
    """Stop the local Neo4j container via docker compose down."""
    cmd = [
        "docker", "compose",
        "-f", str(_TEMPLATE_PATH),
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


def status(config: RuntimeConfig) -> ContainerState:
    """Check the state of the local Neo4j container."""
    cmd = [
        "docker", "compose",
        "-f", str(_TEMPLATE_PATH),
        "ps", "--format", "{{.State}}",
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
