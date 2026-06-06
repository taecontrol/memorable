"""Provisioning-not-reconciliation boundary (PRD #195, #202, ADR-0020).

Schema bootstrap (``memorable init`` / ``ensure_all_constraints``) stays
create-if-absent and must never drop or recreate the vector index. Once
Embeddings are persisted, a bootstrap that "reconciled" drift by dropping and
recreating the index would silently delete every stored vector. Drop+recreate
lives only in ``memorable reindex``. These tests pin that boundary so a future
change cannot quietly make bootstrap destructive.
"""

from __future__ import annotations

import pytest

from memorable.storage.neo4j.repository import ensure_all_constraints


class _StatementRecordingSession:
    def __init__(self, statements: list[str]) -> None:
        self._statements = statements

    def __enter__(self) -> _StatementRecordingSession:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def run(self, statement: str, **_params: object) -> None:
        self._statements.append(statement)
        return None


class _StatementRecordingDriver:
    """Driver spy capturing every Cypher statement bootstrap issues."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def session(self) -> _StatementRecordingSession:
        return _StatementRecordingSession(self.statements)


def test_ensure_all_constraints_never_drops_or_recreates_vector_index() -> None:
    """Bootstrap stays create-if-absent even when configured dims differ.

    Invoked with dimensions that differ from a (hypothetical) existing index,
    bootstrap must still only issue a create-if-absent vector index statement
    and never a DROP -- so an existing index, including one at mismatched
    dimensions, is left intact rather than silently recreated.
    """
    driver = _StatementRecordingDriver()

    ensure_all_constraints(driver, vector_dimensions=1536)

    joined = " ".join(driver.statements).upper()
    assert "DROP INDEX" not in joined  # never destructive
    vector_statements = [s for s in driver.statements if "VECTOR INDEX" in s.upper()]
    assert len(vector_statements) == 1
    only_vector_statement = vector_statements[0].upper()
    assert only_vector_statement.startswith("CREATE VECTOR INDEX")
    assert "IF NOT EXISTS" in only_vector_statement


def _live_vector_index_dimensions(driver, name: str) -> int | None:
    with driver.session() as session:
        result = session.run(
            "SHOW INDEXES YIELD name, type, options "
            "WHERE name = $name AND type = 'VECTOR' "
            "RETURN options AS options",
            name=name,
        )
        record = result.single()
    if record is None:
        return None
    options = record["options"]
    if not isinstance(options, dict):
        return None
    index_config = options.get("indexConfig")
    if not isinstance(index_config, dict):
        return None
    dimensions = index_config.get("vector.dimensions")
    return dimensions if isinstance(dimensions, int) else None


@pytest.mark.integration
def test_neo4j_bootstrap_leaves_existing_mismatched_index_intact() -> None:
    """Live: re-running bootstrap at new dims does not drop a drifted index."""
    try:
        from live_neo4j import build_live_neo4j_driver

        from memorable.storage.neo4j.schema import EXPECTED_VECTOR_INDEX
    except Exception:
        pytest.skip("Neo4j dependencies are not available")

    driver = build_live_neo4j_driver()
    index_name = EXPECTED_VECTOR_INDEX.name
    try:
        try:
            driver.verify_connectivity()
        except Exception:
            pytest.skip("Neo4j is not available")

        # Establish an index drifted to 8 dimensions.
        with driver.session() as session:
            session.run(f"DROP INDEX {index_name} IF EXISTS")
        ensure_all_constraints(driver, vector_dimensions=8)
        with driver.session() as session:
            session.run("CALL db.awaitIndex($name, 30)", name=index_name)
        assert _live_vector_index_dimensions(driver, index_name) == 8

        # Re-running bootstrap at a different configured dimension must NOT
        # drop or recreate the existing index: it stays at 8.
        ensure_all_constraints(driver, vector_dimensions=384)
        with driver.session() as session:
            session.run("CALL db.awaitIndex($name, 30)", name=index_name)
        assert _live_vector_index_dimensions(driver, index_name) == 8
    finally:
        # Leave the index at the repo default so other tests are unaffected.
        with driver.session() as session:
            session.run(f"DROP INDEX {index_name} IF EXISTS")
        try:
            ensure_all_constraints(driver, vector_dimensions=384)
        except Exception:
            pass
        driver.close()
