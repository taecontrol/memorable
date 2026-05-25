from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal, cast

from memorable.config import load_runtime_config
from memorable.core.application import (
    CompleteTaskService,
    CurrentTruthService,
    InitService,
    InspectDecisionHistoryService,
    InspectProvenanceService,
    InspectTaskService,
    PointInTimeTruthService,
    RememberDecisionService,
    RememberEntityService,
    RememberTaskService,
    build_status_payload,
)
from memorable.core.context import ApplicationContext, default_context
from memorable.core.profile import ProfileValidationError, load_profile_from_yaml
from memorable.core.temporal import parse_iso_timestamp
from memorable.core.tracer import TracerService
from memorable.runtime.docker import eject as docker_eject
from memorable.runtime.docker import is_remote_uri
from memorable.runtime.docker import start as docker_start
from memorable.runtime.docker import stop as docker_stop
from memorable.storage.neo4j.repository import ensure_all_constraints
from memorable.storage.production import build_production_context


def resolve_space(space_arg: str | None) -> str:
    """Resolve the MemorySpace name from --space flag or .memorable/memory.yaml.

    If *space_arg* is provided (not None), it wins immediately.
    Otherwise, reads ``.memorable/memory.yaml`` from the current working
    directory and returns the ``space.name`` field.

    Raises:
        SystemExit: With a helpful message when neither source is available.
    """
    if space_arg is not None:
        return space_arg

    profile_path = Path.cwd() / ".memorable" / "memory.yaml"
    if profile_path.exists():
        yaml_text = profile_path.read_text(encoding="utf-8")
        profile = load_profile_from_yaml(yaml_text)
        return profile.space.name

    print(
        "Error: No --space flag provided and no .memorable/memory.yaml found.\n"
        "Either pass --space <name> or create a MemoryProfile with "
        "'memorable init'.",
        file=sys.stderr,
    )
    raise SystemExit(1)


# =====================================================================
# Commands that do NOT need a production context
# =====================================================================


def _cmd_db_status(args: argparse.Namespace) -> int:
    """Print resolved runtime configuration with value sources."""
    base_path = Path(args.path) if args.path else None
    config = load_runtime_config(base_path=base_path)

    def _field_entry(value: object, field_path: str) -> dict[str, str]:
        source = config.sources.get(field_path, "built-in")
        # Mask password
        if field_path.endswith(".password"):
            return {"value": "***", "source": source}
        return {"value": str(value), "source": source}

    output = {
        "neo4j": {
            "uri": _field_entry(config.neo4j.uri, "neo4j.uri"),
            "user": _field_entry(config.neo4j.user, "neo4j.user"),
            "password": _field_entry(config.neo4j.password, "neo4j.password"),
        },
        "docker": {
            "neo4j_version": _field_entry(
                config.docker.neo4j_version, "docker.neo4j_version"
            ),
            "http_port": _field_entry(config.docker.http_port, "docker.http_port"),
            "bolt_port": _field_entry(config.docker.bolt_port, "docker.bolt_port"),
        },
        "embeddings": {
            "provider": _field_entry(config.embeddings.provider, "embeddings.provider"),
            "model": _field_entry(config.embeddings.model, "embeddings.model"),
        },
    }

    print(json.dumps(output, indent=2))
    return 0


def _cmd_db_start(args: argparse.Namespace) -> int:
    """Start the local Neo4j container."""
    base_path = Path(args.path) if args.path else None
    config = load_runtime_config(base_path=base_path)

    if is_remote_uri(config.neo4j.uri):
        print(
            "Using remote Neo4j, no local container to manage.",
            file=sys.stderr,
        )
        return 1

    result = docker_start(config)
    if not result.success:
        print(f"Error: {result.message}", file=sys.stderr)
        return 1
    print(result.message)
    return 0


def _cmd_db_stop(args: argparse.Namespace) -> int:
    """Stop the local Neo4j container."""
    base_path = Path(args.path) if args.path else None
    config = load_runtime_config(base_path=base_path)

    if is_remote_uri(config.neo4j.uri):
        print(
            "Using remote Neo4j, no local container to manage.",
            file=sys.stderr,
        )
        return 1

    result = docker_stop(config)
    if not result.success:
        print(f"Error: {result.message}", file=sys.stderr)
        return 1
    print(result.message)
    return 0


def _cmd_db_eject(args: argparse.Namespace) -> int:
    """Copy compose template to .memorable/ for customization."""
    base_path = Path(args.path) if args.path else Path.cwd()
    target_dir = base_path / ".memorable"

    result = docker_eject(target_dir)
    if not result.success:
        print(f"Error: {result.message}", file=sys.stderr)
        return 1
    print(result.message)
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    """Initialize a MemorySpace from .memorable/memory.yaml.

    Uses the production Neo4j context: bootstraps schema constraints,
    creates the MemorySpace, and closes the driver on exit.
    """
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

    config = load_runtime_config(base_path=base_path)

    try:
        ctx, driver = build_production_context(config)
    except ConnectionError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        ensure_all_constraints(driver)

        service = InitService(repository=ctx.memory_space_repo)

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
    finally:
        driver.close()


def _cmd_tracer_run(args: argparse.Namespace) -> int:
    """Run the tracer-bullet fixture and output verification results."""
    default_context.reset()
    service = TracerService()
    result = service.run()
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


# =====================================================================
# Commands that USE the production context
# =====================================================================


def _cmd_remember_entity(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    """Remember an Entity with provenance."""
    space = resolve_space(getattr(args, "space", None))

    try:
        profile = ctx.load_profile(space)
    except ProfileValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    service = RememberEntityService(repository=ctx.entity_repo, profile=profile)

    at = parse_iso_timestamp(args.at)

    try:
        result = service.remember(
            space=space,
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
                "record_id": result.provenance.record_id,
                "record_kind": result.provenance.record_kind,
                "source": result.provenance.source_id,
                "episode": result.provenance.episode_id,
                "creation_time": result.provenance.creation_time.isoformat(),
                "validity_time": result.provenance.validity_time.isoformat(),
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_inspect_provenance(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    """Inspect provenance for a remembered Entity."""
    space = resolve_space(getattr(args, "space", None))

    inspector = InspectProvenanceService(repository=ctx.entity_repo)
    provenance = inspector.inspect(space=space, entity_id=args.id)

    if provenance is None:
        print(
            f"Error: No provenance found for '{args.id}' in MemorySpace '{space}'.",
            file=sys.stderr,
        )
        return 1

    print(f"Provenance for {provenance.record_id}")
    print(f"  - Record Kind: {provenance.record_kind}")
    print(f"  - Source: {provenance.source_id}")
    print(f"  - Episode: {provenance.episode_id}")
    print(f"  - Writer: {provenance.writer}")
    print(f"  - Creation Time: {provenance.creation_time.isoformat()}")
    print(f"  - Validity Time: {provenance.validity_time.isoformat()}")
    if provenance.reason:
        print(f"  - Reason: {provenance.reason}")
    return 0


def _cmd_remember_decision(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    """Remember a Decision with provenance."""
    space = resolve_space(getattr(args, "space", None))

    try:
        profile = ctx.load_profile(space)
    except ProfileValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    service = RememberDecisionService(repository=ctx.decision_repo, profile=profile)

    at = parse_iso_timestamp(args.at)
    supersedes = getattr(args, "supersedes", None)

    try:
        result = service.remember(
            space=space,
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
                "record_id": result.provenance.record_id,
                "record_kind": result.provenance.record_kind,
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


def _cmd_truth_current(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    """Show the current truth for a Decision, following supersession chain."""
    space = resolve_space(getattr(args, "space", None))

    service = CurrentTruthService(repository=ctx.decision_repo)
    decision = service.current(space=space, decision_id=args.id)

    if decision is None:
        print(
            f"Error: No Decision found for '{args.id}' in MemorySpace '{space}'.",
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


def _cmd_truth_as_of(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    """Show the Decision that was valid at a specific time."""
    space = resolve_space(getattr(args, "space", None))

    service = PointInTimeTruthService(repository=ctx.decision_repo)
    at = parse_iso_timestamp(args.at)
    decision = service.at(space=space, decision_id=args.id, at=at)

    if decision is None:
        print(
            f"Error: No Decision found for '{args.id}' "
            f"in MemorySpace '{space}' at {at.isoformat()}.",
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


def _cmd_inspect_history(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    """Show the full supersession chain for a Decision."""
    space = resolve_space(getattr(args, "space", None))

    service = InspectDecisionHistoryService(repository=ctx.decision_repo)
    history = service.history(space=space, decision_id=args.id)

    if not history:
        print(
            f"Error: No Decision found for '{args.id}' in MemorySpace '{space}'.",
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


def _cmd_remember_task(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    """Remember a Task with provenance."""
    space = resolve_space(getattr(args, "space", None))

    try:
        profile = ctx.load_profile(space)
    except ProfileValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    service = RememberTaskService(repository=ctx.task_repo, profile=profile)

    at = parse_iso_timestamp(args.at)

    try:
        result = service.remember(
            space=space,
            task_id=args.id,
            title=args.title,
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
                "task_id": result.task.id,
                "title": result.task.title,
                "space": result.task.space,
                "lifecycle_state": result.task.lifecycle_state,
                "record_id": result.provenance.record_id,
                "record_kind": result.provenance.record_kind,
                "source": result.provenance.source_id,
                "episode": result.provenance.episode_id,
                "creation_time": result.provenance.creation_time.isoformat(),
                "validity_time": result.provenance.validity_time.isoformat(),
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_complete_task(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    """Complete a Task."""
    space = resolve_space(getattr(args, "space", None))

    service = CompleteTaskService(repository=ctx.task_repo)

    at = parse_iso_timestamp(args.at)

    try:
        result = service.complete(
            space=space,
            task_id=args.id,
            at=at,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "task_id": result.task.id,
                "lifecycle_state": result.task.lifecycle_state,
                "event_id": result.event_id,
                "completion_time": result.completion_time.isoformat(),
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_task_inspect(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    """Inspect task lifecycle."""
    space = resolve_space(getattr(args, "space", None))

    service = InspectTaskService(repository=ctx.task_repo)

    as_of = None
    if hasattr(args, "as_of") and args.as_of is not None:
        as_of = parse_iso_timestamp(args.as_of)

    task = service.inspect(space=space, task_id=args.id, as_of=as_of)

    if task is None:
        print(
            f"Error: No Task found for '{args.id}' in MemorySpace '{space}'.",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "task_id": task.id,
                "title": task.title,
                "space": task.space,
                "lifecycle_state": task.lifecycle_state,
                "validity_time": task.validity_time.isoformat(),
                "completion_time": (
                    task.completion_time.isoformat() if task.completion_time else None
                ),
                "completion_event_id": task.completion_event_id,
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_search(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    """Search memory using hybrid GraphRAG retrieval."""
    space = resolve_space(getattr(args, "space", None))

    service = ctx.build_retrieval_service()

    raw_mode = getattr(args, "mode", "current") or "current"
    mode = cast(Literal["current", "as-of"], raw_mode)
    as_of = None
    if hasattr(args, "as_of") and args.as_of is not None:
        as_of = parse_iso_timestamp(args.as_of)

    results = service.search(
        space=space,
        query=args.query,
        mode=mode,
        as_of=as_of,
    )

    output = {
        "query": args.query,
        "space": space,
        "mode": mode,
        "results": [
            {
                "source_id": r.source_id,
                "source_kind": r.source_kind,
                "lifecycle_state": r.lifecycle_state,
                "score": round(r.score, 4),
                "explanation": r.explanation,
                "provenance_summary": r.provenance_summary,
            }
            for r in results
        ],
    }
    print(json.dumps(output, sort_keys=True, indent=2))
    return 0


# =====================================================================
# Dispatch helpers
# =====================================================================

# Commands that need a production context (Neo4j-backed).
# Identified by (command, subtype) tuples.
_CONTEXT_COMMANDS: set[tuple[str, str | None]] = {
    ("remember", "entity"),
    ("remember", "decision"),
    ("remember", "task"),
    ("complete", "task"),
    ("task", "inspect"),
    ("truth", "current"),
    ("truth", "as-of"),
    ("inspect", "provenance"),
    ("inspect", "history"),
    ("search", None),
}


def _needs_production_context(args: argparse.Namespace) -> bool:
    """Return True if the parsed command requires a production context."""
    command = args.command
    subtype = None
    if command == "remember":
        subtype = getattr(args, "remember_type", None)
    elif command == "complete":
        subtype = getattr(args, "complete_type", None)
    elif command == "task":
        subtype = getattr(args, "task_type", None)
    elif command == "truth":
        subtype = getattr(args, "truth_type", None)
    elif command == "inspect":
        subtype = getattr(args, "inspect_type", None)
    elif command == "search":
        return True

    return (command, subtype) in _CONTEXT_COMMANDS


def _dispatch_context_command(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    """Dispatch a command that uses the production context."""
    if args.command == "remember":
        if args.remember_type == "entity":
            return _cmd_remember_entity(args, ctx)
        elif args.remember_type == "decision":
            return _cmd_remember_decision(args, ctx)
        elif args.remember_type == "task":
            return _cmd_remember_task(args, ctx)
    elif args.command == "complete":
        if args.complete_type == "task":
            return _cmd_complete_task(args, ctx)
    elif args.command == "task":
        if args.task_type == "inspect":
            return _cmd_task_inspect(args, ctx)
    elif args.command == "truth":
        if args.truth_type == "current":
            return _cmd_truth_current(args, ctx)
        elif args.truth_type == "as-of":
            return _cmd_truth_as_of(args, ctx)
    elif args.command == "inspect":
        if args.inspect_type == "provenance":
            return _cmd_inspect_provenance(args, ctx)
        elif args.inspect_type == "history":
            return _cmd_inspect_history(args, ctx)
    elif args.command == "search":
        return _cmd_search(args, ctx)

    raise AssertionError(f"unhandled context command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="memorable")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show Memorable diagnostic status.")

    # db subcommand
    db_parser = subparsers.add_parser("db", help="Database operations.")
    db_sub = db_parser.add_subparsers(dest="db_type", required=True)
    db_status_parser = db_sub.add_parser(
        "status", help="Show resolved runtime configuration."
    )
    db_status_parser.add_argument(
        "--path",
        default=None,
        help="Base directory containing .memorable/ config (default: cwd).",
    )
    db_start_parser = db_sub.add_parser(
        "start", help="Start the local Neo4j container."
    )
    db_start_parser.add_argument(
        "--path",
        default=None,
        help="Base directory containing .memorable/ config (default: cwd).",
    )
    db_stop_parser = db_sub.add_parser("stop", help="Stop the local Neo4j container.")
    db_stop_parser.add_argument(
        "--path",
        default=None,
        help="Base directory containing .memorable/ config (default: cwd).",
    )
    db_eject_parser = db_sub.add_parser(
        "eject", help="Copy compose template to .memorable/ for customization."
    )
    db_eject_parser.add_argument(
        "--path",
        default=None,
        help="Base directory containing .memorable/ (default: cwd).",
    )

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
    remember_sub = remember_parser.add_subparsers(dest="remember_type", required=True)
    entity_parser = remember_sub.add_parser(
        "entity", help="Remember an Entity with provenance."
    )
    entity_parser.add_argument("--space", default=None)
    entity_parser.add_argument("--id", required=True)
    entity_parser.add_argument("--type", required=True)
    entity_parser.add_argument("--name", required=True)
    entity_parser.add_argument("--source", required=True)
    entity_parser.add_argument("--at", required=True)
    entity_parser.add_argument("--writer", default="agent:memorable")
    entity_parser.add_argument("--reason", default="")

    # remember task subcommand
    task_rem_parser = remember_sub.add_parser(
        "task", help="Remember a Task with provenance."
    )
    task_rem_parser.add_argument("--space", default=None)
    task_rem_parser.add_argument("--id", required=True)
    task_rem_parser.add_argument("--title", required=True)
    task_rem_parser.add_argument("--source", required=True)
    task_rem_parser.add_argument("--at", required=True)
    task_rem_parser.add_argument("--writer", default="agent:memorable")
    task_rem_parser.add_argument("--reason", default="")

    # remember decision subcommand
    decision_parser = remember_sub.add_parser(
        "decision", help="Remember a Decision with provenance."
    )
    decision_parser.add_argument("--space", default=None)
    decision_parser.add_argument("--id", required=True)
    decision_parser.add_argument("--statement", required=True)
    decision_parser.add_argument("--source", required=True)
    decision_parser.add_argument("--at", required=True)
    decision_parser.add_argument("--supersedes", default=None)
    decision_parser.add_argument("--writer", default="agent:memorable")
    decision_parser.add_argument("--reason", default="")

    # complete subcommand
    complete_parser = subparsers.add_parser(
        "complete", help="Complete a lifecycle transition."
    )
    complete_sub = complete_parser.add_subparsers(dest="complete_type", required=True)
    complete_task_parser = complete_sub.add_parser("task", help="Complete a Task.")
    complete_task_parser.add_argument("--space", default=None)
    complete_task_parser.add_argument("--id", required=True)
    complete_task_parser.add_argument("--at", required=True)
    complete_task_parser.add_argument("--source", default="")
    complete_task_parser.add_argument("--writer", default="agent:memorable")
    complete_task_parser.add_argument("--reason", default="")

    # task subcommand
    task_parser = subparsers.add_parser("task", help="Task lifecycle operations.")
    task_sub = task_parser.add_subparsers(dest="task_type", required=True)
    task_inspect_parser = task_sub.add_parser("inspect", help="Inspect task lifecycle.")
    task_inspect_parser.add_argument("--space", default=None)
    task_inspect_parser.add_argument("--id", required=True)
    task_inspect_parser.add_argument("--as-of", default=None)

    # truth subcommands
    truth_parser = subparsers.add_parser("truth", help="Query temporal truth.")
    truth_sub = truth_parser.add_subparsers(dest="truth_type", required=True)
    current_parser = truth_sub.add_parser(
        "current", help="Show current truth for a Decision."
    )
    current_parser.add_argument("--space", default=None)
    current_parser.add_argument("--id", required=True)

    as_of_parser = truth_sub.add_parser(
        "as-of", help="Show truth at a specific point in time."
    )
    as_of_parser.add_argument("--space", default=None)
    as_of_parser.add_argument("--id", required=True)
    as_of_parser.add_argument("--at", required=True)

    # inspect provenance subcommand
    inspect_parser = subparsers.add_parser("inspect", help="Inspect memory metadata.")
    inspect_sub = inspect_parser.add_subparsers(dest="inspect_type", required=True)
    prov_parser = inspect_sub.add_parser(
        "provenance", help="Inspect provenance for a remembered Entity."
    )
    prov_parser.add_argument("--space", default=None)
    prov_parser.add_argument("--id", required=True)

    history_parser = inspect_sub.add_parser(
        "history", help="Inspect supersession history for a Decision."
    )
    history_parser.add_argument("--space", default=None)
    history_parser.add_argument("--id", required=True)

    # tracer subcommand
    tracer_parser = subparsers.add_parser("tracer", help="Tracer-bullet operations.")
    tracer_sub = tracer_parser.add_subparsers(dest="tracer_type", required=True)
    tracer_sub.add_parser(
        "run", help="Run the tracer-bullet fixture and verify end-to-end."
    )

    # search subcommand
    search_parser = subparsers.add_parser(
        "search", help="Search memory using hybrid GraphRAG retrieval."
    )
    search_parser.add_argument("--space", default=None)
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--mode", default="current")
    search_parser.add_argument("--as-of", default=None)

    args = parser.parse_args(argv)

    # ----- Commands that do NOT need a production context -----
    if args.command == "status":
        print(json.dumps(build_status_payload(), sort_keys=True))
        return 0
    elif args.command == "db":
        if args.db_type == "status":
            return _cmd_db_status(args)
        elif args.db_type == "start":
            return _cmd_db_start(args)
        elif args.db_type == "stop":
            return _cmd_db_stop(args)
        elif args.db_type == "eject":
            return _cmd_db_eject(args)
        raise AssertionError(f"unhandled db command: {args.db_type}")
    elif args.command == "init":
        return _cmd_init(args)
    elif args.command == "tracer":
        if args.tracer_type == "run":
            return _cmd_tracer_run(args)
        raise AssertionError(f"unhandled tracer command: {args.tracer_type}")

    # ----- Commands that USE a production context -----
    if _needs_production_context(args):
        config = load_runtime_config()
        try:
            ctx, driver = build_production_context(config)
        except ConnectionError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        try:
            return _dispatch_context_command(args, ctx)
        finally:
            driver.close()

    # All subparsers use required=True, so argparse rejects unknown
    # commands before we reach here. Guard against future additions.
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
