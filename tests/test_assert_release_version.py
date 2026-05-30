from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSERT_RELEASE_VERSION = ROOT / "scripts" / "assert_release_version.py"


def test_release_tag_must_match_pyproject_version() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ASSERT_RELEASE_VERSION),
            "--tag",
            "v0.0.2",
            "--pyproject",
            str(ROOT / "pyproject.toml"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "tag v0.0.2 does not match pyproject.toml version 0.0.1" in result.stderr


def test_release_tag_matching_pyproject_version_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ASSERT_RELEASE_VERSION),
            "--tag",
            "v0.0.1",
            "--pyproject",
            str(ROOT / "pyproject.toml"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "release tag v0.0.1 matches pyproject.toml" in result.stdout
