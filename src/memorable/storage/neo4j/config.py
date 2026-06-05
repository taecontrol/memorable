"""Neo4j runtime configuration.

This is infrastructure configuration, not a MemoryProfile.
It belongs in the storage adapter, not in core domain models.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Neo4jConfig:
    """Connection settings for the Neo4j storage adapter.

    TEST-HARNESS-ONLY: this shape exists for live-Neo4j test fixtures that build
    raw drivers directly. Live runtime code (production context, diagnostics,
    CLI, MCP) MUST build drivers through the shared connection policy
    (``memorable.storage.neo4j.connection``), never through ``Neo4jConfig``, so a
    second/third connection-config shape cannot drift back into production and
    reintroduce the IPv4-first / fail-fast divergence this work removed. See
    ADR-0016 and PRD #184.
    """

    uri: str
    user: str
    password: str

    @classmethod
    def default(cls) -> Neo4jConfig:
        """Sensible defaults for local development."""
        return cls(
            uri="bolt://127.0.0.1:7687",
            user="neo4j",
            password="memorable",
        )

    @classmethod
    def from_env(cls) -> Neo4jConfig:
        """Build config from environment variables."""
        return cls(
            uri=os.environ.get("MEMORABLE_NEO4J_URI", "bolt://127.0.0.1:7687"),
            user=os.environ.get("MEMORABLE_NEO4J_USER", "neo4j"),
            password=os.environ.get("MEMORABLE_NEO4J_PASSWORD", "memorable"),
        )
