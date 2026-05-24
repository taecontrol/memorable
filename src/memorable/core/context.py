"""Application context shared by CLI and MCP adapters.

Provides a single place for profile loading/caching, entity repository
access, and the default profile YAML. Both adapters receive the same
context instance instead of constructing their own module-level singletons.
"""

from __future__ import annotations

from pathlib import Path

from memorable.core.profile import MemoryProfile, load_profile_from_yaml
from memorable.core.repositories import (
    InMemoryDecisionRepository,
    InMemoryEntityRepository,
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
records:
  - name: ArchitectureDecision
    extends: Decision
  - name: FollowUp
    extends: Task
"""


class ApplicationContext:
    """Shared application-level state for adapter processes.

    Holds the entity repository and profile cache so that CLI and MCP
    adapters share the same instances within a process, and tests can
    get clean instances by constructing a fresh context.
    """

    def __init__(
        self,
        entity_repo: InMemoryEntityRepository | None = None,
        decision_repo: InMemoryDecisionRepository | None = None,
        task_repo: InMemoryTaskRepository | None = None,
    ) -> None:
        self.entity_repo = entity_repo or InMemoryEntityRepository()
        self.decision_repo = decision_repo or InMemoryDecisionRepository()
        self.task_repo = task_repo or InMemoryTaskRepository()
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

        Uses FakeEmbeddingProvider for the tracer bullet. A production
        system would accept an EmbeddingProvider parameter.
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
        )

    def reset(self) -> None:
        """Clear all cached state. Useful for test isolation."""
        self.entity_repo = InMemoryEntityRepository()
        self.decision_repo = InMemoryDecisionRepository()
        self.task_repo = InMemoryTaskRepository()
        self._profiles.clear()


# Process-wide default context. Both CLI and MCP import this.
# Tests that need isolation should construct their own ApplicationContext.
default_context = ApplicationContext()
