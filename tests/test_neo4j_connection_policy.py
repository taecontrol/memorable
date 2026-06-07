"""Tests for the shared Neo4j connection policy (deep module boundary).

The policy is the single driver-construction path for live runtime callers. It
resolves ambiguous `localhost` to IPv4 loopback for the live connection while
preserving explicit IPv4, explicit IPv6, custom ports, non-local hosts, and
remote/cloud schemes. It applies bounded fail-fast connection settings so
runtime failures become actionable instead of multi-minute stalls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from memorable.config import Neo4jSettings, RuntimeConfig


def _config(uri: str) -> RuntimeConfig:
    return RuntimeConfig(neo4j=Neo4jSettings(uri=uri, user="neo4j", password="secret"))


class TestResolveBoltUri:
    """resolve_bolt_uri rewrites only ambiguous local `localhost` to IPv4."""

    def test_localhost_is_rewritten_to_ipv4_loopback(self) -> None:
        from memorable.storage.neo4j.connection import resolve_bolt_uri

        assert resolve_bolt_uri("bolt://localhost:7687") == "bolt://127.0.0.1:7687"

    def test_explicit_ipv4_loopback_is_preserved(self) -> None:
        from memorable.storage.neo4j.connection import resolve_bolt_uri

        assert resolve_bolt_uri("bolt://127.0.0.1:7687") == "bolt://127.0.0.1:7687"

    def test_explicit_ipv6_loopback_is_preserved(self) -> None:
        from memorable.storage.neo4j.connection import resolve_bolt_uri

        assert resolve_bolt_uri("bolt://[::1]:7687") == "bolt://[::1]:7687"

    def test_custom_local_port_is_preserved(self) -> None:
        from memorable.storage.neo4j.connection import resolve_bolt_uri

        assert resolve_bolt_uri("bolt://localhost:7688") == "bolt://127.0.0.1:7688"

    def test_non_local_host_is_preserved(self) -> None:
        from memorable.storage.neo4j.connection import resolve_bolt_uri

        assert resolve_bolt_uri("bolt://prod-server:7687") == "bolt://prod-server:7687"

    def test_cloud_scheme_is_preserved_exactly(self) -> None:
        from memorable.storage.neo4j.connection import resolve_bolt_uri

        assert (
            resolve_bolt_uri("neo4j+s://cloud.neo4j.io:7687")
            == "neo4j+s://cloud.neo4j.io:7687"
        )

    def test_neo4j_scheme_localhost_is_rewritten_to_ipv4(self) -> None:
        from memorable.storage.neo4j.connection import resolve_bolt_uri

        assert resolve_bolt_uri("neo4j://localhost:7687") == "neo4j://127.0.0.1:7687"


class TestConnect:
    """connect builds one verified, fail-fast driver for live callers."""

    def test_connects_to_resolved_ipv4_endpoint_for_localhost_config(self) -> None:
        from memorable.storage.neo4j.connection import connect

        with patch("memorable.storage.neo4j.connection.GraphDatabase") as mock_gdb:
            mock_driver = MagicMock()
            mock_driver.verify_connectivity.return_value = None
            mock_gdb.driver.return_value = mock_driver

            driver = connect(_config("bolt://localhost:7687"))

        mock_driver.verify_connectivity.assert_called_once()
        connect_uri = mock_gdb.driver.call_args.args[0]
        assert connect_uri == "bolt://127.0.0.1:7687"
        driver.close()
        mock_driver.close.assert_called_once()

    def test_applies_auth_fail_fast_and_notification_suppression(self) -> None:
        from memorable.storage.neo4j.connection import (
            CONNECTION_TIMEOUT_SECONDS,
            MAX_TRANSACTION_RETRY_TIME_SECONDS,
            connect,
        )

        with patch("memorable.storage.neo4j.connection.GraphDatabase") as mock_gdb:
            mock_driver = MagicMock()
            mock_driver.verify_connectivity.return_value = None
            mock_gdb.driver.return_value = mock_driver

            connect(_config("bolt://prod-server:7687"))

        kwargs = mock_gdb.driver.call_args.kwargs
        assert kwargs["auth"] == ("neo4j", "secret")
        assert kwargs["notifications_disabled_classifications"] == ["UNRECOGNIZED"]
        assert kwargs["connection_timeout"] == CONNECTION_TIMEOUT_SECONDS
        assert (
            kwargs["max_transaction_retry_time"] == MAX_TRANSACTION_RETRY_TIME_SECONDS
        )
        # Non-local host is preserved exactly.
        assert mock_gdb.driver.call_args.args[0] == "bolt://prod-server:7687"

    def test_sessions_open_against_configured_database(self) -> None:
        from memorable.storage.neo4j.connection import connect

        configs = [
            ("default", _config("bolt://prod-server:7687"), "neo4j"),
            (
                "overridden",
                RuntimeConfig(
                    neo4j=Neo4jSettings(
                        uri="bolt://prod-server:7687",
                        user="neo4j",
                        password="secret",
                        database="memory_prod",
                    )
                ),
                "memory_prod",
            ),
        ]

        for label, config, expected_database in configs:
            with patch("memorable.storage.neo4j.connection.GraphDatabase") as mock_gdb:
                mock_driver = MagicMock()
                mock_driver.verify_connectivity.return_value = None
                mock_gdb.driver.return_value = mock_driver

                driver = connect(config)
                mock_driver.session.reset_mock()
                driver.session()

            try:
                mock_driver.session.assert_called_once_with(database=expected_database)
            except AssertionError as exc:
                raise AssertionError(label) from exc

    def test_failure_closes_driver_and_names_configured_uri_and_database(
        self,
    ) -> None:
        import pytest

        from memorable.storage.neo4j.connection import connect

        config = RuntimeConfig(
            neo4j=Neo4jSettings(
                uri="bolt://localhost:7687",
                user="neo4j",
                password="secret",
                database="missing_database",
            )
        )

        with patch("memorable.storage.neo4j.connection.GraphDatabase") as mock_gdb:
            mock_driver = MagicMock()
            mock_driver.verify_connectivity.return_value = None
            probe_session = mock_driver.session.return_value.__enter__.return_value
            probe_result = probe_session.run.return_value
            probe_result.consume.side_effect = Exception("database not found")
            mock_gdb.driver.return_value = mock_driver

            with pytest.raises(ConnectionError) as excinfo:
                connect(config)

        message = str(excinfo.value)
        # Error names the configured URI, not the IPv4-rewritten one.
        assert "bolt://localhost:7687" in message
        assert "missing_database" in message
        assert "database not found" in message
        assert "memorable db start" in message
        mock_driver.verify_connectivity.assert_called_once_with()
        mock_driver.session.assert_called_once_with(database="missing_database")
        probe_session.run.assert_called_once_with("RETURN 1")
        probe_result.consume.assert_called_once_with()
        mock_driver.close.assert_called_once()
