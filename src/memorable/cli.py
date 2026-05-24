from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from memorable.core.application import InitService, build_status_payload
from memorable.core.profile import ProfileValidationError
from memorable.core.repositories import make_memory_space_repository


def _cmd_init(args: argparse.Namespace) -> int:
    """Initialize a MemorySpace from .memorable/memory.yaml."""
    base_path = Path(args.path) if args.path else Path.cwd()
    profile_path = base_path / ".memorable" / "memory.yaml"

    if not profile_path.exists():
        print(
            f"Error: No memory.yaml found at {profile_path}. "
            "Create a .memorable/memory.yaml to define your MemoryProfile.",
            file=sys.stderr,
        )
        return 1

    yaml_text = profile_path.read_text(encoding="utf-8")

    repository = make_memory_space_repository()
    service = InitService(repository=repository)

    try:
        result = service.initialize(yaml_text)
    except ProfileValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    status = "already exists" if result.already_existed else "initialized"
    print(
        json.dumps(
            {
                "space": result.space.name,
                "status": status,
                "profile_version": result.profile.version,
            },
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="memorable")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show Memorable diagnostic status.")

    init_parser = subparsers.add_parser(
        "init", help="Initialize a MemorySpace from a MemoryProfile."
    )
    init_parser.add_argument(
        "--path",
        default=None,
        help="Base directory containing .memorable/memory.yaml (default: cwd).",
    )

    args = parser.parse_args(argv)

    if args.command == "status":
        print(json.dumps(build_status_payload(), sort_keys=True))
        return 0
    elif args.command == "init":
        return _cmd_init(args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
