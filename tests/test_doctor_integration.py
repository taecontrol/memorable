"""Integration tests for doctor's live vector index dimension check.

These tests require a running Neo4j instance. They are marked with
@pytest.mark.integration and will be skipped if Neo4j is unavailable.

They prove that `vector_index_dimensions` parses the REAL `SHOW INDEXES ...
options` shape (the unit tests stub `options`); this is the part the architect
finding specifically targets.

Run with: uv run pytest tests/test_doctor_integration.py -v -m integration
"""

from __future__ import annotations

import pytest

from memorable.config import EmbeddingSettings, Neo4jSettings, RuntimeConfig
from memorable.storage.neo4j.config import Neo4jConfig
from memorable.storage.neo4j.schema import create_vector_index_cypher

INDEX_NAME = "memorable_embeddings_vector"
DEFAULT_DIMENSIONS = 384

# Skip all tests in this module if Neo4j is unavailable.
neo4j_available = False
try:
    from neo4j import GraphDatabase

    _config = Neo4jConfig.from_env()
    _driver = GraphDatabase.driver(_config.uri, auth=(_config.user, _config.password))
    _driver.verify_connectivity()
    _driver.close()
    neo4j_available = True
except Exception:
    pass

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not neo4j_available, reason="Neo4j is not available"),
]


class _FakeProvider:
    """Stub embedding provider so the test never downloads a fastembed model."""

    def __init__(self, vector: list[float]) -> None:
        self._vector = vector

    def embed(self, _text: str) -> list[float]:
        return self._vector


def _runtime_config(dimensions: int) -> RuntimeConfig:
    """RuntimeConfig with live Neo4j from env and a stubbed embedding model."""
    neo4j = Neo4jConfig.from_env()
    return RuntimeConfig(
        neo4j=Neo4jSettings(uri=neo4j.uri, user=neo4j.user, password=neo4j.password),
        embeddings=EmbeddingSettings(
            provider="fake", model="hash-based", dimensions=dimensions
        ),
    )


def _create_index_at(session, dimensions: int) -> None:
    session.run(f"DROP INDEX {INDEX_NAME} IF EXISTS")
    session.run(create_vector_index_cypher(dimensions))
    # Vector index creation is asynchronous; SHOW INDEXES does not expose
    # options.indexConfig until the index is ONLINE.
    session.run("CALL db.awaitIndexes()")


@pytest.fixture
def vector_index_at_384():
    """Create the real Memorable vector index at 384 dims, then restore it.

    Teardown always runs (yield fixture), leaving the shared dev DB with the
    index recreated at the default 384 dims for normal use.
    """
    driver = GraphDatabase.driver(_config.uri, auth=(_config.user, _config.password))
    try:
        with driver.session() as session:
            _create_index_at(session, DEFAULT_DIMENSIONS)
        yield
    finally:
        with driver.session() as session:
            session.run(f"DROP INDEX {INDEX_NAME} IF EXISTS")
            session.run(create_vector_index_cypher(DEFAULT_DIMENSIONS))
            session.run("CALL db.awaitIndexes()")
        driver.close()


@pytest.mark.integration
def test_live_vector_index_dimensions_parses_real_options_shape(
    vector_index_at_384,
) -> None:
    """The real SHOW INDEXES options shape parses to the index's dimension."""
    from memorable.runtime.doctor import (
        list_vector_indexes,
        live_vector_index_dimensions,
    )

    config = _runtime_config(DEFAULT_DIMENSIONS)
    indexes = list_vector_indexes(config)

    assert any(index["name"] == INDEX_NAME for index in indexes)
    assert live_vector_index_dimensions(indexes) == DEFAULT_DIMENSIONS


@pytest.mark.integration
def test_doctor_flags_live_index_dimension_mismatch_end_to_end(
    vector_index_at_384,
) -> None:
    """End-to-end: config=768 vs live index=384 → check fails citing both."""
    from memorable.runtime.doctor import DiagnosticProbes, run_diagnostics

    config = _runtime_config(768)
    results = run_diagnostics(
        config,
        probes=DiagnosticProbes(
            build_embedding_provider=lambda _s, api_key=None: _FakeProvider(
                [0.0] * 768
            ),
        ),
    )
    by_check = {result["check"]: result for result in results}

    result = by_check["vector_index_dimensions"]
    assert result["ok"] is False
    assert "384" in result["hint"]
    assert "768" in result["hint"]
