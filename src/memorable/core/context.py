"""Application context shared by CLI and MCP adapters.

Provides a single place for live profile loading, repository access, and the
default profile YAML. Both adapters receive the same context instance instead
of constructing their own module-level singletons.

The MemoryProfile is never cached: ``load_profile`` re-reads and re-validates
``.memorable/memory.yaml`` (or the built-in default) on every call, so each
operation sees the profile as it is on disk right now (ADR-0016, Live
MemoryProfile Resolution amendment).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from memorable.core.ports import (
    AboutRepository,
    DecisionRepository,
    EntityRepository,
    MemorySpaceRepository,
    ObservationRepository,
    RelationRepository,
    TaskRepository,
)
from memorable.core.profile import (
    MemoryProfile,
    ProfileValidationError,
    load_profile_from_yaml,
)
from memorable.core.repositories import (
    InMemoryAboutRepository,
    InMemoryDecisionRepository,
    InMemoryEntityRepository,
    InMemoryMemorySpaceRepository,
    InMemoryObservationRepository,
    InMemoryRelationRepository,
    InMemoryTaskRepository,
)

# Default profile YAML used when no .memorable/memory.yaml is found.
# This supports the tracer fixture and tests that call remember/inspect
# without setting up a filesystem profile.
DEFAULT_PROFILE_YAML = """\
version: 1
space:
  name: memorable
  description: Default memory space
entities:
  - name: Project
  - name: Component
relations:
  - name: depends-on
  - name: owns
records:
  - name: ArchitectureDecision
    extends: Decision
  - name: FollowUp
    extends: Task
  - name: GeneralObservation
    extends: Observation
"""


class ApplicationContext:
    """Shared application-level state for adapter processes.

    Holds repositories so that CLI and MCP adapters share the same instances
    within a process, and tests can get clean instances by constructing a fresh
    context. The MemoryProfile is deliberately not held here: it is resolved
    live on every ``load_profile`` call rather than cached.
    """

    def __init__(
        self,
        entity_repo: EntityRepository | None = None,
        decision_repo: DecisionRepository | None = None,
        task_repo: TaskRepository | None = None,
        observation_repo: ObservationRepository | None = None,
        relation_repo: RelationRepository | None = None,
        about_repo: AboutRepository | None = None,
        memory_space_repo: MemorySpaceRepository | None = None,
    ) -> None:
        self.entity_repo = entity_repo or InMemoryEntityRepository()
        self.decision_repo = decision_repo or InMemoryDecisionRepository()
        self.task_repo = task_repo or InMemoryTaskRepository()
        self.observation_repo = observation_repo or InMemoryObservationRepository()
        self.relation_repo = relation_repo or InMemoryRelationRepository()
        self.about_repo = about_repo or InMemoryAboutRepository()
        self.memory_space_repo = memory_space_repo or InMemoryMemorySpaceRepository()

    def load_profile(self) -> MemoryProfile:
        """Resolve the MemoryProfile live from the current working directory.

        Reads and validates ``.memorable/memory.yaml`` fresh on every call,
        falling back to the built-in default profile when no file is found.
        Resolution is purely cwd-based; there is no per-space cache and no
        per-space reconciliation (ADR-0016, Live MemoryProfile Resolution).

        Raises:
            ProfileValidationError: When the profile is malformed YAML or fails
                MemoryProfile validation. Surfacing this on every call is the
                fail-loud, self-correction signal the amendment relies on.
        """
        profile_path = Path.cwd() / ".memorable" / "memory.yaml"
        if profile_path.exists():
            yaml_text = profile_path.read_text(encoding="utf-8")
        else:
            yaml_text = DEFAULT_PROFILE_YAML

        try:
            return load_profile_from_yaml(yaml_text)
        except yaml.YAMLError as e:
            raise ProfileValidationError(
                f"MemoryProfile at {profile_path} is not valid YAML: {e}"
            ) from e

    def reset(self) -> None:
        """Replace every repository with a fresh, empty instance.

        Used for test isolation. There is no cached profile to clear; only the
        repositories are reset.
        """
        self.entity_repo = InMemoryEntityRepository()
        self.decision_repo = InMemoryDecisionRepository()
        self.task_repo = InMemoryTaskRepository()
        self.observation_repo = InMemoryObservationRepository()
        self.relation_repo = InMemoryRelationRepository()
        self.about_repo = InMemoryAboutRepository()
        self.memory_space_repo = InMemoryMemorySpaceRepository()


# Process-wide default context. Both CLI and MCP import this.
# Tests that need isolation should construct their own ApplicationContext.
default_context = ApplicationContext()
