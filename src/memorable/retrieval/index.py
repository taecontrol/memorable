"""In-memory embedding index for semantic search.

Stores EmbeddingRecords and searches by cosine similarity,
scoped to a MemorySpace.
"""

from __future__ import annotations

import math
from typing import Protocol

from memorable.retrieval.models import EmbeddingRecord, SearchCandidate


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class RetrievalIndex(Protocol):
    """Port for persistent derived Embedding search."""

    def store(self, record: EmbeddingRecord) -> None: ...

    def clear_space(self, space: str) -> None: ...

    def delete(self, *, space: str, source_id: str, source_kind: str) -> None: ...

    def records(self, *, space: str | None = None) -> list[EmbeddingRecord]: ...

    def search(
        self,
        space: str,
        query_vector: list[float],
        top_k: int = 10,
        *,
        provider_name: str | None = None,
        model_name: str | None = None,
        dimensions: int | None = None,
    ) -> list[SearchCandidate]: ...


class InMemoryEmbeddingIndex:
    """In-memory vector store that supports cosine similarity search."""

    def __init__(self) -> None:
        self._records: list[EmbeddingRecord] = []

    def store(self, record: EmbeddingRecord) -> None:
        """Add or replace an Embedding record in the index."""
        self._records = [
            existing
            for existing in self._records
            if not (
                existing.space == record.space
                and existing.source_id == record.source_id
                and existing.source_kind == record.source_kind
                and existing.provider_name == record.provider_name
                and existing.model_name == record.model_name
                and existing.dimensions == record.dimensions
            )
        ]
        self._records.append(record)

    def clear_space(self, space: str) -> None:
        """Remove all derived Embeddings for a MemorySpace."""
        self._records = [record for record in self._records if record.space != space]

    def delete(self, *, space: str, source_id: str, source_kind: str) -> None:
        """Remove derived Embeddings for one source item."""
        self._records = [
            record
            for record in self._records
            if not (
                record.space == space
                and record.source_id == source_id
                and record.source_kind == source_kind
            )
        ]

    def records(self, *, space: str | None = None) -> list[EmbeddingRecord]:
        """Return stored Embeddings, optionally scoped to one MemorySpace."""
        if space is None:
            return list(self._records)
        return [record for record in self._records if record.space == space]

    def search(
        self,
        space: str,
        query_vector: list[float],
        top_k: int = 10,
        *,
        provider_name: str | None = None,
        model_name: str | None = None,
        dimensions: int | None = None,
    ) -> list[SearchCandidate]:
        """Find the top-k most similar records in the given space.

        Returns SearchCandidate list ordered by similarity descending.
        """
        scored = []
        for record in self._records:
            if record.space != space:
                continue
            if provider_name is not None and record.provider_name != provider_name:
                continue
            if model_name is not None and record.model_name != model_name:
                continue
            if dimensions is not None and record.dimensions != dimensions:
                continue
            if len(record.vector) != len(query_vector):
                continue
            score = _cosine_similarity(query_vector, record.vector)
            scored.append(
                SearchCandidate(
                    source_id=record.source_id,
                    source_kind=record.source_kind,
                    score=score,
                )
            )

        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:top_k]
