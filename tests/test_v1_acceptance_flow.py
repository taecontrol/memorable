"""Black-box V1 acceptance flow entry point.

The reusable script drives the CLI and MCP surfaces only. This pytest wrapper
exists so CI/release jobs can run the same flow with a real Neo4j service.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_v1_acceptance_flow_runs_against_real_neo4j() -> None:
    if "MEMORABLE_NEO4J_URI" not in os.environ:
        pytest.skip("MEMORABLE_NEO4J_URI is not set")

    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required to run the project console entry point")

    project_root = Path(__file__).resolve().parents[1]
    script_path = project_root / "scripts" / "v1_acceptance.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--memorable-cmd",
            f"{uv} run --project {project_root} memorable",
            "--mcp-cmd",
            f"{uv} run --project {project_root} memorable-mcp",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=420,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "V1 acceptance flow complete" in result.stdout
