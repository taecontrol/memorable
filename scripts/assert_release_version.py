#!/usr/bin/env python3
"""Assert a release tag matches the package version."""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    expected_tag = f"v{_read_project_version(args.pyproject)}"
    if args.tag != expected_tag:
        print(
            f"tag {args.tag} does not match pyproject.toml version "
            f"{expected_tag.removeprefix('v')}",
            file=sys.stderr,
        )
        return 1

    print(f"release tag {args.tag} matches pyproject.toml")
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assert the release tag matches pyproject.toml version."
    )
    parser.add_argument("--tag", required=True, help="Git tag name, such as v0.0.1.")
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=Path("pyproject.toml"),
        help="Path to pyproject.toml.",
    )
    return parser.parse_args(argv)


def _read_project_version(pyproject: Path) -> str:
    document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    version = document["project"]["version"]
    if not isinstance(version, str):
        raise TypeError("project.version must be a string")
    return version


if __name__ == "__main__":
    raise SystemExit(main())
