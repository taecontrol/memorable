from __future__ import annotations

import argparse
import json
from typing import Protocol

from memorable.core.application import DiagnosticService


class StatusService(Protocol):
    def status(self) -> dict[str, object]:
        """Return a Memorable Core diagnostic payload."""


def build_status_payload(service: StatusService | None = None) -> dict[str, object]:
    diagnostic_service = service or DiagnosticService()
    return diagnostic_service.status()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="memorable")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show Memorable diagnostic status.")

    args = parser.parse_args(argv)

    if args.command == "status":
        print(json.dumps(build_status_payload(), sort_keys=True))
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

