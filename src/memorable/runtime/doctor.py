from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

from neo4j import GraphDatabase

from memorable.config import RuntimeConfig


class DiagnosticResult(TypedDict):
    check: str
    ok: bool
    hint: str

NEO4J_CONNECTIVITY_HINT = (
    "Start Neo4j with 'memorable db start' or check .memorable/runtime.yaml."
)


def ping_neo4j(config: RuntimeConfig) -> None:
    """Verify the configured Neo4j Bolt endpoint is reachable."""
    driver = GraphDatabase.driver(
        config.neo4j.uri,
        auth=(config.neo4j.user, config.neo4j.password),
    )
    try:
        driver.verify_connectivity()
    finally:
        driver.close()


def run_diagnostics(
    config: RuntimeConfig,
    *,
    ping_neo4j: Callable[[RuntimeConfig], None] = ping_neo4j,
) -> list[DiagnosticResult]:
    """Run runtime diagnostics and return presentation-independent results."""
    try:
        ping_neo4j(config)
    except Exception:
        return [
            {
                "check": "neo4j_connectivity",
                "ok": False,
                "hint": NEO4J_CONNECTIVITY_HINT,
            }
        ]

    return [{"check": "neo4j_connectivity", "ok": True, "hint": ""}]


def all_checks_passed(results: list[DiagnosticResult]) -> bool:
    """Return True when every diagnostic check passed."""
    return all(bool(result["ok"]) for result in results)
