"""Regression coverage for local/remote Neo4j runtime parity (PRD #184, #188).

These tests lock the hardened connection contract as a *product/runtime* contract
across the live-command boundary, rather than re-testing private helpers:

- Every live driver-construction path (production context used by CLI + MCP,
  diagnostics) resolves a configured URI through the one shared connection
  policy, so local IPv4, ``localhost`` compatibility, explicit IPv6, custom
  ports, non-local hosts, and cloud schemes behave identically everywhere.
- ``db status`` keeps reporting *configured* values and sources (ADR-0016),
  intentionally distinct from the live effective connection.
- Remote/cloud configuration is never normalized into a local runtime path.
- The test-harness-only ``Neo4jConfig`` shape stays out of every live module so
  it cannot drift back into a second/third production connection-config path.

The policy boundary (``resolve_bolt_uri``) is used as the oracle for the
effective URI, so coverage is deterministic without a live Neo4j.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from memorable.config import Neo4jSettings, RuntimeConfig
from memorable.storage.neo4j.connection import resolve_bolt_uri
from memorable.storage.production import build_production_context

REPO_ROOT = Path(__file__).resolve().parents[1]

# (configured uri, expected effective uri for a live connection, is remote/cloud)
LOCAL_CASES = [
    ("bolt://127.0.0.1:7687", "bolt://127.0.0.1:7687"),
    ("bolt://localhost:7687", "bolt://127.0.0.1:7687"),
    ("bolt://[::1]:7687", "bolt://[::1]:7687"),
    ("bolt://localhost:7999", "bolt://127.0.0.1:7999"),
    ("bolt://127.0.0.1:7999", "bolt://127.0.0.1:7999"),
    ("neo4j://localhost:7687", "neo4j://127.0.0.1:7687"),
]
REMOTE_CASES = [
    "bolt://neo4j.internal.example.com:7687",
    "neo4j+s://abcd1234.databases.neo4j.io",
    "neo4j+ssc://abcd1234.databases.neo4j.io",
]
ALL_CASES = [(uri, eff) for uri, eff in LOCAL_CASES] + [
    (uri, uri) for uri in REMOTE_CASES
]


def _config(uri: str) -> RuntimeConfig:
    return RuntimeConfig(neo4j=Neo4jSettings(uri=uri, user="neo4j", password="secret"))


def _patched_driver():
    """Patch the single connection seam; return (patcher, GraphDatabase, driver)."""
    patcher = patch("memorable.storage.neo4j.connection.GraphDatabase")
    mock_gdb = patcher.start()
    driver = mock_gdb.driver.return_value
    driver.verify_connectivity.return_value = None
    return patcher, mock_gdb, driver


def _doctor_probes():
    """DiagnosticProbes that pass without touching a live runtime or model."""
    from memorable.runtime.doctor import DiagnosticProbes

    class _Provider:
        def embed(self, _text: str) -> list[float]:
            return [0.0] * 384

    return DiagnosticProbes(
        ping_neo4j=lambda _config: None,
        list_schema_constraints=lambda _config: [],
        list_vector_indexes=lambda _config: [],
        build_embedding_provider=lambda _settings, api_key=None: _Provider(),
        load_profile_from_yaml=lambda _yaml_text: object(),
    )


def _write_workspace(base: Path) -> None:
    """Create a minimal .memorable/memory.yaml so ``init`` has a profile."""
    memorable_dir = base / ".memorable"
    memorable_dir.mkdir(parents=True, exist_ok=True)
    (memorable_dir / "memory.yaml").write_text(
        "version: 1\n"
        "space:\n"
        "  name: test-project\n"
        "  description: Test\n"
        "entities:\n"
        "  - name: Project\n",
        encoding="utf-8",
    )


class TestProductionPathAppliesConnectionPolicy:
    """The production context (the path CLI + MCP share) applies the policy."""

    @pytest.mark.parametrize("configured,effective", ALL_CASES)
    def test_driver_constructed_with_effective_uri(
        self, configured: str, effective: str
    ) -> None:
        # The policy boundary is the oracle for the effective URI.
        assert resolve_bolt_uri(configured) == effective

        patcher, mock_gdb, driver = _patched_driver()
        try:
            ctx, returned = build_production_context(_config(configured))
        finally:
            patcher.stop()

        assert mock_gdb.driver.call_args.args[0] == effective
        assert returned is driver


class TestCliAndMcpShareEffectiveConnection:
    """Human CLI and agent-facing MCP reach the same effective live connection.

    A configured ``localhost`` runtime must connect over IPv4 loopback through
    both entrypoints, because both build production context via the one shared
    driver-construction path.
    """

    def test_cli_production_command_connects_over_ipv4_for_localhost(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from memorable.cli import main

        _write_workspace(tmp_path)
        monkeypatch.chdir(tmp_path)
        config = _config("bolt://localhost:7687")

        patcher, mock_gdb, driver = _patched_driver()
        try:
            with (
                patch("memorable.cli.load_runtime_config", return_value=config),
                patch("memorable.cli.ensure_all_constraints"),
                patch("memorable.cli.InitService") as mock_init,
            ):
                result = MagicMock()
                result.already_existed = False
                result.space.name = "test-project"
                result.profile.version = 1
                mock_init.return_value.initialize.return_value = result

                rc = main(["init", "--path", str(tmp_path)])
        finally:
            patcher.stop()

        assert rc == 0
        assert mock_gdb.driver.call_args.args[0] == "bolt://127.0.0.1:7687"
        driver.close.assert_called_once()

    def test_mcp_production_path_connects_over_ipv4_for_localhost(self) -> None:
        from memorable.mcp.__main__ import main
        from memorable.mcp.server import mcp_server

        config = _config("bolt://localhost:7687")

        patcher, mock_gdb, driver = _patched_driver()
        try:
            with (
                patch(
                    "memorable.mcp.__main__.load_runtime_config",
                    return_value=config,
                ),
                patch.object(mcp_server, "run"),
                patch("memorable.mcp.__main__.set_mcp_context"),
            ):
                main()
        finally:
            patcher.stop()

        assert mock_gdb.driver.call_args.args[0] == "bolt://127.0.0.1:7687"
        driver.close.assert_called_once()


class TestDbStatusStaysConfiguredNotEffective:
    """``db status`` reports configured values + sources (ADR-0016), not the
    live-rewritten URI. The live policy resolution is intentionally distinct.
    """

    def test_db_status_reports_configured_localhost_not_ipv4(
        self, tmp_path: Path, capsys
    ) -> None:
        from memorable.cli import main

        config = _config("bolt://localhost:7687")
        with patch("memorable.cli.load_runtime_config", return_value=config):
            rc = main(["db", "status", "--path", str(tmp_path)])

        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        # db status reports the CONFIGURED uri verbatim ...
        assert payload["neo4j"]["uri"]["value"] == "bolt://localhost:7687"
        # ... while the live policy would connect over IPv4 loopback.
        assert resolve_bolt_uri(config.neo4j.uri) == "bolt://127.0.0.1:7687"

    def test_doctor_reflects_live_ipv4_endpoint_while_status_reports_localhost(
        self, tmp_path: Path, capsys
    ) -> None:
        from memorable.cli import main
        from memorable.runtime.doctor import run_diagnostics

        config = _config("bolt://localhost:7687")

        # db status: configured localhost (ADR-0016 file-resolved reporting).
        with patch("memorable.cli.load_runtime_config", return_value=config):
            main(["db", "status", "--path", str(tmp_path)])
        status = json.loads(capsys.readouterr().out)
        assert status["neo4j"]["uri"]["value"] == "bolt://localhost:7687"

        # doctor (a live diagnostic surface) reflects the IPv4 effective endpoint.
        results = run_diagnostics(config, probes=_doctor_probes())
        note = {result["check"]: result for result in results}["neo4j_local_endpoint"]
        assert note["ok"] is True
        assert "127.0.0.1" in note["hint"]


class TestRemoteConfigurationIsNotLocalized:
    """Remote/cloud configuration is preserved exactly and stays remote."""

    @pytest.mark.parametrize("uri", REMOTE_CASES)
    def test_remote_uri_preserved_and_classified_remote(self, uri: str) -> None:
        from memorable.runtime.docker import is_remote_uri

        assert resolve_bolt_uri(uri) == uri
        assert is_remote_uri(uri) is True

        patcher, mock_gdb, driver = _patched_driver()
        try:
            build_production_context(_config(uri))
        finally:
            patcher.stop()

        assert mock_gdb.driver.call_args.args[0] == uri

    @pytest.mark.parametrize(
        "uri",
        ["bolt://localhost:7687", "bolt://127.0.0.1:7687", "bolt://[::1]:7687"],
    )
    def test_local_loopback_classified_local(self, uri: str) -> None:
        from memorable.runtime.docker import is_remote_uri

        assert is_remote_uri(uri) is False


class TestNeo4jConfigStaysOutOfLivePath:
    """``Neo4jConfig`` is test-harness-only and must not re-enter live modules."""

    LIVE_MODULES = (
        "src/memorable/storage/production.py",
        "src/memorable/storage/neo4j/connection.py",
        "src/memorable/runtime/doctor.py",
        "src/memorable/cli.py",
        "src/memorable/mcp/server.py",
        "src/memorable/mcp/__main__.py",
    )

    @pytest.mark.parametrize("rel", LIVE_MODULES)
    def test_live_module_does_not_reference_neo4jconfig(self, rel: str) -> None:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "Neo4jConfig" not in text, (
            f"{rel} must build drivers via the shared connection policy, "
            "not the test-harness-only Neo4jConfig"
        )

    def test_config_module_marks_neo4jconfig_test_harness_only(self) -> None:
        text = (REPO_ROOT / "src/memorable/storage/neo4j/config.py").read_text(
            encoding="utf-8"
        )
        assert "TEST-HARNESS-ONLY" in text
