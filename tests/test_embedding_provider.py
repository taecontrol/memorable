"""Tests for embedding providers and the build_embedding_provider() factory.

Covers:
- OpenRouterEmbeddingProvider unit behavior (protocol, embed, normalization).
- Factory dispatches by EmbeddingSettings.provider to the correct provider.
- Factory raises actionable errors for missing api_key or unknown provider.
- Default EmbeddingSettings never triggers remote calls.
- EmbeddingRecord preserves provider metadata.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
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


class _StubEmbeddingsEndpoint:
    def __init__(
        self,
        embedding: list[float] | None,
        data: list[SimpleNamespace] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._data = (
            data if data is not None else [SimpleNamespace(embedding=embedding)]
        )
        self._error = error
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return SimpleNamespace(data=self._data)


class _StubOpenAIClient:
    def __init__(
        self,
        embedding: list[float] | None = None,
        data: list[SimpleNamespace] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.embeddings = _StubEmbeddingsEndpoint(embedding, data, error)


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

    def test_embed_sends_float_encoding_with_injected_client(self) -> None:
        """embed() requests float Embeddings through the injected client."""
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        client = _StubOpenAIClient(embedding=_normalized_vector(3))
        provider = OpenRouterEmbeddingProvider(
            api_key="test-key",
            model="custom/model-v1",
            dimensions=3,
            client=client,
        )

        provider.embed("hello world")

        assert client.embeddings.calls[0]["encoding_format"] == "float"

    def test_embed_raises_domain_error_when_embedding_is_null(self) -> None:
        """embed() fails loud when the Embedding Provider returns no Embedding."""
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        client = _StubOpenAIClient(embedding=None)
        provider = OpenRouterEmbeddingProvider(
            api_key="test-key",
            model="custom/model-v1",
            dimensions=3,
            client=client,
        )

        with pytest.raises(RuntimeError) as exc_info:
            provider.embed("hello world")

        message = str(exc_info.value)
        assert "Embedding Provider 'openrouter'" in message
        assert "custom/model-v1" in message
        assert "returned no Embedding" in message
        assert "google/gemini-embedding-001" in message

    def test_embed_raises_domain_error_when_response_has_no_data(self) -> None:
        """embed() fails loud when the Embedding Provider returns no data."""
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        client = _StubOpenAIClient(data=[])
        provider = OpenRouterEmbeddingProvider(
            api_key="test-key",
            model="custom/model-v1",
            dimensions=3,
            client=client,
        )

        with pytest.raises(RuntimeError) as exc_info:
            provider.embed("hello world")

        message = str(exc_info.value)
        assert "Embedding Provider 'openrouter'" in message
        assert "custom/model-v1" in message
        assert "returned no Embedding" in message

    def test_embed_wraps_sdk_no_embedding_error(self) -> None:
        """embed() translates the SDK's missing Embedding error to domain language."""
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        client = _StubOpenAIClient(error=ValueError("No embedding data received"))
        provider = OpenRouterEmbeddingProvider(
            api_key="test-key",
            model="custom/model-v1",
            dimensions=3,
            client=client,
        )

        with pytest.raises(RuntimeError) as exc_info:
            provider.embed("hello world")

        message = str(exc_info.value)
        assert "Embedding Provider 'openrouter'" in message
        assert "custom/model-v1" in message
        assert "returned no Embedding" in message
        assert "No embedding data received" not in message
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__suppress_context__ is True

    def test_embed_raises_domain_error_when_dimensions_mismatch(self) -> None:
        """embed() fails loud when returned Embedding dimensions are wrong."""
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        client = _StubOpenAIClient(embedding=[1.0, 2.0, 3.0, 4.0])
        provider = OpenRouterEmbeddingProvider(
            api_key="test-key",
            model="custom/model-v1",
            dimensions=3,
            client=client,
        )

        with pytest.raises(RuntimeError) as exc_info:
            provider.embed("hello world")

        message = str(exc_info.value)
        assert "Embedding Provider 'openrouter'" in message
        assert "custom/model-v1" in message
        assert "dimensions" in message
        assert "returned 4" in message
        assert "configured 3" in message
        assert "Set embeddings.dimensions" in message

    def test_embed_returns_normalized_vector_from_injected_client(self) -> None:
        """embed() returns a normalized Embedding with configured dimensions."""
        from memorable.retrieval.embeddings import OpenRouterEmbeddingProvider

        client = _StubOpenAIClient(embedding=[3.0, 4.0, 0.0])
        provider = OpenRouterEmbeddingProvider(
            api_key="test-key",
            model="custom/model-v1",
            dimensions=3,
            client=client,
        )

        result = provider.embed("hello world")

        assert result == pytest.approx([0.6, 0.8, 0.0])
        assert len(result) == 3

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
# 2. Provider factory tests
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

    def test_fastembed_provider_from_settings(self) -> None:
        """settings.provider == 'fastembed' returns FastembedEmbeddingProvider."""
        from memorable.config import EmbeddingSettings
        from memorable.retrieval.embeddings import (
            FastembedEmbeddingProvider,
            build_embedding_provider,
        )

        settings = EmbeddingSettings(provider="fastembed")
        provider = build_embedding_provider(settings)
        assert isinstance(provider, FastembedEmbeddingProvider)

    def test_openrouter_provider_from_settings_with_api_key(self) -> None:
        """openrouter + api_key returns OpenRouterEmbeddingProvider."""
        from memorable.config import EmbeddingSettings
        from memorable.retrieval.embeddings import (
            OpenRouterEmbeddingProvider,
            build_embedding_provider,
        )

        settings = EmbeddingSettings(
            provider="openrouter",
            model="google/gemini-embedding-2-preview",
            dimensions=768,
        )
        provider = build_embedding_provider(settings, api_key="sk-test-key")
        assert isinstance(provider, OpenRouterEmbeddingProvider)

    def test_openrouter_without_api_key_raises(self) -> None:
        """settings.provider == 'openrouter' without api_key raises actionable error."""
        from memorable.config import EmbeddingSettings
        from memorable.retrieval.embeddings import build_embedding_provider

        settings = EmbeddingSettings(provider="openrouter")

        with pytest.raises(RuntimeError, match="api_key is required"):
            build_embedding_provider(settings)

    def test_unknown_provider_raises_with_valid_names(self) -> None:
        """Unknown provider name raises ValueError listing valid providers."""
        from memorable.config import EmbeddingSettings
        from memorable.retrieval.embeddings import build_embedding_provider

        settings = EmbeddingSettings(provider="nonexistent")

        with pytest.raises(
            ValueError, match="Unknown embedding provider 'nonexistent'"
        ):
            build_embedding_provider(settings)

    def test_factory_passes_model_and_dimensions_to_fake(self) -> None:
        """Factory forwards settings.dimensions to FakeEmbeddingProvider."""
        from memorable.config import EmbeddingSettings
        from memorable.retrieval.embeddings import build_embedding_provider

        settings = EmbeddingSettings(provider="fake", dimensions=64)
        provider = build_embedding_provider(settings)

        vector = provider.embed("test")
        assert len(vector) == 64

    def test_factory_passes_model_and_dimensions_to_fastembed(self) -> None:
        """Factory forwards model and dimensions to FastembedEmbeddingProvider."""
        from memorable.config import EmbeddingSettings
        from memorable.retrieval.embeddings import (
            FastembedEmbeddingProvider,
            build_embedding_provider,
        )

        settings = EmbeddingSettings(
            provider="fastembed",
            model="BAAI/bge-base-en-v1.5",
            dimensions=768,
        )
        provider = build_embedding_provider(settings)

        assert isinstance(provider, FastembedEmbeddingProvider)
        assert provider.model_name == "BAAI/bge-base-en-v1.5"
        assert provider._dimensions == 768

    def test_factory_passes_model_and_dimensions_to_openrouter(self) -> None:
        """Factory forwards model and dimensions to OpenRouter."""
        from memorable.config import EmbeddingSettings
        from memorable.retrieval.embeddings import build_embedding_provider

        settings = EmbeddingSettings(
            provider="openrouter",
            model="custom/model-v2",
            dimensions=512,
        )
        provider = build_embedding_provider(settings, api_key="sk-test-key")

        assert provider.model_name == "custom/model-v2"
        assert provider.dimensions == 512


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
    def test_no_remote_calls_with_default_settings(
        self, mock_openai_cls: MagicMock
    ) -> None:
        """Default EmbeddingSettings uses fastembed, never OpenRouter."""
        from memorable.config import EmbeddingSettings
        from memorable.retrieval.embeddings import (
            FastembedEmbeddingProvider,
            build_embedding_provider,
        )

        settings = EmbeddingSettings()  # defaults to fastembed
        provider = build_embedding_provider(settings)

        assert isinstance(provider, FastembedEmbeddingProvider)
        # OpenAI client constructor should never have been called
        mock_openai_cls.assert_not_called()
