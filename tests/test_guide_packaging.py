"""Packaging guarantee for the guide topic markdown (issue #143).

The ``memorable_guide`` tool reads ``.md`` files from ``memorable/guide/topics/``
at runtime via ``importlib.resources``. On a fresh ``pip install memorable-kg``
(no repo checkout) those files must be inside the wheel, or the guide returns
nothing useful. Hatchling includes non-Python files in a package by default,
but nothing has verified it — this test builds the wheel and asserts every
topic markdown is present so a packaging regression fails loud.

Marked ``integration`` because it shells out to the build backend (slow, may
touch the network) and so it joins the other out-of-band subprocess tests
instead of the fast default suite. The existing ``integration`` marker is the
de-facto "out-of-band / spawns a subprocess" bucket here (the MCP stdio test
uses it without needing Neo4j), so reusing it keeps the suite simple.

Run with: uv run --extra dev pytest tests/test_guide_packaging.py -m integration
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path
from typing import get_args

import pytest

from memorable.guide import GuideTopicName

pytestmark = pytest.mark.integration

# Repo root: this file lives at <root>/tests/test_guide_packaging.py.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _build_wheel(out_dir: Path) -> Path:
    """Build a wheel of the project into *out_dir* and return its path.

    Uses ``uv build --wheel`` because ``build`` is not a project dependency
    while ``uv`` is the mandated tool for every Python task in this repo, so
    it is the reliably available build path here. ``sys.executable`` anchors
    the invocation to the active interpreter rather than a bare ``python``.
    """
    subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(out_dir),
            str(_PROJECT_ROOT),
        ],
        check=True,
        capture_output=True,
        text=True,
        env={"UV_PYTHON": sys.executable, "PATH": _path_env()},
    )

    wheels = sorted(out_dir.glob("*.whl"))
    assert wheels, f"uv build produced no wheel in {out_dir}"
    assert len(wheels) == 1, f"Expected exactly one wheel, found: {wheels}"
    return wheels[0]


def _path_env() -> str:
    import os

    return os.environ.get("PATH", "")


def test_wheel_ships_every_guide_topic_markdown(tmp_path: Path) -> None:
    wheel_path = _build_wheel(tmp_path)

    with zipfile.ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())

    expected = {
        f"memorable/guide/topics/{topic}.md" for topic in get_args(GuideTopicName)
    }
    missing = sorted(name for name in expected if name not in names)

    assert not missing, (
        f"Guide topic markdown missing from wheel {wheel_path.name}: "
        f"{missing}. The memorable_guide tool reads these at runtime, so a "
        f"fresh install of memorable-kg would render empty topics."
    )
