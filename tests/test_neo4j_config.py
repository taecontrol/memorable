"""Tests for Neo4j runtime configuration."""

from __future__ import annotations

import pytest


def test_neo4j_config_has_connection_settings() -> None:
    """Neo4jConfig must hold URI and auth credentials."""
    from memorable.storage.neo4j.config import Neo4jConfig

    config = Neo4jConfig(uri="bolt://localhost:7687", user="neo4j", password="test")
    assert config.uri == "bolt://localhost:7687"
    assert config.user == "neo4j"
    assert config.password == "test"


def test_neo4j_config_has_sensible_defaults() -> None:
    """Neo4jConfig should provide defaults for local development."""
    from memorable.storage.neo4j.config import Neo4jConfig

    config = Neo4jConfig.default()
    assert "bolt://" in config.uri or "neo4j://" in config.uri
    assert config.user == "neo4j"


def test_neo4j_config_default_uses_ipv4_loopback() -> None:
    """Local default URI uses IPv4 loopback, not ambiguous localhost."""
    from memorable.storage.neo4j.config import Neo4jConfig

    assert Neo4jConfig.default().uri == "bolt://127.0.0.1:7687"


def test_neo4j_config_from_env_defaults_to_ipv4_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an explicit URI override, from_env uses IPv4 loopback."""
    from memorable.storage.neo4j.config import Neo4jConfig

    monkeypatch.delenv("MEMORABLE_NEO4J_URI", raising=False)

    assert Neo4jConfig.from_env().uri == "bolt://127.0.0.1:7687"


def test_neo4j_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neo4jConfig should be constructable from environment variables."""
    from memorable.storage.neo4j.config import Neo4jConfig

    monkeypatch.setenv("MEMORABLE_NEO4J_URI", "bolt://custom:7687")
    monkeypatch.setenv("MEMORABLE_NEO4J_USER", "admin")
    monkeypatch.setenv("MEMORABLE_NEO4J_PASSWORD", "secret")

    config = Neo4jConfig.from_env()
    assert config.uri == "bolt://custom:7687"
    assert config.user == "admin"
    assert config.password == "secret"


def test_neo4j_config_is_not_a_memory_profile() -> None:
    """Runtime config must not live in core domain models."""
    import memorable.core.models as core_models

    # Neo4jConfig should NOT be in core
    assert not hasattr(core_models, "Neo4jConfig")
