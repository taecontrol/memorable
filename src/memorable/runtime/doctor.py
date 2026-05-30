from __future__ import annotations

from collections.abc import Callable
from typing import NotRequired, TypedDict

from neo4j import GraphDatabase

from memorable.config import RuntimeConfig
from memorable.storage.neo4j.schema import expected_constraint_shapes


class DiagnosticResult(TypedDict):
    check: str
    ok: bool
    hint: str


class SchemaConstraint(TypedDict):
    name: str
    type: str
    labelsOrTypes: NotRequired[list[str]]
    properties: list[str]

NEO4J_CONNECTIVITY_HINT = (
    "Start Neo4j with 'memorable db start' or check .memorable/runtime.yaml."
)
SCHEMA_CONSTRAINTS_HINT = "Run 'memorable init' to bootstrap schema constraints."


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


def list_schema_constraints(config: RuntimeConfig) -> list[SchemaConstraint]:
    """Return live Neo4j schema constraint descriptors."""
    driver = GraphDatabase.driver(
        config.neo4j.uri,
        auth=(config.neo4j.user, config.neo4j.password),
    )
    try:
        with driver.session() as session:
            result = session.run(
                "SHOW CONSTRAINTS "
                "YIELD name, type, labelsOrTypes, properties "
                "RETURN collect({"
                "name: name, "
                "type: type, "
                "labelsOrTypes: labelsOrTypes, "
                "properties: properties"
                "}) AS constraints"
            )
            record = result.single()
            if record is None:
                return []
            return list(record["constraints"])
    finally:
        driver.close()


def schema_constraints_present(constraints: list[SchemaConstraint]) -> bool:
    """Return whether expected uniqueness constraints exist with expected shape."""
    present_shapes = set()
    for constraint in constraints:
        labels_or_types = constraint.get("labelsOrTypes", [])
        if len(labels_or_types) != 1:
            continue
        present_shapes.add(
            (
                constraint["type"],
                labels_or_types[0],
                tuple(constraint["properties"]),
            )
        )
    return expected_constraint_shapes().issubset(present_shapes)


def run_diagnostics(
    config: RuntimeConfig,
    *,
    ping_neo4j: Callable[[RuntimeConfig], None] = ping_neo4j,
    list_schema_constraints: Callable[
        [RuntimeConfig], list[SchemaConstraint]
    ] = list_schema_constraints,
) -> list[DiagnosticResult]:
    """Run runtime diagnostics and return presentation-independent results."""
    results: list[DiagnosticResult] = []
    try:
        ping_neo4j(config)
    except Exception:
        results.append(
            {
                "check": "neo4j_connectivity",
                "ok": False,
                "hint": NEO4J_CONNECTIVITY_HINT,
            }
        )
    else:
        results.append({"check": "neo4j_connectivity", "ok": True, "hint": ""})

    try:
        present_constraints = list_schema_constraints(config)
    except Exception:
        present_constraints = []
    schema_ok = schema_constraints_present(present_constraints)
    results.append(
        {
            "check": "schema_constraints",
            "ok": schema_ok,
            "hint": "" if schema_ok else SCHEMA_CONSTRAINTS_HINT,
        }
    )

    return results


def all_checks_passed(results: list[DiagnosticResult]) -> bool:
    """Return True when every diagnostic check passed."""
    return all(bool(result["ok"]) for result in results)
