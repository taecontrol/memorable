"""Shared test seam for the live Neo4j runtime.

This is the single place the test harness resolves "which Neo4j" and constructs
a raw driver. It mirrors the live runtime's resolution path: connection settings
come from the layered ``RuntimeConfig`` built by ``load_runtime_config(...)``
(built-in defaults -> runtime.yaml -> runtime.local.yaml -> .env/os.environ),
with process-environment overrides honored exactly as the live commands honor
them. This removes the second, flat ``Neo4jConfig.from_env()`` precedence model
so a passing live-Neo4j test targets the runtime the product would actually
reach.

Fixtures that need a policy-free driver for setup/teardown build it here too, so
connection-building knowledge stays in this one narrow interface rather than
being copied across many test files. The live connection ceremony (fail-fast
timeouts, IPv4 rewrite, notification suppression) belongs to the production
``connect()`` policy, not to these raw-driver test fixtures.
"""

from __future__ import annotations

from neo4j import Driver, GraphDatabase

from memorable.config import Neo4jSettings, load_runtime_config


def resolve_live_neo4j_settings() -> Neo4jSettings:
    """Resolve Neo4j connection settings the way the live runtime does.

    Uses ``include_environment_overrides=True`` so a process-supplied
    ``MEMORABLE_NEO4J_URI``/``_USER`` override is honored just like the live CLI
    and MCP entrypoints, instead of being dropped back to the built-in default.
    """
    return load_runtime_config(include_environment_overrides=True).neo4j


def build_live_neo4j_driver() -> Driver:
    """Build a raw Neo4j driver from the resolved live runtime settings."""
    settings = resolve_live_neo4j_settings()
    return GraphDatabase.driver(settings.uri, auth=(settings.user, settings.password))


def live_neo4j_available() -> bool:
    """Return True when the resolved live Neo4j runtime is reachable."""
    try:
        driver = build_live_neo4j_driver()
        driver.verify_connectivity()
        driver.close()
    except Exception:
        return False
    return True
