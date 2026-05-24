from __future__ import annotations

from pathlib import Path

from memorable.core.application import InitService, build_status_payload
from memorable.core.profile import ProfileValidationError, load_profile_from_yaml
from memorable.core.repositories import make_memory_space_repository


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
