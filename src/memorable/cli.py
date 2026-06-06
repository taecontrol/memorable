from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from memorable.config import RuntimeConfig, load_runtime_config
from memorable.core.application import (
    CompleteTaskService,
    CorrectService,
    CurrentTruthService,
    ForgetService,
    InitService,
    InspectHistoryService,
    InspectProvenanceService,
    InspectTaskService,
    InvalidateService,
    ListRecordsService,
    PointInTimeTruthService,
    RememberDecisionService,
    RememberEntityService,
    RememberObservationService,
    RememberRelationService,
    RememberTaskService,
    build_status_payload,
)
from memorable.core.context import ApplicationContext, default_context
from memorable.core.models import ProvenanceIntegrityError
from memorable.core.profile import (
    ProfileValidationError,
    load_profile_from_yaml,
    profile_summary,
)
from memorable.core.profile_scaffold import render_minimal_profile_scaffold
from memorable.core.temporal import parse_iso_timestamp
from memorable.core.tracer import TracerService
from memorable.runtime.docker import eject as docker_eject
from memorable.runtime.docker import is_remote_uri
from memorable.runtime.docker import start as docker_start
from memorable.runtime.docker import stop as docker_stop
from memorable.runtime.doctor import all_checks_passed, run_diagnostics
from memorable.storage.neo4j.repository import ensure_all_constraints
from memorable.storage.production import build_production_context

if TYPE_CHECKING:
    from memorable.retrieval.indexing import EmbeddingIndexer


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
            "dimensions": _field_entry(
                config.embeddings.dimensions, "embeddings.dimensions"
            ),
        },
    }

    print(json.dumps(output, indent=2))
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Run live runtime health diagnostics."""
    config = load_runtime_config(include_environment_overrides=True)
    results = run_diagnostics(config)

    if args.json:
        print(json.dumps(results, sort_keys=True))
    else:
        for result in results:
            status = "PASS" if result["ok"] else "FAIL"
            print(f"{status} {result['check']}")
            if result["hint"]:
                label = "Note" if result["ok"] else "Hint"
                print(f"{label}: {result['hint']}")

    return 0 if all_checks_passed(results) else 1


def _cmd_db_start(args: argparse.Namespace) -> int:
    """Start the local Neo4j container."""
    base_path = Path(args.path) if args.path else None
    config = load_runtime_config(
        base_path=base_path, include_environment_overrides=True
    )

    if is_remote_uri(config.neo4j.uri):
        print(
            "Using remote Neo4j, no local container to manage.",
            file=sys.stderr,
        )
        return 1

    result = docker_start(config, project_dir=base_path)
    if not result.success:
        print(f"Error: {result.message}", file=sys.stderr)
        return 1
    print(result.message)
    return 0


def _cmd_db_stop(args: argparse.Namespace) -> int:
    """Stop the local Neo4j container."""
    base_path = Path(args.path) if args.path else None
    config = load_runtime_config(
        base_path=base_path, include_environment_overrides=True
    )

    if is_remote_uri(config.neo4j.uri):
        print(
            "Using remote Neo4j, no local container to manage.",
            file=sys.stderr,
        )
        return 1

    result = docker_stop(config, project_dir=base_path)
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
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        space_name = args.space if args.space is not None else base_path.resolve().name
        yaml_text = render_minimal_profile_scaffold(
            space_name, description=args.description
        )
        profile_path.write_text(yaml_text, encoding="utf-8")
    else:
        yaml_text = profile_path.read_text(encoding="utf-8")

    config = load_runtime_config(
        base_path=base_path, include_environment_overrides=True
    )

    try:
        ctx, driver = build_production_context(config)
    except ConnectionError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    try:
        ensure_all_constraints(driver, vector_dimensions=config.embeddings.dimensions)

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


def _cmd_profile_show(args: argparse.Namespace) -> int:
    """Show the loaded MemoryProfile including relation type declarations."""
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

    try:
        profile = load_profile_from_yaml(yaml_text)
    except ProfileValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(profile_summary(profile), sort_keys=True, indent=2))
    return 0


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


def _build_embedding_indexer(
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> EmbeddingIndexer:
    """Build the write-time Embedding indexer for the active runtime config."""
    from memorable.retrieval.embeddings import build_embedding_provider
    from memorable.retrieval.indexing import EmbeddingIndexer

    provider = build_embedding_provider(
        config.embeddings, api_key=config.embeddings.api_key
    )
    return EmbeddingIndexer(
        retrieval_index=ctx.retrieval_index,
        embedding_provider=provider,
        dimensions=config.embeddings.dimensions,
    )


def _index_after_canonical_write(
    *,
    ctx: ApplicationContext,
    config: RuntimeConfig,
    space: str,
    source_id: str,
    source_kind: str,
    upsert: Callable[[EmbeddingIndexer], None],
) -> bool:
    """Upsert a derived Embedding after canonical memory was written."""
    try:
        upsert(_build_embedding_indexer(ctx, config))
    except Exception as exc:
        print(
            "Error: Canonical memory was written, but derived Embedding index "
            f"maintenance failed for {source_kind} '{source_id}' in "
            f"MemorySpace '{space}'. Run `memorable reindex --space {space}` "
            f"to repair search. Original error: {exc}",
            file=sys.stderr,
        )
        return False
    return True


def _delete_after_canonical_forget(
    *,
    ctx: ApplicationContext,
    space: str,
    source_id: str,
    source_kind: str,
) -> bool:
    """Delete a derived Embedding after canonical memory was forgotten."""
    try:
        ctx.retrieval_index.delete(
            space=space,
            source_id=source_id,
            source_kind=source_kind,
        )
    except Exception as exc:
        print(
            "Error: Canonical memory was forgotten, but derived Embedding index "
            f"maintenance failed for {source_kind} '{source_id}' in "
            f"MemorySpace '{space}'. Run `memorable reindex --space {space}` "
            f"to erase stale derived Embeddings. Original error: {exc}",
            file=sys.stderr,
        )
        return False
    return True


_RECORD_EMBEDDING_SOURCE_KIND = {
    "decision": "Decision",
    "observation": "Observation",
    "task": "Task",
}


def _cmd_remember_entity(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
    """Remember an Entity with provenance."""
    space = resolve_space(getattr(args, "space", None))

    try:
        profile = ctx.load_profile()
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

    if not _index_after_canonical_write(
        ctx=ctx,
        config=config,
        space=space,
        source_id=result.entity.id,
        source_kind="Entity",
        upsert=lambda indexer: indexer.upsert_entity(result.entity),
    ):
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


def _cmd_inspect_provenance(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
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


def _cmd_remember_decision(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
    """Remember a Decision with provenance."""
    space = resolve_space(getattr(args, "space", None))

    try:
        profile = ctx.load_profile()
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
            record_type=getattr(args, "record_type", None),
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    def upsert_decision_embeddings(indexer: EmbeddingIndexer) -> None:
        indexer.upsert_decision(result.decision)
        if supersedes is not None:
            superseded_decision = ctx.decision_repo.get(space, supersedes)
            if superseded_decision is not None:
                indexer.upsert_decision(superseded_decision)

    if not _index_after_canonical_write(
        ctx=ctx,
        config=config,
        space=space,
        source_id=result.decision.id,
        source_kind="Decision",
        upsert=upsert_decision_embeddings,
    ):
        return 1

    print(
        json.dumps(
            {
                "decision_id": result.decision.id,
                "statement": result.decision.statement,
                "space": result.decision.space,
                "record_id": result.provenance.record_id,
                "record_kind": result.provenance.record_kind,
                "record_type": result.decision.record_type,
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


def _cmd_remember_observation(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
    """Remember an Observation with provenance."""
    space = resolve_space(getattr(args, "space", None))

    try:
        profile = ctx.load_profile()
    except ProfileValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    service = RememberObservationService(
        repository=ctx.observation_repo, profile=profile
    )

    at = parse_iso_timestamp(args.at)
    supersedes = getattr(args, "supersedes", None)

    try:
        result = service.remember(
            space=space,
            observation_id=args.id,
            statement=args.statement,
            source_id=args.source,
            at=at,
            writer=getattr(args, "writer", "agent:memorable"),
            reason=getattr(args, "reason", ""),
            supersedes=supersedes,
            record_type=getattr(args, "record_type", None),
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    def upsert_observation_embeddings(indexer: EmbeddingIndexer) -> None:
        indexer.upsert_observation(result.observation)
        if supersedes is not None:
            superseded_observation = ctx.observation_repo.get(space, supersedes)
            if superseded_observation is not None:
                indexer.upsert_observation(superseded_observation)

    if not _index_after_canonical_write(
        ctx=ctx,
        config=config,
        space=space,
        source_id=result.observation.id,
        source_kind="Observation",
        upsert=upsert_observation_embeddings,
    ):
        return 1

    print(
        json.dumps(
            {
                "observation_id": result.observation.id,
                "statement": result.observation.statement,
                "space": result.observation.space,
                "record_id": result.provenance.record_id,
                "record_kind": result.provenance.record_kind,
                "record_type": result.observation.record_type,
                "source": result.provenance.source_id,
                "episode": result.provenance.episode_id,
                "creation_time": result.provenance.creation_time.isoformat(),
                "validity_time": result.provenance.validity_time.isoformat(),
                "lifecycle_state": result.observation.lifecycle_state,
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_remember_relation(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
    """Remember a Relation with provenance."""
    space = resolve_space(getattr(args, "space", None))

    try:
        profile = ctx.load_profile()
    except ProfileValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    service = RememberRelationService(
        relation_repo=ctx.relation_repo,
        entity_repo=ctx.entity_repo,
        profile=profile,
    )

    at = parse_iso_timestamp(args.at)
    supersedes = getattr(args, "supersedes", None)

    try:
        result = service.remember(
            space=space,
            relation_id=args.id,
            source_entity_id=args.source_entity_id,
            target_entity_id=args.target_entity_id,
            relation_type=args.relation_type,
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

    def upsert_relation_embeddings(indexer: EmbeddingIndexer) -> None:
        indexer.upsert_relation(result.relation)
        if supersedes is not None:
            superseded_relation = ctx.relation_repo.get(space, supersedes)
            if superseded_relation is not None:
                indexer.upsert_relation(superseded_relation)

    if not _index_after_canonical_write(
        ctx=ctx,
        config=config,
        space=space,
        source_id=result.relation.id,
        source_kind="Relation",
        upsert=upsert_relation_embeddings,
    ):
        return 1

    print(
        json.dumps(
            {
                "relation_id": result.relation.id,
                "statement": result.relation.statement,
                "space": result.relation.space,
                "record_kind": result.provenance.record_kind,
                "lifecycle_state": result.relation.lifecycle_state,
                "source_entity_id": result.relation.source_entity_id,
                "target_entity_id": result.relation.target_entity_id,
                "relation_type": result.relation.relation_type,
                "source": result.provenance.source_id,
                "episode": result.provenance.episode_id,
                "creation_time": result.provenance.creation_time.isoformat(),
                "validity_time": result.provenance.validity_time.isoformat(),
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_truth_current(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
    """Show the current truth for a Decision, following supersession chain."""
    space = resolve_space(getattr(args, "space", None))

    service = CurrentTruthService(repository=ctx.decision_repo)
    decision = service.current(space=space, record_id=args.id)

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
                "record_type": decision.record_type,
                "validity_time": decision.validity_time.isoformat(),
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_truth_as_of(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
    """Show the Decision that was valid at a specific time."""
    space = resolve_space(getattr(args, "space", None))

    service = PointInTimeTruthService(repository=ctx.decision_repo)
    at = parse_iso_timestamp(args.at)
    decision = service.at(space=space, record_id=args.id, at=at)

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
                "record_type": decision.record_type,
                "validity_time": decision.validity_time.isoformat(),
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_inspect_history(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
    """Show the full supersession chain for a Decision."""
    space = resolve_space(getattr(args, "space", None))

    service = InspectHistoryService(repository=ctx.decision_repo)
    history = service.history(space=space, record_id=args.id)

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
        if decision.record_type is not None:
            print(f"      Record Subtype: {decision.record_type}")
        print(f"      Lifecycle: {decision.lifecycle_state}")
        print(f"      Valid from: {decision.validity_time.isoformat()}")
        if decision.invalidation_time:
            print(f"      Invalidated: {decision.invalidation_time.isoformat()}")
        if decision.supersedes:
            print(f"      Supersedes: {decision.supersedes}")
        if decision.superseded_by:
            print(f"      Superseded by: {decision.superseded_by}")
    return 0


def _cmd_remember_task(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
    """Remember a Task with provenance."""
    space = resolve_space(getattr(args, "space", None))

    try:
        profile = ctx.load_profile()
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
            record_type=getattr(args, "record_type", None),
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not _index_after_canonical_write(
        ctx=ctx,
        config=config,
        space=space,
        source_id=result.task.id,
        source_kind="Task",
        upsert=lambda indexer: indexer.upsert_task(result.task),
    ):
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
                "record_type": result.task.record_type,
                "source": result.provenance.source_id,
                "episode": result.provenance.episode_id,
                "creation_time": result.provenance.creation_time.isoformat(),
                "validity_time": result.provenance.validity_time.isoformat(),
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_complete_task(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
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

    if not _index_after_canonical_write(
        ctx=ctx,
        config=config,
        space=space,
        source_id=result.task.id,
        source_kind="Task",
        upsert=lambda indexer: indexer.upsert_task(result.task),
    ):
        return 1

    print(
        json.dumps(
            {
                "task_id": result.task.id,
                "lifecycle_state": result.task.lifecycle_state,
                "record_type": result.task.record_type,
                "event_id": result.event_id,
                "completion_time": result.completion_time.isoformat(),
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_task_inspect(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
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
                "record_type": task.record_type,
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


def _cmd_list(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
    """List MemoryRecords for Memory Review."""
    space = resolve_space(getattr(args, "space", None))

    since = parse_iso_timestamp(args.since) if args.since is not None else None
    until = parse_iso_timestamp(args.until) if args.until is not None else None

    service = ListRecordsService(
        decision_repo=ctx.decision_repo,
        observation_repo=ctx.observation_repo,
        relation_repo=ctx.relation_repo,
        task_repo=ctx.task_repo,
        about_repo=ctx.about_repo,
    )
    try:
        projections = service.list_records(
            space=space,
            type=getattr(args, "record_kind", None),
            state=getattr(args, "state", None),
            since=since,
            until=until,
            about=getattr(args, "about", None),
            record_type=getattr(args, "record_type", None),
            limit=getattr(args, "limit", 50),
        )
    except (ValueError, ProvenanceIntegrityError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "space": space,
                "records": [
                    {
                        "id": projection.id,
                        "type": projection.type,
                        "label": projection.label,
                        "lifecycle_state": projection.lifecycle_state,
                        "creation_time": projection.creation_time.isoformat(),
                        "record_type": projection.record_type,
                    }
                    for projection in projections
                ],
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_search(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
    """Search memory using hybrid GraphRAG retrieval."""
    space = resolve_space(getattr(args, "space", None))

    from memorable.retrieval.embeddings import build_embedding_provider
    from memorable.retrieval.service import (
        EmbeddingIndexCompatibilityError,
        build_retrieval_service,
    )

    try:
        provider = build_embedding_provider(
            config.embeddings, api_key=config.embeddings.api_key
        )
    except (RuntimeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    service = build_retrieval_service(
        ctx,
        provider,
        dimensions=config.embeddings.dimensions,
    )

    raw_mode = getattr(args, "mode", "current") or "current"
    mode = cast(Literal["current", "as-of"], raw_mode)
    as_of = None
    if hasattr(args, "as_of") and args.as_of is not None:
        as_of = parse_iso_timestamp(args.as_of)

    try:
        results = service.search(
            space=space,
            query=args.query,
            mode=mode,
            as_of=as_of,
            record_type=getattr(args, "record_type", None),
        )
    except EmbeddingIndexCompatibilityError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

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
                "record_type": r.record_type,
            }
            for r in results
        ],
    }
    print(json.dumps(output, sort_keys=True, indent=2))
    return 0


def _cmd_reindex(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
    """Backfill persistent Embeddings for a MemorySpace."""
    space = resolve_space(getattr(args, "space", None))

    from memorable.retrieval.embeddings import build_embedding_provider
    from memorable.retrieval.service import build_retrieval_service

    try:
        provider = build_embedding_provider(
            config.embeddings, api_key=config.embeddings.api_key
        )
    except (RuntimeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    service = build_retrieval_service(
        ctx,
        provider,
        dimensions=config.embeddings.dimensions,
    )
    try:
        result = service.reindex(space)
    except Exception as e:
        print(
            f"Error: Reindex failed for MemorySpace '{space}'. Run "
            "`memorable doctor` to diagnose Embedding Provider and vector "
            "index compatibility, then retry `memorable reindex --space "
            f"{space}`. Original error: {e}",
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "space": result.space,
                "indexed_total": result.indexed_total,
                "indexed_by_kind": result.indexed_by_kind,
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_invalidate(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
    """Invalidate a temporal record (Decision or Observation)."""
    space = resolve_space(getattr(args, "space", None))
    record_type = args.record_type

    if record_type == "decision":
        repository = ctx.decision_repo
    elif record_type == "observation":
        repository = ctx.observation_repo
    else:
        print(
            f"Error: Unknown record type '{record_type}'. "
            f"Supported types: decision, observation.",
            file=sys.stderr,
        )
        return 1

    service = InvalidateService(repository=repository)
    at = parse_iso_timestamp(args.at)

    try:
        result = service.invalidate(
            space=space,
            record_id=args.id,
            at=at,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if record_type == "decision":
        invalidated_decision = ctx.decision_repo.get(space, result.record_id)
        if invalidated_decision is None:
            print(
                f"Error: Invalidated Decision '{result.record_id}' not found "
                f"in MemorySpace '{space}'.",
                file=sys.stderr,
            )
            return 1
        if not _index_after_canonical_write(
            ctx=ctx,
            config=config,
            space=space,
            source_id=result.record_id,
            source_kind="Decision",
            upsert=lambda indexer: indexer.upsert_decision(invalidated_decision),
        ):
            return 1
    elif record_type == "observation":
        invalidated_observation = ctx.observation_repo.get(space, result.record_id)
        if invalidated_observation is None:
            print(
                f"Error: Invalidated Observation '{result.record_id}' not found "
                f"in MemorySpace '{space}'.",
                file=sys.stderr,
            )
            return 1
        if not _index_after_canonical_write(
            ctx=ctx,
            config=config,
            space=space,
            source_id=result.record_id,
            source_kind="Observation",
            upsert=lambda indexer: indexer.upsert_observation(invalidated_observation),
        ):
            return 1

    print(
        json.dumps(
            {
                "record_id": result.record_id,
                "space": result.space,
                "lifecycle_state": result.lifecycle_state,
                "invalidation_time": result.invalidation_time.isoformat(),
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_correct(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
    """Correct a temporal record's statement in place (Decision or Observation)."""
    space = resolve_space(getattr(args, "space", None))
    record_type = args.record_type

    if record_type == "decision":
        repository = ctx.decision_repo
    elif record_type == "observation":
        repository = ctx.observation_repo
    else:
        print(
            f"Error: Unknown record type '{record_type}'. "
            f"Supported types: decision, observation.",
            file=sys.stderr,
        )
        return 1

    service = CorrectService(repository=repository)
    at = parse_iso_timestamp(args.at)

    try:
        result = service.correct(
            space=space,
            record_id=args.id,
            new_statement=args.new_statement,
            record_kind=record_type,
            source=args.source,
            writer=getattr(args, "writer", "agent:memorable"),
            at=at,
            reason=getattr(args, "reason", "") or "",
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if record_type == "decision":
        corrected_decision = ctx.decision_repo.get(space, result.record_id)
        if corrected_decision is None:
            print(
                f"Error: Corrected Decision '{result.record_id}' not found "
                f"in MemorySpace '{space}'.",
                file=sys.stderr,
            )
            return 1
        if not _index_after_canonical_write(
            ctx=ctx,
            config=config,
            space=space,
            source_id=result.record_id,
            source_kind="Decision",
            upsert=lambda indexer: indexer.upsert_decision(corrected_decision),
        ):
            return 1
    elif record_type == "observation":
        corrected_observation = ctx.observation_repo.get(space, result.record_id)
        if corrected_observation is None:
            print(
                f"Error: Corrected Observation '{result.record_id}' not found "
                f"in MemorySpace '{space}'.",
                file=sys.stderr,
            )
            return 1
        if not _index_after_canonical_write(
            ctx=ctx,
            config=config,
            space=space,
            source_id=result.record_id,
            source_kind="Observation",
            upsert=lambda indexer: indexer.upsert_observation(corrected_observation),
        ):
            return 1

    print(
        json.dumps(
            {
                "record_id": result.record_id,
                "space": result.space,
                "old_statement": result.old_statement,
                "new_statement": result.new_statement,
            },
            sort_keys=True,
        )
    )
    return 0


def _cmd_forget(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
    """Forget a record or Entity by id within a MemorySpace."""
    space = resolve_space(getattr(args, "space", None))

    service = ForgetService(repository=ctx.forget_repo)
    try:
        if args.target_type == "entity":
            cascaded_relations = list(ctx.relation_repo.list_by_entity(space, args.id))
            result = service.forget_entity(space=space, entity_id=args.id)
            embedding_deletions = [
                (result.record_id, "Entity"),
                *((relation.id, "Relation") for relation in cascaded_relations),
            ]
        else:
            result = service.forget_record(
                space=space,
                record_id=args.id,
                record_kind=args.target_type,
            )
            embedding_deletions = [
                (result.record_id, _RECORD_EMBEDDING_SOURCE_KIND[result.record_kind])
            ]
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    for source_id, source_kind in embedding_deletions:
        if not _delete_after_canonical_forget(
            ctx=ctx,
            space=space,
            source_id=source_id,
            source_kind=source_kind,
        ):
            return 1

    print(
        json.dumps(
            {
                "forgotten": True,
                "record_id": result.record_id,
                "record_kind": result.record_kind,
                "space": result.space,
            },
            sort_keys=True,
        )
    )
    return 0


# =====================================================================
# Dispatch helpers
# =====================================================================

# Registry mapping (command, subtype) -> handler function.
# Single source of truth: _needs_production_context and dispatch both use this.
_CONTEXT_HANDLERS: dict[
    tuple[str, str | None],
    Callable[[argparse.Namespace, ApplicationContext, RuntimeConfig], int],
] = {
    ("remember", "entity"): _cmd_remember_entity,
    ("remember", "decision"): _cmd_remember_decision,
    ("remember", "observation"): _cmd_remember_observation,
    ("remember", "relation"): _cmd_remember_relation,
    ("remember", "task"): _cmd_remember_task,
    ("complete", "task"): _cmd_complete_task,
    ("task", "inspect"): _cmd_task_inspect,
    ("truth", "current"): _cmd_truth_current,
    ("truth", "as-of"): _cmd_truth_as_of,
    ("inspect", "provenance"): _cmd_inspect_provenance,
    ("inspect", "history"): _cmd_inspect_history,
    ("list", None): _cmd_list,
    ("search", None): _cmd_search,
    ("reindex", None): _cmd_reindex,
    ("invalidate", None): _cmd_invalidate,
    ("correct", None): _cmd_correct,
    ("forget", None): _cmd_forget,
}

# Map command name -> attribute that holds the subtype on argparse.Namespace.
_SUBTYPE_ATTRS: dict[str, str] = {
    "remember": "remember_type",
    "complete": "complete_type",
    "task": "task_type",
    "truth": "truth_type",
    "inspect": "inspect_type",
}


def _resolve_context_key(
    args: argparse.Namespace,
) -> tuple[str, str | None]:
    """Extract the (command, subtype) key from parsed args."""
    command = args.command
    attr = _SUBTYPE_ATTRS.get(command)
    subtype = getattr(args, attr, None) if attr else None
    return (command, subtype)


def _needs_production_context(args: argparse.Namespace) -> bool:
    """Return True if the parsed command requires a production context."""
    return _resolve_context_key(args) in _CONTEXT_HANDLERS


def _dispatch_context_command(
    args: argparse.Namespace,
    ctx: ApplicationContext,
    config: RuntimeConfig,
) -> int:
    """Dispatch a command that uses the production context."""
    key = _resolve_context_key(args)
    handler = _CONTEXT_HANDLERS.get(key)
    if handler is None:
        raise AssertionError(f"unhandled context command: {args.command}")
    return handler(args, ctx, config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="memorable")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show Memorable diagnostic status.")
    doctor_parser = subparsers.add_parser(
        "doctor", help="Run live runtime health diagnostics."
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured diagnostic results as JSON.",
    )

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
    init_parser.add_argument(
        "--space",
        default=None,
        help="MemorySpace name for a newly scaffolded MemoryProfile.",
    )
    init_parser.add_argument(
        "--description",
        default=None,
        help="MemorySpace description for a newly scaffolded MemoryProfile.",
    )

    # profile subcommand
    profile_parser = subparsers.add_parser("profile", help="Inspect the MemoryProfile.")
    profile_sub = profile_parser.add_subparsers(dest="profile_type", required=True)
    profile_show_parser = profile_sub.add_parser(
        "show", help="Show the loaded MemoryProfile."
    )
    profile_show_parser.add_argument(
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
    task_rem_parser.add_argument("--type", dest="record_type", default=None)
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
    decision_parser.add_argument("--type", dest="record_type", default=None)
    decision_parser.add_argument("--writer", default="agent:memorable")
    decision_parser.add_argument("--reason", default="")

    # remember observation subcommand
    obs_parser = remember_sub.add_parser(
        "observation", help="Remember an Observation with provenance."
    )
    obs_parser.add_argument("--space", default=None)
    obs_parser.add_argument("--id", required=True)
    obs_parser.add_argument("--statement", required=True)
    obs_parser.add_argument("--source", required=True)
    obs_parser.add_argument("--at", required=True)
    obs_parser.add_argument("--supersedes", default=None)
    obs_parser.add_argument("--type", dest="record_type", default=None)
    obs_parser.add_argument("--writer", default="agent:memorable")
    obs_parser.add_argument("--reason", default="")

    # remember relation subcommand
    rel_parser = remember_sub.add_parser(
        "relation", help="Remember a Relation with provenance."
    )
    rel_parser.add_argument("--space", default=None)
    rel_parser.add_argument("--id", required=True)
    rel_parser.add_argument("--source-entity-id", required=True)
    rel_parser.add_argument("--target-entity-id", required=True)
    rel_parser.add_argument("--relation-type", required=True)
    rel_parser.add_argument("--statement", required=True)
    rel_parser.add_argument("--source", required=True)
    rel_parser.add_argument("--at", required=True)
    rel_parser.add_argument("--supersedes", default=None)
    rel_parser.add_argument("--writer", default="agent:memorable")
    rel_parser.add_argument("--reason", default="")

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

    # list subcommand
    list_parser = subparsers.add_parser(
        "list", help="List MemoryRecords for Memory Review."
    )
    list_parser.add_argument("--space", default=None)
    list_parser.add_argument(
        "--record-kind",
        choices=["decision", "observation", "relation", "task"],
        default=None,
        help="Kernel record kind to list.",
    )
    list_parser.add_argument(
        "--type",
        dest="record_type",
        default=None,
        help="Record Subtype to list, such as Episode or Commitment.",
    )
    list_parser.add_argument("--state", default=None)
    list_parser.add_argument("--since", default=None)
    list_parser.add_argument("--until", default=None)
    list_parser.add_argument("--about", default=None)
    list_parser.add_argument("--limit", type=int, default=50)

    # search subcommand
    search_parser = subparsers.add_parser(
        "search", help="Search memory using hybrid GraphRAG retrieval."
    )
    search_parser.add_argument("--space", default=None)
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--mode", default="current")
    search_parser.add_argument("--as-of", default=None)
    search_parser.add_argument(
        "--type",
        dest="record_type",
        default=None,
        help="Record Subtype to search, such as Episode or Commitment.",
    )

    # reindex subcommand
    reindex_parser = subparsers.add_parser(
        "reindex", help="Backfill persistent Embeddings for a MemorySpace."
    )
    reindex_parser.add_argument("--space", default=None)

    # invalidate subcommand
    invalidate_parser = subparsers.add_parser(
        "invalidate", help="Mark a temporal record as invalidated."
    )
    invalidate_parser.add_argument("--space", default=None)
    invalidate_parser.add_argument("--id", required=True)
    invalidate_parser.add_argument(
        "--record-type",
        required=True,
        help="Type of record (decision, observation).",
    )
    invalidate_parser.add_argument("--at", required=True)

    # correct subcommand
    correct_parser = subparsers.add_parser(
        "correct", help="Correct a temporal record's statement in place."
    )
    correct_parser.add_argument("--space", default=None)
    correct_parser.add_argument("--id", required=True)
    correct_parser.add_argument(
        "--record-type",
        required=True,
        help="Type of record (decision, observation).",
    )
    correct_parser.add_argument("--new-statement", required=True)
    correct_parser.add_argument("--source", required=True)
    correct_parser.add_argument("--at", required=True)
    correct_parser.add_argument("--reason", default="")
    correct_parser.add_argument("--writer", default="agent:memorable")

    # forget subcommand
    forget_parser = subparsers.add_parser(
        "forget",
        help="Hard-delete a record or Entity by id.",
    )
    forget_parser.add_argument("--space", default=None)
    forget_parser.add_argument("--id", required=True)
    forget_parser.add_argument(
        "--target-type",
        required=True,
        choices=["decision", "observation", "task", "entity"],
        help="Target to forget (decision, observation, task, entity).",
    )

    args = parser.parse_args(argv)

    # ----- Commands that do NOT need a production context -----
    if args.command == "status":
        print(json.dumps(build_status_payload(), sort_keys=True))
        return 0
    elif args.command == "doctor":
        return _cmd_doctor(args)
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
    elif args.command == "profile":
        if args.profile_type == "show":
            return _cmd_profile_show(args)
        raise AssertionError(f"unhandled profile command: {args.profile_type}")
    elif args.command == "tracer":
        if args.tracer_type == "run":
            return _cmd_tracer_run(args)
        raise AssertionError(f"unhandled tracer command: {args.tracer_type}")

    # ----- Commands that USE a production context -----
    if _needs_production_context(args):
        config = load_runtime_config(include_environment_overrides=True)
        try:
            ctx, driver = build_production_context(config)
        except ConnectionError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        try:
            return _dispatch_context_command(args, ctx, config)
        finally:
            driver.close()

    # All subparsers use required=True, so argparse rejects unknown
    # commands before we reach here. Guard against future additions.
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
