"""Application context shared by CLI and MCP adapters.

Provides a single place for profile loading/caching, entity repository
access, and the default profile YAML. Both adapters receive the same
context instance instead of constructing their own module-level singletons.
"""

from __future__ import annotations

from pathlib import Path

from memorable.core.ports import (
    DecisionRepository,
    EntityRepository,
    MemorySpaceRepository,
    ObservationRepository,
    RelationRepository,
    TaskRepository,
)
from memorable.core.profile import MemoryProfile, load_profile_from_yaml
from memorable.core.repositories import (
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

    Holds the entity repository and profile cache so that CLI and MCP
    adapters share the same instances within a process, and tests can
    get clean instances by constructing a fresh context.
    """

    def __init__(
        self,
        entity_repo: EntityRepository | None = None,
        decision_repo: DecisionRepository | None = None,
        task_repo: TaskRepository | None = None,
        observation_repo: ObservationRepository | None = None,
        relation_repo: RelationRepository | None = None,
        memory_space_repo: MemorySpaceRepository | None = None,
    ) -> None:
        self.entity_repo = entity_repo or InMemoryEntityRepository()
        self.decision_repo = decision_repo or InMemoryDecisionRepository()
        self.task_repo = task_repo or InMemoryTaskRepository()
        self.observation_repo = observation_repo or InMemoryObservationRepository()
        self.relation_repo = relation_repo or InMemoryRelationRepository()
        self.memory_space_repo = memory_space_repo or InMemoryMemorySpaceRepository()
        self._profiles: dict[str, MemoryProfile] = {}

    def load_profile(self, space: str) -> MemoryProfile:
        """Load and cache a MemoryProfile for the given space.

        Looks for ``.memorable/memory.yaml`` in the current working directory.
        Falls back to the built-in default profile when none is found.
        """
        if space in self._profiles:
            return self._profiles[space]

        profile_path = Path.cwd() / ".memorable" / "memory.yaml"
        if profile_path.exists():
            yaml_text = profile_path.read_text(encoding="utf-8")
        else:
            yaml_text = DEFAULT_PROFILE_YAML

        profile = load_profile_from_yaml(yaml_text)
        self._profiles[space] = profile
        return profile

    def build_retrieval_service(self):
        """Build a HybridRetrievalService wired to this context's repos.

        Uses FakeEmbeddingProvider by default. Use build_embedding_provider()
        to select a real provider via environment configuration.
        """
        from memorable.retrieval.embeddings import (
            FakeEmbeddingProvider,
        )
        from memorable.retrieval.service import (
            HybridRetrievalService,
        )

        provider = FakeEmbeddingProvider(dimensions=32)
        return HybridRetrievalService(
            entity_repo=self.entity_repo,
            decision_repo=self.decision_repo,
            task_repo=self.task_repo,
            embedding_provider=provider,
            observation_repo=self.observation_repo,
            relation_repo=self.relation_repo,
        )

    def reset(self) -> None:
        """Clear all cached state. Useful for test isolation."""
        self.entity_repo = InMemoryEntityRepository()
        self.decision_repo = InMemoryDecisionRepository()
        self.task_repo = InMemoryTaskRepository()
        self.observation_repo = InMemoryObservationRepository()
        self.relation_repo = InMemoryRelationRepository()
        self.memory_space_repo = InMemoryMemorySpaceRepository()
        self._profiles.clear()


# Process-wide default context. Both CLI and MCP import this.
# Tests that need isolation should construct their own ApplicationContext.
default_context = ApplicationContext()
