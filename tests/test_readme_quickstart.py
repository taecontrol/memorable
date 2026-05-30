from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"


def test_pypi_readme_guides_install_to_first_decision() -> None:
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    readme = README.read_text(encoding="utf-8")

    assert pyproject["project"]["readme"] == "README.md"

    required_fragments = [
        "uvx --from memorable-kg memorable",
        "uv tool install memorable-kg",
        "memorable db start",
        "memorable init",
        "memorable doctor",
        "memorable remember decision",
        "memorable search --query",
    ]
    for fragment in required_fragments:
        assert fragment in readme

    normalized_readme = " ".join(readme.lower().split())
    assert "no `write_policy` block" in readme
    assert "kernel record types persist immediately" in normalized_readme

    ordered_flow = [
        "memorable db start",
        "memorable init",
        "memorable doctor",
        "memorable remember decision",
        "memorable search --query",
    ]
    positions = [readme.index(step) for step in ordered_flow]
    assert positions == sorted(positions)
