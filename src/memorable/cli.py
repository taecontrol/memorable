from __future__ import annotations

import argparse
import json

from memorable.core.application import build_status_payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="memorable")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show Memorable diagnostic status.")

    args = parser.parse_args(argv)

    if args.command == "status":
        print(json.dumps(build_status_payload(), sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
