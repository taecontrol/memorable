from __future__ import annotations

from collections.abc import Callable
from typing import NotRequired, TypedDict

from neo4j import GraphDatabase

from memorable.config import RuntimeConfig
from memorable.retrieval.embeddings import build_embedding_provider
from memorable.storage.neo4j.schema import (
    expected_constraint_shapes,
    expected_vector_index_shape,
)


class DiagnosticResult(TypedDict):
    check: str
    ok: bool
    hint: str


class SchemaConstraint(TypedDict):
    name: str
    type: str
    labelsOrTypes: NotRequired[list[str]]
    properties: list[str]


class VectorIndex(TypedDict):
    name: str
    type: str
    labelsOrTypes: NotRequired[list[str]]
    properties: list[str]

NEO4J_CONNECTIVITY_HINT = (
    "Start Neo4j with 'memorable db start' or check .memorable/runtime.yaml."
)
SCHEMA_CONSTRAINTS_HINT = "Run 'memorable init' to bootstrap schema constraints."
VECTOR_INDEX_HINT = "Run 'memorable init' to bootstrap the vector index."
EMBEDDING_PROVIDER_HINT = "Check embeddings.provider, model, dimensions, and API key."


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


def list_vector_indexes(config: RuntimeConfig) -> list[VectorIndex]:
    """Return live Neo4j vector index descriptors."""
    driver = GraphDatabase.driver(
        config.neo4j.uri,
        auth=(config.neo4j.user, config.neo4j.password),
    )
    try:
        with driver.session() as session:
            result = session.run(
                "SHOW INDEXES "
                "YIELD name, type, labelsOrTypes, properties "
                "WHERE type = 'VECTOR' "
                "RETURN collect({"
                "name: name, "
                "type: type, "
                "labelsOrTypes: labelsOrTypes, "
                "properties: properties"
                "}) AS indexes"
            )
            record = result.single()
            if record is None:
                return []
            return list(record["indexes"])
    finally:
        driver.close()


def vector_index_present(indexes: list[VectorIndex]) -> bool:
    """Return whether the expected Memorable vector index exists."""
    expected_name, expected_label, expected_properties = expected_vector_index_shape()
    return any(
        index["name"] == expected_name
        and index["type"] == "VECTOR"
        and index.get("labelsOrTypes") == [expected_label]
        and tuple(index["properties"]) == expected_properties
        for index in indexes
    )


def run_diagnostics(
    config: RuntimeConfig,
    *,
    ping_neo4j: Callable[[RuntimeConfig], None] = ping_neo4j,
    list_schema_constraints: Callable[
        [RuntimeConfig], list[SchemaConstraint]
    ] = list_schema_constraints,
    list_vector_indexes: Callable[
        [RuntimeConfig], list[VectorIndex]
    ] = list_vector_indexes,
    build_embedding_provider: Callable[..., object] = build_embedding_provider,
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

    try:
        present_vector_indexes = list_vector_indexes(config)
    except Exception:
        present_vector_indexes = []
    vector_ok = vector_index_present(present_vector_indexes)
    results.append(
        {
            "check": "vector_index",
            "ok": vector_ok,
            "hint": "" if vector_ok else VECTOR_INDEX_HINT,
        }
    )

    try:
        build_embedding_provider(config.embeddings, api_key=config.embeddings.api_key)
    except Exception:
        results.append(
            {
                "check": "embedding_provider_builds",
                "ok": False,
                "hint": EMBEDDING_PROVIDER_HINT,
            }
        )
    else:
        results.append(
            {"check": "embedding_provider_builds", "ok": True, "hint": ""}
        )

    return results


def all_checks_passed(results: list[DiagnosticResult]) -> bool:
    """Return True when every diagnostic check passed."""
    return all(bool(result["ok"]) for result in results)
