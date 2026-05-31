from __future__ import annotations

from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP

from memorable.config import load_runtime_config
from memorable.core.application import (
    CompleteTaskService,
    CorrectService,
    CurrentTruthService,
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
from memorable.core.ports import TemporalRecordRepository
from memorable.core.profile import (
    ProfileValidationError,
    load_profile_from_yaml,
    profile_summary,
)
from memorable.core.temporal import parse_iso_timestamp
from memorable.runtime.doctor import DiagnosticResult, run_diagnostics

mcp_server = FastMCP("memorable")

# Module-level context used by all MCP tool functions.
# Defaults to the in-memory default_context. The MCP entry point
# replaces this with a production context on startup via set_mcp_context().
_context: ApplicationContext = default_context


def set_mcp_context(ctx: ApplicationContext) -> None:
    """Replace the module-level context used by all MCP tools.

    Called by the MCP entry point after building the production context.
    """
    global _context  # noqa: PLW0603
    _context = ctx


def _resolve_repository(
    record_type: str,
) -> TemporalRecordRepository | dict[str, object]:
    """Map a record_type string to the corresponding TemporalRecordRepository.

    Returns the repository on success, or an error dict on failure.
    Adding a new record type requires only updating this helper.
    """
    repos = {
        "decision": lambda: _context.decision_repo,
        "observation": lambda: _context.observation_repo,
        "relation": lambda: _context.relation_repo,
    }
    accessor = repos.get(record_type)
    if accessor is not None:
        return accessor()
    return {
        "error": f"Unknown record_type '{record_type}'. "
        f"Supported types: decision, observation, relation."
    }


@mcp_server.tool(
    name="memorable_status",
    description=(
        "Return Memorable service diagnostics for the current MemorySpace scope."
    ),
)
def status_tool() -> dict[str, object]:
    return build_status_payload()


@mcp_server.tool(
    name="memorable_doctor",
    description=(
        "Run Memorable runtime health diagnostics for the current MemorySpace. "
        "status reports current runtime state; doctor diagnoses problems and "
        "returns remediation hints."
    ),
)
def doctor_tool() -> list[DiagnosticResult]:
    config = load_runtime_config(include_environment_overrides=True)
    return run_diagnostics(config)


@mcp_server.tool(
    name="memorable_init_space",
    description=(
        "Initialize a MemorySpace from a project's MemoryProfile "
        "(.memorable/memory.yaml). Returns space info or an error."
    ),
)
def init_space_tool(base_path: str) -> dict[str, object]:
    """Initialize a MemorySpace from a project's .memorable/memory.yaml.

    Returns a dict with space info on success, or an error dict on failure.
    """
    profile_path = Path(base_path) / ".memorable" / "memory.yaml"

    if not profile_path.exists():
        return {
            "error": f"No memory.yaml found at {profile_path}. "
            "Create a .memorable/memory.yaml with `memorable init` as the "
            "Human Owner, or edit .memorable/memory.yaml to evolve an "
            "existing MemoryProfile."
        }

    yaml_text = profile_path.read_text(encoding="utf-8")

    service = InitService(repository=_context.memory_space_repo)

    try:
        result = service.initialize(yaml_text)
    except ProfileValidationError as e:
        return {"error": str(e)}

    return {
        "space": result.space.name,
        "status": "already exists" if result.already_existed else "initialized",
        "profile_version": result.profile.version,
    }


@mcp_server.tool(
    name="memorable_inspect_space",
    description=(
        "Inspect a project's MemoryProfile without initializing the MemorySpace. "
        "Returns Entity types, Relation types, and MemoryRecord types."
    ),
)
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

    return profile_summary(profile)


@mcp_server.tool(
    name="memorable_remember_entity",
    description=(
        "Remember an Entity with Provenance in a MemorySpace. "
        "Records the Source, Episode, Validity Time, and writer."
    ),
)
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
        profile = _context.load_profile(space)
    except ProfileValidationError as e:
        return {"error": str(e)}

    service = RememberEntityService(repository=_context.entity_repo, profile=profile)

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
        "record_id": result.provenance.record_id,
        "record_kind": result.provenance.record_kind,
        "source": result.provenance.source_id,
        "episode": result.provenance.episode_id,
        "creation_time": result.provenance.creation_time.isoformat(),
        "validity_time": result.provenance.validity_time.isoformat(),
    }


@mcp_server.tool(
    name="memorable_remember_decision",
    description=(
        "Remember a Decision with Provenance in a MemorySpace. "
        "Supports Supersession to replace an earlier Decision."
    ),
)
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
        profile = _context.load_profile(space)
    except ProfileValidationError as e:
        return {"error": str(e)}

    service = RememberDecisionService(
        repository=_context.decision_repo, profile=profile
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
        "record_id": result.provenance.record_id,
        "record_kind": result.provenance.record_kind,
        "source": result.provenance.source_id,
        "episode": result.provenance.episode_id,
        "creation_time": result.provenance.creation_time.isoformat(),
        "validity_time": result.provenance.validity_time.isoformat(),
        "lifecycle_state": result.decision.lifecycle_state,
    }


@mcp_server.tool(
    name="memorable_remember_observation",
    description=(
        "Remember an Observation with Provenance in a MemorySpace. "
        "Supports Supersession to replace an earlier Observation."
    ),
)
def remember_observation_tool(
    space: str,
    observation_id: str,
    statement: str,
    source: str,
    at: str,
    supersedes: str | None = None,
    writer: str = "agent:memorable",
    reason: str = "",
) -> dict[str, object]:
    """Remember an Observation with provenance in a MemorySpace.

    Returns a dict with observation and provenance info on success,
    or an error dict on failure.
    """
    try:
        profile = _context.load_profile(space)
    except ProfileValidationError as e:
        return {"error": str(e)}

    service = RememberObservationService(
        repository=_context.observation_repo, profile=profile
    )

    timestamp = parse_iso_timestamp(at)

    try:
        result = service.remember(
            space=space,
            observation_id=observation_id,
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
        "observation_id": result.observation.id,
        "statement": result.observation.statement,
        "space": result.observation.space,
        "record_id": result.provenance.record_id,
        "record_kind": result.provenance.record_kind,
        "source": result.provenance.source_id,
        "episode": result.provenance.episode_id,
        "creation_time": result.provenance.creation_time.isoformat(),
        "validity_time": result.provenance.validity_time.isoformat(),
        "lifecycle_state": result.observation.lifecycle_state,
    }


@mcp_server.tool(
    name="memorable_remember_relation",
    description=(
        "Remember a Relation with Provenance in a MemorySpace. "
        "A Relation is a directed, temporal connection between two Entities. "
        "Supports Supersession to replace an earlier Relation."
    ),
)
def remember_relation_tool(
    space: str,
    relation_id: str,
    source_entity_id: str,
    target_entity_id: str,
    relation_type: str,
    statement: str,
    source: str,
    at: str,
    supersedes: str | None = None,
    writer: str = "agent:memorable",
    reason: str = "",
) -> dict[str, object]:
    """Remember a Relation with provenance in a MemorySpace.

    Returns a dict with relation and provenance info on success,
    or an error dict on failure.
    """
    try:
        profile = _context.load_profile(space)
    except ProfileValidationError as e:
        return {"error": str(e)}

    service = RememberRelationService(
        relation_repo=_context.relation_repo,
        entity_repo=_context.entity_repo,
        profile=profile,
    )

    timestamp = parse_iso_timestamp(at)

    try:
        result = service.remember(
            space=space,
            relation_id=relation_id,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relation_type=relation_type,
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
    }


@mcp_server.tool(
    name="memorable_current_truth",
    description=(
        "Get the Current Truth for a temporal record by following its "
        "Supersession chain. Accepts record_type to select the repository "
        "(decision, observation, relation). Returns the active record or an error."
    ),
)
def current_truth_tool(
    space: str,
    record_id: str,
    record_type: str = "decision",
) -> dict[str, object]:
    """Get the current truth for a temporal record, following supersession chain.

    Args:
        space: MemorySpace to search in.
        record_id: ID of the record to resolve.
        record_type: Type of record ("decision" or "observation").

    Returns record details on success, or an error dict on failure.
    """
    resolved = _resolve_repository(record_type)
    if isinstance(resolved, dict):
        return resolved

    service = CurrentTruthService(repository=resolved)
    record = service.current(space=space, record_id=record_id)

    if record is None:
        label = record_type.capitalize()
        return {
            "error": f"No {label} found for '{record_id}' in MemorySpace '{space}'."
        }

    return {
        "record_id": record.id,
        "statement": record.statement,
        "space": record.space,
        "lifecycle_state": record.lifecycle_state,
        "validity_time": record.validity_time.isoformat(),
    }


@mcp_server.tool(
    name="memorable_point_in_time_truth",
    description=(
        "Get the Point-In-Time Truth for a temporal record at a specific "
        "timestamp. Accepts record_type to select the repository "
        "(decision, observation, relation). Returns the record that was "
        "valid at that time."
    ),
)
def point_in_time_truth_tool(
    space: str,
    record_id: str,
    at: str,
    record_type: str = "decision",
) -> dict[str, object]:
    """Get the temporal record that was valid at a specific point in time.

    Args:
        space: MemorySpace to search in.
        record_id: ID of the record to resolve.
        at: ISO timestamp for the point-in-time query.
        record_type: Type of record ("decision" or "observation").

    Returns record details on success, or an error dict on failure.
    """
    resolved = _resolve_repository(record_type)
    if isinstance(resolved, dict):
        return resolved

    service = PointInTimeTruthService(repository=resolved)
    timestamp = parse_iso_timestamp(at)
    record = service.at(space=space, record_id=record_id, at=timestamp)

    if record is None:
        label = record_type.capitalize()
        return {
            "error": f"No {label} found for '{record_id}' "
            f"in MemorySpace '{space}' at {timestamp.isoformat()}."
        }

    return {
        "record_id": record.id,
        "statement": record.statement,
        "space": record.space,
        "lifecycle_state": record.lifecycle_state,
        "validity_time": record.validity_time.isoformat(),
    }


@mcp_server.tool(
    name="memorable_inspect_history",
    description=(
        "Inspect the full Supersession chain for a temporal record. "
        "Accepts a record_type to select the repository "
        "(decision, observation, relation). Returns Lifecycle State, "
        "Validity Time, and Invalidation Time for each version."
    ),
)
def inspect_history_tool(
    space: str,
    record_id: str,
    record_type: str = "decision",
) -> dict[str, object]:
    """Inspect the full supersession chain for a temporal record.

    Args:
        space: MemorySpace to search in.
        record_id: ID of the record to inspect.
        record_type: Type of record ("decision" initially).

    Returns the history on success, or an error dict on failure.
    """
    resolved = _resolve_repository(record_type)
    if isinstance(resolved, dict):
        return resolved

    service = InspectHistoryService(repository=resolved)
    history = service.history(space=space, record_id=record_id)

    if not history:
        return {"error": f"No record found for '{record_id}' in MemorySpace '{space}'."}

    return {
        "record_id": record_id,
        "record_type": record_type,
        "history": [
            {
                "record_id": r.id,
                "statement": r.statement,
                "lifecycle_state": r.lifecycle_state,
                "validity_time": r.validity_time.isoformat(),
                "invalidation_time": (
                    r.invalidation_time.isoformat() if r.invalidation_time else None
                ),
                "supersedes": r.supersedes,
                "superseded_by": r.superseded_by,
            }
            for r in history
        ],
    }


@mcp_server.tool(
    name="memorable_inspect_provenance",
    description=(
        "Inspect Provenance for a remembered Entity. "
        "Returns Source, Episode, writer, reason, Creation Time, and Validity Time."
    ),
)
def inspect_provenance_tool(
    space: str,
    entity_id: str,
) -> dict[str, object]:
    """Inspect provenance for a remembered Entity.

    Returns provenance details on success, or an error dict on failure.
    """
    inspector = InspectProvenanceService(repository=_context.entity_repo)
    provenance = inspector.inspect(space=space, entity_id=entity_id)

    if provenance is None:
        return {
            "error": f"No provenance found for '{entity_id}' in MemorySpace '{space}'."
        }

    return {
        "record_id": provenance.record_id,
        "record_kind": provenance.record_kind,
        "source": provenance.source_id,
        "episode": provenance.episode_id,
        "writer": provenance.writer,
        "reason": provenance.reason,
        "creation_time": provenance.creation_time.isoformat(),
        "validity_time": provenance.validity_time.isoformat(),
    }


@mcp_server.tool(
    name="memorable_remember_task",
    description=(
        "Remember a Task with Provenance in a MemorySpace. "
        "Tasks have a Lifecycle State and support completion transitions."
    ),
)
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
        profile = _context.load_profile(space)
    except ProfileValidationError as e:
        return {"error": str(e)}

    service = RememberTaskService(repository=_context.task_repo, profile=profile)

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
        "record_id": result.provenance.record_id,
        "record_kind": result.provenance.record_kind,
        "source": result.provenance.source_id,
        "episode": result.provenance.episode_id,
        "creation_time": result.provenance.creation_time.isoformat(),
        "validity_time": result.provenance.validity_time.isoformat(),
    }


@mcp_server.tool(
    name="memorable_complete_task",
    description=(
        "Complete a Task in a MemorySpace. "
        "Records the Lifecycle State transition and completion Event."
    ),
)
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
    service = CompleteTaskService(repository=_context.task_repo)

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


@mcp_server.tool(
    name="memorable_search_memory",
    description=(
        "Search memory using Hybrid Retrieval (GraphRAG). "
        "Combines semantic similarity, graph expansion, "
        "temporal filtering, and Provenance-aware explanation. "
        "Supports Current Truth and Point-In-Time Truth modes."
    ),
)
def search_memory_tool(
    space: str,
    query: str,
    mode: Literal["current", "as-of"] = "current",
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
    from memorable.retrieval.embeddings import build_embedding_provider
    from memorable.retrieval.service import build_retrieval_service

    config = load_runtime_config(include_environment_overrides=True)
    try:
        provider = build_embedding_provider(
            config.embeddings, api_key=config.embeddings.api_key
        )
    except (RuntimeError, ValueError) as e:
        return {"error": str(e)}
    service = build_retrieval_service(_context, provider)

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


@mcp_server.tool(
    name="memorable_inspect_task",
    description=(
        "Inspect a Task's Lifecycle State at the current time "
        "or as-of a Point-In-Time. "
        "Returns Task details including completion Event."
    ),
)
def inspect_task_tool(
    space: str,
    task_id: str,
    as_of: str | None = None,
) -> dict[str, object]:
    """Inspect task lifecycle at current time or as-of a point in time.

    Returns task details on success, or an error dict on failure.
    """
    service = InspectTaskService(repository=_context.task_repo)

    as_of_dt = None
    if as_of is not None:
        as_of_dt = parse_iso_timestamp(as_of)

    task = service.inspect(space=space, task_id=task_id, as_of=as_of_dt)

    if task is None:
        return {"error": f"No Task found for '{task_id}' in MemorySpace '{space}'."}

    return {
        "task_id": task.id,
        "title": task.title,
        "space": task.space,
        "lifecycle_state": task.lifecycle_state,
        "validity_time": task.validity_time.isoformat(),
        "completion_time": (
            task.completion_time.isoformat() if task.completion_time else None
        ),
        "completion_event_id": task.completion_event_id,
    }


@mcp_server.tool(
    name="memorable_list_records",
    description=(
        "Memory Review: deterministically list MemoryRecords in a MemorySpace. "
        "Fans across Decision, Observation, Relation, and Task records "
        "(Entities are excluded) and returns a compact projection "
        "{id, type, label, lifecycle_state, creation_time} ordered by "
        "Creation Time, capped by limit (default 50). Pass type to restrict to "
        "a single record type ('decision', 'observation', 'relation', 'task'); "
        "omit it to list every type. 'entity' is not valid. Pass state to "
        "restrict to a single Lifecycle State ('open', 'current', 'completed', "
        "'superseded', 'invalidated'); omit it to list any state. Pass since "
        "and/or until (ISO timestamps) to bound Provenance Creation Time as a "
        "half-open window [since, until): since is inclusive, until is "
        "exclusive; either may be omitted. All filters combine with AND. Use "
        "this to answer state questions like 'what is open?', 'what decisions "
        "did we make today?', or 'what did we do this week?'."
    ),
)
def list_records_tool(
    space: str,
    type: str | None = None,
    state: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
) -> dict[str, object]:
    """List MemoryRecords in a MemorySpace as a Memory Review projection.

    When ``type`` is given, only records of that MemoryRecord type are listed;
    omit it to list every type. When ``state`` is given, only records whose
    Lifecycle State matches are listed; omit it to list any state. ``since`` and
    ``until`` (ISO timestamps) bound Provenance Creation Time as a half-open
    window ``[since, until)`` — ``since`` inclusive, ``until`` exclusive; either
    may be omitted. All filters combine with AND. Returns a dict with a
    ``records`` list on success, or an error dict (e.g. an unknown ``type`` or
    ``entity``).
    """
    service = ListRecordsService(
        decision_repo=_context.decision_repo,
        observation_repo=_context.observation_repo,
        relation_repo=_context.relation_repo,
        task_repo=_context.task_repo,
    )

    since_dt = parse_iso_timestamp(since) if since is not None else None
    until_dt = parse_iso_timestamp(until) if until is not None else None

    try:
        projections = service.list_records(
            space=space,
            type=type,
            state=state,
            since=since_dt,
            until=until_dt,
            limit=limit,
        )
    except ValueError as e:
        # Bad caller input, e.g. an unlistable type ('entity' or unknown).
        return {"error": str(e)}
    except ProvenanceIntegrityError as e:
        # Store invariant violation: a listed record's Provenance join is
        # missing. Surface as an error dict rather than letting it escape to
        # the MCP caller, but keep it distinct from caller-input errors.
        return {"error": str(e)}

    return {
        "space": space,
        "records": [
            {
                "id": projection.id,
                "type": projection.type,
                "label": projection.label,
                "lifecycle_state": projection.lifecycle_state,
                "creation_time": projection.creation_time.isoformat(),
            }
            for projection in projections
        ],
    }


@mcp_server.tool(
    name="memorable_invalidate",
    description=(
        "Mark a temporal record as invalidated in a MemorySpace. "
        "Invalidation means a claim stopped being true without a successor. "
        "Sets Lifecycle State to invalidated and records Invalidation Time. "
        "Accepts record_type to select the repository "
        "(decision, observation, relation)."
    ),
)
def invalidate_tool(
    space: str,
    record_id: str,
    record_type: str,
    at: str,
) -> dict[str, object]:
    """Mark a temporal record as invalidated.

    Args:
        space: MemorySpace containing the record.
        record_id: ID of the record to invalidate.
        record_type: Type of record ("decision" or "observation").
        at: ISO timestamp when the claim stopped being true.

    Returns a dict with invalidation info on success, or an error dict.
    """
    resolved = _resolve_repository(record_type)
    if isinstance(resolved, dict):
        return resolved

    service = InvalidateService(repository=resolved)
    timestamp = parse_iso_timestamp(at)

    try:
        result = service.invalidate(
            space=space,
            record_id=record_id,
            at=timestamp,
        )
    except ValueError as e:
        return {"error": str(e)}

    return {
        "record_id": result.record_id,
        "space": result.space,
        "lifecycle_state": result.lifecycle_state,
        "invalidation_time": result.invalidation_time.isoformat(),
    }


@mcp_server.tool(
    name="memorable_correct",
    description=(
        "Correct a temporal record's statement in place in a MemorySpace. "
        "Correction means the old statement was never true — it was a mistake. "
        "Updates the statement and replaces Provenance with Correction source. "
        "Accepts record_type to select the repository "
        "(decision, observation, relation)."
    ),
)
def correct_tool(
    space: str,
    record_id: str,
    record_type: str,
    new_statement: str,
    source: str,
    at: str,
    reason: str = "",
    writer: str = "agent:memorable",
) -> dict[str, object]:
    """Correct a temporal record's statement in place.

    Args:
        space: MemorySpace containing the record.
        record_id: ID of the record to correct.
        record_type: Type of record ("decision" or "observation").
        new_statement: The corrected statement.
        source: Source ID for the correction provenance.
        at: ISO timestamp for the correction.
        reason: Optional reason for the correction.
        writer: Identity of the agent or user making the correction.

    Returns a dict with correction info on success, or an error dict.
    """
    resolved = _resolve_repository(record_type)
    if isinstance(resolved, dict):
        return resolved

    service = CorrectService(repository=resolved)
    timestamp = parse_iso_timestamp(at)

    try:
        result = service.correct(
            space=space,
            record_id=record_id,
            new_statement=new_statement,
            record_kind=record_type,
            source=source,
            writer=writer,
            at=timestamp,
            reason=reason,
        )
    except ValueError as e:
        return {"error": str(e)}

    return {
        "record_id": result.record_id,
        "space": result.space,
        "old_statement": result.old_statement,
        "new_statement": result.new_statement,
    }
