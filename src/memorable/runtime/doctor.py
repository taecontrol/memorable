from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired, TypedDict

from neo4j import GraphDatabase

from memorable.config import RuntimeConfig
from memorable.core.profile import load_profile_from_yaml
from memorable.retrieval.embeddings import EmbeddingProvider, build_embedding_provider
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
    options: NotRequired[dict]


NEO4J_CONNECTIVITY_HINT = (
    "Start Neo4j with 'memorable db start' or check .memorable/runtime.yaml."
)
SCHEMA_CONSTRAINTS_HINT = "Run 'memorable init' to bootstrap schema constraints."
VECTOR_INDEX_HINT = "Run 'memorable init' to bootstrap the vector index."
VECTOR_INDEX_DIMENSIONS_UNREADABLE_HINT = (
    "Doctor could not read live vector index dimensions; "
    "Neo4j did not expose index options."
)
EMBEDDING_PROVIDER_HINT = "Check embeddings.provider, model, dimensions, and API key."
EMBEDDING_PROVIDER_CHECK = "embedding_provider_embeds"
EMBEDDING_PROBE_TEXT = "Memorable doctor embedding probe."
FASTEMBED_DOWNLOAD_HINT = "fastembed first use may download the local model (~67MB)."
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
                "YIELD name, type, labelsOrTypes, properties, options "
                "WHERE type = 'VECTOR' "
                "RETURN collect({"
                "name: name, "
                "type: type, "
                "labelsOrTypes: labelsOrTypes, "
                "properties: properties, "
                "options: options"
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


def live_vector_index_dimensions(indexes: list[VectorIndex]) -> int | None:
    """Return the live `vector.dimensions` of the expected Memorable index.

    Matches the expected index by the same name/label/property logic
    *vector_index_present* uses, then reads
    ``options["indexConfig"]["vector.dimensions"]``. Returns None when no
    matching index is found or Neo4j did not expose readable dimensions, so
    callers can soft-pass rather than misdiagnose missing metadata as failure.
    """
    expected_name, expected_label, expected_properties = expected_vector_index_shape()
    for index in indexes:
        if (
            index["name"] != expected_name
            or index["type"] != "VECTOR"
            or index.get("labelsOrTypes") != [expected_label]
            or tuple(index["properties"]) != expected_properties
        ):
            continue
        options = index.get("options")
        if not isinstance(options, dict):
            return None
        index_config = options.get("indexConfig")
        if not isinstance(index_config, dict):
            return None
        dimensions = index_config.get("vector.dimensions")
        if isinstance(dimensions, int):
            return dimensions
        return None
    return None


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
    build_embedding_provider: Callable[..., EmbeddingProvider] = (
        build_embedding_provider
    )
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


def _vector_index_dimensions_hint(live_dimensions: int, config: RuntimeConfig) -> str:
    return (
        "Live vector index 'memorable_embeddings_vector' was built for "
        f"{live_dimensions} dimensions, but the runtime is configured for "
        f"{config.embeddings.dimensions} dimensions. The index was built for a "
        "different embedding model; re-run 'memorable init' (or migrate) so the "
        "index matches the configured embeddings."
    )


def _vector_index_dimensions_result(
    config: RuntimeConfig,
    list_vector_indexes: Callable[[RuntimeConfig], list[VectorIndex]],
) -> DiagnosticResult:
    """Validate the live index `vector.dimensions` against the configured value.

    A mismatch is the silent failure ADR-0016 targets: the provider can agree
    with config while the index was built for an older model, so every real
    write/search fails at query time. When Neo4j does not expose readable
    dimensions (no options/indexConfig, or no matching index) we soft-pass —
    the existing 'vector_index' check already reports a genuinely missing index.
    """
    check = "vector_index_dimensions"
    try:
        indexes = list_vector_indexes(config)
    except Exception:
        return {"check": check, "ok": False, "hint": NEO4J_CONNECTIVITY_HINT}

    live_dimensions = live_vector_index_dimensions(indexes)
    if live_dimensions is None:
        return {
            "check": check,
            "ok": True,
            "hint": VECTOR_INDEX_DIMENSIONS_UNREADABLE_HINT,
        }
    if live_dimensions == config.embeddings.dimensions:
        return {"check": check, "ok": True, "hint": ""}
    return {
        "check": check,
        "ok": False,
        "hint": _vector_index_dimensions_hint(live_dimensions, config),
    }


def _embedding_provider_hint(config: RuntimeConfig, cause: str) -> str:
    return (
        "Embedding Provider "
        f"{config.embeddings.provider!r} with model {config.embeddings.model!r} "
        "could not build/embed the doctor probe. "
        f"Expected {config.embeddings.dimensions} dimensions. "
        f"{EMBEDDING_PROVIDER_HINT} Cause: {cause}"
    )


def _embedding_provider_success_hint(config: RuntimeConfig) -> str:
    if config.embeddings.provider == "fastembed":
        return FASTEMBED_DOWNLOAD_HINT
    return ""


def _embedding_probe_result(
    config: RuntimeConfig,
    probes: DiagnosticProbes,
) -> DiagnosticResult:
    # ADR-0016: doctor diagnoses the live runtime, so it must exercise the same
    # embed path used by write/search commands instead of only constructing it.
    try:
        provider = probes.build_embedding_provider(
            config.embeddings, api_key=config.embeddings.api_key
        )
        vector = provider.embed(EMBEDDING_PROBE_TEXT)
    except Exception as exc:
        return {
            "check": EMBEDDING_PROVIDER_CHECK,
            "ok": False,
            "hint": _embedding_provider_hint(config, str(exc)),
        }

    if not isinstance(vector, list) or not vector:
        return {
            "check": EMBEDDING_PROVIDER_CHECK,
            "ok": False,
            "hint": _embedding_provider_hint(config, "provider returned no Embedding"),
        }

    if not all(isinstance(value, float) for value in vector):
        return {
            "check": EMBEDDING_PROVIDER_CHECK,
            "ok": False,
            "hint": _embedding_provider_hint(
                config, "provider returned non-float data"
            ),
        }

    if len(vector) != config.embeddings.dimensions:
        return {
            "check": EMBEDDING_PROVIDER_CHECK,
            "ok": False,
            "hint": _embedding_provider_hint(
                config,
                "provider returned "
                f"{len(vector)} dimensions; runtime configured "
                f"{config.embeddings.dimensions}",
            ),
        }

    return {
        "check": EMBEDDING_PROVIDER_CHECK,
        "ok": True,
        "hint": _embedding_provider_success_hint(config),
    }


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
        results.append(
            {
                "check": "vector_index_dimensions",
                "ok": False,
                "hint": NEO4J_CONNECTIVITY_HINT,
            }
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
        results.append(
            _vector_index_dimensions_result(config, probes.list_vector_indexes)
        )

    results.append(_embedding_probe_result(config, probes))

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
