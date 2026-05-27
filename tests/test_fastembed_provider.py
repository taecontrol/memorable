"""Tests for FastembedEmbeddingProvider — local embedding via fastembed.

Covers slice #69 acceptance criteria:
- FastembedEmbeddingProvider implements the EmbeddingProvider protocol.
- provider_name returns "fastembed".
- model_name returns the configured model name.
- embed(text) returns list[float] of the correct dimensions.
- Returned vectors are L2-normalized.
- Same text produces the same vector (deterministic).
- Different text produces different vectors.
"""

from __future__ import annotations


class TestFastembedProtocolConformance:
    """FastembedEmbeddingProvider satisfies the EmbeddingProvider protocol."""

    def test_conforms_to_embedding_provider_protocol(self) -> None:
        from memorable.retrieval.embeddings import (
            EmbeddingProvider,
            FastembedEmbeddingProvider,
        )

        provider = FastembedEmbeddingProvider()
        assert isinstance(provider, EmbeddingProvider)

    def test_provider_name_is_fastembed(self) -> None:
        from memorable.retrieval.embeddings import FastembedEmbeddingProvider

        provider = FastembedEmbeddingProvider()
        assert provider.provider_name == "fastembed"


class TestFastembedModelConfiguration:
    """FastembedEmbeddingProvider reports its configured model."""

    def test_default_model_name(self) -> None:
        from memorable.retrieval.embeddings import FastembedEmbeddingProvider

        provider = FastembedEmbeddingProvider()
        assert provider.model_name == "BAAI/bge-small-en-v1.5"

    def test_custom_model_name(self) -> None:
        from memorable.retrieval.embeddings import FastembedEmbeddingProvider

        provider = FastembedEmbeddingProvider(model="BAAI/bge-base-en-v1.5")
        assert provider.model_name == "BAAI/bge-base-en-v1.5"


class TestFastembedEmbed:
    """FastembedEmbeddingProvider.embed() returns real semantic vectors."""

    def test_embed_returns_list_of_floats(self) -> None:
        from memorable.retrieval.embeddings import FastembedEmbeddingProvider

        provider = FastembedEmbeddingProvider()
        result = provider.embed("test text for embedding")

        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)

    def test_embed_returns_correct_dimensions(self) -> None:
        from memorable.retrieval.embeddings import FastembedEmbeddingProvider

        provider = FastembedEmbeddingProvider()  # default 384 dims
        result = provider.embed("test text for embedding")

        assert len(result) == 384

    def test_vectors_are_l2_normalized(self) -> None:
        import math

        from memorable.retrieval.embeddings import FastembedEmbeddingProvider

        provider = FastembedEmbeddingProvider()
        result = provider.embed("normalize this text")

        magnitude = math.sqrt(sum(v * v for v in result))
        assert abs(magnitude - 1.0) < 1e-6

    def test_same_text_produces_same_vector(self) -> None:
        from memorable.retrieval.embeddings import FastembedEmbeddingProvider

        provider = FastembedEmbeddingProvider()
        text = "determinism matters for retrieval"

        result_a = provider.embed(text)
        result_b = provider.embed(text)

        assert result_a == result_b

    def test_different_text_produces_different_vectors(self) -> None:
        from memorable.retrieval.embeddings import FastembedEmbeddingProvider

        provider = FastembedEmbeddingProvider()

        vec_a = provider.embed("the cat sat on the mat")
        vec_b = provider.embed("quantum mechanics describes particle behavior")

        assert vec_a != vec_b
