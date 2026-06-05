"""Three-layer runtime configuration for Memorable.

Loads configuration from:
1. Built-in defaults
2. .memorable/runtime.yaml (project base)
3. .memorable/runtime.local.yaml (local overrides, gitignored)
4. .memorable/.env or environment variables (secrets)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Neo4jSettings:
    uri: str = "bolt://127.0.0.1:7687"
    user: str = "neo4j"
    password: str = "memorable"


@dataclass(frozen=True)
class DockerSettings:
    neo4j_version: str = "5.26"
    http_port: int = 7474
    bolt_port: int = 7687


@dataclass(frozen=True)
class EmbeddingSettings:
    provider: str = "fastembed"
    model: str = "BAAI/bge-small-en-v1.5"
    dimensions: int = 384
    api_key: str | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    neo4j: Neo4jSettings = field(default_factory=Neo4jSettings)
    docker: DockerSettings = field(default_factory=DockerSettings)
    embeddings: EmbeddingSettings = field(default_factory=EmbeddingSettings)
    sources: dict[str, str] = field(default_factory=dict)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base, replacing leaf values only."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file. Skips comments and blank lines."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip optional surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        env[key] = value
    return env


def _build_sources(
    raw: dict[str, Any],
    yaml_source: str,
) -> dict[str, str]:
    """Flatten nested dict into dot-path -> source mapping."""
    sources: dict[str, str] = {}
    for section_key, section_val in raw.items():
        if isinstance(section_val, dict):
            for field_key in section_val:
                sources[f"{section_key}.{field_key}"] = yaml_source
        else:
            sources[section_key] = yaml_source
    return sources


_ENV_MAPPING: dict[str, str] = {
    "MEMORABLE_NEO4J_URI": "neo4j.uri",
    "MEMORABLE_NEO4J_USER": "neo4j.user",
    "MEMORABLE_NEO4J_PASSWORD": "neo4j.password",
    "MEMORABLE_OPENROUTER_API_KEY": "embeddings.api_key",
}

_ENV_SECRET_FIELDS = {"neo4j.password", "embeddings.api_key"}


def load_runtime_config(
    base_path: Path | None = None,
    *,
    include_environment_overrides: bool = False,
) -> RuntimeConfig:
    """Load runtime configuration using three-layer strategy.

    Resolution order (later wins):
    1. Built-in defaults
    2. .memorable/runtime.yaml
    3. .memorable/runtime.local.yaml
    4. .memorable/.env or os.environ for secret keys

    Set include_environment_overrides when a live runtime command should accept
    non-secret MEMORABLE_* process overrides supplied by automation.
    """
    if base_path is None:
        base_path = Path.cwd()

    config_dir = base_path / ".memorable"
    runtime_yaml = config_dir / "runtime.yaml"
    local_yaml = config_dir / "runtime.local.yaml"
    dotenv_path = config_dir / ".env"

    # Start with empty merged dict and built-in sources
    merged: dict[str, Any] = {}
    sources: dict[str, str] = {}

    # Layer 2: runtime.yaml
    if runtime_yaml.exists():
        raw = yaml.safe_load(runtime_yaml.read_text(encoding="utf-8")) or {}
        merged = _deep_merge(merged, raw)
        sources.update(_build_sources(raw, "runtime.yaml"))

    # Layer 3: runtime.local.yaml
    if local_yaml.exists():
        raw = yaml.safe_load(local_yaml.read_text(encoding="utf-8")) or {}
        merged = _deep_merge(merged, raw)
        sources.update(_build_sources(raw, "runtime.local.yaml"))

    # Layer 4: secrets from .env or environment
    # If .env exists, use only that file for secrets; otherwise fall back to os.environ
    dotenv = _parse_dotenv(dotenv_path)
    use_dotenv = dotenv_path.exists()

    for env_key, field_path in _ENV_MAPPING.items():
        value: str | None = None
        source: str | None = None

        if use_dotenv:
            if env_key in dotenv:
                value = dotenv[env_key]
                source = ".env"
        elif env_key in os.environ and (
            field_path in _ENV_SECRET_FIELDS or include_environment_overrides
        ):
            value = os.environ[env_key]
            source = "environment"

        if value is not None and source is not None:
            section, _, field_name = field_path.partition(".")
            if section not in merged:
                merged[section] = {}
            merged[section][field_name] = value
            sources[field_path] = source

    # Build settings from merged dict, filling in defaults for unset fields
    neo4j_raw = merged.get("neo4j", {})
    docker_raw = merged.get("docker", {})
    embeddings_raw = merged.get("embeddings", {})

    neo4j = Neo4jSettings(
        uri=neo4j_raw.get("uri", Neo4jSettings.uri),
        user=neo4j_raw.get("user", Neo4jSettings.user),
        password=neo4j_raw.get("password", Neo4jSettings.password),
    )
    docker = DockerSettings(
        neo4j_version=docker_raw.get("neo4j_version", DockerSettings.neo4j_version),
        http_port=docker_raw.get("http_port", DockerSettings.http_port),
        bolt_port=docker_raw.get("bolt_port", DockerSettings.bolt_port),
    )
    embeddings = EmbeddingSettings(
        provider=embeddings_raw.get("provider", EmbeddingSettings.provider),
        model=embeddings_raw.get("model", EmbeddingSettings.model),
        dimensions=embeddings_raw.get("dimensions", EmbeddingSettings.dimensions),
        api_key=embeddings_raw.get("api_key", EmbeddingSettings.api_key),
    )

    # Fill in "built-in" for any field not already tracked
    all_fields = [
        "neo4j.uri",
        "neo4j.user",
        "neo4j.password",
        "docker.neo4j_version",
        "docker.http_port",
        "docker.bolt_port",
        "embeddings.provider",
        "embeddings.model",
        "embeddings.dimensions",
        "embeddings.api_key",
    ]
    for fp in all_fields:
        if fp not in sources:
            sources[fp] = "built-in"

    return RuntimeConfig(
        neo4j=neo4j,
        docker=docker,
        embeddings=embeddings,
        sources=sources,
    )
