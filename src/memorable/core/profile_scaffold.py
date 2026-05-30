"""Pure Minimal MemoryProfile scaffold rendering."""

from __future__ import annotations


def render_minimal_profile_scaffold(
    space_name: str, *, description: str | None = None, version: int = 1
) -> str:
    """Return Minimal MemoryProfile scaffold YAML without filesystem access."""
    space_description = description or ""
    return f"""version: {version}

space:
  name: {_quote_yaml_string(space_name)}
  description: {_quote_yaml_string(space_description)}

entities: []
# Add Entity types when the MemorySpace needs stable named things.
# Example:
# entities:
#   - name: Person

relations: []
# Add Relation types when Entities need typed connections.
# Example:
# relations:
#   - name: supports

records: []
# Add project-specific MemoryRecord types by extending a kernel type.
# Example:
# records:
#   - name: ProjectDecision
#     extends: Decision
"""


def _quote_yaml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'
