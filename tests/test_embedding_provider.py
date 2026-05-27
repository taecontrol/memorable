"""Tests for real embedding provider (OpenRouter) and provider factory.

Covers slice #10 acceptance criteria:
- Remote embedding providers are never used unless explicitly configured.
- Runtime config is separate from .memorable/memory.yaml (env vars only).
- Embedded items preserve provider, model, dimensions, and creation time.
- Missing provider configuration produces actionable diagnostics.
- The runnable tracer bullet can use the real provider path when configured.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest

# =====================================================================
# Helpers
# =====================================================================


def _normalized_vector(dimensions: int) -> list[float]:
    """Return a deterministic L2-normalized vector for mocking."""
    raw = [float(i + 1) for i in range(dimensions)]
    magnitude = math.sqrt(sum(v * v for v in raw))
    return [v / magnitude for v in raw]


# =====================================================================
# 1. OpenRouterEmbeddingProvider unit tests
# =====================================================================


class TestOpenRouterEmbeddingProvider:
    """OpenRouterEmbeddingProvider wraps the OpenAI SDK for OpenRouter."""

    def test_conforms_to_embedding_provider_protocol(self) -> None:
        """OpenRouterEmbeddingProvider satisfies the EmbeddingProvider protocol."""
        from memorable.retrieval.embeddings import (
            EmbeddingProvider,
            OpenRouterEmbeddingProvider,
        )

        provider = OpenRouterEmbeddingProvider(api_key="test-key")
        assert isinstance(provider, EmbeddingProvider)

    def test_provider_name_is_openrouter(self) -> None:
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        provider = OpenRouterEmbeddingProvider(api_key="test-key")
        assert provider.provider_name == "openrouter"

    def test_model_name_matches_configured(self) -> None:
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        provider = OpenRouterEmbeddingProvider(
            api_key="test-key",
            model="custom/model-v1",
        )
        assert provider.model_name == "custom/model-v1"

    def test_default_model_is_gemini_embedding(self) -> None:
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        provider = OpenRouterEmbeddingProvider(api_key="test-key")
        assert provider.model_name == "google/gemini-embedding-2-preview"

    def test_default_dimensions_is_768(self) -> None:
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        provider = OpenRouterEmbeddingProvider(api_key="test-key")
        assert provider.dimensions == 768

    @patch("memorable.retrieval.embeddings.OpenAI")
    def test_embed_returns_vector_of_correct_dimensions(
        self, mock_openai_cls: MagicMock
    ) -> None:
        """embed() returns a list[float] of the configured dimensions."""
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        dims = 768
        expected_vector = _normalized_vector(dims)

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_embedding = MagicMock()
        mock_embedding.embedding = expected_vector
        mock_response = MagicMock()
        mock_response.data = [mock_embedding]
        mock_client.embeddings.create.return_value = mock_response

        provider = OpenRouterEmbeddingProvider(api_key="test-key", dimensions=dims)
        result = provider.embed("test text")

        assert isinstance(result, list)
        assert len(result) == dims
        assert all(isinstance(v, float) for v in result)

    @patch("memorable.retrieval.embeddings.OpenAI")
    def test_embed_calls_openai_embeddings_api(
        self, mock_openai_cls: MagicMock
    ) -> None:
        """embed() delegates to openai client embeddings.create with correct model."""
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_embedding = MagicMock()
        mock_embedding.embedding = _normalized_vector(768)
        mock_response = MagicMock()
        mock_response.data = [mock_embedding]
        mock_client.embeddings.create.return_value = mock_response

        provider = OpenRouterEmbeddingProvider(api_key="test-key")
        provider.embed("hello world")

        mock_client.embeddings.create.assert_called_once()
        call_kwargs = mock_client.embeddings.create.call_args
        # Verify the model parameter was passed correctly
        passed_model = call_kwargs.kwargs.get("model") or (
            call_kwargs[1].get("model") if len(call_kwargs) > 1 else None
        )
        assert passed_model == "google/gemini-embedding-2-preview"

    @patch("memorable.retrieval.embeddings.OpenAI")
    def test_vectors_are_normalized(self, mock_openai_cls: MagicMock) -> None:
        """Returned vectors are L2-normalized."""
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        dims = 768
        # Return an unnormalized vector from the API mock
        raw_vector = [float(i + 1) for i in range(dims)]

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_embedding = MagicMock()
        mock_embedding.embedding = raw_vector
        mock_response = MagicMock()
        mock_response.data = [mock_embedding]
        mock_client.embeddings.create.return_value = mock_response

        provider = OpenRouterEmbeddingProvider(api_key="test-key", dimensions=dims)
        result = provider.embed("normalize me")

        magnitude = math.sqrt(sum(v * v for v in result))
        assert abs(magnitude - 1.0) < 1e-6


# =====================================================================
# 2. Provider configuration tests
# =====================================================================


class TestProviderConfiguration:
    """Env var configuration for the embedding provider."""

    def test_missing_api_key_raises_configuration_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing API key raises a clear error."""
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        monkeypatch.delenv("MEMORABLE_OPENROUTER_API_KEY", raising=False)

        with pytest.raises(Exception, match="MEMORABLE_OPENROUTER_API_KEY"):
            OpenRouterEmbeddingProvider.from_env()

    def test_api_key_from_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Provider reads API key from MEMORABLE_OPENROUTER_API_KEY."""
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        monkeypatch.setenv("MEMORABLE_OPENROUTER_API_KEY", "sk-test-123")
        monkeypatch.delenv("MEMORABLE_EMBEDDING_MODEL", raising=False)
        monkeypatch.delenv("MEMORABLE_EMBEDDING_DIMENSIONS", raising=False)

        provider = OpenRouterEmbeddingProvider.from_env()
        # The provider should have been created successfully with the key
        assert provider.provider_name == "openrouter"

    def test_custom_model_from_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MEMORABLE_EMBEDDING_MODEL overrides default model."""
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        monkeypatch.setenv("MEMORABLE_OPENROUTER_API_KEY", "sk-test-123")
        monkeypatch.setenv("MEMORABLE_EMBEDDING_MODEL", "openai/text-embedding-3-small")
        monkeypatch.delenv("MEMORABLE_EMBEDDING_DIMENSIONS", raising=False)

        provider = OpenRouterEmbeddingProvider.from_env()
        assert provider.model_name == "openai/text-embedding-3-small"

    def test_custom_dimensions_from_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MEMORABLE_EMBEDDING_DIMENSIONS overrides default dimensions."""
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        monkeypatch.setenv("MEMORABLE_OPENROUTER_API_KEY", "sk-test-123")
        monkeypatch.setenv("MEMORABLE_EMBEDDING_DIMENSIONS", "1536")
        monkeypatch.delenv("MEMORABLE_EMBEDDING_MODEL", raising=False)

        provider = OpenRouterEmbeddingProvider.from_env()
        assert provider.dimensions == 1536


# =====================================================================
# 3. Provider factory tests
# =====================================================================


class TestProviderFactory:
    """Factory function builds the right provider from EmbeddingSettings."""

    def test_fake_provider_from_settings(self) -> None:
        """settings.provider == 'fake' returns FakeEmbeddingProvider."""
        from memorable.config import EmbeddingSettings
        from memorable.retrieval.embeddings import (
            FakeEmbeddingProvider,
            build_embedding_provider,
        )

        settings = EmbeddingSettings(provider="fake")
        provider = build_embedding_provider(settings)
        assert isinstance(provider, FakeEmbeddingProvider)


# =====================================================================
# 4. Embedding metadata preservation tests
# =====================================================================


class TestEmbeddingMetadata:
    """EmbeddingRecord preserves provider and model metadata."""

    def test_embedding_record_preserves_provider_name(self) -> None:
        """EmbeddingRecord stores provider_name from the provider."""
        from memorable.retrieval.embeddings import FakeEmbeddingProvider
        from memorable.retrieval.models import EmbeddingRecord

        provider = FakeEmbeddingProvider(dimensions=32)
        vector = provider.embed("test")

        record = EmbeddingRecord(
            source_id="entity:test",
            source_kind="Entity",
            space="memorable",
            indexable_text="test",
            vector=vector,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            dimensions=32,
        )

        assert record.provider_name == "fake"

    def test_embedding_record_preserves_model_name(self) -> None:
        """EmbeddingRecord stores model_name from the provider."""
        from memorable.retrieval.embeddings import FakeEmbeddingProvider
        from memorable.retrieval.models import EmbeddingRecord

        provider = FakeEmbeddingProvider(dimensions=32)
        vector = provider.embed("test")

        record = EmbeddingRecord(
            source_id="entity:test",
            source_kind="Entity",
            space="memorable",
            indexable_text="test",
            vector=vector,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            dimensions=32,
        )

        assert record.model_name == "hash-based"

    def test_embedding_record_preserves_dimensions(self) -> None:
        """Dimensions field matches vector length."""
        from memorable.retrieval.embeddings import FakeEmbeddingProvider
        from memorable.retrieval.models import EmbeddingRecord

        provider = FakeEmbeddingProvider(dimensions=64)
        vector = provider.embed("test")

        record = EmbeddingRecord(
            source_id="entity:test",
            source_kind="Entity",
            space="memorable",
            indexable_text="test",
            vector=vector,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            dimensions=64,
        )

        assert record.dimensions == len(vector)
        assert record.dimensions == 64


# =====================================================================
# 5. Safety: no accidental remote use
# =====================================================================


class TestNoAccidentalRemoteUse:
    """Remote providers are never used unless explicitly configured."""

    def test_default_context_uses_fake_provider(self) -> None:
        """build_retrieval_service with FakeEmbeddingProvider wires fake by default."""
        from memorable.core.context import ApplicationContext
        from memorable.retrieval.embeddings import FakeEmbeddingProvider
        from memorable.retrieval.service import build_retrieval_service

        ctx = ApplicationContext()
        provider = FakeEmbeddingProvider(dimensions=32)
        service = build_retrieval_service(ctx, provider)

        # The service's embedding provider should be FakeEmbeddingProvider
        assert isinstance(service._embedding_provider, FakeEmbeddingProvider)

    @patch("memorable.retrieval.embeddings.OpenAI")
    def test_no_remote_calls_without_explicit_config(
        self, mock_openai_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without env vars, no HTTP calls are made during embedding."""
        from memorable.retrieval.embeddings import build_embedding_provider

        monkeypatch.delenv("MEMORABLE_OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("MEMORABLE_EMBEDDING_PROVIDER", raising=False)

        provider = build_embedding_provider()
        provider.embed("should not call OpenAI")

        # OpenAI client constructor should never have been called
        mock_openai_cls.assert_not_called()
