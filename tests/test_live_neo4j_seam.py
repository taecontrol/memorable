"""Smoke coverage for the shared live-Neo4j test seam.

The test harness must resolve "which Neo4j" the same way the live runtime does:
through the layered ``RuntimeConfig`` built by ``load_runtime_config(...)`` with
process-environment overrides honored. This guards the parity property at the
heart of PRD #191 — a passing live-Neo4j test targets the runtime the product
would actually reach, not a flat env read that ignores config-file layering.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from live_neo4j import build_live_neo4j_driver


def test_build_live_neo4j_driver_resolves_uri_from_layered_runtime_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # A process-supplied URI override is the case live runtime honors via
    # load_runtime_config(include_environment_overrides=True). If the seam drops
    # the override (default False), it would silently target the IPv4 default.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MEMORABLE_NEO4J_URI", "bolt://resolved.example:7687")
    monkeypatch.setenv("MEMORABLE_NEO4J_USER", "neo4j")
    monkeypatch.setenv("MEMORABLE_NEO4J_PASSWORD", "secret")

    with patch("live_neo4j.GraphDatabase") as mock_gdb:
        build_live_neo4j_driver()

    assert mock_gdb.driver.call_args.args[0] == "bolt://resolved.example:7687"
    assert mock_gdb.driver.call_args.kwargs["auth"] == ("neo4j", "secret")
