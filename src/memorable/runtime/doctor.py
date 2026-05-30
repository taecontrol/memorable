from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired, TypedDict

from neo4j import GraphDatabase

from memorable.config import RuntimeConfig
from memorable.core.profile import load_profile_from_yaml
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
MEMORY_PROFILE_HINT = "Fix .memorable/memory.yaml so it is valid MemoryProfile YAML."


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


@dataclass(frozen=True)
class DiagnosticProbes:
    """Collaborators that touch the live runtime, bundled behind one seam.

    Production callers use the default factory, which wires the real Neo4j,
    embedding, and profile probes. Tests substitute a probe set to drive each
    check deterministically without a database.
    """

    ping_neo4j: Callable[[RuntimeConfig], None] = ping_neo4j
    list_schema_constraints: Callable[[RuntimeConfig], list[SchemaConstraint]] = (
        list_schema_constraints
    )
    list_vector_indexes: Callable[[RuntimeConfig], list[VectorIndex]] = (
        list_vector_indexes
    )
    build_embedding_provider: Callable[..., object] = build_embedding_provider
    profile_path: Path | None = None
    load_profile_from_yaml: Callable[[str], object] = load_profile_from_yaml

    def resolved_profile_path(self) -> Path:
        """Return the MemoryProfile path, defaulting to the cwd workspace."""
        if self.profile_path is not None:
            return self.profile_path
        return Path.cwd() / ".memorable" / "memory.yaml"


def _connectivity_dependent_result(
    check: str,
    list_descriptors: Callable[[RuntimeConfig], list],
    is_present: Callable[[list], bool],
    config: RuntimeConfig,
    absent_hint: str,
) -> DiagnosticResult:
    """Evaluate a check that requires a live SHOW query against Neo4j.

    The caller guarantees connectivity already passed. If the SHOW query itself
    raises, that is a query/connectivity error — report it with the connectivity
    hint rather than misdiagnosing the schema as absent. Only when the query
    succeeds and proves the descriptor genuinely absent do we emit *absent_hint*
    (the 'run memorable init' remediation).
    """
    try:
        descriptors = list_descriptors(config)
    except Exception:
        return {"check": check, "ok": False, "hint": NEO4J_CONNECTIVITY_HINT}
    ok = is_present(descriptors)
    return {"check": check, "ok": ok, "hint": "" if ok else absent_hint}


def run_diagnostics(
    config: RuntimeConfig,
    *,
    probes: DiagnosticProbes | None = None,
) -> list[DiagnosticResult]:
    """Run runtime diagnostics and return presentation-independent results."""
    if probes is None:
        probes = DiagnosticProbes()

    results: list[DiagnosticResult] = []

    try:
        probes.ping_neo4j(config)
    except Exception:
        connectivity_ok = False
    else:
        connectivity_ok = True

    results.append(
        {
            "check": "neo4j_connectivity",
            "ok": connectivity_ok,
            "hint": "" if connectivity_ok else NEO4J_CONNECTIVITY_HINT,
        }
    )

    if not connectivity_ok:
        # Neo4j is unreachable, so the schema/vector SHOW queries cannot be
        # performed. Report both as failed with the connectivity hint rather
        # than misdiagnosing the schema as absent.
        results.append(
            {
                "check": "schema_constraints",
                "ok": False,
                "hint": NEO4J_CONNECTIVITY_HINT,
            }
        )
        results.append(
            {"check": "vector_index", "ok": False, "hint": NEO4J_CONNECTIVITY_HINT}
        )
    else:
        results.append(
            _connectivity_dependent_result(
                "schema_constraints",
                probes.list_schema_constraints,
                schema_constraints_present,
                config,
                SCHEMA_CONSTRAINTS_HINT,
            )
        )
        results.append(
            _connectivity_dependent_result(
                "vector_index",
                probes.list_vector_indexes,
                vector_index_present,
                config,
                VECTOR_INDEX_HINT,
            )
        )

    try:
        probes.build_embedding_provider(
            config.embeddings, api_key=config.embeddings.api_key
        )
    except Exception:
        results.append(
            {
                "check": "embedding_provider_builds",
                "ok": False,
                "hint": EMBEDDING_PROVIDER_HINT,
            }
        )
    else:
        results.append({"check": "embedding_provider_builds", "ok": True, "hint": ""})

    profile_path = probes.resolved_profile_path()
    if profile_path.exists():
        try:
            probes.load_profile_from_yaml(profile_path.read_text(encoding="utf-8"))
        except Exception:
            results.append(
                {
                    "check": "memory_profile_parses",
                    "ok": False,
                    "hint": MEMORY_PROFILE_HINT,
                }
            )
        else:
            results.append({"check": "memory_profile_parses", "ok": True, "hint": ""})

    return results


def all_checks_passed(results: list[DiagnosticResult]) -> bool:
    """Return True when every diagnostic check passed."""
    return all(bool(result["ok"]) for result in results)
