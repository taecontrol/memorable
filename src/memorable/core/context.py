"""Application context shared by CLI and MCP adapters.

Provides a single place for live profile loading, repository access, and the
default profile YAML. Both adapters receive the same context instance instead
of constructing their own module-level singletons.
"""

from __future__ import annotations

from pathlib import Path

from memorable.core.ports import (
    AboutRepository,
    DecisionRepository,
    EntityRepository,
    MemorySpaceRepository,
    ObservationRepository,
    RelationRepository,
    TaskRepository,
)
from memorable.core.profile import MemoryProfile, load_profile_from_yaml
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
    context.
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

    def load_profile(self, space: str) -> MemoryProfile:
        """Load a MemoryProfile for the given space.

        Looks for ``.memorable/memory.yaml`` in the current working directory.
        Falls back to the built-in default profile when none is found.
        """
        profile_path = Path.cwd() / ".memorable" / "memory.yaml"
        if profile_path.exists():
            yaml_text = profile_path.read_text(encoding="utf-8")
        else:
            yaml_text = DEFAULT_PROFILE_YAML

        return load_profile_from_yaml(yaml_text)

    def reset(self) -> None:
        """Clear all cached state. Useful for test isolation."""
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
