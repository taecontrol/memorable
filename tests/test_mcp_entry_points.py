"""Tests for MCP entry points and dependency wiring (issue #24).

Verifies:
- pyproject.toml declares mcp dependency, Python >=3.14, ruff py314
- memorable-mcp console script is declared
- src/memorable/mcp/__main__.py is importable with a callable main()
- mcp.server.fastmcp.FastMCP is importable in the test environment
"""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _load_pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


class TestPyprojectDependencies:
    def test_mcp_in_dependencies(self) -> None:
        data = _load_pyproject()
        deps = data["project"]["dependencies"]
        assert any(d.startswith("mcp") for d in deps), (
            "mcp should be in [project.dependencies]"
        )

    def test_mcp_version_constraint(self) -> None:
        data = _load_pyproject()
        deps = data["project"]["dependencies"]
        mcp_dep = next(d for d in deps if d.startswith("mcp"))
        assert ">=1.27" in mcp_dep, "mcp lower bound should be >=1.27"
        assert "<2" in mcp_dep, "mcp upper bound should be <2"


class TestPyprojectPythonVersion:
    def test_requires_python_314(self) -> None:
        data = _load_pyproject()
        assert data["project"]["requires-python"] == ">=3.14"

    def test_ruff_target_version_py314(self) -> None:
        data = _load_pyproject()
        assert data["tool"]["ruff"]["target-version"] == "py314"


class TestConsoleScript:
    def test_memorable_mcp_script_declared(self) -> None:
        data = _load_pyproject()
        scripts = data["project"]["scripts"]
        assert "memorable-mcp" in scripts, (
            "memorable-mcp console script should be in [project.scripts]"
        )

    def test_memorable_mcp_script_target(self) -> None:
        data = _load_pyproject()
        scripts = data["project"]["scripts"]
        assert scripts["memorable-mcp"] == "memorable.mcp.__main__:main"


class TestMcpMainModule:
    def test_main_is_importable(self) -> None:
        from memorable.mcp.__main__ import main

        assert main is not None

    def test_main_is_callable(self) -> None:
        from memorable.mcp.__main__ import main

        assert callable(main)


class TestFastMCPImport:
    def test_fastmcp_importable(self) -> None:
        from mcp.server.fastmcp import FastMCP

        assert FastMCP is not None
