"""Neo4j runtime configuration.

This is infrastructure configuration, not a MemoryProfile.
It belongs in the storage adapter, not in core domain models.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Neo4jConfig:
    """Connection settings for the Neo4j storage adapter."""

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
