"""Embedding provider abstraction and deterministic fake for tests.

Embeddings are derived from Indexable Text. They are NOT canonical memory.
"""

from __future__ import annotations

import hashlib
import math
import os
import struct
from typing import Protocol, runtime_checkable

from openai import OpenAI


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Port for creating Embeddings from Indexable Text."""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def embed(self, text: str) -> list[float]: ...


class FakeEmbeddingProvider:
    """Deterministic embedding provider for tests.

    Uses SHA-256 hash of the input text to seed a stable vector.
    Same text always produces the same vector, across instances and runs.
    Vectors are L2-normalized for cosine similarity.
    """

    def __init__(self, dimensions: int = 32) -> None:
        self._dimensions = dimensions

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "hash-based"

    def embed(self, text: str) -> list[float]:
        # Hash the text to get deterministic bytes
        digest = hashlib.sha256(text.encode("utf-8")).digest()

        # Extend the digest if we need more dimensions than 8
        # (SHA-256 gives 32 bytes = 8 floats via 4-byte packing)
        raw_bytes = digest
        while len(raw_bytes) < self._dimensions * 4:
            raw_bytes += hashlib.sha256(raw_bytes).digest()

        # Unpack bytes into floats
        raw_floats = []
        for i in range(self._dimensions):
            chunk = raw_bytes[i * 4 : (i + 1) * 4]
            # Convert 4 bytes to unsigned int, then to float in [-1, 1]
            value = struct.unpack(">I", chunk)[0]
            raw_floats.append((value / (2**32 - 1)) * 2.0 - 1.0)

        # L2-normalize
        magnitude = math.sqrt(sum(v * v for v in raw_floats))
        if magnitude > 0:
            return [v / magnitude for v in raw_floats]
        return raw_floats


class OpenRouterEmbeddingProvider:
    """Embedding provider backed by OpenRouter's OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str,
        model: str = "google/gemini-embedding-2-preview",
        dimensions: int = 768,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self._client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )

    @property
    def provider_name(self) -> str:
        return "openrouter"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, text: str) -> list[float]:
        response = self._client.embeddings.create(
            model=self._model,
            input=text,
            dimensions=self._dimensions,
        )
        raw = response.data[0].embedding
        magnitude = math.sqrt(sum(v * v for v in raw))
        if magnitude > 0:
            return [v / magnitude for v in raw]
        return raw

    @classmethod
    def from_env(cls) -> OpenRouterEmbeddingProvider:
        api_key = os.environ.get("MEMORABLE_OPENROUTER_API_KEY")
        if not api_key:
            msg = (
                "MEMORABLE_OPENROUTER_API_KEY environment variable is required "
                "for the OpenRouter embedding provider. "
                "Set it to your OpenRouter API key."
            )
            raise RuntimeError(msg)

        model = os.environ.get(
            "MEMORABLE_EMBEDDING_MODEL",
            "google/gemini-embedding-2-preview",
        )
        dimensions = int(os.environ.get("MEMORABLE_EMBEDDING_DIMENSIONS", "768"))
        return cls(api_key=api_key, model=model, dimensions=dimensions)


def build_embedding_provider() -> EmbeddingProvider:
    """Build an embedding provider from environment configuration."""
    provider_name = os.environ.get("MEMORABLE_EMBEDDING_PROVIDER", "")
    if provider_name == "fake":
        return FakeEmbeddingProvider()

    api_key = os.environ.get("MEMORABLE_OPENROUTER_API_KEY")
    if api_key:
        return OpenRouterEmbeddingProvider.from_env()

    return FakeEmbeddingProvider()
