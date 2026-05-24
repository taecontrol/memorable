from __future__ import annotations

from pathlib import Path

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
from memorable.core.context import default_context
from memorable.core.profile import ProfileValidationError, load_profile_from_yaml
from memorable.core.repositories import make_memory_space_repository
from memorable.core.temporal import parse_iso_timestamp


def status_tool() -> dict[str, object]:
    return build_status_payload()


def init_space_tool(base_path: str) -> dict[str, object]:
    """Initialize a MemorySpace from a project's .memorable/memory.yaml.

    Returns a dict with space info on success, or an error dict on failure.
    """
    profile_path = Path(base_path) / ".memorable" / "memory.yaml"

    if not profile_path.exists():
        return {
            "error": f"No memory.yaml found at {profile_path}. "
            "Create a .memorable/memory.yaml to define your MemoryProfile."
        }

    yaml_text = profile_path.read_text(encoding="utf-8")

    repository = make_memory_space_repository()
    service = InitService(repository=repository)

    try:
        result = service.initialize(yaml_text)
    except ProfileValidationError as e:
        return {"error": str(e)}

    return {
        "space": result.space.name,
        "status": "already exists" if result.already_existed else "initialized",
        "profile_version": result.profile.version,
    }


def inspect_space_tool(base_path: str) -> dict[str, object]:
    """Inspect a project's MemoryProfile without initializing.

    Returns profile summary on success, or an error dict on failure.
    """
    profile_path = Path(base_path) / ".memorable" / "memory.yaml"

    if not profile_path.exists():
        return {
            "error": f"No memory.yaml found at {profile_path}. "
            "Create a .memorable/memory.yaml to define your MemoryProfile."
        }

    yaml_text = profile_path.read_text(encoding="utf-8")

    try:
        profile = load_profile_from_yaml(yaml_text)
    except ProfileValidationError as e:
        return {"error": str(e)}

    return {
        "space_name": profile.space.name,
        "description": profile.space.description,
        "entity_count": len(profile.entities),
        "record_count": len(profile.records),
        "write_policy_default": profile.write_policy.default,
        "write_policy_sensitive": profile.write_policy.sensitive,
        "entities": [e.name for e in profile.entities],
        "records": [{"name": r.name, "extends": r.extends} for r in profile.records],
    }


def remember_entity_tool(
    space: str,
    entity_id: str,
    entity_type: str,
    name: str,
    source: str,
    at: str,
    writer: str = "agent:memorable",
    reason: str = "",
) -> dict[str, object]:
    """Remember an Entity with provenance in a MemorySpace.

    Returns a dict with entity and provenance info on success,
    or an error dict on failure.
    """
    try:
        profile = default_context.load_profile(space)
    except ProfileValidationError as e:
        return {"error": str(e)}

    service = RememberEntityService(
        repository=default_context.entity_repo, profile=profile
    )

    timestamp = parse_iso_timestamp(at)

    try:
        result = service.remember(
            space=space,
            entity_id=entity_id,
            entity_type=entity_type,
            name=name,
            source_id=source,
            at=timestamp,
            writer=writer,
            reason=reason,
        )
    except ValueError as e:
        return {"error": str(e)}

    return {
        "entity_id": result.entity.id,
        "entity_type": result.entity.entity_type,
        "name": result.entity.name,
        "space": result.entity.space,
        "source": result.provenance.source_id,
        "episode": result.provenance.episode_id,
        "creation_time": result.provenance.creation_time.isoformat(),
        "validity_time": result.provenance.validity_time.isoformat(),
    }


def remember_decision_tool(
    space: str,
    decision_id: str,
    statement: str,
    source: str,
    at: str,
    supersedes: str | None = None,
    writer: str = "agent:memorable",
    reason: str = "",
) -> dict[str, object]:
    """Remember a Decision with provenance in a MemorySpace.

    Returns a dict with decision and provenance info on success,
    or an error dict on failure.
    """
    try:
        profile = default_context.load_profile(space)
    except ProfileValidationError as e:
        return {"error": str(e)}

    service = RememberDecisionService(
        repository=default_context.decision_repo, profile=profile
    )

    timestamp = parse_iso_timestamp(at)

    try:
        result = service.remember(
            space=space,
            decision_id=decision_id,
            statement=statement,
            source_id=source,
            at=timestamp,
            writer=writer,
            reason=reason,
            supersedes=supersedes,
        )
    except ValueError as e:
        return {"error": str(e)}

    return {
        "decision_id": result.decision.id,
        "statement": result.decision.statement,
        "space": result.decision.space,
        "source": result.provenance.source_id,
        "episode": result.provenance.episode_id,
        "creation_time": result.provenance.creation_time.isoformat(),
        "validity_time": result.provenance.validity_time.isoformat(),
        "lifecycle_state": result.decision.lifecycle_state,
    }


def current_truth_tool(
    space: str,
    decision_id: str,
) -> dict[str, object]:
    """Get the current truth for a Decision, following supersession chain.

    Returns decision details on success, or an error dict on failure.
    """
    service = CurrentTruthService(repository=default_context.decision_repo)
    decision = service.current(space=space, decision_id=decision_id)

    if decision is None:
        return {
            "error": f"No Decision found for '{decision_id}' "
            f"in MemorySpace '{space}'."
        }

    return {
        "decision_id": decision.id,
        "statement": decision.statement,
        "space": decision.space,
        "lifecycle_state": decision.lifecycle_state,
        "validity_time": decision.validity_time.isoformat(),
    }


def point_in_time_truth_tool(
    space: str,
    decision_id: str,
    at: str,
) -> dict[str, object]:
    """Get the Decision that was valid at a specific point in time.

    Returns decision details on success, or an error dict on failure.
    """
    service = PointInTimeTruthService(repository=default_context.decision_repo)
    timestamp = parse_iso_timestamp(at)
    decision = service.at(space=space, decision_id=decision_id, at=timestamp)

    if decision is None:
        return {
            "error": f"No Decision found for '{decision_id}' "
            f"in MemorySpace '{space}' at {timestamp.isoformat()}."
        }

    return {
        "decision_id": decision.id,
        "statement": decision.statement,
        "space": decision.space,
        "lifecycle_state": decision.lifecycle_state,
        "validity_time": decision.validity_time.isoformat(),
    }


def inspect_decision_history_tool(
    space: str,
    decision_id: str,
) -> dict[str, object]:
    """Inspect the full supersession chain for a Decision.

    Returns the history on success, or an error dict on failure.
    """
    service = InspectDecisionHistoryService(repository=default_context.decision_repo)
    history = service.history(space=space, decision_id=decision_id)

    if not history:
        return {
            "error": f"No Decision found for '{decision_id}' "
            f"in MemorySpace '{space}'."
        }

    return {
        "decision_id": decision_id,
        "history": [
            {
                "decision_id": d.id,
                "statement": d.statement,
                "lifecycle_state": d.lifecycle_state,
                "validity_time": d.validity_time.isoformat(),
                "invalidation_time": (
                    d.invalidation_time.isoformat()
                    if d.invalidation_time
                    else None
                ),
                "supersedes": d.supersedes,
                "superseded_by": d.superseded_by,
            }
            for d in history
        ],
    }


def inspect_provenance_tool(
    space: str,
    entity_id: str,
) -> dict[str, object]:
    """Inspect provenance for a remembered Entity.

    Returns provenance details on success, or an error dict on failure.
    """
    inspector = InspectProvenanceService(repository=default_context.entity_repo)
    provenance = inspector.inspect(space=space, entity_id=entity_id)

    if provenance is None:
        return {
            "error": f"No provenance found for '{entity_id}' "
            f"in MemorySpace '{space}'."
        }

    return {
        "entity_id": provenance.entity_id,
        "source": provenance.source_id,
        "episode": provenance.episode_id,
        "writer": provenance.writer,
        "reason": provenance.reason,
        "creation_time": provenance.creation_time.isoformat(),
        "validity_time": provenance.validity_time.isoformat(),
    }


def remember_task_tool(
    space: str,
    task_id: str,
    title: str,
    source: str,
    at: str,
    writer: str = "agent:memorable",
    reason: str = "",
) -> dict[str, object]:
    """Remember a Task with provenance in a MemorySpace.

    Returns a dict with task and provenance info on success,
    or an error dict on failure.
    """
    try:
        profile = default_context.load_profile(space)
    except ProfileValidationError as e:
        return {"error": str(e)}

    service = RememberTaskService(
        repository=default_context.task_repo, profile=profile
    )

    timestamp = parse_iso_timestamp(at)

    try:
        result = service.remember(
            space=space,
            task_id=task_id,
            title=title,
            source_id=source,
            at=timestamp,
            writer=writer,
            reason=reason,
        )
    except ValueError as e:
        return {"error": str(e)}

    return {
        "task_id": result.task.id,
        "title": result.task.title,
        "space": result.task.space,
        "lifecycle_state": result.task.lifecycle_state,
        "source": result.provenance.source_id,
        "episode": result.provenance.episode_id,
        "creation_time": result.provenance.creation_time.isoformat(),
        "validity_time": result.provenance.validity_time.isoformat(),
    }


def complete_task_tool(
    space: str,
    task_id: str,
    at: str,
    source: str = "",
    writer: str = "agent:memorable",
    reason: str = "",
) -> dict[str, object]:
    """Complete a Task in a MemorySpace.

    Returns a dict with completion info on success,
    or an error dict on failure.
    """
    service = CompleteTaskService(repository=default_context.task_repo)

    timestamp = parse_iso_timestamp(at)

    try:
        result = service.complete(
            space=space,
            task_id=task_id,
            at=timestamp,
        )
    except ValueError as e:
        return {"error": str(e)}

    return {
        "task_id": result.task.id,
        "lifecycle_state": result.task.lifecycle_state,
        "event_id": result.event_id,
        "completion_time": result.completion_time.isoformat(),
    }


def search_memory_tool(
    space: str,
    query: str,
    mode: str = "current",
    as_of: str | None = None,
) -> dict[str, object]:
    """Search memory using hybrid GraphRAG retrieval.

    Combines semantic similarity, graph expansion, temporal filtering,
    and provenance-aware explanation.

    Args:
        space: MemorySpace to search
        query: Natural language query
        mode: "current" for Current Truth, "as-of" for Point-In-Time Truth
        as_of: ISO timestamp, required when mode is "as-of"
    """
    service = default_context.build_retrieval_service()

    as_of_dt = None
    if as_of is not None:
        as_of_dt = parse_iso_timestamp(as_of)

    results = service.search(
        space=space,
        query=query,
        mode=mode,
        as_of=as_of_dt,
    )

    return {
        "query": query,
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


def inspect_task_tool(
    space: str,
    task_id: str,
    as_of: str | None = None,
) -> dict[str, object]:
    """Inspect task lifecycle at current time or as-of a point in time.

    Returns task details on success, or an error dict on failure.
    """
    service = InspectTaskService(repository=default_context.task_repo)

    as_of_dt = None
    if as_of is not None:
        as_of_dt = parse_iso_timestamp(as_of)

    task = service.inspect(space=space, task_id=task_id, as_of=as_of_dt)

    if task is None:
        return {
            "error": f"No Task found for '{task_id}' "
            f"in MemorySpace '{space}'."
        }

    return {
        "task_id": task.id,
        "title": task.title,
        "space": task.space,
        "lifecycle_state": task.lifecycle_state,
        "validity_time": task.validity_time.isoformat(),
        "completion_time": (
            task.completion_time.isoformat()
            if task.completion_time
            else None
        ),
        "completion_event_id": task.completion_event_id,
    }
