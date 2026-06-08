"""Tests proving doctor exercises the shared Neo4j connection policy.

Slice #187: runtime diagnostics must build drivers through the same deep module
(``storage/neo4j/connection``) that live commands use, perform a bounded
representative read after basic connectivity, and surface the localhost->IPv4
compatibility behavior without changing ``db status`` semantics.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from memorable.config import Neo4jSettings, RuntimeConfig, StorageSettings
from memorable.runtime.doctor import DiagnosticProbes, run_diagnostics


def _config(uri: str = "bolt://127.0.0.1:7687") -> RuntimeConfig:
    return RuntimeConfig(
        storage=StorageSettings(backend="neo4j"),
        neo4j=Neo4jSettings(uri=uri, user="neo4j", password="secret"),
    )


class _Provider:
    def embed(self, _text: str) -> list[float]:
        return [0.0] * 384


def _passing_probes(**overrides) -> DiagnosticProbes:
    """DiagnosticProbes whose checks pass without touching a live runtime."""
    defaults = {
        "ping_neo4j": lambda _config: None,
        "list_schema_constraints": lambda _config: [],
        "list_vector_indexes": lambda _config: [],
        "build_embedding_provider": lambda _settings, api_key=None: _Provider(),
        "load_profile_from_yaml": lambda _yaml_text: object(),
    }
    defaults.update(overrides)
    return DiagnosticProbes(**defaults)


def _by_check(results: list) -> dict:
    return {result["check"]: result for result in results}


def _session_of(driver: MagicMock) -> MagicMock:
    """Return the session yielded by ``with driver.session() as session``."""
    return driver.session.return_value.__enter__.return_value


class TestPingNeo4j:
    """ping_neo4j connects through the policy and does a representative read."""

    def test_uses_shared_connection_policy_and_closes_driver(self) -> None:
        from memorable.runtime.doctor import ping_neo4j

        config = _config()
        with patch("memorable.runtime.doctor.connect") as mock_connect:
            mock_driver = MagicMock()
            mock_connect.return_value = mock_driver

            ping_neo4j(config)

        mock_connect.assert_called_once_with(config)
        mock_driver.close.assert_called_once()

    def test_runs_lightweight_representative_read(self) -> None:
        from memorable.runtime.doctor import (
            REPRESENTATIVE_READ_QUERY,
            ping_neo4j,
        )

        with patch("memorable.runtime.doctor.connect") as mock_connect:
            mock_driver = MagicMock()
            mock_connect.return_value = mock_driver
            session = _session_of(mock_driver)

            ping_neo4j(_config())

        session.run.assert_called_once_with(REPRESENTATIVE_READ_QUERY)
        session.run.return_value.consume.assert_called_once()

    def test_read_failure_propagates_and_closes_driver(self) -> None:
        from memorable.runtime.doctor import ping_neo4j

        with patch("memorable.runtime.doctor.connect") as mock_connect:
            mock_driver = MagicMock()
            mock_connect.return_value = mock_driver
            _session_of(mock_driver).run.side_effect = RuntimeError("read hung")

            with pytest.raises(RuntimeError):
                ping_neo4j(_config())

        mock_driver.close.assert_called_once()


class TestShowQueriesUsePolicy:
    """The SHOW CONSTRAINTS / SHOW INDEXES reads share the same policy path."""

    def test_list_schema_constraints_uses_shared_connection_policy(self) -> None:
        from memorable.runtime.doctor import list_schema_constraints

        config = _config()
        with patch("memorable.runtime.doctor.connect") as mock_connect:
            mock_driver = MagicMock()
            mock_connect.return_value = mock_driver
            _session_of(mock_driver).run.return_value.single.return_value = {
                "constraints": []
            }

            result = list_schema_constraints(config)

        mock_connect.assert_called_once_with(config)
        mock_driver.close.assert_called_once()
        assert result == []

    def test_representative_read_is_bounded_and_not_a_search(self) -> None:
        from memorable.runtime.doctor import REPRESENTATIVE_READ_QUERY

        query = REPRESENTATIVE_READ_QUERY.lower()
        assert "return 1" in query
        for forbidden in ("match", "vector", "embedding", "db.index", "score"):
            assert forbidden not in query

    def test_list_vector_indexes_uses_shared_connection_policy(self) -> None:
        from memorable.runtime.doctor import list_vector_indexes

        config = _config()
        with patch("memorable.runtime.doctor.connect") as mock_connect:
            mock_driver = MagicMock()
            mock_connect.return_value = mock_driver
            _session_of(mock_driver).run.return_value.single.return_value = {
                "indexes": []
            }

            result = list_vector_indexes(config)

        mock_connect.assert_called_once_with(config)
        mock_driver.close.assert_called_once()
        assert result == []


class TestLocalEndpointNote:
    """Doctor surfaces localhost->IPv4 compatibility without changing status."""

    def test_localhost_config_surfaces_compatibility_note(self) -> None:
        results = run_diagnostics(
            _config("bolt://localhost:7687"), probes=_passing_probes()
        )

        note = _by_check(results)["neo4j_local_endpoint"]
        assert note["ok"] is True
        assert "localhost" in note["hint"]
        assert "127.0.0.1" in note["hint"]

    def test_ipv4_default_emits_no_compatibility_note(self) -> None:
        results = run_diagnostics(
            _config("bolt://127.0.0.1:7687"), probes=_passing_probes()
        )

        assert "neo4j_local_endpoint" not in {r["check"] for r in results}

    def test_explicit_ipv6_emits_no_compatibility_note(self) -> None:
        results = run_diagnostics(
            _config("bolt://[::1]:7687"), probes=_passing_probes()
        )

        assert "neo4j_local_endpoint" not in {r["check"] for r in results}


class TestReadFailureDoesNotMisdiagnoseSchema:
    """A failed runtime read reports connectivity, not absent schema/index."""

    def test_read_failure_reports_connectivity_not_init_hint(self) -> None:
        from memorable.runtime.doctor import NEO4J_CONNECTIVITY_HINT

        def read_failed(_config: RuntimeConfig) -> None:
            raise RuntimeError("representative read hung")

        def must_not_run(_config: RuntimeConfig):
            raise AssertionError("SHOW query ran despite read failure")

        results = run_diagnostics(
            _config(),
            probes=_passing_probes(
                ping_neo4j=read_failed,
                list_schema_constraints=must_not_run,
                list_vector_indexes=must_not_run,
            ),
        )

        by_check = _by_check(results)
        assert by_check["neo4j_connectivity"] == {
            "check": "neo4j_connectivity",
            "ok": False,
            "hint": NEO4J_CONNECTIVITY_HINT,
        }
        assert by_check["schema_constraints"]["hint"] == NEO4J_CONNECTIVITY_HINT
        assert by_check["vector_index"]["hint"] == NEO4J_CONNECTIVITY_HINT
