"""Tests for the standalone build_retrieval_service factory function.

Covers issue #70: extract build_retrieval_service() from ApplicationContext
into a standalone function in the retrieval module.
"""

from __future__ import annotations


class TestBuildRetrievalServiceFactory:
    """Standalone factory wires context repos and embedding provider."""

    def test_returns_service_wired_to_context_repos_and_provider(self) -> None:
        """build_retrieval_service returns a HybridRetrievalService with
        the context's repos and the provided embedding provider."""
        from memorable.core.context import ApplicationContext
        from memorable.retrieval.embeddings import FakeEmbeddingProvider
        from memorable.retrieval.service import (
            HybridRetrievalService,
            build_retrieval_service,
        )

        ctx = ApplicationContext()
        provider = FakeEmbeddingProvider(dimensions=32)
        service = build_retrieval_service(ctx, provider)

        assert isinstance(service, HybridRetrievalService)
        assert service._entity_repo is ctx.entity_repo
        assert service._decision_repo is ctx.decision_repo
        assert service._task_repo is ctx.task_repo
        assert service._observation_repo is ctx.observation_repo
        assert service._relation_repo is ctx.relation_repo
        assert service._about_repo is ctx.about_repo
        assert service._embedding_provider is provider

    def test_application_context_has_no_build_retrieval_service(self) -> None:
        """ApplicationContext no longer owns build_retrieval_service."""
        from memorable.core.context import ApplicationContext

        assert not hasattr(ApplicationContext, "build_retrieval_service")
