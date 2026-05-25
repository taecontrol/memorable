"""Tests that public interfaces and diagnostic output use domain language,
never storage vocabulary (Node, Edge, label, relationship, Cypher)."""

from __future__ import annotations

import inspect
import json

STORAGE_TERMS = {"node", "edge", "label", "relationship", "cypher"}


def _check_no_storage_terms(text: str) -> list[str]:
    """Return any storage terms found in the text."""
    lower = text.lower()
    return [term for term in STORAGE_TERMS if term in lower]


def test_core_models_use_domain_language() -> None:
    """Core models module must not use storage vocabulary in public names."""
    from memorable.core import models

    # Storage terms may appear in docstrings explaining what to avoid,
    # but not in class names, field names, or method names
    for name in dir(models):
        if name.startswith("_"):
            continue
        violations = _check_no_storage_terms(name)
        assert not violations, (
            f"Core model '{name}' uses storage vocabulary: {violations}"
        )


def test_core_ports_use_domain_language() -> None:
    """Core ports module must not use storage vocabulary in public names."""
    from memorable.core import ports

    for name in dir(ports):
        if name.startswith("_"):
            continue
        violations = _check_no_storage_terms(name)
        assert not violations, (
            f"Core port '{name}' uses storage vocabulary: {violations}"
        )


def test_diagnostic_payload_uses_domain_language() -> None:
    """Diagnostic payload must use MemorySpace, not storage terms."""
    from memorable.core.application import build_status_payload

    payload = build_status_payload()
    text = json.dumps(payload)
    violations = _check_no_storage_terms(text)
    assert not violations, (
        f"Diagnostic payload contains storage vocabulary: {violations}"
    )
    # Must contain domain terms
    assert "MemorySpace" in text


def test_cli_diagnostic_uses_memory_space_language() -> None:
    """CLI output must say MemorySpace, not storage vocabulary."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    src_path = str(project_root / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        src_path if not existing else f"{src_path}{os.pathsep}{existing}"
    )

    result = subprocess.run(
        [sys.executable, "-m", "memorable.cli", "status"],
        cwd=project_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    output = result.stdout
    violations = _check_no_storage_terms(output)
    assert not violations, f"CLI output contains storage vocabulary: {violations}"
    assert "MemorySpace" in output


def test_mcp_diagnostic_uses_memory_space_language() -> None:
    """MCP tool output must say MemorySpace, not storage vocabulary."""
    from memorable.mcp.server import status_tool

    payload = status_tool()
    text = json.dumps(payload)
    violations = _check_no_storage_terms(text)
    assert not violations, f"MCP output contains storage vocabulary: {violations}"
    assert "MemorySpace" in text


def test_neo4j_adapter_public_api_uses_domain_language() -> None:
    """Neo4j adapter's public methods and parameters must use domain language."""
    from memorable.storage.neo4j.repository import Neo4jMemorySpaceRepository

    for name in dir(Neo4jMemorySpaceRepository):
        if name.startswith("_"):
            continue
        violations = _check_no_storage_terms(name)
        assert not violations, (
            f"Adapter method '{name}' uses storage vocabulary: {violations}"
        )

        method = getattr(Neo4jMemorySpaceRepository, name)
        if callable(method):
            sig = inspect.signature(method)
            for param_name in sig.parameters:
                if param_name == "self":
                    continue
                violations = _check_no_storage_terms(param_name)
                assert not violations, (
                    f"Adapter parameter '{param_name}' in '{name}' "
                    f"uses storage vocabulary: {violations}"
                )
