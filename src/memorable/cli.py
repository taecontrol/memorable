from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from memorable.core.application import (
    CurrentTruthService,
    InitService,
    InspectDecisionHistoryService,
    InspectProvenanceService,
    PointInTimeTruthService,
    RememberDecisionService,
    RememberEntityService,
    build_status_payload,
)
from memorable.core.context import default_context
from memorable.core.profile import ProfileValidationError
from memorable.core.repositories import make_memory_space_repository
from memorable.core.temporal import parse_iso_timestamp


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


def _cmd_remember_entity(args: argparse.Namespace) -> int:
    """Remember an Entity with provenance."""
    try:
        profile = default_context.load_profile(args.space)
    except ProfileValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    service = RememberEntityService(
        repository=default_context.entity_repo, profile=profile
    )

    at = parse_iso_timestamp(args.at)

    try:
        result = service.remember(
            space=args.space,
            entity_id=args.id,
            entity_type=args.type,
            name=args.name,
            source_id=args.source,
            at=at,
            writer=getattr(args, "writer", "agent:memorable"),
            reason=getattr(args, "reason", ""),
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "entity_id": result.entity.id,
                "entity_type": result.entity.entity_type,
                "name": result.entity.name,
                "space": result.entity.space,
                "source": result.provenance.source_id,
                "episode": result.provenance.episode_id,
                "creation_time": result.provenance.creation_time.isoformat(),
                "validity_time": result.provenance.validity_time.isoformat(),
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_inspect_provenance(args: argparse.Namespace) -> int:
    """Inspect provenance for a remembered Entity."""
    inspector = InspectProvenanceService(repository=default_context.entity_repo)
    provenance = inspector.inspect(space=args.space, entity_id=args.id)

    if provenance is None:
        print(
            f"Error: No provenance found for '{args.id}' "
            f"in MemorySpace '{args.space}'.",
            file=sys.stderr,
        )
        return 1

    print(f"Provenance for {provenance.entity_id}")
    print(f"  - Source: {provenance.source_id}")
    print(f"  - Episode: {provenance.episode_id}")
    print(f"  - Writer: {provenance.writer}")
    print(f"  - Creation Time: {provenance.creation_time.isoformat()}")
    print(f"  - Validity Time: {provenance.validity_time.isoformat()}")
    if provenance.reason:
        print(f"  - Reason: {provenance.reason}")
    return 0


def _cmd_remember_decision(args: argparse.Namespace) -> int:
    """Remember a Decision with provenance."""
    try:
        profile = default_context.load_profile(args.space)
    except ProfileValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    service = RememberDecisionService(
        repository=default_context.decision_repo, profile=profile
    )

    at = parse_iso_timestamp(args.at)
    supersedes = getattr(args, "supersedes", None)

    try:
        result = service.remember(
            space=args.space,
            decision_id=args.id,
            statement=args.statement,
            source_id=args.source,
            at=at,
            writer=getattr(args, "writer", "agent:memorable"),
            reason=getattr(args, "reason", ""),
            supersedes=supersedes,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "decision_id": result.decision.id,
                "statement": result.decision.statement,
                "space": result.decision.space,
                "source": result.provenance.source_id,
                "episode": result.provenance.episode_id,
                "creation_time": result.provenance.creation_time.isoformat(),
                "validity_time": result.provenance.validity_time.isoformat(),
                "lifecycle_state": result.decision.lifecycle_state,
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_truth_current(args: argparse.Namespace) -> int:
    """Show the current truth for a Decision, following supersession chain."""
    service = CurrentTruthService(repository=default_context.decision_repo)
    decision = service.current(space=args.space, decision_id=args.id)

    if decision is None:
        print(
            f"Error: No Decision found for '{args.id}' "
            f"in MemorySpace '{args.space}'.",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "decision_id": decision.id,
                "statement": decision.statement,
                "space": decision.space,
                "lifecycle_state": decision.lifecycle_state,
                "validity_time": decision.validity_time.isoformat(),
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_truth_as_of(args: argparse.Namespace) -> int:
    """Show the Decision that was valid at a specific time."""
    service = PointInTimeTruthService(repository=default_context.decision_repo)
    at = parse_iso_timestamp(args.at)
    decision = service.at(space=args.space, decision_id=args.id, at=at)

    if decision is None:
        print(
            f"Error: No Decision found for '{args.id}' "
            f"in MemorySpace '{args.space}' at {at.isoformat()}.",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "decision_id": decision.id,
                "statement": decision.statement,
                "space": decision.space,
                "lifecycle_state": decision.lifecycle_state,
                "validity_time": decision.validity_time.isoformat(),
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_inspect_history(args: argparse.Namespace) -> int:
    """Show the full supersession chain for a Decision."""
    service = InspectDecisionHistoryService(repository=default_context.decision_repo)
    history = service.history(space=args.space, decision_id=args.id)

    if not history:
        print(
            f"Error: No Decision found for '{args.id}' "
            f"in MemorySpace '{args.space}'.",
            file=sys.stderr,
        )
        return 1

    print(f"Decision history for {args.id}")
    for i, decision in enumerate(history):
        print(f"  [{i + 1}] {decision.id}")
        print(f"      Statement: {decision.statement}")
        print(f"      Lifecycle: {decision.lifecycle_state}")
        print(f"      Valid from: {decision.validity_time.isoformat()}")
        if decision.invalidation_time:
            print(f"      Invalidated: {decision.invalidation_time.isoformat()}")
        if decision.supersedes:
            print(f"      Supersedes: {decision.supersedes}")
        if decision.superseded_by:
            print(f"      Superseded by: {decision.superseded_by}")
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

    # remember entity subcommand
    remember_parser = subparsers.add_parser(
        "remember", help="Remember structured memory."
    )
    remember_sub = remember_parser.add_subparsers(
        dest="remember_type", required=True
    )
    entity_parser = remember_sub.add_parser(
        "entity", help="Remember an Entity with provenance."
    )
    entity_parser.add_argument("--space", required=True)
    entity_parser.add_argument("--id", required=True)
    entity_parser.add_argument("--type", required=True)
    entity_parser.add_argument("--name", required=True)
    entity_parser.add_argument("--source", required=True)
    entity_parser.add_argument("--at", required=True)
    entity_parser.add_argument("--writer", default="agent:memorable")
    entity_parser.add_argument("--reason", default="")

    # remember decision subcommand
    decision_parser = remember_sub.add_parser(
        "decision", help="Remember a Decision with provenance."
    )
    decision_parser.add_argument("--space", required=True)
    decision_parser.add_argument("--id", required=True)
    decision_parser.add_argument("--statement", required=True)
    decision_parser.add_argument("--source", required=True)
    decision_parser.add_argument("--at", required=True)
    decision_parser.add_argument("--supersedes", default=None)
    decision_parser.add_argument("--writer", default="agent:memorable")
    decision_parser.add_argument("--reason", default="")

    # truth subcommands
    truth_parser = subparsers.add_parser(
        "truth", help="Query temporal truth."
    )
    truth_sub = truth_parser.add_subparsers(
        dest="truth_type", required=True
    )
    current_parser = truth_sub.add_parser(
        "current", help="Show current truth for a Decision."
    )
    current_parser.add_argument("--space", required=True)
    current_parser.add_argument("--id", required=True)

    as_of_parser = truth_sub.add_parser(
        "as-of", help="Show truth at a specific point in time."
    )
    as_of_parser.add_argument("--space", required=True)
    as_of_parser.add_argument("--id", required=True)
    as_of_parser.add_argument("--at", required=True)

    # inspect provenance subcommand
    inspect_parser = subparsers.add_parser(
        "inspect", help="Inspect memory metadata."
    )
    inspect_sub = inspect_parser.add_subparsers(
        dest="inspect_type", required=True
    )
    prov_parser = inspect_sub.add_parser(
        "provenance", help="Inspect provenance for a remembered Entity."
    )
    prov_parser.add_argument("--space", required=True)
    prov_parser.add_argument("--id", required=True)

    history_parser = inspect_sub.add_parser(
        "history", help="Inspect supersession history for a Decision."
    )
    history_parser.add_argument("--space", required=True)
    history_parser.add_argument("--id", required=True)

    args = parser.parse_args(argv)

    if args.command == "status":
        print(json.dumps(build_status_payload(), sort_keys=True))
        return 0
    elif args.command == "init":
        return _cmd_init(args)
    elif args.command == "remember":
        if args.remember_type == "entity":
            return _cmd_remember_entity(args)
        elif args.remember_type == "decision":
            return _cmd_remember_decision(args)
    elif args.command == "truth":
        if args.truth_type == "current":
            return _cmd_truth_current(args)
        elif args.truth_type == "as-of":
            return _cmd_truth_as_of(args)
    elif args.command == "inspect":
        if args.inspect_type == "provenance":
            return _cmd_inspect_provenance(args)
        elif args.inspect_type == "history":
            return _cmd_inspect_history(args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
