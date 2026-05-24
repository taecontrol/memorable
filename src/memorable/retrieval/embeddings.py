"""Embedding provider abstraction and deterministic fake for tests.

Embeddings are derived from Indexable Text. They are NOT canonical memory.
"""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Protocol, runtime_checkable


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
